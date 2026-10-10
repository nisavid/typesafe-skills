import unittest

from fork_sync.gates import evaluate


def accepted_evidence():
    candidate = {
        "base": "a" * 40, "upstream": "b" * 40,
        "head": "c" * 40, "tree": "d" * 40,
        "policy_sha256": "e" * 64, "questions_sha256": "f" * 64,
    }
    policy = {
        "sha256": candidate["policy_sha256"],
        "questions_sha256": candidate["questions_sha256"],
        "jev_model": "jev-1.13.0", "jev_min_probability": 0.96,
        "coderabbit_user_id": 136622811,
        "required_checks": [{"name": "sync-ci", "app_id": 15368}],
    }
    observation = {
        "binding": candidate.copy(),
        "live_base": candidate["base"], "live_head": candidate["head"],
        "policy_sha256": policy["sha256"],
        "questions_sha256": policy["questions_sha256"],
        "mergeability": "clean", "unresolved_threads": 0,
        "protection": {"enforce_admins": True, "strict": True,
                       "required_approving_review_count": 1, "dismiss_stale_reviews": True,
                       "required_conversation_resolution": True,
                       "review_bypass_allowances": {"users": [], "teams": [], "apps": []},
                       "required_checks": [{"name": "sync-ci", "app_id": 15368}]},
        "checks": [{"name": "sync-ci", "app_id": 15368,
                    "head": candidate["head"], "status": "completed",
                    "conclusion": "success"}],
        "reviews": [{"id": 42, "user": "coderabbitai[bot]",
                     "user_id": 136622811,
                     "state": "APPROVED", "commit_id": candidate["head"],
                     "submitted_at": "2026-10-07T20:00:00Z"}],
        "jev": {
            "binding": candidate.copy(), "model": "jev-1.13.0",
            "cached": False, "question_type": "choice",
            "options": ["no_additional_handling", "additional_handling", "insufficient_context"],
            "answer": "no_additional_handling",
            "probabilities": {"no_additional_handling": 0.96,
                              "additional_handling": 0.03,
                              "insufficient_context": 0.01},
            "state_sha256": "1" * 64, "observed_state_sha256": "1" * 64,
        },
    }
    return candidate, observation, policy


