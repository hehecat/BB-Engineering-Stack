"""Deterministic, zero-execution binary header and container inspection.

Gives an agent immediate structural facts (ELF, PE/.NET, Mach-O/Universal, WASM)
and safe extraction for packaged application containers (Electron ASAR,
PyInstaller CArchive, ZIP/APK/IPA/JAR/AAR/VSIX) using only the Python standard
library, without MCP schema bloat or target execution.
"""

from __future__ import annotations

import hashlib
import json
import struct
import zipfile
import zlib
from pathlib import Path
from typing import Any

from .errors import ValidationError

DEFAULT_MAX_EXTRACT_BYTES = 128 * 1024 * 1024
DEFAULT_MAX_EXTRACT_FILES = 4000
MAX_MEMBER_LISTING = 200

_PYI_MAGIC = b"MEI\x0c\x0b\x0a\x0b\x0e"
_PYI_TAIL_SCAN = 4 * 1024 * 1024

_ELF_MACHINES = {
    0x03: "x86",
    0x08: "mips",
    0x28: "arm",
    0x3E: "x86_64",
    0xB7: "aarch64",
    0xF3: "riscv",
}
_ELF_TYPES = {1: "REL", 2: "EXEC", 3: "DYN", 4: "CORE"}

_PE_MACHINES = {
    0x014C: "x86",
    0x8664: "x86_64",
    0xAA64: "aarch64",
    0x01C4: "arm",
}
_PE_SUBSYSTEMS = {
    1: "native",
    2: "windows-gui",
    3: "windows-cui",
    9: "windows-ce-gui",
    10: "efi-application",
}

_MACHO_CPUS = {
    7: "x86",
    0x01000007: "x86_64",
    12: "arm",
    0x0100000C: "arm64",
    0x0200000C: "arm64_32",
}
_MACHO_FILETYPES = {
    1: "OBJECT",
    2: "EXECUTE",
    6: "DYLIB",
    8: "BUNDLE",
    11: "KEXT_BUNDLE",
}

_WASM_SECTIONS = {
    0: "custom",
    1: "type",
    2: "import",
    3: "function",
    4: "table",
    5: "memory",
    6: "global",
    7: "export",
    8: "start",
    9: "element",
    10: "code",
    11: "data",
    12: "data_count",
}

