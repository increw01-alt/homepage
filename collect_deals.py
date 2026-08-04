# -*- coding: utf-8 -*-
"""
네이버 쇼핑 검색 API로 상품권 최저가를 수집해 할인율을 계산하고
html/deals.json 을 자동 생성하는 스크립트.

사용법 (Windows PowerShell):
    $env:NAVER_CLIENT_ID="발급받은_Client_ID"
    $env:NAVER_CLIENT_SECRET="발급받은_Client_Secret"
    python collect_deals.py

키는 코드에 절대 넣지 말고 환경변수로만 전달합니다.
"""

import os
import re
import sys
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta

# 콘솔 한글 출력 안전 처리 (윈도우 cp949 대비)
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

CLIENT_ID = os.environ.get("NAVER_CLIENT_ID")
CLIENT_SECRET = os.environ.get("NAVER_CLIENT_SECRET")

API_URL = "https://openapi.naver.com/v1/search/shop.json"

# 수집 대상: 상품권 종류(컬럼) → 액면가별 검색어
# key     : 요약표 컬럼명
# name    : 딜 목록 카테고리 제목
# items   : 검색어(q)와 액면가(face)
# include : 제목에 이 중 하나가 반드시 있어야 인정
# deny    : 제목에 이 중 하나라도 있으면 제외(타 브랜드/묶음권 걸러냄)
CATEGORIES = [
    {"key": "컬처", "name": "컬쳐랜드 문화상품권",
     "include": ["컬쳐", "컬처"],
     "deny": ["신세계", "롯데", "현대", "백화점", "투썸", "스타벅스", "해피머니"],
     "items": [
        {"q": "컬쳐랜드 모바일 문화상품권 5만원", "face": 50000},
        {"q": "컬쳐랜드 모바일 문화상품권 3만원", "face": 30000},
        {"q": "컬쳐랜드 모바일 문화상품권 1만원", "face": 10000},
     ]},
    {"key": "문화", "name": "도서문화상품권 (북앤라이프)",
     "include": ["북앤라이프", "도서문화"],
     "deny": ["컬쳐", "컬처", "신세계", "롯데", "현대", "백화점", "투썸", "스타벅스"],
     "items": [
        {"q": "북앤라이프 도서문화상품권 5만원", "face": 50000},
        {"q": "북앤라이프 도서문화상품권 3만원", "face": 30000},
     ]},
    {"key": "롯데", "name": "롯데 상품권",
     "include": ["롯데"],
     "deny": ["신세계", "현대", "컬쳐", "컬처", "투썸", "스타벅스", "갤러리아",
              "시네마", "하이마트", "슈퍼", "면세", "홈쇼핑", "리아", "월드"],
     "items": [
        {"q": "롯데백화점 상품권 5만원", "face": 50000},
        {"q": "롯데백화점 상품권 10만원", "face": 100000},
        {"q": "롯데 모바일상품권 5만원", "face": 50000},
        {"q": "롯데상품권 10만원권", "face": 100000},
     ]},
    {"key": "현대", "name": "현대백화점 상품권",
     "include": ["현대"],
     "deny": ["신세계", "롯데", "컬쳐", "컬처", "투썸", "스타벅스", "갤러리아",
              "홈쇼핑", "면세", "자동차", "카드"],
     "items": [
        {"q": "현대백화점 상품권 5만원", "face": 50000},
        {"q": "현대백화점 상품권 10만원", "face": 100000},
        {"q": "현대백화점 모바일상품권", "face": 50000},
        {"q": "현대백화점상품권 10만원권", "face": 100000},
     ]},
    {"key": "신세계", "name": "신세계 상품권",
     "include": ["신세계"],
     "deny": ["롯데", "현대", "컬쳐", "컬처", "투썸", "스타벅스", "갤러리아",
              "면세", "아울렛"],
     "items": [
        {"q": "신세계 모바일상품권 5만원", "face": 50000},
        {"q": "신세계상품권 10만원", "face": 100000},
        {"q": "신세계 상품권 5만원권", "face": 50000},
        {"q": "SSG 신세계상품권", "face": 100000},
     ]},
]

