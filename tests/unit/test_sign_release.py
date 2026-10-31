"""Synthetic PE/ZIP integrity tests; mocked metadata never asserts live trust."""

import importlib.util
import json
import stat
import struct
import zipfile
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "sign_release", Path(__file__).resolve().parents[2] / "packaging/sign_release.py"
)
signing = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(signing)


def image(overlay=b"PYINSTALLER-overlay-cookie!", magic=0x20B):
    data = bytearray(1024)
    data[:2] = b"MZ"
    struct.pack_into("<I", data, 60, 128)
    data[128:132] = b"PE\0\0"
    struct.pack_into("<H", data, 134, 1)
    struct.pack_into("<H", data, 148, 240)
    struct.pack_into("<H", data, 152, magic)
    struct.pack_into("<I", data, 212, 512)
    struct.pack_into("<I", data, 244 if magic == 0x10B else 260, 16)
    struct.pack_into("<II", data, 408, 512, 512)
    return bytes(data) + overlay


def certificate(data):
    result = bytearray(data)
    result += b"\0" * (-len(result) % 8)
    security = 280 if struct.unpack_from("<H", data, 152)[0] == 0x10B else 296
    struct.pack_into("<II", result, security, len(result), 16)
    struct.pack_into("<I", result, 216, 12345)
    # Structural fixture only: not a usable certificate or a real signature.
    return bytes(result) + struct.pack("<IHH", 16, 0x200, 2) + b"fixture!"


@pytest.fixture
def staged(tmp_path):
    archive = tmp_path / "unsigned.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        for name in signing.TARGETS:
            info = zipfile.ZipInfo(name)
            info.external_attr = (stat.S_IFREG | 0o755) << 16
            bundle.writestr(info, image())
        bundle.writestr("Audio8D/_internal/ffmpeg.exe", b"third party unchanged")
        bundle.writestr("Audio8D/BUILD-INFO.txt", b"Audio8D 1.0.0\n")
    checksum = tmp_path / "unsigned.sha256"
    checksum.write_text(f"{signing.digest(archive.read_bytes())}  {archive.name}\n")
    folder = signing.stage(archive, tmp_path / "payload", checksum)
    return folder, archive, checksum


def mock_sign(folder, monkeypatch):
    for name in signing.TARGETS:
        path = folder / name
        path.write_bytes(certificate(path.read_bytes()))
    monkeypatch.setattr(
        signing,
        "signature_evidence",
        lambda path, publisher: {
            "signerThumbprint": "A" * 40,
            "timestampSignerSubject": "Mock timestamp metadata",
        },
    )


def test_stage_rejects_a_link_at_the_external_snapshot(staged, tmp_path, monkeypatch):
    _, archive, checksum = staged
    destination = tmp_path / "another-payload"
    snapshot = tmp_path / "another-payload.signing-input.json"
    monkeypatch.setattr(signing, "linked", lambda path: path == snapshot)
    with pytest.raises(signing.SigningError, match="must not traverse links"):
        signing.stage(archive, destination, checksum)
    assert not destination.exists()


@pytest.mark.parametrize("overlay", [b"x", b"x\0", b"x\0\0\0\0\0\0\0", b"cookie"])
@pytest.mark.parametrize("magic", [0x10B, 0x20B])
def test_normalization_preserves_overlay_and_only_allows_signing_fields(overlay, magic):
    original = image(overlay, magic)
    content, signed = signing.pe_content(original)
    assert not signed
    final = certificate(original)
    assert signing.pe_content(final, len(original)) == (content, True)
    modified = bytearray(final)
    modified[600] ^= 1
    assert signing.pe_content(bytes(modified), len(original))[0] != content
    modified = bytearray(final)
    modified[len(original) - 1] ^= 1
    assert signing.pe_content(bytes(modified), len(original))[0] != content


def test_nonzero_alignment_and_postcertificate_data_are_rejected():
    original = image(b"x")
    modified = bytearray(certificate(original))
    modified[len(original)] = 1
    with pytest.raises(signing.SigningError):
        signing.pe_content(bytes(modified), len(original))
    with pytest.raises(signing.SigningError):
        signing.pe_content(certificate(original) + b"extra", len(original))


def test_finalize_checks_all_bytes_and_preserves_modes(staged, tmp_path, monkeypatch):
    folder, _, _ = staged
    original = json.loads(
        folder.with_name(folder.name + ".signing-input.json").read_text()
    )
    mock_sign(folder, monkeypatch)
    archive = signing.finalize(
        folder, tmp_path / "signed.zip", "Mock publisher metadata"
    )
    manifest = signing.verify_signed_archive(archive, "Mock publisher metadata")
    assert len(manifest["signing"]) == 2
    assert manifest["unsignedArchiveSha256"] == original["archiveSha256"]
    assert signing.MANIFEST not in {r["path"] for r in manifest["files"]}
    with zipfile.ZipFile(archive) as bundle:
        assert bundle.read("Audio8D/_internal/ffmpeg.exe") == b"third party unchanged"
        assert (
            stat.S_IMODE(bundle.getinfo(signing.TARGETS[0]).external_attr >> 16)
            == 0o755
        )
    assert (
        archive.with_suffix(".sha256")
        .read_text()
        .startswith(signing.digest(archive.read_bytes()))
    )