_APK_SIG_MAGIC = b"APK Sig Block 42"
_APK_SIG_SCHEMES = {
    0x7109871A: "v2",
    0xF05368C0: "v3",
    0x1B93AD61: "v3.1",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_relpath(raw: str, destination: Path) -> Path:
    cleaned = raw.replace("\\", "/").lstrip("/")
    if not cleaned:
        raise ValidationError(f"container member has an empty path: {raw!r}")
    rel = Path(cleaned)
    if rel.is_absolute() or ".." in rel.parts:
        raise ValidationError(f"container member escapes extraction root: {raw!r}")
    normalized = Path(*[part for part in rel.parts if part not in {"", "."}])
    if not normalized.parts:
        raise ValidationError(f"container member resolves to root: {raw!r}")
    target = (destination / normalized).resolve()
    base = destination.resolve()
    try:
        target.relative_to(base)
    except ValueError as error:
        raise ValidationError(
            f"container member escapes extraction root: {raw!r}"
        ) from error
    return target


def _scan_markers(path: Path, size: int) -> list[str]:
    markers: list[str] = []
    # Scan bounded head and tail slices so huge images stay instantaneous.
    window = 4 * 1024 * 1024
    with path.open("rb") as handle:
        head = handle.read(min(size, window))
        tail = b""
        if size > window:
            handle.seek(max(0, size - window))
            tail = handle.read(window)
    blob = head + b"\x00" + tail
    if b"Go buildinf:" in blob or b".gopclntab" in blob:
        markers.append("go")
    if b"rustc/" in blob or b"rust_eh_personality" in blob:
        markers.append("rust")
    if b"UPX!" in blob:
        markers.append("upx")
    if b"libflutter.so" in blob or b"io.flutter" in blob:
        markers.append("flutter")
    return markers


def _parse_elf(path: Path, size: int) -> dict[str, Any] | None:
    if size < 52:
        return None
    with path.open("rb") as handle:
        header = handle.read(64)
    if header[:4] != b"\x7fELF":
        return None
    ei_class = header[4]
    ei_data = header[5]
    if ei_class not in (1, 2) or ei_data not in (1, 2):
        return {"format": "elf", "malformed": True}
    endian = "<" if ei_data == 1 else ">"
    bits = 32 if ei_class == 1 else 64
    if bits == 32:
        e_type, e_machine, _, e_entry, _, _, _, _, _, e_phnum, _, e_shnum, _ = (
            struct.unpack(f"{endian}HHIIIIIHHHHHH", header[16:52])
        )
    else:
        if len(header) < 64:
            return {"format": "elf", "malformed": True}
        e_type, e_machine, _, e_entry, _, _, _, _, _, e_phnum, _, e_shnum, _ = (
            struct.unpack(f"{endian}HHIQQQIHHHHHH", header[16:64])
        )
    return {
        "format": "elf",
        "bits": bits,
        "endianness": "little" if ei_data == 1 else "big",
        "type": _ELF_TYPES.get(e_type, f"0x{e_type:x}"),
        "machine": _ELF_MACHINES.get(e_machine, f"0x{e_machine:x}"),
        "entry_point": hex(e_entry),
        "program_headers": e_phnum,
        "section_headers": e_shnum,
        "markers": _scan_markers(path, size),
    }


def _parse_pe(path: Path, size: int) -> dict[str, Any] | None:
    if size < 0x40:
        return None
    with path.open("rb") as handle:
        dos = handle.read(0x40)
        if dos[:2] != b"MZ":
            return None
        pe_offset = struct.unpack_from("<I", dos, 0x3C)[0]
        if pe_offset < 0x40 or pe_offset + 24 > size:
            return None
        handle.seek(pe_offset)
        sig_coff = handle.read(24)
        if sig_coff[:4] != b"PE\x00\x00":
            return None
        machine, num_sections, _, _, _, opt_size, characteristics = struct.unpack(
            "<HHIIIHH", sig_coff[4:24]
        )
        opt = handle.read(min(opt_size, 512))
        section_table = handle.read(min(num_sections, 96) * 40)

    is_dll = bool(characteristics & 0x2000)
    pe_kind = "pe"
    entry_rva = None
    image_base = None
    subsystem = None
    is_dotnet = False
    has_authenticode = False
    if len(opt) >= 2:
        magic = struct.unpack_from("<H", opt, 0)[0]
        if magic == 0x10B and len(opt) >= 96:
            pe_kind = "pe32"
            entry_rva = struct.unpack_from("<I", opt, 16)[0]
            image_base = struct.unpack_from("<I", opt, 28)[0]
            subsystem_id = struct.unpack_from("<H", opt, 68)[0]
            subsystem = _PE_SUBSYSTEMS.get(subsystem_id, str(subsystem_id))
            num_rva = struct.unpack_from("<I", opt, 92)[0]
            dirs_off = 96
        elif magic == 0x20B and len(opt) >= 112:
            pe_kind = "pe32+"
            entry_rva = struct.unpack_from("<I", opt, 16)[0]
            image_base = struct.unpack_from("<Q", opt, 24)[0]
            subsystem_id = struct.unpack_from("<H", opt, 68)[0]
            subsystem = _PE_SUBSYSTEMS.get(subsystem_id, str(subsystem_id))
            num_rva = struct.unpack_from("<I", opt, 108)[0]
            dirs_off = 112
        else:
            num_rva = 0
            dirs_off = 0
        if num_rva > 4 and len(opt) >= dirs_off + 5 * 8:
            cert_va, cert_sz = struct.unpack_from("<II", opt, dirs_off + 4 * 8)
            has_authenticode = bool(cert_va and cert_sz)
        if num_rva > 14 and len(opt) >= dirs_off + 15 * 8:
            clr_rva, clr_sz = struct.unpack_from("<II", opt, dirs_off + 14 * 8)
            is_dotnet = bool(clr_rva and clr_sz)

    sections: list[dict[str, Any]] = []
    for idx in range(len(section_table) // 40):
        chunk = section_table[idx * 40 : (idx + 1) * 40]
        raw_name = chunk[:8].split(b"\x00", 1)[0].decode("ascii", errors="replace")
        vsize, vrva, rsize, roff = struct.unpack_from("<IIII", chunk, 8)
        sections.append(
            {
                "name": raw_name,
                "virtual_address": hex(vrva),
                "virtual_size": vsize,
                "raw_offset": hex(roff),
                "raw_size": rsize,
            }
        )
    return {
        "format": "pe",
        "variant": pe_kind,
        "is_dll": is_dll,
        "is_dotnet": is_dotnet,
        "has_authenticode": has_authenticode,
        "machine": _PE_MACHINES.get(machine, f"0x{machine:x}"),
        "subsystem": subsystem,
        "image_base": hex(image_base) if image_base is not None else None,
        "entry_point_rva": hex(entry_rva) if entry_rva is not None else None,
        "sections": sections,
        "markers": _scan_markers(path, size),
    }


def _parse_macho_slice(data: bytes, offset: int = 0) -> dict[str, Any] | None:
    if len(data) - offset < 28:
        return None
    magic = struct.unpack_from(">I", data, offset)[0]
    mapping = {
        0xFEEDFACE: (">", 32),
        0xCEFAEDFE: ("<", 32),
        0xFEEDFACF: (">", 64),
        0xCFFAEDFE: ("<", 64),
    }
    if magic not in mapping:
        return None
    endian, bits = mapping[magic]
    hdr_size = 28 if bits == 32 else 32
    if len(data) - offset < hdr_size:
        return None
    cputype, _, filetype, ncmds, sizeofcmds, _ = struct.unpack_from(
        f"{endian}iiIIII", data, offset + 4
    )
    has_code_signature = False
    cmd_off = offset + hdr_size
    cmd_end = min(len(data), cmd_off + sizeofcmds)
    for _ in range(min(ncmds, 512)):
        if cmd_off + 8 > cmd_end:
            break
        cmd, cmdsize = struct.unpack_from(f"{endian}II", data, cmd_off)
        if cmd == 0x1D:  # LC_CODE_SIGNATURE
            has_code_signature = True
        if cmdsize < 8:
            break
        cmd_off += cmdsize
    return {
        "bits": bits,
        "endianness": "little" if endian == "<" else "big",
        "cpu": _MACHO_CPUS.get(cputype, f"0x{cputype & 0xFFFFFFFF:x}"),
        "filetype": _MACHO_FILETYPES.get(filetype, str(filetype)),
        "load_commands": ncmds,
        "has_code_signature": has_code_signature,
    }


def _parse_macho(path: Path, size: int) -> dict[str, Any] | None:
    if size < 28:
        return None
    with path.open("rb") as handle:
        head = handle.read(min(size, 65536))
    single = _parse_macho_slice(head, 0)
    if single is not None:
        return {"format": "macho", "universal": False, "slices": [single]}
    magic = struct.unpack_from(">I", head, 0)[0]
    if magic not in (0xCAFEBABE, 0xCAFEBABF) or len(head) < 8:
        return None
    nfat = struct.unpack_from(">I", head, 4)[0]
    # Java class files also start with 0xCAFEBABE followed by minor/major>=45.
    if nfat == 0 or nfat > 16:
        return None
    entry_size = 20 if magic == 0xCAFEBABE else 32
    if len(head) < 8 + nfat * entry_size:
        return None
    slices: list[dict[str, Any]] = []
    with path.open("rb") as handle:
        for idx in range(nfat):
            base = 8 + idx * entry_size
            if magic == 0xCAFEBABE:
                cputype, _, slice_off, slice_size, _ = struct.unpack_from(
                    ">iiIII", head, base
                )
            else:
                cputype, _, slice_off, slice_size, _, _ = struct.unpack_from(
                    ">iiQQII", head, base
                )
            if slice_off + 32 > size or cputype not in _MACHO_CPUS:
                return None
            handle.seek(slice_off)
            chunk = handle.read(min(slice_size, 65536))
            parsed = _parse_macho_slice(chunk, 0) or {
                "cpu": _MACHO_CPUS.get(cputype, hex(cputype)),
            }
            parsed["offset"] = hex(slice_off)
            parsed["size"] = slice_size
            slices.append(parsed)
    return {"format": "macho", "universal": True, "slices": slices}


def _read_leb128_u32(data: bytes, offset: int) -> tuple[int, int]:
    result = 0
    shift = 0
    for _ in range(5):
        if offset >= len(data):
            raise ValueError("truncated LEB128")
        byte = data[offset]
        offset += 1
        result |= (byte & 0x7F) << shift
        if not (byte & 0x80):
            return result, offset
        shift += 7
    raise ValueError("LEB128 exceeds uint32")


def _parse_wasm(path: Path, size: int) -> dict[str, Any] | None:
    if size < 8:
        return None
    with path.open("rb") as handle:
        head = handle.read(8)
        if head[:4] != b"\x00asm":
            return None
        version = struct.unpack_from("<I", head, 4)[0]
        sections: list[dict[str, Any]] = []
        offset = 8
        while offset < size and len(sections) < 256:
            handle.seek(offset)
            probe = handle.read(64)
            if not probe:
                break
            sec_id = probe[0]
            try:
                sec_len, rel = _read_leb128_u32(probe, 1)
            except ValueError:
                break
            payload_start = offset + rel
            custom_name = None
            if sec_id == 0 and sec_len > 0:
                try:
                    name_len, name_rel = _read_leb128_u32(probe, rel)
                    if name_rel + name_len <= len(probe):
                        custom_name = probe[name_rel : name_rel + name_len].decode(
                            "utf-8", errors="replace"
                        )
                except ValueError:
                    custom_name = None
            entry: dict[str, Any] = {
                "id": sec_id,
                "kind": _WASM_SECTIONS.get(sec_id, f"unknown-{sec_id}"),
                "offset": hex(payload_start),
                "size": sec_len,
            }
            if custom_name is not None:
                entry["name"] = custom_name
            sections.append(entry)
            offset = payload_start + sec_len
    return {"format": "wasm", "version": version, "sections": sections}


def _parse_asar(
    path: Path,
    size: int,
    *,
    extract_dir: Path | None,
    max_extract_bytes: int,
    max_extract_files: int,
) -> dict[str, Any] | None:
    if size < 16:
        return None
    with path.open("rb") as handle:
        prefix = handle.read(16)
        p_size, h_total, h_aligned, json_len = struct.unpack("<IIII", prefix)
        # Standard Chromium Pickle framing used by @electron/asar.
        if p_size != 4 or json_len == 0 or json_len > 32 * 1024 * 1024:
            return None
        data_offset = 8 + h_total
        if data_offset > size or 16 + json_len > data_offset or h_aligned < json_len:
            return None
        raw_json = handle.read(json_len)
        try:
            tree = json.loads(raw_json.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None
        if not isinstance(tree, dict) or not isinstance(tree.get("files"), dict):
            return None

        members: list[dict[str, Any]] = []
        links: list[dict[str, str]] = []

        def walk(node: dict[str, Any], prefix_parts: list[str]) -> None:
            for name, meta in sorted((node.get("files") or {}).items()):
                if not isinstance(meta, dict):
                    continue
                parts = [*prefix_parts, name]
                rel = "/".join(parts)
                if isinstance(meta.get("files"), dict):
                    walk(meta, parts)
                elif "link" in meta:
                    links.append({"path": rel, "target": str(meta["link"])})
                else:
                    raw_off = meta.get("offset", "0")
                    members.append(
                        {
                            "path": rel,
                            "size": int(meta.get("size", 0)),
                            "offset": int(str(raw_off)),
                            "unpacked": bool(meta.get("unpacked", False)),
                            "executable": bool(meta.get("executable", False)),
                        }
                    )

        walk(tree, [])
        extracted_count = 0
        extracted_bytes = 0
        skipped_unpacked = 0
        if extract_dir is not None:
            extract_dir.mkdir(parents=True, exist_ok=True)
            for item in members:
                if item["unpacked"]:
                    skipped_unpacked += 1
                    continue
                if extracted_count >= max_extract_files:
                    raise ValidationError(
                        f"ASAR member count exceeds max_extract_files ({max_extract_files})"
                    )
                item_size = item["size"]
                if item_size < 0 or extracted_bytes + item_size > max_extract_bytes:
                    raise ValidationError(
                        f"ASAR extraction exceeds max_extract_bytes ({max_extract_bytes})"
                    )
                abs_off = data_offset + item["offset"]
                if abs_off < data_offset or abs_off + item_size > size:
                    raise ValidationError(
                        f"ASAR member {item['path']!r} offset/size exceeds file bounds"
                    )
                destination = _safe_relpath(item["path"], extract_dir)
                destination.parent.mkdir(parents=True, exist_ok=True)
                handle.seek(abs_off)
                remaining = item_size
                with destination.open("wb") as out:
                    while remaining > 0:
                        chunk = handle.read(min(remaining, 1024 * 1024))
                        if not chunk:
                            raise ValidationError(
                                f"unexpected EOF reading ASAR member {item['path']!r}"
                            )
                        out.write(chunk)
                        remaining -= len(chunk)
                extracted_count += 1
                extracted_bytes += item_size

    report: dict[str, Any] = {
        "kind": "asar",
        "data_offset": data_offset,
        "member_count": len(members),
        "symlink_count": len(links),
        "unpacked_count": sum(1 for item in members if item["unpacked"]),
        "total_bytes": sum(item["size"] for item in members),
        "members": members[:MAX_MEMBER_LISTING],
        "members_truncated": len(members) > MAX_MEMBER_LISTING,
    }
    if links:
        report["symlinks"] = links[:MAX_MEMBER_LISTING]
    if extract_dir is not None:
        report["extraction"] = {
            "directory": str(extract_dir),
            "files_written": extracted_count,
            "bytes_written": extracted_bytes,
            "skipped_unpacked": skipped_unpacked,
        }
    return report


def _parse_pyinstaller(
    path: Path,
    size: int,
    *,
    extract_dir: Path | None,
    max_extract_bytes: int,
    max_extract_files: int,
) -> dict[str, Any] | None:
    if size < 24:
        return None
    scan_len = min(size, _PYI_TAIL_SCAN)
    scan_start = size - scan_len
    with path.open("rb") as handle:
        handle.seek(scan_start)
        tail = handle.read(scan_len)
        idx = tail.rfind(_PYI_MAGIC)
        if idx < 0:
            return None
        cookie_pos = scan_start + idx
        rem = size - cookie_pos
        pylib = None
        if rem >= 88:
            _, pkg_len, toc_off, toc_len, pyver, pylib_raw = struct.unpack_from(
                "!8siiii64s", tail, idx
            )
            cookie_size = 88
            pylib = pylib_raw.split(b"\x00", 1)[0].decode("utf-8", errors="replace")
        elif rem >= 24:
            _, pkg_len, toc_off, toc_len, pyver = struct.unpack_from(
                "!8siiii", tail, idx
            )
            cookie_size = 24
        else:
            return None

        archive_base = cookie_pos + cookie_size - pkg_len
        toc_abs = archive_base + toc_off
        if (
            pkg_len <= 0
            or archive_base < 0
            or toc_len < 0
            or toc_len > 32 * 1024 * 1024
            or toc_abs < 0
            or toc_abs + toc_len > cookie_pos
        ):
            return None

        handle.seek(toc_abs)
        toc_bytes = handle.read(toc_len)
        entries: list[dict[str, Any]] = []
        pos = 0
        while pos + 18 <= len(toc_bytes):
            entry_len, data_off, comp_len, uncomp_len, comp_flag, typecode = (
                struct.unpack_from("!iiiiBc", toc_bytes, pos)
            )
            if entry_len < 18 or pos + entry_len > len(toc_bytes):
                break
            raw_name = toc_bytes[pos + 18 : pos + entry_len].rstrip(b"\x00")
            name = raw_name.decode("utf-8", errors="replace")
            code = typecode.decode("ascii", errors="replace")
            entries.append(
                {
                    "name": name,
                    "typecode": code,
                    "offset": archive_base + data_off,
                    "compressed_size": comp_len,
                    "uncompressed_size": uncomp_len,
                    "compressed": bool(comp_flag),
                }
            )
            pos += entry_len

        extracted_count = 0
        extracted_bytes = 0
        if extract_dir is not None:
            extract_dir.mkdir(parents=True, exist_ok=True)
            for item in entries:
                if not item["name"] or item["typecode"] in {"d", "o"}:
                    continue
                if extracted_count >= max_extract_files:
                    raise ValidationError(
                        f"PyInstaller TOC exceeds max_extract_files ({max_extract_files})"
                    )
                comp_size = item["compressed_size"]
                abs_off = item["offset"]
                if comp_size < 0 or abs_off < 0 or abs_off + comp_size > size:
                    raise ValidationError(
                        f"PyInstaller member {item['name']!r} exceeds archive bounds"
                    )
                rel_name = item["name"]
                if item["typecode"] == "s" and not rel_name.endswith(".pyc"):
                    rel_name = f"scripts/{rel_name}.pyc_stream"
                destination = _safe_relpath(rel_name, extract_dir)
                destination.parent.mkdir(parents=True, exist_ok=True)
                handle.seek(abs_off)
                if item["compressed"]:
                    decompressor = zlib.decompressobj()
                    remaining = comp_size
                    with destination.open("wb") as out:
                        while remaining > 0:
                            chunk = handle.read(min(remaining, 256 * 1024))
                            if not chunk:
                                raise ValidationError(
                                    f"unexpected EOF in PyInstaller member {item['name']!r}"
                                )
                            remaining -= len(chunk)
                            budget = max_extract_bytes - extracted_bytes + 1
                            produced = decompressor.decompress(chunk, budget)
                            extracted_bytes += len(produced)
                            if extracted_bytes > max_extract_bytes:
                                raise ValidationError(
                                    f"PyInstaller extraction exceeds max_extract_bytes ({max_extract_bytes})"
                                )
                            out.write(produced)
                        tail_out = decompressor.flush()
                        extracted_bytes += len(tail_out)
                        if extracted_bytes > max_extract_bytes:
                            raise ValidationError(
                                f"PyInstaller extraction exceeds max_extract_bytes ({max_extract_bytes})"
                            )
                        out.write(tail_out)
                else:
                    if extracted_bytes + comp_size > max_extract_bytes:
                        raise ValidationError(
                            f"PyInstaller extraction exceeds max_extract_bytes ({max_extract_bytes})"
                        )
                    remaining = comp_size
                    with destination.open("wb") as out:
                        while remaining > 0:
                            chunk = handle.read(min(remaining, 1024 * 1024))
                            if not chunk:
                                raise ValidationError(
                                    f"unexpected EOF in PyInstaller member {item['name']!r}"
                                )
                            out.write(chunk)
                            remaining -= len(chunk)
                    extracted_bytes += comp_size
                extracted_count += 1

    entry_scripts = [item["name"] for item in entries if item["typecode"] == "s"]
    pyz_bundles = [item["name"] for item in entries if item["typecode"] in {"z", "Z"}]
    report: dict[str, Any] = {
        "kind": "pyinstaller",
        "python_version_tag": pyver,
        "python_library": pylib,
        "archive_offset": archive_base,
        "package_bytes": pkg_len,
        "member_count": len(entries),
        "entry_scripts": entry_scripts,
        "pyz_bundles": pyz_bundles,
        "members": [
            {
                "name": item["name"],
                "typecode": item["typecode"],
                "compressed_size": item["compressed_size"],
                "uncompressed_size": item["uncompressed_size"],
                "compressed": item["compressed"],
            }
            for item in entries[:MAX_MEMBER_LISTING]
        ],
        "members_truncated": len(entries) > MAX_MEMBER_LISTING,
    }
    if extract_dir is not None:
        report["extraction"] = {
            "directory": str(extract_dir),
            "files_written": extracted_count,
            "bytes_written": extracted_bytes,
        }
    return report


def _detect_apk_signing_schemes(path: Path, size: int) -> list[str]:
    if size < 64:
        return []
    window = min(size, 256 * 1024)
    with path.open("rb") as handle:
        handle.seek(size - window)
        tail = handle.read(window)
        eocd = tail.rfind(b"PK\x05\x06")
        if eocd < 0 or eocd + 20 > len(tail):
            return []
        cd_offset = struct.unpack_from("<I", tail, eocd + 16)[0]
        if cd_offset < 32 or cd_offset > size:
            return []
        handle.seek(cd_offset - 24)
        footer = handle.read(24)
        block_size, magic = struct.unpack("<Q16s", footer)
        if magic != _APK_SIG_MAGIC or block_size < 24 or block_size > cd_offset:
            return []
        block_start = cd_offset - block_size - 8
        if block_start < 0:
            return []
        handle.seek(block_start)
        header_size = struct.unpack("<Q", handle.read(8))[0]
        if header_size != block_size:
            return []
        pairs_end = cd_offset - 24
        pos = block_start + 8
        schemes: list[str] = []
        while pos + 12 <= pairs_end and len(schemes) < 16:
            handle.seek(pos)
            pair_len, pair_id = struct.unpack("<QI", handle.read(12))
            if pair_len < 4 or pos + 8 + pair_len > pairs_end:
                break
            label = _APK_SIG_SCHEMES.get(pair_id)
            if label and label not in schemes:
                schemes.append(label)
            pos += 8 + pair_len
        return schemes


def _parse_zip_container(
    path: Path,
    size: int,
    *,
    extract_dir: Path | None,
    max_extract_bytes: int,
    max_extract_files: int,
) -> dict[str, Any] | None:
    if not zipfile.is_zipfile(path):
        return None
    try:
        with zipfile.ZipFile(path, "r") as archive:
            infos = archive.infolist()
            names = [info.filename for info in infos]
            name_set = set(names)
            if "AndroidManifest.xml" in name_set or any(
                n.startswith("classes") and n.endswith(".dex") for n in names
            ):
                subkind = "apk"
            elif any(n.startswith("Payload/") and ".app/" in n for n in names):
                subkind = "ipa"
            elif "extension.vsixmanifest" in name_set:
                subkind = "vsix"
            elif "AndroidManifest.xml" not in name_set and "classes.jar" in name_set:
                subkind = "aar"
            elif "META-INF/MANIFEST.MF" in name_set:
                subkind = "jar"
            else:
                subkind = "zip"

            extracted_count = 0
            extracted_bytes = 0
            if extract_dir is not None:
                extract_dir.mkdir(parents=True, exist_ok=True)
                for info in infos:
                    if info.is_dir():
                        continue
                    unix_mode = info.external_attr >> 16
                    if unix_mode and (unix_mode & 0o170000) == 0o120000:
                        raise ValidationError(
                            f"ZIP container member is a symbolic link: {info.filename!r}"
                        )
                    if extracted_count >= max_extract_files:
                        raise ValidationError(
                            f"ZIP member count exceeds max_extract_files ({max_extract_files})"
                        )
                    destination = _safe_relpath(info.filename, extract_dir)
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(info, "r") as src, destination.open("wb") as out:
                        while True:
                            chunk = src.read(256 * 1024)
                            if not chunk:
                                break
                            extracted_bytes += len(chunk)
                            if extracted_bytes > max_extract_bytes:
                                raise ValidationError(
                                    f"ZIP extraction exceeds max_extract_bytes ({max_extract_bytes})"
                                )
                            out.write(chunk)
                    extracted_count += 1
    except zipfile.BadZipFile:
        return None

    report: dict[str, Any] = {
        "kind": subkind,
        "member_count": len(infos),
        "total_uncompressed_bytes": sum(info.file_size for info in infos),
        "members": [
            {
                "path": info.filename,
                "size": info.file_size,
                "compressed_size": info.compress_size,
            }
            for info in infos[:MAX_MEMBER_LISTING]
        ],
        "members_truncated": len(infos) > MAX_MEMBER_LISTING,
    }
    if subkind == "apk":
        report["apk_signature_schemes"] = _detect_apk_signing_schemes(path, size)
    if extract_dir is not None:
        report["extraction"] = {
            "directory": str(extract_dir),
            "files_written": extracted_count,
            "bytes_written": extracted_bytes,
        }
    return report


def inspect_artifact(
    source: Path,
    *,
    output_dir: Path | None = None,
    extract: bool = False,
    max_extract_bytes: int = DEFAULT_MAX_EXTRACT_BYTES,
    max_extract_files: int = DEFAULT_MAX_EXTRACT_FILES,
) -> dict[str, Any]:
    """Deterministically inspect *source* and optionally unpack its container."""
    resolved = source.expanduser().resolve()
    if not resolved.is_file():
        raise ValidationError(f"artifact is not a regular file: {resolved}")
    if max_extract_bytes < 1:
        raise ValidationError("max_extract_bytes must be positive")
    if max_extract_files < 1:
        raise ValidationError("max_extract_files must be positive")
    if extract and output_dir is None:
        raise ValidationError("--extract requires an explicit --output directory")

    destination: Path | None = None
    if output_dir is not None:
        destination = output_dir.expanduser().resolve()
        if destination == resolved or resolved.is_relative_to(destination):
            raise ValidationError("output directory must not contain the input artifact")

    before = _sha256(resolved)
    size = resolved.stat().st_size
    extract_root = (destination / "extracted") if (extract and destination) else None
    if extract_root is not None and extract_root.exists() and any(extract_root.iterdir()):
        raise ValidationError(f"extraction directory is not empty: {extract_root}")

    binary = (
        _parse_elf(resolved, size)
        or _parse_pe(resolved, size)
        or _parse_macho(resolved, size)
        or _parse_wasm(resolved, size)
    )
    container = (
        _parse_asar(
            resolved,
            size,
            extract_dir=extract_root,
            max_extract_bytes=max_extract_bytes,
            max_extract_files=max_extract_files,
        )
        or _parse_pyinstaller(
            resolved,
            size,
            extract_dir=extract_root,
            max_extract_bytes=max_extract_bytes,
            max_extract_files=max_extract_files,
        )
        or _parse_zip_container(
            resolved,
            size,
            extract_dir=extract_root,
            max_extract_bytes=max_extract_bytes,
            max_extract_files=max_extract_files,
        )
    )
    after = _sha256(resolved)
    if before != after:
        raise ValidationError("input artifact hash changed during inspection")

    primary_format = (
        container["kind"]
        if container is not None and binary is None
        else (binary["format"] if binary is not None else "unknown")
    )
    result: dict[str, Any] = {
        "schema_version": 1,
        "input": {
            "path": str(resolved),
            "size": size,
            "sha256": before,
            "unchanged": True,
        },
        "primary_format": primary_format,
        "binary": binary,
        "container": container,
    }
    if extract and container is None:
        result["extraction_note"] = "no supported container detected; nothing extracted"
    if destination is not None:
        destination.mkdir(parents=True, exist_ok=True)
        (destination / "artifact.json").write_text(
            json.dumps(result, indent=2, ensure_ascii=True) + "\n",
            encoding="utf-8",
        )
    return result
