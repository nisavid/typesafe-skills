"""Reconcile pinned Git inputs through authenticated hosted adapters."""
import hashlib
import json
import os
import re
import subprocess

from .git_candidate import construct
from .gates import evaluate


class HostedServices:
    """Production adapters; tests substitute controlled external services."""
    def publish(self, *args):
        from .publication import publish
        return publish(*args)

    def observe(self, *args):
        from .github import observe
        return observe(*args)

    def judge(self, *args):
        from .jev import judge
        return judge(*args)

    def permit(self, *args):
        from .attempts import permit
        return permit(*args)

    def merge(self, *args):
        from .github import merge
        return merge(*args)


def reconcile(repo, base, upstream, policy_bytes, provingkit, *, services=None,
              target_branch=None, evidence_dir=None, phase='finalize'):
    """Run once, retaining public decision evidence when a destination is supplied."""
    try:
        result = _reconcile(repo, base, upstream, policy_bytes, provingkit,
                            services=services, target_branch=target_branch, phase=phase)
    except (KeyError, TypeError, ValueError, OSError, subprocess.SubprocessError):
        result = {'status': 'hold', 'reasons': ['invalid-input-or-unavailable-service']}
    if evidence_dir is not None:
        evidence_dir.mkdir(parents=True, exist_ok=True)
        (evidence_dir / 'result.json').write_text(json.dumps(result, sort_keys=True, indent=2) + '\n')
    return result


def _reconcile(repo, base, upstream, policy_bytes, provingkit, *, services,
               target_branch, phase):
    """Run one bounded attempt; a held result is resumed by a later invocation."""
    services = services or HostedServices()
    if phase not in ('prepare', 'finalize'):
        return {'status': 'hold', 'reasons': ['unsupported-phase']}
    if not all(isinstance(oid, str) and re.fullmatch('[0-9a-f]{40}', oid) for oid in (base, upstream)):
        return {'status': 'hold', 'reasons': ['unpinned-input']}
    try:
        stored = subprocess.run(['git', '-C', str(repo), 'show', base + ':.agents/fork-sync.json'],
                                capture_output=True, timeout=30, check=True,
                                env={**{k: v for k, v in os.environ.items() if not k.startswith('GIT_')},
                                     'GIT_NO_REPLACE_OBJECTS': '1'}).stdout
    except (OSError, subprocess.SubprocessError):
        return {'status': 'hold', 'reasons': ['base-policy-unavailable']}
    if stored != policy_bytes:
        return {'status': 'hold', 'reasons': ['base-policy-changed']}
    policy = json.loads(policy_bytes)
    if target_branch is not None:
        if target_branch not in (policy['target_branch'], policy.get('validation_branch')):
            return {'status': 'hold', 'reasons': ['unapproved-target-branch']}
        policy['target_branch'] = target_branch
    policy['sha256'] = hashlib.sha256(policy_bytes).hexdigest()
    questions = (json.dumps(policy['jev_questions'], indent=2, ensure_ascii=False) + '\n').encode()
    policy['questions_sha256'] = hashlib.sha256(questions).hexdigest()
    candidate = construct(repo, base, upstream, policy)
    if candidate['status'] != 'candidate':
        return candidate
    candidate.update(policy_sha256=policy['sha256'], questions_sha256=policy['questions_sha256'])
    published = services.publish(repo, candidate, policy, provingkit)
    if published['status'] != 'published':
        return published
    policy['head_branch'] = published['head_branch']
    observation = services.observe(policy['repository'], published['pr_number'],
                                   policy['target_branch'], candidate, policy)
    context = {'candidate': candidate, 'pr_url': published['url']}
    preliminary = evaluate(candidate, observation, policy)
    # Jev is the last gate; missing CI/reviews/protection need no paid judgment.
    if preliminary['reasons'] != ['jev_not_accepted']:
        return {**preliminary, **context}
    binding = {key: candidate[key] for key in ('base', 'upstream', 'head', 'tree',
                                               'policy_sha256', 'questions_sha256')}
    digest = hashlib.sha256(json.dumps(binding, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    if phase == 'prepare':
        return {'status': 'awaiting_judgment', 'judgment_binding': digest, **context}
    attempt = services.permit(candidate, policy)
    if attempt.get('status') != 'permitted':
        return {**attempt, **context}
    judgment = services.judge(repo, candidate, policy)
    context['jev'] = judgment
    observation['jev'] = judgment
    decision = evaluate(candidate, observation, policy)
    if decision['status'] != 'ready':
        return {**decision, **context}
    latest = services.observe(policy['repository'], published['pr_number'],
                              policy['target_branch'], candidate, policy)
    latest['jev'] = judgment
    decision = evaluate(candidate, latest, policy)
    if decision['status'] != 'ready':
        return {**decision, **context}
    return {**services.merge(policy['repository'], published['pr_number'], candidate, policy),
            **context, 'jev': judgment}
