"""
DART OpenAPI Service
회사명/종목코드로 최신 사업보고서 조회 및 재무 요약
"""
import os, requests, zipfile, io, re, json, time
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(dotenv_path=".env", override=False)
API_KEY = os.environ.get("DART_API_KEY", "")
BASE = "https://opendart.fss.or.kr/api"

import tempfile as _tempfile
CACHE_DIR = Path(_tempfile.gettempdir()) / "fincap_dart"
CACHE_DIR.mkdir(exist_ok=True)


def _cache(key):
    p = CACHE_DIR / f"{key}.json"
    if p.exists() and (time.time() - p.stat().st_mtime) < 86400:
        return json.loads(p.read_text(encoding="utf-8"))
    return None


def _save(key, data):
    (CACHE_DIR / f"{key}.json").write_text(
        json.dumps(data, ensure_ascii=False), encoding="utf-8"
    )


def _load_corp_index() -> list:
    """DART 전체 기업 고유번호 파일 로드 (캐시 7일)"""
    cache_path = CACHE_DIR / "corp_index.json"
    if cache_path.exists() and (time.time() - cache_path.stat().st_mtime) < 7 * 86400:
        return json.loads(cache_path.read_text(encoding="utf-8"))

    r = requests.get(f"{BASE}/corpCode.xml",
        params={"crtfc_key": API_KEY}, timeout=60)
    z = zipfile.ZipFile(io.BytesIO(r.content))
    import xml.etree.ElementTree as ET
    with z.open("CORPCODE.xml") as f:
        tree = ET.parse(f)
    root = tree.getroot()
    index = []
    for item in root.findall("list"):
        index.append({
            "corp_code":   item.findtext("corp_code", ""),
            "corp_name":   item.findtext("corp_name", ""),
            "stock_code":  item.findtext("stock_code", ""),
            "modify_date": item.findtext("modify_date", ""),
        })
    cache_path.write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")
    return index


_dart_names_upper: set | None = None

def get_dart_name_set() -> set:
    """상장사 영문명 대문자 set (빠른 라우팅용)"""
    global _dart_names_upper
    if _dart_names_upper is not None:
        return _dart_names_upper
    idx = _load_corp_index()
    _dart_names_upper = {
        item["corp_name"].upper()
        for item in idx
        if item.get("stock_code", "").strip()
    }
    return _dart_names_upper


def search_company(query: str) -> list[dict]:
    """회사명 or 종목코드로 기업 검색 — corpCode.xml 기반"""
    q = query.strip()
    cached = _cache(f"co_{q}")
    if cached:
        return cached

    index = _load_corp_index()
    is_code = re.match(r"^\d{6}$", q)
    results = []

    for item in index:
        # 상장사 우선 (stock_code 있는 것)
        if is_code:
            if item["stock_code"].strip() == q:
                results.append(item)
        else:
            # 회사명 부분 일치 (대소문자 무관)
            if q.lower() in item["corp_name"].lower():
                results.append(item)

    def sort_key(item):
        nm = item["corp_name"]
        has_stock = 1 if item["stock_code"].strip() else 2
        # 정확 일치 최우선, 접두 일치 차순, 나머지
        if nm == q:
            exact = 0
        elif nm.startswith(q):
            exact = 1
        else:
            exact = 2
        return (exact, has_stock, nm)

    results.sort(key=sort_key)

    _save(f"co_{q}", results[:10])
    return results[:10]


