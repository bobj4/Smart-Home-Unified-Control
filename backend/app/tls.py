"""The HTTPS certificate an owner uploads in Settings > Admin.

The certificate chain is stored as PEM; the private key is stored encrypted
with the vault. scripts/serve.py writes both to a private temporary folder
when the server starts, because uvicorn reads them from files.
"""

import os
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.x509.oid import NameOID
from sqlalchemy.orm import Session

from app import vault
from app.login_policy import settings

MAX_CERTIFICATE_CHARS = 64 * 1024
MAX_KEY_CHARS = 16 * 1024
TEMP_PREFIX = "smart-home-tls-"


class TlsError(ValueError):
    """The certificate or key cannot be used."""


def _public(key: Any) -> bytes:
    return bytes(
        key.public_bytes(
            serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )


def _name(name: x509.Name) -> str:
    common = name.get_attributes_for_oid(NameOID.COMMON_NAME)
    return str(common[0].value) if common else name.rfc4514_string()


def _chain(certificate_pem: str) -> list[x509.Certificate]:
    try:
        chain = x509.load_pem_x509_certificates(certificate_pem.encode())
    except ValueError:
        raise TlsError("the certificate is not a PEM certificate") from None
    if not chain:
        raise TlsError("the certificate is not a PEM certificate")
    return chain


def describe(certificate_pem: str) -> dict[str, Any]:
    chain = _chain(certificate_pem)
    leaf = chain[0]
    try:
        san = leaf.extensions.get_extension_for_class(x509.SubjectAlternativeName)
        names = [str(n) for n in san.value.get_values_for_type(x509.DNSName)] + [
            str(ip) for ip in san.value.get_values_for_type(x509.IPAddress)
        ]
    except x509.ExtensionNotFound:
        names = []
    return {
        "subject": _name(leaf.subject),
        "issuer": _name(leaf.issuer),
        "hostnames": names,
        "not_before": leaf.not_valid_before_utc.isoformat(),
        "not_after": leaf.not_valid_after_utc.isoformat(),
        "self_signed": leaf.issuer == leaf.subject,
        "chain_length": len(chain),
    }


def check(certificate_pem: str, key_pem: str) -> str:
    """Validate the pair; return the key as unencrypted PKCS#8 PEM."""
    if len(certificate_pem) > MAX_CERTIFICATE_CHARS or len(key_pem) > MAX_KEY_CHARS:
        raise TlsError("the file is too large to be a certificate or key")
    leaf = _chain(certificate_pem)[0]
    try:
        key = serialization.load_pem_private_key(key_pem.encode(), password=None)
    except TypeError:
        raise TlsError(
            "the private key is protected by a password; upload it without one"
        ) from None
    except (ValueError, NotImplementedError):
        raise TlsError("the private key is not a PEM private key") from None
    if _public(key.public_key()) != _public(leaf.public_key()):
        raise TlsError("the private key does not belong to the certificate")
    if leaf.not_valid_after_utc <= datetime.now(UTC):
        raise TlsError("the certificate has expired")
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()


def save(db: Session, certificate_pem: str, key_pem: str) -> None:
    """Validate and store (the caller commits). Raises TlsError or VaultError."""
    key = check(certificate_pem, key_pem)
    row = settings(db)
    row.tls_private_key = vault.encrypt({"key": key})
    row.tls_certificate = certificate_pem.strip() + "\n"


def remove(db: Session) -> None:
    row = settings(db)
    row.tls_certificate = None
    row.tls_private_key = None
    row.https_enabled = False


def server_files(db: Session) -> tuple[Path, Path] | None:
    """Write the certificate and key for uvicorn, or None if HTTPS is off.
    The caller deletes the folder (it is the files' parent) when it stops."""
    row = settings(db)
    if not (row.https_enabled and row.tls_certificate and row.tls_private_key):
        return None
    key = str(vault.decrypt(row.tls_private_key)["key"])
    # A server that was killed cannot clean up after itself; do it now.
    for stale in Path(tempfile.gettempdir()).glob(f"{TEMP_PREFIX}*"):
        shutil.rmtree(stale, ignore_errors=True)
    folder = Path(tempfile.mkdtemp(prefix=TEMP_PREFIX))
    paths = (folder / "cert.pem", folder / "key.pem")
    for path, text in zip(paths, (row.tls_certificate, key), strict=True):
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as handle:
            handle.write(text)
    return paths