# 신뢰할 수 있는 판매처만 노출.
# 1순위: 링크 도메인이 아래 신뢰 도메인이면 통과 (네이버 브랜드스토어/공식, 대형 오픈마켓).
#   → 현금화·소액결제성 사이트(상품권판다·달인페이 등 자체 도메인)는 자동 제외됨.
TRUST_DOMAINS = [
    "smartstore.naver.com", "brand.naver.com",   # 네이버 브랜드스토어/스마트스토어(공식)
    "gmarket.co.kr", "auction.co.kr", "11st.co.kr",
    "coupang.com", "ssg.com", "lotteon.com", "gsshop.com",
    "wemakeprice.com", "tmon.co.kr", "hmall.com", "cjonstyle.com", "hyundaihmall.com",
]
# 2순위: 판매처 이름에 아래가 포함돼도 통과 (도메인만으론 놓칠 수 있는 공식/대형몰 보완).
TRUST_ALLOW = [
    "지마켓", "G마켓", "gmarket", "옥션", "auction", "11번가", "위메프", "티몬",
    "인터파크", "쿠팡", "coupang", "SSG", "쓱", "롯데on", "lotteon",
    "플러스유", "플러스문", "모아핀", "핀큐", "플러스존",  # 협회 자체몰
]

# ── 링크프라이스 딥링크 자동 변환 ──────────────────────────────
# 승인완료 머천트의 상품 링크를 제휴(실적) 링크로 감쌉니다.
# 어필리에이트 ID는 링크프라이스 '한국상품권협회' 채널 기준.
LP_AFFILIATE_ID = "A100706248"
LP_MERCHANTS = {            # 도메인 → 머천트 코드 (승인완료만 등록)
    "gmarket.co.kr": "gmarket",
    "auction.co.kr": "auction",
    "lotteon.com": "lotteon",
    # "11st.co.kr": "11st",     # 협회 채널 승인대기 — 승인되면 주석 해제
    # "emart.ssg.com": "emart", # 주의: 이마트몰은 제휴링크로 상품권 접속 시 구매 제한 → 변환 금지
    "gsshop.com": "gseshop",
    "hmall.com": "hmall",
    "lotteimall.com": "woori",
}


def to_deeplink(url):
    """신뢰 링크가 승인 머천트 도메인이면 링크프라이스 딥링크로 변환."""
    low = (url or "").lower()
    for domain, mcode in LP_MERCHANTS.items():
        if domain in low:
            return ("https://click.linkprice.com/click.php"
                    f"?m={mcode}&a={LP_AFFILIATE_ID}&l=9999"
                    f"&tu={urllib.parse.quote(url, safe='')}")
    return url


TAG_RE = re.compile(r"<[^>]+>")

# 모든 카테고리 공통 차단어 — 상품권이 '증정/사은품'으로 딸린 일반 상품 오탐 방지
GLOBAL_DENY = ["세트", "사은품", "증정", "파운데이션", "화장품", "크림", "에센스",
               "향수", "쿠션", "립스틱", "선물세트", "기획"]

# 11번가 상품 페이지는 일반 요청으로 접근 가능 → 등록 딜의 가격을 실행 시마다 자동 갱신.
# (지마켓·옥션은 스크립트 접근을 차단하므로 수동 등록가를 그대로 사용)
BROWSER_HDRS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
}


def parse_face_from_name(name):
    """상품명에서 액면가 추출: '5만원' → 50000, '100,000원' → 100000."""
    m = re.search(r"(\d+)\s*만\s*원", name or "")
    if m:
        return int(m.group(1)) * 10000
    m = re.search(r"([\d,]{4,9})\s*원", name or "")
    if m:
        v = int(m.group(1).replace(",", ""))
        if v >= 1000:
            return v
    return None


