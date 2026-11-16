"""Start the smart home server.

    python scripts/serve.py [--host 0.0.0.0] [--port 8000]

Serves HTTPS when it is turned on in Settings > Admin and a certificate is
saved; otherwise plain HTTP. Restart it after changing the HTTPS settings.
SECRETS_KEY must be set (the certificate's key is stored encrypted).
"""

import argparse
import logging
import os
import shutil
import sys
from pathlib import Path

import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import init_db, tls  # noqa: E402
from app.bootstrap import ensure_default_admin  # noqa: E402
from app.db_config import SessionLocal  # noqa: E402
from app.vault import VaultError  # noqa: E402


def setup_logging() -> None:
    """The server's own notes (integration problems, backups) and the vendor
    libraries' warnings go to the output (docker logs) too, not only uvicorn's
    request lines. Never secrets: the app logs reasons, not data."""
    logging.basicConfig(
        level=logging.WARNING, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    logging.getLogger("app").setLevel(logging.INFO)
    for vendor in ("pycync", "pyeconet", "samsungtvws"):
        logging.getLogger(vendor).setLevel(logging.WARNING)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    # Listening on every address is the point: phones on the home network.
    parser.add_argument("--host", default="0.0.0.0")  # nosec B104
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    setup_logging()
    init_db()
    first_password = os.environ.get("FIRST_ADMIN_PASSWORD", "").strip() or None
    with SessionLocal() as db:
        if ensure_default_admin(db, first_password):
            # The password itself never goes in the log.
            if first_password:
                print('First start: created the account "admin" with the password in')
                print(
                    "FIRST_ADMIN_PASSWORD (deploy/.env); change it in Settings > My account."
                )
            else:
                print('First start: log in with username "admin" and password "admin",')
                print("then change the password in Settings > My account.")
    with SessionLocal() as db:
        try:
            files = tls.server_files(db)
        except VaultError as error:
            print(f"HTTPS is on but the certificate key cannot be read: {error}")
            return 1
    ssl: dict[str, str] = {}
    if files:
        ssl = {"ssl_certfile": str(files[0]), "ssl_keyfile": str(files[1])}
        print(f"Serving HTTPS on port {args.port}")
    else:
        print(f"Serving HTTP on port {args.port} (HTTPS is off in Settings > Admin)")
    try:
        uvicorn.run("main:app", host=args.host, port=args.port, **ssl)  # type: ignore[arg-type]
    finally:
        if files:
            shutil.rmtree(files[0].parent, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
