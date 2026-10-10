"""Run the sync controller; absence of activation always leaves the fork alone."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess


def _reconcile(args):
    mode = os.environ.get('FORK_SYNC_MODE', 'off')
    if mode not in ('validation', 'production'):
        return {'status': 'hold', 'reasons': ['unsupported-mode']}
    if not args.provingkit or any((args.base, args.upstream, args.policy)):
        return {'status': 'hold', 'reasons': ['invalid-reconcile-arguments']}
    controller = Path(__file__).resolve().parents[1]
    if args.repo.resolve() != controller:
        return {'status': 'hold', 'reasons': ['untrusted-controller-path']}
    if args.evidence_dir and args.evidence_dir.resolve().is_relative_to(controller):
        return {'status': 'hold', 'reasons': ['evidence-directory-inside-controller']}
    approved = os.environ.get('FORK_SYNC_APPROVED_REVISION', '')
    if not re.fullmatch('[0-9a-f]{40}', approved):
        return {'status': 'hold', 'reasons': ['controller-not-approved']}
    env = {key: value for key, value in os.environ.items() if not key.startswith('GIT_')}
    env['GIT_NO_REPLACE_OBJECTS'] = '1'

    def git(*command):
        return subprocess.run(
            ['git', '-C', str(controller), '-c', 'core.hooksPath=/dev/null',
             '-c', 'credential.helper=', '-c', 'credential.interactive=false',
             '-c', 'protocol.allow=never', '-c', 'protocol.https.allow=always', *command],
            env=env, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60,
        ).stdout

    head = git('rev-parse', '--verify', 'HEAD^{commit}').strip().decode()
    if head != approved or git('status', '--porcelain=v1', '--untracked-files=all'):
        return {'status': 'hold', 'reasons': ['controller-not-clean-approved-revision']}
    policy_bytes = git('show', head + ':.agents/fork-sync.json')
    if (controller / '.agents/fork-sync.json').read_bytes() != policy_bytes:
        return {'status': 'hold', 'reasons': ['controller-policy-changed']}
    policy = json.loads(policy_bytes)
    repository_pattern = r'[A-Za-z0-9_][A-Za-z0-9_.-]*/[A-Za-z0-9_][A-Za-z0-9_.-]*'
    if (not isinstance(policy, dict) or not isinstance(policy.get('repository'), str)
            or not re.fullmatch(repository_pattern, policy['repository'])
            or not isinstance(policy.get('upstream_url'), str)
            or not re.fullmatch('https://github[.]com/' + repository_pattern + '[.]git', policy['upstream_url'])
            or policy.get('target_branch') != 'main'
            or policy.get('validation_branch') != 'nisavid/upstream-sync-validation'):
        return {'status': 'hold', 'reasons': ['unsupported-repository-policy']}
    for branch in (policy['target_branch'], policy['validation_branch'], policy['upstream_branch']):
        if not isinstance(branch, str) or not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_./-]*', branch):
            return {'status': 'hold', 'reasons': ['invalid-policy-branch']}
        git('check-ref-format', 'refs/heads/' + branch)
    owned = policy['owned_paths']
    if not isinstance(owned, list) or not all(isinstance(path, str) for path in owned) or len(set(owned)) != len(owned):
        return {'status': 'hold', 'reasons': ['invalid-owned-paths']}
    required = {'.agents/fork-sync.json'} | {
        str(path.relative_to(controller)) for path in (controller / 'fork_sync').glob('*.py')}
    if not required.issubset(owned):
        return {'status': 'hold', 'reasons': ['controller-files-not-owned']}
    for name in owned:
        parts = name.split('/')
        if any(not re.fullmatch(r'[A-Za-z0-9_.][A-Za-z0-9_.-]*', part)
               or part in ('.', '..') or part.lower() == '.git' for part in parts):
            return {'status': 'hold', 'reasons': ['invalid-owned-paths']}
        path = controller / name
        if any(parent.is_symlink() for parent in [path, *path.parents] if parent != controller.parent):
            return {'status': 'hold', 'reasons': ['owned-file-symlink']}
        entry = git('ls-tree', '-z', head, '--', name)
        if not entry:
            return {'status': 'hold', 'reasons': ['owned-file-untracked']}
        metadata, tracked_name = entry.rstrip(b'\0').split(b'\t', 1)
        file_mode, kind, oid = metadata.split()
        if (kind != b'blob' or file_mode not in (b'100644', b'100755')
                or tracked_name.decode() != name or not path.is_file()
                or bool(path.stat().st_mode & 0o111) != (file_mode == b'100755')
                or path.read_bytes() != git('cat-file', 'blob', oid.decode())):
            return {'status': 'hold', 'reasons': ['owned-file-changed']}
    try:
        rewrites = git('config', '--name-only', '--get-regexp', r'^url\..*\.(insteadof|pushinsteadof)$')
    except subprocess.CalledProcessError as error:
        if error.returncode != 1:
            raise
        rewrites = b''
    if rewrites:
        return {'status': 'hold', 'reasons': ['git-url-rewriting-configured']}
    target = policy['validation_branch'] if mode == 'validation' else policy['target_branch']
    origin = 'https://github.com/' + policy['repository'] + '.git'
    git('fetch', '--no-tags', '--no-recurse-submodules', origin,
        '+refs/heads/' + target + ':refs/fork-sync/target')
    git('fetch', '--no-tags', '--no-recurse-submodules', policy['upstream_url'],
        '+refs/heads/' + policy['upstream_branch'] + ':refs/fork-sync/upstream')
    base = git('rev-parse', '--verify', 'refs/fork-sync/target^{commit}').strip().decode()
    upstream = git('rev-parse', '--verify', 'refs/fork-sync/upstream^{commit}').strip().decode()
    from .controller import reconcile
    return reconcile(controller, base, upstream, policy_bytes, args.provingkit,
                     target_branch=target, evidence_dir=args.evidence_dir, phase=args.phase)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['plan', 'reconcile'])
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--base')
    parser.add_argument('--upstream')
    parser.add_argument('--policy', type=Path)
    parser.add_argument('--provingkit', type=Path)
    parser.add_argument('--evidence-dir', type=Path)
    parser.add_argument('--phase', choices=['prepare', 'finalize'], default='prepare')
    args = parser.parse_args()
    if args.command == 'plan':
        if not all((args.base, args.upstream, args.policy)):
            parser.error('plan requires --base, --upstream, and --policy')
        from .git_candidate import construct
        result = construct(args.repo, args.base, args.upstream,
                           json.loads(args.policy.read_text()))
        print(json.dumps(result, sort_keys=True))
        return 2 if result['status'] == 'hold' else 0
    if os.environ.get('FORK_SYNC_MODE', 'off') == 'off':
        print(json.dumps({'status': 'disabled'}))
        return 0
    try:
        result = _reconcile(args)
    except (OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError):
        result = {'status': 'hold', 'reasons': ['configuration-or-hosted-operation-failed']}
    print(json.dumps(result, sort_keys=True))
    return 2 if result['status'] in ('hold', 'unknown') else 0


if __name__ == '__main__':
    raise SystemExit(main())
