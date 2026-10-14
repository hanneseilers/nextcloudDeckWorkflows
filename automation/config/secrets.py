"""Optional encryption for the app passwords stored in config/nextcloud.yaml.

Shared hosting often means other accounts on the same machine can read
files they shouldn't be able to via misconfigured permissions - encrypting
the app password at rest is a defense-in-depth step for that case (not a
defense against someone who can already run code as this same user, who
could just read config/secret.key too).

Uses `cryptography`'s Fernet (AES-128-CBC + HMAC-SHA256, authenticated,
versioned, replay-resistant via its embedded timestamp) - a well-reviewed
high-level "recipe", not hand-rolled crypto. Deliberately NOT in
requirements.txt/vendored: unlike the project's other dependencies, it has
a compiled (Rust) extension that can't be vendored as plain source the way
PyYAML/requests/icalendar/python-dateutil are (see tools/build.sh) - install
it yourself (`pip install cryptography`) only if you actually want this
feature; everything else works fine without it.

Usage:
    python -m automation.config.secrets generate-key
    python -m automation.config.secrets encrypt "my app password"

Paste the result into nextcloud.yaml as `encrypted_app_password` instead
of `app_password` on that instance. website/src/Config.php decrypts the
exact same way (website/src/Fernet.php) - the same automation/config/secret.key
file has to be readable by whatever runs the website too.
"""

from __future__ import annotations

import sys

from automation.config.settings import REPO_ROOT

SECRET_KEY_PATH = REPO_ROOT / "config" / "secret.key"


def _load_key() -> bytes:
    if not SECRET_KEY_PATH.exists():
        raise FileNotFoundError(
            f"Missing {SECRET_KEY_PATH} - generate one with "
            "'python -m automation.config.secrets generate-key'"
        )
    return SECRET_KEY_PATH.read_text().strip().encode("ascii")


def generate_key() -> bytes:
    from cryptography.fernet import Fernet  # lazy: optional dependency, see module docstring

    return Fernet.generate_key()


def encrypt(plaintext: str) -> str:
    from cryptography.fernet import Fernet

    return Fernet(_load_key()).encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt(ciphertext: str) -> str:
    from cryptography.fernet import Fernet

    return Fernet(_load_key()).decrypt(ciphertext.encode("ascii")).decode("utf-8")


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Manage encrypted app passwords for config/nextcloud.yaml"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("generate-key", help=f"Create {SECRET_KEY_PATH} (fails if it already exists)")
    encrypt_parser = subparsers.add_parser("encrypt", help="Encrypt a plaintext app password")
    encrypt_parser.add_argument("plaintext")
    args = parser.parse_args()

    if args.command == "generate-key":
        if SECRET_KEY_PATH.exists():
            print(f"{SECRET_KEY_PATH} already exists - not overwriting it.", file=sys.stderr)
            sys.exit(1)
        SECRET_KEY_PATH.parent.mkdir(parents=True, exist_ok=True)
        SECRET_KEY_PATH.write_text(generate_key().decode("ascii"))
        SECRET_KEY_PATH.chmod(0o600)
        print(f"Wrote a new key to {SECRET_KEY_PATH}.")
        print("Keep it secret and back it up separately - losing it makes every encrypted password unrecoverable.")
    elif args.command == "encrypt":
        print(encrypt(args.plaintext))


if __name__ == "__main__":
    main()