class GateTests(unittest.TestCase):
    def test_malformed_numeric_evidence_holds_without_raising(self):
        candidate, observation, policy = accepted_evidence()
        observation["jev"]["probabilities"]["no_additional_handling"] = 10 ** 1000
        self.assertEqual(evaluate(candidate, observation, policy)["status"], "hold")

    def test_qualified_current_candidate_is_ready(self):
        self.assertEqual(evaluate(*accepted_evidence()), {"status": "ready", "reasons": []})

    def test_jev_requires_a_fresh_pinned_answer_and_complete_distribution(self):
        for mutation in ({"model": "jev-other"}, {"cached": True},
                         {"question_type": "text"}, {"options": ["no_additional_handling"]},
                         {"answer": "additional_handling"}, {"answer": None},
                         {"state_sha256": "0" * 64}, {"observed_state_sha256": None},
                         {"binding": {}}, {"probabilities": {}},
                         {"probabilities": {"no_additional_handling": 0.959,
                                            "additional_handling": 0.031, "insufficient_context": 0.01}},
                         {"probabilities": {"no_additional_handling": 0.97,
                                            "additional_handling": 0.03, "insufficient_context": 0.01}}):
            with self.subTest(mutation=mutation):
                candidate, observation, policy = accepted_evidence()
                observation["jev"].update(mutation)
                self.assertEqual(evaluate(candidate, observation, policy)["status"], "hold")
        for value in (float("nan"), float("inf"), -0.01, 1.01, True, "1"):
            with self.subTest(probability=value):
                candidate, observation, policy = accepted_evidence()
                observation["jev"]["probabilities"]["no_additional_handling"] = value
                self.assertEqual(evaluate(candidate, observation, policy)["status"], "hold")
        for mutation in ({"jev_model": "jev-other"}, {"jev_min_probability": 0},
                         {"jev_min_probability": None}):
            with self.subTest(policy=mutation):
                candidate, observation, policy = accepted_evidence()
                policy.update(mutation)
                self.assertEqual(evaluate(candidate, observation, policy)["status"], "hold")

    def test_coderabbit_approval_must_be_current_and_from_the_pinned_identity(self):
        for mutation in ({"commit_id": "0" * 40}, {"user": "someone"},
                         {"user_id": 1}, {"state": "COMMENTED"},
                         {"state": "DISMISSED"}, {"state": "CHANGES_REQUESTED"},
                         {"state": "PENDING"}, {"submitted_at": "bad"}):
            with self.subTest(mutation=mutation):
                candidate, observation, policy = accepted_evidence()
                observation["reviews"][0].update(mutation)
                self.assertEqual(evaluate(candidate, observation, policy)["status"], "hold")
        for reviews in (None, [], [None]):
            with self.subTest(reviews=reviews):
                candidate, observation, policy = accepted_evidence()
                observation["reviews"] = reviews
                self.assertEqual(evaluate(candidate, observation, policy)["status"], "hold")
        candidate, observation, policy = accepted_evidence()
        del policy["coderabbit_user_id"]
        self.assertEqual(evaluate(candidate, observation, policy)["status"], "hold")

    def test_later_review_objection_cancels_approval_until_a_new_approval(self):
        for state in ("CHANGES_REQUESTED", "DISMISSED"):
            with self.subTest(state=state):
                candidate, observation, policy = accepted_evidence()
                objection = dict(observation["reviews"][0], id=43, state=state,
                                 submitted_at="2026-10-07T21:00:00Z")
                observation["reviews"].insert(0, objection)
                self.assertEqual(evaluate(candidate, observation, policy)["status"], "hold")
                observation["reviews"].append(dict(objection, id=44, state="APPROVED",
                                                   submitted_at="2026-10-07T22:00:00Z"))
                self.assertEqual(evaluate(candidate, observation, policy)["status"], "ready")

    def test_review_protection_must_enforce_approval_dismissal_and_conversations(self):
        invalid_values = {
            "required_approving_review_count": (None, 0, -1, True, 1.0, "1", [], {}),
            "dismiss_stale_reviews": (None, False, 1, "true", [], {}),
            "required_conversation_resolution": (None, False, 1, "true", [], {}),
        }
        for field, values in invalid_values.items():
            for value in (*values, "missing"):
                with self.subTest(field=field, value=value):
                    candidate, observation, policy = accepted_evidence()
                    if value == "missing":
                        del observation["protection"][field]
                    else:
                        observation["protection"][field] = value
                    self.assertEqual(evaluate(candidate, observation, policy),
                                     {"status": "hold", "reasons": ["protection_inadequate"]})
        candidate, observation, policy = accepted_evidence()
        observation["protection"]["required_approving_review_count"] = 2
        self.assertEqual(evaluate(candidate, observation, policy)["status"], "ready")

    def test_review_bypass_allowances_must_be_complete_and_empty(self):
        variants = [None, {}, [], False, {"users": [], "teams": []}]
        for category in ("users", "teams", "apps"):
            for value in ([{"id": 123}], None, {}, "", False):
                variants.append({**{"users": [], "teams": [], "apps": []}, category: value})
        variants.append({"users": [], "teams": [], "apps": [], "unknown": []})
        for allowances in variants:
            with self.subTest(allowances=allowances):
                candidate, observation, policy = accepted_evidence()
                observation["protection"]["review_bypass_allowances"] = allowances
                self.assertEqual(evaluate(candidate, observation, policy),
                                 {"status": "hold", "reasons": ["protection_inadequate"]})
        candidate, observation, policy = accepted_evidence()
        del observation["protection"]["review_bypass_allowances"]
        self.assertEqual(evaluate(candidate, observation, policy),
                         {"status": "hold", "reasons": ["protection_inadequate"]})

    def test_unsafe_merge_state_holds(self):
        for field, value in (("mergeability", "unknown"), ("mergeability", "conflicting"),
                             ("unresolved_threads", 1), ("unresolved_threads", None),
                             ("unresolved_threads", False), ("protection", {}),
                             ("protection", None)):
            with self.subTest(field=field, value=value):
                candidate, observation, policy = accepted_evidence()
                observation[field] = value
                self.assertEqual(evaluate(candidate, observation, policy)["status"], "hold")

    def test_review_rules_do_not_replace_admin_and_required_check_protection(self):
        for mutation in ({"enforce_admins": False}, {"strict": False}, {"required_checks": []},
                         {"required_checks": [{"name": "sync-ci", "app_id": 1}]}):
            with self.subTest(mutation=mutation):
                candidate, observation, policy = accepted_evidence()
                observation["protection"].update(mutation)
                self.assertEqual(evaluate(candidate, observation, policy),
                                 {"status": "hold", "reasons": ["protection_inadequate"]})

    def test_every_required_check_must_succeed_for_the_current_head_and_app(self):
        for mutation in ({"head": "0" * 40}, {"app_id": 1}, {"conclusion": "skipped"},
                         {"conclusion": "neutral"}, {"conclusion": "failure"},
                         {"status": "in_progress"}, {"name": "different-check"}):
            with self.subTest(mutation=mutation):
                candidate, observation, policy = accepted_evidence()
                observation["checks"][0].update(mutation)
                self.assertEqual(evaluate(candidate, observation, policy)["status"], "hold")
        for checks in (None, [], [None]):
            with self.subTest(checks=checks):
                candidate, observation, policy = accepted_evidence()
                observation["checks"] = checks
                self.assertEqual(evaluate(candidate, observation, policy)["status"], "hold")
        candidate, observation, policy = accepted_evidence()
        policy["required_checks"] = []
        self.assertEqual(evaluate(candidate, observation, policy)["status"], "hold")
        candidate, observation, policy = accepted_evidence()
        observation["checks"] *= 2
        self.assertEqual(evaluate(candidate, observation, policy)["status"], "hold")

    def test_stale_or_incomplete_candidate_binding_holds(self):
        for field in ("base", "upstream", "head", "tree", "policy_sha256", "questions_sha256"):
            with self.subTest(field=field):
                candidate, observation, policy = accepted_evidence()
                observation["binding"][field] = "0" * len(candidate[field])
                self.assertEqual(evaluate(candidate, observation, policy)["status"], "hold")

    def test_live_branch_or_policy_drift_holds(self):
        for field in ("live_base", "live_head", "policy_sha256", "questions_sha256"):
            with self.subTest(field=field):
                candidate, observation, policy = accepted_evidence()
                observation[field] = "0" * len(observation[field])
                self.assertEqual(evaluate(candidate, observation, policy)["status"], "hold")
        for field in ("sha256", "questions_sha256"):
            with self.subTest(policy=field):
                candidate, observation, policy = accepted_evidence()
                policy[field] = "0" * 64
                self.assertEqual(evaluate(candidate, observation, policy)["status"], "hold")
        for observation in ({}, None, []):
            with self.subTest(observation=observation):
                candidate, _, policy = accepted_evidence()
                self.assertEqual(evaluate(candidate, observation, policy)["status"], "hold")


if __name__ == "__main__":
    unittest.main()
