"""Judge sends complete bounded inputs and rejects ambiguous provider evidence."""
import copy
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from fork_sync.jev import judge
from fork_sync.gates import evaluate


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
        if command[0] != "node":
            return self.real_run(command, **kwargs)
        questions_path = Path(command[3])
        state_path = Path(command[4])
        self.calls.append({"command": command, "kwargs": kwargs, "state": state_path.read_bytes(),
                           "questions": questions_path.read_bytes(), "mode": state_path.stat().st_mode & 0o777,
                           "path": state_path})
        return subprocess.CompletedProcess(command, 0, json.dumps(self.response).encode(), b"")

    def run_judge(self):
        with patch.dict(os.environ, {"TYPESAFE_API_KEY": "test-secret"}), patch("subprocess.run", side_effect=self.fake_run):
            return judge(self.repo, self.candidate, self.policy)

    def controlled_transport(self, scenario):
        """Run the production adapter and locked SDK with only HTTP and time controlled."""
        cli = shutil.which("jev-axi")
        node = shutil.which("node")
        self.assertIsNotNone(cli, "Install tools/jev's locked dependencies and put their .bin on PATH")
        self.assertIsNotNone(node, "Node is required for the locked Jev transport tests")
        package = Path(cli).resolve().parents[2]
        self.assertEqual(json.loads((package / "package.json").read_text())["version"], "0.7.2")
        transport_directory = tempfile.TemporaryDirectory(prefix="transport-", dir=self.repo)
        self.addCleanup(transport_directory.cleanup)
        transport = Path(transport_directory.name)
        (transport / "scenario.json").write_text(json.dumps(scenario))
        log = transport / "requests.jsonl"
        preload = transport / "fetch.mjs"
        preload.write_text("""
import { appendFileSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { configureFetch } from CLIENT;
const scenario = JSON.parse(readFileSync(SCENARIO, 'utf8'));
if (scenario.cached) {
  const questions = JSON.parse(readFileSync(process.argv[3], 'utf8'));
  const state = JSON.parse(readFileSync(process.argv[4], 'utf8'));
  const key = createHash('sha256').update(JSON.stringify({ model: process.argv[5], state, questions })).digest('hex');
  const cache = process.env.XDG_CACHE_HOME + '/jev-axi';
  mkdirSync(cache, { recursive: true });
  writeFileSync(cache + '/' + key + '.json', JSON.stringify({ ...scenario.cached, created: Date.now() }));
}
const originalTimeout = globalThis.setTimeout;
// Exercise the SDK's real abort timer without waiting its production 60 seconds.
globalThis.setTimeout = (fn, ms, ...args) => originalTimeout(fn, ms === 60000 ? 5 : ms, ...args);
configureFetch(async (url, init) => {
  appendFileSync(LOG, JSON.stringify({ url, body: JSON.parse(init.body) }) + '\\n');
  if (scenario.kind === 'network') throw new TypeError('test-secret connection failure');
  if (scenario.kind === 'timeout-before-response') {
    return await new Promise((_, reject) => init.signal.addEventListener('abort',
      () => reject(new DOMException('test-secret', 'AbortError')), { once: true }));
  }
  if (scenario.kind === 'timeout-after-response') {
    return new Response(new ReadableStream({ start(controller) {
      controller.enqueue(new TextEncoder().encode('{"model":"jev-1.13.0",'));
      init.signal.addEventListener('abort', () => controller.error(new DOMException('test-secret', 'AbortError')),
        { once: true });
    }}), { status: 200, headers: { 'content-type': 'application/json' } });
  }
  return new Response(JSON.stringify(scenario.body ?? { error: 'test-secret controlled failure' }), {
    status: scenario.status, headers: { 'content-type': 'application/json', 'retry-after-ms': '0' }
  });
});
""".replace("CLIENT", json.dumps((package / "dist/src/client.js").as_uri()))
            .replace("SCENARIO", json.dumps(str(transport / "scenario.json")))
            .replace("LOG", json.dumps(str(log))))
        shim = transport / "node"
        shim.write_text(f"#!/bin/sh\nexec {shlex.quote(node)} --import {shlex.quote(str(preload))} \"$@\"\n")
        shim.chmod(0o700)
        home = transport / "home"
        home.mkdir()
        environment = {"PATH": str(transport) + os.pathsep + os.environ["PATH"],
                       "HOME": str(home), "XDG_CACHE_HOME": str(home / "cache"),
                       "TYPESAFE_API_KEY": "test-secret"}
        with patch.dict(os.environ, environment, clear=True):
            result = judge(self.repo, self.candidate, self.policy)
        requests = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
        return result, requests

    def test_transport_503_holds_after_one_request(self):
        result, requests = self.controlled_transport({"status": 503})
        self.assertEqual(result, {"status": "hold", "reasons": ["jev_input_or_transport_error"]})
        self.assertEqual(len(requests), 1)
        self.assertNotIn("test-secret", json.dumps(result))

    def test_transport_preserves_choice_confidence_precision(self):
        probabilities = dict(zip(OPTIONS, [0.968, 0.02, 0.012]))
        result, requests = self.controlled_transport({"status": 200, "body": {
            "model": "jev-1.13.0", "usage": {"input_tokens": 100, "output_tokens": 10},
            "answers": {"additional_handling": {"type": "choice", "choice": OPTIONS[0],
                "confidence": 0.968, "probabilities": probabilities}}}})
        self.assertEqual(result.get("answer"), "no_additional_handling", result)
        self.assertEqual(result["probabilities"], probabilities)
        self.assertEqual(len(requests), 1)

    def test_transport_preserves_probability_precision(self):
        probabilities = dict(zip(OPTIONS, [0.98, 0.0102, 0.0098]))
        result, requests = self.controlled_transport({"status": 200, "body": {
            "model": "jev-1.13.0", "usage": {"input_tokens": 100, "output_tokens": 10},
            "answers": {"additional_handling": {"type": "choice", "choice": OPTIONS[0],
                "confidence": 0.98, "probabilities": probabilities}}}})
        self.assertEqual(result.get("answer"), "no_additional_handling", result)
        self.assertEqual(result["probabilities"], probabilities)
        self.assertEqual(len(requests), 1)

    def test_gate_uses_unrounded_transport_probability_at_threshold(self):
        policy = {**self.policy, "sha256": self.candidate["policy_sha256"],
                  "questions_sha256": self.candidate["questions_sha256"],
                  "coderabbit_user_id": 136622811,
                  "required_checks": [{"name": "sync-ci", "app_id": 15368}]}
        observation = {
            "binding": self.candidate.copy(), "live_base": self.candidate["base"],
            "live_head": self.candidate["head"], "policy_sha256": policy["sha256"],
            "questions_sha256": policy["questions_sha256"], "mergeability": "clean",
            "unresolved_threads": 0, "protection": {"enforce_admins": True, "strict": True,
                "required_approving_review_count": 1, "dismiss_stale_reviews": True,
                "required_conversation_resolution": True,
                "review_bypass_allowances": {"users": [], "teams": [], "apps": []},
                "required_checks": policy["required_checks"]},
            "checks": [{"name": "sync-ci", "app_id": 15368, "head": self.candidate["head"],
                        "status": "completed", "conclusion": "success"}],
            "reviews": [{"id": 42, "user": "coderabbitai[bot]", "user_id": 136622811,
                         "state": "APPROVED", "commit_id": self.candidate["head"],
                         "submitted_at": "2026-10-07T20:00:00Z"}],
        }
        for values, expected in (([0.9599, 0.0201, 0.02], "hold"),
                                 ([0.96, 0.02, 0.02], "ready"),
                                 ([0.9601, 0.0199, 0.02], "ready")):
            with self.subTest(values=values):
                probabilities = dict(zip(OPTIONS, values))
                result, requests = self.controlled_transport({"status": 200, "body": {
                    "model": "jev-1.13.0", "usage": {"input_tokens": 100, "output_tokens": 10},
                    "answers": {"additional_handling": {"type": "choice", "choice": OPTIONS[0],
                        "confidence": values[0], "probabilities": probabilities}}}})
                self.assertEqual(result.get("answer"), "no_additional_handling", result)
                self.assertEqual(result["probabilities"], probabilities)
                self.assertEqual(evaluate(self.candidate, {**observation, "jev": result}, policy)["status"], expected)
                self.assertEqual(len(requests), 1)

    def test_malformed_raw_transport_evidence_holds_after_one_request(self):
        body = {"model": "jev-1.13.0", "usage": {"input_tokens": 100, "output_tokens": 10},
                "answers": self.response["raw"][0]["answers"]}
        variants = []
        for field, value in (("type", "text"), ("choice", "other_option"),
                             ("confidence", True), ("probabilities", {}),
                             ("probabilities", dict(zip(OPTIONS, [0.98, 0.01, 0.02]))),
                             ("probabilities", dict(zip(OPTIONS, [0.01, 0.98, 0.01])))):
            variant = copy.deepcopy(body)
            variant["answers"]["additional_handling"][field] = value
            variants.append(variant)
        variants.append({**body, "model": "jev-latest"})
        extra = copy.deepcopy(body)
        extra["answers"]["other_question"] = copy.deepcopy(extra["answers"]["additional_handling"])
        variants.append(extra)
        for index, variant in enumerate(variants):
            with self.subTest(index=index):
                result, requests = self.controlled_transport({"status": 200, "body": variant})
                self.assertEqual(result, {"status": "hold", "reasons": ["jev_input_or_transport_error"]})
                self.assertEqual(len(requests), 1)
                self.assertNotIn("test-secret", json.dumps(result))

    def test_transport_failures_and_timeouts_hold_without_another_request(self):
        scenarios = [{"kind": "network"}, {"kind": "timeout-before-response"},
                     {"kind": "timeout-after-response"}, {"status": 408}, {"status": 429},
                     {"status": 500}, {"status": 529}]
        for scenario in scenarios:
            with self.subTest(scenario=scenario):
                result, requests = self.controlled_transport(scenario)
                self.assertEqual(result, {"status": "hold", "reasons": ["jev_input_or_transport_error"]})
                self.assertEqual(len(requests), 1)
                self.assertNotIn("test-secret", json.dumps(result))

    def test_live_response_preserves_full_judgment_and_complete_inputs(self):
        raw = self.response["raw"][0]
        cached = {"model": raw["model"], "usage": {"input_tokens": 100, "output_tokens": 10},
                  "answers": {"additional_handling": {"type": "choice", "choice": OPTIONS[1],
                      "confidence": 0.98, "probabilities": dict(zip(OPTIONS, [0.01, 0.98, 0.01]))}}}
        result, requests = self.controlled_transport({"status": 200, "body": {
            "model": raw["model"], "answers": raw["answers"],
            "usage": {"input_tokens": 100, "output_tokens": 10}}, "cached": cached})
        self.assertEqual(result["answer"], "no_additional_handling", result)
        self.assertEqual(result["probabilities"], dict(zip(OPTIONS, [0.98, 0.01, 0.01])))
        self.assertIs(result["cached"], False)
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0]["body"]["questions"], self.questions)
        self.assertEqual(requests[0]["body"]["model"], "jev-1.13.0")
        state = requests[0]["body"]["state"]
        self.assertEqual(state["binding"], self.candidate)
        self.assertEqual(state["fork_obligations"], self.policy["fork_obligations"])
        self.assertIn("-Before", state["complete_upstream_diff"])
        self.assertIn("+After", state["complete_upstream_diff"])
        state_bytes = (json.dumps(state, indent=2, ensure_ascii=False) + "\n").encode()
        self.assertEqual(result["state_sha256"], hashlib.sha256(state_bytes).hexdigest())

    def test_negative_and_below_threshold_live_answers_are_not_resubmitted(self):
        for choice, probabilities in ((OPTIONS[1], [0.01, 0.98, 0.01]),
                                      (OPTIONS[0], [0.95, 0.03, 0.02])):
            with self.subTest(choice=choice, probabilities=probabilities):
                result, requests = self.controlled_transport({"status": 200, "body": {
                    "model": "jev-1.13.0", "usage": {"input_tokens": 100, "output_tokens": 10},
                    "answers": {"additional_handling": {"type": "choice", "choice": choice,
                        "confidence": max(probabilities), "probabilities": dict(zip(OPTIONS, probabilities))}}}})
                self.assertEqual(result["answer"], choice, result)
                self.assertEqual(result["probabilities"], dict(zip(OPTIONS, probabilities)))
                self.assertEqual(len(requests), 1)

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
        self.assertEqual(call["command"][5], "jev-1.13.0")
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
                                     'ACTIONS_RUNTIME_TOKEN': 'runner-secret',
                                     'NODE_OPTIONS': '--import untrusted-test-hook'}):
            self.assertEqual(self.run_judge()['answer'], 'no_additional_handling')
        environment = self.calls[0]['kwargs']['env']
        self.assertEqual(environment['TYPESAFE_API_KEY'], 'test-secret')
        self.assertFalse({'GH_TOKEN', 'GH_READ_TOKEN', 'ACTIONS_RUNTIME_TOKEN', 'NODE_OPTIONS'} & environment.keys())

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
        mismatch = copy.deepcopy(original)
        mismatch["answers"][0]["confidence"] = 0.97
        variants.append(mismatch)
        mismatch = copy.deepcopy(original)
        mismatch["distributions"]["additional_handling"][0]["p"] = 0.97
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
                if command[0] != "node":
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
            if command[0] == "node":
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
