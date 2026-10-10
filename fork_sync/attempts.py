"""Fail closed unless Actions history establishes the first candidate attempt.

Activation supplies immutable FORK_SYNC_WORKFLOW_ID and
FORK_SYNC_FIRST_RUN_NUMBER. GITHUB_RUN_ID and GITHUB_RUN_ATTEMPT identify this
execution. GH_READ_TOKEN needs Actions read access. No artifact or missing
record is interpreted as permission to sample Jev again.
"""

import hashlib
import json
import os
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

_FIELDS = ("base", "upstream", "head", "tree", "policy_sha256", "questions_sha256")


def _api(endpoint, *, pages=False):
    env = os.environ.copy()
    env["GH_TOKEN"] = env["GH_READ_TOKEN"]
    args = ["gh", "api", endpoint, "--hostname", "github.com", "--method", "GET"]
    if pages:
        args += ["--paginate", "--slurp"]
    result = subprocess.run(args, capture_output=True, text=True, env=env, timeout=90)
    if result.returncode:
        raise ValueError("history_unavailable")
    return json.loads(result.stdout)


def _records(endpoint, key):
    pages = _api(endpoint, pages=True)
    if not isinstance(pages, list) or not pages:
        raise ValueError("history_unavailable")
    records = []
    for page in pages:
        if not isinstance(page[key], list):
            raise ValueError("history_unavailable")
        records.extend(page[key])
    if any(type(page["total_count"]) is not int or page["total_count"] != len(records) for page in pages):
        raise ValueError("history_incomplete")
    for record in records:
        if not isinstance(record, dict) or type(record["id"]) is not int or record["id"] <= 0:
            raise ValueError("record_invalid")
        if key == "jobs" and (type(record["run_id"]) is not int or record["run_id"] <= 0
                or not isinstance(record["name"], str)
                or record["status"] not in ("queued", "in_progress", "completed", "waiting", "pending", "requested")
                or (record["started_at"] is not None and datetime.fromisoformat(record["started_at"]).tzinfo is None)):
            raise ValueError("job_invalid")
    return records


def permit(candidate: dict, policy: dict) -> dict:
    """Permit only this visible job's first attempt for the complete binding."""
    try:
        run_id, attempt, workflow_id, first = [int(os.environ[key]) for key in (
            "GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT", "FORK_SYNC_WORKFLOW_ID", "FORK_SYNC_FIRST_RUN_NUMBER")]
        if min(run_id, attempt, workflow_id, first) <= 0 or not os.environ["GH_READ_TOKEN"]:
            raise ValueError("activation_missing")
        repository = policy["repository"]
        if not isinstance(repository, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9_][A-Za-z0-9_.-]*", repository):
            raise ValueError("repository_invalid")
        binding = {key: candidate[key] for key in _FIELDS}
        if not all(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}" if key.endswith("sha256") else r"[0-9a-f]{40}", value)
                   for key, value in binding.items()):
            raise ValueError("binding_invalid")
        name = "Jev " + hashlib.sha256(json.dumps(binding, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        prefix = f"repos/{repository}/actions"
        workflow = _api(f"{prefix}/workflows/upstream-sync.yml")
        current = _api(f"{prefix}/runs/{run_id}")
        if (workflow["id"] != workflow_id or workflow["path"] != ".github/workflows/upstream-sync.yml"
                or workflow["state"] != "active" or current["id"] != run_id
                or current["workflow_id"] != workflow_id or current["run_attempt"] != attempt
                or current["repository"]["full_name"] != repository or current["status"] != "in_progress"
                or current["run_number"] < first):
            raise ValueError("workflow_identity_changed")
        jobs = _records(f"{prefix}/runs/{run_id}/attempts/{attempt}/jobs?per_page=100", "jobs")
        matching = [job for job in jobs if job["name"] == name]
        if len(matching) != 1:
            raise ValueError("current_job_unconfirmed")
        job = matching[0]
        if (job["status"] != "in_progress" or job["conclusion"] is not None
                or datetime.fromisoformat(job["started_at"]).tzinfo is None):
            raise ValueError("current_job_unconfirmed")
        runs = _records(f"{prefix}/workflows/{workflow_id}/runs?per_page=100", "workflow_runs")
        numbers, run_ids = set(), set()
        for run in runs:
            if (type(run["run_number"]) is not int or run["run_number"] <= 0
                    or type(run["id"]) is not int or run["id"] <= 0
                    or type(run["run_attempt"]) is not int or run["run_attempt"] <= 0
                    or run["workflow_id"] != workflow_id or run["repository"]["full_name"] != repository
                    or run["run_number"] in numbers or run["id"] in run_ids):
                raise ValueError("run_history_invalid")
            numbers.add(run["run_number"])
            run_ids.add(run["id"])
        eligible = [number for number in numbers if number >= first]
        if (run_id not in run_ids or not eligible or min(eligible) != first
                or max(eligible) - first + 1 != len(eligible)):
            raise ValueError("run_history_incomplete")
        for run in runs:
            if run["id"] == run_id and any(run[key] != current[key] for key in ("run_attempt", "run_number", "status")):
                raise ValueError("current_run_changed")

        def consumed(run):
            all_jobs = _records(f"{prefix}/runs/{run['id']}/jobs?filter=all&per_page=100", "jobs")
            attempt_jobs = []
            for number in range(1, run["run_attempt"] + 1):
                records = (jobs if run["id"] == run_id and number == attempt else
                           _records(f"{prefix}/runs/{run['id']}/attempts/{number}/jobs?per_page=100", "jobs"))
                if not records or len([item for item in records if item["name"].startswith("Jev ")]) != 1:
                    raise ValueError("attempt_history_incomplete")
                attempt_jobs.extend(records)
            all_ids = [item["id"] for item in all_jobs]
            attempt_ids = [item["id"] for item in attempt_jobs]
            if (len(set(all_ids)) != len(all_ids) or len(set(attempt_ids)) != len(attempt_ids)
                    or set(all_ids) != set(attempt_ids)):
                raise ValueError("job_history_incomplete")
            compared = ("id", "run_id", "name", "status", "conclusion", "started_at")
            snapshots = {item["id"]: {key: item[key] for key in compared} for item in attempt_jobs}
            for previous in all_jobs:
                if (previous["run_id"] != run["id"]
                        or {key: previous[key] for key in compared} != snapshots[previous["id"]]):
                    raise ValueError("job_run_mismatch")
                if previous["id"] == job["id"] and run["id"] == run_id:
                    continue
                if previous["name"] == name and not (previous["status"] == "completed" and previous["conclusion"] == "skipped"):
                    return True
            return False

        with ThreadPoolExecutor(max_workers=4) as history:
            consumed_attempts = list(history.map(consumed, (run for run in runs if run["run_number"] >= first)))
        if any(consumed_attempts):
            return {"status": "hold", "reasons": ["jev_attempt_consumed"]}
        return {"status": "permitted", "reasons": []}
    except (KeyError, TypeError, ValueError, OSError, subprocess.TimeoutExpired):
        return {"status": "hold", "reasons": ["jev_attempt_unconfirmed"]}