def fetch_11st_live(url, face=None):
    """11번가 상품 페이지의 JSON-LD에서 상품명·판매가·정가·재고를 읽는다.

    반환: {"title", "price", "face", "rate"} / 품절·파싱실패·비정상가면 None.
    face 를 넘기지 않으면 정가(또는 상품명)에서 액면가를 자동 판별한다.
    """
    req = urllib.request.Request(url, headers=BROWSER_HDRS)
    with urllib.request.urlopen(req, timeout=12) as r:
        html = r.read().decode("utf-8", errors="ignore")

    m = re.search(r'<script type="application/ld\+json">(.*?)</script>', html, re.S)
    if not m:
        return None
    try:
        ld = json.loads(m.group(1))
    except Exception:
        return None

    offers = ld.get("offers") or {}
    price = offers.get("price")
    if not isinstance(price, (int, float)) or price <= 0:
        return None

    # 품절/판매중단이면 제외
    if "InStock" not in str(offers.get("availability", "")):
        return None

    name = (ld.get("name") or "").strip()
    # 액면가: 인자 > 정가(취소선 가격) > 상품명
    if not face:
        spec = offers.get("priceSpecification") or {}
        face = spec.get("price") or parse_face_from_name(name)
    if not face:
        return None

    price = int(price)
    face = int(face)
    # 액면가 대비 상식적 범위(70~102%)만 인정 — 오탐 방지
    if not (face * 0.70 <= price <= face * 1.02):
        return None
    rate = round((face - price) / face * 100, 1)
    if rate <= 0:
        return None
    return {"title": name, "price": price, "face": face, "rate": rate}


def is_trusted(link, seller):
    url = (link or "").lower()
    if any(d in url for d in TRUST_DOMAINS):
        return True
    s = (seller or "").lower()
    return any(k.lower() in s for k in TRUST_ALLOW)


def clean(text):
    """검색 결과 title 의 <b> 태그 등 제거."""
    return TAG_RE.sub("", text).replace("&amp;", "&").strip()


def search_shop(query, display=100):
    """네이버 쇼핑 검색 API 호출 → items 리스트 반환."""
    params = urllib.parse.urlencode({"query": query, "display": display, "sort": "asc"})
    req = urllib.request.Request(API_URL + "?" + params)
    req.add_header("X-Naver-Client-Id", CLIENT_ID)
    req.add_header("X-Naver-Client-Secret", CLIENT_SECRET)
    with urllib.request.urlopen(req, timeout=10) as res:
        data = json.loads(res.read().decode("utf-8"))
    return data.get("items", [])


def best_deals_for(query, face, include, deny, must):
    """한 검색어에 대해 액면가 근처 + 브랜드 일치 매물만 골라 할인율 계산."""
    out = []
    for it in search_shop(query):
        # 신뢰 판매처만 통과 (현금화·소액결제성 사이트 제외)
        seller = clean(it.get("mallName", "기타"))
        link = it.get("link", "")
        if not is_trusted(link, seller):
            continue
        title = clean(it.get("title", ""))
        # 브랜드 필터: include 중 하나 이상 포함 / must 는 모두 포함 / deny 는 하나도 없어야
        if include and not any(k in title for k in include):
            continue
        if must and not all(k in title for k in must):
            continue
        if deny and any(k in title for k in deny):
            continue
        # 상품권이 '사은품'으로 딸린 일반 상품(화장품 세트 등) 오탐 차단
        if any(k in title for k in GLOBAL_DENY):
            continue
        try:
            price = int(it.get("lprice", 0))
        except ValueError:
            continue
        if price <= 0:
            continue
        # 액면가의 80%~102% 범위만 (묶음/사은품/오인식 제거)
        if not (face * 0.80 <= price <= face * 1.02):
            continue
        rate = round((face - price) / face * 100, 1)
        if rate <= 0:
            continue
        out.append({
            "seller": seller,
            "rate": rate,
            "price": price,
            "face": face,
            "title": title,
            "url": to_deeplink(link or "#"),
        })
    return out


# 수동 등록 딜의 유효 기간(일) — 가격 자동 갱신이 불가능한 판매처(지마켓·옥션)는
# 등록일이 오래되면 시세가 틀어질 수 있으므로 자동으로 노출에서 제외한다.
MANUAL_STALE_DAYS = 14


