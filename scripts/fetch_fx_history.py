"""fetch_fx_history.py — pull YEARS of FX + gold intraday from IBKR (paged).

MUST run on a machine with IB Gateway/TWS up + API enabled (the sandbox can't
reach a local gateway). Pages backward in chunks, so deep 5m history is SLOW
(IBKR pacing ~3s/chunk): years of 5m for ~10 symbols can take 1–2h — run it
once, ideally overnight.

Usage:
    python scripts/fetch_fx_history.py                       # 30m+5m, 2015→now, 9 FX + gold
    python scripts/fetch_fx_history.py --start 2018-01-01 --intervals 30m
    python scripts/fetch_fx_history.py --symbols XAUUSD,EURUSD --intervals 5m
"""
import argparse
import asyncio

from services import hf_data_service as hf

DEFAULT = ["EURUSD", "USDJPY", "EURJPY", "GBPJPY", "AUDJPY", "EURAUD",
           "EURCAD", "GBPUSD", "AUDUSD", "XAUUSD"]


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2015-01-01")
    ap.add_argument("--intervals", default="30m,5m")
    ap.add_argument("--symbols", default=",".join(DEFAULT))
    a = ap.parse_args()
    syms = [s.strip().upper() for s in a.symbols.split(",") if s.strip()]
    ivs = [i.strip() for i in a.intervals.split(",") if i.strip()]
    print(f"IBKR fetch: {len(syms)} symbols × {ivs} from {a.start} (paged — be patient)\n")
    for iv in ivs:
        for s in syms:
            r = await hf.fetch_and_save(s, source="ibkr", start=a.start, interval=iv)
            if r.get("ok"):
                print(f"  {s:8} {iv:4} ok rows={r.get('rows'):>7}  {r.get('first')} .. {r.get('last')}")
            else:
                print(f"  {s:8} {iv:4} ERR {str(r.get('error'))[:90]}")


if __name__ == "__main__":
    asyncio.run(main())
