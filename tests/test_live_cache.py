"""11번가 직전 성공값 캐시 테스트.

11번가가 러너 IP에 502/503을 돌려주면 URL만 등록된 11번가 딜이 통째로 사라졌다
(2026-11-02~11-16). 조회 오류일 때만 48시간 이내 직전 성공값으로 대신 노출한다.
"""
import json
import os
import sys
import tempfile
import unittest
import urllib.error
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import collect_deals as cd  # noqa: E402

URL = "https://www.11st.co.kr/products/1234567890"
LIVE = {"title": "[5만원권] 테스트 문화상품권", "price": 47500, "face": 50000, "rate": 5.0}


def http_502(*_args, **_kwargs):
    raise urllib.error.HTTPError(URL, 502, "Bad Gateway", None, None)


class LiveCacheTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.manual = os.path.join(self.tmp.name, "manual_deals.json")
        with open(self.manual, "w", encoding="utf-8") as f:
            json.dump({"deals": [{"category": "문화상품권", "url": URL}]}, f)
        self.sleep = patch.object(cd.time, "sleep", lambda *_: None)
        self.sleep.start()

    def tearDown(self):
        self.sleep.stop()
        self.tmp.cleanup()

    def cached_entry(self, hours_ago):
        at = datetime.now(cd.KST) - timedelta(hours=hours_ago)
        return {**LIVE, "fetched_at": at.isoformat(timespec="minutes")}

    def load(self, cache, fetch):
        with patch.object(cd, "fetch_11st_live", fetch):
            # 4번째 값(수동딜 만료 현황)은 test_manual_expiry.py 에서 검증한다
            return cd.load_manual_deals(cache, path=self.manual)[:3]

    def test_success_records_cache(self):
        cache = {}
        by_cat, live_ok, live_cached = self.load(cache, lambda *_: dict(LIVE))
        self.assertEqual((live_ok, live_cached), (1, 0))
        self.assertEqual(by_cat["문화상품권"][0]["rate"], 5.0)
        self.assertEqual(cache[URL]["price"], 47500)
        self.assertIn("fetched_at", cache[URL])

    def test_fetch_error_uses_fresh_cache(self):
        cache = {URL: self.cached_entry(hours_ago=3)}
        by_cat, live_ok, live_cached = self.load(cache, http_502)
        # 캐시 딜은 실시간 검증이 아니므로 live_ok(→ live_zero_streak 감시)에 세지 않는다
        self.assertEqual((live_ok, live_cached), (0, 1))
        item = by_cat["문화상품권"][0]
        self.assertEqual((item["rate"], item["price"], item["seller"]), (5.0, 47500, "11번가"))

    def test_fetch_error_ignores_stale_cache(self):
        cache = {URL: self.cached_entry(hours_ago=cd.LIVE_CACHE_TTL_HOURS + 1)}
        by_cat, live_ok, live_cached = self.load(cache, http_502)
        self.assertEqual((by_cat, live_ok, live_cached), ({}, 0, 0))

    def test_sold_out_drops_cache(self):
        cache = {URL: self.cached_entry(hours_ago=1)}
        by_cat, _, live_cached = self.load(cache, lambda *_: None)
        self.assertEqual((by_cat, live_cached), ({}, 0))
        self.assertNotIn(URL, cache)

    def test_without_cache_keeps_old_behavior(self):
        by_cat, live_ok, live_cached = self.load(None, http_502)
        self.assertEqual((by_cat, live_ok, live_cached), ({}, 0, 0))

    def test_save_prunes_stale_and_load_roundtrip(self):
        path = os.path.join(self.tmp.name, "cache.json")
        self.assertEqual(cd.load_live_cache(path), {})  # 파일 없음
        cache = {URL: self.cached_entry(hours_ago=1),
                 URL + "9": self.cached_entry(hours_ago=cd.LIVE_CACHE_TTL_HOURS + 5)}
        cd.save_live_cache(cache, path)
        self.assertEqual(list(cd.load_live_cache(path)), [URL])


class WorkflowCommitsCacheTest(unittest.TestCase):
    def test_both_workflows_stage_cache_file(self):
        # 수집기가 갱신한 캐시를 커밋 대상에서 빠뜨리면 unstaged 로 남아
        # git pull --rebase 가 실패한다
        for name in ("collect-deals.yml", "add-deal.yml"):
            text = (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")
            self.assertIn("git add live_11st_cache.json || true", text, name)


if __name__ == "__main__":
    unittest.main()
