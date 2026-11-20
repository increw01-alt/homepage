"""collect-deals.yml 실패 처리 구조 테스트.

2026-11-02~11-16: 딜이 0건이 되자 딜 수집 스텝의 exit 1 이 job 을 멈춰
시세 수집·커밋까지 12일간 막혔다. 같은 구조로 되돌아가지 않도록 고정한다.
"""
import os
import unittest

try:
    import yaml
except ImportError:  # pragma: no cover - PyYAML 이 없으면 건너뛴다
    yaml = None

WORKFLOW = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        ".github", "workflows", "collect-deals.yml")


@unittest.skipIf(yaml is None, "PyYAML 미설치")
class CollectWorkflowFailureHandlingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(WORKFLOW, encoding="utf-8") as f:
            cls.steps = yaml.safe_load(f)["jobs"]["collect"]["steps"]
        cls.names = [s.get("name", "") for s in cls.steps]

    def step(self, step_id=None, name=None):
        for s in self.steps:
            if (step_id and s.get("id") == step_id) or (name and s.get("name") == name):
                return s
        self.fail(f"스텝 없음: {step_id or name}")

    def index(self, step):
        return self.steps.index(step)

    def test_deal_failure_does_not_stop_rates_and_commit(self):
        deals = self.step("deals")
        self.assertTrue(deals.get("continue-on-error"))
        self.assertIn("collect_deals.py", deals["run"])
        rates = self.step(name="시세 수집 실행")
        commit = self.step("commit")
        self.assertLess(self.index(deals), self.index(rates))
        self.assertLess(self.index(rates), self.index(commit))
        # 커밋 스텝은 조건 없이(앞 스텝 성공 기준) 실행돼야 한다
        self.assertNotIn("if", commit)

    def test_deal_failure_marks_run_failed_at_end(self):
        mark = self.step(name="딜 수집 실패 처리")
        self.assertIn("steps.deals.outcome == 'failure'", mark["if"])
        self.assertIn("always()", mark["if"])
        self.assertIn("exit 1", mark["run"])
        self.assertGreater(self.index(mark), self.index(self.step("commit")))

    def test_failure_issue_created_once_and_closed_on_recovery(self):
        create = self.step(name="수집 실패 알림 (GitHub 이슈, 열린 이슈가 있으면 생략)")
        self.assertIn("steps.deals.outcome == 'failure'", create["if"])
        self.assertIn("steps.commit.outcome == 'failure'", create["if"])
        self.assertIn("always()", create["if"])
        self.assertIn("gh issue list", create["run"])
        self.assertIn("gh issue create", create["run"])
        self.assertIn("[수집실패]", create["run"])

        close = self.step(name="수집 정상화 시 실패 이슈 닫기")
        self.assertIn("steps.deals.outcome == 'success'", close["if"])
        self.assertIn("steps.commit.outcome == 'success'", close["if"])
        self.assertIn("gh issue close", close["run"])
        self.assertIn("[수집실패]", close["run"])
        self.assertGreater(self.index(close), self.index(create))

    def test_schedule_avoids_top_of_hour(self):
        # 정각(:00) 예약 실행은 GitHub 가 대량으로 누락시켰다(하루 24회 중 3~5회 실행)
        with open(WORKFLOW, encoding="utf-8") as f:
            doc = yaml.safe_load(f)
        triggers = doc.get("on", doc.get(True))  # PyYAML 은 키 on 을 True 로 읽는다
        crons = [s["cron"] for s in triggers["schedule"]]
        self.assertEqual(len(crons), 1)
        minute, hour = crons[0].split()[:2]
        self.assertEqual(hour, "*")  # 매시간 실행 유지
        self.assertTrue(minute.isdigit() and 1 <= int(minute) <= 59, crons[0])

    def test_deal_alert_issue_skipped_when_deals_failed(self):
        alert = self.step(name="고할인 복귀 알림 (신규 감지 시 GitHub 이슈 생성)")
        self.assertEqual(alert.get("if"), "steps.deals.outcome == 'success'")


if __name__ == "__main__":
    unittest.main()
