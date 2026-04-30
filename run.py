"""
run.py - start the TradeAgent server.

Usage:
    python run.py dev                          (hot reload, info logging, 127.0.0.1)
    python run.py prod                         (no reload, 2 workers, 127.0.0.1)
    python run.py dev  --host 0.0.0.0          (LAN/Tailscale access; needs firewall rule)
    python run.py prod --host 100.x.y.z        (bind to a specific Tailscale IP)
    python run.py dev  --port 8080             (override port)

Phone access via Tailscale:
    1. Install Tailscale on this Windows box and on your phone, log in to the
       same tailnet.
    2. Find this machine's Tailscale IP (Tailscale tray icon) — looks like
       100.64.x.y.
    3. Allow Windows Defender Firewall TCP inbound on the chosen port.
    4. Launch with --host 0.0.0.0 (or that specific Tailscale IP).
    5. On your phone, open  http://<tailscale-ip>:5000  in Safari/Chrome.

Note: binding to 0.0.0.0 exposes the app on every interface this machine has.
On a trusted home network + Tailscale-only WAN this is fine; on a coffee-shop
Wi-Fi prefer the explicit Tailscale IP.
"""
import argparse
import subprocess
import sys


parser = argparse.ArgumentParser(add_help=True)
parser.add_argument("mode", nargs="?", default="dev", choices=["dev", "prod"])
parser.add_argument("--host", default="127.0.0.1",
                    help="Interface to bind. Default 127.0.0.1 (localhost only). "
                         "Use 0.0.0.0 or your Tailscale IP for phone access.")
parser.add_argument("--port", default="5000")
args = parser.parse_args()

base = [sys.executable, "-m", "uvicorn", "app:app",
        "--host", args.host, "--port", args.port]

if args.mode == "dev":
    cmd = base + ["--reload", "--log-level", "info"]
    label = "DEV (hot reload)"
else:
    cmd = base + ["--workers", "2", "--log-level", "warning"]
    label = "PROD"

display_host = "localhost" if args.host == "127.0.0.1" else args.host
print(f"TradeAgent {label} -> http://{display_host}:{args.port}")
if args.host != "127.0.0.1":
    print("  (binding to non-loopback — make sure Windows firewall allows this port)")

subprocess.run(cmd)
