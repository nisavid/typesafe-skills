"""Judge sends complete bounded inputs and rejects ambiguous provider evidence."""
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from fork_sync.jev import judge


OPTIONS = ["no_additional_handling", "additional_handling", "insufficient_context"]


class JevTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name)
        self.git("init", "-q")
        self.git("config", "user.name", "Fixture")
        self.git("config", "user.email", "fixture@example.invalid")
        (self.repo / "README.md").write_text("Before\n")
        self.base = self.commit()
        (self.repo / "README.md").write_text("After\n")
        self.upstream = self.commit()
        self.questions = {"additional_handling": {"type": "choice", "instructions": "Assess obligations.",
                                                  "criteria": dict.fromkeys(OPTIONS, "Public criterion.")}}
        self.policy = {"jev_questions": self.questions, "jev_model": "jev-1.13.0",
                       "jev_min_probability": 0.96, "fork_obligations": ["Preserve public upstream content."]}
        question_bytes = (json.dumps(self.questions, indent=2, ensure_ascii=False) + "\n").encode()
        self.candidate = {"base": self.base, "upstream": self.upstream, "head": self.upstream,
                          "tree": self.git("rev-parse", "HEAD^{tree}"), "policy_sha256": "a" * 64,
                          "questions_sha256": hashlib.sha256(question_bytes).hexdigest()}
        probabilities = dict(zip(OPTIONS, [0.98, 0.01, 0.01]))
        self.response = {"answers": [{"id": "additional_handling", "type": "choice", "answer": OPTIONS[0], "confidence": 0.98, "band": "act"}],
                         "distributions": {"additional_handling": [{"option": key, "p": value} for key, value in probabilities.items()]},
                         "raw": [{"model": "jev-1.13.0", "cached": False,
                                  "answers": {"additional_handling": {"type": "choice", "choice": OPTIONS[0], "confidence": 0.98, "probabilities": probabilities}}}]}
        self.calls = []
        self.real_run = subprocess.run

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.repo), *args], stderr=subprocess.PIPE).decode().strip()

    def commit(self):
        self.git("add", "-A")
        self.git("commit", "-qm", "fixture")
        return self.git("rev-parse", "HEAD")

    def fake_run(self, command, **kwargs):
        if command[0] != "jev-axi":
            return self.real_run(command, **kwargs)
        state_path = Path(command[command.index("--state") + 1])
        questions_path = Path(command[command.index("--questions") + 1])
        self.calls.append({"command": command, "kwargs": kwargs, "state": state_path.read_bytes(),
                           "questions": questions_path.read_bytes(), "mode": state_path.stat().st_mode & 0o777,
                           "path": state_path})
        return subprocess.CompletedProcess(command, 0, json.dumps(self.response).encode(), b"")

    def run_judge(self):
        with patch.dict(os.environ, {"TYPESAFE_API_KEY": "test-secret"}), patch("subprocess.run", side_effect=self.fake_run):
            return judge(self.repo, self.candidate, self.policy)

    def test_observed_response_binds_complete_state_and_candidate(self):
        result = self.run_judge()
        self.assertEqual(result["answer"], "no_additional_handling", result)
        self.assertEqual(result["binding"], self.candidate)
        self.assertEqual(result["probabilities"]["no_additional_handling"], 0.98)
        call = self.calls[0]
        self.assertIn(b"-Before", call["state"])
        self.assertIn(b"+After", call["state"])
        self.assertIn(b"Preserve public upstream content.", call["state"])
        self.assertEqual(result["state_sha256"], hashlib.sha256(call["state"]).hexdigest())
        self.assertEqual(result["state_sha256"], result["observed_state_sha256"])
        self.assertIn("--no-cache", call["command"])
        self.assertEqual(call["kwargs"]["timeout"], 75)
        self.assertEqual(call["mode"], 0o600)
        self.assertFalse(call["path"].exists())
        self.assertNotIn("test-secret", json.dumps(result))

    def test_oversized_complete_state_holds_without_api_call(self):
        (self.repo / "README.md").write_text("a" * 64001)
        self.candidate["upstream"] = self.commit()
        result = self.run_judge()
        self.assertEqual(result["status"], "hold", result)
        self.assertIn("state_too_large", result["reasons"])
        self.assertEqual(self.calls, [])

    def test_judgment_cli_receives_no_forge_or_runner_credentials(self):
        with patch.dict(os.environ, {'GH_TOKEN': 'forge-write-secret',
                                     'GH_READ_TOKEN': 'forge-read-secret',
                                     'ACTIONS_RUNTIME_TOKEN': 'runner-secret'}):
            self.assertEqual(self.run_judge()['answer'], 'no_additional_handling')
        environment = self.calls[0]['kwargs']['env']
        self.assertEqual(environment['TYPESAFE_API_KEY'], 'test-secret')
        self.assertFalse({'GH_TOKEN', 'GH_READ_TOKEN', 'ACTIONS_RUNTIME_TOKEN'} & environment.keys())

    def test_binary_changes_hold_without_api_call(self):
        (self.repo / "image.bin").write_bytes(b"\x00\xff\x00")
        self.candidate["upstream"] = self.commit()
        result = self.run_judge()
        self.assertEqual(result["status"], "hold", result)
        self.assertIn("binary_diff", result["reasons"])
        self.assertEqual(self.calls, [])

    def test_changed_question_hash_or_policy_holds_before_sending(self):
        original = copy.deepcopy(self.policy)
        for field, value in (("jev_model", "jev-latest"), ("jev_min_probability", 0.95),
                             ("jev_questions", {}), ("fork_obligations", "Not a list")):
            with self.subTest(field=field):
                self.policy = {**original, field: value}
                result = self.run_judge()
                self.assertEqual(result["status"], "hold", result)
        self.policy = original
        self.candidate["questions_sha256"] = "b" * 64
        self.assertEqual(self.run_judge()["status"], "hold")
        self.assertEqual(self.calls, [])

    def test_ambiguous_or_invalid_responses_hold(self):
        original = copy.deepcopy(self.response)
        variants = []
        for field, value in (("model", "jev-latest"), ("cached", True), ("cached", 0)):
            variant = copy.deepcopy(original)
            variant["raw"][0][field] = value
            variants.append(variant)
        duplicate = copy.deepcopy(original)
        duplicate["raw"].append(copy.deepcopy(duplicate["raw"][0]))
        variants.append(duplicate)
        extra = copy.deepcopy(original)
        extra["raw"][0]["answers"]["other_question"] = copy.deepcopy(extra["raw"][0]["answers"]["additional_handling"])
        variants.append(extra)
        mismatch = copy.deepcopy(original)
        mismatch["answers"][0]["answer"] = "additional_handling"
        variants.append(mismatch)
        for value in (True, float("nan"), -0.1, 1.1, 0.5, 10 ** 400):
            variant = copy.deepcopy(original)
            variant["raw"][0]["answers"]["additional_handling"]["probabilities"]["no_additional_handling"] = value
            variants.append(variant)
        for index, variant in enumerate(variants):
            with self.subTest(index=index):
                self.response = variant
                self.assertEqual(self.run_judge().get("status"), "hold")

    def test_missing_runtime_key_holds_without_invoking_cli(self):
        with patch.dict(os.environ, {}, clear=True), patch("subprocess.run", side_effect=self.fake_run):
            result = judge(self.repo, self.candidate, self.policy)
        self.assertEqual(result.get("status"), "hold")
        self.assertEqual(self.calls, [])

    def test_errors_hold_without_retry_or_secret_output(self):
        for failure in (subprocess.TimeoutExpired(["jev-axi"], 75, output=b"test-secret"),
                        subprocess.CalledProcessError(1, ["jev-axi"], stderr=b"test-secret"),
                        OSError("test-secret")):
            attempts = []
            def fail(command, **kwargs):
                if command[0] != "jev-axi":
                    return self.real_run(command, **kwargs)
                attempts.append(command)
                raise failure
            with self.subTest(failure=type(failure).__name__), patch.dict(os.environ, {"TYPESAFE_API_KEY": "test-secret"}), patch("subprocess.run", side_effect=fail):
                result = judge(self.repo, self.candidate, self.policy)
                self.assertEqual(result["status"], "hold")
                self.assertEqual(len(attempts), 1)
                self.assertNotIn("test-secret", json.dumps(result))

    def test_negative_judgment_is_preserved_for_gate(self):
        self.response["raw"][0]["answers"]["additional_handling"]["choice"] = OPTIONS[1]
        self.response["raw"][0]["answers"]["additional_handling"]["probabilities"] = dict(zip(OPTIONS, [0.01, 0.98, 0.01]))
        self.response["answers"][0]["answer"] = OPTIONS[1]
        self.response["distributions"]["additional_handling"] = [{"option": key, "p": value} for key, value in zip(OPTIONS, [0.01, 0.98, 0.01])]
        result = self.run_judge()
        self.assertEqual(result["answer"], "additional_handling")
        self.assertEqual(result["probabilities"]["no_additional_handling"], 0.01)

    def test_duplicate_json_keys_hold(self):
        def duplicate(command, **kwargs):
            result = self.fake_run(command, **kwargs)
            if command[0] == "jev-axi":
                result.stdout = result.stdout.replace(b'"cached": false', b'"cached": true, "cached": false')
            return result
        with patch.dict(os.environ, {"TYPESAFE_API_KEY": "test-secret"}), patch("subprocess.run", side_effect=duplicate):
            result = judge(self.repo, self.candidate, self.policy)
        self.assertEqual(result.get("status"), "hold")

    def test_diff_excludes_fork_changes_and_ignores_external_diff(self):
        self.git("checkout", "-q", "--detach", self.base)
        (self.repo / "AGENTS.md").write_text("Fork-only instruction\n")
        self.candidate["base"] = self.commit()
        marker = self.repo / "external-diff-ran"
        self.git("config", "diff.external", f"touch {marker}")
        result = self.run_judge()
        self.assertEqual(result["answer"], "no_additional_handling")
        state = json.loads(self.calls[0]["state"])
        self.assertNotIn("AGENTS.md", state["complete_upstream_diff"])
        self.assertEqual(state["upstream_merge_base"], self.base)
        self.assertFalse(marker.exists())


if __name__ == "__main__":
    unittest.main()
