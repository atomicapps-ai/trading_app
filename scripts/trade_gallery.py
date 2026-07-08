"""trade_gallery — render detected trades as candlestick charts for VISUAL CONFIRMATION.

Takes a trade ledger (from a bt_*.py) + the 1-minute bars, and renders each sampled trade as a
self-contained HTML gallery: candlesticks around the trade with the opening-range box, entry / stop /
target price lines, and the entry candle highlighted. Optional reference frames from the source video
are embedded alongside so a human can confirm the code fires where the strategy actually sets up.

  python scripts/trade_gallery.py --ledger data/research/strategy_results/one_box_scalper_ledger.json \
      --frames research/video_library/day_intra/FEmD-hK1-yU/frames/frame_00300s.jpg,.../frame_00435s.jpg \
      --sample 30 --out data/research/strategy_results/one_box_scalper_gallery.html
"""
from __future__ import annotations
import argparse, base64, json, sys
from datetime import time
from pathlib import Path
import numpy as np, pandas as pd

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "historical_1m"


_CACHE: dict[str, pd.DataFrame] = {}


def _load_sym(sym: str) -> pd.DataFrame | None:
    if sym in _CACHE:
        return _CACHE[sym]
    p = SRC / f"{sym}.parquet"
    if not p.exists():
        _CACHE[sym] = None; return None
    df = pd.read_parquet(p)
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    df = df.tz_convert("America/New_York")
    df["_d"] = df.index.date
    _CACHE[sym] = df
    return df


def load_session(sym: str, date: str) -> pd.DataFrame | None:
    df = _load_sym(sym)
    if df is None:
        return None
    d = pd.Timestamp(date).date()
    s = df[df["_d"] == d].between_time(time(9, 30), time(12, 30), inclusive="left")
    return s if len(s) else None


