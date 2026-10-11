"""Publish immutable sync candidates through Versionkeeping and Mergecraft.

Only this adapter's reviewed template is authored automatically. Existing PR
text and branch commits are never overwritten. Receipts stay in private local
state; later hosted runs reconcile fresh observations without claiming retained
canonical publication history.
"""
import hashlib
import html
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.request
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote, urljoin


TOKEN = "__PUBLISHING_REVIEWABLE_PRS_PR_NUMBER__"
FIELDS = ("number,url,title,body,baseRefName,baseRefOid,headRefName,headRefOid,"
          "headRepository,headRepositoryOwner,isDraft,state")
TAXONOMY = ("IMPL means non-test source and configuration. TEST means automated verification. "
            "DOC means reviewer and user documentation. GEN means generated artifacts. "
            "OTHER means files outside those categories. FILES shows added, modified, "
            "and removed files as +, ~, and −.")


class Hold(Exception):
    """A redacted reason suitable for operator-visible workflow output."""

    def __init__(self, reason, *, operation=None, exit_status=None):
        super().__init__(reason)
        self.diagnostic = ({"operation": operation, "exit_status": exit_status}
                           if operation is not None else None)


def _sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def _run(arguments, repo, env, *, operation, json_output=False, input_text=None):
    try:
        result = subprocess.run([str(arg) for arg in arguments], cwd=repo, env=env,
                                input=input_text, capture_output=True, text=True, timeout=90)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise Hold("publication_command_outcome_unknown", operation=operation) from error
    if result.returncode:
        # Command diagnostics may contain forge text or credential-helper output.
        raise Hold("publication_command_failed_or_outcome_unknown", operation=operation,
                   exit_status=result.returncode)
    if json_output:
        try:
            return json.loads(result.stdout)
        except (ValueError, TypeError) as error:
            raise Hold("publication_command_invalid_response", operation=operation,
                       exit_status=0) from error
    return result.stdout


def _git(repo, env, *arguments, operation):
    return _run(["git", "-C", repo, *arguments], repo, env, operation=operation).strip()


def _write(path, value):
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n")
    return path


def _remote_ref(repo, env, ref):
    lines = _git(repo, env, "ls-remote", "--refs", "origin", ref, operation="inspect_remote_ref").splitlines()
    if not lines:
        return None
    if len(lines) != 1 or not re.fullmatch(r"[0-9a-f]{40}\t" + re.escape(ref), lines[0]):
        raise Hold("ambiguous_remote_ref")
    return lines[0].split("\t")[0]


def _badge(alt, path, title=None, *, style="flat", extra=""):
    title_attr = ' title="' + html.escape(title, quote=True) + '"' if title else ""
    return ('<picture><img alt="' + html.escape(alt, quote=True) + '"' + title_attr +
            ' src="https://img.shields.io/badge/' + path + '?style=' + style + extra +
            '" height="16"></picture>')