def is_stale(checked):
    """checked 날짜(YYYY-MM-DD)가 MANUAL_STALE_DAYS 보다 오래되었는지."""
    if not checked:
        return True  # 확인일이 없으면 신뢰할 수 없음
    try:
        d = datetime.strptime(checked, "%Y-%m-%d").date()
    except ValueError:
        return True
    kst_today = datetime.now(timezone(timedelta(hours=9))).date()
    return (kst_today - d).days > MANUAL_STALE_DAYS


def load_manual_deals():
    """manual_deals.json 의 수동 등록 딜을 읽어 카테고리별로 반환."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "manual_deals.json")
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"[경고] manual_deals.json 읽기 실패: {e}")
        return {}
    by_cat = {}
    for d in data.get("deals", []):
        url = d.get("url", "")
        # URL 미입력(플레이스홀더) 항목은 건너뜀
        if not url or url.startswith("여기에") or url == "#":
            continue
        rate = d.get("rate", 0)
        face = d.get("face")
        title = d.get("title", "")
        seller = d.get("seller", "")

        # 11번가 딜: 상품명·가격·할인율을 실행마다 자동 갱신 (URL만 등록해도 동작)
        if "11st.co.kr" in url:
            try:
                live = fetch_11st_live(url, face)
                if live:
                    rate = live["rate"]
                    title = live["title"] or title
                    face = live["face"]
                    seller = seller or "11번가"
                else:
                    # 품절·판매중단·비정상가 → 노출 제외 (등록값으로 잘못 노출하지 않음)
                    print(f"[제외] 11번가 딜 확인 불가(품절/변경): {title[:30] or url}")
                    continue
            except Exception as e:
                print(f"[경고] 11번가 조회 오류({title[:20] or url}): {e}")
                if not rate or not title:
                    continue  # 등록 정보도 없으면 건너뜀
            time.sleep(0.3)

        else:
            # 11번가가 아닌 딜(지마켓·옥션 등)은 가격 자동 갱신이 안 되므로
            # 확인일이 오래되면 잘못된 시세를 노출하지 않도록 자동 제외한다.
            if is_stale(d.get("checked")):
                print(f"[만료] {MANUAL_STALE_DAYS}일 경과로 제외: {title[:30] or url}")
                continue

        if not rate or not title:
            print(f"[제외] 정보 부족(rate/title 없음): {url}")
            continue

        by_cat.setdefault(d.get("category", "기타"), []).append({
            "seller": seller,
            "rate": rate,
            "title": title,
            "url": to_deeplink(url),
            "manual": True,
        })
    return by_cat


# ─────────────────────────────────────────────────────────────
# 프리렌더: 수집 결과를 상품권딜.html 의 마커 구간에 정적 HTML로 굽는다.
# 네이버 크롤러(Yeti)는 JS를 렌더링하지 않으므로, 딜 데이터가 원본 HTML에
# 있어야 검색에 노출된다. JS는 페이지를 열 때 deals.json 으로 다시 그리므로
# 이중 렌더 문제는 없다 (성공 시 innerHTML 통째 교체).
# ─────────────────────────────────────────────────────────────

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEAL_PAGE = os.path.join(BASE_DIR, "html", "상품권딜.html")
SITEMAP_PATH = os.path.join(BASE_DIR, "html", "sitemap.xml")
PAGE_URL = "https://koreagiftcard.co.kr/상품권딜"
# IndexNow 공개 키 — html/<키>.txt 파일과 반드시 일치해야 한다 (공개되어도 무방한 값)
INDEXNOW_KEY = "d907cfe3732b7f0d4a64d7f84e3c9c28"

# 아래 상수·마크업은 상품권딜.html 의 JS 렌더러와 1:1 동일해야 한다.
# 마크업 구조를 바꿀 때는 반드시 양쪽을 함께 수정할 것.
CHEVRON_SVG = ('<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">'
               '<path d="M9 6l6 6-6 6" fill="none" stroke="currentColor" stroke-width="2"'
               ' stroke-linecap="round" stroke-linejoin="round"/></svg>')

MALL_LOGO = {
    "11번가": "img/mall/11st.png",
    "지마켓": "img/mall/gmarket.png",
    "옥션": "img/mall/auction.png",
    "롯데온": "img/mall/lotteon.png",
    "롯데on": "img/mall/lotteon.png",
    "네이버": "img/mall/naver.png",
}
LOGO_FALLBACK = "this.parentNode.classList.remove('has_logo');this.outerHTML=this.alt;"
NAVER_STORE_RE = re.compile(r"(smartstore|brand|shopping)\.naver\.com")


def esc(s):
    """JS 렌더러의 esc() 와 동일한 HTML 이스케이프."""
    return (str("" if s is None else s)
            .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;").replace("'", "&#39;"))


def fmt_rate(v):
    """5.0 → '5', 5.2 → '5.2' — JS 의 숫자 문자열 표기와 동일하게."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    return str(int(f)) if f == int(f) else str(f)


