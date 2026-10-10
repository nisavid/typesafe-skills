"""Evaluate bounded, independently collected sync observations without I/O.

``evaluate`` consumes normalized JSON, not raw provider responses. Bindings
contain base/upstream/head/tree Git SHA-1s and policy/questions SHA-256s.
The caller computes policy.sha256 from the actual policy file, collects all
review pages, hashes the submitted Jev state as observed_state_sha256, and
authenticates every observation. Matching strings cannot authenticate evidence.

Checks and protection.required_checks use {name, app_id}. Reviews use
{id, user, user_id, state, commit_id, submitted_at}; submission timestamps must
include a timezone. Jev uses {binding, model, cached, question_type, options,
answer, probabilities, state_sha256, observed_state_sha256}. The executable
accepted_evidence example in tests/test_gates.py supplies the complete shape.

The first failed gate returns a fixed reason with no provider payload. Ready
is a decision about these observations; the transport must re-observe before
merging and rely on strict server-side protection against concurrent base drift.
"""

import math
import re
from datetime import datetime

_BINDING = ("base", "upstream", "head", "tree", "policy_sha256", "questions_sha256")
_OPTIONS = ["no_additional_handling", "additional_handling", "insufficient_context"]


def _digest(value, length):
    return isinstance(value, str) and re.fullmatch(f"[0-9a-f]{{{length}}}", value) is not None


def _check_keys(records):
    if not isinstance(records, list) or not records:
        return None
    keys = []
    for record in records:
        if (not isinstance(record, dict) or not isinstance(record.get("name"), str)
                or not record["name"] or type(record.get("app_id")) is not int or record["app_id"] <= 0):
            return None
        keys.append((record["name"], record["app_id"]))
    return keys if len(set(keys)) == len(keys) else None


def _review_approved(reviews, head, user_id):
    if type(user_id) is not int or user_id <= 0 or not isinstance(reviews, list):
        return False
    ordered = []
    ids = set()
    for review in reviews:
        if (not isinstance(review, dict) or type(review.get("id")) is not int
                or review["id"] <= 0 or review["id"] in ids
                or type(review.get("user_id")) is not int
                or not isinstance(review.get("user"), str)
                or not _digest(review.get("commit_id"), 40)
                or review.get("state") not in ("APPROVED", "CHANGES_REQUESTED", "DISMISSED", "COMMENTED")):
            return False
        ids.add(review["id"])
        try:
            timestamp = datetime.fromisoformat(review["submitted_at"])
            if timestamp.tzinfo is None:
                return False
        except (KeyError, ValueError, TypeError):
            return False
        ordered.append((timestamp, review["id"], review))
    approved = False
    for _, _, review in sorted(ordered):
        if review["user"] != "coderabbitai[bot]" or review["user_id"] != user_id:
            continue
        if review["state"] == "APPROVED":
            approved = review["commit_id"] == head
        elif review["state"] in ("CHANGES_REQUESTED", "DISMISSED"):
            approved = False
    return approved


def _jev_accepted(jev, binding, policy):
    if (not isinstance(jev, dict) or jev.get("binding") != binding
            or policy.get("jev_model") != "jev-1.13.0" or jev.get("model") != "jev-1.13.0"
            or type(policy.get("jev_min_probability")) not in (int, float)
            or policy["jev_min_probability"] != 0.96
            or jev.get("cached") is not False or jev.get("question_type") != "choice"
            or jev.get("options") != _OPTIONS or jev.get("answer") != "no_additional_handling"
            or not _digest(jev.get("state_sha256"), 64)
            or jev["state_sha256"] != jev.get("observed_state_sha256")):
        return False
    probabilities = jev.get("probabilities")
    if not isinstance(probabilities, dict) or set(probabilities) != set(_OPTIONS):
        return False
    values = list(probabilities.values())
    if not all(type(value) in (int, float) and 0 <= value <= 1 and math.isfinite(value) for value in values):
        return False
    return (math.isclose(sum(values), 1.0, rel_tol=0, abs_tol=1e-9)
            and probabilities["no_additional_handling"] >= policy["jev_min_probability"])


def evaluate(candidate: dict, observation: dict, policy: dict) -> dict:
    if not all(isinstance(value, dict) for value in (candidate, observation, policy)):
        return {"status": "hold", "reasons": ["malformed_input"]}
    if not all(_digest(candidate.get(key), 64 if key.endswith("sha256") else 40) for key in _BINDING):
        return {"status": "hold", "reasons": ["malformed_candidate"]}
    binding = {key: candidate[key] for key in _BINDING}
    if observation.get("binding") != binding:
        return {"status": "hold", "reasons": ["stale_observation"]}
    if observation.get("live_base") != candidate["base"] or observation.get("live_head") != candidate["head"]:
        return {"status": "hold", "reasons": ["branch_changed"]}
    if (policy.get("sha256") != candidate["policy_sha256"]
            or observation.get("policy_sha256") != candidate["policy_sha256"]
            or policy.get("questions_sha256") != candidate["questions_sha256"]
            or observation.get("questions_sha256") != candidate["questions_sha256"]):
        return {"status": "hold", "reasons": ["policy_changed"]}
    required = _check_keys(policy.get("required_checks"))
    observed = _check_keys(observation.get("checks"))
    if required is None:
        return {"status": "hold", "reasons": ["invalid_required_checks"]}
    if observed is None or not set(required).issubset(observed):
        return {"status": "hold", "reasons": ["missing_required_checks"]}
    for key, check in zip(observed, observation["checks"]):
        if key in required and (check.get("head") != candidate["head"]
                or check.get("status") != "completed" or check.get("conclusion") != "success"):
            return {"status": "hold", "reasons": ["checks_not_passed"]}
    protection = observation.get("protection")
    if not isinstance(protection, dict):
        return {"status": "hold", "reasons": ["protection_missing"]}
    protected = _check_keys(protection.get("required_checks"))
    if (protection.get("enforce_admins") is not True or protection.get("strict") is not True
            or protected is None or not set(required).issubset(protected)
            or type(protection.get("required_approving_review_count")) is not int
            or protection["required_approving_review_count"] < 1
            or protection.get("dismiss_stale_reviews") is not True
            or protection.get("required_conversation_resolution") is not True
            or protection.get("review_bypass_allowances") != {"users": [], "teams": [], "apps": []}):
        return {"status": "hold", "reasons": ["protection_inadequate"]}
    if observation.get("mergeability") != "clean":
        return {"status": "hold", "reasons": ["mergeability_unconfirmed"]}
    if type(observation.get("unresolved_threads")) is not int or observation["unresolved_threads"] != 0:
        return {"status": "hold", "reasons": ["threads_unresolved"]}
    if not _review_approved(observation.get("reviews"), candidate["head"], policy.get("coderabbit_user_id")):
        return {"status": "hold", "reasons": ["coderabbit_not_approved"]}
    if not _jev_accepted(observation.get("jev"), binding, policy):
        return {"status": "hold", "reasons": ["jev_not_accepted"]}
    return {"status": "ready", "reasons": []}
