import contextlib
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.error
import benchmark as b


RESPONSE = dict(done=True, total_duration=4_000_000_000, load_duration=100,
                prompt_eval_count=10, prompt_eval_duration=1_000_000_000,
                eval_count=20, eval_duration=2_000_000_000)


class FakeClient:
    base_url = 'http://example.invalid'

    def __init__(self, fail_at=None, ps_error=False):
        self.calls = []
        self.generations = 0
        self.fail_at = fail_at
        self.ps_error = ps_error

    def request(self, endpoint, payload=None):
        self.calls.append((endpoint, payload))
        if endpoint == '/api/generate':
            self.generations += 1
            if self.generations == self.fail_at:
                raise TimeoutError('simulated timeout')
            return dict(RESPONSE)
        if endpoint == '/api/ps' and self.ps_error:
            raise RuntimeError('unavailable')
        if endpoint in ('/api/ps', '/api/tags'):
            return {'models': [{'name': 'tiny:latest', 'digest': 'sha256:test', 'size': 100, 'size_vram': 40}]}
        return {'version': 'test'}


class BenchmarkTests(unittest.TestCase):
    def scenario(self, **kwargs):
        data = dict(models=['tiny'], threads=[2, 4], gpu_modes=['cpu_only', 'automatic'],
                    repetitions=1, warmup=0, preload=False, unload_before=False)
        data.update(kwargs)
        return b.validate(data)

    def execute(self, client, scenario=None, dry=False):
        with tempfile.TemporaryDirectory(dir=b.ROOT) as tmp:
            directory = Path(tmp)
            with contextlib.redirect_stdout(io.StringIO()):
                manifest = b.run(scenario or self.scenario(), client, directory, dry)
            files = {p.name: p.read_text() for p in directory.iterdir()}
        return manifest, files

    def test_gpu_payloads(self):
        s = self.scenario()
        self.assertEqual(b.payload(s, 'tiny', 2, 'cpu_only')['options']['num_gpu'], 0)
        self.assertNotIn('num_gpu', b.payload(s, 'tiny', 2, 'automatic')['options'])
        self.assertIs(b.payload(s, 'tiny', 2, 'automatic')['stream'], False)

    def test_thinking_and_context_defaults(self):
        scenario = self.scenario()
        self.assertIs(scenario['think'], False)
        self.assertEqual(scenario['num_ctx'], 16384)
        for mode in ('cpu_only', 'automatic'):
            body = b.payload(scenario, 'tiny', 4, mode)
            self.assertIs(body['think'], False)
            self.assertNotIn('think', body['options'])
            self.assertEqual(body['options']['num_ctx'], 16384)

    def test_thinking_and_context_in_all_requests_and_results(self):
        for think, num_ctx in ((False, 16384), (True, 8192)):
            with self.subTest(think=think, num_ctx=num_ctx):
                scenario = self.scenario(think=think, num_ctx=num_ctx,
                                         unload_before=True, preload=True, warmup=1)
                client = FakeClient()
                manifest, files = self.execute(client, scenario)
                for endpoint, body in client.calls:
                    if endpoint != '/api/generate':
                        continue
                    self.assertIs(body['think'], think)
                    self.assertEqual(body['options']['num_ctx'], num_ctx)
                    # CPU-only and automatic must retain their GPU behavior.
                    if 'num_gpu' in body['options']:
                        self.assertEqual(body['options']['num_gpu'], 0)
                for name, text in files.items():
                    if name.startswith('run_'):
                        record = json.loads(text)
                        self.assertIs(record['think'], think)
                        self.assertEqual(record['num_ctx'], num_ctx)
                        if record['gpu_mode'] == 'automatic':
                            self.assertNotIn('num_gpu', record['request']['options'])
                        else:
                            self.assertEqual(record['request']['options']['num_gpu'], 0)
                for config in manifest['plan']:
                    self.assertIs(config['think'], think)
                    self.assertEqual(config['num_ctx'], num_ctx)

    def test_invalid_thinking_and_context(self):
        for key, values in [('think', [0, 1, 'false', None, [], {}]),
                            ('num_ctx', [0, -1, True, False, 16384.0, '16384', None])]:
            for value in values:
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    self.scenario(**{key: value})

    def test_smoke_scenario(self):
        scenario = b.validate(json.loads((b.ROOT / 'scenarios/smoke.json').read_text()))
        self.assertEqual(scenario['models'], ['phi4-mini:3.8b'])
        self.assertEqual(scenario['threads'], [4, 8])
        self.assertEqual(scenario['gpu_modes'], ['cpu_only', 'automatic'])
        self.assertEqual(scenario['repetitions'], 1)
        self.assertIs(scenario['think'], False)
        self.assertEqual(scenario['num_ctx'], 16384)

    def test_cli_dry_run_never_calls_http(self):
        with tempfile.TemporaryDirectory(dir=b.ROOT) as tmp:
            with patch('urllib.request.urlopen', side_effect=AssertionError('HTTP forbidden')) as http:
                with contextlib.redirect_stdout(io.StringIO()):
                    result = b.main(['scenarios/smoke.json', '--output', tmp, '--dry-run'])
                self.assertEqual(result, 0)
                http.assert_not_called()
            archive = next(Path(tmp).iterdir())
            effective = json.loads((archive / 'scenario.json').read_text())
            self.assertIs(effective['think'], False)
            self.assertEqual(effective['num_ctx'], 16384)

    def test_validation(self):
        cases = [dict(threads=[0]), dict(threads=[True]), dict(threads=[2, 2]), dict(models=[]),
                 dict(gpu_modes=['all']), dict(repetitions=0), dict(timeout_seconds=float('nan')),
                 dict(preload='yes'), dict(prompt=''), dict(num_gpu=99)]
        for case in cases:
            with self.subTest(case=case), self.assertRaises(ValueError):
                self.scenario(**case)

    def test_dry_run_no_network_or_measurements(self):
        client = FakeClient()
        manifest, files = self.execute(client, dry=True)
        self.assertEqual(client.calls, [])
        self.assertEqual(manifest['planned_runs'], 4)
        self.assertEqual(manifest['completed_runs'], 0)
        self.assertFalse(any(name.startswith('run_') for name in files))
        self.assertEqual(json.loads(files['summary.json']), [])

    def test_matrix_and_measurements(self):
        client = FakeClient()
        manifest, files = self.execute(client)
        self.assertEqual(manifest['completed_runs'], 4)
        self.assertEqual(manifest['failures'], 0)
        run = json.loads(files['run_00001.json'])
        self.assertEqual(run['tokens_per_second'], 10)
        self.assertEqual(run['prompt_tokens_per_second'], 10)
        self.assertEqual(run['model_digest'], 'sha256:test')
        self.assertEqual(run['digest_source'], 'ps')
        self.assertEqual(run['ps']['data']['models'][0]['size_vram'], 40)
        self.assertIn('tokens_per_second_mean', files['summary.csv'])

    def test_timeout_does_not_abort_series(self):
        manifest, files = self.execute(FakeClient(fail_at=1))
        self.assertEqual(manifest['completed_runs'], 4)
        self.assertEqual(manifest['failures'], 1)
        failed = json.loads(files['run_00001.json'])
        self.assertIn('TimeoutError', failed['error'])
        self.assertTrue(json.loads(files['run_00002.json'])['success'])

    def test_preparation_order(self):
        client = FakeClient()
        self.execute(client, self.scenario(threads=[2], gpu_modes=['cpu_only'],
                     unload_before=True, preload=True, warmup=2, repetitions=2))
        requests = [body for endpoint, body in client.calls if endpoint == '/api/generate']
        self.assertEqual(len(requests), 6)
        self.assertEqual(requests[0]['keep_alive'], 0)
        self.assertEqual(requests[1]['prompt'], '')
        self.assertEqual(requests[2]['prompt'], self.scenario()['prompt'])

    def test_preparation_failure_skips_measurement_and_continues(self):
        client = FakeClient(fail_at=1)
        manifest, files = self.execute(client, self.scenario(unload_before=True))
        self.assertEqual(manifest['failures'], 1)
        self.assertIn('preparation failed', json.loads(files['run_00001.json'])['error'])
        self.assertTrue(json.loads(files['run_00002.json'])['success'])

    def test_ps_failure_falls_back_to_tags(self):
        _, files = self.execute(FakeClient(ps_error=True))
        r = json.loads(files['run_00001.json'])
        self.assertTrue(r['success'])
        self.assertEqual(r['digest_source'], 'tags')
        self.assertIn('unavailable', r['ps']['error'])

    def test_statistics_exclude_errors_and_use_sample_stdev(self):
        base = dict(model='tiny', threads=2, gpu_mode='automatic', success=True)
        rows = [dict(base, tokens_per_second=v) for v in (2, 4, 6)]
        rows.append(dict(base, success=False, tokens_per_second=999))
        summary = b.summarize(rows)[0]
        self.assertEqual(summary['tokens_per_second_mean'], 4)
        self.assertEqual(summary['tokens_per_second_median'], 4)
        self.assertEqual(summary['tokens_per_second_stdev'], 2)
        self.assertEqual(summary['failures'], 1)
        self.assertIsNone(b.summarize(rows[:1])[0]['tokens_per_second_stdev'])

    def test_missing_timings_and_zero_duration(self):
        client = FakeClient()
        original = client.request
        def request(endpoint, payload=None):
            if endpoint == '/api/generate':
                return dict(done=True, eval_count=0, eval_duration=0)
            return original(endpoint, payload)
        client.request = request
        _, files = self.execute(client)
        r = json.loads(files['run_00001.json'])
        self.assertTrue(r['success'])
        self.assertIsNone(r['tokens_per_second'])
        self.assertIsNone(r['total_duration'])

    def test_incomplete_response_is_failure(self):
        client = FakeClient()
        original = client.request
        client.request = lambda endpoint, payload=None: {'done': False} if endpoint == '/api/generate' else original(endpoint, payload)
        manifest, _ = self.execute(client)
        self.assertEqual(manifest['failures'], 4)

    def test_interruption_preserves_manifest(self):
        client = FakeClient()
        client.request = lambda *args: (_ for _ in ()).throw(KeyboardInterrupt())
        # Interrupt during generation, after environment snapshots.
        original = FakeClient().request
        client.request = lambda endpoint, payload=None: (_ for _ in ()).throw(KeyboardInterrupt()) if endpoint == '/api/generate' else original(endpoint, payload)
        with tempfile.TemporaryDirectory(dir=b.ROOT) as tmp:
            with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(KeyboardInterrupt):
                b.run(self.scenario(), client, Path(tmp))
            self.assertEqual(json.loads((Path(tmp)/'manifest.json').read_text())['status'], 'interrupted')

    def test_http_request_and_timeout(self):
        response = io.BytesIO(json.dumps(RESPONSE).encode())
        with patch('urllib.request.urlopen', return_value=response) as opener:
            result = b.Client('http://localhost:11434', 12).request('/api/generate', {'stream': False})
        self.assertTrue(result['done'])
        request = opener.call_args.args[0]
        self.assertEqual(request.method if hasattr(request, 'method') else request.get_method(), 'POST')
        self.assertEqual(opener.call_args.kwargs['timeout'], 12)
        self.assertEqual(json.loads(request.data), {'stream': False})

    def test_http_and_api_errors(self):
        error = urllib.error.HTTPError('http://localhost', 500, 'bad', {}, io.BytesIO(b'failure'))
        with patch('urllib.request.urlopen', side_effect=error), self.assertRaisesRegex(RuntimeError, 'HTTP 500'):
            b.Client('http://localhost', 1).request('/api/ps')
        for response in (b'{"error":"missing model"}', b'[]', b'invalid json'):
            with patch('urllib.request.urlopen', return_value=io.BytesIO(response)), self.assertRaises((ValueError, RuntimeError)):
                b.Client('http://localhost', 1).request('/api/ps')

    def test_api_configuration_precedence(self):
        cases = [({}, [], 'http://127.0.0.1:11434'),
                 ({'OLLAMA_API_URL': 'http://environment.invalid:11434'}, [],
                  'http://environment.invalid:11434'),
                 ({'OLLAMA_API_URL': 'http://environment.invalid:11434'},
                  ['--api-url', 'http://cli.invalid:11434'], 'http://cli.invalid:11434'),
                 ({'OLLAMA_API_URL': ''}, ['--api-url', 'http://cli.invalid:11434'],
                  'http://cli.invalid:11434')]
        for env, flags, expected in cases:
            with self.subTest(env=env, flags=flags), tempfile.TemporaryDirectory(dir=b.ROOT) as tmp:
                with patch.dict(b.os.environ, env, clear=True), patch('urllib.request.urlopen') as http:
                    with contextlib.redirect_stdout(io.StringIO()):
                        result = b.main(['scenarios/smoke.json', '--output', tmp, '--dry-run'] + flags)
                    self.assertEqual(result, 0)
                    http.assert_not_called()
                archive = next(Path(tmp).iterdir())
                data = json.loads((archive / 'environment.json').read_text())
                self.assertEqual(data['api_url'], expected)

    def test_invalid_api_configuration(self):
        for value in ('', 'localhost:11434', 'ftp://example.invalid', 'http://'):
            with self.subTest(value=value), tempfile.TemporaryDirectory(dir=b.ROOT) as tmp:
                with patch.dict(b.os.environ, {'OLLAMA_API_URL': value}, clear=True):
                    with contextlib.redirect_stderr(io.StringIO()), patch('urllib.request.urlopen') as http:
                        self.assertEqual(b.main(['scenarios/smoke.json', '--output', tmp, '--dry-run']), 2)
                        http.assert_not_called()
                self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_output_cannot_escape_project(self):
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(b.main(['scenarios/smoke.json', '--output', '/tmp/outside', '--dry-run']), 2)


if __name__ == '__main__':
    unittest.main()
