"""app_url — print the base URL the app is actually reachable at.

Probes the public tunnel (https://app.tindex.ai) then localhost and prints the
first that answers /health, so you (or a script) always target a working base.

    python -m scripts.app_url            # -> https://app.tindex.ai   (or the local URL)
    python -m scripts.app_url --all      # show every candidate + reachable?
    python -m scripts.app_url --path /pending   # print base + path
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true", help="probe and list every candidate")
    ap.add_argument("--path", default="", help="append this path to the resolved base")
    a = ap.parse_args()
    from services import app_url

    if a.all:
        for base in app_url.candidates():
            ok = app_url.probe(base)
            print(f"{'OK  ' if ok else 'down'}  {base}")
        return
    base, reachable = app_url.resolve_base_url()
    if not reachable:
        print(f"# WARNING: no base reachable; falling back to {base}", file=sys.stderr)
    print(base + (a.path if a.path.startswith("/") else ("/" + a.path if a.path else "")))


if __name__ == "__main__":
    main()
