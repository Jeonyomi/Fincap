"""
Financial Lookup — Real-time Company Financial Summary
DART (Korean companies) / SEC EDGAR (US & Global) — auto-routed
"""
import re
import streamlit as st
from dart_service import (
    search_company as dart_search,
    get_latest_report,
    get_financials,
    parse_financials,
    get_geo_revenue,
)
from sec_service import (
    search_company as sec_search,
    get_company_info,
    get_xbrl_financials,
    parse_xbrl_summary,
)

st.set_page_config(page_title="Financial Lookup", page_icon="\U0001f4ca", layout="centered")

# ── Language ─────────────────────────────────────────────────────────────────
_h1, _h2 = st.columns([5, 1])
with _h2:
    lang = st.selectbox("Language", ["\U0001f1fa\U0001f1f8 ENG", "\U0001f1f0\U0001f1f7 KOR"],
                        label_visibility="collapsed", key="lang")
_lc = "en" if lang.endswith("ENG") else "ko"

T = {
    "title":        {"en": "\U0001f4ca Financial Lookup",      "ko": "\U0001f4ca 기업 재무 조회"},
    "subtitle":     {"en": "Enter a company name or ticker — we'll find it via DART or SEC EDGAR.",
                     "ko": "회사명 또는 종목코드/티커를 입력하세요."},
    "placeholder":  {"en": "e.g. TSMC, Apple, SK하이닉스, 005930 ...",
                     "ko": "예: 풍산, SK하이닉스, TSMC, NVDA ..."},
    "search":       {"en": "Search", "ko": "검색"},
    "select_hint":  {"en": "Multiple companies found — please select one:",
                     "ko": "여러 회사가 검색됐습니다. 하나를 선택하세요:"},
    "select_btn":   {"en": "View Financials", "ko": "재무 조회"},
    "loading":      {"en": "Fetching data...", "ko": "조회 중..."},
    "no_result":    {"en": "No results found. Try a different name or ticker.",
                     "ko": "검색 결과가 없습니다. 다른 회사명 또는 코드를 입력해주세요."},
    "filing":       {"en": "View Filing \U0001f517", "ko": "공시 원문 \U0001f517"},
    "fin_summary":  {"en": "Financial Summary", "ko": "재무 요약"},
    "geo_rev":      {"en": "Revenue by Geography", "ko": "지역별 매출"},
    "revenue":      {"en": "Revenue", "ko": "매출액"},
    "op_income":    {"en": "Operating Income", "ko": "영업이익"},
    "op_margin":    {"en": "Op. Margin", "ko": "영업이익률"},
    "net_income":   {"en": "Net Income", "ko": "당기순이익"},
    "total_assets": {"en": "Total Assets", "ko": "자산총계"},
    "debt_ratio":   {"en": "Debt Ratio", "ko": "부채비율"},
    "prior":        {"en": "Prior", "ko": "전기"},
    "dart_badge":   {"en": "\U0001f534 DART (KR)", "ko": "\U0001f534 DART"},
    "sec_badge":    {"en": "\U0001f535 SEC EDGAR", "ko": "\U0001f535 SEC EDGAR"},
    "footer":       {"en": "Data: DART OpenAPI · SEC EDGAR | For reference only.",
                     "ko": "출처: DART OpenAPI · SEC EDGAR | 참고용"},
    "back":         {"en": "\u2190 New search", "ko": "\u2190 다시 검색"},
}

def t(key): return T[key][_lc]


def auto_route(query: str) -> str:
    q = query.strip()
    # 한국 종목코드 (숫자 6자리)
    if re.match(r"^\d{6}$", q): return "dart"
    # 한글 포함
    if re.search(r"[가-힣]", q): return "dart"
    # 영문이지만 DART 상장사 이름과 완전 일치 → DART
    try:
        from dart_service import get_dart_name_set
        if q.upper() in get_dart_name_set():
            return "dart"
    except Exception:
        pass
    return "sec"


# ── Header ────────────────────────────────────────────────────────────────────
with _h1:
    st.title(t("title"))
st.caption(t("subtitle"))

