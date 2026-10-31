"""Stage and verify optional trusted Windows signing; never execute package files."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import struct
import subprocess
import zipfile
from pathlib import Path

TARGETS = ("Audio8D/Audio8D.exe", "Audio8D/audio8d-cli.exe")
MANIFEST = "Audio8D/signing-manifest.json"
LIMIT = 1024 * 1024 * 1024


class SigningError(RuntimeError):
    """Signing evidence is missing, inconsistent or untrusted."""


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def linked(path: Path) -> bool:
    return path.is_symlink() or getattr(path, "is_junction", lambda: False)()


def plain_path(path: Path) -> None:
    if any(linked(part) for part in (path, *path.parents)):
        raise SigningError("Signing paths must not traverse links")


def safe_name(name: str) -> str:
    plain = name[:-1] if name.endswith("/") else name
    parts = plain.split("/")
    if (
        not parts
        or parts[0] != "Audio8D"
        or any(
            not p
            or p in (".", "..")
            or p.endswith((".", " "))
            or re.search(r'[\x00-\x1f\x7f\\:<>"|?*]', p)
            or re.fullmatch(
                r"(?i:CON|PRN|AUX|NUL|CONIN\$|CONOUT\$|COM[1-9¹²³]|LPT[1-9¹²³])",
                p.split(".")[0],
            )
            for p in parts
        )
    ):
        raise SigningError("Unsafe Windows ZIP member")
    return plain


def members(bundle: zipfile.ZipFile) -> dict:
    entries = bundle.infolist()
    if not entries or len(entries) > 50000 or sum(i.file_size for i in entries) > LIMIT:
        raise SigningError("Unexpected ZIP size or member count")
    found = {}
    for info in entries:
        name = safe_name(info.filename)
        kind = stat.S_IFMT(info.external_attr >> 16)
        if (
            name.casefold() in found
            or info.flag_bits & 1
            or kind not in (0, stat.S_IFREG, stat.S_IFDIR)
            or (kind == stat.S_IFDIR and not info.is_dir())
        ):
            raise SigningError("Duplicate, encrypted or nonordinary ZIP member")
        found[name.casefold()] = info
    files = {i.filename: i for i in entries if not i.is_dir()}
    for name in files:
        if any(parent.as_posix() in files for parent in Path(name).parents):
            raise SigningError("ZIP file/directory collision")
    return files


def pe_content(data: bytes, original_size: int | None = None) -> tuple[str, bool]:
    """Hash every byte including the PyInstaller overlay, except signing fields.

    Only the PE checksum, security-directory entry and EOF certificate table are
    omitted. A signed file can add at most seven zero bytes to align the table;
    the original size disambiguates those bytes from legitimate overlay content.
    """

    def u16(offset):
        return struct.unpack_from("<H", data, offset)[0]

    def u32(offset):
        return struct.unpack_from("<I", data, offset)[0]

    try:
        if len(data) < 64 or data[:2] != b"MZ":
            raise SigningError("Not a PE image")
        pe = u32(60)
        if pe < 64 or data[pe : pe + 4] != b"PE\0\0":
            raise SigningError("Invalid PE header")
        optional = pe + 24
        magic = u16(optional)
        if magic not in (0x10B, 0x20B):
            raise SigningError("Unsupported PE optional header")
        security = optional + (128 if magic == 0x10B else 144)
        count = optional + (92 if magic == 0x10B else 108)
        optional_size = u16(pe + 20)
        checksum = optional + 64
        sections = u16(pe + 6)
        headers = u32(optional + 60)
        table = optional + optional_size
        if (
            u32(count) <= 4
            or optional_size < security + 8 - optional
            or not sections
            or table + sections * 40 > headers
            or headers > len(data)
        ):
            raise SigningError("Invalid PE header/section table")
        covered = headers
        for section in range(sections):
            size, start = struct.unpack_from("<II", data, table + section * 40 + 16)
            if size and (start < headers or start + size > len(data)):
                raise SigningError("Invalid PE section range")
            covered = max(covered, start + size if size else 0)
        certificate, size = struct.unpack_from("<II", data, security)
        end = len(data)
        signed = bool(certificate or size)
        if signed:
            if (
                not certificate
                or size < 8
                or certificate % 8
                or size % 8
                or certificate < covered
                or certificate + size != len(data)
            ):
                raise SigningError(
                    "Certificate table must be aligned, outside sections and at EOF"
                )
            cursor = certificate
            while cursor < len(data):
                length, revision, kind = struct.unpack_from("<IHH", data, cursor)
                if (
                    length < 8
                    or cursor + length > len(data)
                    or revision != 0x200
                    or kind != 2
                ):
                    raise SigningError("Invalid WIN_CERTIFICATE record")
                cursor += (length + 7) & ~7
            if cursor != len(data):
                raise SigningError("Invalid certificate padding")
            end = certificate
            if original_size is not None:
                if (
                    original_size < covered
                    or certificate != ((original_size + 7) & ~7)
                    or any(data[original_size:certificate])
                ):
                    raise SigningError(
                        "Unexpected changes before the certificate table"
                    )
                end = original_size
        elif original_size is not None and original_size != len(data):
            raise SigningError("Unsigned PE length changed")
        if security + 8 > end:
            raise SigningError("Certificate overlaps headers")
        return digest(
            data[:checksum] + data[checksum + 4 : security] + data[security + 8 : end]
        ), signed
    except (struct.error, IndexError) as exc:
        raise SigningError("Truncated PE image") from exc


def records(folder: Path) -> list[dict]:
    result = []
    for path in sorted(folder.rglob("*")):
        if linked(path):
            raise SigningError("Links are not valid signing payloads")
        if path.is_file():
            name = path.relative_to(folder).as_posix()
            safe_name(name)
            result.append(
                {
                    "path": name,
                    "size": path.stat().st_size,
                    "sha256": digest(path.read_bytes()),
                }
            )
    return result


def stage(archive: Path, destination: Path, checksum: Path) -> Path:
    plain_path(destination.absolute())
    destination = destination.resolve()
    snapshot = destination.with_name(destination.name + ".signing-input.json")
    plain_path(snapshot)
    if destination.exists() or snapshot.exists():
        raise SigningError("Preserve existing signing payload/snapshot")
    line = checksum.read_text(encoding="utf-8").strip()
    if (
        archive.stat().st_size > LIMIT
        or line != f"{digest(archive.read_bytes())}  {archive.name}"
    ):
        raise SigningError("Unsigned archive checksum/size mismatch")
    with zipfile.ZipFile(archive) as bundle:
        files = members(bundle)
        if MANIFEST in files or not set(TARGETS).issubset(files):
            raise SigningError(
                "Expected unsigned frontends are missing or already finalized"
            )
        # Reading every member checks zipfile's CRC before extracting anything.
        if bundle.testzip() is not None:
            raise SigningError("ZIP CRC mismatch")
        destination.mkdir(parents=True)
        for name, info in files.items():
            target = destination / name
            target.parent.mkdir(parents=True, exist_ok=True)
            with bundle.open(info) as source, target.open("xb") as output:
                shutil.copyfileobj(source, output)
    pe = []
    for name in TARGETS:
        data = (destination / name).read_bytes()
        content, signed = pe_content(data)
        if signed:
            raise SigningError("Signing input must be unsigned")
        pe.append(
            {
                "path": name,
                "unsignedSize": len(data),
                "unsignedSha256": digest(data),
                "authenticodeContentSha256": content,
            }
        )
    snapshot_data = (
        json.dumps(
            {
                "schemaVersion": 1,
                "folder": str(destination),
                "archiveSha256": digest(archive.read_bytes()),
                "files": records(destination),
                "attributes": {
                    name: info.external_attr for name, info in files.items()
                },
                "peFiles": pe,
            },
            indent=2,
        )
        + "\n"
    )
    with snapshot.open("x", encoding="utf-8", newline="\n") as output:
        output.write(snapshot_data)
    return destination


def signature_evidence(path: Path, publisher: str) -> dict:
    """Windows trust evaluation; no package executable is launched."""
    if os.name != "nt" or not publisher.strip():
        raise SigningError("Windows and an exact expected publisher are required")
    script = r"""
    $ErrorActionPreference = 'Stop'
    $s = Get-AuthenticodeSignature -LiteralPath $env:AUDIO8D_VERIFY_FILE
    $c = $s.SignerCertificate
    if ($s.Status -ne 'Valid' -or $s.SignatureType -ne 'Authenticode' -or
        $null -eq $c -or $null -eq $s.TimeStamperCertificate) {
        throw 'Valid embedded timestamped signature required'
    }
    if ($c.Subject -cne $env:AUDIO8D_VERIFY_PUBLISHER -or
        $c.Subject -ceq $c.Issuer) { throw 'Unexpected or self-issued publisher' }
    $eku = @($c.Extensions | Where-Object { $_.Oid.Value -eq '2.5.29.37' } |
        ForEach-Object { $_.EnhancedKeyUsages } | ForEach-Object { $_.Value })
    if ('1.3.6.1.5.5.7.3.3' -notin $eku) { throw 'Code-signing EKU required' }
    @{signerThumbprint=$c.Thumbprint;
      timestampSignerSubject=$s.TimeStamperCertificate.Subject} |
        ConvertTo-Json -Compress
    """
    result = subprocess.run(
        ["pwsh", "-NoProfile", "-NonInteractive", "-Command", script],
        env={
            **os.environ,
            "AUDIO8D_VERIFY_FILE": str(path.resolve()),
            "AUDIO8D_VERIFY_PUBLISHER": publisher,
        },
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        check=True,
    )
    evidence = json.loads(result.stdout)
    if not re.fullmatch(
        r"[A-Fa-f0-9]{40,64}", evidence.get("signerThumbprint", "")
    ) or not evidence.get("timestampSignerSubject"):
        raise SigningError("Incomplete Windows signature evidence")
    return evidence


def finalize(folder: Path, archive: Path, publisher: str) -> Path:
    plain_path(folder.absolute())
    plain_path(archive.absolute())
    folder = folder.resolve()
    checksum = archive.with_suffix(".sha256")
    if (
        not publisher.strip()
        or archive.exists()
        or checksum.exists()
        or folder in archive.resolve().parents
    ):
        raise SigningError(
            "Publisher is required; preserve existing outputs "
            "and keep ZIP outside payload"
        )
    snapshot_path = folder.with_name(folder.name + ".signing-input.json")
    plain_path(snapshot_path)
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    if snapshot.get("schemaVersion") != 1 or snapshot.get("folder") != str(folder):
        raise SigningError("Signing snapshot does not match payload")
    before = {r["path"]: r for r in snapshot["files"]}
    after = {r["path"]: r for r in records(folder)}
    if (
        len(before) != len(snapshot["files"])
        or before.keys() != after.keys()
        or any(before[n] != after[n] for n in before if n not in TARGETS)
    ):
        raise SigningError("Signing changed nonfrontend files or file membership")
    originals = {r["path"]: r for r in snapshot["peFiles"]}
    if set(originals) != set(TARGETS):
        raise SigningError("Exactly two original frontend records are required")
    signed_files = []
    for name in TARGETS:
        prior = originals[name]
        if (
            before[name]["sha256"] != prior["unsignedSha256"]
            or before[name]["size"] != prior["unsignedSize"]
        ):
            raise SigningError("Original PE evidence disagrees")
        content, signed = pe_content(
            (folder / name).read_bytes(), prior["unsignedSize"]
        )
        if not signed or content != prior["authenticodeContentSha256"]:
            raise SigningError(
                "Signing changed frontend content or no signature was added"
            )
        signed_files.append(
            {
                **prior,
                "signedSha256": after[name]["sha256"],
                **signature_evidence(folder / name, publisher),
            }
        )
    manifest = {
        "schemaVersion": 1,
        "status": "Authenticode signed Windows frontends",
        "publisher": publisher,
        "unsignedArchiveSha256": snapshot["archiveSha256"],
        "signing": signed_files,
        "files": list(after.values()),
    }
    (folder / MANIFEST).write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    archive.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive, "x", zipfile.ZIP_DEFLATED) as bundle:
        for record in records(folder):
            info = zipfile.ZipInfo(record["path"])
            info.create_system = 3
            info.external_attr = snapshot["attributes"].get(
                record["path"], (stat.S_IFREG | 0o644) << 16
            )
            info.compress_type = zipfile.ZIP_DEFLATED
            with (
                (folder / record["path"]).open("rb") as source,
                bundle.open(info, "w") as target,
            ):
                shutil.copyfileobj(source, target)
    verify_signed_archive(archive, publisher)
    checksum.write_text(
        f"{digest(archive.read_bytes())}  {archive.name}\n",
        encoding="utf-8",
        newline="\n",
    )
    return archive


def verify_signed_archive(archive: Path, publisher: str | None = None) -> dict:
    """Verify Windows-job evidence and bytes, not cryptographic trust on Linux."""
    with zipfile.ZipFile(archive) as bundle:
        files = members(bundle)
        if MANIFEST not in files or files[MANIFEST].file_size > 16 * 1024 * 1024:
            raise SigningError("Signing manifest is missing or oversized")
        manifest = json.loads(bundle.read(MANIFEST))
        if (
            manifest.get("schemaVersion") != 1
            or manifest.get("status") != "Authenticode signed Windows frontends"
            or not manifest.get("publisher")
            or (publisher is not None and manifest["publisher"] != publisher)
            or not re.fullmatch(
                r"[a-f0-9]{64}", manifest.get("unsignedArchiveSha256", "")
            )
        ):
            raise SigningError("Unsupported signing manifest")
        expected = {r["path"]: r for r in manifest["files"]}
        if len(expected) != len(manifest["files"]) or set(expected) != set(files) - {
            MANIFEST
        }:
            raise SigningError("Final signing manifest file coverage mismatch")
        for name, record in expected.items():
            data = bundle.read(name)  # also validates CRC
            if len(data) != record["size"] or digest(data) != record["sha256"]:
                raise SigningError("Final signing manifest file hash mismatch")
        signing = {r["path"]: r for r in manifest["signing"]}
        if len(manifest["signing"]) != 2 or set(signing) != set(TARGETS):
            raise SigningError("Exactly two signed frontend records are required")
        for name, record in signing.items():
            content, signed = pe_content(bundle.read(name), record["unsignedSize"])
            if (
                not signed
                or content != record["authenticodeContentSha256"]
                or expected[name]["sha256"] != record["signedSha256"]
                or not re.fullmatch(r"[a-f0-9]{64}", record.get("unsignedSha256", ""))
                or not re.fullmatch(
                    r"[A-Fa-f0-9]{40,64}", record.get("signerThumbprint", "")
                )
                or not record.get("timestampSignerSubject")
            ):
                raise SigningError("Invalid signed frontend evidence")
        return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("stage")
    prepare.add_argument("archive", type=Path)
    prepare.add_argument("destination", type=Path)
    prepare.add_argument("--checksum", required=True, type=Path)
    complete = commands.add_parser("finalize")
    complete.add_argument("folder", type=Path)
    complete.add_argument("archive", type=Path)
    complete.add_argument("--publisher", required=True)
    args = parser.parse_args()
    if args.command == "stage":
        print(stage(args.archive, args.destination, args.checksum))
    else:
        print(finalize(args.folder, args.archive, args.publisher))


if __name__ == "__main__":
    main()
