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
    {"key": "롯데", "name": "롯데백화점 상품권",
     "include": ["롯데"], "must": ["백화점"],
     "deny": ["신세계", "현대", "컬쳐", "컬처", "투썸", "스타벅스", "갤러리아",
              "시네마", "마트", "월드", "하이마트", "슈퍼", "면세", "홈쇼핑", "리아"],
     "items": [
        {"q": "롯데백화점 상품권 5만원", "face": 50000},
        {"q": "롯데백화점 상품권 10만원", "face": 100000},
     ]},
    {"key": "현대", "name": "현대백화점 상품권",
     "include": ["현대"], "must": ["백화점"],
     "deny": ["신세계", "롯데", "컬쳐", "컬처", "투썸", "스타벅스", "갤러리아",
              "홈쇼핑", "면세", "그룹", "통합"],
     "items": [
        {"q": "현대백화점 상품권 5만원", "face": 50000},
        {"q": "현대백화점 상품권 10만원", "face": 100000},
     ]},
    {"key": "신세계", "name": "신세계 상품권",
     "include": ["신세계"],
     "deny": ["롯데", "현대", "컬쳐", "컬처", "투썸", "스타벅스", "갤러리아",
              "면세", "아울렛", "이마트"],
     "items": [
        {"q": "신세계 모바일상품권 5만원", "face": 50000},
        {"q": "신세계상품권 10만원", "face": 100000},
     ]},
]

TAG_RE = re.compile(r"<[^>]+>")


def clean(text):
    """검색 결과 title 의 <b> 태그 등 제거."""
    return TAG_RE.sub("", text).replace("&amp;", "&").strip()


def search_shop(query, display=40):
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
        title = clean(it.get("title", ""))
        # 브랜드 필터: include 중 하나 이상 포함 / must 는 모두 포함 / deny 는 하나도 없어야
        if include and not any(k in title for k in include):
            continue
        if must and not all(k in title for k in must):
            continue
        if deny and any(k in title for k in deny):
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
            "seller": clean(it.get("mallName", "기타")),
            "rate": rate,
            "price": price,
            "face": face,
            "title": title,
            "url": it.get("link", "#"),
        })
    return out


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

    for cat in CATEGORIES:
        collected = []
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
        "note": "본 페이지의 딜 정보는 네이버 쇼핑 검색 결과의 최저가를 수집해 자동 계산됩니다. 실제 구매 조건은 판매처에서 확인해 주세요.",
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
