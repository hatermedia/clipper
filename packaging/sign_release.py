"""Create the Clipper release signing key and sign SHA256SUMS files.

The private key never belongs in the repository, on GitHub, or in CI logs.
Keep it on the release machine (ideally on removable or encrypted storage).

    # once
    python packaging/sign_release.py keygen --out D:/keys/clipper-release.key
    #   -> prints the public key; paste it into UPDATE_PUBLIC_KEYS in
    #      src/clipper/update.py and ship that build first.

    # every release, after packaging/checksums.ps1
    python packaging/sign_release.py sign packaging/release/SHA256SUMS-0.9.1.txt \
        --key D:/keys/clipper-release.key
    #   -> writes SHA256SUMS-0.9.1.txt.sig; upload it next to the checksums.

    python packaging/sign_release.py verify packaging/release/SHA256SUMS-0.9.1.txt
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from clipper import signing  # noqa: E402
from clipper.update import UPDATE_PUBLIC_KEYS, verify_checksums_signature  # noqa: E402


def _read_key(path: Path) -> bytes:
    text = path.read_text(encoding="ascii").strip()
    secret = bytes.fromhex(text)
    if len(secret) != 32:
        raise SystemExit(f"{path} is not a 32-byte hex Ed25519 seed")
    return secret


def keygen(out: Path) -> int:
    out = out.expanduser().resolve()
    try:
        out.relative_to(ROOT)
    except ValueError:
        pass
    else:
        raise SystemExit("Refusing to write the private key inside the repository.")
    if out.exists():
        raise SystemExit(f"{out} already exists; refusing to overwrite a signing key.")
    secret = os.urandom(32)
    out.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="ascii") as handle:
        handle.write(secret.hex() + "\n")
    print(f"Private key written to {out} (keep it offline, never commit it).")
    print("Public key (add to UPDATE_PUBLIC_KEYS in src/clipper/update.py):")
    print(signing.public_key(secret).hex())
    return 0


def sign(checksums: Path, key: Path) -> int:
    secret = _read_key(key.expanduser())
    data = checksums.read_bytes()
    signature = signing.sign(secret, data)
    target = checksums.with_name(checksums.name + ".sig")
    target.write_text(signature.hex() + "\n", encoding="ascii")
    public = signing.public_key(secret).hex()
    print(f"Signed {checksums.name} -> {target.name}")
    if public not in UPDATE_PUBLIC_KEYS:
        print(
            "WARNING: this key is not in UPDATE_PUBLIC_KEYS; installed apps will "
            "reject this signature once signing is enforced.",
            file=sys.stderr,
        )
    return 0


def verify(checksums: Path, keys: list[str]) -> int:
    signature = checksums.with_name(checksums.name + ".sig")
    if not signature.is_file():
        raise SystemExit(f"Missing {signature.name}")
    allowed = tuple(keys) or UPDATE_PUBLIC_KEYS
    if not allowed:
        raise SystemExit("No public key given and UPDATE_PUBLIC_KEYS is empty.")
    ok = verify_checksums_signature(
        checksums.read_bytes(), signature.read_text(encoding="ascii"), allowed
    )
    print("signature OK" if ok else "signature INVALID")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p_keygen = sub.add_parser("keygen", help="create a new signing key")
    p_keygen.add_argument("--out", type=Path, required=True)
    p_sign = sub.add_parser("sign", help="sign a SHA256SUMS file")
    p_sign.add_argument("checksums", type=Path)
    p_sign.add_argument("--key", type=Path, required=True)
    p_verify = sub.add_parser("verify", help="verify a signed SHA256SUMS file")
    p_verify.add_argument("checksums", type=Path)
    p_verify.add_argument("--public-key", action="append", default=[])
    args = parser.parse_args(argv)
    if args.command == "keygen":
        return keygen(args.out)
    if args.command == "sign":
        return sign(args.checksums, args.key)
    return verify(args.checksums, args.public_key)


if __name__ == "__main__":
    raise SystemExit(main())
