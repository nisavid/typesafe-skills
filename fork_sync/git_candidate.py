"""Construct an upstream merge using objects only, leaving refs and checkout alone."""
import os
from pathlib import Path
import re
import subprocess


class _Hold(Exception):
    pass


def construct(repo: Path, base: str, upstream: str, policy: dict) -> dict:
    """Return a candidate, a verified no-op, or a hold with actionable reasons."""
    try:
        return _construct(repo, base, upstream, policy)
    except _Hold as error:
        return {"status": "hold", "reasons": [str(error)]}
    except subprocess.CalledProcessError as error:
        reason = "merge conflict" if "merge-tree" in error.cmd and error.returncode == 1 else "Git operation failed"
        return {"status": "hold", "reasons": [reason]}
    except (OSError, subprocess.TimeoutExpired, ValueError, KeyError, TypeError):
        return {"status": "hold", "reasons": ["invalid input or unavailable Git objects"]}


def _construct(repo, base, upstream, policy):
    identity_variables = {"GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL"}
    env = {key: value for key, value in os.environ.items()
           if not key.startswith("GIT_") or key in identity_variables}
    env["GIT_NO_REPLACE_OBJECTS"] = "1"

    def git(*args, input=None):
        return subprocess.check_output(
            ["git", "-C", str(repo), "-c", "core.hooksPath=/dev/null",
             "-c", "commit.gpgSign=false", "-c", "core.attributesFile=/dev/null",
             "-c", "merge.renormalize=false", *args],
            input=input, env=env, stderr=subprocess.PIPE, timeout=60,
        )

    def entries(ref):
        result = {}
        directories = []
        for entry in git("ls-tree", "-rtz", "--full-tree", ref).split(b"\0"):
            if entry:
                metadata, path = entry.split(b"\t", 1)
                mode, kind, oid = metadata.split()
                try:
                    name = path.decode("utf-8", errors="strict")
                except UnicodeDecodeError:
                    raise _Hold("unsafe path encoding: " + repr(path)) from None
                safe_path(name)
                if mode == b"040000" and kind == b"tree":
                    directories.append(name)
                    continue
                if mode not in (b"100644", b"100755") or kind != b"blob":
                    raise _Hold("unsupported Git entry: " + repr(path))
                result[name] = metadata
        for directory in directories:
            if not any(path.startswith(directory + "/") for path in result):
                raise _Hold("unsupported empty directory tree: " + directory)
        return result

    def safe_path(path):
        if not isinstance(path, str) or any(
            not re.fullmatch(r"[A-Za-z0-9_.][A-Za-z0-9_.-]*", part)
            or part in (".", "..") or part.lower() == ".git"
            for part in path.split("/")
        ):
            raise _Hold("unsafe path: " + repr(path))

    anchor = policy["upstream_anchor"]
    if any(not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{40}", sha)
           for sha in (base, upstream, anchor)):
        return {"status": "hold", "reasons": ["full lowercase commit IDs required"]}
    for sha in (base, upstream, anchor):
        if git("cat-file", "-t", sha).strip() != b"commit":
            return {"status": "hold", "reasons": ["input object is not a commit"]}
    for sha in (base, upstream):
        try:
            git("merge-base", "--is-ancestor", anchor, sha)
        except subprocess.CalledProcessError:
            return {"status": "hold", "reasons": ["upstream anchor is not an ancestor of both inputs"]}
    upstream_entries = entries(upstream)
    base_entries = entries(base)
    owned = policy["owned_paths"]
    if not isinstance(owned, list) or not all(isinstance(path, str) for path in owned) or len(set(owned)) != len(owned):
        raise _Hold("owned_paths must be a list of distinct file paths")
    for path in owned:
        safe_path(path)
    for path in upstream_entries:
        if any(path == own or path.startswith(own + "/") or own.startswith(path + "/") for own in owned):
            return {"status": "hold", "reasons": [f"ownership collision: {path}"]}
    for path in upstream_entries.keys() | base_entries.keys():
        if path.startswith(".github/workflows/") and path not in owned and upstream_entries.get(path) != base_entries.get(path):
            raise _Hold(f"upstream workflow change requires handling: {path}")
    try:
        drivers = git("config", "--name-only", "--get-regexp", r"^merge\..*\.driver$")
    except subprocess.CalledProcessError as error:
        if error.returncode != 1:
            raise
        drivers = b""
    if drivers:
        raise _Hold("custom merge driver configured; use an isolated repository")
    tree = git("merge-tree", "--write-tree", base, upstream).splitlines()[0].decode()
    merged_entries = entries(tree)
    if any(merged_entries.get(path) != entry for path, entry in upstream_entries.items()):
        return {"status": "hold", "reasons": ["upstream parity mismatch"]}
    base_entries = entries(base)
    for path in merged_entries.keys() - upstream_entries.keys():
        if path not in owned:
            return {"status": "hold", "reasons": [f"unapproved extra: {path}"]}
    for path in owned:
        if merged_entries.get(path) != base_entries.get(path):
            return {"status": "hold", "reasons": [f"fork-owned file changed: {path}"]}
    if git("merge-base", base, upstream).strip().decode() == upstream:
        return {"status": "noop", "base": base, "upstream": upstream,
                "head": base, "tree": tree, "changed_paths": []}
    timestamp = max(int(git("show", "-s", "--format=%ct", sha)) for sha in (base, upstream)) + 1
    env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = f"@{timestamp} +0000"
    head = git("commit-tree", tree, "-p", base, "-p", upstream,
               input=f"chore(sync): merge upstream {upstream}\n".encode()).strip().decode()
    changed = git("diff-tree", "--no-commit-id", "--name-only", "-r", "-z", base, head)
    return {"status": "candidate", "base": base, "upstream": upstream,
            "head": head, "tree": tree,
            "changed_paths": sorted(p.decode() for p in changed.split(b"\0") if p)}
