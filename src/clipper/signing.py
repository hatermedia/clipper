"""Ed25519 signatures for release metadata, using only the standard library.

Clipper's updater verifies a detached Ed25519 signature over the release
``SHA256SUMS`` file before trusting any hash in it. A matching SHA-256 alone
only proves the installer was not corrupted in transit; the signature proves
the checksums were produced by whoever holds the release signing key, which is
never stored on GitHub.

This is the RFC 8032 reference algorithm. Verification is all the app needs and
does not handle secrets. ``sign`` exists for the offline release script; it is
not constant-time, so only run it on a trusted build machine.
"""

from __future__ import annotations

import hashlib

_P = 2**255 - 19
_Q = 2**252 + 27742317777372353535851937790883648493


def _inv(value: int) -> int:
    return pow(value, _P - 2, _P)


_D = -121665 * _inv(121666) % _P
_SQRT_M1 = pow(2, (_P - 1) // 4, _P)


def _sha512(data: bytes) -> bytes:
    return hashlib.sha512(data).digest()


def _sha512_modq(data: bytes) -> int:
    return int.from_bytes(_sha512(data), "little") % _Q


def _add(left: tuple[int, int, int, int], right: tuple[int, int, int, int]):
    a = (left[1] - left[0]) * (right[1] - right[0]) % _P
    b = (left[1] + left[0]) * (right[1] + right[0]) % _P
    c = 2 * left[3] * right[3] * _D % _P
    d = 2 * left[2] * right[2] % _P
    e, f, g, h = b - a, d - c, d + c, b + a
    return (e * f % _P, g * h % _P, f * g % _P, e * h % _P)


def _mul(scalar: int, point: tuple[int, int, int, int]):
    result = (0, 1, 1, 0)
    while scalar > 0:
        if scalar & 1:
            result = _add(result, point)
        point = _add(point, point)
        scalar >>= 1
    return result


def _equal(left, right) -> bool:
    if (left[0] * right[2] - right[0] * left[2]) % _P:
        return False
    return (left[1] * right[2] - right[1] * left[2]) % _P == 0


def _recover_x(y: int, sign: int) -> int | None:
    if y >= _P:
        return None
    x2 = (y * y - 1) * _inv(_D * y * y + 1) % _P
    if x2 == 0:
        return None if sign else 0
    x = pow(x2, (_P + 3) // 8, _P)
    if (x * x - x2) % _P:
        x = x * _SQRT_M1 % _P
    if (x * x - x2) % _P:
        return None
    if (x & 1) != sign:
        x = _P - x
    return x


_GY = 4 * _inv(5) % _P
_GX = _recover_x(_GY, 0)
assert _GX is not None
_G = (_GX, _GY, 1, _GX * _GY % _P)


def _compress(point) -> bytes:
    zinv = _inv(point[2])
    x = point[0] * zinv % _P
    y = point[1] * zinv % _P
    return int.to_bytes(y | ((x & 1) << 255), 32, "little")


def _decompress(data: bytes):
    if len(data) != 32:
        return None
    y = int.from_bytes(data, "little")
    sign = y >> 255
    y &= (1 << 255) - 1
    x = _recover_x(y, sign)
    if x is None:
        return None
    return (x, y, 1, x * y % _P)


def _expand(secret: bytes) -> tuple[int, bytes]:
    if len(secret) != 32:
        raise ValueError("Ed25519 secret keys are 32 bytes")
    digest = _sha512(secret)
    scalar = int.from_bytes(digest[:32], "little")
    scalar &= (1 << 254) - 8
    scalar |= 1 << 254
    return scalar, digest[32:]


def public_key(secret: bytes) -> bytes:
    scalar, _prefix = _expand(secret)
    return _compress(_mul(scalar, _G))


def sign(secret: bytes, message: bytes) -> bytes:
    scalar, prefix = _expand(secret)
    public = _compress(_mul(scalar, _G))
    r = _sha512_modq(prefix + message)
    encoded_r = _compress(_mul(r, _G))
    h = _sha512_modq(encoded_r + public + message)
    s = (r + h * scalar) % _Q
    return encoded_r + int.to_bytes(s, 32, "little")


def verify(public: bytes, message: bytes, signature: bytes) -> bool:
    """Return True only for a valid Ed25519 signature."""

    if len(public) != 32 or len(signature) != 64:
        return False
    point_a = _decompress(public)
    if point_a is None:
        return False
    encoded_r = signature[:32]
    point_r = _decompress(encoded_r)
    if point_r is None:
        return False
    s = int.from_bytes(signature[32:], "little")
    if s >= _Q:
        return False
    h = _sha512_modq(encoded_r + public + message)
    return _equal(_mul(s, _G), _add(point_r, _mul(h, point_a)))


def parse_signature(text: str | bytes) -> bytes:
    """Read a detached signature file: 128 hex chars or base64, whitespace ok."""

    import base64
    import binascii

    raw = text.decode("ascii", errors="replace") if isinstance(text, bytes) else text
    lines = [
        line.strip()
        for line in raw.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    value = "".join(lines)
    try:
        if len(value) == 128:
            return bytes.fromhex(value)
        decoded = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError("Signature is not hex or base64") from exc
    if len(decoded) != 64:
        raise ValueError("Ed25519 signatures are 64 bytes")
    return decoded
