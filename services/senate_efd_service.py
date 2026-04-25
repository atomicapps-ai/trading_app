"""Senate Electronic Financial Disclosure (eFD) scraper.

Source: https://efdsearch.senate.gov/search/

The eFD has no public API. The flow is:
  1. GET  /search/home/   → CSRF token + session cookie
  2. POST /search/home/   → accept the prohibition agreement (302)
  3. POST /search/report/data/  → JSON list of filings (DataTables format)

Each Periodic Transaction Report (PTR) is rendered as a separate page with
a PDF download. Per user direction we DO NOT parse PDFs eagerly — we cache
the filing index only and parse on demand later when a user views the
politician's trades.

Refresh detection: the daily background job re-runs the search and compares
filing IDs to `senate_filings` table. New IDs trigger a "Refresh available"
badge in the UI. No webhooks; eFD has none.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import httpx

logger = logging.getLogger(__name__)

BASE = "https://efdsearch.senate.gov"
HOME = f"{BASE}/search/home/"
SEARCH_PAGE = f"{BASE}/search/"
REPORT_DATA = f"{BASE}/search/report/data/"

# Report type IDs from the eFD search form. 11 = Periodic Transaction Report
PTR_REPORT_TYPE = 11

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}

_CSRF_RE = re.compile(
    r"name=['\"]csrfmiddlewaretoken['\"][^>]*value=['\"]([^'\"]+)['\"]"
)
_PTR_LINK_RE = re.compile(
    r'<a\s+href="(/search/view/ptr/([0-9a-f-]+)/)"[^>]*>([^<]+)</a>',
    re.IGNORECASE,
)


# --------------------------------------------------------------------------- #
# Data models
# --------------------------------------------------------------------------- #


@dataclass
class SenateFiling:
    """One Periodic Transaction Report filing.

    `ptr_id` is the eFD UUID — stable across refreshes, used for dedup.
    `pdf_url` is the absolute URL to the eFD detail page (HTML, not raw PDF —
    eFD renders PTRs as structured HTML tables).
    """
    ptr_id: str
    senator_name: str
    senator_first: str
    senator_last: str
    filing_date: str   # MM/DD/YYYY as returned, normalized to YYYY-MM-DD
    pdf_url: str
    raw_label: str     # e.g. "Periodic Transaction Report for 04/20/2026"


@dataclass
class SenateTrade:
    """One transaction row parsed from a PTR HTML table.

    Same shape as House `PoliticianTrade` from capitol_trades_service so the
    yfinance performance pipeline can consume it without changes.
    """
    ptr_id: str
    row_num: int               # # within the PTR (stable, used for dedup)
    transaction_date: str      # YYYY-MM-DD
    owner: str                 # Self / Joint / Spouse / DC / etc.
    ticker: str                # Uppercased; "" for non-equity rows
    asset_name: str
    asset_type: str            # Stock / Bond / Other Securities / etc.
    transaction_type: str      # purchase / sale / sale_partial / exchange
    amount_min: float
    amount_max: float
    comment: str


# --------------------------------------------------------------------------- #
# Service
# --------------------------------------------------------------------------- #


def _normalize_date(s: str) -> str:
    """eFD returns MM/DD/YYYY — convert to ISO YYYY-MM-DD for consistency."""
    s = (s or "").strip()
    try:
        return datetime.strptime(s, "%m/%d/%Y").date().isoformat()
    except ValueError:
        return s  # Leave as-is if parse fails (don't drop the row)


def _cell_text(cell) -> str:
    """Extract clean text from a BeautifulSoup <td>, collapsing whitespace."""
    return " ".join(cell.get_text(" ", strip=True).split())


_AMOUNT_RANGE = re.compile(r"\$?\s*([\d,]+)\s*[-–—]\s*\$?\s*([\d,]+)")
_AMOUNT_OVER  = re.compile(r"[Oo]ver\s+\$?\s*([\d,]+)")


def _parse_amount(raw: str) -> tuple[float, float]:
    """Parse amount strings like '$1,001 - $15,000' or 'Over $50,000,000'."""
    if not raw:
        return 0.0, 0.0
    m = _AMOUNT_RANGE.search(raw)
    if m:
        return float(m.group(1).replace(",", "")), float(m.group(2).replace(",", ""))
    m = _AMOUNT_OVER.search(raw)
    if m:
        v = float(m.group(1).replace(",", ""))
        return v, v * 3
    return 0.0, 0.0


def _normalize_tx_type(raw: str) -> str:
    """Collapse the eFD transaction type into our internal vocab.

    eFD values: "Purchase", "Sale (Full)", "Sale (Partial)", "Exchange",
    "Receive", "Distribution", etc. We map to {purchase, sale, exchange, ""}.
    """
    if not raw:
        return ""
    r = raw.lower().strip()
    if "purchas" in r or r in ("buy", "bought"):
        return "purchase"
    if "sale" in r or r in ("sell", "sold"):
        return "sale_partial" if "partial" in r else "sale"
    if "exchang" in r:
        return "exchange"
    return ""


def _name_to_slug(name: str) -> str:
    out = []
    for ch in name.lower():
        if ch.isalnum():
            out.append(ch)
        elif out and out[-1] != "-":
            out.append("-")
    return "".join(out).strip("-")


class SenateEFDService:
    """Wraps the eFD search flow into reusable methods."""

    TIMEOUT = 30.0

    async def _new_session(self) -> tuple[httpx.AsyncClient, str]:
        """Open a fresh client, accept the agreement, return (client, csrf)
        ready to call /search/report/data/."""
        client = httpx.AsyncClient(headers=_HEADERS, timeout=self.TIMEOUT, follow_redirects=False)
        try:
            # 1) GET home → CSRF + session cookie
            r1 = await client.get(HOME)
            if r1.status_code != 200:
                raise RuntimeError(f"eFD home returned {r1.status_code}")
            m = _CSRF_RE.search(r1.text)
            if not m:
                raise RuntimeError("eFD: no CSRF token in home page")
            csrf = m.group(1)

            # 2) POST agreement → 302 to /search/
            r2 = await client.post(
                HOME,
                data={"csrfmiddlewaretoken": csrf, "prohibition_agreement": "1"},
                headers={"Referer": HOME},
            )
            if r2.status_code not in (200, 302):
                raise RuntimeError(f"eFD agreement returned {r2.status_code}")

            # 3) GET search page → fresh CSRF for the search form
            r3 = await client.get(SEARCH_PAGE, headers={"Referer": HOME})
            if r3.status_code != 200:
                raise RuntimeError(f"eFD search page returned {r3.status_code}")
            m = _CSRF_RE.search(r3.text)
            if not m:
                raise RuntimeError("eFD: no CSRF token in search page")
            csrf = m.group(1)
            return client, csrf
        except Exception:
            await client.aclose()
            raise

    async def fetch_ptr_filings(
        self,
        days_back: int = 365,
        page_size: int = 100,
        max_pages: int = 25,
    ) -> list[SenateFiling]:
        """Fetch all PTR filings in the date window. Returns deduplicated list.

        eFD's DataTables endpoint paginates with `start` + `length`; we walk it
        until `recordsTotal` is exhausted or `max_pages` cap is hit.
        """
        end = datetime.now(timezone.utc).date()
        start = end - timedelta(days=days_back)
        date_fmt = "%m/%d/%Y"
        start_str = f"{start.strftime(date_fmt)} 00:00:00"
        end_str   = f"{end.strftime(date_fmt)} 23:59:59"

        client, csrf = await self._new_session()
        try:
            all_filings: list[SenateFiling] = []
            seen_ids: set[str] = set()
            for page in range(max_pages):
                offset = page * page_size
                payload = {
                    "start": str(offset),
                    "length": str(page_size),
                    "report_types": f"[{PTR_REPORT_TYPE}]",
                    "filer_types": "[]",
                    "submitted_start_date": start_str,
                    "submitted_end_date": end_str,
                    "candidate_state": "",
                    "senator_state": "",
                    "office_id": "",
                    "first_name": "",
                    "last_name": "",
                    "csrfmiddlewaretoken": csrf,
                }
                r = await client.post(
                    REPORT_DATA, data=payload,
                    headers={
                        "Referer": SEARCH_PAGE,
                        "X-Requested-With": "XMLHttpRequest",
                        "X-CSRFToken": csrf,
                    },
                )
                if r.status_code != 200:
                    logger.warning("eFD page %d returned %s", page, r.status_code)
                    break

                data = r.json()
                rows = data.get("data") or []
                total = int(data.get("recordsTotal") or 0)
                if not rows:
                    break

                for row in rows:
                    parsed = self._parse_row(row)
                    if parsed and parsed.ptr_id not in seen_ids:
                        seen_ids.add(parsed.ptr_id)
                        all_filings.append(parsed)

                logger.info("eFD page %d: %d rows (running total %d / %d)",
                            page, len(rows), len(all_filings), total)
                if len(all_filings) >= total:
                    break

            return all_filings
        finally:
            await client.aclose()

    # ------------------------------------------------------------------ #
    # PTR detail parsing — fetches one filing's HTML and extracts trades
    # ------------------------------------------------------------------ #

    async def fetch_ptr_trades(
        self, ptr_id: str, *, client: httpx.AsyncClient | None = None
    ) -> list[SenateTrade]:
        """Fetch one PTR detail page and parse its transaction table.

        eFD renders PTRs as a single HTML <table> with columns:
            #, Transaction Date, Owner, Ticker, Asset Name, Asset Type, Type,
            Amount, Comment

        If `client` is supplied, reuse it (with its session cookie + agreement
        already accepted). Otherwise open a new session — costs an extra round
        trip but keeps callers simple.
        """
        if not ptr_id:
            return []

        own_client = client is None
        if own_client:
            client, _csrf = await self._new_session()

        try:
            url = f"{BASE}/search/view/ptr/{ptr_id}/"
            r = await client.get(url, headers={"Referer": SEARCH_PAGE})
            if r.status_code != 200:
                logger.warning("PTR %s: HTTP %s", ptr_id, r.status_code)
                return []
            return self._parse_ptr_html(ptr_id, r.text)
        finally:
            if own_client:
                await client.aclose()

    @staticmethod
    def _parse_ptr_html(ptr_id: str, html: str) -> list[SenateTrade]:
        """Parse the transactions table out of a PTR detail HTML page."""
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "lxml")
        table = soup.find("table")
        if not table:
            logger.debug("PTR %s: no table found", ptr_id)
            return []

        # Validate header — guard against eFD changing column order
        headers = [th.get_text(strip=True).lower() for th in table.find_all("th")]
        expected_first_cols = ["#", "transaction date"]
        if not headers or not all(
            h in " ".join(headers) for h in expected_first_cols
        ):
            logger.warning("PTR %s: unexpected table headers: %s", ptr_id, headers)
            # Try anyway — positional parsing below is forgiving

        out: list[SenateTrade] = []
        for tr in table.find_all("tr"):
            cells = tr.find_all("td")
            if len(cells) < 8:
                continue
            try:
                row_num = int(_cell_text(cells[0]) or 0)
                tx_date = _normalize_date(_cell_text(cells[1]))
                owner = _cell_text(cells[2])
                ticker_raw = _cell_text(cells[3])
                # eFD shows "--" for non-equity rows (bonds, etc.) — normalize to ""
                ticker = "" if ticker_raw in ("--", "—", "N/A", "") else ticker_raw.upper().strip()
                asset_name = _cell_text(cells[4])
                asset_type = _cell_text(cells[5])
                tx_type_raw = _cell_text(cells[6])
                amount_raw = _cell_text(cells[7])
                comment = _cell_text(cells[8]) if len(cells) > 8 else ""

                lo, hi = _parse_amount(amount_raw)
                tx_type = _normalize_tx_type(tx_type_raw)
                if not tx_type:
                    continue

                out.append(SenateTrade(
                    ptr_id=ptr_id,
                    row_num=row_num,
                    transaction_date=tx_date,
                    owner=owner,
                    ticker=ticker,
                    asset_name=asset_name,
                    asset_type=asset_type,
                    transaction_type=tx_type,
                    amount_min=lo,
                    amount_max=hi,
                    comment=comment if comment != "--" else "",
                ))
            except Exception as exc:
                logger.debug("PTR %s row parse failed: %s", ptr_id, exc)
                continue
        logger.info("PTR %s: parsed %d trades", ptr_id, len(out))
        return out

    @staticmethod
    def _parse_row(row: list) -> SenateFiling | None:
        """Parse one DataTables row.

        eFD layout (positional):
          [first_name, last_name, full_filer_name, link_html, filing_date]
        Where link_html embeds the PTR UUID and label.
        """
        try:
            if len(row) < 5:
                return None
            first = (row[0] or "").strip()
            last  = (row[1] or "").strip()
            filer = (row[2] or "").strip()
            link  = row[3] or ""
            date_str = row[4] or ""
            m = _PTR_LINK_RE.search(link)
            if not m:
                return None
            href, ptr_id, label = m.group(1), m.group(2), m.group(3)
            return SenateFiling(
                ptr_id=ptr_id,
                senator_name=f"{first} {last}".strip() or filer,
                senator_first=first,
                senator_last=last,
                filing_date=_normalize_date(date_str),
                pdf_url=f"{BASE}{href}",
                raw_label=label,
            )
        except Exception as exc:
            logger.debug("eFD row parse failed: %s | row=%r", exc, row)
            return None

    # ------------------------------------------------------------------ #
    # Aggregations
    # ------------------------------------------------------------------ #

    # ------------------------------------------------------------------ #
    # Performance — reuses the House yfinance pipeline by adapting shape
    # ------------------------------------------------------------------ #

    @staticmethod
    async def compute_senator_performance(
        senator_slug: str, senator_name: str
    ) -> dict | None:
        """Compute win-rate + 30-day return for a senator using cached trades.

        Pulls every trade we've already parsed for this senator from
        senate_trades, converts them to the same shape House trades use, and
        feeds them into capitol_trades_service._compute_performance_locally
        (the same yfinance pipeline). Returns None if no equity trades are
        cached yet — caller should call parse_senator_filings first.
        """
        from services import db_service
        from services.capitol_trades_service import (
            PoliticianTrade,
            _compute_performance_locally,
        )
        import asyncio

        rows = await db_service.list_senate_trades(senator_slug=senator_slug, limit=2000)
        # Convert to PoliticianTrade dataclass shape (same field names where possible)
        adapted: list[PoliticianTrade] = []
        for r in rows:
            ticker = (r.get("ticker") or "").upper().strip()
            if not ticker:
                continue  # Skip non-equity rows
            tx = (r.get("transaction_type") or "").lower()
            # Treat sale_partial as a sale for return-direction purposes
            if tx == "sale_partial":
                tx = "sale"
            if tx not in ("purchase", "sale"):
                continue
            adapted.append(PoliticianTrade(
                trade_id=f"{r['ptr_id']}-{r['row_num']}",
                politician_name=r["senator_name"],
                politician_slug=r["senator_slug"],
                party="",
                chamber="Senate",
                ticker=ticker,
                asset_name=r.get("asset_name", ""),
                asset_type=r.get("asset_type", "Stock"),
                transaction_type=tx,
                transaction_date=r["transaction_date"],
                published_date=r["transaction_date"],
                amount_min=float(r.get("amount_min") or 0),
                amount_max=float(r.get("amount_max") or 0),
                amount_mid=(float(r.get("amount_min") or 0) + float(r.get("amount_max") or 0)) / 2,
            ))

        if not adapted:
            return {
                "slug": senator_slug, "name": senator_name,
                "total_trades": 0, "win_rate_30d": None,
                "avg_return_30d": None, "avg_spy_return_30d": None,
            }

        # _compute_performance_locally is sync (yfinance is sync) — run in thread
        perf = await asyncio.to_thread(
            _compute_performance_locally,
            senator_slug, senator_name, adapted,
        )
        return {
            "slug": perf.politician_slug,
            "name": perf.politician_name,
            "total_trades": perf.total_trades,
            "win_rate_30d": perf.win_rate_30d,
            "avg_return_30d": perf.avg_return_30d,
            "avg_spy_return_30d": perf.avg_spy_return_30d,
        }

    @staticmethod
    def aggregate_by_senator(filings: list[SenateFiling]) -> list[dict]:
        """Group filings by senator into a politician-summary record compatible
        with the existing dropdown/leaderboard schema.

        Returned dicts use the same keys as the House `PoliticianScore` so the
        UI can render them through the same code path.
        """
        from collections import defaultdict
        today = datetime.now(timezone.utc).date()
        by_slug: dict[str, dict] = defaultdict(lambda: {
            "filings": [], "name": "", "first": "", "last": "",
        })

        for f in filings:
            slug = _name_to_slug(f.senator_name)
            d = by_slug[slug]
            d["name"] = f.senator_name
            d["first"] = f.senator_first
            d["last"] = f.senator_last
            d["filings"].append(f)

        out = []
        cutoff_90 = (today - timedelta(days=90)).isoformat()
        for slug, d in by_slug.items():
            filings_sorted = sorted(d["filings"], key=lambda x: x.filing_date, reverse=True)
            last_date = filings_sorted[0].filing_date if filings_sorted else ""
            count_90 = sum(1 for f in filings_sorted if f.filing_date >= cutoff_90)
            try:
                days_ago = max(0, (today - datetime.fromisoformat(last_date).date()).days)
            except ValueError:
                days_ago = 999
            score = round(len(filings_sorted) * (100.0 / (days_ago + 1)), 2)
            out.append({
                "slug": slug,
                "name": d["name"],
                "chamber": "Senate",
                "state": "",  # Not in the search-results JSON; would need PDF parse
                "district": "",
                "trade_count_90d": count_90,  # filings, not trades — naming is for UI compat
                "last_trade_date": last_date,
                "days_since_last_trade": days_ago,
                "filing_count_total": len(filings_sorted),
                "score": score,
                "ptr_ids": [f.ptr_id for f in filings_sorted[:10]],  # most recent 10
            })
        out.sort(key=lambda x: x["score"], reverse=True)
        return out
