import base64
import hashlib
import json
import subprocess
import unittest
from unittest.mock import patch

from fork_sync.gates import evaluate
from fork_sync.github import merge, observe


REPOSITORY = "owner/fork"
BASE, HEAD, UPSTREAM, TREE, MERGED = (letter * 40 for letter in "abcde")


def fixture():
    raw_policy = b'{"jev_questions":{"sync":{"type":"choice"}}}\n'
    questions = b'{\n  "sync": {\n    "type": "choice"\n  }\n}\n'
    policy = {
        "sha256": hashlib.sha256(raw_policy).hexdigest(),
        "questions_sha256": hashlib.sha256(questions).hexdigest(),
        "target_branch": "main", "head_branch": "nisavid/sync-candidate",
    }
    candidate = {"base": BASE, "head": HEAD, "upstream": UPSTREAM, "tree": TREE,
                 "policy_sha256": policy["sha256"], "questions_sha256": policy["questions_sha256"]}
    pr = {"number": 9, "state": "open", "draft": False,
          "base": {"ref": "main", "sha": BASE, "repo": {"full_name": REPOSITORY}},
          "head": {"ref": policy["head_branch"], "sha": HEAD, "repo": {"full_name": REPOSITORY}},
          "mergeable": True, "mergeable_state": "clean"}
    routes = {
        "repos/owner/fork/pulls/9": pr,
        "repos/owner/fork/git/ref/heads/main": {"object": {"sha": BASE}},
        f"repos/owner/fork/git/commits/{HEAD}": {"sha": HEAD, "tree": {"sha": TREE}},
        f"repos/owner/fork/contents/.agents/fork-sync.json?ref={BASE}": {
            "type": "file", "encoding": "base64", "content": base64.b64encode(raw_policy).decode()},
        f"repos/owner/fork/commits/{HEAD}/check-runs?filter=latest&per_page=100": [
            {"total_count": 1, "check_runs": [{"name": "sync-ci", "app": {"id": 15368},
                "head_sha": HEAD, "status": "completed", "conclusion": "success"}]}],
        "repos/owner/fork/pulls/9/reviews?per_page=100": [[{
            "id": 10, "user": {"login": "coderabbitai[bot]", "id": 136622811},
            "state": "APPROVED", "commit_id": HEAD, "submitted_at": "2026-10-07T20:00:00Z"}]],
        "graphql": [{"data": {"repository": {"pullRequest": {"reviewThreads": {
            "nodes": [{"isResolved": True}],
            "pageInfo": {"hasNextPage": False, "endCursor": None}}}}}}],
        "repos/owner/fork/branches/main/protection": {
            "enforce_admins": {"enabled": True}, "required_status_checks": {
                "strict": True, "checks": [{"context": "sync-ci", "app_id": 15368}]}},
        "repos/owner/fork/pulls/9/merge": {"merged": True, "sha": MERGED},
        f"repos/owner/fork/git/commits/{MERGED}": {
            "sha": MERGED, "parents": [{"sha": BASE}, {"sha": HEAD}]},
    }
    return candidate, policy, routes


class FakeGitHub:
    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def __call__(self, arguments, **kwargs):
        self.calls.append((arguments, kwargs))
        response = self.routes[arguments[2]]
        if isinstance(response, Exception):
            raise response
        if isinstance(response, subprocess.CompletedProcess):
            return response
        return subprocess.CompletedProcess(arguments, 0, json.dumps(response), "")