# ── Session state ─────────────────────────────────────────────────────────────
if "candidates" not in st.session_state:
    st.session_state.candidates = []
if "selected" not in st.session_state:
    st.session_state.selected = None
if "route" not in st.session_state:
    st.session_state.route = None

# ── Search form ───────────────────────────────────────────────────────────────
with st.form("search_form", clear_on_submit=False):
    query = st.text_input("query", placeholder=t("placeholder"), label_visibility="collapsed")
    search_clicked = st.form_submit_button(t("search"), type="primary")

if search_clicked and query.strip():
    st.session_state.candidates = []
    st.session_state.selected = None
    route = auto_route(query.strip())
    st.session_state.route = route

    with st.spinner(t("loading")):
        if route == "dart":
            results = dart_search(query.strip())
        else:
            results = sec_search(query.strip())

    if not results:
        st.error(t("no_result"))
        st.stop()

    st.session_state.candidates = results

    # 단일 결과 or 정확 종목코드 입력이면 바로 선택
    if len(results) == 1 or re.match(r"^\d{6}$", query.strip()):
        st.session_state.selected = results[0]
    # SEC 티커 정확 매치도 바로 선택
    elif route == "sec" and results[0].get("match_type") == "ticker":
        st.session_state.selected = results[0]

# ── Candidate list (여러 결과) ─────────────────────────────────────────────────
if st.session_state.candidates and st.session_state.selected is None:
    st.markdown(f"**{t('select_hint')}**")
    candidates = st.session_state.candidates
    route = st.session_state.route

    # 상장사 + 비상장 구분 표시
    for i, co in enumerate(candidates[:15]):
        if route == "dart":
            stock = co.get("stock_code", "").strip()
            label = f"{co['corp_name']}"
            badge = f"`{stock}`" if stock else ""
            col1, col2 = st.columns([5, 1])
            with col1:
                if st.button(f"{label}  {badge}", key=f"co_{i}"):
                    st.session_state.selected = co
                    st.rerun()
        else:
            nm = co["name"].split("(")[0].strip()
            tickers_str = ""
            cik = co["cik"]
            col1, col2 = st.columns([5, 1])
            with col1:
                if st.button(f"{nm}  `CIK {cik}`", key=f"co_{i}"):
                    st.session_state.selected = co
                    st.rerun()

    st.stop()

