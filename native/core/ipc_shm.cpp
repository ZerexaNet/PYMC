// ============================================================
// PyMC - Shared Memory IPC Implementation
// Lock-free ring buffer over shared memory for zero-copy IPC
// ============================================================

#include "ipc_shm.h"

#include <algorithm>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <thread>
#include <system_error>

namespace pymc {

// -----------------------------------------------------------
// Helper: page-aligned size
// -----------------------------------------------------------
static size_t page_align(size_t sz) {
#ifdef _WIN32
    SYSTEM_INFO si;
    GetSystemInfo(&si);
    size_t page = si.dwPageSize;
#else
    long page = sysconf(_SC_PAGESIZE);
    if (page <= 0) page = 4096;
#endif
    return ((sz + static_cast<size_t>(page) - 1) / static_cast<size_t>(page))
           * static_cast<size_t>(page);
}

// -----------------------------------------------------------
// Helper: next power of 2
// -----------------------------------------------------------
static uint32_t next_pow2(uint32_t v) {
    v--;
    v |= v >> 1;
    v |= v >> 2;
    v |= v >> 4;
    v |= v >> 8;
    v |= v >> 16;
    v++;
    return v;
}

// ===========================================================
// SharedMemoryIPC implementation
// ===========================================================

SharedMemoryIPC::SharedMemoryIPC(const char* name, size_t size, bool create)
    : name_(name)
    , size_(page_align(std::max(size, static_cast<size_t>(4096))))
    , creator_(create)
    , valid_(false)
#ifdef _WIN32
    , shm_handle_(NULL)
#else
    , fd_(-1)
#endif
    , mapped_(nullptr)
    , ring_(nullptr)
    , data_(nullptr)
{
#ifdef _WIN32
    // Windows: CreateFileMapping / OpenFileMapping
    if (creator_) {
        shm_handle_ = CreateFileMappingA(
            INVALID_HANDLE_VALUE, NULL, PAGE_READWRITE,
            static_cast<DWORD>(size_ >> 32),
            static_cast<DWORD>(size_ & 0xFFFFFFFF),
            name);
    } else {
        shm_handle_ = OpenFileMappingA(FILE_MAP_ALL_ACCESS, FALSE, name);
    }

    if (!shm_handle_) {
        fprintf(stderr, "[PYMC IPC] CreateFileMapping/OpenFileMapping failed for '%s': %lu\n",
                name, GetLastError());
        return;
    }

    mapped_ = MapViewOfFile(shm_handle_, FILE_MAP_ALL_ACCESS, 0, 0, size_);
    if (!mapped_) {
        fprintf(stderr, "[PYMC IPC] MapViewOfFile failed for '%s': %lu\n",
                name, GetLastError());
        CloseHandle(shm_handle_);
        shm_handle_ = NULL;
        return;
    }
#else
    // Linux/POSIX: shm_open / mmap
    fd_ = shm_open(name, O_RDWR | (create ? O_CREAT : 0), 0666);
    if (fd_ < 0) {
        fprintf(stderr, "[PYMC IPC] shm_open failed for '%s': %s\n",
                name, strerror(errno));
        return;
    }

    if (create) {
        if (ftruncate(fd_, static_cast<off_t>(size_)) != 0) {
            fprintf(stderr, "[PYMC IPC] ftruncate failed for '%s': %s\n",
                    name, strerror(errno));
            ::close(fd_);
            fd_ = -1;
            return;
        }
    }

    mapped_ = mmap(nullptr, size_, PROT_READ | PROT_WRITE, MAP_SHARED, fd_, 0);
    if (mapped_ == MAP_FAILED) {
        fprintf(stderr, "[PYMC IPC] mmap failed for '%s': %s\n",
                name, strerror(errno));
        mapped_ = nullptr;
        ::close(fd_);
        fd_ = -1;
        return;
    }

    // On Linux we can close fd after mmap; the mapping stays valid.
    // But we keep it open for potential resizing later.
#endif

    ring_ = static_cast<RingBufferHeader*>(mapped_);
    data_ = reinterpret_cast<uint8_t*>(mapped_) + sizeof(RingBufferHeader);

    if (create) {
        init_ring_buffer();
    }

    valid_ = true;
}

SharedMemoryIPC::~SharedMemoryIPC() {
    cleanup();
}

void SharedMemoryIPC::init_ring_buffer() {
    // Compute usable capacity (everything after the header)
    uint32_t usable = static_cast<uint32_t>(size_ - sizeof(RingBufferHeader));
    // Round down to power of 2 for fast modulo
    uint32_t cap = next_pow2(usable);
    if (cap > usable) cap >>= 1;  // Don't exceed actual space
    if (cap < 64) cap = 64;       // Minimum useful size

    // Zero out the entire region first
    std::memset(mapped_, 0, size_);

    ring_->capacity = cap;
    ring_->mask = cap - 1;
    ring_->write_pos.store(0, std::memory_order_relaxed);
    ring_->read_pos.store(0, std::memory_order_relaxed);
}

void SharedMemoryIPC::cleanup() {
    if (mapped_) {
#ifdef _WIN32
        UnmapViewOfFile(mapped_);
        if (shm_handle_) {
            CloseHandle(shm_handle_);
            shm_handle_ = NULL;
        }
#else
        munmap(mapped_, size_);
        if (fd_ >= 0) {
            // If we're the creator, unlink the shared memory
            if (creator_) {
                shm_unlink(name_.c_str());
            }
            ::close(fd_);
            fd_ = -1;
        }
#endif
        mapped_ = nullptr;
        ring_ = nullptr;
        data_ = nullptr;
    }
    valid_ = false;
}

// ---- Write operations ----

bool SharedMemoryIPC::write(const void* data, size_t len) {
    // Message = [4-byte LE length][payload]
    size_t total = 4 + len;
    if (total > free_bytes()) return false;

    uint32_t wp = ring_->write_pos.load(std::memory_order_relaxed);
    uint32_t mask = ring_->mask;
    uint32_t cap = ring_->capacity;

    // Write length prefix (little-endian)
    uint32_t le_len = static_cast<uint32_t>(len);
    uint8_t len_bytes[4] = {
        static_cast<uint8_t>(le_len & 0xFF),
        static_cast<uint8_t>((le_len >> 8) & 0xFF),
        static_cast<uint8_t>((le_len >> 16) & 0xFF),
        static_cast<uint8_t>((le_len >> 24) & 0xFF),
    };

    // Write length prefix (may wrap)
    for (int i = 0; i < 4; i++) {
        data_[(wp + i) & mask] = len_bytes[i];
    }

    // Write payload (may wrap)
    const uint8_t* src = static_cast<const uint8_t*>(data);
    uint32_t start = (wp + 4) & mask;

    if (start + len <= cap) {
        // No wrap
        std::memcpy(data_ + start, src, len);
    } else {
        // Wraps around
        uint32_t first = cap - start;
        std::memcpy(data_ + start, src, first);
        std::memcpy(data_, src + first, len - first);
    }

    // Publish with release semantics so consumer sees the data
    ring_->write_pos.store((wp + static_cast<uint32_t>(total)) & mask,
                           std::memory_order_release);
    return true;
}

bool SharedMemoryIPC::write_raw(const void* data, size_t len) {
    if (len > free_bytes()) return false;

    uint32_t wp = ring_->write_pos.load(std::memory_order_relaxed);
    uint32_t mask = ring_->mask;
    uint32_t cap = ring_->capacity;

    const uint8_t* src = static_cast<const uint8_t*>(data);

    if (wp + len <= cap) {
        std::memcpy(data_ + wp, src, len);
    } else {
        uint32_t first = cap - wp;
        std::memcpy(data_ + wp, src, first);
        std::memcpy(data_, src + first, len - first);
    }

    ring_->write_pos.store((wp + static_cast<uint32_t>(len)) & mask,
                           std::memory_order_release);
    return true;
}

// ---- Read operations ----

size_t SharedMemoryIPC::read(void* buffer, size_t max_len) {
    if (!has_message()) return 0;

    uint32_t rp = ring_->read_pos.load(std::memory_order_relaxed);
    uint32_t mask = ring_->mask;
    uint32_t cap = ring_->capacity;

    // Read length prefix
    uint8_t len_bytes[4];
    for (int i = 0; i < 4; i++) {
        len_bytes[i] = data_[(rp + i) & mask];
    }
    uint32_t msg_len = static_cast<uint32_t>(len_bytes[0])
                     | (static_cast<uint32_t>(len_bytes[1]) << 8)
                     | (static_cast<uint32_t>(len_bytes[2]) << 16)
                     | (static_cast<uint32_t>(len_bytes[3]) << 24);

    if (msg_len > max_len) {
        // Buffer too small — still consume the message
        // Skip over it entirely
        uint32_t total = 4 + msg_len;
        ring_->read_pos.store((rp + total) & mask, std::memory_order_release);
        return 0;
    }

    // Read payload
    uint8_t* dst = static_cast<uint8_t*>(buffer);
    uint32_t start = (rp + 4) & mask;

    if (start + msg_len <= cap) {
        std::memcpy(dst, data_ + start, msg_len);
    } else {
        uint32_t first = cap - start;
        std::memcpy(dst, data_ + start, first);
        std::memcpy(dst + first, data_, msg_len - first);
    }

    uint32_t total = 4 + msg_len;
    ring_->read_pos.store((rp + total) & mask, std::memory_order_release);
    return msg_len;
}

size_t SharedMemoryIPC::read_raw(void* buffer, size_t len) {
    uint32_t avail = used_bytes();
    if (avail == 0) return 0;

    size_t to_read = std::min(len, static_cast<size_t>(avail));
    uint32_t rp = ring_->read_pos.load(std::memory_order_relaxed);
    uint32_t mask = ring_->mask;
    uint32_t cap = ring_->capacity;

    uint8_t* dst = static_cast<uint8_t*>(buffer);

    if (rp + to_read <= cap) {
        std::memcpy(dst, data_ + rp, to_read);
    } else {
        uint32_t first = cap - rp;
        std::memcpy(dst, data_ + rp, first);
        std::memcpy(dst + first, data_, to_read - first);
    }

    ring_->read_pos.store((rp + static_cast<uint32_t>(to_read)) & mask,
                          std::memory_order_release);
    return to_read;
}

uint32_t SharedMemoryIPC::peek_message_len() const {
    uint32_t wp = ring_->write_pos.load(std::memory_order_acquire);
    uint32_t rp = ring_->read_pos.load(std::memory_order_acquire);

    // Calculate available bytes
    uint32_t used = (wp >= rp) ? (wp - rp) : (ring_->capacity - rp + wp);
    if (used < 4) return 0;  // Not even a complete length prefix

    uint32_t mask = ring_->mask;
    uint8_t len_bytes[4];
    for (int i = 0; i < 4; i++) {
        len_bytes[i] = data_[(rp + i) & mask];
    }
    uint32_t msg_len = static_cast<uint32_t>(len_bytes[0])
                     | (static_cast<uint32_t>(len_bytes[1]) << 8)
                     | (static_cast<uint32_t>(len_bytes[2]) << 16)
                     | (static_cast<uint32_t>(len_bytes[3]) << 24);

    // Check if the full message payload is available
    if (used < 4 + msg_len) return 0;

    return msg_len;
}

// ---- Synchronization ----

bool SharedMemoryIPC::wait_for_data(int timeout_ms) {
    auto deadline = std::chrono::steady_clock::now()
                  + std::chrono::milliseconds(timeout_ms);

    // Spin phase: ~1000 iterations (~1-10 µs)
    for (int i = 0; i < 1000; i++) {
        if (used_bytes() > 0) return true;
    }

    // Yield phase: exponential backoff
    int sleep_us = 10;
    while (true) {
        if (used_bytes() > 0) return true;
        if (std::chrono::steady_clock::now() >= deadline) return false;

        std::this_thread::sleep_for(std::chrono::microseconds(sleep_us));
        sleep_us = std::min(sleep_us * 2, 1000);  // Cap at 1ms
    }
}

bool SharedMemoryIPC::has_message() const {
    uint32_t wp = ring_->write_pos.load(std::memory_order_acquire);
    uint32_t rp = ring_->read_pos.load(std::memory_order_acquire);
    uint32_t used = (wp >= rp) ? (wp - rp) : (ring_->capacity - rp + wp);

    if (used < 4) return false;  // No length prefix

    uint32_t mask = ring_->mask;
    uint8_t len_bytes[4];
    for (int i = 0; i < 4; i++) {
        len_bytes[i] = data_[(rp + i) & mask];
    }
    uint32_t msg_len = static_cast<uint32_t>(len_bytes[0])
                     | (static_cast<uint32_t>(len_bytes[1]) << 8)
                     | (static_cast<uint32_t>(len_bytes[2]) << 16)
                     | (static_cast<uint32_t>(len_bytes[3]) << 24);

    return used >= 4 + msg_len;
}

uint32_t SharedMemoryIPC::used_bytes() const {
    uint32_t wp = ring_->write_pos.load(std::memory_order_acquire);
    uint32_t rp = ring_->read_pos.load(std::memory_order_acquire);
    return (wp >= rp) ? (wp - rp) : (ring_->capacity - rp + wp);
}

uint32_t SharedMemoryIPC::free_bytes() const {
    uint32_t wp = ring_->write_pos.load(std::memory_order_acquire);
    uint32_t rp = ring_->read_pos.load(std::memory_order_acquire);
    uint32_t used = (wp >= rp) ? (wp - rp) : (ring_->capacity - rp + wp);
    return ring_->capacity - used - 1;  // -1 because full == empty in ring buffer
}

// ===========================================================
// IPCChannel implementation
// ===========================================================

IPCChannel::IPCChannel(const char* name, size_t cmd_size, size_t resp_size, bool create) {
    std::string cmd_name = std::string(name) + "_cmd";
    std::string resp_name = std::string(name) + "_resp";

    cmd_ = std::make_unique<SharedMemoryIPC>(cmd_name.c_str(), cmd_size, create);
    resp_ = std::make_unique<SharedMemoryIPC>(resp_name.c_str(), resp_size, create);
}

IPCChannel::~IPCChannel() = default;

bool IPCChannel::send_command(const void* data, size_t len) {
    return cmd_->write(data, len);
}

size_t IPCChannel::recv_response(void* buffer, size_t max_len) {
    return resp_->read(buffer, max_len);
}

size_t IPCChannel::recv_command(void* buffer, size_t max_len) {
    return cmd_->read(buffer, max_len);
}

bool IPCChannel::send_response(const void* data, size_t len) {
    return resp_->write(data, len);
}

bool IPCChannel::wait_for_command(int timeout_ms) {
    return cmd_->wait_for_data(timeout_ms);
}

bool IPCChannel::wait_for_response(int timeout_ms) {
    return resp_->wait_for_data(timeout_ms);
}

bool IPCChannel::is_valid() const {
    return cmd_ && cmd_->is_valid() && resp_ && resp_->is_valid();
}

}  // namespace pymc
