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


class TestTrendChart(unittest.TestCase):
    """히어로 미니 차트 — 이력 파일을 임시로 바꿔치기해 검증한다."""

    def setUp(self):
        self._orig = cr.HISTORY_PATH
        self._tmp = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                 "_tmp_history.json")

    def tearDown(self):
        cr.HISTORY_PATH = self._orig
        if os.path.exists(self._tmp):
            os.remove(self._tmp)

    def _write(self, points):
        import json
        with open(self._tmp, "w", encoding="utf-8") as f:
            json.dump({"points": points}, f, ensure_ascii=False)
        cr.HISTORY_PATH = self._tmp

    def test_returns_none_when_too_few_points(self):
        """점 2개로는 '동향'이 되지 않으므로 차트를 그리지 않는다."""
        self._write([{"t": "2026-08-12 10:00", "신세계": 96800},
                     {"t": "2026-08-12 11:00", "신세계": 96700}])
        self.assertIsNone(cr.build_trend())

    def test_returns_none_when_history_missing(self):
        cr.HISTORY_PATH = os.path.join(os.path.dirname(self._tmp), "_no_such_file.json")
        self.assertIsNone(cr.build_trend())

    def test_builds_coords_from_min_buy(self):
        self._write([
            {"t": "2026-08-12 10:00", "신세계": 96800, "롯데": 95700},
            {"t": "2026-08-12 11:00", "신세계": 96700, "롯데": 95500},
            {"t": "2026-08-12 12:00", "신세계": 96600, "롯데": 95900},
        ])
        t = cr.build_trend()
        self.assertIsNotNone(t)
        self.assertEqual(len(t["coords"]), 3)
        # 각 시점의 '전체 최저 살때'가 계열이 된다
        self.assertEqual([s["v"] for s in t["series"]], [95700, 95500, 95900])
        self.assertEqual(t["lo"], 95500)
        self.assertEqual(t["hi"], 95900)
        # 값이 낮을수록 y 가 커진다(SVG 좌표계는 위가 0)
        ys = [y for _, y in t["coords"]]
        self.assertGreater(ys[1], ys[2], "최저값 지점이 가장 아래여야 한다")
        # x 는 왼쪽에서 오른쪽으로 증가
        xs = [x for x, _ in t["coords"]]
        self.assertEqual(xs, sorted(xs))

    def test_chart_html_empty_without_history(self):
        cr.HISTORY_PATH = os.path.join(os.path.dirname(self._tmp), "_no_such_file.json")
        self.assertEqual(cr.build_hero_chart(), "")

    def test_chart_html_has_polyline(self):
        self._write([
            {"t": "2026-08-12 10:00", "신세계": 96800},
            {"t": "2026-08-12 11:00", "신세계": 96700},
            {"t": "2026-08-12 12:00", "신세계": 96600},
        ])
        html = cr.build_hero_chart()
        self.assertIn("<polyline", html)
        self.assertIn("hero_chart", html)


class TestHeroBoard(unittest.TestCase):
    def test_arrow_reflects_dir_field(self):
        """화살표는 summary[].dir 로만 결정된다(프리렌더·JS 가 같은 값을 쓰도록)."""
        data = {"summary": [
            {"brand": "신세계", "bestBuy": {"price": 96680, "shop": "A"},
             "bestSell": {"price": 96650, "shop": "B"}, "dir": "down"},
            {"brand": "롯데", "bestBuy": {"price": 95700, "shop": "A"},
             "bestSell": None, "dir": "up"},
            {"brand": "현대", "bestBuy": {"price": 96700, "shop": "A"},
             "bestSell": None},
        ]}
        html = cr.build_hero_table(data)
        self.assertIn("hb_arw down", html)
        self.assertIn("hb_arw up", html)
        self.assertEqual(html.count("hb_arw"), 2, "dir 없는 행엔 화살표를 넣지 않는다")

    def test_skips_brand_without_data(self):
        data = {"summary": [{"brand": "AK", "bestBuy": None, "bestSell": None}]}
        self.assertNotIn("AK", cr.build_hero_table(data))


class TestPrerenderHelpers(unittest.TestCase):
    def test_won_formats_and_handles_none(self):
        self.assertEqual(cr.won(96700), "96,700원")
        self.assertEqual(cr.won(None), "—")

    def test_esc_escapes_html(self):
        self.assertEqual(cr.esc('<a href="x">&'), "&lt;a href=&quot;x&quot;&gt;&amp;")


if __name__ == "__main__":
    unittest.main()
