from __future__ import annotations

import hashlib
import io
from pathlib import Path

import pytest

from clipper import signing, update

# RFC 8032 section 7.1 test vectors.
RFC_VECTORS = [
    (
        "9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60",
        "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a",
        "",
        "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b",
    ),
    (
        "4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb",
        "3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c",
        "72",
        "92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da085ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00",
    ),
    (
        "c5aa8df43f9f837bedb7442f31dcb7b166d38535076f094b85ce3a2e0b4458f7",
        "fc51cd8e6218a1a38da47ed00230f0580816ed13ba3303ac5deb911548908025",
        "af82",
        "6291d657deec24024827e69c3abe01a30ce548a284743a445e3680d7db5ac3ac18ff9b538d16f290ae67f760984dc6594a7c15e9716ed28dc027beceea1ec40a",
    ),
]

SECRET = bytes(range(32))
PUBLIC_HEX = signing.public_key(SECRET).hex()


@pytest.mark.parametrize("secret,public,message,signature", RFC_VECTORS)
def test_rfc8032_vectors(secret: str, public: str, message: str, signature: str) -> None:
    sk, pk, msg, sig = map(bytes.fromhex, (secret, public, message, signature))
    assert signing.public_key(sk) == pk
    assert signing.sign(sk, msg) == sig
    assert signing.verify(pk, msg, sig)


def test_verify_rejects_tampering_and_bad_lengths() -> None:
    message = b"abc123  ClipperSetup-9.9.9.exe\n"
    signature = signing.sign(SECRET, message)
    public = bytes.fromhex(PUBLIC_HEX)
    assert signing.verify(public, message, signature)
    assert not signing.verify(public, message + b"x", signature)
    flipped = bytes([signature[0] ^ 1]) + signature[1:]
    assert not signing.verify(public, message, flipped)
    assert not signing.verify(public[:31], message, signature)
    assert not signing.verify(public, message, signature[:63])
    other = signing.public_key(bytes(32))
    assert not signing.verify(other, message, signature)


def test_parse_signature_accepts_hex_and_base64() -> None:
    import base64

    signature = signing.sign(SECRET, b"x")
    assert signing.parse_signature(signature.hex() + "\n") == signature
    assert signing.parse_signature(base64.b64encode(signature).decode()) == signature
    with pytest.raises(ValueError):
        signing.parse_signature("not a signature")


class FakeResponse(io.BytesIO):
    def __init__(self, payload: bytes) -> None:
        super().__init__(payload)
        self.headers = {
            "Content-Type": "application/octet-stream",
            "Content-Length": str(len(payload)),
        }

    def __enter__(self):
        return self

    def __exit__(self, *args) -> None:
        self.close()


def _release(payload: bytes, *, signed: bool) -> update.ReleaseInfo:
    return update.ReleaseInfo(
        version="9.9.9",
        tag="v9.9.9",
        name="v9.9.9",
        notes="",
        page_url="https://example.test",
        published_at="",
        installer_name="ClipperSetup-9.9.9.exe",
        installer_url="https://example.test/ClipperSetup-9.9.9.exe",
        installer_size=len(payload),
        checksums_name="SHA256SUMS-9.9.9.txt",
        checksums_url="https://example.test/SHA256SUMS-9.9.9.txt",
        signature_name="SHA256SUMS-9.9.9.txt.sig" if signed else None,
        signature_url="https://example.test/SHA256SUMS-9.9.9.txt.sig" if signed else None,
    )


def _setup(monkeypatch, payload: bytes, signature: bytes | None) -> None:
    sums = f"{hashlib.sha256(payload).hexdigest()}  ClipperSetup-9.9.9.exe\n"
    monkeypatch.setattr(update, "_fetch_text", lambda *a, **k: sums)
    monkeypatch.setattr(
        update,
        "_fetch_bytes",
        lambda *a, **k: (signature.hex().encode() if signature is not None else b""),
    )
    monkeypatch.setattr(update, "_open_url", lambda *a, **k: FakeResponse(payload))
    monkeypatch.setattr(update, "authenticode_status", lambda _p: ("NotSigned", ""))


def test_enforced_signature_accepts_a_signed_release(tmp_path: Path, monkeypatch) -> None:
    payload = b"MZ" + b"x" * 4096
    sums = f"{hashlib.sha256(payload).hexdigest()}  ClipperSetup-9.9.9.exe\n".encode()
    monkeypatch.setattr(update, "UPDATE_PUBLIC_KEYS", (PUBLIC_HEX,))
    _setup(monkeypatch, payload, signing.sign(SECRET, sums))
    target = tmp_path / "ClipperSetup-9.9.9.exe"
    assert update.download_installer(_release(payload, signed=True), target) == target
    assert update.signature_enforced()


def test_enforced_signature_refuses_unsigned_release(tmp_path: Path, monkeypatch) -> None:
    payload = b"MZ" + b"x" * 4096
    monkeypatch.setattr(update, "UPDATE_PUBLIC_KEYS", (PUBLIC_HEX,))
    _setup(monkeypatch, payload, None)
    with pytest.raises(update.UpdateError, match="no checksum signature"):
        update.download_installer(
            _release(payload, signed=False), tmp_path / "ClipperSetup-9.9.9.exe"
        )