def seller_mark(name, naver_sellers):
    """판매처 표기: 로고 마켓은 로고, 네이버 스토어는 네이버 로고+스토어명, 그 외 이름."""
    src = MALL_LOGO.get(name)
    if src:
        return f'<img class="mall_logo" src="{src}" alt="{esc(name)}" onerror="{LOGO_FALLBACK}">'
    if name in naver_sellers:
        return ('<img class="platform_logo" src="img/mall/naver.png" alt="네이버" onerror="this.remove();">'
                f'<span class="store_name" title="{esc(name)}">{esc(name)}</span>')
    return esc(name)


def seller_class(name, naver_sellers):
    if name in MALL_LOGO:
        return " has_logo"
    return " has_platform" if name in naver_sellers else ""


def build_prerender(data):
    """deals 데이터 → 마커 이름별 정적 HTML 조각 dict."""
    naver_sellers = set()
    for g in data.get("deals", []):
        for it in g.get("items", []):
            if NAVER_STORE_RE.search(it.get("url") or ""):
                naver_sellers.add(it.get("seller"))
    ns = naver_sellers

    parts = {}
    parts["updatedAt"] = esc(data.get("updated_at") or "-")
    parts["dealNote"] = esc(data.get("note") or "")

    # 오늘의 최고 할인 TOP 3
    all_items = [it for g in data.get("deals", []) for it in g.get("items", [])]
    top3 = sorted(all_items, key=lambda d: d["rate"], reverse=True)[:3]
    parts["bestStrip"] = "".join(
        f'<a class="best_card rank{i + 1}" href="{esc(it["url"])}" target="_blank" rel="nofollow sponsored noopener">'
        f'<span class="rank_badge">TOP {i + 1}</span>'
        f'<div class="b_rate">{fmt_rate(it["rate"])}<small>%</small></div>'
        f'<span class="b_seller{seller_class(it["seller"], ns)}">{seller_mark(it["seller"], ns)}</span>'
        f'<div class="b_title">{esc(it["title"])}</div></a>'
        for i, it in enumerate(top3))

    # 마켓별 최고 할인율 요약표
    cols = data.get("summary", {}).get("columns", [])
    rows = data.get("summary", {}).get("rows", [])
    parts["summaryHead"] = ("<tr><th>판매처</th>"
                            + "".join(f"<th>{esc(c)}</th>" for c in cols) + "</tr>")
    best_per_col = []
    for ci in range(len(cols)):
        vals = [r["rates"][ci] for r in rows if r["rates"][ci] is not None]
        best_per_col.append(max(vals) if vals else None)
    body_rows = []
    for row in rows:
        tds = []
        for ci, v in enumerate(row["rates"]):
            if v is None:
                tds.append('<td class="none">-</td>')
            else:
                best = " best" if v == best_per_col[ci] else ""
                tds.append(f'<td><span class="rate{best}">{fmt_rate(v)}%</span></td>')
        body_rows.append(
            f'<tr><th><span class="seller_cell{seller_class(row["seller"], ns)}">'
            f'{seller_mark(row["seller"], ns)}</span></th>{"".join(tds)}</tr>')
    parts["summaryBody"] = "".join(body_rows)

    # 카테고리별 딜 목록
    groups_html = []
    for group in data.get("deals", []):
        sorted_items = sorted(group["items"], key=lambda d: d["rate"], reverse=True)
        best = sorted_items[0]["rate"] if sorted_items else None
        items_html = []
        for idx, it in enumerate(sorted_items):
            hot = " hot" if it["rate"] >= 6 else ""
            is_top = it["rate"] == best
            best_tag = '<span class="best_tag">최고</span>' if is_top else ""
            items_html.append(
                f'<a class="deal_item{" top" if is_top else ""}" href="{esc(it["url"])}"'
                f' target="_blank" rel="nofollow sponsored noopener">'
                f'<span class="rank">{idx + 1}</span>'
                f'<span class="seller{seller_class(it["seller"], ns)}">{seller_mark(it["seller"], ns)}</span>'
                f'<span class="rate_pill{hot}">{fmt_rate(it["rate"])}%</span>'
                f'<span class="d_title">{esc(it["title"])}</span>'
                f'{best_tag}<span class="go">{CHEVRON_SVG}</span></a>')
        groups_html.append(
            f'<div class="deal_group"><h3 class="deal_cat_title">{esc(group["category"])}</h3>'
            f'<div class="deal_list">{"".join(items_html)}</div></div>')
    parts["dealGroups"] = "".join(groups_html)

    # meta description — 카테고리별 최고 할인율을 담아 검색 스니펫 품질을 높인다
    cat_best = []
    for g in data.get("deals", []):
        if g.get("items"):
            top = max(g["items"], key=lambda d: d["rate"])
            cat_best.append((g["category"].split()[0], top["rate"]))
    cat_best.sort(key=lambda t: t[1], reverse=True)
    if cat_best:
        frag = "·".join(f"{name} {fmt_rate(rate)}%" for name, rate in cat_best[:3])
        desc = (f"오늘 상품권 최고 할인율: {frag}. 11번가·지마켓·옥션 등 신뢰 판매처의 "
                "컬쳐랜드·도서문화·백화점상품권 특가를 한국상품권협회가 매시간 자동 집계합니다.")
    else:  # 수집 결과가 비어도 스니펫이 깨지지 않게 기본 문구 유지
        desc = ("컬쳐랜드·도서문화·백화점상품권의 실시간 최고 할인율을 11번가·지마켓·옥션 등 "
                "신뢰 판매처만 선별해 한국상품권협회가 매시간 자동 집계합니다.")
    parts["metaDesc"] = f'<meta name="description" content="{esc(desc)}">'

    # ItemList 구조화 데이터 — 상위 딜 10개 (제휴 URL 은 넣지 않는다)
    top10 = sorted(all_items, key=lambda d: d["rate"], reverse=True)[:10]
    ld = {
        "@context": "https://schema.org",
        "@type": "ItemList",
        "name": "오늘의 상품권 할인 딜 TOP 10",
        "numberOfItems": len(top10),
        "itemListElement": [
            {"@type": "ListItem", "position": i + 1,
             "name": f"{it['title']} — {it['seller']} {fmt_rate(it['rate'])}% 할인"}
            for i, it in enumerate(top10)
        ],
    }
    # '<' 전체를 JSON 이스케이프(<)로 치환 — 상품명을 통한 </script> 탈출·
    # 프리렌더 마커 주입·HTML 주석 상태 오염을 한 번에 차단 (외부 입력 방어)
    ld_json = json.dumps(ld, ensure_ascii=False).replace("<", "\\u003c")
    parts["jsonld"] = f'<script type="application/ld+json">{ld_json}</script>'

    return parts


