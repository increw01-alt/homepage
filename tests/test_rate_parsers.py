# -*- coding: utf-8 -*-
"""상품권 거래소 파서 회귀 테스트.

파서는 남의 사이트 구조에 종속돼 가장 자주 깨지는 코드다.
픽스처(tests/fixtures/*.html)는 각 업체 시세표 구간만 잘라 저장한 것으로,
사이트가 개편돼 파서가 깨졌을 때 여기서 먼저 잡힌다.

실행: python -m unittest discover -s tests -v
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import rate_parsers as rp


class TestHelpers(unittest.TestCase):
    def test_normalize_brand_maps_known_names(self):
        self.assertEqual(rp.normalize_brand("신세계상품권"), "신세계")
        self.assertEqual(rp.normalize_brand("신세계백화점 10만원권"), "신세계")
        self.assertEqual(rp.normalize_brand("롯데 백화점(10만원권)"), "롯데")
        self.assertEqual(rp.normalize_brand("현대백화점"), "현대")
        self.assertEqual(rp.normalize_brand("갤러리아백화점"), "갤러리아")
        self.assertEqual(rp.normalize_brand("AK플라자"), "AK")

    def test_normalize_brand_rejects_other_categories(self):
        self.assertIsNone(rp.normalize_brand("국민관광상품권"))
        self.assertIsNone(rp.normalize_brand("이랜드 상품권"))
        self.assertIsNone(rp.normalize_brand("주유상품권"))
        self.assertIsNone(rp.normalize_brand("홈플러스"))

    def test_normalize_brand_rejects_gift_variants(self):
        # "증정용"은 일반 시세와 조건이 달라 섞으면 안 된다
        self.assertIsNone(rp.normalize_brand("롯데 상품권★증정용"))
        self.assertIsNone(rp.normalize_brand("[사은증정]신세계"))

    def test_parse_money(self):
        self.assertEqual(rp.parse_money("96,700원"), 96700)
        self.assertEqual(rp.parse_money(" 96700 "), 96700)
        self.assertIsNone(rp.parse_money("—"))
        self.assertIsNone(rp.parse_money(""))

    def test_parse_rate(self):
        self.assertEqual(rp.parse_rate("(3.30%)"), 3.3)
        self.assertEqual(rp.parse_rate("3.8%"), 3.8)
        self.assertIsNone(rp.parse_rate("없음"))


class TestValidateRow(unittest.TestCase):
    FACE = 100000

    def test_accepts_consistent_row(self):
        row = {"brand": "신세계", "buy": 96700, "buyRate": 3.3,
               "sell": 96600, "sellRate": 3.4}
        self.assertTrue(rp.validate_row(row, self.FACE))

    def test_rejects_identity_mismatch(self):
        # 96,700원인데 할인율이 10%로 적혀 있으면 컬럼 정렬이 어긋난 것
        row = {"brand": "신세계", "buy": 96700, "buyRate": 10.0,
               "sell": 96600, "sellRate": 3.4}
        self.assertFalse(rp.validate_row(row, self.FACE))

    def test_rejects_out_of_range(self):
        row = {"brand": "신세계", "buy": 50000, "buyRate": 50.0,
               "sell": 49000, "sellRate": 51.0}
        self.assertFalse(rp.validate_row(row, self.FACE))

    def test_rejects_buy_not_greater_than_sell(self):
        # 매입/판매 컬럼을 반대로 읽은 경우
        row = {"brand": "신세계", "buy": 96600, "buyRate": 3.4,
               "sell": 96700, "sellRate": 3.3}
        self.assertFalse(rp.validate_row(row, self.FACE))

    def test_accepts_row_with_only_one_side(self):
        # 업체가 살때만 공시하는 경우도 있다
        row = {"brand": "롯데", "buy": 95700, "buyRate": 4.3,
               "sell": None, "sellRate": None}
        self.assertTrue(rp.validate_row(row, self.FACE))

    def test_rejects_row_with_no_price(self):
        row = {"brand": "롯데", "buy": None, "buyRate": None,
               "sell": None, "sellRate": None}
        self.assertFalse(rp.validate_row(row, self.FACE))

    def test_rejects_unknown_brand(self):
        row = {"brand": None, "buy": 96700, "buyRate": 3.3,
               "sell": 96600, "sellRate": 3.4}
        self.assertFalse(rp.validate_row(row, self.FACE))

    def test_accepts_row_without_rate(self):
        # 할인율 표기가 없는 업체는 금액만으로 범위 검사한다
        row = {"brand": "현대", "buy": 96800, "buyRate": None,
               "sell": 96600, "sellRate": None}
        self.assertTrue(rp.validate_row(row, self.FACE))


FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")

# 픽스처는 각 업체 시세표 구간만 잘라 저장한 것이다(페이지 전체가 아니다).
# 갱신하려면 실제 페이지를 받아 같은 방식으로 잘라 넣고 이 테스트를 돌린다.
SHOP_KEYS = ["worldticket", "xegift", "choigo", "mingren", "centralgift",
             "citypay", "wooticket", "woorist", "sgbaekhwajeom", "gogo"]

BRANDS = ["신세계", "롯데", "현대", "갤러리아", "AK"]


def load_fixture(key):
    with open(os.path.join(FIXTURES, key + ".html"), encoding="utf-8") as f:
        return f.read()


class TestParserContract(unittest.TestCase):
    """모든 파서가 공통으로 지켜야 할 계약."""

    def test_every_parser_has_a_fixture(self):
        for key in rp.PARSERS:
            self.assertIn(key, SHOP_KEYS, f"{key}: 픽스처·테스트 없이 추가됨")

    def test_parsers_return_valid_rows(self):
        for key in SHOP_KEYS:
            with self.subTest(shop=key):
                rows = rp.PARSERS[key](load_fixture(key))
                self.assertGreater(len(rows), 0, f"{key}: 행이 0개")
                for r in rows:
                    self.assertIn(r["brand"], BRANDS)
                    self.assertTrue(rp.validate_row(r), f"{key}: 검증 실패 {r}")

    def test_parsers_cover_major_brands(self):
        # 백화점 3사는 어느 업체나 취급한다
        for key in SHOP_KEYS:
            with self.subTest(shop=key):
                brands = {r["brand"] for r in rp.PARSERS[key](load_fixture(key))}
                self.assertTrue({"신세계", "롯데", "현대"} <= brands,
                                f"{key}: 3사 누락 {brands}")

    def test_no_duplicate_brands(self):
        # 액면가별 행이 중복 노출되면 안 된다(10만원권 하나만)
        for key in SHOP_KEYS:
            with self.subTest(shop=key):
                brands = [r["brand"] for r in rp.PARSERS[key](load_fixture(key))]
                self.assertEqual(len(brands), len(set(brands)), f"{key}: 중복 {brands}")

    def test_parsers_return_empty_on_garbage(self):
        # 사이트가 개편돼 구조가 사라지면 예외 대신 빈 리스트여야 한다
        for key in SHOP_KEYS:
            with self.subTest(shop=key):
                self.assertEqual(rp.PARSERS[key]("<html><body>없음</body></html>"), [])

    def test_buy_greater_than_sell(self):
        for key in SHOP_KEYS:
            with self.subTest(shop=key):
                for r in rp.PARSERS[key](load_fixture(key)):
                    if r["buy"] is not None and r["sell"] is not None:
                        self.assertGreater(r["buy"], r["sell"], f"{key}: {r}")

    def test_prices_are_near_face_value(self):
        # 10만원권 시세이므로 9만원대여야 한다. 5만·50만원권이 섞이면 실패한다.
        for key in SHOP_KEYS:
            with self.subTest(shop=key):
                for r in rp.PARSERS[key](load_fixture(key)):
                    for p in (r["buy"], r["sell"]):
                        if p is not None:
                            self.assertTrue(90000 <= p <= 102000, f"{key}: {p} {r}")


class TestMingrenScope(unittest.TestCase):
    def test_ignores_inactive_boxes(self):
        """box0 이외의 박스 값을 주워오면 안 된다.

        명인상품권 페이지에는 같은 상품명이 box0~box6 에 중복 등장한다.
        스코프를 좁히지 않으면 조용히 틀린 값이 들어간다.
        """
        html = (
            '<div class="sise_box box0 active">'
            '<table><tr><td>신세계상품권(10만원)</td><td>96,600원(3.40%)</td>'
            '<td>96,700원(3.30%)</td></tr></table></div>'
            '<div class="sise_box box2">'
            '<table><tr><td>신세계상품권(10만원)</td><td>95,000원(5.00%)</td>'
            '<td>95,500원(4.50%)</td></tr></table></div>'
        )
        rows = rp.parse_mingren(html)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["sell"], 96600)
        self.assertEqual(rows[0]["buy"], 96700)

    def test_returns_empty_when_active_box_missing(self):
        # active 박스를 못 찾으면 전체 검색으로 넘어가지 않고 포기한다
        html = ('<div class="sise_box box2"><table><tr><td>신세계상품권</td>'
                '<td>95,000원(5.00%)</td><td>95,500원(4.50%)</td></tr></table></div>')
        self.assertEqual(rp.parse_mingren(html), [])


class TestEncodingSensitiveShops(unittest.TestCase):
    """EUC-KR 사이트를 UTF-8 로 잘못 읽으면 종류명이 깨져 행이 0개가 된다.

    픽스처는 이미 UTF-8 로 변환해 저장했으므로, 여기서 행이 나오면
    수집기(collect_rates.py)의 디코딩만 맞추면 된다.
    """

    def test_euckr_shops_parse_korean_brands(self):
        for key in ["wooticket", "woorist"]:
            with self.subTest(shop=key):
                rows = rp.PARSERS[key](load_fixture(key))
                self.assertGreater(len(rows), 0, f"{key}: 한글 종류명 매칭 실패")


class TestFaceValueTrap(unittest.TestCase):
    def test_sgbaekhwajeom_ignores_face_value_number(self):
        """상품권백화점은 상품명 뒤에 액면가(100000)가 그대로 찍혀 있다.

        이걸 가격으로 오인하면 sell 자리에 액면가가 들어가 전량 탈락한다.
        """
        html = ('<li class="sct_li">롯데 백화점(10만원권) 100000 '
                '95,500원 95,700원</li>')
        rows = rp.parse_sgbaekhwajeom(html)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["sell"], 95500)
        self.assertEqual(rows[0]["buy"], 95700)


if __name__ == "__main__":
    unittest.main()
