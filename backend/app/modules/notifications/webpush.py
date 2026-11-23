"""Web Push primitives: the VAPID key pair, the VAPID header and the payload encryption.

The functions are pure. They hold no state and do no I/O, so the worker and the tests
call them the same way.

- The VAPID key pair is a P-256 key (RFC 8292). The public key travels to the browser as
  the uncompressed point in base64url, the browser binds the subscription to it.
- `vapid_authorization` signs a short-lived ES256 JWT for the origin of the endpoint,
  because the push service accepts a request only from the key of the subscription.
- `encrypt` implements RFC 8291 with the content coding ``aes128gcm`` (RFC 8188) in one
  record. The push service sees only the ciphertext, the browser decrypts it with the
  private key of the subscription.
"""

from __future__ import annotations

import base64
import os
import time
from dataclasses import dataclass
from urllib.parse import urlsplit

import jwt
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

#: The record size of the single ``aes128gcm`` record. 4096 is the size that every push
#: service accepts, and a push payload stays below it.
RECORD_SIZE = 4096

#: The largest plaintext that fits one record: the record size minus the 16-byte tag and
#: the one padding delimiter byte.
MAX_PLAINTEXT = RECORD_SIZE - 17

#: Lifetime of the VAPID JWT. RFC 8292 allows at most 24 hours.
VAPID_TTL_SECONDS = 12 * 3600


def b64url(data: bytes) -> str:
    """Return ``data`` as base64url without padding."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def b64url_decode(text: str) -> bytes:
    """Decode base64url with or without padding."""
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


@dataclass(frozen=True, slots=True)
class VapidKeys:
    """A VAPID key pair: the private key as PKCS8 PEM, the public key as base64url point."""

    private_pem: str
    public_key: str


def _public_point(key: ec.EllipticCurvePrivateKey) -> bytes:
    return key.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )


def generate_vapid_keys() -> VapidKeys:
    """Make a new P-256 key pair for VAPID."""
    key = ec.generate_private_key(ec.SECP256R1())
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode("ascii")
    return VapidKeys(private_pem=pem, public_key=b64url(_public_point(key)))


def _load_private(pem: str) -> ec.EllipticCurvePrivateKey:
    key = serialization.load_pem_private_key(pem.encode("ascii"), password=None)
    if not isinstance(key, ec.EllipticCurvePrivateKey):
        raise ValueError("VAPID key is not an EC key")
    return key


def vapid_authorization(endpoint: str, keys: VapidKeys, subject: str, *, now: float) -> str:
    """Return the ``Authorization`` header value of a push request to ``endpoint``.

    The audience is the origin of the endpoint, because the push service checks exactly
    that. ``subject`` is a ``mailto:`` or ``https:`` contact of the platform.
    """
    parts = urlsplit(endpoint)
    claims = {
        "aud": f"{parts.scheme}://{parts.netloc}",
        "exp": int(now) + VAPID_TTL_SECONDS,
        "sub": subject,
    }
    token = jwt.encode(claims, _load_private(keys.private_pem), algorithm="ES256")
    return f"vapid t={token}, k={keys.public_key}"


def _hkdf(salt: bytes, ikm: bytes, info: bytes, length: int) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=length, salt=salt, info=info).derive(ikm)


def encrypt(
    plaintext: bytes,
    *,
    p256dh: str,
    auth: str,
    salt: bytes | None = None,
    sender_key: ec.EllipticCurvePrivateKey | None = None,
) -> bytes:
    """Encrypt ``plaintext`` for one subscription (RFC 8291, ``aes128gcm``).

    ``p256dh`` and ``auth`` are the keys of the subscription in base64url. ``salt`` and
    ``sender_key`` default to fresh random values; a test passes fixed ones to compare
    against the example of RFC 8291.

    Returns:
        The request body: the RFC 8188 header followed by the one encrypted record.

    Raises:
        ValueError: The plaintext does not fit one record.
    """
    if len(plaintext) > MAX_PLAINTEXT:
        raise ValueError("push payload too large")
    ua_public = b64url_decode(p256dh)
    auth_secret = b64url_decode(auth)
    record_salt = salt if salt is not None else os.urandom(16)
    as_key = sender_key if sender_key is not None else ec.generate_private_key(ec.SECP256R1())
    as_public = _public_point(as_key)
    ua_key = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ua_public)
    shared = as_key.exchange(ec.ECDH(), ua_key)
    ikm = _hkdf(auth_secret, shared, b"WebPush: info\x00" + ua_public + as_public, 32)
    cek = _hkdf(record_salt, ikm, b"Content-Encoding: aes128gcm\x00", 16)
    nonce = _hkdf(record_salt, ikm, b"Content-Encoding: nonce\x00", 12)
    record = AESGCM(cek).encrypt(nonce, plaintext + b"\x02", None)
    header = record_salt + RECORD_SIZE.to_bytes(4, "big") + bytes([len(as_public)]) + as_public
    return header + record


def now_seconds() -> float:
    """Return the current Unix time; the worker passes it to `vapid_authorization`."""
    return time.time()
