"""Detached Ed25519 signatures over run bundles.

Requires ``pip install proofline[sign]``. The signed payload is the canonical
JSON of the bundle without its ``signatures`` field, so it covers every other
field including the volatile ones and ``bundle_digest`` — re-sealing a
tampered bundle invalidates the signature.
"""

from __future__ import annotations

import base64
import hashlib
import os
from pathlib import Path
from typing import Any

from .model import canonical_json, utc_now
from .storage import read_bundle, write_bundle

MISSING_CRYPTO_HINT = "signature support requires the sign extra: pip install proofline[sign]"

PRIVATE_KEY_NAME = "proofline-signing.pem"
PUBLIC_KEY_NAME = "proofline-signing.pub.pem"


def _crypto() -> tuple[Any, Any]:
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import ed25519
    except ImportError as exc:
        raise RuntimeError(MISSING_CRYPTO_HINT) from exc
    return ed25519, serialization


def signing_payload(bundle: dict[str, Any]) -> bytes:
    unsigned = {key: value for key, value in bundle.items() if key != "signatures"}
    return canonical_json(unsigned).encode("utf-8")


def generate_keypair(directory: str | Path) -> tuple[Path, Path]:
    """Write an Ed25519 keypair as PEM files and return (private_path, public_path)."""
    ed25519, serialization = _crypto()
    target = Path(directory)
    target.mkdir(parents=True, exist_ok=True)
    private_key = ed25519.Ed25519PrivateKey.generate()

    private_path = target / PRIVATE_KEY_NAME
    private_path.write_bytes(
        private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    if os.name == "posix":
        private_path.chmod(0o600)

    public_path = target / PUBLIC_KEY_NAME
    public_path.write_bytes(
        private_key.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    return private_path, public_path


def _load_private_key(path: str | Path) -> Any:
    ed25519, serialization = _crypto()
    key = serialization.load_pem_private_key(Path(path).read_bytes(), password=None)
    if not isinstance(key, ed25519.Ed25519PrivateKey):
        raise ValueError(f"not an Ed25519 private key: {path}")
    return key


def _public_key_b64(path: str | Path) -> str:
    ed25519, serialization = _crypto()
    key = serialization.load_pem_public_key(Path(path).read_bytes())
    if not isinstance(key, ed25519.Ed25519PublicKey):
        raise ValueError(f"not an Ed25519 public key: {path}")
    raw = key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return base64.b64encode(raw).decode("ascii")


def sign_bundle(
    bundle_or_path: str | Path | dict[str, Any], private_key_path: str | Path
) -> dict[str, Any]:
    """Append a signature entry; when given a path, the file is rewritten in place."""
    _, serialization = _crypto()
    target = bundle_or_path if isinstance(bundle_or_path, (str, Path)) else None
    bundle = read_bundle(target) if target is not None else bundle_or_path

    private_key = _load_private_key(private_key_path)
    public_raw = private_key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    entry = {
        "algorithm": "ed25519",
        "public_key": base64.b64encode(public_raw).decode("ascii"),
        "signature": base64.b64encode(private_key.sign(signing_payload(bundle))).decode("ascii"),
        "key_id": hashlib.sha256(public_raw).hexdigest()[:16],
        "signed_at": utc_now(),
    }
    bundle.setdefault("signatures", []).append(entry)
    if target is not None:
        write_bundle(target, bundle)
    return bundle


def verify_signatures(bundle: dict[str, Any]) -> list[str]:
    """Return verification errors for every signature entry in the bundle."""
    signatures = bundle.get("signatures")
    if signatures is None:
        return []
    if not isinstance(signatures, list) or not signatures:
        return ["signatures must be a non-empty array when present"]

    ed25519, _ = _crypto()
    payload = signing_payload(bundle)
    errors: list[str] = []
    for index, entry in enumerate(signatures):
        if not isinstance(entry, dict):
            errors.append(f"signatures[{index}] must be an object")
            continue
        if entry.get("algorithm") != "ed25519":
            errors.append(
                f"signatures[{index}].algorithm is unsupported: {entry.get('algorithm')!r}"
            )
            continue
        try:
            public_key = ed25519.Ed25519PublicKey.from_public_bytes(
                base64.b64decode(entry["public_key"], validate=True)
            )
            public_key.verify(base64.b64decode(entry["signature"], validate=True), payload)
        except Exception:
            errors.append(f"signatures[{index}] does not verify against the bundle")
    return errors


def signed_by(bundle: dict[str, Any], public_key_path: str | Path) -> bool:
    """True when the bundle carries a valid signature from the given public key."""
    expected = _public_key_b64(public_key_path)
    if verify_signatures(bundle):
        return False
    return any(
        entry.get("public_key") == expected
        for entry in bundle.get("signatures") or []
        if isinstance(entry, dict)
    )
