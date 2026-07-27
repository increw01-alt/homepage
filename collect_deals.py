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


def fetch_11st_live(url, face):
    """11번가 상품 페이지에서 현재 판매가를 읽어 (price, rate) 반환. 실패 시 None."""
    req = urllib.request.Request(url, headers=BROWSER_HDRS)
    with urllib.request.urlopen(req, timeout=12) as r:
        html = r.read().decode("utf-8", errors="ignore")
    m = re.search(r"가격\s*:\s*([\d,]+)원", html)
    if not m:
        return None
    price = int(m.group(1).replace(",", ""))
    # 액면가 대비 상식적 범위(70~102%)만 인정 — 품절·페이지 변경 오탐 방지
    if not (face * 0.70 <= price <= face * 1.02):
        return None
    rate = round((face - price) / face * 100, 1)
    if rate <= 0:
        return None
    return price, rate


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
        # 11번가 딜은 실행 시마다 현재가로 할인율 자동 갱신 (실패하면 등록값 유지)
        if face and "11st.co.kr" in url:
            try:
                live = fetch_11st_live(url, face)
                if live:
                    rate = live[1]
                else:
                    print(f"[경고] 11번가 가격 확인 실패(등록값 사용): {d.get('title','')[:30]}")
            except Exception as e:
                print(f"[경고] 11번가 조회 오류(등록값 사용): {e}")
            time.sleep(0.3)
        by_cat.setdefault(d.get("category", "기타"), []).append({
            "seller": d.get("seller", ""),
            "rate": rate,
            "title": d.get("title", ""),
            "url": to_deeplink(url),
            "manual": True,
        })
    return by_cat


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
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

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
    main()
