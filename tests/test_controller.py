"""Exercise the complete reconciliation decision using disposable Git inputs."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from fork_sync.controller import reconcile
from test_gates import accepted_evidence


class HostedResponses:
    def __init__(self, ready=False, drift=False):
        self.published = []
        self.merged = []
        self.ready = ready
        self.drift = drift
        self.observations = 0

    def publish(self, repo, candidate, policy, dependency):
        self.published.append(candidate)
        return {'status': 'published', 'pr_number': 12, 'url': 'https://github.com/nisavid/typesafe-skills/pull/12',
                'head_branch': 'nisavid/upstream-sync/test'}

    def observe(self, repository, number, branch, candidate, policy):
        self.observations += 1
        if self.ready:
            _, evidence, _ = accepted_evidence()
            binding = {key: candidate[key] for key in ('base', 'upstream', 'head', 'tree', 'policy_sha256', 'questions_sha256')}
            evidence.update(binding=binding, live_base=candidate['base'], live_head=candidate['head'],
                            policy_sha256=policy['sha256'], questions_sha256=policy['questions_sha256'])
            evidence['checks'][0]['head'] = candidate['head']
            evidence['reviews'][0]['commit_id'] = candidate['head']
            evidence.pop('jev')
            if self.drift and self.observations > 1:
                evidence['live_base'] = '0' * 40
            return evidence
        return {'error': 'checks_not_yet_available'}

    def judge(self, repo, candidate, policy):
        if self.ready:
            _, evidence, _ = accepted_evidence()
            evidence['jev']['binding'] = {key: candidate[key] for key in ('base', 'upstream', 'head', 'tree', 'policy_sha256', 'questions_sha256')}
            return evidence['jev']
        raise AssertionError('Do not spend a judgment before hosted gates are present')

    def permit(self, candidate, policy):
        return {'status': 'permitted'}

    def merge(self, repository, number, candidate, policy):
        self.merged.append(candidate)
        if not self.ready:
            raise AssertionError('Missing hosted evidence cannot merge')
        return {'status': 'merged', 'merge_commit': 'a' * 40}


class ControllerTests(unittest.TestCase):
    def test_incomplete_target_inventory_holds_before_publication_from_a_complete_checkout(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            def git(*args):
                return subprocess.check_output(['git', '-C', str(repo), *args], stderr=subprocess.PIPE).decode().strip()
            git('init', '-q', '-b', 'main')
            git('config', 'maintenance.auto', 'false')
            git('config', 'user.name', 'Test Maintainer')
            git('config', 'user.email', 'test@example.invalid')
            (repo / 'README.md').write_text('before\n')
            git('add', '.')
            git('commit', '-qm', 'upstream')
            anchor = git('rev-parse', 'HEAD')
            policy = {'repository': 'nisavid/typesafe-skills', 'target_branch': 'main',
                      'owned_paths': ['.agents/fork-sync.json', 'AGENTS.md'], 'upstream_anchor': anchor,
                      'jev_questions': {}}
            raw = (json.dumps(policy, indent=2) + '\n').encode()
            (repo / '.agents').mkdir()
            (repo / '.agents/fork-sync.json').write_bytes(raw)
            (repo / 'AGENTS.md').write_text('Fork instructions\n')
            git('add', '.')
            git('commit', '-qm', 'complete fork inventory')
            complete_base = git('rev-parse', 'HEAD')
            git('rm', '-q', 'AGENTS.md')
            git('commit', '-qm', 'remove a still-declared fork file')
            damaged_base = git('rev-parse', 'HEAD')
            git('checkout', '-q', '--detach', anchor)
            (repo / 'README.md').write_text('after\n')
            git('add', '.')
            git('commit', '-qm', 'upstream update')
            upstream = git('rev-parse', 'HEAD')
            git('checkout', '-q', '--detach', complete_base)
            before = (git('rev-parse', 'HEAD'), git('status', '--porcelain=v1'),
                      (repo / '.git/index').read_bytes(), git('for-each-ref', '--format=%(refname) %(objectname)'))
            remote = HostedResponses()
            result = reconcile(repo, damaged_base, upstream, raw, repo, services=remote)
            self.assertEqual(result, {'status': 'hold', 'reasons': ['fork-owned file missing: AGENTS.md']})
            self.assertEqual(remote.published, [])
            self.assertEqual(remote.merged, [])
            self.assertEqual((repo / 'AGENTS.md').read_text(), 'Fork instructions\n')
            self.assertEqual((git('rev-parse', 'HEAD'), git('status', '--porcelain=v1'),
                              (repo / '.git/index').read_bytes(), git('for-each-ref', '--format=%(refname) %(objectname)')),
                             before)

    def test_publishes_verified_candidate_and_holds_without_hosted_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            def git(*args):
                return subprocess.check_output(['git', '-C', str(repo), *args], stderr=subprocess.PIPE).decode().strip()
            git('init', '-q', '-b', 'main')
            git('config', 'user.name', 'Test Maintainer')
            git('config', 'user.email', 'test@example.invalid')
            (repo / 'README.md').write_text('before\n')
            git('add', '.'); git('commit', '-qm', 'upstream')
            anchor = git('rev-parse', 'HEAD')
            policy = {'repository': 'nisavid/typesafe-skills', 'target_branch': 'main',
                      'owned_paths': ['.agents/fork-sync.json'], 'upstream_anchor': anchor,
                      'jev_questions': {}, 'required_checks': [{'name': 'sync-ci', 'app_id': 15368}],
                      'jev_model': 'jev-1.13.0', 'jev_min_probability': 0.96, 'coderabbit_user_id': 136622811}
            (repo / '.agents').mkdir()
            raw = (json.dumps(policy, indent=2) + '\n').encode()
            (repo / '.agents/fork-sync.json').write_bytes(raw)
            git('add', '.'); git('commit', '-qm', 'fork policy')
            base = git('rev-parse', 'HEAD')
            git('checkout', '-q', '--detach', anchor)
            (repo / 'README.md').write_text('after\n')
            git('add', '.'); git('commit', '-qm', 'upstream update')
            upstream = git('rev-parse', 'HEAD')
            git('checkout', '-q', '--detach', base)
            remote = HostedResponses()
            result = reconcile(repo, base, upstream, raw, repo, services=remote)
            self.assertEqual(result['status'], 'hold', result)
            self.assertEqual(len(remote.published), 1)
            candidate = remote.published[0]
            self.assertEqual(git('show', candidate['head'] + ':README.md'), 'after')
            self.assertEqual(git('show', candidate['head'] + ':.agents/fork-sync.json'), raw.decode().strip())
            self.assertEqual(remote.merged, [])
            self.assertEqual(git('rev-parse', 'HEAD'), base)
            ready = HostedResponses(ready=True)
            prepared = reconcile(repo, base, upstream, raw, repo, services=ready, phase='prepare')
            self.assertEqual(prepared['status'], 'awaiting_judgment', prepared)
            self.assertEqual(len(prepared['judgment_binding']), 64)
            self.assertEqual(ready.merged, [])
            result = reconcile(repo, base, upstream, raw, repo, services=ready)
            self.assertEqual(result['status'], 'merged', result)
            self.assertEqual(len(ready.merged), 1)
            drifted = HostedResponses(ready=True, drift=True)
            result = reconcile(repo, base, upstream, raw, repo, services=drifted)
            self.assertEqual(result['status'], 'hold', result)
            self.assertEqual(drifted.merged, [])
            changed_policy = json.loads(raw)
            changed_policy['fork_obligations'] = ['unreviewed policy from outside the base']
            remote = HostedResponses()
            result = reconcile(repo, base, upstream, json.dumps(changed_policy).encode(), repo, services=remote)
            self.assertEqual(result['status'], 'hold')
            self.assertEqual(remote.published, [])

            policy['validation_branch'] = 'nisavid/upstream-sync-validation'
            raw = (json.dumps(policy, indent=2) + '\n').encode()
            (repo / '.agents/fork-sync.json').write_bytes(raw)
            git('add', '.'); git('commit', '-qm', 'validation policy')
            base = git('rev-parse', 'HEAD')
            result = reconcile(repo, base, upstream, raw, repo, services=HostedResponses(ready=True),
                               target_branch=policy['validation_branch'], phase='prepare')
            self.assertEqual(result['status'], 'awaiting_judgment', result)
            result = reconcile(repo, base, upstream, raw, repo, services=HostedResponses(ready=True),
                               target_branch='unapproved')
            self.assertEqual(result['status'], 'hold', result)


if __name__ == '__main__':
    unittest.main()
