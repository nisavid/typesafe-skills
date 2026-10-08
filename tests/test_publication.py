"""Publication behavior with hosted process and HTTP boundaries controlled."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fork_sync.publication import publish


class HostedWorld:
    """A GitHub/helper process boundary; local Git remains real."""
    def __init__(self, root, history_only=None):
        self.real_run = subprocess.run
        self.repo = root / "candidate"
        self.dependency = root / "provingkit"
        for directory in (self.repo, self.dependency):
            directory.mkdir()
            self.git(directory, "init", "-b", "main")
            self.git(directory, "config", "user.name", "Publication test")
            self.git(directory, "config", "user.email", "test@example.invalid")
        (self.repo / "README.md").write_text("old\n")
        self.git(self.repo, "add", "README.md")
        self.git(self.repo, "commit", "-m", "base")
        base = self.git(self.repo, "rev-parse", "HEAD")
        if history_only == "empty":
            self.git(self.repo, "commit", "--allow-empty", "-m", "upstream history")
        else:
            (self.repo / "README.md").write_text("new\n")
            self.git(self.repo, "commit", "-am", "upstream")
            if history_only == "reverted":
                self.git(self.repo, "revert", "--no-edit", "HEAD")
        head = self.git(self.repo, "rev-parse", "HEAD")
        self.git(self.repo, "remote", "add", "origin", "https://github.com/nisavid/typesafe-skills.git")
        (self.dependency / "dependency").write_text("pinned helper boundary fixture\n")
        self.git(self.dependency, "add", "dependency")
        self.git(self.dependency, "commit", "-m", "helpers")
        self.policy = {"repository": "nisavid/typesafe-skills", "target_branch": "main",
                       "candidate_prefix": "nisavid/upstream-sync/",
                       "publication_categories": {"README.md": "DOC"},
                       "provingkit_pin": self.git(self.dependency, "rev-parse", "HEAD")}
        self.candidate = {"base": base, "upstream": head, "head": head,
                          "tree": self.git(self.repo, "rev-parse", "HEAD^{tree}"),
                          "changed_paths": [] if history_only else ["README.md"]}
        self.branch = "nisavid/upstream-sync/" + head[:12] + "-" + base[:12]
        self.remote_sha = None
        self.pr = None
        self.writes = []
        self.break_render = False

    def git(self, directory, *arguments):
        return self.real_run(["git", "-C", str(directory), *arguments], check=True,
                             capture_output=True, text=True).stdout.strip()

    def run(self, args, **kwargs):
        args = [str(arg) for arg in args]
        def output(value, code=0):
            return subprocess.CompletedProcess(args, code, value if isinstance(value, str) else json.dumps(value), "")
        def arg(flag):
            return args[args.index(flag) + 1]
        if args[0] == "git":
            if "ls-remote" in args:
                ref = args[-1]
                sha = self.candidate["base"] if ref == "refs/heads/main" else self.remote_sha
                return output(f"{sha}\t{ref}\n" if sha else "")
            return self.real_run(args, **kwargs)
        if args[0] == "gh":
            if args[1:3] == ["pr", "list"]:
                return output([self.pr] if self.pr else [])
            if args[1:3] == ["pr", "view"]:
                return output(self.pr)
            raise AssertionError("Unexpected direct GitHub command: " + repr(args))
        if "-c" in args:
            if "observe_git_diff" in args[args.index("-c") + 1]:
                return output([{"source_path": None, "target_path": "README.md", "operation": "modified",
                                "additions": 1, "deletions": 1, "binary": False}])
            if "authored_body" in args[args.index("-c") + 1]:
                return output(self.pr["body"])
        helper = Path(args[1]).name
        if helper == "plan_git_publication.py":
            request = json.loads(Path(arg("--request")).read_text())
            ref = "refs/heads/" + self.branch
            return output({"status": "ready", "request": request, "source_sha": self.candidate["head"],
                           "destination": {"remote": "origin", "ref": ref, "default_branch_ref": "refs/heads/main"},
                           "target": {"present": False, "sha": None}, "target_only_shas": [],
                           "rewrite_required": False,
                           "push": {"source_sha": self.candidate["head"], "ref": ref,
                                    "refspec": self.candidate["head"] + ":" + ref,
                                    "expected_target": {"present": False, "sha": None},
                                    "lease": "--force-with-lease=" + ref + ":"}})
        if helper == "execute_git_publication.py":
            self.writes.append("branch")
            self.remote_sha = self.candidate["head"]
            return output({"status": "verified"})
        if helper == "create_reviewable_pr.py":
            self.writes.append("create")
            body = Path(arg("--body-template")).read_text().replace("__PUBLISHING_REVIEWABLE_PRS_PR_NUMBER__", "42")
            self.pr = {"number": 42, "url": "https://github.com/nisavid/typesafe-skills/pull/42",
                       "title": arg("--title"), "body": body, "baseRefName": "main",
                       "baseRefOid": self.candidate["base"], "headRefName": self.branch,
                       "headRefOid": self.candidate["head"], "headRepository": {"name": "typesafe-skills", "nameWithOwner": "nisavid/typesafe-skills"},
                       "headRepositoryOwner": {"login": "nisavid"}, "state": "OPEN", "isDraft": True}
            return output({"status": "verified", "pr": 42, "url": self.pr["url"]})
        if helper == "update_reviewable_pr.py":
            self.writes.append("ready")
            self.pr["isDraft"] = False
            return output({"status": "verified"})
        if helper == "audit_reviewable_pr.py":
            return output({"status": "reconciled-unreceipted" if args[2] == "reconcile" else "verified"})
        if helper == "validate_change_navigation.py":
            return output("validated")
        raise AssertionError("Unexpected helper command: " + repr(args))

    def http(self, request, **kwargs):
        import hashlib
        anchor = "diff-" + hashlib.sha256(b"README.md").hexdigest()
        if request.full_url.endswith("/commits"):
            commits = self.git(self.repo, "rev-list", self.candidate["base"] + ".." + self.candidate["head"]).splitlines()
            html = "".join(f'<a href="{self.pr["url"]}/commits/{commit}">Commit</a>' for commit in commits)
        elif request.full_url.endswith("/files"):
            html = f'<div id="{anchor}"></div>'
        else:
            html = '<div class="markdown-body"><details><summary><img alt="DIFF"></summary>'
            if self.candidate["changed_paths"]:
                html += f'<a href="{self.pr["url"]}/files#{anchor}"><code>README.md</code></a></details>'
            else:
                comparison = f'https://github.com/nisavid/typesafe-skills/compare/{self.candidate["base"]}...{self.candidate["head"]}'
                html += f'<a href="{self.pr["url"]}/commits">Review the commits</a><a href="{comparison}">View history</a></details>'
            html += self.candidate["head"] + ' ' + self.candidate["base"] + '</div>'
        if self.break_render:
            html = '<html><body>Sign in to GitHub</body></html>'
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def geturl(self): return request.full_url
            def read(self, limit): return html.encode()[:limit]
        return Response()

    def publish(self):
        with patch("subprocess.run", side_effect=self.run), patch("urllib.request.urlopen", side_effect=self.http):
            return publish(self.repo, self.candidate, self.policy, self.dependency)


class PublicationTests(unittest.TestCase):
    def setUp(self):
        environment = patch.dict(os.environ, {"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
                                             "GIT_AUTHOR_DATE": "2001-01-04T00:00:00+0000",
                                             "GIT_COMMITTER_DATE": "2001-01-04T00:00:00+0000"})
        environment.start()
        self.addCleanup(environment.stop)

    def test_invalid_dependency_pin_holds_without_publication(self):
        with tempfile.TemporaryDirectory() as temporary:
            result = publish(Path(temporary), {}, {
                "repository": "nisavid/typesafe-skills",
                "target_branch": "main",
                "candidate_prefix": "nisavid/upstream-sync/",
                "provingkit_pin": "main",
            }, Path(temporary))
        self.assertEqual(result["status"], "hold")
        self.assertEqual(result["reason"], "invalid_publication_input")

    def test_candidate_is_published_ready_with_checked_live_navigation(self):
        with tempfile.TemporaryDirectory() as temporary:
            world = HostedWorld(Path(temporary))
            result = world.publish()
            self.assertEqual(result["status"], "published", result)
            self.assertEqual(result["url"], "https://github.com/nisavid/typesafe-skills/pull/42")
            self.assertFalse(world.pr["isDraft"])
            self.assertEqual(result["evidence"]["rendering"], "live_structure_and_anchors_verified")

    def test_controller_checkout_stays_at_base_while_publishing_candidate_objects(self):
        with tempfile.TemporaryDirectory() as temporary:
            world = HostedWorld(Path(temporary))
            world.git(world.repo, "checkout", "--detach", world.candidate["base"])
            result = world.publish()
            self.assertEqual(result["status"], "published", result)
            self.assertEqual(world.git(world.repo, "rev-parse", "HEAD"), world.candidate["base"])
            self.assertEqual((world.repo / "README.md").read_text(), "old\n")

    def test_candidate_data_checkout_does_not_copy_or_run_controller_hooks(self):
        with tempfile.TemporaryDirectory() as temporary:
            world = HostedWorld(Path(temporary))
            world.git(world.repo, "checkout", "--detach", world.candidate["base"])
            marker = Path(temporary) / "hook-ran"
            hook = world.repo / ".git/hooks/post-checkout"
            hook.write_text("#!/bin/sh\ntouch '" + str(marker) + "'\n")
            hook.chmod(0o700)
            result = world.publish()
            self.assertEqual(result["status"], "published", result)
            self.assertFalse(marker.exists())

    def test_configured_filter_holds_before_materializing_or_inspecting_worktree(self):
        with tempfile.TemporaryDirectory() as temporary:
            world = HostedWorld(Path(temporary))
            marker = Path(temporary) / "filter-ran"
            world.git(world.repo, "config", "filter.untrusted.clean", "touch '" + str(marker) + "'")
            world.git(world.repo, "config", "filter.untrusted.smudge", "touch '" + str(marker) + "'")
            (world.repo / ".git/info/attributes").write_text("* filter=untrusted\n")
            result = world.publish()
            self.assertEqual(result["reason"], "publication_git_configuration_requires_isolation")
            self.assertFalse(marker.exists())
            self.assertEqual(world.writes, [])

    def test_render_failure_keeps_the_created_pr_draft(self):
        with tempfile.TemporaryDirectory() as temporary:
            world = HostedWorld(Path(temporary))
            world.break_render = True
            result = world.publish()
            self.assertEqual(result["status"], "hold", result)
            self.assertEqual(result["reason"], "live_rendering_or_anchors_unverified")
            self.assertTrue(world.pr["isDraft"])

    def test_ambiguous_create_outcome_stops_without_readiness_or_retry(self):
        with tempfile.TemporaryDirectory() as temporary:
            world = HostedWorld(Path(temporary))
            def process(args, **kwargs):
                result = world.run(args, **kwargs)
                if Path(str(args[1])).name == "create_reviewable_pr.py":
                    raise subprocess.TimeoutExpired(args, 90)
                return result
            with patch("subprocess.run", side_effect=process), patch("urllib.request.urlopen", side_effect=world.http):
                result = publish(world.repo, world.candidate, world.policy, world.dependency)
            self.assertEqual(result["reason"], "publication_command_outcome_unknown")
            self.assertEqual(world.writes, ["branch", "create"])
            self.assertTrue(world.pr["isDraft"])

    def test_exact_existing_candidate_is_reused_without_new_forge_writes(self):
        with tempfile.TemporaryDirectory() as temporary:
            world = HostedWorld(Path(temporary))
            self.assertEqual(world.publish()["status"], "published")
            world.writes.clear()
            resumed = world.publish()
            self.assertEqual(resumed["status"], "published", resumed)
            self.assertEqual(world.writes, [])
            self.assertEqual(resumed["evidence"]["provenance"], "reconciled-unreceipted")

    def test_foreign_commit_on_candidate_branch_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as temporary:
            world = HostedWorld(Path(temporary))
            world.remote_sha = "a" * 40
            result = world.publish()
            self.assertEqual(result["reason"], "candidate_branch_collision")
            self.assertEqual(world.writes, [])

    def test_unclassified_upstream_path_holds_before_publication(self):
        with tempfile.TemporaryDirectory() as temporary:
            world = HostedWorld(Path(temporary))
            world.policy["publication_categories"] = {}
            result = world.publish()
            self.assertEqual(result["reason"], "publication_path_category_unestablished")
            self.assertEqual(world.writes, [])

    def test_human_edited_pr_body_is_preserved_and_held(self):
        with tempfile.TemporaryDirectory() as temporary:
            world = HostedWorld(Path(temporary))
            self.assertEqual(world.publish()["status"], "published")
            world.pr["body"] += "\n\nI need to preserve this operator note."
            world.writes.clear()
            result = world.publish()
            self.assertEqual(result["reason"], "existing_pr_text_drift")
            self.assertEqual(world.writes, [])

    def test_missing_live_file_anchor_holds_instead_of_claiming_verified_rendering(self):
        with tempfile.TemporaryDirectory() as temporary:
            world = HostedWorld(Path(temporary))
            original = world.http
            def response(request, **kwargs):
                if request.full_url.endswith("/files"):
                    world.break_render = True
                return original(request, **kwargs)
            with patch("subprocess.run", side_effect=world.run), patch("urllib.request.urlopen", side_effect=response):
                result = publish(world.repo, world.candidate, world.policy, world.dependency)
            self.assertEqual(result["status"], "hold")
            self.assertTrue(world.pr["isDraft"])

    @unittest.skipUnless(os.environ.get("PROVINGKIT_TEST_ROOT"), "set PROVINGKIT_TEST_ROOT for the actual pinned helper contract")
    def test_new_and_resumed_candidates_validate_with_the_actual_writer(self):
        writer = Path(os.environ["PROVINGKIT_TEST_ROOT"]) / "plugins/mergecraft/skills/writing-reviewable-pr-descriptions/scripts"
        with tempfile.TemporaryDirectory() as temporary:
            world = HostedWorld(Path(temporary))
            def process(args, **kwargs):
                args = list(map(str, args))
                if Path(args[1]).name == "validate_change_navigation.py":
                    args[1] = str(writer / "validate_change_navigation.py")
                    return world.real_run([args[0], "-B", *args[1:]], **kwargs)
                if "-c" in args and any(name in args[args.index("-c") + 1] for name in ("observe_git_diff", "authored_body")):
                    args[args.index("-c") + 2] = str(writer)
                    return world.real_run([args[0], "-B", *args[1:]], **kwargs)
                return world.run(args, **kwargs)
            with patch("subprocess.run", side_effect=process), patch("urllib.request.urlopen", side_effect=world.http):
                for _ in range(2):
                    result = publish(world.repo, world.candidate, world.policy, world.dependency)
                    self.assertEqual(result["status"], "published", result)

    @unittest.skipUnless(os.environ.get("PROVINGKIT_TEST_ROOT"), "set PROVINGKIT_TEST_ROOT for the actual pinned helper contract")
    def test_actual_publisher_creation_readiness_and_reconciliation(self):
        self._assert_actual_publication()

    @unittest.skipUnless(os.environ.get("PROVINGKIT_TEST_ROOT"), "set PROVINGKIT_TEST_ROOT for the actual pinned helper contract")
    def test_ancestry_only_updates_publish_and_resume_without_invented_file_changes(self):
        for history in ("empty", "reverted"):
            with self.subTest(history=history):
                self._assert_actual_publication(history)

    @unittest.skipUnless(os.environ.get("PROVINGKIT_TEST_ROOT"), "set PROVINGKIT_TEST_ROOT for the actual pinned helper contract")
    def test_missing_rendered_history_keeps_the_published_pr_draft(self):
        self._assert_actual_publication("empty", missing_history=True)

    def _assert_actual_publication(self, history_only=None, missing_history=False):
        dependency = Path(os.environ["PROVINGKIT_TEST_ROOT"])
        writer = dependency / "plugins/mergecraft/skills/writing-reviewable-pr-descriptions/scripts"
        publisher = dependency / "plugins/mergecraft/skills/publishing-reviewable-prs/scripts"
        versionkeeping = dependency / "plugins/versionkeeping/skills/checkpointing-and-publishing-git-work/scripts"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            world = HostedWorld(root, history_only=history_only)
            if history_only == "reverted":
                # Keep this fixture sensitive to the planner's set normalization.
                commits = world.git(world.repo, "rev-list", world.candidate["base"] + ".." + world.candidate["upstream"]).splitlines()
                self.assertNotEqual(commits, sorted(commits))
            world.git(world.repo, "checkout", "--detach", world.candidate["base"])
            remote = root / "remote.git"
            world.real_run(["git", "init", "--bare", "-b", "main", str(remote)], check=True, capture_output=True)
            world.real_run(["git", "--git-dir", str(remote), "fetch", str(world.repo),
                            world.candidate["base"] + ":refs/heads/main"], check=True, capture_output=True)
            state = root / "forge.json"
            state.write_text(json.dumps({"pr": None, "base": world.candidate["base"], "head": world.candidate["head"]}))
            executable = root / "gh"
            executable.write_text('''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
p=Path(os.environ["FAKE_FORGE_STATE"]); state=json.loads(p.read_text()); args=sys.argv[1:]
def arg(flag): return args[args.index(flag)+1]
if args[:1]==["-R"]: args=args[2:]
if args[:2]==["pr","view"]: print(json.dumps(state["pr"]))
elif args[:2]==["pr","list"]: print(json.dumps([state["pr"]] if state["pr"] else []))
elif args[:1]==["api"] and any(a.endswith("/pulls") for a in args):
    print(json.dumps([[{"number":42}] if state["pr"] else []]))
elif args[:2]==["pr","create"]:
    state["pr"]={"number":42,"url":"https://github.com/nisavid/typesafe-skills/pull/42",
      "title":arg("--title"),"body":Path(arg("--body-file")).read_text(),"baseRefName":arg("--base"),
      "baseRefOid":state["base"],"headRefName":arg("--head").split(":",1)[1],"headRefOid":state["head"],
      "headRepository":{"name":"typesafe-skills","nameWithOwner":"nisavid/typesafe-skills"},"headRepositoryOwner":{"login":"nisavid"},"state":"OPEN","isDraft":True}
    print(state["pr"]["url"])
elif args[:2]==["pr","edit"]:
    state["pr"]["title"]=arg("--title"); state["pr"]["body"]=Path(arg("--body-file")).read_text()
elif args[:2]==["pr","ready"]: state["pr"]["isDraft"]=False
else: raise SystemExit("Unexpected fake gh operation: "+repr(args))
p.write_text(json.dumps(state))
''')
            executable.chmod(0o700)
            def process(args, **kwargs):
                args = list(map(str, args))
                if args[0] == "gh":
                    args[0] = str(executable)
                elif Path(args[1]).name in {"create_reviewable_pr.py", "update_reviewable_pr.py", "audit_reviewable_pr.py"}:
                    args[1] = str(publisher / Path(args[1]).name)
                elif Path(args[1]).name == "validate_change_navigation.py":
                    args[1] = str(writer / Path(args[1]).name)
                elif Path(args[1]).name in {"plan_git_publication.py", "execute_git_publication.py"}:
                    # Substitute only the transport endpoint: both real helpers
                    # operate on a disposable local bare remote, with no network.
                    data_repo = args[args.index("--repo") + 1]
                    world.git(data_repo, "remote", "set-url", "origin", str(remote))
                    args[1] = str(versionkeeping / Path(args[1]).name)
                elif "-c" in args and any(name in args[args.index("-c")+1] for name in ("observe_git_diff", "observe_git_history", "authored_body")):
                    args[args.index("-c")+2] = str(writer)
                else:
                    return world.run(args, **kwargs)
                # Isolated Python ignores PYTHONDONTWRITEBYTECODE; keep the
                # shared pinned helper fixture free of generated cache files.
                executed = [args[0], "-B", *args[1:]] if args[0] == sys.executable else args
                result = world.real_run(executed, **kwargs)
                world.pr = json.loads(state.read_text())["pr"]
                if Path(args[1]).name == "execute_git_publication.py" and not result.returncode:
                    world.remote_sha = world.real_run(["git", "--git-dir", str(remote), "rev-parse",
                                                      "refs/heads/" + world.branch], check=True,
                                                     capture_output=True, text=True).stdout.strip()
                if Path(args[1]).name == "plan_git_publication.py" and not result.returncode:
                    self.assertEqual(json.loads(result.stdout)["status"], "ready", result.stdout)
                if result.returncode:
                    raise AssertionError("Real helper failed: " + result.stdout + result.stderr)
                return result
            environment = {"PATH": str(root) + os.pathsep + os.environ["PATH"], "FAKE_FORGE_STATE": str(state)}
            def page(request, **kwargs):
                if missing_history and request.full_url.endswith("/commits"):
                    world.break_render = True
                return world.http(request, **kwargs)
            with patch.dict(os.environ, environment), patch("subprocess.run", side_effect=process), patch("urllib.request.urlopen", side_effect=page):
                first = publish(world.repo, world.candidate, world.policy, world.dependency)
                if missing_history:
                    self.assertEqual(first["status"], "hold", first)
                    self.assertEqual(first["reason"], "live_history_navigation_unverified")
                    self.assertTrue(world.pr["isDraft"])
                    return
                self.assertEqual(first["status"], "published", first)
                if history_only:
                    self.assertEqual(world.git(world.repo, "diff", world.candidate["base"], world.candidate["head"]), "")
                    self.assertNotEqual(world.candidate["base"], world.candidate["head"])
                    self.assertIn("No file changes", world.pr["body"])
                    self.assertIn("/pull/42/commits", world.pr["body"])
                    self.assertNotIn("/files#diff-", world.pr["body"])
                self.assertFalse(world.pr["isDraft"])
                self.assertEqual(world.git(world.repo, "rev-parse", "HEAD"), world.candidate["base"])
                self.assertEqual((world.repo / "README.md").read_text(), "old\n")
                second = publish(world.repo, world.candidate, world.policy, world.dependency)
                self.assertEqual(second["status"], "published", second)
                self.assertEqual(second["evidence"]["provenance"], "reconciled-unreceipted")


if __name__ == "__main__":
    unittest.main()
