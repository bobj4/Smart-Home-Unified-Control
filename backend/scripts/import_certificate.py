"""Take the HTTPS certificate this server's web server uses (deploy/linux/
smarthome cert-import reads the files and sends them here, on stdin: the
source on the first line, the certificate, SPLIT on a line, then the key). Only while Settings > Admin > HTTPS >
"Take the certificate from this server's web server" is on.

Prints one word: "off" (the setting is off), "same" (nothing new), or
"changed" (stored; HTTPS needs a restart to use it, when it is on).
Exit status 2 on a certificate the app refuses.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy.orm import Session  # noqa: E402

from app import db_config, init_db, tls  # noqa: E402
from app.audit import record_event  # noqa: E402
from app.login_policy import settings  # noqa: E402
from app.models import utcnow  # noqa: E402
from app.vault import VaultError  # noqa: E402

MAX_INPUT = tls.MAX_CERTIFICATE_CHARS + tls.MAX_KEY_CHARS + 1024
SPLIT = "-----SMARTHOME KEY FOLLOWS-----"


def parse(text: str) -> tuple[str, str, str]:
    """(source, certificate, key) from what cert-import sends."""
    source, _, rest = text.partition("\n")
    certificate, found, key = rest.partition(SPLIT)
    if not found:
        raise ValueError("no key in the input")
    return source.strip()[:300], certificate.strip() + "\n", key.strip() + "\n"


def apply(db: Session, source: str, certificate: str, key: str) -> str:
    """Store the certificate if the setting is on and it is new. Raises
    tls.TlsError or VaultError on one the app refuses."""
    row = settings(db)
    if not row.cert_auto_import:
        return "off"
    if row.tls_certificate and row.tls_certificate.strip() == certificate.strip():
        return "same"
    tls.save(db, certificate, key)
    row.cert_import_source = source or None
    row.cert_imported_at = utcnow()
    db.commit()
    record_event(db, "https_certificate_imported", details={"source": source})
    return "changed"


def main() -> int:
    try:
        source, certificate, key = parse(sys.stdin.read(MAX_INPUT))
    except ValueError as error:
        print(f"refused: {error}", file=sys.stderr)
        return 2
    init_db()
    with db_config.SessionLocal() as db:
        try:
            print(apply(db, source, certificate, key))
        except (tls.TlsError, VaultError) as error:
            print(f"refused: {error}", file=sys.stderr)
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
