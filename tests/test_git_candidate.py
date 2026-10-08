"""The public constructor preserves upstream bytes without changing a checkout."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from fork_sync.git_candidate import construct


class CandidateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name)
        self.git("init", "-q")
        # Keep detached maintenance from racing temporary-repository cleanup.
        self.git("config", "maintenance.auto", "false")
        self.git("config", "user.name", "Fixture Author")
        self.git("config", "user.email", "fixture@example.invalid")
        self.write("README.md", "Upstream one\n")
        self.anchor = self.commit("initial upstream")
        self.write("AGENTS.md", "Fork instructions\n")
        self.base = self.commit("fork additions")
        self.git("checkout", "-q", "--detach", self.anchor)
        self.write("README.md", "Upstream two\n")
        self.write("skills/demo.md", "New skill\n")
        self.upstream = self.commit("upstream update")
        self.git("checkout", "-q", "--detach", self.base)
        self.policy = {"owned_paths": ["AGENTS.md"], "upstream_anchor": self.anchor}

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.repo), *args], stderr=subprocess.PIPE).decode().strip()

    def write(self, path, text):
        target = self.repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)

    def commit(self, message):
        self.git("add", "-A")
        self.git("commit", "-qm", message)
        return self.git("rev-parse", "HEAD")

    def test_clean_update_preserves_bytes_parents_and_checkout(self):
        self.write("scratch.txt", "Untracked local work\n")
        self.write("README.md", "Uncommitted local edit\n")
        before = self.git("status", "--porcelain=v1")
        result = construct(self.repo, self.base, self.upstream, self.policy)
        self.assertEqual(result["status"], "candidate", result)
        self.assertEqual(result["changed_paths"], ["README.md", "skills/demo.md"])
        self.assertEqual(self.git("show", f'{result["head"]}:README.md'), "Upstream two")
        self.assertEqual(self.git("show", f'{result["head"]}:AGENTS.md'), "Fork instructions")
        self.assertEqual(self.git("show", "-s", "--format=%P", result["head"]), f"{self.base} {self.upstream}")
        self.assertEqual(self.git("rev-parse", "HEAD"), self.base)
        self.assertEqual(self.git("status", "--porcelain=v1"), before)
        self.assertEqual(construct(self.repo, self.base, self.upstream, self.policy)["head"], result["head"])

    def test_noop_requires_matching_upstream_bytes(self):
        result = construct(self.repo, self.base, self.anchor, self.policy)
        self.assertEqual(result["status"], "noop", result)
        self.write("README.md", "Fork changed upstream bytes\n")
        changed_base = self.commit("unapproved fork edit")
        held = construct(self.repo, changed_base, self.anchor, self.policy)
        self.assertEqual(held["status"], "hold", held)
        self.assertIn("upstream parity", " ".join(held["reasons"]))

    def test_new_history_with_unchanged_tree_is_a_candidate_until_incorporated(self):
        for history in ("empty", "reverted"):
            with self.subTest(history=history):
                self.git("checkout", "-q", "--detach", self.anchor)
                if history == "empty":
                    self.git("commit", "--allow-empty", "-qm", "history only")
                else:
                    self.write("README.md", "Temporary upstream change\n")
                    self.commit("change")
                    self.git("revert", "--no-edit", "HEAD")
                upstream = self.git("rev-parse", "HEAD")
                self.git("checkout", "-q", "--detach", self.base)
                result = construct(self.repo, self.base, upstream, self.policy)
                self.assertEqual(result["status"], "candidate", result)
                self.assertEqual(result["changed_paths"], [])
                self.assertEqual(result["tree"], self.git("rev-parse", self.base + "^{tree}"))
                self.assertEqual(self.git("show", "-s", "--format=%P", result["head"]), f"{self.base} {upstream}")
                self.assertEqual(construct(self.repo, result["head"], upstream, self.policy)["status"], "noop")
                self.assertEqual(self.git("rev-parse", "HEAD"), self.base)

    def test_upstream_claiming_fork_path_holds_even_with_identical_bytes(self):
        self.git("checkout", "-q", "--detach", self.upstream)
        self.write("AGENTS.md", "Fork instructions\n")
        upstream = self.commit("upstream claims instructions")
        result = construct(self.repo, self.base, upstream, self.policy)
        self.assertEqual(result["status"], "hold", result)
        self.assertIn("ownership collision", " ".join(result["reasons"]))

    def test_unapproved_extra_file_holds_on_updates_and_noops(self):
        self.write("local.py", "print('unapproved')\n")
        base = self.commit("unapproved addition")
        for upstream in (self.upstream, self.anchor):
            with self.subTest(upstream=upstream):
                result = construct(self.repo, base, upstream, self.policy)
                self.assertEqual(result["status"], "hold", result)
                self.assertIn("unapproved extra", " ".join(result["reasons"]))

    def test_conflict_holds_without_changing_the_checkout(self):
        self.write("README.md", "Conflicting fork edit\n")
        base = self.commit("fork diverges")
        result = construct(self.repo, base, self.upstream, self.policy)
        self.assertEqual(result["status"], "hold", result)
        self.assertIn("merge conflict", " ".join(result["reasons"]))
        self.assertEqual(self.git("rev-parse", "HEAD"), base)

    def test_only_pinned_commits_descended_from_anchor_are_accepted(self):
        cases = [
            ("HEAD", self.upstream, self.policy),
            (self.base, self.upstream, {**self.policy, "upstream_anchor": self.base}),
            (self.base, self.upstream, {**self.policy, "upstream_anchor": self.upstream}),
        ]
        for base, upstream, policy in cases:
            with self.subTest(base=base, anchor=policy["upstream_anchor"]):
                result = construct(self.repo, base, upstream, policy)
                self.assertEqual(result["status"], "hold", result)

    def test_symlink_and_submodule_entries_hold(self):
        for kind in ("symlink", "submodule"):
            with self.subTest(kind=kind):
                self.git("checkout", "-q", "--detach", self.upstream)
                if kind == "symlink":
                    (self.repo / "shortcut").symlink_to("README.md")
                    upstream = self.commit("upstream symlink")
                else:
                    self.git("update-index", "--add", "--cacheinfo", "160000", self.anchor, "dependency")
                    self.git("commit", "-qm", "upstream submodule")
                    upstream = self.git("rev-parse", "HEAD")
                result = construct(self.repo, self.base, upstream, self.policy)
                self.assertEqual(result["status"], "hold", result)
                self.assertIn("unsupported Git entry", " ".join(result["reasons"]))

    def test_unsafe_publication_paths_hold(self):
        for path in ("line\nbreak.md", "dash/-option.md", "odd[link].md"):
            with self.subTest(path=path):
                self.git("checkout", "-q", "--detach", self.upstream)
                self.write(path, "Unsafe path\n")
                upstream = self.commit("unsafe filename")
                result = construct(self.repo, self.base, upstream, self.policy)
                self.assertEqual(result["status"], "hold", result)
                self.assertIn("unsafe path", " ".join(result["reasons"]))

    def test_upstream_workflow_changes_require_handling(self):
        self.git("checkout", "-q", "--detach", self.upstream)
        self.write(".github/workflows/release.yml", "name: upstream release\n")
        upstream = self.commit("upstream workflow")
        result = construct(self.repo, self.base, upstream, self.policy)
        self.assertEqual(result["status"], "hold", result)
        self.assertIn("upstream workflow change", " ".join(result["reasons"]))

    def test_custom_merge_driver_never_executes(self):
        marker = self.repo / "driver-ran"
        self.git("config", "merge.probe.driver", f"touch {marker}; cp %B %A")
        self.write(".gitattributes", "README.md merge=probe\n")
        self.write("README.md", "A fork change triggers merging\n")
        base = self.commit("source selects custom merge driver")
        policy = {**self.policy, "owned_paths": ["AGENTS.md", ".gitattributes"]}
        result = construct(self.repo, base, self.upstream, policy)
        self.assertEqual(result["status"], "hold", result)
        self.assertIn("custom merge driver", " ".join(result["reasons"]))
        self.assertFalse(marker.exists())

    def test_repo_argument_is_not_redirected_by_environment(self):
        with patch.dict(os.environ, {"GIT_DIR": str(self.repo / "missing.git"),
                                     "GIT_OBJECT_DIRECTORY": str(self.repo / "missing-objects")}):
            result = construct(self.repo, self.base, self.upstream, self.policy)
        self.assertEqual(result["status"], "candidate", result)

    def test_deletion_and_binary_executable_are_preserved(self):
        self.git("checkout", "-q", "--detach", self.upstream)
        (self.repo / "README.md").unlink()
        payload = b"\x00\xff\x01\r\n"
        (self.repo / "program").write_bytes(payload)
        (self.repo / "program").chmod(0o755)
        upstream = self.commit("delete README and add binary executable")
        result = construct(self.repo, self.base, upstream, self.policy)
        self.assertEqual(result["status"], "candidate", result)
        self.assertEqual(result["changed_paths"], ["README.md", "program", "skills/demo.md"])
        self.assertEqual(self.git("ls-tree", result["head"], "README.md"), "")
        self.assertTrue(self.git("ls-tree", result["head"], "program").startswith("100755 blob "))
        data = subprocess.check_output(["git", "-C", str(self.repo), "show", f'{result["head"]}:program'])
        self.assertEqual(data, payload)

    def test_empty_directory_tree_is_not_silently_ignored(self):
        empty_tree = subprocess.check_output(["git", "-C", str(self.repo), "mktree"], input=b"").decode().strip()
        records = self.git("ls-tree", self.upstream).encode() + f"\n040000 tree {empty_tree}\tempty\n".encode()
        tree = subprocess.check_output(["git", "-C", str(self.repo), "mktree"], input=records).decode().strip()
        upstream = self.git("commit-tree", tree, "-p", self.upstream, "-m", "empty directory")
        result = construct(self.repo, self.base, upstream, self.policy)
        self.assertEqual(result["status"], "hold", result)
        self.assertIn("empty directory", " ".join(result["reasons"]))

    def test_hooks_filters_and_external_diff_are_not_executed(self):
        marker = self.repo / "extension-ran"
        self.write(".gitattributes", "README.md filter=probe diff=probe\n")
        base = self.commit("attribute declarations")
        self.git("config", "filter.probe.clean", f"touch {marker}; cat")
        self.git("config", "diff.probe.command", f"touch {marker}")
        self.git("config", "merge.renormalize", "true")
        hook = self.repo / ".git/hooks/commit-msg"
        hook.write_text(f"#!/bin/sh\ntouch {marker}\n")
        hook.chmod(0o755)
        policy = {**self.policy, "owned_paths": ["AGENTS.md", ".gitattributes"]}
        result = construct(self.repo, base, self.upstream, policy)
        self.assertEqual(result["status"], "candidate", result)
        self.assertFalse(marker.exists())


if __name__ == "__main__":
    unittest.main()
