# -*- coding: utf-8 -*-
"""휴대폰에서 보낸 딜 URL을 manual_deals.json 에 등록하는 스크립트.

GitHub Issue 본문(환경변수 ISSUE_BODY) 또는 명령행 인자에서 상품 URL을 찾아
manual_deals.json 에 추가한다. 11번가는 상품 페이지에서 상품명·가격·액면가를
자동으로 읽어오므로 URL만 있으면 되고, 지마켓·옥션은 본문에 할인율(예: 3.2%)과
액면가(예: 5만원)를 함께 적어야 한다.

사용 예:
    python add_deal.py https://www.11st.co.kr/products/9315309544
    ISSUE_BODY="https://item.gmarket.co.kr/Item?goodscode=123 5만원 3.2%" python add_deal.py
"""

import os
import re
import sys
import json
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from collect_deals import fetch_11st_live, parse_face_from_name  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = os.path.dirname(os.path.abspath(__file__))
MANUAL_PATH = os.path.join(ROOT, "manual_deals.json")

# 허용 도메인만 처리 (외부 임의 URL 차단)
# 쇼핑 앱에서 '링크 복사'로 나오는 단축링크(link.gmarket.co.kr 등)도 지원한다.
URL_RE = re.compile(
    r"https?://[^\s<>\"']*(?:"
    r"11st\.co\.kr/products/\d+"
    r"|item\.gmarket\.co\.kr/Item\?[^\s<>\"']*goodscode=\d+"
    r"|m\.gmarket\.co\.kr/(?:vi/product/\d+|n/item\?[^\s<>\"']*goodsCode=\d+)"
    r"|itempage3\.auction\.co\.kr/DetailView\.aspx\?[^\s<>\"']*itemno=[A-Za-z0-9]+"
    r"|m\.auction\.co\.kr/[^\s<>\"']*itemno=[A-Za-z0-9]+"
    r"|link\.(?:gmarket|auction)\.co\.kr/[A-Za-z0-9]+"
    r")[^\s<>\"']*",
    re.I,
)

MOBILE_HDRS = {
    "User-Agent": ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                   "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"),
    "Accept-Language": "ko-KR,ko;q=0.9",
}


def resolve_short(url):
    """앱 공유용 단축링크(link.gmarket.co.kr/XXXX)를 실제 상품 URL로 바꾼다.

    단축링크 페이지 본문에 최종 이동 주소가 담겨 있어 거기서 상품번호를 뽑는다.
    실패하면 원래 URL을 그대로 돌려준다.
    """
    if not re.search(r"link\.(gmarket|auction)\.co\.kr", url, re.I):
        return url
    try:
        req = urllib.request.Request(url, headers=MOBILE_HDRS)
        with urllib.request.urlopen(req, timeout=15) as r:
            body = r.read().decode("utf-8", errors="ignore")
            final = r.geturl()
    except Exception:
        return url
    # 단축링크 본문의 이동 주소는 여러 번 URL 인코딩되어 있어 반복 디코딩한다
    blob = final + " " + body
    for _ in range(3):
        decoded = urllib.parse.unquote(blob)
        if decoded == blob:
            break
        blob = decoded
    m = re.search(r"(?:vi/product/|goods[Cc]ode=|goodscode=)(\d{6,})", blob, re.I)
    if m:
        return f"https://item.gmarket.co.kr/Item?goodscode={m.group(1)}"
    m = re.search(r"itemno=([A-Za-z0-9]+)", blob)
    if m:
        return f"https://itempage3.auction.co.kr/DetailView.aspx?itemno={m.group(1).upper()}"
    return url

# 상품명·본문 키워드 → 카테고리 자동 판별
CATEGORY_RULES = [
    (["컬쳐랜드", "컬처랜드", "컬쳐캐시", "문화상품권"], "컬쳐랜드 문화상품권"),
    (["북앤라이프", "도서문화"], "도서문화상품권 (북앤라이프)"),
    (["신세계", "이마트", "ssg"], "신세계 상품권"),
    (["현대백화점", "현대"], "현대백화점 상품권"),
    (["롯데"], "롯데 상품권"),
]


def detect_category(*texts):
    """상품명/본문에서 카테고리 추정. 컬쳐랜드·도서문화를 먼저 검사한다."""
    blob = " ".join(t or "" for t in texts).lower()
    for keys, cat in CATEGORY_RULES:
        if any(k.lower() in blob for k in keys):
            return cat
    return None


def normalize(url):
    """중복 판정용 정규화 — 추적 파라미터 제거하고 상품 식별자만 남긴다."""
    low = url.lower()
    m = re.search(r"11st\.co\.kr/products/(\d+)", low)
    if m:
        return f"11st:{m.group(1)}"
    m = re.search(r"(?:goodscode=|vi/product/)(\d+)", low)
    if m:
        return f"gmarket:{m.group(1)}"
    m = re.search(r"itemno=([a-z0-9]+)", low)
    if m:
        return f"auction:{m.group(1)}"
    return low