@pytest.mark.parametrize(
    "change", ["add", "remove", "thirdparty", "overlay", "unsigned"]
)
def test_finalize_rejects_unauthorized_changes(staged, tmp_path, monkeypatch, change):
    folder, _, _ = staged
    mock_sign(folder, monkeypatch)
    if change == "add":
        (folder / "Audio8D/extra.txt").write_text("extra")
    elif change == "remove":
        (folder / "Audio8D/BUILD-INFO.txt").unlink()
    elif change == "thirdparty":
        (folder / "Audio8D/_internal/ffmpeg.exe").write_bytes(b"changed")
    elif change == "overlay":
        path = folder / signing.TARGETS[0]
        data = bytearray(path.read_bytes())
        data[1024] ^= 1
        path.write_bytes(data)
    else:
        (folder / signing.TARGETS[0]).write_bytes(image())
    with pytest.raises(signing.SigningError):
        signing.finalize(folder, tmp_path / "signed.zip", "Mock publisher metadata")
    assert not (tmp_path / "signed.zip").exists()


def test_untrusted_signature_blocks_archive_creation(staged, tmp_path, monkeypatch):
    folder, _, _ = staged
    mock_sign(folder, monkeypatch)

    def reject(*_args):
        raise signing.SigningError("Mock Windows trust rejection")

    monkeypatch.setattr(signing, "signature_evidence", reject)
    with pytest.raises(signing.SigningError, match="trust rejection"):
        signing.finalize(folder, tmp_path / "signed.zip", "Mock publisher metadata")
    assert not (tmp_path / "signed.zip").exists()


@pytest.mark.parametrize(
    "name",
    [
        "../escape",
        "/absolute",
        "Audio8D/../escape",
        "Audio8D/a:stream",
        "Audio8D/NUL.txt",
        "Audio8D/a\\b",
    ],
)
def test_unsafe_archive_names_are_rejected(name):
    with pytest.raises(signing.SigningError):
        signing.safe_name(name)


@pytest.mark.parametrize("kind", ["duplicate", "symlink", "casefold", "checksum"])
def test_bad_archive_is_rejected_before_staging(staged, tmp_path, kind):
    _, archive, checksum = staged
    if kind != "checksum":
        with zipfile.ZipFile(archive, "a") as bundle:
            info = zipfile.ZipInfo(
                "Audio8D/Audio8D.exe"
                if kind == "duplicate"
                else "Audio8D/AUDIO8D.EXE"
                if kind == "casefold"
                else "Audio8D/link"
            )
            if kind == "symlink":
                info.external_attr = (stat.S_IFLNK | 0o777) << 16
            bundle.writestr(info, b"bad")
        checksum.write_text(f"{signing.digest(archive.read_bytes())}  {archive.name}\n")
    else:
        checksum.write_text("0" * 64 + f"  {archive.name}\n")
    with pytest.raises(signing.SigningError):
        signing.stage(archive, tmp_path / "rejected", checksum)
    assert not (tmp_path / "rejected").exists()


def test_corrupt_crc_is_rejected_before_extraction(staged, tmp_path):
    _, archive, checksum = staged
    with zipfile.ZipFile(archive) as bundle:
        info = bundle.getinfo(signing.TARGETS[0])
        offset = info.header_offset + 30 + len(info.filename.encode()) + len(info.extra)
    data = bytearray(archive.read_bytes())
    data[offset + 700] ^= 1
    archive.write_bytes(data)
    checksum.write_text(f"{signing.digest(data)}  {archive.name}\n")
    with pytest.raises(signing.SigningError, match="CRC mismatch"):
        signing.stage(archive, tmp_path / "corrupt", checksum)
    assert not (tmp_path / "corrupt").exists()


@pytest.mark.parametrize(
    "change", ["filebytes", "coverage", "publisher", "signedhash", "timestamp"]
)
def test_publisher_guard_rejects_inconsistent_final_evidence(
    staged, tmp_path, monkeypatch, change
):
    folder, _, _ = staged
    mock_sign(folder, monkeypatch)
    archive = signing.finalize(
        folder, tmp_path / "signed.zip", "Mock publisher metadata"
    )
    with zipfile.ZipFile(archive) as bundle:
        content = {info.filename: bundle.read(info) for info in bundle.infolist()}
    manifest = json.loads(content[signing.MANIFEST])
    if change == "filebytes":
        content["Audio8D/_internal/ffmpeg.exe"] += b"tampered"
    elif change == "coverage":
        manifest["files"].pop()
    elif change == "publisher":
        manifest["publisher"] = "Other publisher"
    elif change == "signedhash":
        manifest["signing"][0]["signedSha256"] = "0" * 64
    else:
        manifest["signing"][0]["timestampSignerSubject"] = ""
    content[signing.MANIFEST] = json.dumps(manifest).encode()
    with zipfile.ZipFile(archive, "w") as bundle:
        for name, data in content.items():
            bundle.writestr(name, data)
    with pytest.raises(signing.SigningError):
        signing.verify_signed_archive(archive, "Mock publisher metadata")
