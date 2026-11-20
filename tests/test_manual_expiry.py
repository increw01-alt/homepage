"""수동딜 만료 예고 → GitHub 이슈 테스트.

2026-11-02 수동딜 17건이 동시에 만료됐지만 예고가 실행 로그 경고에만 있어
아무도 보지 못했다. 만료 현황을 deals.json 에 남기고 워크플로가 이슈로 알린다.
"""
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import collect_deals as cd  # noqa: E402

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None


def checked(days_ago):
    return (datetime.now(cd.KST).date() - timedelta(days=days_ago)).isoformat()


def manual(seller, days_ago):
    return {"category": "문화상품권", "seller": seller, "rate": 3.5,
            "title": f"{seller} 문화상품권 5만원권", "url": f"https://www.gmarket.co.kr/{seller}",
            "checked": checked(days_ago)}


class ManualExpiryTest(unittest.TestCase):
    def load(self, deals):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "manual_deals.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"deals": deals}, f, ensure_ascii=False)
            return cd.load_manual_deals(None, path=path)

    def test_reports_expiring_and_expired(self):
        stale = cd.MANUAL_STALE_DAYS
        by_cat, _, _, expiry = self.load([
            manual("지마켓", 1),            # 여유 있음
            manual("옥션", stale - 2),      # D-3
            manual("옥션B", stale),         # D-1 (오늘까지 노출)
            manual("지마켓B", stale + 1),   # 만료 → 노출 제외
        ])
        self.assertEqual(len(by_cat["문화상품권"]), 3)
        self.assertEqual(expiry["expired"], 1)
        self.assertEqual(len(expiry["expiring"]), 2)
        self.assertTrue(expiry["expiring"][0].startswith("D-3 옥션"))
        self.assertTrue(expiry["expiring"][1].startswith("D-1 옥션B"))

    def test_nothing_expiring(self):
        _, _, _, expiry = self.load([manual("지마켓", 0)])
        self.assertEqual(expiry, {"expiring": [], "expired": 0})

    def test_missing_file_returns_empty_expiry(self):
        result = cd.load_manual_deals(None, path=os.path.join(tempfile.gettempdir(), "없는파일.json"))
        self.assertEqual(result, ({}, 0, 0, {"expiring": [], "expired": 0}))


@unittest.skipIf(yaml is None, "PyYAML 미설치")
class ManualExpiryWorkflowTest(unittest.TestCase):
    def test_issue_step(self):
        with open(ROOT / ".github" / "workflows" / "collect-deals.yml", encoding="utf-8") as f:
            steps = yaml.safe_load(f)["jobs"]["collect"]["steps"]
        step = next(s for s in steps if s.get("name", "").startswith("수동딜 만료 예고"))
        self.assertEqual(step.get("if"), "steps.deals.outcome == 'success'")
        run = step["run"]
        for needle in ("collect_health.manual_expiring", "collect_health.manual_expired",
                       "[수동딜만료]", "gh issue list", "gh issue create", "gh issue close"):
            self.assertIn(needle, run)
        # 실패 처리·건강 점검보다 앞에 있어야 그 스텝들이 실패해도 예고가 나간다
        names = [s.get("name", "") for s in steps]
        self.assertLess(names.index(step["name"]),
                        names.index("자동 갱신 건강 점검 (0건 지속 시 실행 실패로 알림)"))


if __name__ == "__main__":
    unittest.main()
