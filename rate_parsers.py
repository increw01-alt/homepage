# -*- coding: utf-8 -*-
"""상품권 거래소별 시세 파서.

각 업체 파서는 HTML 문자열을 받아 Row 리스트를 돌려준다.

    Row = {"brand", "buy", "buyRate", "sell", "sellRate"}
      buy  = 고객이 사는 값 (업체 표기 "판매가")
      sell = 고객이 파는 값 (업체 표기 "매입가")
    항상 buy > sell 이다(업체 마진). 이 부등식이 컬럼 뒤바뀜 검사에 쓰인다.

파서는 남의 사이트 구조에 종속돼 가장 자주 깨지는 코드다.
새 파서를 추가하면 반드시 tests/fixtures 에 축약 픽스처와 테스트를 함께 넣을 것.

설계·운영 원칙은 상품권시세-설계.md 참조.
"""

import re

FACE = 100000  # 시세표 기준 액면가(10만원권)

# 표기 흔들림을 흡수해 5종으로 정규화한다.
_BRAND_PATTERNS = [
    ("신세계", ["신세계", "SSG"]),
    ("롯데", ["롯데"]),
    ("현대", ["현대"]),
    ("갤러리아", ["갤러리아"]),
    ("AK", ["AK플라자", "AK백화점", "AK상품권", "애경", "AK"]),
]

# 일반 백화점 상품권 시세와 조건이 다른 항목은 제외한다.
# (증정용은 할인율 체계가 다르고, 나머지는 백화점 상품권이 아니다)
_BRAND_EXCLUDE = ["증정", "사은", "구두", "주유", "문화", "국민", "관광",
                  "이랜드", "홈플러스", "교육", "여행", "레저", "기프트카드",
                  # 일반 상품권과 시세 체계가 다른 변형 상품
                  "스페셜", "카드형", "모바일", "e카드", "선불"]


def normalize_brand(name):
    """원문 종류명을 5종 중 하나로. 해당 없으면 None."""
    if not name:
        return None
    s = re.sub(r"\s+", "", str(name))
    if any(x in s for x in _BRAND_EXCLUDE):
        return None
    for canon, keys in _BRAND_PATTERNS:
        if any(k in s for k in keys):
            return canon
    return None


def parse_money(s):
    """'96,700원' → 96700. 숫자가 없으면 None."""
    if s is None:
        return None
    m = re.search(r"(\d[\d,]{2,})", str(s))
    if not m:
        return None
    return int(m.group(1).replace(",", ""))


def parse_rate(s):
    """'(3.30%)' → 3.3. 없으면 None."""
    if s is None:
        return None
    m = re.search(r"(\d+(?:\.\d+)?)\s*%", str(s))
    if not m:
        return None
    return float(m.group(1))


def validate_row(row, face=FACE):
    """4중 검증. 하나라도 실패하면 이 행을 버린다.

    틀린 시세를 협회 이름으로 내보내는 것보다 빈 칸이 낫다는 원칙에 따라,
    조금이라도 의심스러우면 채택하지 않는다.
    """
    if not row.get("brand"):
        return False

    buy, sell = row.get("buy"), row.get("sell")
    if buy is None and sell is None:
        return False

    for price, rate in ((buy, row.get("buyRate")), (sell, row.get("sellRate"))):
        if price is None:
            continue
        # 범위: 액면가의 90~102%. 5만·50만원권 행도 여기서 함께 걸러진다.
        if not (face * 0.90 <= price <= face * 1.02):
            return False
        # 항등식: 금액 ≈ 액면가 × (1 − 할인율/100)
        # 업체가 금액과 할인율을 함께 표기하므로 서로를 교차검증할 수 있다.
        # 컬럼 정렬이 어긋나면 여기서 잡힌다.
        if rate is not None:
            expected = face * (1 - rate / 100.0)
            if abs(price - expected) > face * 0.01:
                return False

    # 부등식: 둘 다 있으면 살때 > 팔때
    if buy is not None and sell is not None and buy <= sell:
        return False

    return True


# ─────────────────────────────────────────────────────────────
# 공통 헬퍼
# ─────────────────────────────────────────────────────────────

_TAG = re.compile(r"<[^>]+>")
# ​ = 제로폭 공백. 일부 페이지 빌더가 텍스트에 섞어 넣어 매칭을 방해한다.
_WS = re.compile(r"[\s​\xa0]+")


def _text(fragment):
    """태그 제거 후 공백 정규화."""
    s = _TAG.sub(" ", fragment or "")
    s = s.replace("&nbsp;", " ").replace("&amp;", "&")
    return _WS.sub(" ", s).strip()


def _cells(tr_html):
    """<tr> 안의 td/th 텍스트 리스트."""
    return [_text(td) for td in
            re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr_html, re.S | re.I)]


