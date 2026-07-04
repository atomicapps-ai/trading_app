# Deploying TradeAgent on your domain (Cloudflare Tunnel + Access)

Goal: reach the app from any phone/computer at **https://app.tindex.ai**, with
login required, while the app + IB Gateway keep running on your always-on PC.
Everyone hitting that URL sees the **same** backend (same DB, positions,
strategies, jobs) — that's what makes all devices consistent.

Cloudflare Tunnel connects your local app to Cloudflare over an **outbound**
connection — no open ports, no firewall changes, no exposing your home IP.
Cloudflare terminates TLS at the edge (so the PWA installs and cookies are
Secure), and Cloudflare Access gates who's allowed in.

## 0. Prerequisites

- `tindex.ai` is on Cloudflare (its nameservers point to Cloudflare).
- The app runs on the host and responds at `http://127.0.0.1:5000`
  (`.\run dev` or `.\run prod`).
- Two env values set in `.env` (then encrypted — see the bottom of SETUP.md):
  - `APP_AUTH_PASSWORD=<a strong passphrase>`  — the in-app login backstop
  - `PUBLIC_BASE_URL=https://app.tindex.ai`    — makes phone-push links open the site

## 1. Install cloudflared (on the always-on PC)

```powershell
winget install --id Cloudflare.cloudflared
# or download the .exe from https://github.com/cloudflare/cloudflared/releases
```

## 2. Authenticate + create the tunnel

```powershell
cloudflared tunnel login                 # browser opens -> pick the tindex.ai zone
cloudflared tunnel create tindex-app     # prints a Tunnel UUID + writes a creds .json
cloudflared tunnel route dns tindex-app app.tindex.ai
```

The create step writes credentials to `C:\Users\<you>\.cloudflared\<UUID>.json`.

## 3. Config file

Create `C:\Users\<you>\.cloudflared\config.yml`:

```yaml
tunnel: <UUID-from-step-2>
credentials-file: C:\Users\<you>\.cloudflared\<UUID>.json
ingress:
  - hostname: app.tindex.ai
    service: http://127.0.0.1:5000
  - service: http_status:404
```

Test it in the foreground:

```powershell
cloudflared tunnel run tindex-app
```

Open https://app.tindex.ai — you should hit the app's login page. Then install
it as a Windows service so it survives reboots:

```powershell
cloudflared service install
```

## 4. Cloudflare Access (who's allowed in)

In the Cloudflare dashboard → **Zero Trust → Access → Applications → Add an
application → Self-hosted**:

- **Application domain:** `app.tindex.ai`
- **Policy:** Action = *Allow*; Include = *Emails* → your email address(es).
- Session duration: e.g. 24h.

Now Cloudflare requires SSO / one-time-PIN before anyone reaches the app; the
app's own `APP_AUTH_PASSWORD` is the second layer behind it.

## 5. Notes

- The app still binds `127.0.0.1:5000`; only cloudflared talks to it.
- Behind the tunnel the app sees `http` from cloudflared but honors
  `X-Forwarded-Proto: https`, so the session cookie's `Secure` flag is set
  correctly and the PWA (which requires HTTPS) installs from `app.tindex.ai`.
- Want a different hostname (apex `tindex.ai` or `trade.tindex.ai`)? Change it
  in step 2's `route dns`, step 3's `hostname`, `PUBLIC_BASE_URL`, and the
  Access application domain.
- IBKR gateway keeps running on this PC as before (IB Gateway auto-restart /
  IBC handles its nightly restart; you can also restart it remotely).
