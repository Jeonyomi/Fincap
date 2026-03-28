"""
SEC EDGAR Service
회사명/티커/CIK로 최신 20-F/10-K 조회 및 재무 요약
"""
import os, requests, json, time, re
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(dotenv_path=".env", override=False)
UA = os.environ.get("SEC_USER_AGENT", "FinancialLookup contact@example.com")
HEADERS = {"User-Agent": UA, "Accept": "application/json"}
CACHE_DIR = Path("cache")
CACHE_DIR.mkdir(exist_ok=True)


def _cache(key):
    p = CACHE_DIR / f"sec_{key}.json"
    if p.exists() and (time.time() - p.stat().st_mtime) < 86400:
        return json.loads(p.read_text(encoding="utf-8"))
    return None


def _save(key, data):
    (CACHE_DIR / f"sec_{key}.json").write_text(
        json.dumps(data, ensure_ascii=False), encoding="utf-8"
    )


def _load_ticker_index() -> dict:
    """SEC company_tickers.json → {ticker: {cik, name}} (캐시 24h)"""
    cache_path = CACHE_DIR / "sec_tickers.json"
    if cache_path.exists() and (time.time() - cache_path.stat().st_mtime) < 86400:
        return json.loads(cache_path.read_text(encoding="utf-8"))
    time.sleep(0.2)
    r = requests.get("https://www.sec.gov/files/company_tickers.json",
                     headers=HEADERS, timeout=20)
    raw = r.json()
    # {ticker_upper: {cik_str, title}}
    index = {}
    for v in raw.values():
        tk = v.get("ticker", "").upper()
        if tk:
            index[tk] = {
                "cik": str(v.get("cik_str", "")),
                "name": v.get("title", ""),
            }
    cache_path.write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")
    return index


# 별칭 매핑: 약칭 → 실제 티커
_ALIASES = {
    "GE AERO": "GE",
    "GE AEROSPACE": "GE",
    "GENERAL ELECTRIC": "GE",
    "GE HEALTHCARE": "GEHC",
    "GE VERNOVA": "GEV",
    "META": "META",
    "FACEBOOK": "META",
    "GOOGLE": "GOOGL",
    "ALPHABET": "GOOGL",
    "MICROSOFT": "MSFT",
    "AMAZON": "AMZN",
}


def search_company(query: str) -> list[dict]:
    """티커 or 회사명으로 SEC 기업 검색.
    1) 정확한 티커 매치 우선 (company_tickers.json)
    2) 없으면 EDGAR full-text search (회사명)
    """
    q = query.strip()
    cache_key = f"co_{q.upper()}"
    cached = _cache(cache_key)
    if cached:
        return cached

    results = []

    # ── 0. 별칭 → 티커 변환 ──────────────────────────────────────────────────
    ticker_idx = _load_ticker_index()
    q_upper = q.upper()
    resolved_ticker = _ALIASES.get(q_upper)
    if not resolved_ticker:
        # 공백 제거 후 재시도
        resolved_ticker = _ALIASES.get(q_upper.replace(" ", ""))

    effective_q = resolved_ticker or q_upper

    # ── 1. 티커 정확 매치 ────────────────────────────────────────────────────
    exact = ticker_idx.get(effective_q)
    if exact:
        results.append({
            "cik":  exact["cik"],
            "name": exact["name"],
            "form": None,
            "file_date": None,
            "match_type": "ticker",
        })
    else:
        # 부분 매치 (이름에 쿼리 포함)
        q_lo = q.lower()
        for tk, v in ticker_idx.items():
            if q_lo in v["name"].lower() or q_lo in tk.lower():
                results.append({
                    "cik":  v["cik"],
                    "name": v["name"],
                    "form": None,
                    "file_date": None,
                    "match_type": "name",
                })
            if len(results) >= 8:
                break

    # ── 2. EDGAR full-text (보완) — 정확 티커 없을 때 ───────────────────────
    if not results:
        time.sleep(0.2)
        r = requests.get(
            "https://efts.sec.gov/LATEST/search-index",
            params={"q": f'"{q}"', "dateRange": "custom",
                    "startdt": "2023-01-01", "enddt": "2026-04-01",
                    "forms": "20-F,10-K"},
            headers=HEADERS, timeout=15,
        )
        if r.status_code == 200:
            seen = set()
            for h in r.json().get("hits", {}).get("hits", [])[:8]:
                src = h.get("_source", {})
                for cik in src.get("ciks", []):
                    if cik not in seen:
                        seen.add(cik)
                        nm = (src.get("display_names") or [cik])[0]
                        results.append({
                            "cik": cik, "name": nm,
                            "form": src.get("form"),
                            "file_date": src.get("file_date"),
                            "match_type": "fulltext",
                        })

    _save(cache_key, results[:8])
    return results[:8]