def _rows_from_table(html, cols, face=FACE):
    """<tr> 를 순회하며 지정한 컬럼 인덱스에서 값을 뽑는 공통 헬퍼.

    cols = {"name": 0, "sell": 1, "buy": 2}  ← td 인덱스
      업체 표기 "매입가"가 sell(고객이 파는 값), "판매가"가 buy(고객이 사는 값)다.
      호출부에서 이 대응을 맞춰 넘길 것.

    액면가 필터는 따로 두지 않는다 — validate_row 의 범위 검사(90~102%)가
    5만·50만원권 행을 자동으로 걸러낸다.
    """
    out = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S | re.I):
        tds = _cells(tr)
        if len(tds) <= max(cols.values()):
            continue
        brand = normalize_brand(tds[cols["name"]])
        if not brand:
            continue
        sell_cell = tds[cols["sell"]] if "sell" in cols else ""
        buy_cell = tds[cols["buy"]] if "buy" in cols else ""
        row = {
            "brand": brand,
            "buy": parse_money(buy_cell), "buyRate": parse_rate(buy_cell),
            "sell": parse_money(sell_cell), "sellRate": parse_rate(sell_cell),
        }
        if validate_row(row, face):
            out.append(row)
    return out


def _dedupe(rows):
    """같은 브랜드가 여러 번 나오면 첫 행만 남긴다(액면가별 중복 방지)."""
    seen, out = set(), []
    for r in rows:
        if r["brand"] in seen:
            continue
        seen.add(r["brand"])
        out.append(r)
    return out


# ─────────────────────────────────────────────────────────────
# 업체별 파서
#   구조는 tests/fixtures/*.html 픽스처를 기준으로 한다.
#   사이트가 개편되면 픽스처를 갱신하고 테스트로 먼저 확인할 것.
# ─────────────────────────────────────────────────────────────

def parse_worldticket(html):
    """월드티켓상품권 — td[0]=명 td[1]=매입 td[2]=판매."""
    m = re.search(r'<div[^>]*class="[^"]*guide-table[^"]*"[^>]*>(.*)', html, re.S | re.I)
    scope = m.group(1) if m else html
    return _dedupe(_rows_from_table(scope, {"name": 0, "sell": 1, "buy": 2}))


def parse_xegift(html):
    """엑스이상품권 — td[0]=명 td[1]=매입(.blue) td[2]=판매(.red)."""
    return _dedupe(_rows_from_table(html, {"name": 0, "sell": 1, "buy": 2}))


def parse_choigo(html):
    """최고상품권 — 수량 input 의 커스텀 속성에서 직접 추출.

    <input _amt1="96600" _amt2="96800" _item="현대 상품권 (10만원)">
      _amt1 = 매입가(sell), _amt2 = 판매가(buy)
    콤마 없는 정수라 후처리가 필요 없다.
    """
    out = []
    for m in re.finditer(
            r'<input[^>]*_amt1="(\d+)"[^>]*_amt2="(\d+)"[^>]*_item="([^"]+)"', html, re.I):
        sell, buy, item = int(m.group(1)), int(m.group(2)), m.group(3)
        brand = normalize_brand(item)
        if not brand:
            continue
        row = {"brand": brand, "buy": buy, "buyRate": None,
               "sell": sell, "sellRate": None}
        if validate_row(row):
            out.append(row)
    return _dedupe(out)


def parse_meee(html):
    """미래상품권 — tbody.giftcard_list 안 표.

    thead 가 '상품권명 / 매입가(손님 파실때) / 판매가(손님 구매시) / 수량' 이라
    컬럼 의미가 명확하다. '[사은증정]' 항목은 시세 체계가 다른데,
    normalize_brand 의 제외 목록('사은', '증정')이 걸러 준다.
    """
    m = re.search(r'<tbody[^>]*class="[^"]*giftcard_list[^"]*"[^>]*>(.*?)</tbody>',
                  html, re.S | re.I)
    scope = m.group(1) if m else html
    return _dedupe(_rows_from_table(scope, {"name": 0, "sell": 1, "buy": 2}))


def parse_mingren(html):
    """명인상품권 — div.sise_box.box0.active 로 스코프를 좁힌 뒤 표를 읽는다.

    box0~box6 에 같은 상품명이 중복 등장하므로 스코프 한정이 필수다.
    active 박스를 못 찾으면 빈 리스트를 돌려준다(전체 검색 금지 — 조용히
    틀린 값을 채택하는 것보다 빈 값이 낫다).
    """
    m = re.search(
        r'<div[^>]*class="[^"]*sise_box[^"]*box0[^"]*active[^"]*"[^>]*>(.*?)'
        r'(?=<div[^>]*class="[^"]*sise_box|\Z)', html, re.S | re.I)
    if not m:
        return []
    return _dedupe(_rows_from_table(m.group(1), {"name": 0, "sell": 1, "buy": 2}))