def sample_trades(ledger: list[dict], n: int) -> list[dict]:
    wins = [t for t in ledger if t["r_gross"] > 0]
    losses = [t for t in ledger if t["r_gross"] <= 0]
    def spread(lst, k):
        if not lst or k <= 0:
            return []
        step = max(1, len(lst) // k)
        return lst[::step][:k]
    half = n // 2
    return spread(wins, half) + spread(losses, n - half)


def b64(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode() if path.exists() else ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ledger", required=True)
    ap.add_argument("--frames", default="")
    ap.add_argument("--sample", type=int, default=30)
    ap.add_argument("--title", default="One Box Scalper — trade confirmation")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    ledger = json.loads(Path(args.ledger).read_text())
    if not ledger:
        sys.exit("empty ledger")
    picks = sample_trades(ledger, args.sample)

    cards = []
    for t in picks:
        s = load_session(t["symbol"], t["date"])
        if s is None:
            continue
        bars = [{"o": float(o), "h": float(h), "l": float(l), "c": float(c),
                 "t": ts.strftime("%H:%M")}
                for ts, o, h, l, c in zip(s.index, s["open"], s["high"], s["low"], s["close"])]
        cards.append({
            "sym": t["symbol"], "date": t["date"], "dir": t["direction"],
            "box_high": t["box_high"], "box_low": t["box_low"],
            "entry": t["entry"], "stop": t["stop"], "target": t["target"],
            "entry_time": t["entry_time"], "exit_time": t["exit_time"],
            "r": t["r_gross"], "rnet": t.get("r_net", t["r_gross"]), "bars": bars,
        })

    refs = [b64(Path(p)) for p in args.frames.split(",") if p.strip()]
    n_win = sum(1 for c in cards if c["r"] > 0)
    html = _TEMPLATE.replace("__TITLE__", args.title) \
        .replace("__SUB__", f"{len(cards)} sampled trades ({n_win} wins / {len(cards)-n_win} losses) "
                            f"of {len(ledger)} total — visual check: does the box + break + retest + "
                            f"entry/stop/2R match the strategy?") \
        .replace("__REFS__", json.dumps(refs)) \
        .replace("__DATA__", json.dumps(cards))
    Path(args.out).write_text(html, encoding="utf-8")
    print(f"wrote {args.out}  ({len(cards)} trade cards, {len(refs)} reference frames)")


_TEMPLATE = r"""<!doctype html><html><head><meta charset="utf-8"><title>__TITLE__</title>
<style>
 body{background:#0d1117;color:#e6edf3;font-family:system-ui,Segoe UI,Arial;margin:0;padding:20px}
 h1{font-size:20px;margin:0 0 4px} .sub{color:#9da7b3;font-size:13px;margin-bottom:16px;max-width:900px}
 .refs{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:20px}
 .refs img{max-height:200px;border:1px solid #30363d;border-radius:6px}
 .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(430px,1fr));gap:14px}
 .card{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:10px}
 .hd{display:flex;justify-content:space-between;font-size:13px;margin-bottom:6px}
 .win{color:#3fb950} .loss{color:#f85149} .muted{color:#9da7b3}
 canvas{width:100%;height:230px;display:block}
 .lg{font-size:11px;color:#9da7b3;margin-top:4px}
 .lg b{color:#e6edf3}
</style></head><body>
<h1>__TITLE__</h1><div class="sub">__SUB__</div>
<div class="refs" id="refs"></div><div class="grid" id="grid"></div>
<script>
const REFS=__REFS__, DATA=__DATA__;
const rd=document.getElementById('refs');
REFS.forEach(b=>{const i=new Image();i.src='data:image/jpeg;base64,'+b;rd.appendChild(i);});
function draw(cv,card){
  const dpr=window.devicePixelRatio||1, W=cv.clientWidth,H=cv.clientHeight;
  cv.width=W*dpr;cv.height=H*dpr;const x=cv.getContext('2d');x.scale(dpr,dpr);
  const bars=card.bars,n=bars.length;
  let lo=Math.min(...bars.map(b=>b.l),card.stop,card.target),
      hi=Math.max(...bars.map(b=>b.h),card.stop,card.target);
  const pad=(hi-lo)*0.08;lo-=pad;hi+=pad;
  const L=44,R=6,T=6,B=16,pw=W-L-R,ph=H-T-B;
  const X=i=>L+pw*(i+0.5)/n, Y=p=>T+ph*(hi-p)/(hi-lo), cw=Math.max(1.4,pw/n*0.62);
  // box (opening range)
  x.fillStyle='rgba(56,139,253,0.10)';x.fillRect(L,Y(card.box_high),pw,Y(card.box_low)-Y(card.box_high));
  x.strokeStyle='rgba(56,139,253,0.5)';x.strokeRect(L,Y(card.box_high),pw,Y(card.box_low)-Y(card.box_high));
  // level lines
  const line=(p,col,dash)=>{x.strokeStyle=col;x.setLineDash(dash||[]);x.beginPath();x.moveTo(L,Y(p));x.lineTo(W-R,Y(p));x.stroke();x.setLineDash([]);
    x.fillStyle=col;x.font='9px system-ui';x.fillText(p.toFixed(2),2,Y(p)+3);};
  line(card.entry,'#e3b341',[4,3]); line(card.stop,'#f85149',[4,3]); line(card.target,'#3fb950',[4,3]);
  // candles
  bars.forEach((b,i)=>{const up=b.c>=b.o,col=up?'#3fb950':'#f85149';x.strokeStyle=col;x.fillStyle=col;
    x.beginPath();x.moveTo(X(i),Y(b.h));x.lineTo(X(i),Y(b.l));x.stroke();
    const yo=Y(b.o),yc=Y(b.c);x.fillRect(X(i)-cw/2,Math.min(yo,yc),cw,Math.max(1,Math.abs(yc-yo)));
    if(b.t===card.entry_time){x.strokeStyle='#e3b341';x.lineWidth=1.5;x.strokeRect(X(i)-cw/2-1,Y(b.h)-2,cw+2,Y(b.l)-Y(b.h)+4);x.lineWidth=1;}
  });
}
DATA.forEach(card=>{
  const d=document.createElement('div');d.className='card';
  const cls=card.r>0?'win':'loss';
  d.innerHTML=`<div class="hd"><span><b>${card.sym}</b> <span class="muted">${card.date}</span> ·
    <span class="${card.dir==='long'?'win':'loss'}">${card.dir.toUpperCase()}</span></span>
    <span class="${cls}">${card.r>0?'+':''}${card.r}R <span class="muted">(net ${card.rnet})</span></span></div>
    <canvas></canvas>
    <div class="lg">box <b>${card.box_low}–${card.box_high}</b> · entry <b>${card.entry}</b> @${card.entry_time}
     · stop <b>${card.stop}</b> · 2R target <b>${card.target}</b> · exit @${card.exit_time}</div>`;
  document.getElementById('grid').appendChild(d);
  draw(d.querySelector('canvas'),card);
});
</script></body></html>"""


if __name__ == "__main__":
    main()
