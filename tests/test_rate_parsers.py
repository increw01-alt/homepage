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


if __name__ == "__main__":
    unittest.main()