def get_latest_report(corp_code: str) -> dict | None:
    """최신 사업보고서 메타데이터"""
    cached = _cache(f"rep_{corp_code}")
    if cached:
        return cached

    r = requests.get(f"{BASE}/list.json", params={
        "crtfc_key": API_KEY,
        "corp_code": corp_code,
        "bgn_de": "20250101",
        "end_de": "20260401",
        "pblntf_ty": "A",
        "pblntf_detail_ty": "A001",
        "page_count": 5,
    }, timeout=15)
    data = r.json()
    items = data.get("list", [])
    if not items:
        # 더 넓은 범위
        r2 = requests.get(f"{BASE}/list.json", params={
            "crtfc_key": API_KEY,
            "corp_code": corp_code,
            "bgn_de": "20230101",
            "end_de": "20260401",
            "pblntf_ty": "A",
            "pblntf_detail_ty": "A001",
            "page_count": 5,
        }, timeout=15)
        items = r2.json().get("list", [])

    if not items:
        return None

    items.sort(key=lambda x: x.get("rcept_no", ""), reverse=True)
    result = items[0]
    _save(f"rep_{corp_code}", result)
    return result


def get_financials(corp_code: str, bsns_year: str) -> list[dict]:
    """주요 재무 계정 (연결 + 별도)"""
    cache_key = f"fin_{corp_code}_{bsns_year}"
    cached = _cache(cache_key)
    if cached:
        return cached

    r = requests.get(f"{BASE}/fnlttSinglAcnt.json", params={
        "crtfc_key": API_KEY,
        "corp_code": corp_code,
        "bsns_year": bsns_year,
        "reprt_code": "11011",  # 사업보고서
    }, timeout=15)
    data = r.json()
    if data.get("status") != "000":
        return []

    result = data.get("list", [])
    _save(cache_key, result)
    return result


def parse_financials(items: list[dict]) -> dict:
    """재무 항목 파싱 — 연결 기준 우선"""
    # 연결(CFS) 우선, 없으면 별도(OFS)
    cfs = [i for i in items if i.get("fs_div") == "CFS"]
    ofs = [i for i in items if i.get("fs_div") == "OFS"]
    target = cfs if cfs else ofs
    fs_type = "연결" if cfs else "별도"

    def get_val(account_names: list, items_list: list) -> tuple[str | None, str | None]:
        for nm in account_names:
            for item in items_list:
                if nm in item.get("account_nm", ""):
                    curr = item.get("thstrm_amount", "").replace(",", "")
                    prev = item.get("frmtrm_amount", "").replace(",", "")
                    return curr or None, prev or None
        return None, None

    KRW_RATE = 1363.5  # 2024 연평균 KRW/USD

    def fmt(val_str: str | None, currency: str = "KRW") -> str:
        """KRW → USD 환산 후 포맷 (음수는 괄호 표기)"""
        if not val_str:
            return "—"
        try:
            v = int(val_str)
            usd = v / KRW_RATE
            neg = usd < 0
            av = abs(usd)
            if av >= 1e12:
                s = f"${av/1e12:.2f}T"
            elif av >= 1e9:
                s = f"${av/1e9:.2f}B"
            elif av >= 1e6:
                s = f"${av/1e6:.0f}M"
            else:
                s = f"${av:,.0f}"
            return f"({s})" if neg else s
        except Exception:
            return val_str

    rev_c, rev_p = get_val(["수익(매출액)", "매출액", "영업수익"], target)
    oi_c,  oi_p  = get_val(["영업이익", "영업손익"], target)
    ni_c,  ni_p  = get_val(["당기순이익", "당기순손익"], target)
    ta_c,  ta_p  = get_val(["자산총계"], target)
    tl_c,  tl_p  = get_val(["부채총계"], target)
    eq_c,  eq_p  = get_val(["자본총계"], target)

    # 부채비율
    debt_ratio = None
    try:
        if tl_c and eq_c and int(eq_c) != 0:
            debt_ratio = f"{int(tl_c) / int(eq_c) * 100:.1f}%"
    except Exception:
        pass

    # 영업이익률
    op_margin = None
    try:
        if oi_c and rev_c and int(rev_c) != 0:
            op_margin = f"{int(oi_c) / int(rev_c) * 100:.1f}%"
    except Exception:
        pass

    return {
        "fs_type": fs_type,
        "revenue":      {"current": fmt(rev_c), "prev": fmt(rev_p), "raw_c": rev_c, "raw_p": rev_p},
        "op_income":    {"current": fmt(oi_c),  "prev": fmt(oi_p)},
        "net_income":   {"current": fmt(ni_c),  "prev": fmt(ni_p)},
        "total_assets": {"current": fmt(ta_c),  "prev": fmt(ta_p)},
        "total_liab":   {"current": fmt(tl_c),  "prev": fmt(tl_p)},
        "total_equity": {"current": fmt(eq_c),  "prev": fmt(eq_p)},
        "debt_ratio":   debt_ratio,
        "op_margin":    op_margin,
    }


