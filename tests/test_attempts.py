import json
import os
import subprocess
import threading
import unittest
from collections import Counter
from unittest.mock import patch

from fork_sync.attempts import permit


REPO = "nisavid/typesafe-skills"
CANDIDATE = {"base": "a" * 40, "upstream": "b" * 40, "head": "c" * 40,
             "tree": "d" * 40, "policy_sha256": "e" * 64, "questions_sha256": "f" * 64}
# Fixed independently recorded digest for this public candidate fixture.
NAME = "Jev 760bb26dc88d6f953a009b85e60970d45317bc97ddd5547cd056b91919af82aa"


def fixture():
    run = {"id": 100, "run_number": 1, "run_attempt": 1, "workflow_id": 12,
           "status": "in_progress", "repository": {"full_name": REPO}}
    job = {"id": 200, "run_id": 100, "name": NAME, "status": "in_progress",
           "conclusion": None, "started_at": "2026-10-08T01:00:00Z"}
    return {
        f"repos/{REPO}/actions/workflows/upstream-sync.yml": {
            "id": 12, "path": ".github/workflows/upstream-sync.yml", "state": "active"},
        f"repos/{REPO}/actions/runs/100": run,
        f"repos/{REPO}/actions/workflows/12/runs?per_page=100": [{"total_count": 1, "workflow_runs": [run]}],
        f"repos/{REPO}/actions/runs/100/jobs?filter=all&per_page=100": [{"total_count": 1, "jobs": [job]}],
        f"repos/{REPO}/actions/runs/100/attempts/1/jobs?per_page=100": [{"total_count": 1, "jobs": [job]}],
    }


def retained_history(count=100):
    routes = fixture()
    runs = routes[f"repos/{REPO}/actions/workflows/12/runs?per_page=100"][0]["workflow_runs"]
    runs[0]["run_number"] = count
    for number in range(2, count + 1):
        run_id = 99 + number
        runs.append({"id": run_id, "run_number": number - 1, "run_attempt": 2,
                     "workflow_id": 12, "status": "completed", "repository": {"full_name": REPO}})
        jobs = [{"id": 1000 + number * 2 + attempt, "run_id": run_id,
                 "name": NAME, "status": "completed", "conclusion": "skipped",
                 "started_at": None} for attempt in (1, 2)]
        routes[f"repos/{REPO}/actions/runs/{run_id}/jobs?filter=all&per_page=100"] = [
            {"total_count": 2, "jobs": [job]} for job in jobs]
        for attempt, job in enumerate(jobs, 1):
            routes[f"repos/{REPO}/actions/runs/{run_id}/attempts/{attempt}/jobs?per_page=100"] = [
                {"total_count": 1, "jobs": [job]}]
    routes[f"repos/{REPO}/actions/workflows/12/runs?per_page=100"] = [
        {"total_count": count, "workflow_runs": runs[:50]},
        {"total_count": count, "workflow_runs": runs[50:]},
    ]
    return routes


class Transport:
    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def __call__(self, args, **kwargs):
        self.calls.append((args, kwargs))
        value = self.routes[args[2]]
        if isinstance(value, Exception):
            raise value
        return subprocess.CompletedProcess(args, 0, json.dumps(value), "")


