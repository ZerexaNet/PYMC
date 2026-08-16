import struct

from world._native_binary import _is_compatible_elf, _is_compatible_macho


def _write_elf(path, machine):
    header = bytearray(20)
    header[0:4] = b"\x7fELF"
    header[4] = 2       # ELFCLASS64
    header[5] = 1       # ELFDATA2LSB
    header[6] = 1       # EV_CURRENT
    header[16:18] = struct.pack("<H", 2)  # ET_EXEC
    struct.pack_into("<H", header, 18, machine)
    path.write_bytes(header)


def test_elf_validation_rejects_wrong_arch(tmp_path, monkeypatch):
    x86_64 = tmp_path / "x86_64"
    arm64 = tmp_path / "arm64"
    _write_elf(x86_64, 62)    # EM_X86_64
    _write_elf(arm64, 183)    # EM_AARCH64

    monkeypatch.setattr("world._native_binary._normalized_machine", lambda: "x86_64")
    assert _is_compatible_elf(x86_64)
    assert not _is_compatible_elf(arm64)

    monkeypatch.setattr("world._native_binary._normalized_machine", lambda: "arm64")
    assert not _is_compatible_elf(x86_64)
    assert _is_compatible_elf(arm64)


def test_macho_validation_rejects_wrong_arch(tmp_path, monkeypatch):
    arm64_macho = tmp_path / "arm64_macho"
    x86_64_macho = tmp_path / "x86_64_macho"
    fat_macho = tmp_path / "fat_macho"

    # MH_CIGAM_64 (little-endian 64-bit Mach-O), cpu_type = CPU_TYPE_ARM64.
    arm64_macho.write_bytes(b"\xcf\xfa\xed\xfe" + struct.pack("<I", 0x0100000C))
    # MH_CIGAM_64 with cpu_type = CPU_TYPE_X86_64.
    x86_64_macho.write_bytes(b"\xcf\xfa\xed\xfe" + struct.pack("<I", 0x01000007))
    # FAT_MAGIC_64 universal binary.
    fat_macho.write_bytes(b"\xca\xfe\xba\xbf\x00\x00\x00\x00")

    monkeypatch.setattr("world._native_binary._normalized_machine", lambda: "arm64")
    assert _is_compatible_macho(arm64_macho)
    assert not _is_compatible_macho(x86_64_macho)
    assert _is_compatible_macho(fat_macho)

    monkeypatch.setattr("world._native_binary._normalized_machine", lambda: "x86_64")
    assert not _is_compatible_macho(arm64_macho)
    assert _is_compatible_macho(x86_64_macho)
    assert _is_compatible_macho(fat_macho)
