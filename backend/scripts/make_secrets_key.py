"""Print a new SECRETS_KEY for deploy/.env (encrypts integration logins).

Run from backend/:  ../.venv/Scripts/python.exe -m scripts.make_secrets_key
Keep the key private. If it is lost, saved integration logins must be
entered again.
"""

from cryptography.fernet import Fernet


def main() -> int:
    print(Fernet.generate_key().decode())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
