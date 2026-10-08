"""Collect GitHub evidence and submit one head-conditional merge.

Read operations use GH_READ_TOKEN when present; only the merge write uses
GH_TOKEN. Errors are fixed codes, never forge response bodies or diagnostics.
This adapter never creates, edits, or changes the readiness of a pull request.
"""

import base64
import hashlib
import json
import os
import re
import subprocess
from urllib.parse import quote


_THREADS = """query($owner:String!,$name:String!,$number:Int!,$endCursor:String){
  repository(owner:$owner,name:$name){pullRequest(number:$number){
    reviewThreads(first:100,after:$endCursor){nodes{isResolved}
      pageInfo{hasNextPage endCursor}}}}}"""


def _address_valid(repository, pr_number):
    return (isinstance(repository, str)
            and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9_][A-Za-z0-9_.-]*", repository) is not None
            and type(pr_number) is int and pr_number > 0)


def _candidate_valid(candidate):
    return isinstance(candidate, dict) and all(
        isinstance(candidate.get(key), str) and re.fullmatch(pattern, candidate[key])
        for key, pattern in (("base", r"[0-9a-f]{40}"), ("head", r"[0-9a-f]{40}"),
                             ("upstream", r"[0-9a-f]{40}"), ("tree", r"[0-9a-f]{40}"),
                             ("policy_sha256", r"[0-9a-f]{64}"), ("questions_sha256", r"[0-9a-f]{64}")))


def _api(endpoint, *, paginate=False, payload=None, write=False):
    environment = os.environ.copy()
    if not write and environment.get("GH_READ_TOKEN"):
        environment["GH_TOKEN"] = environment["GH_READ_TOKEN"]
    arguments = ["gh", "api", endpoint, "--hostname", "github.com",
                 "--method", "PUT" if write else ("POST" if endpoint == "graphql" else "GET")]
    if paginate:
        arguments += ["--paginate", "--slurp"]
    input_text = None
    if endpoint == "graphql" and payload is not None:
        arguments += ["--raw-field", "query=" + payload["query"]]
        for key, value in payload["variables"].items():
            arguments += ["--field" if type(value) is int else "--raw-field", f"{key}={value}"]
    elif payload is not None:
        arguments += ["--input", "-"]
        input_text = json.dumps(payload)
    result = subprocess.run(arguments, input=input_text, capture_output=True,
                            text=True, env=environment, timeout=90)
    if result.returncode:
        raise ValueError("api_failed")
    return json.loads(result.stdout)


def observe(repository: str, pr_number: int, target_branch: str,
            candidate: dict, policy: dict) -> dict:
    """Return normalized gates.evaluate observations; errors fail closed."""
    if not _address_valid(repository, pr_number) or not _candidate_valid(candidate):
        return {"error": "github_observation_unavailable"}
    prefix = f"repos/{repository}"
    try:
        pr = _api(f"{prefix}/pulls/{pr_number}")
        _identity(pr, repository, pr_number, target_branch, candidate, policy)
        base = _api(f"{prefix}/git/ref/heads/{quote(target_branch, safe='')}")["object"]["sha"]
        head = pr["head"]["sha"]
        tree = _api(f"{prefix}/git/commits/{head}")["tree"]["sha"]
        content = _api(f"{prefix}/contents/.agents/fork-sync.json?ref={base}")
        if content["type"] != "file" or content["encoding"] != "base64":
            raise ValueError("policy_file_invalid")
        raw_policy = base64.b64decode("".join(content["content"].split()), validate=True)
        fresh_policy = json.loads(raw_policy)
        questions = (json.dumps(fresh_policy["jev_questions"], indent=2, ensure_ascii=False) + "\n").encode()
        policy_sha = hashlib.sha256(raw_policy).hexdigest()
        questions_sha = hashlib.sha256(questions).hexdigest()
        check_pages = _api(f"{prefix}/commits/{head}/check-runs?filter=latest&per_page=100", paginate=True)
        checks = [{"name": check["name"], "app_id": check["app"]["id"],
                   "head": check["head_sha"], "status": check["status"], "conclusion": check["conclusion"]}
                  for page in check_pages for check in page["check_runs"]]
        if not check_pages or any(type(page["total_count"]) is not int
                or page["total_count"] != len(checks) for page in check_pages):
            raise ValueError("check_pages_incomplete")
        review_pages = _api(f"{prefix}/pulls/{pr_number}/reviews?per_page=100", paginate=True)
        if not isinstance(review_pages, list) or not review_pages or not all(isinstance(page, list) for page in review_pages):
            raise ValueError("review_pages_invalid")
        reviews = [{"id": review["id"], "user": review["user"]["login"], "user_id": review["user"]["id"],
                    "state": review["state"], "commit_id": review["commit_id"], "submitted_at": review["submitted_at"]}
                   for page in review_pages for review in page]
        owner, name = repository.split("/")
        thread_pages = _api("graphql", paginate=True, payload={
            "query": _THREADS, "variables": {"owner": owner, "name": name, "number": pr_number}})
        if not isinstance(thread_pages, list) or not thread_pages:
            raise ValueError("thread_pages_missing")
        threads = []
        cursors = set()
        for index, page in enumerate(thread_pages):
            if not isinstance(page, dict) or page.get("errors"):
                raise ValueError("thread_query_failed")
            connection = page["data"]["repository"]["pullRequest"]["reviewThreads"]
            info = connection["pageInfo"]
            if info["hasNextPage"] is not (index < len(thread_pages) - 1):
                raise ValueError("thread_pages_incomplete")
            if info["hasNextPage"]:
                if not isinstance(info["endCursor"], str) or not info["endCursor"] or info["endCursor"] in cursors:
                    raise ValueError("thread_cursor_invalid")
                cursors.add(info["endCursor"])
            if not isinstance(connection["nodes"], list):
                raise ValueError("threads_invalid")
            for node in connection["nodes"]:
                if type(node["isResolved"]) is not bool:
                    raise ValueError("thread_resolution_invalid")
                threads.append(node)
        protection = _api(f"{prefix}/branches/{quote(target_branch, safe='')}/protection")
        required = protection["required_status_checks"]
        return {
            "binding": {"base": base, "head": head, "upstream": candidate["upstream"], "tree": tree,
                        "policy_sha256": policy_sha, "questions_sha256": questions_sha},
            "live_base": base, "live_head": head, "policy_sha256": policy_sha,
            "questions_sha256": questions_sha,
            "mergeability": pr["mergeable_state"] if pr["mergeable"] is True else "unknown",
            "unresolved_threads": sum(not node["isResolved"] for node in threads),
            "checks": checks, "reviews": reviews,
            "protection": {"enforce_admins": protection["enforce_admins"]["enabled"],
                           "strict": required["strict"],
                           "required_checks": [{"name": item["context"], "app_id": item["app_id"]}
                                               for item in required["checks"]]},
        }
    except (KeyError, TypeError, ValueError, OSError, subprocess.TimeoutExpired):
        return {"error": "github_observation_unavailable"}