def get_company_info(cik: str) -> dict:
    """CIK로 기업 기본 정보"""
    cached = _cache(f"info_{cik}")
    if cached:
        return cached

    cik_pad = str(cik).lstrip("0").zfill(10)
    time.sleep(0.15)
    r = requests.get(f"https://data.sec.gov/submissions/CIK{cik_pad}.json",
                     headers=HEADERS, timeout=15)
    if r.status_code != 200:
        return {}
    data = r.json()
    info = {
        "name": data.get("name", ""),
        "cik": cik,
        "tickers": data.get("tickers", []),
        "fiscal_year_end": data.get("fiscalYearEnd", ""),
        "sic_desc": data.get("sicDescription", ""),
    }
    _save(f"info_{cik}", info)
    return info


def get_xbrl_financials(cik: str) -> dict:
    """SEC EDGAR XBRL company facts → 최신 재무 데이터"""
    cached = _cache(f"xbrl_{cik}")
    if cached:
        return cached

    cik_pad = str(cik).lstrip("0").zfill(10)
    time.sleep(0.2)
    r = requests.get(
        f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik_pad}.json",
        headers=HEADERS, timeout=30,
    )
    if r.status_code != 200:
        return {}

    data = r.json()
    us_gaap = data.get("facts", {}).get("us-gaap", {})
    ifrs    = data.get("facts", {}).get("ifrs-full", {})

    def latest_annual(tag_data: dict, fy_range=(2022, 2025)) -> dict:
        """가장 최신 연간(FY) 값 추출"""
        best = {}
        for currency, entries in tag_data.get("units", {}).items():
            for e in entries:
                fy = e.get("fy")
                fp = e.get("fp", "")
                form = e.get("form", "")
                if fp != "FY":
                    continue
                if form not in ("10-K", "20-F", "10-K/A", "20-F/A"):
                    continue
                if not (fy_range[0] <= (fy or 0) <= fy_range[1]):
                    continue
                val = e.get("val")
                if val is None:
                    continue
                cur_best = best.get(fy, {})
                # 최신 공시 우선
                if not cur_best or e.get("filed", "") > cur_best.get("filed", ""):
                    best[fy] = {"val": val, "currency": currency, "filed": e.get("filed", ""), "fy": fy}
        return best

    # 주요 태그 시도 순서
    REVENUE_TAGS_GAAP = ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax",
                          "SalesRevenueNet", "RevenueFromContractWithCustomerIncludingAssessedTax"]
    REVENUE_TAGS_IFRS = ["Revenue", "RevenueFromContractsWithCustomers"]
    OI_TAGS_GAAP = ["OperatingIncomeLoss", "OperatingProfit"]
    OI_TAGS_IFRS = ["ProfitLossFromOperatingActivities", "OperatingProfit"]
    NI_TAGS_GAAP = ["NetIncomeLoss", "ProfitLoss"]
    NI_TAGS_IFRS = ["ProfitLoss", "NetIncomeLoss"]
    TA_TAGS = ["Assets"]
    TL_TAGS = ["Liabilities"]
    EQ_TAGS = ["StockholdersEquity", "Equity"]

    def extract(tags_gaap, tags_ifrs):
        for tag in tags_gaap:
            if tag in us_gaap:
                data_tag = latest_annual(us_gaap[tag])
                if data_tag:
                    return data_tag
        for tag in tags_ifrs:
            if tag in ifrs:
                data_tag = latest_annual(ifrs[tag])
                if data_tag:
                    return data_tag
        return {}

    result = {
        "revenue":    extract(REVENUE_TAGS_GAAP, REVENUE_TAGS_IFRS),
        "op_income":  extract(OI_TAGS_GAAP, OI_TAGS_IFRS),
        "net_income": extract(NI_TAGS_GAAP, NI_TAGS_IFRS),
        "total_assets": extract(TA_TAGS, TA_TAGS),
        "total_liab":   extract(TL_TAGS, TL_TAGS),
        "total_equity": extract(EQ_TAGS, ["Equity"]),
    }
    _save(f"xbrl_{cik}", result)
    return result