def parse_centralgift(html):
    """중앙상품권 — td[0]=명 td[1]=액면 td[2]=매입 td[3]=판매."""
    return _dedupe(_rows_from_table(html, {"name": 0, "sell": 2, "buy": 3}))


def parse_citypay(html):
    """시티페이 — wpDataTables. td[0]=명 td[1]=매입 td[2]=판매.

    매입 칸에 '이체 95,500 / 현금 95,400' 두 값이 들어 있는데,
    parse_money 가 첫 숫자(이체가)를 잡는다.
    """
    m = re.search(r'<table[^>]*id="table_\d+"[^>]*>(.*?)</table>', html, re.S | re.I)
    scope = m.group(1) if m else html
    return _dedupe(_rows_from_table(scope, {"name": 0, "sell": 1, "buy": 2}))


def parse_wooticket(html):
    """우천상품권 — 레거시 테이블. td[0]=명 td[1]=매입 td[2]=판매.

    페이지 인코딩이 EUC-KR 이므로 수집기에서 디코딩해 넘길 것.
    """
    return _dedupe(_rows_from_table(html, {"name": 0, "sell": 1, "buy": 2}))


def parse_woorist(html):
    """우리에스티 — 매입시세표 전용 페이지. EUC-KR.

    컬럼이 넓다: td[0]=명 td[2]=액면 td[3]=매입 td[4]=판매.
    할인율은 '[4.50 %]' 형태.
    """
    return _dedupe(_rows_from_table(html, {"name": 0, "sell": 3, "buy": 4}))


def parse_sgbaekhwajeom(html):
    """상품권백화점 — 영카트 상품 목록이 곧 시세표.

    li.sct_li 안에 '롯데 백화점(10만원권) 100000 95,500원 95,700원' 순으로
    액면가·매입가·판매가가 차례로 온다. 표가 아니라 블록 단위로 훑는다.
    """
    out = []
    for block in re.findall(r'<li[^>]*class="[^"]*sct_li[^"]*"[^>]*>(.*?)</li>',
                            html, re.S | re.I):
        txt = _text(block)
        brand = normalize_brand(txt)
        if not brand:
            continue
        nums = [int(n.replace(",", "")) for n in re.findall(r"(\d[\d,]{4,})", txt)]
        # 액면가(100000)가 상품명 뒤에 그대로 찍혀 있어 범위 필터를 통과한다.
        # 이걸 가격으로 오인하면 sell 자리에 액면가가 들어가 검증에서 전량 탈락한다.
        prices = [n for n in nums if FACE * 0.90 <= n <= FACE * 1.02 and n != FACE]
        if len(prices) < 2:
            continue
        # 등장 순서가 매입(sell) → 판매(buy)
        row = {"brand": brand, "buy": prices[1], "buyRate": None,
               "sell": prices[0], "sellRate": None}
        if validate_row(row):
            out.append(row)
    return _dedupe(out)


def parse_gogo(html):
    """고고상품권 — div.tab-editor[editor-name] 블록. 블록명이 곧 종류명이다.

    탭은 CSS 로 숨겨질 뿐 전 블록이 서버 HTML 에 있다.
    블록 안에 '스페셜 카드' 등 시세 체계가 다른 변형이 섞여 있으므로
    normalize_brand 의 제외 목록으로 걸러내고 블록당 첫 행만 취한다.
    """
    out = []
    blocks = re.split(r'(?=<div[^>]*class="[^"]*tab-editor[^"]*"[^>]*editor-name=")', html)
    for b in blocks:
        m = re.search(r'editor-name="([^"]*)"', b)
        if not m:
            continue
        brand = normalize_brand(m.group(1))
        if not brand:
            continue
        for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", b, re.S | re.I):
            tds = _cells(tr)
            if len(tds) < 3:
                continue
            # 행 이름에 변형 상품(스페셜 카드 등)이 있으면 건너뛴다
            if normalize_brand(tds[0]) != brand:
                continue
            row = {
                "brand": brand,
                "buy": parse_money(tds[2]), "buyRate": parse_rate(tds[2]),
                "sell": parse_money(tds[1]), "sellRate": parse_rate(tds[1]),
            }
            if validate_row(row):
                out.append(row)
                break  # 블록당 첫 유효 행만
    return _dedupe(out)


# 업체키 → 파서 함수
PARSERS = {
    "worldticket": parse_worldticket,
    "xegift": parse_xegift,
    "choigo": parse_choigo,
    "meee": parse_meee,
    "mingren": parse_mingren,
    "centralgift": parse_centralgift,
    "citypay": parse_citypay,
    "wooticket": parse_wooticket,
    "woorist": parse_woorist,
    "sgbaekhwajeom": parse_sgbaekhwajeom,
    "gogo": parse_gogo,
}
