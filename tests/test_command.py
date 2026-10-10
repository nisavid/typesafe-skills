"""Exercise the executable controller with disposable Git and a fake fetch service."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


class CommandTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / "controller"
        self.repo.mkdir()
        self.git_executable = shutil.which("git")
        self.git("init", "-q")
        self.git("config", "user.name", "Fixture")
        self.git("config", "user.email", "fixture@example.invalid")
        (self.repo / "README.md").write_text("Upstream content\n")
        self.anchor = self.commit()
        package = self.repo / "fork_sync"
        package.mkdir()
        for source in (Path(__file__).resolve().parents[1] / "fork_sync").glob("*.py"):
            shutil.copyfile(source, package / source.name)
        (self.repo / ".agents").mkdir()
        owned = sorted(str(path.relative_to(self.repo)) for path in package.glob("*.py")) + [".agents/fork-sync.json"]
        self.policy = {"repository": "nisavid/typesafe-skills", "upstream_url": "https://github.com/typesafe-ai/skills.git",
                       "upstream_branch": "main", "target_branch": "main", "validation_branch": "nisavid/upstream-sync-validation",
                       "upstream_anchor": self.anchor, "owned_paths": owned, "jev_questions": {}}
        (self.repo / ".agents/fork-sync.json").write_text(json.dumps(self.policy))
        self.head = self.commit()
        fake_bin = self.root / "bin"
        fake_bin.mkdir()
        runner = fake_bin / "git"
        runner.write_text("#!" + sys.executable + "\n" +
            "import json, os, subprocess, sys\n"
            "args = sys.argv[1:]\n"
            "if 'fetch' in args:\n"
            "    with open(os.environ['FETCH_LOG'], 'a') as f: f.write(json.dumps(args) + '\\n')\n"
            "    if os.environ.get('FETCH_FAIL'): sys.stderr.write('private-secret'); sys.exit(1)\n"
            "    destination = args[-1].split(':', 1)[1]\n"
            "    oid = os.environ['FIXTURE_UPSTREAM'] if 'typesafe-ai/skills.git' in args[-2] else os.environ['FIXTURE_BASE']\n"
            "    sys.exit(subprocess.call([os.environ['REAL_GIT'], '-C', args[args.index('-C') + 1], 'update-ref', destination, oid]))\n"
            "os.execv(os.environ['REAL_GIT'], [os.environ['REAL_GIT'], *args])\n")
        runner.chmod(0o755)
        self.log = self.root / "fetch.log"
        self.env = {**os.environ, "PATH": str(fake_bin) + os.pathsep + os.environ["PATH"],
                    "HOME": str(self.root), "XDG_CONFIG_HOME": str(self.root / "config"),
                    "PYTHONDONTWRITEBYTECODE": "1", "FORK_SYNC_MODE": "validation",
                    "FORK_SYNC_APPROVED_REVISION": self.head, "REAL_GIT": self.git_executable,
                    "FETCH_LOG": str(self.log), "FIXTURE_BASE": self.head, "FIXTURE_UPSTREAM": self.anchor}

    def git(self, *args):
        return subprocess.check_output([self.git_executable, "-C", str(self.repo), *args], stderr=subprocess.PIPE).decode().strip()

    def commit(self):
        self.git("add", "-A")
        self.git("commit", "-qm", "fixture")
        return self.git("rev-parse", "HEAD")

    def invoke(self, *extra, repo=None):
        result = subprocess.run([sys.executable, "-m", "fork_sync", "reconcile", "--repo", str(repo or self.repo),
                                 "--provingkit", str(self.root / "provingkit"), *extra],
                                cwd=self.repo, env=self.env, capture_output=True, timeout=30)
        self.assertNotIn("private-secret", result.stdout.decode() + result.stderr.decode())
        return result, json.loads(result.stdout)

    def test_disabled_mode_performs_no_repository_or_network_work(self):
        self.env.pop("FORK_SYNC_MODE")
        result, output = self.invoke(repo=self.root / "missing")
        self.assertEqual(output, {"status": "disabled"})
        self.assertEqual(result.returncode, 0)
        self.assertFalse(self.log.exists())

    def test_approved_clean_controller_fetches_pinned_inputs_and_verifies_noop(self):
        result, output = self.invoke()
        self.assertEqual(output["status"], "noop", output)
        self.assertEqual(result.returncode, 0)
        fetches = [json.loads(line) for line in self.log.read_text().splitlines()]
        self.assertEqual(len(fetches), 2)
        self.assertIn("https://github.com/nisavid/typesafe-skills.git", fetches[0])
        self.assertIn("refs/heads/nisavid/upstream-sync-validation", fetches[0][-1])
        self.assertIn("https://github.com/typesafe-ai/skills.git", fetches[1])
        self.assertEqual(output["base"], self.head)
        self.assertEqual(output["upstream"], self.anchor)

    def test_malformed_upstream_location_holds_before_fetch(self):
        self.policy["upstream_url"] = "ext::private-secret"
        (self.repo / ".agents/fork-sync.json").write_text(json.dumps(self.policy))
        self.env["FORK_SYNC_APPROVED_REVISION"] = self.commit()
        _, output = self.invoke()
        self.assertEqual(output["status"], "hold", output)
        self.assertFalse(self.log.exists())

    def test_owned_file_hidden_from_status_still_holds(self):
        path = "fork_sync/jev.py"
        self.git("update-index", "--assume-unchanged", path)
        with (self.repo / path).open("a") as stream:
            stream.write("\n# changed despite clean status\n")
        _, output = self.invoke()
        self.assertEqual(output["status"], "hold", output)
        self.assertFalse(self.log.exists())

    def test_url_rewriting_is_rejected_before_fetch(self):
        self.git("config", "url.https://elsewhere.invalid/.insteadOf", "https://github.com/")
        _, output = self.invoke()
        self.assertEqual(output["status"], "hold", output)
        self.assertFalse(self.log.exists())

    def test_evidence_directory_inside_controller_is_rejected(self):
        _, output = self.invoke("--evidence-dir", str(self.repo / "evidence"))
        self.assertEqual(output["status"], "hold", output)
        self.assertFalse(self.log.exists())

    def test_unapproved_revision_wrong_mode_and_other_checkout_do_not_fetch(self):
        original = self.env.copy()
        for changes in ({"FORK_SYNC_APPROVED_REVISION": "a" * 40},
                        {"FORK_SYNC_APPROVED_REVISION": ""}, {"FORK_SYNC_MODE": "unknown"}):
            self.env = {**original, **changes}
            _, output = self.invoke()
            self.assertEqual(output["status"], "hold", output)
            self.assertFalse(self.log.exists())
        self.env = original
        _, output = self.invoke(repo=self.root)
        self.assertEqual(output["status"], "hold", output)
        self.assertFalse(self.log.exists())

    def test_fetch_failure_is_redacted_and_not_retried(self):
        self.env["FETCH_FAIL"] = "1"
        _, output = self.invoke()
        self.assertEqual(output["status"], "hold", output)
        self.assertEqual(len(self.log.read_text().splitlines()), 1)

    def test_plan_command_still_constructs_without_activation(self):
        result = subprocess.run([sys.executable, "-m", "fork_sync", "plan", "--repo", str(self.repo),
                                 "--base", self.head, "--upstream", self.anchor,
                                 "--policy", str(self.repo / ".agents/fork-sync.json")],
                                cwd=self.repo, env=self.env, capture_output=True, timeout=30)
        self.assertEqual(json.loads(result.stdout)["status"], "noop")
        self.assertFalse(self.log.exists())

    def test_production_selects_main_without_rewriting_policy(self):
        self.env["FORK_SYNC_MODE"] = "production"
        before = (self.repo / ".agents/fork-sync.json").read_bytes()
        _, output = self.invoke("--phase", "finalize", "--evidence-dir", str(self.root / "evidence"))
        self.assertEqual(output["status"], "noop", output)
        fetches = [json.loads(line) for line in self.log.read_text().splitlines()]
        self.assertTrue(fetches[0][-1].startswith("+refs/heads/main:"))
        self.assertEqual((self.repo / ".agents/fork-sync.json").read_bytes(), before)

    def test_dirty_controller_holds_before_fetch(self):
        (self.repo / "untracked.txt").write_text("Local work\n")
        _, output = self.invoke()
        self.assertEqual(output["status"], "hold", output)
        self.assertFalse(self.log.exists())


if __name__ == "__main__":
    unittest.main()