class AttemptTests(unittest.TestCase):
    def test_complete_retained_history_overlaps_at_most_four_external_reads(self):
        routes = retained_history()
        transport = Transport(routes)
        lock, four_reading, release = threading.Lock(), threading.Event(), threading.Event()
        active, peak = 0, 0

        def blocked_transport(args, **kwargs):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
                if active == 4:
                    four_reading.set()
            try:
                if "jobs?filter=all" in args[2]:
                    if not release.wait(5):
                        raise OSError("test transport was not released")
                return transport(args, **kwargs)
            finally:
                with lock:
                    active -= 1

        result = []
        with patch("subprocess.run", side_effect=blocked_transport):
            runner = threading.Thread(target=lambda: result.append(permit(CANDIDATE, {"repository": REPO})))
            runner.start()
            try:
                overlapped = four_reading.wait(2)
                self.assertFalse(result, "history must finish before permission")
            finally:
                release.set()
                runner.join(5)
            self.assertFalse(runner.is_alive())
        self.assertTrue(overlapped, "four independent history reads should overlap")
        self.assertEqual(peak, 4, "at most four gh processes may be in flight")
        self.assertEqual(result, [{"status": "permitted", "reasons": []}])
        # Every page-bearing endpoint and both attempts of all 99 prior runs are required.
        self.assertEqual(Counter(args[2] for args, _ in transport.calls), Counter(routes.keys()))

    def test_delayed_old_attempt_must_finish_before_permission(self):
        for outcome in ("skipped", "consumed", "unavailable", "timeout", "missing", "inconsistent"):
            with self.subTest(outcome=outcome):
                routes = retained_history(12)
                delayed = f"repos/{REPO}/actions/runs/101/attempts/1/jobs?per_page=100"
                if outcome == "consumed":
                    # The all-attempt snapshot contains this same old job.
                    routes[delayed][0]["jobs"][0]["conclusion"] = "failure"
                elif outcome == "unavailable":
                    routes[delayed] = OSError("retained attempt unavailable")
                elif outcome == "timeout":
                    routes[delayed] = subprocess.TimeoutExpired("gh", 90)
                elif outcome == "missing":
                    routes[delayed] = [{"total_count": 1, "jobs": []}]
                elif outcome == "inconsistent":
                    routes[delayed] = [{"total_count": 1, "jobs": [dict(
                        routes[delayed][0]["jobs"][0], name="Jev " + "0" * 64)]}]
                transport = Transport(routes)
                waiting, others_finished, release = threading.Event(), threading.Event(), threading.Event()
                lock, seen = threading.Lock(), set()
                # Attempt two of the delayed run remains sequential behind attempt one.
                independent = set(routes) - {delayed,
                    f"repos/{REPO}/actions/runs/101/attempts/2/jobs?per_page=100"}

                def delayed_transport(args, **kwargs):
                    if args[2] == delayed:
                        waiting.set()
                        if not release.wait(5):
                            raise OSError("test transport was not released")
                    response = transport(args, **kwargs)
                    with lock:
                        seen.add(args[2])
                        if independent <= seen:
                            others_finished.set()
                    return response

                result = []
                with patch("subprocess.run", side_effect=delayed_transport):
                    runner = threading.Thread(target=lambda: result.append(permit(CANDIDATE, {"repository": REPO})))
                    runner.start()
                    try:
                        self.assertTrue(waiting.wait(2), "the old attempt must be read")
                        completed_independent = others_finished.wait(2)
                        self.assertFalse(result, "an outstanding old attempt prevents permission")
                    finally:
                        release.set()
                        runner.join(5)
                    self.assertFalse(runner.is_alive())
                self.assertTrue(completed_independent, "unrelated runs should finish while the old read waits")
                expected = ({"status": "permitted", "reasons": []} if outcome == "skipped" else
                            {"status": "hold", "reasons": ["jev_attempt_consumed" if outcome == "consumed"
                                                          else "jev_attempt_unconfirmed"]})
                self.assertEqual(result, [expected])

    def test_malformed_job_metadata_holds_without_raising(self):
        for field, value in (("id", True), ("name", 17), ("run_id", []), ("started_at", "invalid")):
            routes = fixture()
            routes[f"repos/{REPO}/actions/runs/100/attempts/1/jobs?per_page=100"][0]["jobs"][0][field] = value
            with self.subTest(field=field), patch("subprocess.run", side_effect=Transport(routes)):
                self.assertEqual(permit(CANDIDATE, {"repository": REPO})["status"], "hold")

    def test_disagreeing_job_snapshots_do_not_permit(self):
        routes = fixture()
        job = dict(routes[f"repos/{REPO}/actions/runs/100/jobs?filter=all&per_page=100"][0]["jobs"][0],
                   name="Jev " + "0" * 64)
        routes[f"repos/{REPO}/actions/runs/100/jobs?filter=all&per_page=100"] = [{"total_count": 1, "jobs": [job]}]
        with patch("subprocess.run", side_effect=Transport(routes)):
            self.assertEqual(permit(CANDIDATE, {"repository": REPO})["status"], "hold")

    def test_previous_rerun_attempt_cannot_be_hidden_by_latest_jobs(self):
        routes = fixture()
        routes[f"repos/{REPO}/actions/runs/100"]["run_attempt"] = 2
        old = dict(routes[f"repos/{REPO}/actions/runs/100/attempts/1/jobs?per_page=100"][0]["jobs"][0],
                   id=199, status="completed", conclusion="failure")
        current = routes[f"repos/{REPO}/actions/runs/100/jobs?filter=all&per_page=100"][0]["jobs"][0]
        routes[f"repos/{REPO}/actions/runs/100/attempts/2/jobs?per_page=100"] = [{"total_count": 1, "jobs": [current]}]
        routes[f"repos/{REPO}/actions/runs/100/attempts/1/jobs?per_page=100"] = [{"total_count": 1, "jobs": [old]}]
        routes[f"repos/{REPO}/actions/runs/100/jobs?filter=all&per_page=100"] = [{"total_count": 2, "jobs": [old, current]}]
        with patch.dict(os.environ, {"GITHUB_RUN_ATTEMPT": "2"}), patch("subprocess.run", side_effect=Transport(routes)):
            self.assertEqual(permit(CANDIDATE, {"repository": REPO}), {"status": "hold", "reasons": ["jev_attempt_consumed"]})
        old["conclusion"] = "skipped"
        with patch.dict(os.environ, {"GITHUB_RUN_ATTEMPT": "2"}), patch("subprocess.run", side_effect=Transport(routes)):
            self.assertEqual(permit(CANDIDATE, {"repository": REPO})["status"], "permitted")

    def test_malformed_or_expired_records_hold(self):
        for endpoint, value in ((f"repos/{REPO}/actions/workflows/12/runs?per_page=100", []),
                                (f"repos/{REPO}/actions/runs/100/jobs?filter=all&per_page=100", [{"total_count": 1, "jobs": []}]),
                                (f"repos/{REPO}/actions/runs/100/attempts/1/jobs?per_page=100", OSError("expired detail"))):
            routes = fixture()
            routes[endpoint] = value
            with self.subTest(endpoint=endpoint), patch("subprocess.run", side_effect=Transport(routes)):
                self.assertEqual(permit(CANDIDATE, {"repository": REPO})["status"], "hold")
    def test_missing_run_history_holds_even_when_current_job_is_visible(self):
        routes = fixture()
        routes[f"repos/{REPO}/actions/runs/100"]["run_number"] = 2
        with patch("subprocess.run", side_effect=Transport(routes)):
            self.assertEqual(permit(CANDIDATE, {"repository": REPO})["status"], "hold")

    def test_previously_started_matching_job_consumes_attempt_even_in_later_numbered_run(self):
        for status, conclusion in (("completed", "success"), ("completed", "failure"),
                                   ("completed", "cancelled"), ("completed", "timed_out"),
                                   ("in_progress", None)):
            routes = fixture()
            history = routes[f"repos/{REPO}/actions/workflows/12/runs?per_page=100"]
            history[0]["total_count"] = 2
            history.append({"total_count": 2, "workflow_runs": [{"id": 101,
                "workflow_id": 12, "run_number": 2, "run_attempt": 1, "status": status,
                "repository": {"full_name": REPO}}]})
            job = {"id": 201, "run_id": 101, "name": NAME, "status": status,
                   "conclusion": conclusion, "started_at": "2026-10-08T00:00:00Z"}
            for suffix in ("jobs?filter=all&per_page=100", "attempts/1/jobs?per_page=100"):
                routes[f"repos/{REPO}/actions/runs/101/{suffix}"] = [{"total_count": 1, "jobs": [job]}]
            with self.subTest(status=status, conclusion=conclusion), patch("subprocess.run", side_effect=Transport(routes)):
                self.assertEqual(permit(CANDIDATE, {"repository": REPO})["status"], "hold")
    def test_workflow_recreation_or_run_identity_mismatch_holds(self):
        for endpoint, field, value in ((f"repos/{REPO}/actions/workflows/upstream-sync.yml", "id", 13),
                                       (f"repos/{REPO}/actions/workflows/upstream-sync.yml", "path", ".github/workflows/other.yml"),
                                       (f"repos/{REPO}/actions/runs/100", "run_attempt", 2),
                                       (f"repos/{REPO}/actions/runs/100", "workflow_id", 13)):
            routes = fixture()
            routes[endpoint][field] = value
            with self.subTest(field=field), patch("subprocess.run", side_effect=Transport(routes)):
                self.assertEqual(permit(CANDIDATE, {"repository": REPO})["status"], "hold")

    def setUp(self):
        env = patch.dict(os.environ, {"GITHUB_RUN_ID": "100", "GITHUB_RUN_ATTEMPT": "1",
            "FORK_SYNC_FIRST_RUN_NUMBER": "1", "FORK_SYNC_WORKFLOW_ID": "12",
            "GH_READ_TOKEN": "fixture-read-token"}, clear=True)
        env.start()
        self.addCleanup(env.stop)

    def test_first_visible_candidate_job_is_permitted(self):
        with patch("subprocess.run", side_effect=Transport(fixture())):
            self.assertEqual(permit(CANDIDATE, {"repository": REPO}), {"status": "permitted", "reasons": []})

    def test_activation_and_current_job_must_be_present_and_match(self):
        for key in ("GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT", "FORK_SYNC_WORKFLOW_ID",
                    "FORK_SYNC_FIRST_RUN_NUMBER", "GH_READ_TOKEN"):
            with self.subTest(key=key), patch.dict(os.environ, {key: ""}), patch("subprocess.run") as process:
                self.assertEqual(permit(CANDIDATE, {"repository": REPO})["status"], "hold")
                self.assertFalse(process.called)
        for field, value in (("name", "Jev wrong-binding"), ("status", "queued"), ("started_at", None)):
            routes = fixture()
            routes[f"repos/{REPO}/actions/runs/100/attempts/1/jobs?per_page=100"][0]["jobs"][0][field] = value
            with self.subTest(field=field), patch("subprocess.run", side_effect=Transport(routes)):
                self.assertEqual(permit(CANDIDATE, {"repository": REPO})["status"], "hold")


if __name__ == "__main__":
    unittest.main()