# ── Financial detail ──────────────────────────────────────────────────────────
if st.session_state.selected:
    co = st.session_state.selected
    route = st.session_state.route

    # Back button
    if st.button(t("back"), key="back_btn"):
        st.session_state.selected = None
        st.rerun()

    with st.spinner(t("loading")):

        # ── DART ─────────────────────────────────────────────────────────────
        if route == "dart":
            corp_code  = co["corp_code"]
            corp_name  = co["corp_name"]
            stock_code = co.get("stock_code", "")

            report = get_latest_report(corp_code)
            if not report:
                st.warning(
                    f"**{corp_name}** — Annual report not found on DART. (code: {corp_code})"
                    if _lc == "en" else
                    f"**{corp_name}** — 사업보고서를 찾을 수 없습니다. (code: {corp_code})"
                )
                st.stop()

            rcept_no   = report.get("rcept_no", "")
            report_nm  = report.get("report_nm", "")
            rcept_dt   = report.get("rcept_dt", "")
            ym         = re.search(r"\((\d{4})\.", report_nm)
            bsns_year  = ym.group(1) if ym else str(int(rcept_dt[:4]) - 1)
            report_url = f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}"

            fin_items = get_financials(corp_code, bsns_year)
            if not fin_items:
                fin_items = get_financials(corp_code, str(int(bsns_year) - 1))
            fin = parse_financials(fin_items)
            geo = get_geo_revenue(corp_code, rcept_no)

            st.divider()
            hc1, hc2 = st.columns([4, 1])
            with hc1:
                st.subheader(f"{corp_name}" + (f"  `{stock_code}`" if stock_code else ""))
                st.caption(
                    f"{t('dart_badge')} · {report_nm} · "
                    f"Filed {rcept_dt[:4]}.{rcept_dt[4:6]}.{rcept_dt[6:]} · "
                    f"FY{bsns_year} ({fin['fs_type']})"
                )
            with hc2:
                st.link_button(t("filing"), report_url)

            st.markdown(f"**{t('fin_summary')}**")
            c1, c2, c3 = st.columns(3)
            c1.metric(t("revenue"),    fin["revenue"]["current"],
                      help=f"{t('prior')}: {fin['revenue']['prev']}")
            c2.metric(t("op_income"),  fin["op_income"]["current"],
                      help=f"{t('prior')}: {fin['op_income']['prev']}")
            c3.metric(t("op_margin"),  fin["op_margin"] or "—")

            c4, c5, c6 = st.columns(3)
            c4.metric(t("net_income"),   fin["net_income"]["current"],
                      help=f"{t('prior')}: {fin['net_income']['prev']}")
            c5.metric(t("total_assets"), fin["total_assets"]["current"],
                      help=f"{t('prior')}: {fin['total_assets']['prev']}")
            c6.metric(t("debt_ratio"),   fin["debt_ratio"] or "—")

            if geo:
                st.divider()
                st.markdown(f"**{t('geo_rev')}** *(DART XBRL)*")
                for yr, regions in sorted(geo.items(), reverse=True):
                    st.markdown(f"*FY{yr}*")
                    cols = st.columns(len(regions))
                    for i, (region, val) in enumerate(sorted(regions.items())):
                        usd = val / 1395.50 / 1e9
                        label = region if _lc == "ko" else {
                            "미국": "US", "북미": "North America",
                            "아메리카": "Americas", "한국": "Korea",
                            "중국": "China", "유럽": "Europe",
                        }.get(region, region)
                        cols[i].metric(label, f"${usd:.2f}B", help=f"{val/1e12:.2f}T KRW")

        # ── SEC EDGAR ─────────────────────────────────────────────────────────
        else:
            cik = co["cik"]
            info    = get_company_info(cik)
            xbrl    = get_xbrl_financials(cik)
            summary = parse_xbrl_summary(xbrl)

            name    = info.get("name") or co["name"].split("(")[0].strip()
            tickers = info.get("tickers", [])
            fy_cur  = summary.get("fy_current")
            fy_prev = summary.get("fy_prev")
            cik_pad = str(cik).lstrip("0").zfill(10)
            edgar_url = (
                f"https://www.sec.gov/cgi-bin/browse-edgar"
                f"?action=getcompany&CIK={cik_pad}&type=20-F&dateb=&owner=include&count=5"
            )

            st.divider()
            hc1, hc2 = st.columns([4, 1])
            with hc1:
                ticker_str = "  `" + "` `".join(tickers) + "`" if tickers else ""
                st.subheader(f"{name}{ticker_str}")
                orig_cur = summary.get("currency", "USD")
                note = f"USD (from {orig_cur})" if orig_cur != "USD" else "USD"
                st.caption(
                    f"{t('sec_badge')} · CIK {cik} · FY{fy_cur} vs FY{fy_prev} · "
                    f"{info.get('sic_desc','')} · {note}"
                )
            with hc2:
                st.link_button(t("filing"), edgar_url)

            st.markdown(f"**{t('fin_summary')}** *(FY{fy_cur})*")
            c1, c2, c3 = st.columns(3)
            c1.metric(t("revenue"),   summary["revenue"]["current"],
                      help=f"FY{fy_prev}: {summary['revenue']['prev']}")
            c2.metric(t("op_income"), summary["op_income"]["current"],
                      help=f"FY{fy_prev}: {summary['op_income']['prev']}")
            c3.metric(t("op_margin"), summary["op_margin"] or "—")

            c4, c5, c6 = st.columns(3)
            c4.metric(t("net_income"),   summary["net_income"]["current"],
                      help=f"FY{fy_prev}: {summary['net_income']['prev']}")
            c5.metric(t("total_assets"), summary["total_assets"]["current"],
                      help=f"FY{fy_prev}: {summary['total_assets']['prev']}")
            c6.metric(t("debt_ratio"),   summary["debt_ratio"] or "—")

st.divider()
st.caption(f"\U0001f4cc {t('footer')}")