def apply_prerender(data):
    """상품권딜.html 의 <!--PR:이름--> ... <!--/PR:이름--> 구간을 실제 딜 HTML로 치환."""
    with open(DEAL_PAGE, encoding="utf-8", newline="") as f:
        html = f.read()
    parts = build_prerender(data)
    for name, content in parts.items():
        pattern = re.compile(
            r"(<!--PR:%s-->).*?(<!--/PR:%s-->)" % (re.escape(name), re.escape(name)), re.S)
        html, n = pattern.subn(lambda m, c=content: m.group(1) + c + m.group(2), html)
        if n != 1:
            # 마커가 지워지면 프리렌더가 화석화되므로 조용히 넘어가지 않고 실패시킨다
            print(f"[오류] 프리렌더 마커 'PR:{name}' 치환 실패(발견 {n}곳) — 상품권딜.html 의 마커를 확인하세요.")
            sys.exit(1)
    with open(DEAL_PAGE, "w", encoding="utf-8", newline="") as f:
        f.write(html)
    print(f"[완료] 상품권딜.html 프리렌더 갱신 ({len(parts)}개 구간)")


def update_sitemap_lastmod():
    """sitemap.xml 의 /상품권딜 lastmod 를 KST 오늘 날짜로. 날짜가 바뀐 첫 실행에서만
    실제로 변경되므로 하루 1회만 커밋 diff 가 생긴다. 변경 시 True 반환."""
    today = datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d")
    try:
        with open(SITEMAP_PATH, encoding="utf-8", newline="") as f:
            xml = f.read()
    except OSError as e:
        print(f"::warning::sitemap.xml 읽기 실패: {e}")
        return False
    pattern = re.compile(
        r"(<loc>https://koreagiftcard\.co\.kr/%EC%83%81%ED%92%88%EA%B6%8C%EB%94%9C</loc>\s*"
        r"<lastmod>)([^<]*)(</lastmod>)")
    m = pattern.search(xml)
    if not m:
        # ::warning:: — GitHub Actions 실행 요약에 노란 경고로 표시되어 묻히지 않게
        print("::warning::sitemap.xml 에서 상품권딜 항목을 찾지 못했습니다 — lastmod 갱신 생략")
        return False
    if m.group(2) == today:
        return False
    xml = pattern.sub(lambda mm: mm.group(1) + today + mm.group(3), xml, count=1)
    with open(SITEMAP_PATH, "w", encoding="utf-8", newline="") as f:
        f.write(xml)
    print(f"[완료] sitemap.xml 상품권딜 lastmod → {today}")
    return True