def test_enforced_signature_refuses_wrong_key(tmp_path: Path, monkeypatch) -> None:
    payload = b"MZ" + b"x" * 4096
    sums = f"{hashlib.sha256(payload).hexdigest()}  ClipperSetup-9.9.9.exe\n".encode()
    monkeypatch.setattr(update, "UPDATE_PUBLIC_KEYS", (PUBLIC_HEX,))
    attacker = signing.sign(b"\x07" * 32, sums)
    _setup(monkeypatch, payload, attacker)
    target = tmp_path / "ClipperSetup-9.9.9.exe"
    with pytest.raises(update.UpdateError, match="not signed by the Clipper release key"):
        update.download_installer(_release(payload, signed=True), target)
    assert not target.exists()


def test_broken_authenticode_signature_is_refused(tmp_path: Path, monkeypatch) -> None:
    payload = b"MZ" + b"x" * 4096
    _setup(monkeypatch, payload, None)
    monkeypatch.setattr(update, "authenticode_status", lambda _p: ("HashMismatch", "CN=x"))
    target = tmp_path / "ClipperSetup-9.9.9.exe"
    with pytest.raises(update.UpdateError, match="HashMismatch"):
        update.download_installer(_release(payload, signed=False), target)
    assert not target.exists()


def test_required_publisher_is_enforced(tmp_path: Path, monkeypatch) -> None:
    payload = b"MZ" + b"x" * 4096
    _setup(monkeypatch, payload, None)
    monkeypatch.setattr(update, "UPDATE_PUBLISHER", "CN=hatermedia")
    with pytest.raises(update.UpdateError, match="not signed by the Clipper publisher"):
        update.download_installer(
            _release(payload, signed=False), tmp_path / "ClipperSetup-9.9.9.exe"
        )
    monkeypatch.setattr(update, "authenticode_status", lambda _p: ("Valid", "CN=hatermedia, O=x"))
    target = tmp_path / "b" / "ClipperSetup-9.9.9.exe"
    assert update.download_installer(_release(payload, signed=False), target) == target


def test_release_payload_finds_signature_and_not_as_checksums() -> None:
    release = update._release_from_payload(
        {
            "tag_name": "v1.0.0",
            "assets": [
                {
                    "name": "SHA256SUMS-1.0.0.txt.sig",
                    "browser_download_url": "https://example.test/sig",
                },
                {
                    "name": "ClipperSetup-1.0.0.exe",
                    "browser_download_url": "https://example.test/setup",
                },
                {
                    "name": "SHA256SUMS-1.0.0.txt",
                    "browser_download_url": "https://example.test/sums",
                },
            ],
        }
    )
    assert release.checksums_name == "SHA256SUMS-1.0.0.txt"
    assert release.signature_name == "SHA256SUMS-1.0.0.txt.sig"
    assert release.has_signature
    restored = update.ReleaseInfo.from_dict(release.to_dict())
    assert restored.signature_url == "https://example.test/sig"


@pytest.mark.skipif(__import__("os").name != "nt", reason="Windows install paths")
def test_helper_only_stops_clipper_from_the_install_folder() -> None:
    lines = update._helper_script(
        Path("C:/Temp/clipper-update-x/ClipperSetup-9.9.9.exe"),
        Path(r"C:\Users\me\AppData\Local\Programs\Clipper\Clipper.exe"),
        Path(r"C:\Users\me\AppData\Local\Clipper\update.log"),
        relaunch=False,
        wait_pid=0,
    )
    script = "\n".join(lines)
    assert "/IM Clipper.exe" not in script
    assert "/IM " not in script  # only the installer's own PID may be killed
    assert r"$installDir = 'C:\Users\me\AppData\Local\Programs\Clipper'" in script
    assert "ExecutablePath.StartsWith($installDir" in script


def test_sign_release_script_round_trip(tmp_path: Path, monkeypatch) -> None:
    import importlib.util

    script = Path(__file__).resolve().parents[1] / "packaging" / "sign_release.py"
    spec = importlib.util.spec_from_file_location("sign_release", script)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    key = tmp_path / "keys" / "release.key"
    assert module.main(["keygen", "--out", str(key)]) == 0
    secret = bytes.fromhex(key.read_text().strip())
    sums = tmp_path / "SHA256SUMS-1.0.0.txt"
    sums.write_text("a" * 64 + "  ClipperSetup-1.0.0.exe\n", encoding="ascii")
    assert module.main(["sign", str(sums), "--key", str(key)]) == 0
    public = signing.public_key(secret).hex()
    assert module.main(["verify", str(sums), "--public-key", public]) == 0
    sums.write_text("b" * 64 + "  ClipperSetup-1.0.0.exe\n", encoding="ascii")
    assert module.main(["verify", str(sums), "--public-key", public]) == 1
    with pytest.raises(SystemExit):
        module.main(["keygen", "--out", str(key)])  # never overwrite a key