class GitHubTests(unittest.TestCase):
    def evaluate_routes(self, candidate, policy, routes):
        policy.setdefault("required_checks", [{"name": "sync-ci", "app_id": 15368}])
        policy.update({"coderabbit_user_id": 136622811,
                       "jev_model": "jev-1.13.0", "jev_min_probability": 0.96})
        with patch("subprocess.run", side_effect=FakeGitHub(routes)):
            observation = observe(REPOSITORY, 9, "main", candidate, policy)
        observation["jev"] = {
            "binding": candidate.copy(), "model": "jev-1.13.0",
            "cached": False, "question_type": "choice",
            "options": ["no_additional_handling", "additional_handling", "insufficient_context"],
            "answer": "no_additional_handling",
            "probabilities": {"no_additional_handling": 0.96,
                              "additional_handling": 0.03, "insufficient_context": 0.01},
            "state_sha256": "1" * 64, "observed_state_sha256": "1" * 64,
        }
        return evaluate(candidate, observation, policy)

    def test_identical_successful_suites_on_one_page_allow_readiness(self):
        candidate, policy, routes = fixture()
        self.assertEqual(self.evaluate_routes(candidate, policy, routes),
                         {"status": "ready", "reasons": []})
        page = routes[f"repos/owner/fork/commits/{HEAD}/check-runs?filter=latest&per_page=100"][0]
        page["check_runs"][0].update({"id": 100, "check_suite": {"id": 200}})
        page["check_runs"].append(dict(page["check_runs"][0], id=101, check_suite={"id": 201}))
        page["total_count"] = 2
        self.assertEqual(self.evaluate_routes(candidate, policy, routes),
                         {"status": "ready", "reasons": []})

    def test_identical_successful_suites_across_pages_allow_readiness(self):
        candidate, policy, routes = fixture()
        pages = routes[f"repos/owner/fork/commits/{HEAD}/check-runs?filter=latest&per_page=100"]
        pages[0]["total_count"] = 2
        pages.append({"total_count": 2, "check_runs": [dict(pages[0]["check_runs"][0])]})
        self.assertEqual(self.evaluate_routes(candidate, policy, routes),
                         {"status": "ready", "reasons": []})

    def test_conflicting_repeated_check_identity_holds_on_any_page(self):
        for mutation in ({"head_sha": "0" * 40}, {"status": "in_progress"},
                         {"conclusion": "failure"}):
            for separate_page in (False, True):
                for conflicting_first in (False, True):
                    with self.subTest(mutation=mutation, separate_page=separate_page,
                                      conflicting_first=conflicting_first):
                        candidate, policy, routes = fixture()
                        pages = routes[f"repos/owner/fork/commits/{HEAD}/check-runs?filter=latest&per_page=100"]
                        original = pages[0]["check_runs"][0]
                        records = [original, dict(original, **mutation)]
                        if conflicting_first:
                            records.reverse()
                        routes[f"repos/owner/fork/commits/{HEAD}/check-runs?filter=latest&per_page=100"] = (
                            [{"total_count": 2, "check_runs": [record]} for record in records]
                            if separate_page else [{"total_count": 2, "check_runs": records}])
                        self.assertEqual(self.evaluate_routes(candidate, policy, routes),
                                         {"status": "hold", "reasons": ["missing_required_checks"]})

    def test_identical_failed_pending_or_wrong_head_checks_still_hold(self):
        for mutation in ({"head_sha": "0" * 40}, {"status": "in_progress", "conclusion": None},
                         {"conclusion": "failure"}):
            with self.subTest(mutation=mutation):
                candidate, policy, routes = fixture()
                page = routes[f"repos/owner/fork/commits/{HEAD}/check-runs?filter=latest&per_page=100"][0]
                page["check_runs"][0].update(mutation)
                page["check_runs"].append(dict(page["check_runs"][0]))
                page["total_count"] = 2
                self.assertEqual(self.evaluate_routes(candidate, policy, routes),
                                 {"status": "hold", "reasons": ["checks_not_passed"]})

    def test_incomplete_or_malformed_raw_check_pages_hold_before_collapsing(self):
        for replacement in ([], [None], [{"total_count": 1}],
                            [{"total_count": True, "check_runs": []}]):
            with self.subTest(replacement=replacement):
                candidate, policy, routes = fixture()
                routes[f"repos/owner/fork/commits/{HEAD}/check-runs?filter=latest&per_page=100"] = replacement
                self.assertEqual(self.evaluate_routes(candidate, policy, routes),
                                 {"status": "hold", "reasons": ["stale_observation"]})
        for counts in ((1,), (3,), (2, 1)):
            with self.subTest(counts=counts):
                candidate, policy, routes = fixture()
                endpoint = f"repos/owner/fork/commits/{HEAD}/check-runs?filter=latest&per_page=100"
                check = routes[endpoint][0]["check_runs"][0]
                routes[endpoint] = ([{"total_count": counts[0], "check_runs": [check, dict(check)]}]
                                    if len(counts) == 1 else
                                    [{"total_count": count, "check_runs": [dict(check)]} for count in counts])
                self.assertEqual(self.evaluate_routes(candidate, policy, routes),
                                 {"status": "hold", "reasons": ["stale_observation"]})

    def test_required_checks_with_different_names_or_apps_stay_distinct(self):
        for mutation, required in (({"name": "second-ci"}, {"name": "second-ci", "app_id": 15368}),
                                   ({"app": {"id": 1}}, {"name": "sync-ci", "app_id": 1})):
            with self.subTest(mutation=mutation):
                candidate, policy, routes = fixture()
                policy["required_checks"] = [{"name": "sync-ci", "app_id": 15368}, required]
                routes["repos/owner/fork/branches/main/protection"]["required_status_checks"]["checks"].append(
                    {"context": required["name"], "app_id": required["app_id"]})
                page = routes[f"repos/owner/fork/commits/{HEAD}/check-runs?filter=latest&per_page=100"][0]
                page["check_runs"].append(dict(page["check_runs"][0], **mutation))
                page["total_count"] = 2
                self.assertEqual(self.evaluate_routes(candidate, policy, routes),
                                 {"status": "ready", "reasons": []})
                page["check_runs"][1]["conclusion"] = "failure"
                self.assertEqual(self.evaluate_routes(candidate, policy, routes),
                                 {"status": "hold", "reasons": ["checks_not_passed"]})

    def test_boolean_or_float_app_ids_cannot_collapse_into_a_valid_integer(self):
        for invalid_app_id in (True, 1.0):
            for invalid_first in (False, True):
                with self.subTest(invalid_app_id=invalid_app_id, invalid_first=invalid_first):
                    candidate, policy, routes = fixture()
                    policy["required_checks"] = [{"name": "sync-ci", "app_id": 1}]
                    routes["repos/owner/fork/branches/main/protection"]["required_status_checks"]["checks"][0]["app_id"] = 1
                    page = routes[f"repos/owner/fork/commits/{HEAD}/check-runs?filter=latest&per_page=100"][0]
                    page["check_runs"][0]["app"] = {"id": 1}
                    self.assertEqual(self.evaluate_routes(candidate, policy, routes),
                                     {"status": "ready", "reasons": []})
                    page["check_runs"].append(dict(page["check_runs"][0], app={"id": invalid_app_id}))
                    if invalid_first:
                        page["check_runs"].reverse()
                    page["total_count"] = 2
                    self.assertEqual(self.evaluate_routes(candidate, policy, routes),
                                     {"status": "hold", "reasons": ["missing_required_checks"]})

    def test_transport_failures_are_redacted(self):
        for response in (OSError("sensitive transport detail"),
                         subprocess.CompletedProcess("gh", 1, "secret output", "secret stderr"),
                         subprocess.CompletedProcess("gh", 0, "not JSON", "")):
            candidate, policy, routes = fixture()
            routes["repos/owner/fork/pulls/9"] = response
            with self.subTest(response=type(response).__name__), patch("subprocess.run", side_effect=FakeGitHub(routes)):
                self.assertEqual(observe(REPOSITORY, 9, "main", candidate, policy),
                                 {"error": "github_observation_unavailable"})

    def test_invalid_candidate_does_not_reach_github(self):
        candidate, policy, routes = fixture()
        candidate["head"] = "../another-resource"
        with patch("subprocess.run") as process:
            self.assertIn("error", observe(REPOSITORY, 9, "main", candidate, policy))
            self.assertEqual(merge(REPOSITORY, 9, candidate, policy)["status"], "hold")
            self.assertFalse(process.called)

    def test_timeout_after_success_recovers_only_verified_merge(self):
        candidate, policy, routes = fixture()
        routes["repos/owner/fork/pulls/9/merge"] = subprocess.TimeoutExpired("gh", 90)
        routes["repos/owner/fork/pulls/9"]["merged"] = True
        routes["repos/owner/fork/pulls/9"]["merge_commit_sha"] = MERGED
        transport = FakeGitHub(routes)
        with patch("subprocess.run", side_effect=transport):
            self.assertEqual(merge(REPOSITORY, 9, candidate, policy), {"status": "merged", "merge_commit": MERGED})
        self.assertEqual(sum("PUT" in args for args, _ in transport.calls), 1)

    def test_head_and_mergeability_drift_prevent_merge(self):
        for field, value in (("head", {"sha": "0" * 40}), ("mergeable", False),
                             ("mergeable_state", "unknown")):
            candidate, policy, routes = fixture()
            routes["repos/owner/fork/pulls/9"][field] = value
            transport = FakeGitHub(routes)
            with self.subTest(field=field), patch("subprocess.run", side_effect=transport):
                self.assertEqual(merge(REPOSITORY, 9, candidate, policy)["status"], "hold")
                self.assertFalse(any("PUT" in args for args, _ in transport.calls))

    def test_malformed_provider_shapes_and_wrong_policy_file_type_hold(self):
        for endpoint, replacement in (("graphql", [None]),
                                       ("repos/owner/fork/pulls/9/reviews?per_page=100", {}),
                                       (f"repos/owner/fork/contents/.agents/fork-sync.json?ref={BASE}", None)):
            candidate, policy, routes = fixture()
            routes[endpoint] = replacement
            with self.subTest(endpoint=endpoint), patch("subprocess.run", side_effect=FakeGitHub(routes)):
                self.assertIn("error", observe(REPOSITORY, 9, "main", candidate, policy))
        for field, value in (("type", "symlink"), ("encoding", "none")):
            candidate, policy, routes = fixture()
            routes[f"repos/owner/fork/contents/.agents/fork-sync.json?ref={BASE}"][field] = value
            with self.subTest(field=field), patch("subprocess.run", side_effect=FakeGitHub(routes)):
                self.assertIn("error", observe(REPOSITORY, 9, "main", candidate, policy))

    def test_rejected_merge_and_wrong_result_parents_are_not_success(self):
        for response, parents, expected in (({"merged": False}, [BASE, HEAD], "hold"),
                                             ({"merged": True, "sha": MERGED}, ["0" * 40, HEAD], "unknown"),
                                             ({"merged": True, "sha": MERGED}, [BASE], "unknown")):
            with self.subTest(expected=expected, parents=parents):
                candidate, policy, routes = fixture()
                routes["repos/owner/fork/pulls/9/merge"] = response
                routes[f"repos/owner/fork/git/commits/{MERGED}"]["parents"] = [{"sha": value} for value in parents]
                transport = FakeGitHub(routes)
                with patch("subprocess.run", side_effect=transport):
                    self.assertEqual(merge(REPOSITORY, 9, candidate, policy)["status"], expected)
                self.assertEqual(sum("PUT" in args for args, _ in transport.calls), 1)

    def test_missing_resolution_boolean_cannot_look_resolved(self):
        candidate, policy, routes = fixture()
        routes["graphql"][0]["data"]["repository"]["pullRequest"]["reviewThreads"]["nodes"] = [{"isResolved": "false"}]
        with patch("subprocess.run", side_effect=FakeGitHub(routes)):
            self.assertIn("error", observe(REPOSITORY, 9, "main", candidate, policy))

    def test_policy_freshness_is_computed_from_returned_bytes(self):
        candidate, policy, routes = fixture()
        raw = b'{"jev_questions":{"changed":true}}\n'
        routes[f"repos/owner/fork/contents/.agents/fork-sync.json?ref={BASE}"]["content"] = base64.b64encode(raw).decode()
        with patch("subprocess.run", side_effect=FakeGitHub(routes)):
            result = observe(REPOSITORY, 9, "main", candidate, policy)
        self.assertNotEqual(result["policy_sha256"], candidate["policy_sha256"])
        self.assertNotEqual(result["questions_sha256"], candidate["questions_sha256"])

    def setUp(self):
        environment = patch.dict("os.environ", {"GH_TOKEN": "publication-fixture-token"}, clear=True)
        environment.start()
        self.addCleanup(environment.stop)

    def test_merge_requires_explicit_credential_and_safe_address(self):
        candidate, policy, routes = fixture()
        transport = FakeGitHub(routes)
        with patch.dict("os.environ", {"GH_TOKEN": ""}), patch("subprocess.run", side_effect=transport):
            self.assertEqual(merge(REPOSITORY, 9, candidate, policy)["status"], "hold")
        self.assertFalse(any("PUT" in args for args, _ in transport.calls))
        for repo, number in (("../other", 9), ("https://example.com", 9), ("owner/fork?query", 9),
                             (REPOSITORY, "9/merge"), (REPOSITORY, True)):
            with self.subTest(repo=repo, number=number), patch("subprocess.run") as process:
                self.assertEqual(merge(repo, number, candidate, policy)["status"], "hold")
                self.assertFalse(process.called)

    def test_base_drift_blocks_merge_before_the_write(self):
        candidate, policy, routes = fixture()
        routes["repos/owner/fork/git/ref/heads/main"]["object"]["sha"] = "0" * 40
        transport = FakeGitHub(routes)
        with patch("subprocess.run", side_effect=transport):
            result = merge(REPOSITORY, 9, candidate, policy)
        self.assertEqual(result["status"], "hold")
        self.assertFalse(any("PUT" in args for args, _ in transport.calls))

    def test_uncertain_merge_is_observed_but_never_retried(self):
        candidate, policy, routes = fixture()
        routes["repos/owner/fork/pulls/9/merge"] = subprocess.TimeoutExpired("gh", 90)
        routes["repos/owner/fork/pulls/9"]["merged"] = False
        transport = FakeGitHub(routes)
        with patch("subprocess.run", side_effect=transport):
            result = merge(REPOSITORY, 9, candidate, policy)
        self.assertEqual(result["status"], "unknown")
        self.assertEqual(sum("PUT" in args for args, _ in transport.calls), 1)
        self.assertEqual(transport.calls[-1][0][2], "repos/owner/fork/pulls/9")

    def test_merge_uses_one_conditional_write_and_verifies_result_parents(self):
        candidate, policy, routes = fixture()
        transport = FakeGitHub(routes)
        with patch.dict("os.environ", {"GH_TOKEN": "publication-fixture-token", "GH_READ_TOKEN": "read-fixture-token"}), \
                patch("subprocess.run", side_effect=transport):
            result = merge(REPOSITORY, 9, candidate, policy)
        self.assertEqual(result, {"status": "merged", "merge_commit": MERGED})
        writes = [(args, kwargs) for args, kwargs in transport.calls if "PUT" in args]
        self.assertEqual(len(writes), 1)
        self.assertEqual(json.loads(writes[0][1]["input"]), {"sha": HEAD, "merge_method": "merge"})
        self.assertEqual(writes[0][1]["env"]["GH_TOKEN"], "publication-fixture-token")
        self.assertTrue(all(kwargs["env"]["GH_TOKEN"] == "read-fixture-token"
                            for args, kwargs in transport.calls if "PUT" not in args))

    def test_missing_or_partial_api_evidence_is_redacted_and_holds(self):
        for key, response in (
                ("graphql", [{"errors": [{"message": "sensitive forge details"}], "data": None}]),
                ("repos/owner/fork/branches/main/protection", None),
                (f"repos/owner/fork/commits/{HEAD}/check-runs?filter=latest&per_page=100",
                 [{"total_count": 20, "check_runs": []}]),
                (f"repos/owner/fork/contents/.agents/fork-sync.json?ref={BASE}",
                 {"encoding": "base64", "content": "!!!!", "type": "file"})):
            with self.subTest(endpoint=key):
                candidate, policy, routes = fixture()
                routes[key] = response
                with patch("subprocess.run", side_effect=FakeGitHub(routes)):
                    result = observe(REPOSITORY, 9, "main", candidate, policy)
                self.assertEqual(result, {"error": "github_observation_unavailable"})

    def test_all_pages_are_retained_and_incomplete_thread_evidence_holds(self):
        candidate, policy, routes = fixture()
        check_endpoint = f"repos/owner/fork/commits/{HEAD}/check-runs?filter=latest&per_page=100"
        routes[check_endpoint][0]["total_count"] = 2
        routes[check_endpoint].append({"total_count": 2, "check_runs": [{
            "name": "second-check", "app": {"id": 15368}, "head_sha": HEAD,
            "status": "completed", "conclusion": "failure"}]})
        routes["repos/owner/fork/pulls/9/reviews?per_page=100"].append([{
            "id": 11, "user": {"login": "coderabbitai[bot]", "id": 136622811},
            "state": "CHANGES_REQUESTED", "commit_id": HEAD, "submitted_at": "2026-10-07T21:00:00Z"}])
        threads = routes["graphql"][0]["data"]["repository"]["pullRequest"]["reviewThreads"]
        threads["pageInfo"] = {"hasNextPage": True, "endCursor": "page1"}
        with patch("subprocess.run", side_effect=FakeGitHub(routes)):
            self.assertIn("error", observe(REPOSITORY, 9, "main", candidate, policy))
        routes["graphql"].append({"data": {"repository": {"pullRequest": {"reviewThreads": {
            "nodes": [{"isResolved": False}],
            "pageInfo": {"hasNextPage": False, "endCursor": "page2"}}}}}})
        transport = FakeGitHub(routes)
        with patch("subprocess.run", side_effect=transport):
            result = observe(REPOSITORY, 9, "main", candidate, policy)
        self.assertEqual(len(result["checks"]), 2)
        self.assertEqual(len(result["reviews"]), 2)
        self.assertEqual(result["unresolved_threads"], 1)
        paged = [args for args, _ in transport.calls if args[2] in (
            check_endpoint, "repos/owner/fork/pulls/9/reviews?per_page=100", "graphql")]
        self.assertTrue(all("--paginate" in args and "--slurp" in args for args in paged))

    def test_wrong_pr_identity_or_changed_candidate_holds(self):
        for field, value in (("base_repo", "elsewhere/fork"), ("head_repo", "elsewhere/fork"),
                             ("base_ref", "other"), ("head_ref", "other"),
                             ("head_sha", "0" * 40), ("state", "closed"), ("draft", True)):
            with self.subTest(field=field):
                candidate, policy, routes = fixture()
                pr = routes["repos/owner/fork/pulls/9"]
                if field.endswith("_repo"):
                    pr[field.split("_")[0]]["repo"]["full_name"] = value
                elif field.endswith(("_ref", "_sha")):
                    part, attribute = field.split("_")
                    pr[part][attribute] = value
                else:
                    pr[field] = value
                with patch("subprocess.run", side_effect=FakeGitHub(routes)):
                    result = observe(REPOSITORY, 9, "main", candidate, policy)
                self.assertIn("error", result)

    def test_collects_current_authenticated_gate_observations(self):
        candidate, policy, routes = fixture()
        with patch("subprocess.run", side_effect=FakeGitHub(routes)):
            result = observe(REPOSITORY, 9, "main", candidate, policy)
        self.assertEqual(result["binding"], candidate)
        self.assertEqual(result["checks"][0]["app_id"], 15368)
        self.assertEqual(result["reviews"][0]["user_id"], 136622811)
        self.assertEqual(result["unresolved_threads"], 0)
        self.assertEqual(result["questions_sha256"], candidate["questions_sha256"])


if __name__ == "__main__":
    unittest.main()