def ping_indexnow():
    """네이버·Bing 에 페이지 갱신을 통지 (IndexNow). GitHub Actions 에서만 실행되며
    실패해도 수집을 막지 않는다. 로컬 테스트에서는 아무것도 하지 않음."""
    if os.environ.get("GITHUB_ACTIONS") != "true":
        return
    ping = ("https://api.indexnow.org/indexnow?url="
            + urllib.parse.quote(PAGE_URL, safe="") + "&key=" + INDEXNOW_KEY)
    try:
        with urllib.request.urlopen(ping, timeout=10) as r:
            print(f"[완료] IndexNow 핑 전송 (HTTP {r.status})")
    except Exception as e:
        print(f"[경고] IndexNow 핑 실패: {e}")


def main():
    if not CLIENT_ID or not CLIENT_SECRET:
        print("[오류] 환경변수 NAVER_CLIENT_ID / NAVER_CLIENT_SECRET 가 설정되지 않았습니다.")
        print("       PowerShell에서:")
        print('       $env:NAVER_CLIENT_ID="..."; $env:NAVER_CLIENT_SECRET="..."')
        sys.exit(1)

    deals = []
    # (seller, category_key) -> 최고 할인율  (요약표용)
    matrix = {}
    sellers_seen = {}
    manual_by_cat = load_manual_deals()

    for cat in CATEGORIES:
        # 수동 등록 딜 먼저 반영 (자동수집이 놓친 특가)
        collected = list(manual_by_cat.pop(cat["name"], []))
        for item in cat["items"]:
            try:
                collected.extend(best_deals_for(
                    item["q"], item["face"], cat.get("include", []),
                    cat.get("deny", []), cat.get("must", [])))
            except urllib.error.HTTPError as e:
                if e.code == 401:
                    print("[오류] 인증 실패(401). Client ID/Secret 을 확인하세요.")
                    sys.exit(1)
                print(f"[경고] '{item['q']}' 검색 실패: HTTP {e.code}")
            except Exception as e:
                print(f"[경고] '{item['q']}' 검색 중 오류: {e}")
            time.sleep(0.1)  # API 예의상 약간의 간격

        # 중복 제거(같은 판매처+상품명) 후 할인율 높은 순 정렬, 상위 6개만 노출
        seen = set()
        deduped = []
        for d in sorted(collected, key=lambda d: d["rate"], reverse=True):
            sig = (d["seller"], d["title"])
            if sig in seen:
                continue
            seen.add(sig)
            deduped.append(d)
        collected = deduped
        top = collected[:6]
        if top:
            deals.append({"category": cat["name"], "items": [
                {"seller": d["seller"], "rate": d["rate"], "title": d["title"], "url": d["url"]}
                for d in top
            ]})

        # 요약표: 판매처×종류별 최고 할인율
        for d in collected:
            k = (d["seller"], cat["key"])
            if d["rate"] > matrix.get(k, -1):
                matrix[k] = d["rate"]
            sellers_seen[d["seller"]] = sellers_seen.get(d["seller"], 0) + 1

    # CATEGORIES 에 없는 수동 카테고리도 그대로 노출
    for cat_name, items in manual_by_cat.items():
        items.sort(key=lambda d: d["rate"], reverse=True)
        deals.append({"category": cat_name, "items": [
            {"seller": d["seller"], "rate": d["rate"], "title": d["title"], "url": d["url"]}
            for d in items
        ]})

    # 수집이 통째로 실패(API 장애·쿼터 초과 등)한 경우 빈 페이지를 배포하지 않도록
    # 실행 자체를 실패시켜 기존 deals.json·프리렌더를 보존한다 (조용한 실패 방지).
    total_items = sum(len(g["items"]) for g in deals)
    if total_items < 3:
        print(f"::error::수집된 딜이 {total_items}건뿐입니다 — API 장애 가능성. 기존 데이터를 보존하고 종료합니다.")
        sys.exit(1)

    columns = [c["key"] for c in CATEGORIES]
    # 매물이 많은 상위 6개 판매처만 요약표 행으로
    top_sellers = [s for s, _ in sorted(sellers_seen.items(), key=lambda x: x[1], reverse=True)[:6]]
    rows = []
    for s in top_sellers:
        rows.append({
            "seller": s,
            "rates": [matrix.get((s, col)) for col in columns],
        })

    kst = timezone(timedelta(hours=9))
    result = {
        "updated_at": datetime.now(kst).strftime("%Y-%m-%d %H:%M"),
        "note": "본 페이지는 대형 오픈마켓·공식 스토어 등 신뢰할 수 있는 판매처의 가격만 선별해 자동 계산합니다. 일부 링크는 제휴마케팅이 포함된 광고로 커미션을 지급받을 수 있으며, 실제 구매 조건은 판매처에서 확인해 주세요.",
        "summary": {"columns": columns, "rows": rows},
        "deals": deals,
    }

    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "html", "deals.json")
    # newline="\n" — 윈도우 로컬 실행과 리눅스 Actions 실행이 교차해도 개행 차이 diff 가 없게
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    # 프리렌더(SEO) + 사이트맵 갱신 + 색인 통지
    apply_prerender(result)
    if update_sitemap_lastmod():
        ping_indexnow()

    # 콘솔 요약 출력
    print(f"[완료] {out_path} 생성")
    print(f"       업데이트: {result['updated_at']}")
    print(f"       카테고리 {len(deals)}개 / 요약표 판매처 {len(rows)}개")
    for g in deals:
        if g["items"]:
            b = g["items"][0]
            print(f"       - {g['category']}: 최고 {b['rate']}% ({b['seller']})")
    if not deals:
        print("       ※ 조건에 맞는 매물이 없습니다. 검색어/액면가 범위를 조정해야 할 수 있어요.")


if __name__ == "__main__":
    if "--render-only" in sys.argv:
        # API 수집 없이 기존 html/deals.json 으로 프리렌더만 다시 실행 (로컬 점검용)
        with open(os.path.join(BASE_DIR, "html", "deals.json"), encoding="utf-8") as f:
            apply_prerender(json.load(f))
        update_sitemap_lastmod()
    else:
        main()