# 연간 평균 환율 (USD 기준: 1 USD = X 현지통화)
FX_TO_USD = {
    "TWD": 32.5,   # 2024 평균
    "NTD": 32.5,
    "JPY": 151.9,  # 2024 평균
    "EUR": 0.920,  # 2024 평균 (EUR/USD 역수)
    "KRW": 1363.5, # 2024 평균
    "GBP": 0.785,
    "CNY": 7.10,
    "USD": 1.0,
}


def to_usd(val, currency: str) -> float | None:
    """현지통화 → USD 환산"""
    if val is None:
        return None
    try:
        rate = FX_TO_USD.get(currency.upper(), 1.0)
        if currency.upper() == "EUR":
            # EUR: 1 EUR = 1/0.920 USD
            return float(val) / rate
        return float(val) / rate
    except Exception:
        return None


def fmt_usd(val, currency="USD") -> str:
    """수치 → USD 포맷팅 (음수는 괄호 표기)"""
    if val is None:
        return "—"
    try:
        usd = to_usd(float(val), currency)
        if usd is None:
            return "—"
        neg = usd < 0
        v = abs(usd)
        if v >= 1e12:
            s = f"${v/1e12:.2f}T"
        elif v >= 1e9:
            s = f"${v/1e9:.2f}B"
        elif v >= 1e6:
            s = f"${v/1e6:.0f}M"
        else:
            s = f"${v:,.0f}"
        return f"({s})" if neg else s
    except Exception:
        return "—"


# 하위 호환
def fmt_val(val, currency="USD"):
    return fmt_usd(val, currency)


def parse_xbrl_summary(xbrl: dict) -> dict:
    """XBRL 데이터 → 표시용 요약"""
    def best_two(field_data: dict):
        years = sorted(field_data.keys(), reverse=True)
        curr = field_data.get(years[0], {}) if years else {}
        prev = field_data.get(years[1], {}) if len(years) > 1 else {}
        return curr, prev

    rev_c, rev_p   = best_two(xbrl.get("revenue", {}))
    oi_c,  oi_p    = best_two(xbrl.get("op_income", {}))
    ni_c,  ni_p    = best_two(xbrl.get("net_income", {}))
    ta_c,  ta_p    = best_two(xbrl.get("total_assets", {}))
    tl_c,  tl_p    = best_two(xbrl.get("total_liab", {}))
    eq_c,  eq_p    = best_two(xbrl.get("total_equity", {}))

    cur = rev_c.get("currency", "USD")

    debt_ratio = None
    try:
        if tl_c.get("val") and eq_c.get("val") and eq_c["val"] != 0:
            debt_ratio = f"{tl_c['val'] / eq_c['val'] * 100:.1f}%"
    except Exception:
        pass

    op_margin = None
    try:
        if oi_c.get("val") and rev_c.get("val") and rev_c["val"] != 0:
            op_margin = f"{oi_c['val'] / rev_c['val'] * 100:.1f}%"
    except Exception:
        pass

    return {
        "currency": cur,
        "fy_current": rev_c.get("fy"),
        "fy_prev":    rev_p.get("fy"),
        "revenue":      {"current": fmt_usd(rev_c.get("val"), cur), "prev": fmt_usd(rev_p.get("val"), cur)},
        "op_income":    {"current": fmt_usd(oi_c.get("val"), cur),  "prev": fmt_usd(oi_p.get("val"), cur)},
        "net_income":   {"current": fmt_usd(ni_c.get("val"), cur),  "prev": fmt_usd(ni_p.get("val"), cur)},
        "total_assets": {"current": fmt_usd(ta_c.get("val"), cur),  "prev": fmt_usd(ta_p.get("val"), cur)},
        "total_liab":   {"current": fmt_usd(tl_c.get("val"), cur),  "prev": fmt_usd(tl_p.get("val"), cur)},
        "total_equity": {"current": fmt_usd(eq_c.get("val"), cur),  "prev": fmt_usd(eq_p.get("val"), cur)},
        "debt_ratio":   debt_ratio,
        "op_margin":    op_margin,
    }