def _body(repository, candidate, rows, pr_number, categories):
    taxonomy = {
        "IMPL": ("Implementation", "non-test source and configuration", "0969DA", "implementation"),
        "TEST": ("Tests", "automated verification", "6F5F9A", "test"),
        "DOC": ("Documentation", "reviewer and user documentation", "3F7770", "documentation"),
        "GEN": ("Generated", "generated artifacts", "76652F", "generated"),
        "OTHER": ("Other", "files outside the other categories", "57606A", "other"),
    }
    if any(categories.get(row["target_path"]) not in taxonomy for row in rows):
        raise Hold("publication_path_category_unestablished")
    groups = {key: [row for row in rows if categories[row["target_path"]] == key] for key in taxonomy}
    groups = {key: group for key, group in groups.items() if group}
    rows = [row for group in groups.values() for row in group]
    totals = {key: (sum(row["additions"] or 0 for row in group), sum(row["deletions"] or 0 for row in group))
              for key, group in groups.items()}
    def line_metric(added, deleted):
        return f"{added} " + ("addition" if added == 1 else "additions") + f", {deleted} " + ("deletion" if deleted == 1 else "deletions")
    def category_badge(key):
        added, deleted = totals[key]
        name, meaning, color, _ = taxonomy[key]
        return _badge(f"{key}: {added} additions, {deleted} deletions",
                      key + "-" + quote(f"+{added} −{deleted}", safe="") + "-" + color,
                      name + ": " + line_metric(added, deleted) + " (" + meaning + ")")
    summary = _badge("DIFF", "DIFF-57606A", style="for-the-badge") + "&nbsp;"
    summary += " ".join(category_badge(key) for key in groups if any(totals[key]))
    summary += (" " if rows else "") + _badge(f"FILES: {len(rows)} touched", f"FILES-{len(rows)}-5F6B78")
    lines = ["<details>", "<summary>" + summary + "</summary>", ""]
    previous = None
    diff = []
    for row in rows:
        category = categories[row["target_path"]]
        if category != previous:
            lines.append("- " + category_badge(category) + " " + _badge(
                f"FILES: {len(groups[category])} {taxonomy[category][3]} " + ("file" if len(groups[category]) == 1 else "files"),
                f"FILES-{len(groups[category])}-5F6B78"))
            previous = category
        path, source = row["target_path"], row["source_path"]
        operation = {"renamed": "MOVED", "copied": "COPIED"}.get(row["operation"], "ATOMIC")
        if row["binary"] and operation == "ATOMIC":
            operation = "BINARY"
        link = f"https://github.com/{repository}/pull/{pr_number}/files#diff-{_sha(path)}"
        paths = [source, path] if source else [path]
        if any("`" in part for part in paths):
            label = " → ".join("<code>" + html.escape(part, quote=False) + "</code>" for part in paths)
            navigation = '<a href="' + link + '">' + label + '</a>'
        else:
            label = " → ".join("`" + part + "`" for part in paths)
            navigation = "[" + label + "](" + link + ")"
        metrics = []
        if operation != "ATOMIC":
            metrics.append(_badge(operation, operation + "-5F6B78", operation))
        added, deleted = row["additions"], row["deletions"]
        if not row["binary"] and (operation == "ATOMIC" or added or deleted):
            text = line_metric(added, deleted)
            metrics.append(_badge(text, quote(f"+{added}", safe="") + "-" + quote(f"−{deleted}", safe="") + "-CF222E",
                                  text, extra="&labelColor=1A7F37"))
        lines.append("  - " + navigation + " " + " ".join(metrics))
        diff.append({"source_path": source, "target_path": path,
                     "additions": added or 0, "deletions": deleted or 0,
                     "category": category, "operation": operation})
    if not rows:
        lines.append("No file changes in the reviewer-visible comparison. "
                     f"[Review the commits](https://github.com/{repository}/pull/{pr_number}/commits) and "
                     f"[view the immutable history comparison](https://github.com/{repository}/compare/"
                     f"{candidate['base']}...{candidate['head']}).")
    if rows:
        lines += ["", "<sup>" + TAXONOMY + "</sup>"]
    lines += ["", "</details>", "",
              f"I imported upstream commit `{candidate['upstream']}` onto fork commit `{candidate['base']}`. "
              f"The proposed merge commit is `{candidate['head']}`.", "",
              "Source verification must establish upstream tree parity and unchanged fork-owned paths. "
              "CodeRabbit excludes verified upstream content from its content review; its approval does not establish source parity. "
              "The workflow separately checks CI, Jev, and current-commit approval before any merge."]
    return "\n".join(lines), diff


