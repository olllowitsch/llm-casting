import contextlib
import hashlib
from html.parser import HTMLParser
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import report


class Elements(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags = []
        self.attributes = []
    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        self.attributes.extend(attrs)


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=report.ROOT)
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def archive(self, name='a', records=None):
        d = self.root / name
        d.mkdir()
        (d/'manifest.json').write_text(json.dumps(dict(planned_runs=3, started_at='2026-01-01T00:00:00Z',
                    finished_at='2026-01-01T00:00:10Z', wall_seconds=10, status='complete')))
        (d/'scenario.json').write_text(json.dumps(dict(models=['tiny'], num_ctx=16384, think=False)))
        if records is None:
            records = [self.record(n=20), self.record(n=40), self.record(success=False, error='failure')]
        for i, r in enumerate(records, 1):
            (d/f'run_{i:05d}.json').write_text(json.dumps(r))
        return d

    def record(self, n=20, **overrides):
        r = dict(model='tiny', model_digest='sha256:sample', threads=4, gpu_mode='cpu_only', num_ctx=16384,
                 think=False, success=True, error=None, repetition=1, eval_count=n,
                 eval_duration=2_000_000_000, prompt_eval_count=30, prompt_eval_duration=1_000_000_000)
        r.update(overrides)
        return r

    def document(self, archive):
        output = self.root/'report.html'
        report.generate_report([archive], output)
        return output.read_text()

    def test_statistics_and_units(self):
        archive = report.load_archive(self.archive())
        row = archive['rows'][0]
        self.assertEqual((row['successes'], row['failures']), (2, 1))
        values = row['metrics']['tokens_per_second']
        self.assertEqual(values['mean'], 15)
        self.assertEqual(values['median'], 15)
        self.assertAlmostEqual(values['stdev'], 7.0710678119)
        self.assertEqual(row['metrics']['prompt_tokens_per_second']['mean'], 30)
        self.assertEqual(row['metrics']['eval_seconds']['mean'], 2)
        document = report.render([archive])
        self.assertIn('Generierungsdauer s', document)
        self.assertIn('15.000 / 15.000 / 7.071 (n=2)', document)

    def test_html_escaping_and_no_external_resources(self):
        attack = '<script>alert(1)</script><img src="https://evil.invalid/x" onerror="alert(1)">'
        archive = self.archive(records=[self.record(model=attack, success=False, error=attack, model_digest=attack)])
        document = self.document(archive)
        parser = Elements()
        parser.feed(document)
        self.assertNotIn('script', parser.tags)
        self.assertNotIn('img', parser.tags)
        self.assertIn('&lt;script&gt;', document)
        self.assertFalse(any(k.startswith('on') or k in ('src', 'href') for k, v in parser.attributes))
        self.assertIn("default-src 'none'", document)

    def test_missing_metrics_are_not_zero(self):
        a = report.load_archive(self.archive(records=[self.record(eval_count=None, prompt_eval_duration=0, eval_duration=None)]))
        for key in report.METRICS:
            self.assertIsNone(a['rows'][0]['metrics'][key]['mean'])
        document = report.render([a])
        self.assertIn('— / — / — (n=0)', document)
        self.assertNotIn('nan', document.lower())

    def test_single_sample_stdev_and_zero_tokens(self):
        a = report.load_archive(self.archive(records=[self.record(n=0)]))
        metric = a['rows'][0]['metrics']['tokens_per_second']
        self.assertEqual(metric['mean'], 0)
        self.assertIsNone(metric['stdev'])

    def test_invalid_or_missing_archive(self):
        for name, contents in [('bad', '{'), ('list', '[]'), ('nan', '{"wall_seconds":NaN}')]:
            d = self.archive(name)
            (d/'manifest.json').write_text(contents)
            with self.subTest(name=name), self.assertRaises(ValueError):
                report.load_archive(d)
        d = self.archive('missing')
        (d/'scenario.json').unlink()
        with self.assertRaises(ValueError):
            report.load_archive(d)

    def test_partial_series_and_pending_intent(self):
        d = self.archive(records=[self.record(uncertain_previous_attempts=2)])
        (d/'intent_00002.json').write_text(json.dumps(dict(run_index=2)))
        a = report.load_archive(d)
        self.assertTrue(any('Unvollständige' in w for w in a['warnings']))
        document = report.render([a])
        self.assertIn('Unklare frühere Versuche: 2', document)
        self.assertIn('Offene Versuche: 1', document)
        self.assertIn('Ausgang unklar', document)

    def test_empty_archive(self):
        a = report.load_archive(self.archive(records=[]))
        self.assertEqual(a['rows'], [])
        self.assertIn('Keine Messwerte vorhanden', report.render([a]))

    def test_compare_archives_without_pooling(self):
        a = self.archive('a', records=[self.record(n=20)])
        b = self.archive('b', records=[self.record(n=60, gpu_mode='automatic')])
        output = self.root/'compare.html'
        archives = report.generate_report([a,b], output)
        document = output.read_text()
        self.assertEqual(len(archives), 2)
        self.assertIn('Archiv 1', document)
        self.assertIn('Archiv 2', document)
        self.assertIn('10.000 tokens/s', document)
        self.assertIn('30.000 tokens/s', document)
        self.assertIn('width:33.333%', document)
        self.assertIn('width:100.000%', document)
        self.assertIn('GPU-Nutzung nicht garantiert', document)

    def test_digest_and_context_are_separate_groups(self):
        a = report.load_archive(self.archive(records=[self.record(), self.record(model_digest='other'), self.record(num_ctx=8192)]))
        self.assertEqual(len(a['rows']), 3)

    def test_no_network_and_source_files_unchanged(self):
        a = self.archive()
        before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in a.iterdir()}
        with patch('socket.socket', side_effect=AssertionError('network forbidden')):
            document = self.document(a)
        self.assertIn('Benchmarkbericht', document)
        after = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in a.iterdir()}
        self.assertEqual(before, after)

    def test_private_metadata_is_not_disclosed(self):
        a = self.archive(records=[self.record(success=False, error='server example.internal http://example.internal:11434 /home/private/data 192.168.9.8')])
        (a/'environment.json').write_text(json.dumps(dict(runner_host='example.internal', api_url='http://example.internal:11434')))
        document = self.document(a)
        for secret in ('example.internal', '/home/private', '192.168.9.8', str(a)):
            self.assertNotIn(secret, document)

    def test_corrupt_checksum_and_identity(self):
        for record in (self.record(record_sha256='bad'), self.record(run_index=2), self.record(success='yes')):
            with tempfile.TemporaryDirectory(dir=self.root) as tmp:
                d = Path(tmp)
                (d/'manifest.json').write_text('{}')
                (d/'scenario.json').write_text('{}')
                (d/'run_00001.json').write_text(json.dumps(record))
                with self.assertRaises(ValueError):
                    report.load_archive(d)

    def test_output_paths_and_overwrite(self):
        a = self.archive()
        original = (a/'manifest.json').read_bytes()
        for output in (a/'report.html', report.ROOT/'results/report.html', self.root/'bad.json', Path('/tmp/report.html')):
            with self.subTest(output=output), self.assertRaises(ValueError):
                report.generate_report([a], output)
        self.assertEqual((a/'manifest.json').read_bytes(), original)
        output = self.root/'existing.html'
        output.write_text('original')
        with self.assertRaises(ValueError):
            report.generate_report([a], output)
        self.assertEqual(output.read_text(), 'original')

    def test_cli_and_duplicate_archives(self):
        a = self.archive()
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(report.main([str(a), '-o', str(self.root/'cli.html')]), 0)
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(report.main([str(a), str(a), '-o', str(self.root/'dup.html')]), 2)


if __name__ == '__main__':
    unittest.main()
