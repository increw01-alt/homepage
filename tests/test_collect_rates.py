# -*- coding: utf-8 -*-
"""시세 수집기 테스트 (네트워크 없이 도는 부분만)."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import collect_rates as cr
import rate_parsers as rp


class TestShopRegistry(unittest.TestCase):
    def test_every_shop_has_a_parser(self):
        for s in cr.SHOPS:
            self.assertIn(s["key"], rp.PARSERS, f"{s['name']}: 파서 없음")

    def test_parsers_may_outlive_shops(self):
        """수집 대상에서 빠진 업체의 파서는 남겨 둔다.

        차단·인증서 만료 등으로 잠시 제외된 업체가 대부분이라,
        파서를 지우면 복구할 때 처음부터 다시 만들어야 한다.
        (파서는 픽스처 테스트로 계속 검증된다)
        """
        keys = {s["key"] for s in cr.SHOPS}
        self.assertTrue(keys <= set(rp.PARSERS), "SHOPS 에 파서 없는 업체가 있다")

    def test_shop_fields(self):
        for s in cr.SHOPS:
            for f in ("key", "name", "url", "area", "encoding"):
                self.assertIn(f, s, f"{s.get('name')}: {f} 누락")
            self.assertTrue(s["url"].startswith("http"))

    def test_no_aggregator_sources(self):
        """비교 사이트를 수집원으로 넣으면 안 된다(남의 DB 복제)."""
        for s in cr.SHOPS:
            self.assertNotIn("sisego", s["url"])

    def test_shop_names_unique(self):
        names = [s["name"] for s in cr.SHOPS]
        self.assertEqual(len(names), len(set(names)))


class TestRequestHeaders(unittest.TestCase):
    def test_user_agent_is_latin1_encodable(self):
        """HTTP 헤더는 latin-1 로만 인코딩된다.

        UA 에 한글을 넣으면 요청 단계에서 UnicodeEncodeError 가 나
        전 업체 수집이 통째로 실패한다(실제로 겪은 버그).
        """
        cr.UA.encode("latin-1")

    def test_user_agent_identifies_us(self):
        self.assertIn("koreagiftcard.co.kr", cr.UA)


class TestSummary(unittest.TestCase):
    def test_picks_cheapest_buy_and_highest_sell(self):
        shops = [
            {"name": "A", "rows": [{"brand": "신세계", "buy": 96800, "buyRate": 3.2,
                                    "sell": 96000, "sellRate": 4.0}]},
            {"name": "B", "rows": [{"brand": "신세계", "buy": 96200, "buyRate": 3.8,
                                    "sell": 96700, "sellRate": 3.3}]},
        ]
        s = {x["brand"]: x for x in cr.build_summary(shops)}["신세계"]
        self.assertEqual(s["bestBuy"]["price"], 96200)   # 살 때는 싼 쪽
        self.assertEqual(s["bestBuy"]["shop"], "B")
        self.assertEqual(s["bestSell"]["price"], 96700)  # 팔 때는 비싼 쪽
        self.assertEqual(s["bestSell"]["shop"], "B")

    def test_handles_missing_side(self):
        shops = [{"name": "A", "rows": [{"brand": "롯데", "buy": 95700, "buyRate": 4.3,
                                         "sell": None, "sellRate": None}]}]
        s = {x["brand"]: x for x in cr.build_summary(shops)}["롯데"]
        self.assertIsNotNone(s["bestBuy"])
        self.assertIsNone(s["bestSell"])

    def test_brand_with_no_data_is_none(self):
        s = {x["brand"]: x for x in cr.build_summary([])}["AK"]
        self.assertIsNone(s["bestBuy"])
        self.assertIsNone(s["bestSell"])

    def test_summary_covers_all_brands(self):
        summary = cr.build_summary([])
        self.assertEqual([x["brand"] for x in summary], cr.BRANDS)


class TestPrerenderHelpers(unittest.TestCase):
    def test_won_formats_and_handles_none(self):
        self.assertEqual(cr.won(96700), "96,700원")
        self.assertEqual(cr.won(None), "—")

    def test_esc_escapes_html(self):
        self.assertEqual(cr.esc('<a href="x">&'), "&lt;a href=&quot;x&quot;&gt;&amp;")


if __name__ == "__main__":
    unittest.main()