def clean_url(url):
    """저장용 URL — 불필요한 추적 파라미터를 떼고 짧게 만든다."""
    m = re.search(r"11st\.co\.kr/products/(\d+)", url, re.I)
    if m:
        return f"https://www.11st.co.kr/products/{m.group(1)}"
    m = re.search(r"(?:goodscode=|vi/product/)(\d+)", url, re.I)
    if m:
        return f"https://item.gmarket.co.kr/Item?goodscode={m.group(1)}"
    m = re.search(r"itemno=([A-Za-z0-9]+)", url, re.I)
    if m:
        return f"https://itempage3.auction.co.kr/DetailView.aspx?itemno={m.group(1).upper()}"
    return url


def parse_hints(text):
    """본문에서 액면가·판매가·할인율 힌트를 뽑는다.

    허용 형태 예: '5만원 3.2%' / '5만원 48400' / '5만원권 48,400원'
    반환: (face, price, rate) — 알 수 없는 값은 None.
    """
    face = parse_face_from_name(text)
    rate = None
    m = re.search(r"(\d+(?:\.\d+)?)\s*%", text)
    if m:
        rate = float(m.group(1))

    # 판매가: 액면가로 인식된 숫자를 제외한 4자리 이상 금액 중 액면가보다 작은 값
    price = None
    if face:
        for cand in re.findall(r"([\d,]{4,9})", text):
            v = int(cand.replace(",", ""))
            if v != face and face * 0.5 <= v < face:
                price = v
                break

    # 둘 중 하나만 있으면 나머지를 계산
    if face and price and rate is None:
        rate = round((face - price) / face * 100, 1)
    elif face and rate and price is None:
        price = int(round(face * (1 - rate / 100)))
    return face, price, rate


def seller_of(url):
    low = url.lower()
    if "11st" in low:
        return "11번가"
    if "gmarket" in low:
        return "지마켓"
    if "auction" in low:
        return "옥션"
    return ""


def main():
    text = os.environ.get("ISSUE_BODY", "") + "\n" + os.environ.get("ISSUE_TITLE", "")
    if len(sys.argv) > 1:
        text += "\n" + "\n".join(sys.argv[1:])

    urls = list(dict.fromkeys(URL_RE.findall(text) or []))
    # findall 이 그룹 때문에 부분만 줄 수 있어 finditer 로 다시 확보
    urls = list(dict.fromkeys(m.group(0) for m in URL_RE.finditer(text)))

    if not urls:
        print("등록할 수 있는 상품 URL을 찾지 못했습니다.")
        print("지원: 11번가(11st.co.kr/products/...), 지마켓(goodscode=...), 옥션(itemno=...)")
        sys.exit(0)

    # 본문에서 공통 액면가·판매가·할인율 힌트 추출 (지마켓·옥션용)
    face_hint, price_hint, rate_hint = parse_hints(text)

    data = json.load(open(MANUAL_PATH, encoding="utf-8"))
    deals = data.setdefault("deals", [])
    existing = {normalize(d.get("url", "")) for d in deals}

    added, skipped, failed = [], [], []

    for raw in urls:
        url = clean_url(resolve_short(raw))
        key = normalize(url)
        if key in existing:
            skipped.append(f"이미 등록됨: {url}")
            continue

        seller = seller_of(url)

        if seller == "11번가":
            try:
                live = fetch_11st_live(url)
            except Exception as e:
                failed.append(f"{url} → 조회 오류({e})")
                continue
            if not live:
                failed.append(f"{url} → 품절이거나 가격을 읽을 수 없습니다")
                continue
            cat = detect_category(live["title"], text)
            if not cat:
                failed.append(f"{url} → 카테고리를 판별할 수 없습니다({live['title'][:30]})")
                continue
            deals.append({"category": cat, "url": url})
            existing.add(key)
            added.append(f"{cat} | 11번가 {live['rate']}% | {live['title'][:40]}")
            continue

        # 지마켓·옥션: 자동 조회가 차단되므로 할인율·액면가가 본문에 있어야 함
        cat = detect_category(text)
        if not cat:
            failed.append(f"{url} → 카테고리를 판별할 수 없습니다(본문에 '컬쳐랜드' 등 상품권 종류를 적어주세요)")
            continue
        if rate_hint is None or not face_hint:
            failed.append(
                f"{url} → {seller}는 가격을 자동으로 읽을 수 없습니다. "
                f"액면가와 할인율(또는 판매가)을 함께 적어주세요 (예: '5만원 3.2%' 또는 '5만원 48400')")
            continue
        price = price_hint or int(round(face_hint * (1 - rate_hint / 100)))
        deals.append({
            "category": cat, "seller": seller, "rate": rate_hint,
            "face": face_hint, "price": price,
            "title": f"{cat} {face_hint // 10000}만원권" if face_hint >= 10000 else cat,
            "url": url,
        })
        existing.add(key)
        added.append(f"{cat} | {seller} {rate_hint}% | 액면 {face_hint:,}원 → {price:,}원")

    if added:
        json.dump(data, open(MANUAL_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    # 결과 출력 (워크플로가 이 내용을 Issue 댓글로 남긴다)
    if added:
        print("### ✅ 등록 완료\n")
        for a in added:
            print(f"- {a}")
    if skipped:
        print("\n### ℹ️ 건너뜀\n")
        for s in skipped:
            print(f"- {s}")
    if failed:
        print("\n### ⚠️ 등록 실패\n")
        for f in failed:
            print(f"- {f}")
    if added:
        print("\n곧 사이트에 반영됩니다. (매시 정각 자동 갱신)")


if __name__ == "__main__":
    main()
