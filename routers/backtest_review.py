"""Backtest Review — browse each strategy's winner/loser trade galleries + per-trade metrics.

Reads the artifacts produced by scripts/render_backtest_images.py:
  data/backtest_images/<strategy>/{manifest.json, winners/*.png, losers/*.png, gallery.html}
and the trade ledgers in data/research/strategy_results/. Self-contained dark-theme pages so it
slots in now and can be repurposed into the live /strategies views later.

Routes:
  GET /backtest-review            -> strategy list (metrics + status badges)
  GET /backtest-review/{strategy} -> Metrics / Winners / Losers tabs + trade table
Images are served by the /bt-images static mount (app.py).
"""
from __future__ import annotations
import json
import statistics
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from services.settings_service import DATA_DIR

router = APIRouter()
IMG_ROOT = DATA_DIR / "backtest_images"
RESULTS = DATA_DIR / "research" / "strategy_results"

# status/verdict per strategy (live book vs research)
_STATUS = {
    "momentum_breakout": ("LIVE", "#3fb950"), "fear_dip_reversion": ("LIVE", "#3fb950"),
    "macd_run": ("LIVE", "#3fb950"), "coil_breakout": ("LIVE", "#3fb950"),
    "rsi_pullback": ("CANDIDATE", "#58a6ff"), "band_extreme_fade": ("CANDIDATE", "#58a6ff"),
    "one_box_scalper": ("EXCEPTION", "#e3b341"),
    "three_line_strike": ("REJECTED", "#f85149"), "orb5_2R": ("REJECTED", "#f85149"),
}


def _ledger_for(strategy: str) -> list[dict]:
    for name in (f"{strategy}_ledger.json", f"{strategy}_swing_ledger.json"):
        p = RESULTS / name
        if p.exists():
            try:
                return json.loads(p.read_text())
            except Exception:  # noqa: BLE001
                return []
    return []


def _pf(rs):
    w = sum(x for x in rs if x > 0); l = -sum(x for x in rs if x <= 0)
    return round(w / l, 2) if l > 0 else 0.0


def _metrics(strategy: str, manifest: dict) -> dict:
    led = _ledger_for(strategy)
    g = [t.get("r_gross", t.get("r", 0)) for t in led]
    net = [t.get("r_net", t.get("r_gross", t.get("r", 0))) for t in led]
    n = len(g)
    wins = sum(1 for x in g if x > 0)
    m = {"n": n or manifest.get("n_total", 0),
         "win": round(wins / n * 100, 1) if n else 0.0,
         "gross_pf": _pf(g) if g else 0.0, "net_pf": _pf(net) if net else 0.0,
         "net_avg_r": round(statistics.mean(net), 3) if net else 0.0,
         "interval": manifest.get("interval", ""), "source": manifest.get("source", "")}
    # OOS + control from the summary json if present
    sp = RESULTS / f"{strategy}.json"
    if sp.exists():
        try:
            s = json.loads(sp.read_text())
            oo = s.get("net_OOS") or s.get("out_sample") or {}
            ct = s.get("control_OOS") or s.get("control") or {}
            m["oos_pf"] = oo.get("PF"); m["ctrl_pf"] = ct.get("PF")
        except Exception:  # noqa: BLE001
            pass
    return m


def _strategies() -> list[dict]:
    out = []
    if not IMG_ROOT.exists():
        return out
    for d in sorted(IMG_ROOT.iterdir()):
        mf = d / "manifest.json"
        if not mf.exists():
            continue
        try:
            manifest = json.loads(mf.read_text())
        except Exception:  # noqa: BLE001
            continue
        status, color = _STATUS.get(d.name, ("RESEARCH", "#9da7b3"))
        out.append({"name": d.name, "manifest": manifest, "status": status, "color": color,
                    "metrics": _metrics(d.name, manifest)})
    return out


_HEAD = """<meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<style>body{background:#0d1117;color:#e6edf3;font-family:system-ui,Segoe UI,Arial;margin:0;padding:20px}
a{color:#58a6ff;text-decoration:none}h1{font-size:20px;margin:0 0 12px}
.badge{font-size:10px;font-weight:700;padding:2px 7px;border-radius:10px;color:#0d1117}
table{border-collapse:collapse;width:100%;font-size:12px}th,td{padding:5px 8px;border-bottom:1px solid #21262d;text-align:right}
th:first-child,td:first-child{text-align:left}th{color:#9da7b3;font-weight:600}
.card{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:12px 14px;margin-bottom:10px;display:flex;justify-content:space-between;align-items:center}
.m{color:#9da7b3;font-size:12px}.m b{color:#e6edf3}.w{color:#3fb950}.l{color:#f85149}
.tabs{display:flex;gap:6px;margin:14px 0}.tab{padding:6px 14px;background:#161b22;border:1px solid #30363d;border-radius:6px;cursor:pointer;font-size:13px}
.tab.on{background:#21262d;color:#fff;border-color:#58a6ff}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:10px}
figure{margin:0;background:#161b22;border:1px solid #30363d;border-radius:6px;padding:5px}
figure img{width:100%;display:block;border-radius:4px}figcaption{font-size:11px;color:#9da7b3;padding:4px 2px}
.hide{display:none}</style>"""


