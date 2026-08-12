# -*- coding: utf-8 -*-
"""
상품권 최저가를 모아 할인율을 계산하고 html/deals.json 과 프리렌더를
자동 생성하는 스크립트.

데이터 소스:
  - 11번가 등록 딜: 상품 페이지의 JSON-LD 를 매 실행 조회해 현재가·품절 자동 반영
  - 수동 등록 딜(지마켓·옥션 등): manual_deals.json, 14일 지나면 자동 만료
  - 네이버 쇼핑 검색 API: 2026-07-31 폐지(SE05)되어 현재 비활성
    → NAVER_SHOP_SEARCH_ENABLED 주석 참고

사용법 (Windows PowerShell):
    python collect_deals.py

네이버 검색을 다시 켤 때만 키가 필요합니다. 키는 코드에 절대 넣지 말고
환경변수로만 전달합니다.
    $env:NAVER_CLIENT_ID="발급받은_Client_ID"
    $env:NAVER_CLIENT_SECRET="발급받은_Client_Secret"
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

# ── 네이버 쇼핑 검색 API 중단 (2026-08-12 원인 확정) ─────────────
# 2026-07-31 18:43 KST 실행을 마지막으로 모든 검색어가 HTTP 404 로 실패해 왔다.
# 2026-08-12 Actions 에서 같은 키로 두 API 를 대조 호출한 결과:
#   /v1/search/shop.json → HTTP 404  errorCode "SE05"
#                          "Invalid search api (존재하지 않는 검색 api 입니다.)"
#   /v1/search/blog.json → HTTP 200  정상 응답 (같은 키·같은 앱)
# 블로그 검색이 성공하므로 키·앱·쿼터는 정상이며, 401(인증)도 429(한도)도 아닌
# SE05 는 "그 API 가 존재하지 않는다"는 뜻이다 → 쇼핑 검색 API 자체가 폐지됐다.
# 코드로 고칠 수 있는 장애가 아니므로 무의미한 매시간 404 호출을 중단한다.
# CATEGORIES 의 검색어·필터 정의는 그대로 남겨 둔다 — 네이버가 API 를 되살리거나
# 동등한 검색형 소스를 붙일 때 이 값을 True 로 되돌리면 즉시 복구된다.
NAVER_SHOP_SEARCH_ENABLED = False

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


def days_since_checked(checked):
    """checked 날짜(YYYY-MM-DD)로부터 KST 오늘까지 경과 일수. 없거나 형식 오류면 None."""
    if not checked:
        return None  # 확인일이 없으면 신뢰할 수 없음
    try:
        d = datetime.strptime(checked, "%Y-%m-%d").date()
    except ValueError:
        return None
    kst_today = datetime.now(timezone(timedelta(hours=9))).date()
    return (kst_today - d).days


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
    expired = []   # 만료로 제외된 수동 딜 (요약 경고용)
    expiring = []  # 만료 임박 수동 딜 (요약 경고용)
    # 네이버 쇼핑 검색 폐지 후 11번가 실시간 조회가 유일하게 남은 자동 갱신 경로다.
    # 이 건수가 0 이 되면 페이지에 자동 검증되는 딜이 하나도 없다는 뜻이므로 감시한다.
    live_ok = 0
    for d in data.get("deals", []):
        url = d.get("url", "")
        # URL 미입력(플레이스홀더) 항목은 건너뜀
        if not url or url.startswith("여기에") or url == "#":
            continue
        rate = d.get("rate", 0)
        face = d.get("face")
        price = d.get("price")
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
                    price = live["price"]
                    seller = seller or "11번가"
                    live_ok += 1
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
            days = days_since_checked(d.get("checked"))
            if days is None or days > MANUAL_STALE_DAYS:
                print(f"[만료] 제외(checked={d.get('checked') or '없음'}): {seller} {title[:30] or url}")
                expired.append(f"{seller} {title[:20] or url}")
                continue
            # 자정(KST) 경계에서 소리 없이 일괄 소멸하는 일을 막기 위한 사전 예고
            days_left = MANUAL_STALE_DAYS - days + 1  # 노출 제외까지 남은 일수
            if days_left <= 3:
                print(f"[만료 임박] D-{days_left}: {seller} {title[:30] or url}")
                expiring.append(f"D-{days_left} {seller} {title[:20] or url}")

        if not rate or not title:
            print(f"[제외] 정보 부족(rate/title 없음): {url}")
            continue

        by_cat.setdefault(d.get("category", "기타"), []).append({
            "seller": seller,
            "rate": rate,
            "price": price,
            "face": face,
            "title": title,
            "url": to_deeplink(url),
            "manual": True,
        })

    # 경고는 건당이 아니라 요약 한 줄로 — GitHub Actions 애너테이션은 스텝당
    # warning 10개까지만 표시되므로, 일괄 만료(11건 등)가 다른 중요 경고
    # (자동수집 0건 등)를 애너테이션에서 밀어내지 않게 한다. 상세는 개별 로그 참조.
    if expired:
        print(f"::warning::[만료] 수동 딜 {len(expired)}건 노출 제외({MANUAL_STALE_DAYS}일 경과/checked 누락) — 시세 확인 후 manual_deals.json 의 checked 갱신 시 재노출: "
              + "; ".join(expired[:5]) + (f" 외 {len(expired) - 5}건" if len(expired) > 5 else ""))
    if expiring:
        print(f"::warning::[만료 임박] 수동 딜 {len(expiring)}건 — manual_deals.json 의 checked 갱신 필요: "
              + "; ".join(expiring[:5]) + (f" 외 {len(expiring) - 5}건" if len(expiring) > 5 else ""))
    return by_cat, live_ok


# ─────────────────────────────────────────────────────────────
# 프리렌더: 수집 결과를 상품권딜.html 의 마커 구간에 정적 HTML로 굽는다.
# 네이버 크롤러(Yeti)는 JS를 렌더링하지 않으므로, 딜 데이터가 원본 HTML에
# 있어야 검색에 노출된다. JS는 페이지를 열 때 deals.json 으로 다시 그리므로
# 이중 렌더 문제는 없다 (성공 시 innerHTML 통째 교체).
# ─────────────────────────────────────────────────────────────

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEAL_PAGE = os.path.join(BASE_DIR, "html", "상품권딜.html")
SITEMAP_PATH = os.path.join(BASE_DIR, "html", "sitemap.xml")
HISTORY_PATH = os.path.join(BASE_DIR, "html", "rates_history.json")  # 시세 트렌드 이력 (14일)
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

# 라이브 시세 스트림 티커 — 카테고리(첫 단어) → 브랜드 로고 / 폴백 칩 색상
# JS 렌더러의 TICKER_LOGO/TICKER_CHIP 과 동일해야 함.
TICKER_LOGO = {
    # 파일명은 ASCII 로 유지 — 한글 파일명은 URL 인코딩·캐시 키 문제를 일으킬 수 있음
    "컬쳐랜드": "img/1/ticker-cultureland.png",
    "도서문화상품권": "img/1/ticker-booknlife.png",
    "롯데": "img/1/ticker-lotte.png",
    "신세계": "img/1/ticker-shinsegae.png",
}
TICKER_CHIP = {
    "컬쳐랜드": "#7A5AF8",
    "도서문화상품권": "#0FA47F",
    "롯데": "#E60013",
    "신세계": "#1F2937",
    "현대백화점": "#0B4A32",
}


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


def pill_class(rate):
    """할인율 크기에 따른 pill 농도 차등 — JS 렌더러의 pillClass() 와 동일해야 함."""
    if rate >= 6:
        return " hot"
    if rate >= 5:
        return " r5"
    if rate >= 3:
        return ""
    return " r1"


def item_price(it):
    """딜 목록의 실구매가 표기 (가격 정보가 있는 딜만)."""
    price = it.get("price")
    if not price:
        return ""
    return f'<span class="d_price">{price:,}원</span>'


def fmt_face(face):
    """액면가 표기: 50000 → '5만원권' — JS 렌더러의 fmtFace() 와 동일해야 함."""
    if not face:
        return ""
    face = int(face)  # float 로 들어와도 JS 표기('5만원권')와 어긋나지 않게
    if face % 10000 == 0:
        return f"{face // 10000}만원권"
    return f"{face:,}원권"


def append_history(result):
    """매시간 최고 할인율 1점을 rates_history.json 에 기록 (트렌드 차트용, 14일 보관).
    이력 기록 실패가 수집 자체를 막지는 않는다."""
    try:
        rates = [it["rate"] for g in result.get("deals", []) for it in g.get("items", [])]
        if not rates:
            return
        if os.path.exists(HISTORY_PATH):
            try:
                with open(HISTORY_PATH, encoding="utf-8") as f:
                    hist = json.load(f).get("points", [])
            except Exception as e:
                # 파일이 있는데 못 읽으면 덮어쓰지 않는다 — 조용한 이력 소실 방지.
                # 다음 정상 실행에서 파일이 복구되면 자연히 재개된다.
                print(f"::warning::rates_history.json 파싱 실패({e}) — 이번 시간 기록 생략")
                return
        else:
            hist = []
        t = result["updated_at"]
        if hist and hist[-1].get("t") == t:
            return
        hist.append({"t": t, "best": round(max(rates), 1),
                     "avg": round(sum(rates) / len(rates), 2)})
        cutoff = (datetime.now(timezone(timedelta(hours=9)))
                  - timedelta(days=14)).strftime("%Y-%m-%d %H:%M")
        hist = [p for p in hist if isinstance(p, dict) and p.get("t", "") >= cutoff]
        # 임시 파일 + 원자적 교체 — 쓰기 도중 중단돼도 잘린 파일이 남지 않게
        tmp = HISTORY_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            json.dump({"points": hist}, f, ensure_ascii=False, indent=1)
        os.replace(tmp, HISTORY_PATH)
    except Exception as e:
        print(f"::warning::시세 이력 기록 실패: {e}")


TREND_EMPTY = '<p class="trend_empty">시세 이력을 수집하는 중입니다. 잠시 후 다시 확인해 주세요.</p>'


def build_trend():
    """rates_history.json → 최근 7일 최고 할인율 스파크라인 SVG + 전일 대비 요약.
    프리렌더 전용 구간 — JS 렌더러는 이 영역을 다시 그리지 않는다.
    이력이 어떻게 오염돼 있어도 수집 잡을 죽이지 않는다 (실패 시 안내 문구)."""
    try:
        return _build_trend_inner()
    except Exception as e:
        print(f"::warning::트렌드 차트 생성 실패: {e}")
        return TREND_EMPTY


def _median3(vals):
    """3점 중앙값 필터 — 단일 포인트 결측 스파이크 제거 (표시 전용, 원본 미변경)."""
    if len(vals) < 3:
        return list(vals)
    out = [vals[0]]
    for i in range(1, len(vals) - 1):
        out.append(sorted(vals[i - 1:i + 2])[1])
    out.append(vals[-1])
    return out


def _smooth_path(coords):
    """Catmull-Rom → Bezier 변환으로 부드러운 곡선 경로 생성."""
    if len(coords) < 3:
        return "M" + " L".join(f"{x},{y}" for x, y in coords)
    d = f"M{coords[0][0]},{coords[0][1]}"
    for i in range(len(coords) - 1):
        p0 = coords[i - 1] if i else coords[i]
        p1, p2 = coords[i], coords[i + 1]
        p3 = coords[i + 2] if i + 2 < len(coords) else p2
        c1x = round(p1[0] + (p2[0] - p0[0]) / 6, 1)
        c1y = round(p1[1] + (p2[1] - p0[1]) / 6, 1)
        c2x = round(p2[0] - (p3[0] - p1[0]) / 6, 1)
        c2y = round(p2[1] - (p3[1] - p1[1]) / 6, 1)
        d += f" C{c1x},{c1y} {c2x},{c2y} {p2[0]},{p2[1]}"
    return d


def _build_trend_inner():
    try:
        with open(HISTORY_PATH, encoding="utf-8") as f:
            pts = json.load(f).get("points", [])
    except Exception:
        pts = []
    kst_now = datetime.now(timezone(timedelta(hours=9)))
    cutoff = (kst_now - timedelta(days=7)).strftime("%Y-%m-%d %H:%M")
    # 항목 형태를 엄격히 검증 — dict 아님·t 문자열 아님·best 숫자 아님(bool 포함)은 제외
    pts = [p for p in pts
           if isinstance(p, dict)
           and isinstance(p.get("t"), str)
           and isinstance(p.get("best"), (int, float))
           and not isinstance(p.get("best"), bool)
           and p["t"] >= cutoff]
    if len(pts) < 2:
        return TREND_EMPTY

    # 표시용 보정: 단일 포인트 수집 결측 스파이크는 3점 중앙값으로 제거 (원본 이력은 그대로 보존)
    best_raw = [p["best"] for p in pts]
    best_vals = _median3(best_raw)
    lo, hi = min(best_raw), max(best_raw)  # 문구 표기는 원본 기준
    avg_raw = [p.get("avg") for p in pts]
    has_avg = all(isinstance(a, (int, float)) and not isinstance(a, bool) for a in avg_raw)
    avg_vals = _median3(avg_raw) if has_avg else None

    series_all = best_vals + (avg_vals or [])
    s_lo, s_hi = min(series_all), max(series_all)
    pad = max(0.3, (s_hi - s_lo) * 0.15)
    vmin, vmax = s_lo - pad, s_hi + pad

    W, H = 280, 100
    PL, PR, PT, PB = 30, 10, 8, 6
    n = len(pts)

    def xy(i, v):
        x = round(PL + (W - PL - PR) * (i / (n - 1)), 1)
        y = round(PT + (H - PT - PB) * (1 - (v - vmin) / (vmax - vmin)), 1)
        return x, y

    # 가로 그리드 + % 눈금 (상·중·하)
    grid_parts = []
    for gv in (s_hi, (s_hi + s_lo) / 2, s_lo):
        gy = xy(0, gv)[1]
        grid_parts.append(
            f'<line x1="{PL}" y1="{gy}" x2="{W - PR}" y2="{gy}" stroke="#e7edf6"'
            f' stroke-width="1" stroke-dasharray="3 3"/>'
            f'<text x="{PL - 4}" y="{gy + 3}" font-size="8.5" fill="#a6adba"'
            f' text-anchor="end">{round(gv, 1)}%</text>')

    best_c = [xy(i, v) for i, v in enumerate(best_vals)]
    line_best = _smooth_path(best_c)
    area = line_best + f" L{best_c[-1][0]},{H - PB} L{best_c[0][0]},{H - PB} Z"
    bx, by = best_c[-1]

    avg_svg = ""
    if avg_vals:
        avg_c = [xy(i, v) for i, v in enumerate(avg_vals)]
        ax, ay = avg_c[-1]
        avg_svg = (f'<path class="t_avg" d="{_smooth_path(avg_c)}" fill="none" stroke="#9dc4f2"'
                   f' stroke-width="1.6" stroke-dasharray="4 3" stroke-linecap="round"/>'
                   f'<circle class="t_avg_dot" cx="{ax}" cy="{ay}" r="2.4" fill="#9dc4f2"/>')

    svg = (f'<svg class="trend_svg" viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg"'
           f' role="img" aria-label="최근 7일 상품권 할인율 추이 (최고·평균)">'
           f'<defs><linearGradient id="trendFill" x1="0" y1="0" x2="0" y2="1">'
           f'<stop offset="0" stop-color="#097cff" stop-opacity="0.16"/>'
           f'<stop offset="1" stop-color="#097cff" stop-opacity="0"/></linearGradient></defs>'
           f'{"".join(grid_parts)}'
           f'<path class="t_area" d="{area}" fill="url(#trendFill)"/>'
           f'{avg_svg}'
           f'<path class="t_line" d="{line_best}" pathLength="100" fill="none" stroke="#097cff"'
           f' stroke-width="2.2" stroke-linejoin="round" stroke-linecap="round"/>'
           f'<circle class="t_halo" cx="{bx}" cy="{by}" r="7" fill="#097cff" opacity="0"/>'
           f'<circle class="t_dot" cx="{bx}" cy="{by}" r="3.4" fill="#097cff"/></svg>')
    legend = ('<div class="trend_legend"><span class="lg b">최고 할인율</span>'
              '<span class="lg a">평균 할인율</span></div>' if avg_vals else "")
    svg = legend + svg
    # 마지막 포인트가 오늘이 아닐 수도 있으므로 (이력 갱신 지연 등) 날짜를 정직하게 표기
    today = kst_now.strftime("%Y-%m-%d")
    last_t = pts[-1]["t"]
    last_label = (f"오늘 {last_t[11:]}" if last_t[:10] == today
                  else f'{last_t[5:10].replace("-", ".")} {last_t[11:]}')
    axis = (f'<div class="trend_axis"><span>{pts[0]["t"][5:10].replace("-", ".")}</span>'
            f'<span>{last_label}</span></div>')

    yday = (kst_now - timedelta(days=1)).strftime("%Y-%m-%d")
    t_vals = [p["best"] for p in pts if p["t"][:10] == today]
    y_vals = [p["best"] for p in pts if p["t"][:10] == yday]
    if t_vals and y_vals:
        diff = round(sum(t_vals) / len(t_vals) - sum(y_vals) / len(y_vals), 2)
        if diff >= 0.05:
            delta = f'<div class="trend_delta up">▲ 할인율 전일 대비 평균 +{diff}%p</div>'
        elif diff <= -0.05:
            delta = f'<div class="trend_delta down">▼ 할인율 전일 대비 평균 {diff}%p</div>'
        else:
            delta = '<div class="trend_delta">전일과 비슷한 수준입니다</div>'
    else:
        delta = f'<div class="trend_delta">7일 최고 {fmt_rate(hi)}% · 최저 {fmt_rate(lo)}%</div>'
    return svg + axis + delta


def build_hero_stats(data):
    """실측 가능한 숫자만 사용하는 통계 타일 3개 (허수 금지 — 협회 신뢰 원칙).
    모든 수치는 지금 페이지에 실제 노출되는 데이터에서 계산한다 (설정 개수 하드코딩 금지)."""
    deals = data.get("deals", [])
    n_items = sum(len(g.get("items", [])) for g in deals)
    sellers = {it.get("seller") for g in deals for it in g.get("items", []) if it.get("seller")}
    return (f'<div class="stat"><b>{len(sellers)}곳</b><span>오늘 딜 노출 판매처 · 신뢰 필터 통과</span></div>'
            f'<div class="stat"><b>{len(deals)}종 · {n_items}건</b><span>오늘의 상품권 종류 · 등록 딜</span></div>'
            f'<div class="stat"><b>24회</b><span>매일 자동 갱신 · 매시간 집계</span></div>')


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

    # 오늘의 최고 할인 TOP 3 — 같은 딜 반복을 피하기 위해 "카테고리별 대표(최고) 딜"로 다양화
    all_items = [it for g in data.get("deals", []) for it in g.get("items", [])]
    cat_best = []
    for g in data.get("deals", []):
        if g.get("items"):
            best_it = max(g["items"], key=lambda d: d["rate"])  # 동률이면 앞선 항목 (JS reduce 와 동일)
            # split(" ") — JS 의 split(' ') 과 동일한 U+0020 단일 구분 (split() 은 탭·NBSP 도 갈라 어긋남)
            cat_best.append((g["category"].split(" ")[0], best_it))
    cat_best.sort(key=lambda t: t[1]["rate"], reverse=True)
    rows = []
    for i, (cat, it) in enumerate(cat_best[:3]):
        face_small = f'<small>{fmt_face(it["face"])}</small>' if it.get("face") else ""
        price_small = f'<small>{it["price"]:,}원</small>' if it.get("price") else ""
        rows.append(
            f'<a class="hot3_row" href="{esc(it["url"])}" target="_blank"'
            f' rel="nofollow sponsored noopener" title="{esc(it["title"])}">'
            f'<span class="medal m{i + 1}">{i + 1}</span>'
            f'<span class="h3_seller{seller_class(it["seller"], ns)}">{seller_mark(it["seller"], ns)}</span>'
            f'<div class="h3_main"><b>{esc(cat)}</b>{face_small}</div>'
            f'<div class="h3_val"><b>{fmt_rate(it["rate"])}%</b>{price_small}</div>'
            f'<span class="go">{CHEVRON_SVG}</span></a>')
    parts["bestStrip"] = "".join(rows)

    # 라이브 시세 스트림 티커 — 카테고리별 대표 딜 카드 (마퀴 무한롤링용 2행 복제)
    cards = []
    for cat, it in cat_best:
        logo = TICKER_LOGO.get(cat)
        img = (f'<img class="kgt-logo" src="{logo}" alt="{esc(cat)}" onerror="this.remove()">'
               if logo else "")
        chip = f'<i style="background:{TICKER_CHIP.get(cat, "#6B7684")};">{esc(cat[:1])}</i>'
        if it.get("price"):
            sub = f'{it["price"]:,}원'
        elif it.get("face"):
            sub = fmt_face(it["face"])
        else:
            sub = esc(it["seller"])
        cards.append(
            f'<div class="kgt-card"><div class="kgt-brand">{img}{chip}<span>{esc(cat)}</span></div>'
            f'<div class="kgt-rate"><b>{fmt_rate(it["rate"])}%↓</b><span>{sub}</span></div></div>')
    row = f'<div class="kgt-row">{"".join(cards)}</div>'
    parts["tickerCards"] = row + row

    # 시세 트렌드 · 통계 (프리렌더 전용 — JS 는 이 구간을 다시 그리지 않음)
    parts["trendChart"] = build_trend()
    parts["heroStats"] = build_hero_stats(data)

    # 카테고리 바로가기 칩 (sticky) — 딜 그룹 id 와 1:1 대응
    parts["catChips"] = "".join(
        f'<a class="chip" href="#dealcat-{i}">{esc(g["category"].split(" ")[0])}</a>'
        for i, g in enumerate(data.get("deals", [])))

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

    # 카테고리별 딜 목록 — "최고" 배지는 1위 한 건만, pill 은 할인율에 비례한 농도
    groups_html = []
    for gi, group in enumerate(data.get("deals", [])):
        sorted_items = sorted(group["items"], key=lambda d: d["rate"], reverse=True)
        items_html = []
        for idx, it in enumerate(sorted_items):
            is_top = idx == 0
            best_tag = '<span class="best_tag">최고</span>' if is_top else ""
            items_html.append(
                f'<a class="deal_item{" top" if is_top else ""}" href="{esc(it["url"])}"'
                f' target="_blank" rel="nofollow sponsored noopener">'
                f'<span class="rank">{idx + 1}</span>'
                f'<span class="seller{seller_class(it["seller"], ns)}">{seller_mark(it["seller"], ns)}</span>'
                f'<span class="rate_pill{pill_class(it["rate"])}">{fmt_rate(it["rate"])}%</span>'
                f'<span class="d_title">{esc(it["title"])}</span>'
                f'{item_price(it)}'
                f'{best_tag}<span class="go">{CHEVRON_SVG}</span></a>')
        groups_html.append(
            f'<div class="deal_group" id="dealcat-{gi}">'
            f'<h3 class="deal_cat_title">{esc(group["category"])}</h3>'
            f'<div class="deal_list">{"".join(items_html)}</div></div>')
    parts["dealGroups"] = "".join(groups_html)

    # meta description — 카테고리별 최고 할인율을 담아 검색 스니펫 품질을 높인다
    cat_best = []
    for g in data.get("deals", []):
        if g.get("items"):
            top = max(g["items"], key=lambda d: d["rate"])
            cat_best.append((g["category"].split(" ")[0], top["rate"]))
    cat_best.sort(key=lambda t: t[1], reverse=True)
    if cat_best:
        frag = "·".join(f"{name} {fmt_rate(rate)}%" for name, rate in cat_best[:3])
        desc = (f"오늘의 상품권 핫딜 최고 할인율: {frag}. 11번가·지마켓·옥션 등 신뢰 판매처의 "
                "컬쳐랜드·도서문화·백화점상품권 특가를 한국상품권협회가 매시간 자동 집계합니다.")
    else:  # 수집 결과가 비어도 스니펫이 깨지지 않게 기본 문구 유지
        desc = ("컬쳐랜드·도서문화·백화점상품권 핫딜의 실시간 할인율을 11번가·지마켓·옥션 등 "
                "신뢰 판매처만 선별해 한국상품권협회가 매시간 자동 집계합니다.")
    parts["metaDesc"] = f'<meta name="description" content="{esc(desc)}">'

    # ItemList 구조화 데이터 — 상위 딜 10개 (제휴 URL 은 넣지 않는다)
    top10 = sorted(all_items, key=lambda d: d["rate"], reverse=True)[:10]
    ld = {
        "@context": "https://schema.org",
        "@type": "ItemList",
        "name": "오늘의 상품권 핫딜 TOP 10",
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
    # 네이버 쇼핑 검색이 폐지된 뒤로는 키가 없어도 11번가 실시간 조회 + 수동 딜로
    # 정상 동작한다. 검색을 다시 켤 때만 키를 필수로 요구한다.
    if NAVER_SHOP_SEARCH_ENABLED and (not CLIENT_ID or not CLIENT_SECRET):
        print("[오류] 환경변수 NAVER_CLIENT_ID / NAVER_CLIENT_SECRET 가 설정되지 않았습니다.")
        print("       PowerShell에서:")
        print('       $env:NAVER_CLIENT_ID="..."; $env:NAVER_CLIENT_SECRET="..."')
        sys.exit(1)

    deals = []
    # (seller, category_key) -> 최고 할인율  (요약표용)
    matrix = {}
    sellers_seen = {}
    auto_items = 0  # 네이버 API 자동수집으로 필터를 통과한 딜 수 (현재 API 폐지로 항상 0)
    manual_by_cat, live_items = load_manual_deals()

    for cat in CATEGORIES:
        # 수동 등록 딜 먼저 반영 (자동수집이 놓친 특가)
        collected = list(manual_by_cat.pop(cat["name"], []))
        for item in cat["items"] if NAVER_SHOP_SEARCH_ENABLED else []:
            try:
                found = best_deals_for(
                    item["q"], item["face"], cat.get("include", []),
                    cat.get("deny", []), cat.get("must", []))
                auto_items += len(found)
                collected.extend(found)
            except urllib.error.HTTPError as e:
                if e.code == 401:
                    print("[오류] 인증 실패(401). Client ID/Secret 을 확인하세요.")
                    sys.exit(1)
                # 응답 본문에 네이버 errorCode 가 들어 있다 — 원인 판별에 필수이므로 함께 남긴다
                try:
                    detail = e.read().decode("utf-8", "replace")[:200].replace("\n", " ")
                except Exception:
                    detail = "(본문 읽기 실패)"
                print(f"[경고] '{item['q']}' 검색 실패: HTTP {e.code} {detail}")
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
            # price·face 는 값이 있는 딜에만 포함 (실구매가·절약액 표시용)
            deals.append({"category": cat["name"], "items": [
                {k: v for k, v in {
                    "seller": d["seller"], "rate": d["rate"], "title": d["title"],
                    "url": d["url"], "price": d.get("price"), "face": d.get("face"),
                }.items() if v is not None}
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
            {k: v for k, v in {
                "seller": d["seller"], "rate": d["rate"], "title": d["title"],
                "url": d["url"], "price": d.get("price"), "face": d.get("face"),
            }.items() if v is not None}
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

    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "html", "deals.json")

    # 자동 갱신 전멸 감시 — 수동딜만으로 위 가드(3건)를 통과하면 자동 경로가 죽어도
    # 워크플로가 계속 성공해 장애가 묻힌다(2026-07-31~08-11 실제 사건).
    # 네이버 쇼핑 검색이 폐지된 지금은 11번가 실시간 조회가 유일한 자동 경로이므로,
    # 감시 대상을 "네이버 수집 0건"에서 "11번가 실시간 조회 0건"으로 옮긴다.
    # (네이버 기준으로 두면 복구 불가능한 원인으로 매일 알림이 울려 소음만 된다.)
    prev_streak = 0
    try:
        with open(out_path, encoding="utf-8") as f:
            prev_streak = int(json.load(f).get("collect_health", {}).get("live_zero_streak", 0) or 0)
    except Exception:
        pass
    live_zero_streak = prev_streak + 1 if live_items == 0 else 0
    if live_items == 0:
        print(f"::warning::11번가 실시간 조회 0건 (연속 {live_zero_streak}회) — 자동으로 검증되는 딜이 "
              "하나도 없습니다. 11번가 페이지 구조 변경·등록 상품 전량 품절 여부를 점검하세요.")

    kst = timezone(timedelta(hours=9))
    result = {
        "updated_at": datetime.now(kst).strftime("%Y-%m-%d %H:%M"),
        "note": "본 페이지는 대형 오픈마켓·공식 스토어 등 신뢰할 수 있는 판매처의 가격만 선별해 자동 계산합니다. 일부 링크는 제휴마케팅이 포함된 광고로 커미션을 지급받을 수 있으며, 실제 구매 조건은 판매처에서 확인해 주세요.",
        "collect_health": {
            # live_* : 11번가 실시간 조회(현재 유일한 자동 갱신 경로) 감시 지표
            "live_items": live_items,
            "live_zero_streak": live_zero_streak,
            # 네이버 쇼핑 검색은 2026-07-31 폐지(SE05) — 되살아나기 전까지 항상 0
            "auto_items": auto_items,
            "naver_shop_api": "disabled" if not NAVER_SHOP_SEARCH_ENABLED else "enabled",
        },
        "summary": {"columns": columns, "rows": rows},
        "deals": deals,
    }

    # newline="\n" — 윈도우 로컬 실행과 리눅스 Actions 실행이 교차해도 개행 차이 diff 가 없게
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    # 시세 이력 기록 + 프리렌더(SEO) + 사이트맵 갱신 + 색인 통지
    append_history(result)
    apply_prerender(result)
    if update_sitemap_lastmod():
        ping_indexnow()

    # 콘솔 요약 출력
    print(f"[완료] {out_path} 생성")
    print(f"       업데이트: {result['updated_at']}")
    print(f"       카테고리 {len(deals)}개 / 요약표 판매처 {len(rows)}개 / "
          f"11번가 실시간 {live_items}건 / 네이버 자동수집 {auto_items}건"
          f"{' (API 폐지로 비활성)' if not NAVER_SHOP_SEARCH_ENABLED else ''}")
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
