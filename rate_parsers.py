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
                  "이랜드", "홈플러스", "교육", "여행", "레저", "기프트카드"]


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


# 업체키 → 파서 함수
PARSERS = {}
