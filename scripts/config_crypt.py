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
HOME = Path.home()
BLOB = ROOT / "config.enc"
# Everything a second machine needs to become the host. Project files are
# root-relative; ``~/...`` entries are home-relative (portable across machines
# even with different usernames since Path.home() resolves per machine); globs
# are expanded. The Cloudflare tunnel files let both laptops run the SAME
# tunnel — no manual copy after the first encrypt.
DEFAULT_FILES = [
    ".env",
    "settings.yaml",
    "~/.cloudflared/config.yml",
    "~/.cloudflared/cert.pem",
    "~/.cloudflared/*.json",     # tunnel credentials (<UUID>.json)
]
_MAGIC = b"TRADEAGENT-CONFIG-V1"


def _resolve_key(key: str) -> Path:
    """Map a stored bundle key back to a filesystem path on THIS machine.
    ``~/x`` -> home-relative; absolute -> as-is; else project-root-relative."""
    if key.startswith("~/") or key.startswith("~\\"):
        return HOME / key[2:]
    p = Path(key)
    return p if p.is_absolute() else ROOT / key


def _portable_key(path: Path) -> str:
    """Build a portable, forward-slashed key for a resolved path: prefer
    home- or project-relative so it re-resolves on the other machine."""
    try:
        return "~/" + path.relative_to(HOME).as_posix()
    except ValueError:
        pass
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _expand(patterns: list[str]) -> list[tuple[str, Path]]:
    """Resolve each pattern (plain / ~home / absolute / glob) to existing
    files, returned as (portable_key, path). Skips (and reports) misses."""
    out: list[tuple[str, Path]] = []
    seen: set[str] = set()
    for pat in patterns:
        is_glob = any(c in pat for c in "*?[")
        if is_glob:
            base = _resolve_key(pat)  # parent + name pattern
            matches = sorted(base.parent.glob(base.name))
            if not matches:
                print(f"  (skip, no match: {pat})")
            for m in matches:
                if m.is_file():
                    key = _portable_key(m)
                    if key not in seen:
                        seen.add(key); out.append((key, m))
        else:
            path = _resolve_key(pat)
            if path.exists():
                key = _portable_key(path)
                if key not in seen:
                    seen.add(key); out.append((key, path))
            else:
                print(f"  (skip, not found: {pat})")
    return out


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
    for key, path in _expand(files):
        try:
            bundle[key] = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError) as e:
            print(f"  (skip, unreadable: {key}: {e})")
    if not bundle:
        print("Nothing to encrypt — no config files found.", file=sys.stderr)
        return 1
    pw = _get_passphrase(passphrase, confirm=True)
    salt = os.urandom(16)
    token = Fernet(_derive_key(pw, salt)).encrypt(json.dumps(bundle).encode("utf-8"))
    # SINGLE-LINE base64 of MAGIC + salt(16) + token. No embedded newlines, so
    # git's CRLF conversion on Windows can't corrupt it (only a harmless
    # trailing newline, which decrypt strips). .gitattributes marks it binary too.
    BLOB.write_bytes(base64.b64encode(_MAGIC + salt + token))
    print(f"Encrypted {', '.join(bundle)} -> {BLOB.name} "
          f"({BLOB.stat().st_size} bytes). Commit {BLOB.name}.")
    return 0


def _unpack(raw: bytes) -> tuple[bytes, bytes]:
    """Return (salt, token) from config.enc. Handles the current single-line
    base64 format and the legacy MAGIC\\n b64(salt) \\n token format, tolerating
    CRLF that git may have injected on Windows."""
    s = raw.strip()
    # Current format: base64(MAGIC + salt + token)
    try:
        blob = base64.b64decode(s, validate=True)
        if blob[:len(_MAGIC)] == _MAGIC:
            body = blob[len(_MAGIC):]
            return body[:16], body[16:]
    except Exception:  # noqa: BLE001
        pass
    # Legacy multi-line format, CRLF-normalized
    norm = raw.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    parts = norm.split(b"\n")
    if parts and parts[0].strip() == _MAGIC and len(parts) >= 3:
        salt = base64.b64decode(parts[1].strip())
        token = b"".join(parts[2:]).strip()
        return salt, token
    raise ValueError("unrecognized config.enc format")


def cmd_decrypt(passphrase: str | None, force: bool) -> int:
    if not BLOB.exists():
        print(f"{BLOB.name} not found — run encrypt first (or git pull).",
              file=sys.stderr)
        return 1
    raw = BLOB.read_bytes()
    try:
        salt, token = _unpack(raw)
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
        dest = _resolve_key(name)
        if dest.exists() and not force:
            # Don't clobber a locally-edited config without --force.
            try:
                unchanged = dest.read_text(encoding="utf-8") == content
            except (UnicodeDecodeError, OSError):
                unchanged = False
            if not unchanged:
                print(f"  {name} exists and differs — use --force to overwrite. Skipped.")
                continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8")
        print(f"  wrote {name}  ->  {dest}")
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