def _identity(pr, repository, pr_number, target_branch, candidate, policy):
    if (pr["number"] != pr_number or pr["state"] != "open" or pr["draft"] is not False
            or pr["base"]["repo"]["full_name"] != repository
            or pr["head"]["repo"]["full_name"] != repository
            or pr["base"]["ref"] != target_branch or pr["base"]["sha"] != candidate["base"]
            or pr["head"]["ref"] != policy["head_branch"] or pr["head"]["sha"] != candidate["head"]):
        raise ValueError("pr_identity_changed")


def merge(repository: str, pr_number: int, candidate: dict, policy: dict) -> dict:
    """Merge after caller qualification; never retry an ambiguous write.

The caller must run gates.evaluate on fresh observations first. Strict server
    protection closes the race after this function's final base/head observation.
    """
    if not _address_valid(repository, pr_number) or not _candidate_valid(candidate) or not os.environ.get("GH_TOKEN"):
        return {"status": "hold", "reason": "merge_preflight_failed"}
    prefix = f"repos/{repository}"
    try:
        pr = _api(f"{prefix}/pulls/{pr_number}")
        _identity(pr, repository, pr_number, policy["target_branch"], candidate, policy)
        if pr["mergeable"] is not True or pr["mergeable_state"] != "clean":
            return {"status": "hold", "reason": "mergeability_unconfirmed"}
        base = _api(f"{prefix}/git/ref/heads/{quote(policy['target_branch'], safe='')}")["object"]["sha"]
        if base != candidate["base"]:
            return {"status": "hold", "reason": "base_changed"}
    except (KeyError, TypeError, ValueError, OSError, subprocess.TimeoutExpired):
        return {"status": "hold", "reason": "merge_preflight_failed"}
    try:
        result = _api(f"{prefix}/pulls/{pr_number}/merge", write=True,
                      payload={"sha": candidate["head"], "merge_method": "merge"})
        if result["merged"] is not True:
            return {"status": "hold", "reason": "merge_rejected"}
        commit = _api(f"{prefix}/git/commits/{result['sha']}")
        if commit["sha"] != result["sha"] or [parent["sha"] for parent in commit["parents"]] != [candidate["base"], candidate["head"]]:
            return {"status": "unknown", "reason": "merge_parents_unverified"}
        return {"status": "merged", "merge_commit": result["sha"]}
    except (KeyError, TypeError, ValueError, OSError, subprocess.TimeoutExpired):
        # A lost response may still have committed the merge. Observe once;
        # never issue another write from this invocation.
        try:
            observed = _api(f"{prefix}/pulls/{pr_number}")
            if observed["merged"] is True and observed["head"]["sha"] == candidate["head"]:
                commit = _api(f"{prefix}/git/commits/{observed['merge_commit_sha']}")
                if (commit["sha"] == observed["merge_commit_sha"]
                        and [parent["sha"] for parent in commit["parents"]] == [candidate["base"], candidate["head"]]):
                    return {"status": "merged", "merge_commit": commit["sha"]}
        except (KeyError, TypeError, ValueError, OSError, subprocess.TimeoutExpired):
            pass
        return {"status": "unknown", "reason": "merge_outcome_unknown"}
