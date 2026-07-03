"""config_crypt.py — encrypt/decrypt local config so it can be source-controlled.

Bundles the machine-specific config files (.env and settings.yaml, whichever
exist) into ONE encrypted blob — ``config.enc`` — that is safe to commit. On
any machine, decrypt it with the shared passphrase to recreate the plaintext
files. The plaintext stays gitignored; only the encrypted blob is committed,
so a fresh clone needs just the passphrase instead of a manual .env rebuild.

    python -m scripts.config_crypt encrypt        # .env[,settings.yaml] -> config.enc
    python -m scripts.config_crypt decrypt        # config.enc -> .env[,settings.yaml]
    python -m scripts.config_crypt encrypt --files .env,settings.yaml,other.txt

Passphrase resolution (first that is set):
    --passphrase <value>  |  $CONFIG_PASSPHRASE  |  interactive prompt

Crypto: Fernet (AES-128-CBC + HMAC-SHA256) with a key derived from the
passphrase via scrypt (n=2**15). A fresh random salt is stored alongside the
ciphertext on every encrypt. The passphrase is the ONLY secret not in git —
keep it in a password manager. Use a strong one; anyone with the repo + the
passphrase can read the config.

NOTE: committing encrypted secrets is a deliberate tradeoff. Rotate any
credential that was ever committed if the passphrase is later exposed.
"""
from __future__ import annotations

import argparse
import base64
import getpass
import json
import os
import sys
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

ROOT = Path(__file__).resolve().parent.parent
BLOB = ROOT / "config.enc"
DEFAULT_FILES = [".env", "settings.yaml"]
_MAGIC = b"TRADEAGENT-CONFIG-V1"


def _derive_key(passphrase: str, salt: bytes) -> bytes:
    kdf = Scrypt(salt=salt, length=32, n=2**15, r=8, p=1)
    return base64.urlsafe_b64encode(kdf.derive(passphrase.encode("utf-8")))


def _get_passphrase(arg: str | None, *, confirm: bool) -> str:
    if arg:
        return arg
    env = os.environ.get("CONFIG_PASSPHRASE")
    if env:
        return env
    p = getpass.getpass("Config passphrase: ")
    if confirm:
        if p != getpass.getpass("Confirm passphrase: "):
            print("Passphrases do not match.", file=sys.stderr)
            sys.exit(1)
    if not p:
        print("Empty passphrase refused.", file=sys.stderr)
        sys.exit(1)
    return p


def cmd_encrypt(files: list[str], passphrase: str | None) -> int:
    bundle: dict[str, str] = {}
    for name in files:
        p = ROOT / name
        if p.exists():
            bundle[name] = p.read_text(encoding="utf-8")
        else:
            print(f"  (skip, not found: {name})")
    if not bundle:
        print("Nothing to encrypt — no config files found.", file=sys.stderr)
        return 1
    pw = _get_passphrase(passphrase, confirm=True)
    salt = os.urandom(16)
    token = Fernet(_derive_key(pw, salt)).encrypt(json.dumps(bundle).encode("utf-8"))
    # Format: MAGIC \n b64(salt) \n token   (all committed as config.enc)
    BLOB.write_bytes(_MAGIC + b"\n" + base64.b64encode(salt) + b"\n" + token)
    print(f"Encrypted {', '.join(bundle)} -> {BLOB.name} "
          f"({BLOB.stat().st_size} bytes). Commit {BLOB.name}.")
    return 0


def cmd_decrypt(passphrase: str | None, force: bool) -> int:
    if not BLOB.exists():
        print(f"{BLOB.name} not found — run encrypt first (or git pull).",
              file=sys.stderr)
        return 1
    raw = BLOB.read_bytes()
    try:
        magic, salt_b64, token = raw.split(b"\n", 2)
        assert magic == _MAGIC
        salt = base64.b64decode(salt_b64)
    except Exception:  # noqa: BLE001
        print(f"{BLOB.name} is malformed.", file=sys.stderr)
        return 1
    pw = _get_passphrase(passphrase, confirm=False)
    try:
        bundle = json.loads(Fernet(_derive_key(pw, salt)).decrypt(token))
    except InvalidToken:
        print("Wrong passphrase (or corrupt blob).", file=sys.stderr)
        return 1
    for name, content in bundle.items():
        dest = ROOT / name
        if dest.exists() and not force:
            # Don't clobber a locally-edited config without --force.
            if dest.read_text(encoding="utf-8") != content:
                print(f"  {name} exists and differs — use --force to overwrite. Skipped.")
                continue
        dest.write_text(content, encoding="utf-8")
        print(f"  wrote {name}")
    print("Done.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("encrypt", "decrypt"):
        s = sub.add_parser(name)
        s.add_argument("--passphrase", default=None,
                       help="passphrase (else $CONFIG_PASSPHRASE or prompt)")
        if name == "encrypt":
            s.add_argument("--files", default=",".join(DEFAULT_FILES),
                           help="comma-separated files to bundle")
        else:
            s.add_argument("--force", action="store_true",
                           help="overwrite locally-modified files")
    a = ap.parse_args()
    if a.cmd == "encrypt":
        return cmd_encrypt([f.strip() for f in a.files.split(",") if f.strip()],
                           a.passphrase)
    return cmd_decrypt(a.passphrase, a.force)


if __name__ == "__main__":
    raise SystemExit(main())