@router.get("/backtest-review", response_class=HTMLResponse)
async def review_list():
    rows = _strategies()
    cards = []
    for r in rows:
        m = r["metrics"]
        cards.append(
            f'<a class=card href="/backtest-review/{r["name"]}">'
            f'<div><b style="font-size:15px">{r["name"]}</b> '
            f'<span class=badge style="background:{r["color"]}">{r["status"]}</span><br>'
            f'<span class=m>{m["interval"]} · {m["n"]} trades · win <b>{m["win"]}%</b> · '
            f'gross PF <b>{m["gross_pf"]}</b> · net PF <b>{m["net_pf"]}</b> · avg <b>{m["net_avg_r"]}</b>R</span></div>'
            f'<div class=m>{r["manifest"].get("n_win",0)} <span class=w>win</span> / '
            f'{r["manifest"].get("n_loss",0)} <span class=l>loss</span> imaged →</div></a>')
    return HTMLResponse(f"{_HEAD}<h1>Backtest Review</h1>"
                        f'<div class=m style="margin-bottom:12px">Click a strategy to review its winner / loser trade '
                        f'galleries and per-trade metrics. {len(rows)} strategies imaged.</div>{"".join(cards)}')


@router.get("/backtest-review/{strategy}", response_class=HTMLResponse)
async def review_detail(strategy: str):
    d = IMG_ROOT / strategy
    mf = d / "manifest.json"
    if not mf.exists():
        return HTMLResponse(f"{_HEAD}<h1>{strategy}</h1><p class=m>No images yet. "
                            f'<a href="/backtest-review">← back</a></p>', status_code=404)
    manifest = json.loads(mf.read_text())
    m = _metrics(strategy, manifest)
    status, color = _STATUS.get(strategy, ("RESEARCH", "#9da7b3"))
    trades = manifest.get("trades", [])
    wins = [t for t in trades if t["outcome"] == "win"]
    loss = [t for t in trades if t["outcome"] == "loss"]

    def cells(ts):
        return "".join(
            f'<figure><a href="/bt-images/{strategy}/{t["image"]}" target=_blank>'
            f'<img loading=lazy src="/bt-images/{strategy}/{t["image"]}"></a>'
            f'<figcaption>{t["symbol"]} {t["date"]} {t["direction"]} '
            f'<b class="{"w" if t["outcome"]=="win" else "l"}">{t["r_gross"]:+}R</b></figcaption></figure>'
            for t in ts)

    def table(ts):
        rows = "".join(
            f'<tr><td>{t["symbol"]}</td><td>{t["date"]}</td><td>{t["direction"]}</td>'
            f'<td>{t.get("entry","")}</td><td>{t.get("stop","")}</td><td>{t.get("target","")}</td>'
            f'<td class="{"w" if t["r_gross"]>0 else "l"}">{t["r_gross"]:+}</td>'
            f'<td>{t.get("r_net","")}</td></tr>' for t in ts)
        return ("<table><tr><th>symbol</th><th>date</th><th>dir</th><th>entry</th><th>stop</th>"
                f"<th>target</th><th>R gross</th><th>R net</th></tr>{rows}</table>")

    oos = f' · OOS PF <b>{m["oos_pf"]}</b> vs control <b>{m.get("ctrl_pf")}</b>' if m.get("oos_pf") else ""
    html = f"""{_HEAD}
<a href="/backtest-review" class=m>← all strategies</a>
<h1>{strategy} <span class=badge style="background:{color}">{status}</span></h1>
<div class=m style="margin-bottom:6px">{m['interval']} · <b>{m['n']}</b> trades · win <b>{m['win']}%</b>
 · gross PF <b>{m['gross_pf']}</b> · net PF <b>{m['net_pf']}</b> · net avg <b>{m['net_avg_r']}</b>R{oos}<br>
 <span style="font-size:11px">{m['source']}</span></div>
<div class=tabs>
 <div class=tab onclick="show('win',this)">✓ Winners ({len(wins)})</div>
 <div class="tab on" onclick="show('all',this)">Metrics / Trades</div>
 <div class=tab onclick="show('loss',this)">✗ Losers ({len(loss)})</div></div>
<div id=win class=hide><div class=grid>{cells(wins)}</div></div>
<div id=loss class=hide><div class=grid>{cells(loss)}</div></div>
<div id=all>
 <div class=m style="margin-bottom:6px">Per-trade entry / stop / target / R (sampled across the full period —
 confirm the setups match the strategy).</div>
 <h3 class=w style="color:#3fb950">Winners</h3>{table(wins)}
 <h3 class=l style="color:#f85149;margin-top:16px">Losers</h3>{table(loss)}</div>
<script>function show(id,el){{for(const s of ['win','loss','all'])document.getElementById(s).classList.add('hide');
document.getElementById(id).classList.remove('hide');
for(const t of document.querySelectorAll('.tab'))t.classList.remove('on');el.classList.add('on');}}</script>"""
    return HTMLResponse(html)
