"""Envelope encryption for stored third-party credentials.

ARCHITECTURE §4: "Env-injected + envelope encryption (AES-256-GCM), KEK outside
the DB". §14 adds: "just-in-time decryption in the single worker that needs it,
never in an LLM context, never logged".

Why envelope rather than encrypting directly with the KEK: each credential gets
its own random DEK, so a stored ciphertext is bound to one credential and one
DEK. Rotating the KEK re-wraps DEKs only, which is a small, fast, auditable
operation over one column — not a decrypt-and-re-encrypt pass over every
customer's GSC refresh token.

**This module must never be importable from Zone U.** Invariant 1 names
``neptiq_security.credentials`` explicitly, and tools/check_zone_imports.py
enforces it. Zone U has no need to decrypt anything: it receives the fetch
targets it is told to fetch and returns blobs.
"""

from __future__ import annotations

import base64
import os
from dataclasses import dataclass
from typing import Final

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from neptiq_core.errors import NeptiqError

_KEY_LEN: Final = 32  # AES-256
_NONCE_LEN: Final = 12  # GCM standard; 96-bit nonces are the only sane choice
_VERSION: Final = 1


class CredentialError(NeptiqError):
    status = 500
    code = "credential_error"
    title = "Credential could not be sealed or opened"


@dataclass(frozen=True, slots=True)
class SealedCredential:
    """What gets stored in the ``credentials`` table.

    No plaintext, and no KEK material. ``kek_id`` records which KEK generation
    wrapped the DEK so rotation can find rows that still need re-wrapping.
    """

    version: int
    kek_id: str
    wrapped_dek: bytes
    dek_nonce: bytes
    ciphertext: bytes
    ct_nonce: bytes

    def to_columns(self) -> dict[str, object]:
        """Render for a parameterised INSERT. Base64 so the column is text."""
        return {
            "envelope_version": self.version,
            "kek_id": self.kek_id,
            "wrapped_dek": base64.b64encode(self.wrapped_dek).decode("ascii"),
            "dek_nonce": base64.b64encode(self.dek_nonce).decode("ascii"),
            "ciphertext": base64.b64encode(self.ciphertext).decode("ascii"),
            "ct_nonce": base64.b64encode(self.ct_nonce).decode("ascii"),
        }

    @classmethod
    def from_columns(cls, row: dict[str, object]) -> SealedCredential:
        def _b(key: str) -> bytes:
            raw = row[key]
            if not isinstance(raw, str):
                raise CredentialError(f"column {key} is not text")
            return base64.b64decode(raw)

        version = row["envelope_version"]
        kek_id = row["kek_id"]
        if not isinstance(version, int) or not isinstance(kek_id, str):
            raise CredentialError("malformed envelope metadata")
        return cls(
            version=version,
            kek_id=kek_id,
            wrapped_dek=_b("wrapped_dek"),
            dek_nonce=_b("dek_nonce"),
            ciphertext=_b("ciphertext"),
            ct_nonce=_b("ct_nonce"),
        )

    def __repr__(self) -> str:
        # Never render ciphertext or wrapped key material; reprs reach logs.
        return f"<SealedCredential v{self.version} kek={self.kek_id} ct={len(self.ciphertext)}B>"


def _load_kek(kek_base64: str) -> bytes:
    try:
        key = base64.b64decode(kek_base64, validate=True)
    except Exception as exc:
        raise CredentialError("KEK_BASE64 is not valid base64") from exc
    if len(key) != _KEY_LEN:
        raise CredentialError(f"KEK must be {_KEY_LEN} bytes (AES-256), got {len(key)}")
    return key


def seal(
    plaintext: bytes,
    *,
    kek_base64: str,
    kek_id: str,
    aad: bytes | None = None,
) -> SealedCredential:
    """Encrypt ``plaintext`` under a fresh DEK, wrap the DEK under the KEK.

    ``aad`` should carry the binding context — typically
    ``f"{org_id}:{provider}"``. GCM authenticates AAD without encrypting it, so
    a ciphertext moved to a different tenant's row fails to open rather than
    decrypting successfully into the wrong tenant. That turns a row-swap attack
    from a silent credential-confusion bug into a hard error.
    """
    if not plaintext:
        raise CredentialError("refusing to seal empty plaintext")

    kek = _load_kek(kek_base64)
    dek = os.urandom(_KEY_LEN)
    ct_nonce = os.urandom(_NONCE_LEN)
    dek_nonce = os.urandom(_NONCE_LEN)

    ciphertext = AESGCM(dek).encrypt(ct_nonce, plaintext, aad)
    wrapped_dek = AESGCM(kek).encrypt(dek_nonce, dek, kek_id.encode("utf-8"))

    return SealedCredential(
        version=_VERSION,
        kek_id=kek_id,
        wrapped_dek=wrapped_dek,
        dek_nonce=dek_nonce,
        ciphertext=ciphertext,
        ct_nonce=ct_nonce,
    )


def open_sealed(
    sealed: SealedCredential,
    *,
    kek_base64: str,
    aad: bytes | None = None,
) -> bytes:
    """Unwrap the DEK and decrypt.

    Callers must use the result immediately and not retain it. §14's
    "just-in-time decryption in the single worker that needs it" is a calling
    convention this module cannot enforce; it is stated in the docstring so a
    reviewer can catch a violation.
    """
    if sealed.version != _VERSION:
        raise CredentialError(f"unsupported envelope version {sealed.version}")

    kek = _load_kek(kek_base64)
    try:
        dek = AESGCM(kek).decrypt(sealed.dek_nonce, sealed.wrapped_dek, sealed.kek_id.encode())
    except InvalidTag as exc:
        raise CredentialError("DEK unwrap failed: wrong KEK or tampered row") from exc

    try:
        return AESGCM(dek).decrypt(sealed.ct_nonce, sealed.ciphertext, aad)
    except InvalidTag as exc:
        raise CredentialError(
            "credential decrypt failed: wrong AAD binding or tampered ciphertext"
        ) from exc


def rewrap(
    sealed: SealedCredential,
    *,
    old_kek_base64: str,
    new_kek_base64: str,
    new_kek_id: str,
) -> SealedCredential:
    """Re-wrap the DEK under a new KEK without touching the ciphertext.

    This is the point of envelope encryption: KEK rotation rewrites one small
    column and never decrypts the credential itself.
    """
    old_kek = _load_kek(old_kek_base64)
    new_kek = _load_kek(new_kek_base64)
    try:
        dek = AESGCM(old_kek).decrypt(sealed.dek_nonce, sealed.wrapped_dek, sealed.kek_id.encode())
    except InvalidTag as exc:
        raise CredentialError("DEK unwrap failed during rewrap") from exc

    new_nonce = os.urandom(_NONCE_LEN)
    return SealedCredential(
        version=sealed.version,
        kek_id=new_kek_id,
        wrapped_dek=AESGCM(new_kek).encrypt(new_nonce, dek, new_kek_id.encode("utf-8")),
        dek_nonce=new_nonce,
        ciphertext=sealed.ciphertext,
        ct_nonce=sealed.ct_nonce,
    )


def generate_kek_base64() -> str:
    """Generate a KEK for operator use. Never called by application code."""
    return base64.b64encode(os.urandom(_KEY_LEN)).decode("ascii")


__all__ = [
    "CredentialError",
    "SealedCredential",
    "generate_kek_base64",
    "open_sealed",
    "rewrap",
    "seal",
]
