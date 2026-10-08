"""Verify the admitted source surface and retained qualification evidence."""
import hashlib
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class PolicyTests(unittest.TestCase):
    def test_policy_retains_the_approved_question_and_explicit_fork_surface(self):
        policy = json.loads((ROOT / '.agents/fork-sync.json').read_text())
        questions = (json.dumps(policy['jev_questions'], indent=2, ensure_ascii=False) + '\n').encode()
        self.assertEqual(hashlib.sha256(questions).hexdigest(),
                         '20aa3418577d02efa61115f71062cffcad98ef14334dda1887b69001ad49c48a')
        self.assertEqual(policy['jev_model'], 'jev-1.13.0')
        self.assertEqual(policy['jev_min_probability'], 0.96)
        self.assertEqual(policy['required_checks'], [{'name': 'sync-ci', 'app_id': 15368}])
        self.assertEqual(policy['coderabbit_user_id'], 136622811)
        owned = policy['owned_paths']
        self.assertEqual(len(owned), len(set(owned)))
        for path in owned:
            self.assertTrue((ROOT / path).is_file(), path)
        self.assertTrue(set(str(path.relative_to(ROOT)) for path in (ROOT / 'fork_sync').glob('*.py')).issubset(owned))
        self.assertTrue(set(owned).isdisjoint(policy['publication_categories']))
        self.assertEqual(policy['target_branch'], 'main')
        self.assertEqual(policy['validation_branch'], 'nisavid/upstream-sync-validation')

    def test_retained_bytes_reproduce_the_published_heldout_result(self):
        directory = ROOT / 'docs/agents/qualification'
        for name, digest in json.loads((directory / 'SHA256SUMS.json').read_text()).items():
            self.assertEqual(hashlib.sha256((directory / name).read_bytes()).hexdigest(), digest, name)
        records = json.loads((directory / 'raw-records.json').read_text())
        for name, record in records.items():
            self.assertEqual(hashlib.sha256(record['utf8'].encode()).hexdigest(), record['sha256'], name)
        cases = json.loads((directory / 'cases.json').read_text())
        counts = {'ordinary': 0, 'accepted': 0, 'hold': 0, 'false_pass': 0}
        for case in cases:
            observation = json.loads(records['observations/' + case['id'] + '.json']['utf8'])
            state = records['states/' + case['id'] + '.json']
            self.assertEqual(observation['state_sha256'], state['sha256'])
            raw = observation['response']['raw'][0]
            self.assertIs(raw['cached'], False)
            self.assertEqual(raw['model'], 'jev-1.13.0')
            if case['split'] != 'heldout' or case['id'] == 'heldout-real-historical-release':
                continue
            answer = raw['answers']['additional_handling']
            accepted = answer['choice'] == 'no_additional_handling' and answer['probabilities']['no_additional_handling'] >= 0.96
            if case['expected'] == 'no_additional_handling':
                counts['ordinary'] += 1
                counts['accepted'] += accepted
            else:
                counts['hold'] += 1
                counts['false_pass'] += accepted
        self.assertEqual(counts, {'ordinary': 7, 'accepted': 5, 'hold': 16, 'false_pass': 0})


if __name__ == '__main__':
    unittest.main()