class _Page(HTMLParser):
    """Inspect observed GitHub HTML; this is not a Markdown renderer."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.ids, self.links, self.bodies = set(), set(), []
        self.depth = 0
        self.body = None
        self.body_depth = 0
        self.details = 0
        self.summary = 0

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        if attrs.get("id"):
            self.ids.add(attrs["id"])
        if tag == "a" and attrs.get("href"):
            self.links.add(attrs["href"])
        if tag not in {"img", "br", "hr", "input", "meta", "link", "source", "wbr", "area", "base", "embed", "param", "track", "col"}:
            self.depth += 1
        if "markdown-body" in attrs.get("class", "").split() and self.body is None:
            self.body = {"text": [], "links": set(), "diff": False}
            self.body_depth = self.depth
        if self.body is not None:
            if tag == "details": self.details += 1
            if tag == "summary" and self.details: self.summary += 1
            if tag == "img" and attrs.get("alt") == "DIFF" and self.summary:
                self.body["diff"] = True
            if tag == "a" and self.details and attrs.get("href"):
                self.body["links"].add(attrs["href"])

    def handle_endtag(self, tag):
        if self.body is not None:
            if tag == "summary" and self.summary: self.summary -= 1
            if tag == "details" and self.details: self.details -= 1
            if self.depth == self.body_depth:
                self.bodies.append(self.body)
                self.body = None
        self.depth -= 1

    def handle_data(self, data):
        if self.body is not None:
            self.body["text"].append(data)

    def handle_startendtag(self, tag, attributes):
        before = self.depth
        self.handle_starttag(tag, attributes)
        if self.depth > before:
            self.handle_endtag(tag)


def _rendered(url, candidate, rows, history=None):
    pages = []
    for suffix in ("", "/files" if rows else "/commits"):
        target = url + suffix
        request = urllib.request.Request(target, headers={"User-Agent": "typesafe-fork-sync", "Accept": "text/html"})
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read(8 * 1024 * 1024 + 1)
                if response.geturl() != target or len(raw) > 8 * 1024 * 1024:
                    raise Hold("live_rendering_unavailable")
        except (OSError, ValueError) as error:
            raise Hold("live_rendering_unavailable") from error
        page = _Page()
        page.feed(raw.decode("utf-8", "strict"))
        pages.append(page)
    anchors = {"diff-" + _sha(row["target_path"]) for row in rows}
    expected_links = {url + "/files#" + anchor for anchor in anchors}
    if history is not None:
        repository_url = url.rsplit("/pull/", 1)[0]
        expected_links = {url + "/commits", repository_url + "/compare/" + candidate["base"] + "..." + candidate["head"]}
        observed_links = {urljoin(url, link) for link in pages[1].links}
        if any(not {repository_url + "/commit/" + commit, url + "/commits/" + commit} & observed_links
               for commit in history["head_only_commits"]):
            raise Hold("live_history_navigation_unverified")
    good_body = any(body["diff"] and candidate["head"] in "".join(body["text"]) and
                    candidate["base"] in "".join(body["text"]) and
                    expected_links <= {urljoin(url, link) for link in body["links"]}
                    for body in pages[0].bodies)
    if not good_body or not anchors <= pages[1].ids:
        raise Hold("live_rendering_or_anchors_unverified")


def _publish(repo, candidate, policy, provingkit, temporary, env):
    repository = policy["repository"]
    owner = repository.split("/")[0]
    target = policy["target_branch"]
    branch = policy["candidate_prefix"] + candidate["upstream"][:12] + "-" + candidate["base"][:12]
    ref = "refs/heads/" + branch
    _git(repo, env, "check-ref-format", ref, operation="validate_candidate_ref")
    _git(repo, env, "check-ref-format", "refs/heads/" + target, operation="validate_target_ref")
    if branch == target or _git(provingkit, env, "rev-parse", "HEAD", operation="inspect_helper_revision") != policy["provingkit_pin"]:
        raise Hold("dependency_or_destination_drift")
    for directory in (repo, provingkit):
        if _git(directory, env, "status", "--porcelain=v1", "--untracked-files=all", operation="inspect_publication_worktree"):
            raise Hold("dirty_publication_input")
    if (_git(repo, env, "rev-parse", "HEAD", operation="inspect_candidate_revision") != candidate["head"] or
            _git(repo, env, "rev-parse", candidate["head"] + "^{tree}", operation="inspect_candidate_tree") != candidate["tree"]):
        raise Hold("candidate_checkout_drift")
    if _git(repo, env, "remote", "get-url", "--push", "--all", "origin", operation="inspect_origin") != f"https://github.com/{repository}.git":
        raise Hold("publication_origin_mismatch")
    if _remote_ref(repo, env, "refs/heads/" + target) != candidate["base"]:
        raise Hold("publication_base_moved")
    remote = _remote_ref(repo, env, ref)
    if remote not in (None, candidate["head"]):
        raise Hold("candidate_branch_collision")
    publisher = provingkit / "plugins/mergecraft/skills/publishing-reviewable-prs/scripts"
    writer = provingkit / "plugins/mergecraft/skills/writing-reviewable-pr-descriptions/scripts"
    versionkeeping = provingkit / "plugins/versionkeeping/skills/checkpointing-and-publishing-git-work/scripts"
    def helper(directory, name, *arguments, structured=True):
        operations = {"validate_change_navigation.py": "validate_navigation",
                      "plan_git_publication.py": "plan_branch_publication",
                      "execute_git_publication.py": "publish_branch",
                      "create_reviewable_pr.py": "create_pr",
                      "update_reviewable_pr.py": "mark_pr_ready",
                      "audit_reviewable_pr.py": "audit_pr"}
        operation = operations[name]
        if name == "audit_reviewable_pr.py" and arguments[0] == "reconcile":
            operation = "reconcile_pr"
        return _run([sys.executable, directory / name, *arguments], repo, env,
                    operation=operation, json_output=structured)
    read_env = dict(env)
    if env.get("GH_READ_TOKEN"):
        read_env["GH_TOKEN"] = env["GH_READ_TOKEN"]
    def inspect_pr(number):
        live = _run(["gh", "pr", "view", str(number), "--repo", repository, "--json", FIELDS],
                    repo, read_env, operation="inspect_pr", json_output=True)
        if not isinstance(live, dict):
            raise Hold("publication_command_invalid_response", operation="inspect_pr", exit_status=0)
        return live
    identity = ["--repository", repository, "--base", target, "--base-oid", candidate["base"],
                "--head", owner + ":" + branch, "--head-oid", candidate["head"],
                "--head-owner", owner, "--head-repository", repository]
    prs = _run(["gh", "pr", "list", "--repo", repository, "--state", "all", "--base", target,
                "--head", branch, "--limit", "100", "--json", FIELDS], repo, read_env, operation="find_candidate_pr", json_output=True)
    if not isinstance(prs, list) or len(prs) > 1:
        raise Hold("ambiguous_candidate_pr")
    if prs and (prs[0]["state"] != "OPEN" or prs[0]["headRefOid"] != candidate["head"]):
        raise Hold("candidate_pr_collision")
    rows = _run([sys.executable, "-I", "-c",
                 "import sys,json; from pathlib import Path; sys.path.insert(0,sys.argv[1]); "
                 "from change_navigation.git_observer import observe_git_diff; "
                 "print(json.dumps(observe_git_diff(Path(sys.argv[2]),base_oid=sys.argv[3],head_oid=sys.argv[4])))",
                 writer, repo, candidate["base"], candidate["head"]], repo, env, operation="observe_diff", json_output=True)
    if (len(rows) > 100 or sorted(row["target_path"] for row in rows) != sorted(candidate["changed_paths"])):
        raise Hold("publication_diff_outside_template_contract")
    history = None
    if not rows:
        history = _run([sys.executable, "-I", "-c",
                        "import sys,json; from pathlib import Path; sys.path.insert(0,sys.argv[1]); "
                        "from change_navigation.git_observer import observe_git_history; "
                        "print(json.dumps(observe_git_history(Path(sys.argv[2]),base_oid=sys.argv[3],head_oid=sys.argv[4])))",
                        writer, repo, candidate["base"], candidate["head"]], repo, env, operation="observe_history", json_output=True)
        if not history["head_only_commits"]:
            raise Hold("publication_history_outside_template_contract")
    title = "chore(sync): import upstream " + candidate["upstream"][:12]
    number = prs[0]["number"] if prs else TOKEN
    body, diff = _body(repository, candidate, rows, number, policy.get("publication_categories", {}))
    baseline = {"mode": "new", "title_sha256": None, "body_sha256": None, "fragments": []}
    if prs:
        live = inspect_pr(number)
        prefix = _run([sys.executable, "-I", "-c",
                       "import sys; sys.path.insert(0,sys.argv[1]); from change_navigation.bot_body import authored_body; "
                       "sys.stdout.write(authored_body(sys.stdin.read(),expected_sha256=sys.argv[2]))",
                       writer, _sha(body)], repo, env, operation="verify_authored_body", input_text=live["body"])
        if live["title"] != title or prefix != body:
            raise Hold("existing_pr_text_drift")
        baseline = {"mode": "existing", "title_sha256": _sha(title), "body_sha256": _sha(body),
                    "fragments": [{"id": "preserved-sync-body", "text": body, "sha256": _sha(body),
                                   "disposition": "retain", "replacement": None, "reason": None}]}
    manifest = {"version": 3, "repository": repository, "pr_number": number,
                "base": {"ref": target, "oid": candidate["base"]},
                "head": {"ref": owner + ":" + branch, "oid": candidate["head"], "owner": owner, "repository": repository},
                "candidate": {"title": title, "body_sha256": _sha(body)}, "git_diff": rows,
                "diff": diff, "stack": [], "baseline": baseline}
    if history is not None:
        manifest.update(version=4, git_history=history)
    manifest["content_sha256"] = _sha(json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False))
    manifest_path = _write(temporary / "manifest.json", manifest)
    body_path = temporary / "body.md"
    body_path.write_text(body)
    rendered_path = temporary / "rendered.md"
    rendered_path.write_text(body.replace(TOKEN, "1"))
    helper(writer, "validate_change_navigation.py", "--repository", repository,
           "--pr", str(number if prs else 1), "--title", title,
           "--git-repository", repo, "--review-input", manifest_path,
           *(["--template-body", body_path] if not prs else []), rendered_path, structured=False)
    if not remote:
        adopted = sorted(_git(repo, env, "rev-list", candidate["base"] + ".." + candidate["upstream"], operation="inspect_adopted_history").splitlines())
        request = {"schema_version": 2, "start_head": candidate["base"], "source_sha": candidate["head"],
                   "task_owned_commits": [candidate["head"]], "adopted_commits": adopted,
                   "removal_authorized_commits": [], "explicit_destination": {"remote": "origin", "ref": ref},
                   "default_branch_policy": None, "allow_create": True, "creation_base_ref": "refs/heads/" + target}
        request_path = _write(temporary / "request.json", request)
        plan_raw = helper(versionkeeping, "plan_git_publication.py", "--repo", repo, "--request", request_path, structured=False)
        try:
            plan = json.loads(plan_raw)
        except ValueError as error:
            raise Hold("invalid_publication_response_or_input",
                       operation="plan_branch_publication", exit_status=0) from error
        if not isinstance(plan, dict):
            raise Hold("invalid_publication_response_or_input",
                       operation="plan_branch_publication", exit_status=0)
        push, destination = plan.get("push", {}), plan.get("destination", {})
        if (plan.get("status") != "ready" or plan.get("request") != request or plan.get("source_sha") != candidate["head"] or
                destination.get("remote") != "origin" or destination.get("ref") != ref or destination.get("default_branch_ref") == ref or
                plan.get("target_only_shas") or plan.get("rewrite_required") or
                push.get("source_sha") != candidate["head"] or push.get("ref") != ref or
                push.get("refspec") != candidate["head"] + ":" + ref or
                push.get("expected_target") != {"present": False, "sha": None} or
                push.get("lease") != "--force-with-lease=" + ref + ":"):
            raise Hold("publication_plan_outside_authorized_candidate")
        plan_path = temporary / "plan.json"
        plan_path.write_text(plan_raw)
        result = helper(versionkeeping, "execute_git_publication.py", "--repo", repo, "--plan", plan_path,
                        "--reviewed-plan-sha256", "sha256:" + _sha(plan_raw))
        if result.get("status") != "verified" or _remote_ref(repo, env, ref) != candidate["head"]:
            raise Hold("branch_publication_unverified")
    review = ["--review-mode", "not-required", "--selected-specialists", "[]"]
    if not prs:
        created = helper(publisher, "create_reviewable_pr.py", *identity, "--title", title,
                         "--body-template", body_path, "--review-input", manifest_path, *review)
        if created.get("status") != "verified" or not isinstance(created.get("pr"), int):
            raise Hold("pr_creation_unverified")
        number = created["pr"]
    live = inspect_pr(number)
    url = f"https://github.com/{repository}/pull/{number}"
    if (live.get("url") != url or live.get("state") != "OPEN" or live.get("headRefOid") != candidate["head"] or
            live.get("baseRefOid") != candidate["base"] or live.get("baseRefName") != target or
            live.get("headRefName") != branch or live.get("headRepositoryOwner", {}).get("login") != owner or
            live.get("headRepository", {}).get("name") != repository.split("/")[1]):
        raise Hold("published_pr_identity_drift")
    _rendered(url, candidate, rows, history)
    bound = [*identity, "--pr", str(number)]
    provenance = "canonical"
    if prs:
        reconciled = helper(publisher, "audit_reviewable_pr.py", "reconcile", *bound, "--review-input", manifest_path)
        if reconciled.get("status") != "reconciled-unreceipted":
            raise Hold("publication_reconciliation_unverified")
        provenance = "reconciled-unreceipted"
    if live["isDraft"]:
        rendered_body = body.replace(TOKEN, str(number))
        ready = helper(publisher, "update_reviewable_pr.py", "ready", *bound,
                       "--expected-title-sha256", _sha(title), "--expected-body-sha256", _sha(rendered_body),
                       "--review-input", manifest_path, *review,
                       *(["--body-template", body_path] if not prs else []))
        if ready.get("status") != "verified":
            raise Hold("pr_readiness_unverified")
        provenance = "canonical"
    audit = helper(publisher, "audit_reviewable_pr.py", "audit", *bound)
    if audit.get("status") != "verified":
        raise Hold("publication_audit_unverified")
    return {"status": "published", "pr_number": number, "url": url, "head_branch": branch,
            "head": candidate["head"], "base": candidate["base"],
            "evidence": {"rendering": "live_structure_and_history_links_verified" if history else "live_structure_and_anchors_verified", "publication_audit": "verified",
                         "provenance": provenance, "receipt_retention": "private_ephemeral_run",
                         "relation_context": None}}


def publish(repo: Path, candidate: dict, policy: dict, provingkit: Path) -> dict:
    """Return a published PR or a hold; no merge or review overrides occur here."""
    try:
        if (not re.fullmatch(r"[0-9a-f]{40}", policy.get("provingkit_pin", "")) or
                not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", policy.get("repository", "")) or
                not policy.get("candidate_prefix", "").startswith("nisavid/") or
                not policy["candidate_prefix"].endswith("/") or
                any(not re.fullmatch(r"[0-9a-f]{40}", candidate.get(key, "")) for key in ("base", "upstream", "head", "tree"))):
            raise Hold("invalid_publication_input")
        env = {key: value for key, value in os.environ.items() if key not in {"PYTHONPATH", "PYTHONHOME", "GH_HOST", "GH_REPO"}}
        env.update({"GH_PROMPT_DISABLED": "1", "GIT_TERMINAL_PROMPT": "0"})
        with tempfile.TemporaryDirectory(prefix="typesafe-publication-") as temporary:
            root = Path(temporary)
            env["XDG_STATE_HOME"] = str(root / "state")
            repo = repo.resolve()
            config_names = _git(repo, env, "config", "--name-only", "--list", operation="inspect_git_configuration").lower().splitlines()
            if any(name.startswith(("filter.", "include.", "includeif.")) or
                   name == "core.fsmonitor" for name in config_names):
                raise Hold("publication_git_configuration_requires_isolation")
            if _git(repo, env, "status", "--porcelain=v1", "--untracked-files=all", operation="inspect_controller_worktree"):
                raise Hold("dirty_publication_input")
            origin = f"https://github.com/{policy['repository']}.git"
            if _git(repo, env, "remote", "get-url", "--push", "--all", "origin", operation="inspect_origin") != origin:
                raise Hold("publication_origin_mismatch")
            # The writer requires HEAD at the PR candidate. Materialize only a
            # disposable data checkout; the executing controller never moves.
            # A shared clone would create alternates forbidden by Versionkeeping.
            data = root / "candidate"
            data.mkdir()
            template = root / "empty-template"
            template.mkdir()
            checkout_env = {key: value for key, value in env.items() if not key.startswith("GIT_")}
            checkout_env.update({"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
                                 "GIT_TERMINAL_PROMPT": "0", "GIT_NO_REPLACE_OBJECTS": "1"})
            _git(data, checkout_env, "init", "--template=" + str(template), operation="initialize_candidate")
            for key, value in (("submodule.recurse", "false"), ("core.autocrlf", "false")):
                _git(data, checkout_env, "config", key, value, operation="configure_candidate")
            _git(data, checkout_env, "-c", "protocol.file.allow=always", "fetch", "--no-tags",
                 "--no-recurse-submodules", str(repo), candidate["head"], operation="fetch_candidate")
            _git(data, checkout_env, "-c", "core.hooksPath=" + str(template),
                 "-c", "core.attributesFile=" + os.devnull, "checkout", "--detach", candidate["head"], operation="checkout_candidate")
            _git(data, checkout_env, "remote", "add", "origin", origin, operation="configure_candidate_origin")
            return _publish(data, candidate, policy, provingkit.resolve(), root, env)
    except Hold as error:
        result = {"status": "hold", "reason": str(error), "head": candidate.get("head"), "base": candidate.get("base")}
        if error.diagnostic is not None:
            result["diagnostic"] = error.diagnostic
        return result
    except (ValueError, KeyError, TypeError, UnicodeError) as error:
        return {"status": "hold", "reason": "invalid_publication_response_or_input",
                "head": candidate.get("head"), "base": candidate.get("base")}