def get_geo_revenue(corp_code: str, rcept_no: str) -> dict | None:
    """사업보고서 XBRL에서 지역별 매출 추출"""
    cache_key = f"geo_{rcept_no}"
    cached = _cache(cache_key)
    if cached is not None:
        return cached

    r = requests.get(f"{BASE}/document.xml",
        params={"crtfc_key": API_KEY, "rcept_no": rcept_no}, timeout=60)

    if r.content[:4] != b'PK\x03\x04':
        _save(cache_key, {})
        return {}

    z = zipfile.ZipFile(io.BytesIO(r.content))
    main = next((n for n in z.namelist() if n == f"{rcept_no}.xml"), None)
    if not main:
        main = max(z.namelist(), key=lambda n: z.getinfo(n).file_size)

    with z.open(main) as f:
        raw = f.read().decode("utf-8", errors="ignore")

    # 지역 멤버 필터링
    DART_STD = ("dart_USMember", "dart_NorthAmericaMember", "dart_AmericasMember",
                "dart_KRMember", "dart_DomesticMember", "dart_CNMember")
    ENTITY_KW = ("NorthAmericaMember", "NorthAmericaOf", "AmericaMember", "AmericaOf", "KusMmeber")
    TE_PAT = re.compile(
        r'<TE\b(?=[^>]*ACODE="(?P<acode>[^"]+)")(?=[^>]*ADECIMAL="(?P<decimal>[^"]*)")?'
        r'(?=[^>]*ACONTEXT="(?P<context>[^"]*)")'
        r'[^>]*>(?P<value>[0-9,]+)<',
        re.DOTALL
    )

    geo = {}
    for line in raw.split("\n"):
        if not ("Revenue" in line and "ACODE" in line and "ACONTEXT" in line):
            continue
        if not (any(m in line for m in DART_STD) or
                ("GeographicalAreas" in line and any(kw in line for kw in ENTITY_KW))):
            continue

        m_ctx = re.search(r'ACONTEXT="([^"]+)"', line)
        m_val = re.search(r">([0-9,]+)<", line)
        m_dec = re.search(r'ADECIMAL="([^"]*)"', line)
        if not (m_ctx and m_val):
            continue

        ctx = m_ctx.group(1)
        val = float(m_val.group(1).replace(",", ""))
        dec = int(m_dec.group(1)) if m_dec and m_dec.group(1) else -6
        actual = val * (10 ** abs(dec))

        yr = "2025" if ("CFY2025" in ctx or "CFY2026" in ctx) else ("2024" if "PFY2024" in ctx else None)
        if not yr:
            continue

        ctx_lo = ctx.lower()
        if "dart_usmember" in ctx_lo or ("kusmember" in ctx_lo and "othersthan" not in ctx_lo):
            region = "미국"
        elif any(k in ctx_lo for k in ["northamericamember", "northamericaof"]):
            region = "북미"
        elif any(k in ctx_lo for k in ["dart_ameri", "americasmember", "americaof"]):
            region = "아메리카"
        elif "dart_cnmember" in ctx_lo:
            region = "중국"
        elif any(k in ctx_lo for k in ["dart_krmember", "dart_domesticmember"]):
            region = "한국"
        else:
            continue

        key = (yr, region)
        if key not in geo or "ConsolidatedMember" in ctx:
            geo[key] = actual

    result = {}
    for (yr, region), val in sorted(geo.items()):
        result.setdefault(yr, {})[region] = val

    _save(cache_key, result)
    return result
