// ============================================================
// PyMC - Shared Memory IPC Layer
// Lock-free ring buffer over POSIX shared memory (Linux)
// or CreateFileMapping (Windows) for zero-copy Python<->C++ IPC
//
// Architecture:
//   - Two ring buffers per channel: one for commands (Python->C++),
//     one for responses (C++->Python)
//   - Each message is length-prefixed: [uint32_t len][payload...]
//   - Lock-free via atomic read/write positions with proper
//     memory ordering (acquire/release semantics)
//   - Cache-line aligned positions to avoid false sharing
// ============================================================

#ifndef PYMC_IPC_SHM_H
#define PYMC_IPC_SHM_H

#include <atomic>
#include <cstddef>
#include <cstdint>
#include <memory>
#include <string>

#ifdef _WIN32
// Prevent windows.h from defining min/max macros that conflict with
// std::min / std::max (MSVC error C2589).
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#else
#include <sys/mman.h>
#include <sys/stat.h>
#include <fcntl.h>
#include <unistd.h>
#include <cerrno>
#include <cstring>
#endif

namespace pymc {

// -----------------------------------------------------------
// Ring buffer header — lives at the start of the shared region
// -----------------------------------------------------------
struct RingBufferHeader {
    // Cache-line aligned to prevent false sharing between
    // the producer (write_pos) and consumer (read_pos).
    alignas(64) std::atomic<uint32_t> write_pos;   // next slot to write
    alignas(64) std::atomic<uint32_t> read_pos;    // next slot to read
    uint32_t capacity;     // total buffer capacity in bytes (must be power of 2)
    uint32_t mask;         // capacity - 1, for fast modulo
    // data[] follows immediately after this header
};

// -----------------------------------------------------------
// SharedMemoryIPC — manages a single shared memory region
// containing a lock-free SPSC ring buffer.
//
// Usage pattern:
//   Python side: create=true, writes commands, reads responses
//   C++ side:   create=false, reads commands, writes responses
//
// For bidirectional communication, create TWO SharedMemoryIPC
// instances (one per direction) sharing the same SHM name
// with different suffixes.
// -----------------------------------------------------------
class SharedMemoryIPC {
public:
    // Create or open a shared memory ring buffer.
    //   name:   unique name for the shared memory object
    //   size:   total size including header (must be >= 4096, will be rounded to page)
    //   create: true = creator (Python side), false = opener (C++ side)
    SharedMemoryIPC(const char* name, size_t size, bool create);

    ~SharedMemoryIPC();

    // Non-copyable
    SharedMemoryIPC(const SharedMemoryIPC&) = delete;
    SharedMemoryIPC& operator=(const SharedMemoryIPC&) = delete;

    // ---- Write side (producer) ----

    // Write a message to the ring buffer.
    // Non-blocking: returns false if not enough space.
    // Message format: [4-byte little-endian length][payload]
    bool write(const void* data, size_t len);

    // Convenience: write raw bytes without length prefix.
    // Used when the consumer knows the expected size.
    bool write_raw(const void* data, size_t len);

    // ---- Read side (consumer) ----

    // Read the next message from the ring buffer.
    // Returns the number of payload bytes read, or 0 if empty/insufficient buffer.
    // The 4-byte length prefix is consumed automatically.
    size_t read(void* buffer, size_t max_len);

    // Read raw bytes (no length prefix).
    // Returns number of bytes actually read (may be < len if buffer empty).
    size_t read_raw(void* buffer, size_t len);

    // Peek at the next message length without consuming it.
    // Returns 0 if no complete message is available.
    uint32_t peek_message_len() const;

    // ---- Synchronization ----

    // Block until data is available or timeout expires.
    // Uses a lightweight spin-wait with exponential backoff.
    // Returns true if data is available, false on timeout.
    bool wait_for_data(int timeout_ms);

    // Check if there is at least one complete message available.
    bool has_message() const;

    // Get the number of bytes used in the ring buffer.
    uint32_t used_bytes() const;

    // Get the number of free bytes available for writing.
    uint32_t free_bytes() const;

    // ---- Status ----

    bool is_valid() const { return mapped_ != nullptr; }
    size_t total_size() const { return size_; }
    const char* name() const { return name_.c_str(); }

private:
    void init_ring_buffer();
    void cleanup();

    std::string name_;
    size_t size_;
    bool creator_;
    bool valid_;

#ifdef _WIN32
    HANDLE shm_handle_;
#else
    int fd_;
#endif

    void* mapped_;
    RingBufferHeader* ring_;
    uint8_t* data_;  // points to ring_->data[0]
};

// -----------------------------------------------------------
// IPCChannel — bidirectional channel using two ring buffers
//
// Two shared memory regions are created:
//   {name}_cmd  : Python writes commands, C++ reads them
//   {name}_resp : C++ writes responses, Python reads them
// -----------------------------------------------------------
class IPCChannel {
public:
    IPCChannel(const char* name, size_t cmd_size, size_t resp_size, bool create);
    ~IPCChannel();

    IPCChannel(const IPCChannel&) = delete;
    IPCChannel& operator=(const IPCChannel&) = delete;

    // Python side: send command, receive response
    bool send_command(const void* data, size_t len);
    size_t recv_response(void* buffer, size_t max_len);

    // C++ side: receive command, send response
    size_t recv_command(void* buffer, size_t max_len);
    bool send_response(const void* data, size_t len);

    // Wait for a command to arrive (C++ side) or response (Python side)
    bool wait_for_command(int timeout_ms);
    bool wait_for_response(int timeout_ms);

    bool is_valid() const;

    SharedMemoryIPC& cmd_channel() { return *cmd_; }
    SharedMemoryIPC& resp_channel() { return *resp_; }

private:
    std::unique_ptr<SharedMemoryIPC> cmd_;
    std::unique_ptr<SharedMemoryIPC> resp_;
};

}  // namespace pymc

#endif  // PYMC_IPC_SHM_H
