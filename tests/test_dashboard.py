import base64
import contextlib
import hashlib
from html.parser import HTMLParser
import io
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import dashboard as d
import report


class Parser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags, self.attrs = [], []
    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        self.attrs.extend(attrs)


class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=d.ROOT)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.results = self.root/'results'
        self.results.mkdir()

    def archive(self, name='a', records=None, planned=None, status='complete', dry=False):
        directory = self.results/name
        directory.mkdir()
        records = [self.record()] if records is None else records
        scenario = dict(models=['tiny'], prompt='CONFIDENTIAL_PROMPT', num_ctx=16384, think=False)
        manifest = dict(planned_runs=len(records) if planned is None else planned, status=status, dry_run=dry,
                        started_at='2026-01-01T01:00:00Z', finished_at='2026-01-01T01:00:10Z', wall_seconds=10)
        (directory/'scenario.json').write_text(json.dumps(scenario))
        (directory/'manifest.json').write_text(json.dumps(manifest))
        for i,record in enumerate(records,1):
            (directory/f'run_{i:05d}.json').write_text(json.dumps(record))
        return directory

    def record(self, **overrides):
        r = dict(model='tiny', model_digest='sha256:one', threads=4, gpu_mode='cpu_only', num_ctx=16384,
                 think=False, success=True, error=None, eval_count=20, eval_duration=2_000_000_000,
                 prompt_eval_count=10, prompt_eval_duration=1_000_000_000, repetition=1,
                 started_at='2026-01-01T01:00:02Z')
        r.update(overrides)
        if 'request' not in overrides:
            options = dict(num_thread=r['threads'], num_ctx=r['num_ctx'], num_predict=64, seed=42, temperature=0)
            if r['gpu_mode'] == 'cpu_only':
                options['num_gpu'] = 0
            r['request'] = dict(model=r['model'], prompt='CONFIDENTIAL_PROMPT', stream=False, think=r['think'],
                                keep_alive='5m', options=options)
        return r

    def generate(self, selected=None):
        output = self.root/'dashboard.html'
        entries = d.generate_dashboard(selected, output, self.results)
        return entries, output.read_text()

    def test_empty_results_and_missing_results(self):
        entries, html = self.generate()
        self.assertEqual(d.overview(entries)['archives'], 0)
        self.assertIn('Keine Archive gefunden', html)
        self.assertIn('Keine Messkonfigurationen', html)
        self.assertEqual(d.discover(results=self.root/'absent'), [])

    def test_multiple_archives_overview_and_details(self):
        a = self.archive('a')
        b = self.archive('b', records=[self.record(gpu_mode='automatic', threads=8), self.record(success=False, error='failed')])
        entries, html = self.generate()
        totals = d.overview(entries)
        self.assertEqual(totals['archives'], 2)
        self.assertEqual(totals['models'], 1)
        self.assertEqual(totals['complete'], 2)
        self.assertEqual(totals['success'], 2)
        self.assertEqual(totals['failures'], 1)
        self.assertEqual(totals['pending'], 0)
        self.assertIn('href="#archive-1"', html)
        self.assertIn('id="archive-2"', html)
        self.assertIn('Fehlgeschlagene Messung;', html)
        self.assertIn('10.000 / 10.000 / — (n=1)', html)

    def test_interrupted_series_and_dry_run(self):
        self.archive('interrupted', planned=4, status='interrupted')
        self.archive('dry', records=[], planned=4, dry=True)
        entries, html = self.generate()
        totals = d.overview(entries)
        self.assertEqual(totals['interrupted'], 1)
        self.assertEqual(totals['dry'], 1)
        self.assertEqual(totals['pending'], 3)
        self.assertIn('Offen / unterbrochen', html)

    def test_invalid_archive_is_visible_and_excluded(self):
        self.archive('good')
        bad = self.archive('bad')
        (bad/'manifest.json').write_text('{broken')
        entries, html = self.generate()
        self.assertEqual(d.overview(entries)['invalid'], 1)
        self.assertEqual(d.overview(entries)['success'], 1)
        self.assertIn('Aus allen Statistiken ausgeschlossen', html)
        self.assertIn('Archiv beschädigt', html)

    def test_digest_prompt_and_context_are_not_mixed(self):
        r1 = self.record()
        r2 = self.record(model_digest='sha256:two')
        r3 = self.record()
        r3['request']['prompt'] = 'ANOTHER_SECRET_PROMPT'
        r4 = self.record(num_ctx=8192)
        directory = self.archive(records=[r1,r2,r3,r4])
        entries, html = self.generate()
        rows = entries[0]['rows']
        self.assertEqual(len(rows), 4)
        self.assertEqual(len({r['family'] for r in rows}), 4)
        self.assertNotIn('CONFIDENTIAL_PROMPT', html)
        self.assertNotIn('ANOTHER_SECRET_PROMPT', html)
        self.assertIn('Zwischen Gruppen: nicht vergleichbar', html)

    def test_cpu_gpu_threads_comparable_without_pooling(self):
        self.archive('cpu', records=[self.record()])
        self.archive('gpu', records=[self.record(threads=8, gpu_mode='automatic', eval_count=60)])
        entries, html = self.generate()
        self.assertEqual(entries[0]['rows'][0]['family'], entries[1]['rows'][0]['family'])
        self.assertEqual(entries[0]['rows'][0]['metrics']['tokens_per_second']['mean'], 10)
        self.assertEqual(entries[1]['rows'][0]['metrics']['tokens_per_second']['mean'], 30)
        self.assertIn('width:33.333%', html)
        self.assertIn('Serverhardware unbestätigt', html)

    def test_unknown_metadata_has_no_comparability(self):
        self.archive(records=[self.record(request=None), self.record(model_digest=None)])
        entries, html = self.generate()
        self.assertTrue(all(not r['comparable'] for r in entries[0]['rows']))
        self.assertIn('Nicht vergleichbar: Metadaten fehlen', html)

    def test_server_hardware_is_not_runner_hardware(self):
        a = self.archive('a')
        b = self.archive('b')
        (a/'environment.json').write_text(json.dumps(dict(runner_host='secret-runner', server_hardware={'gpu':'gpu-a'})))
        (b/'environment.json').write_text(json.dumps(dict(runner_host='secret-runner', server_hardware={'gpu':'gpu-b'})))
        entries, html = self.generate()
        self.assertNotEqual(entries[0]['hardware'], entries[1]['hardware'])
        self.assertEqual(entries[0]['rows'][0]['family'], entries[1]['rows'][0]['family'])
        self.assertNotIn('secret-runner', html)
        self.assertNotIn('gpu-a', html)

    def test_xss_security_policy_and_private_data(self):
        attack = '<script>alert(1)</script><img src=x onerror=alert(2)>'
        record = self.record(model=attack, success=False,
                             error='password=SUPERSECRET http://internal.invalid:11434 /home/private/file CONFIDENTIAL_PROMPT')
        record['response'] = {'response':'<script>EVIL_RESPONSE()</script>'}
        archive = self.archive(records=[record])
        (archive/'environment.json').write_text(json.dumps(dict(runner_host='internal.invalid', api_url='http://internal.invalid:11434')))
        entries, html = self.generate()
        parser = Parser()
        parser.feed(html)
        self.assertEqual(parser.tags.count('script'), 1)
        self.assertNotIn('img', parser.tags)
        self.assertIn('&lt;script&gt;', html)
        self.assertFalse(any(k.startswith('on') or k == 'src' for k,v in parser.attrs))
        self.assertTrue(all(v.startswith('#') for k,v in parser.attrs if k == 'href'))
        script_hash = base64.b64encode(hashlib.sha256(d.SCRIPT.encode()).digest()).decode()
        self.assertIn('sha256-'+script_hash, html)
        for private in ('SUPERSECRET', 'internal.invalid', '/home/private', 'CONFIDENTIAL_PROMPT', 'EVIL_RESPONSE', 'file://', str(archive)):
            self.assertNotIn(private, html)
        self.assertNotIn('innerHTML', d.SCRIPT)
        self.assertNotIn('fetch(', d.SCRIPT)

    def test_sensitive_model_label_redaction(self):
        self.archive(records=[self.record(model='token=SUPERSECRET /home/private/model')])
        _, html = self.generate()
        self.assertNotIn('SUPERSECRET', html)
        self.assertNotIn('/home/private', html)

    def test_no_network_or_modification(self):
        a = self.archive()
        before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in a.iterdir()}
        with patch('socket.socket', side_effect=AssertionError('network forbidden')):
            self.generate()
        after = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in a.iterdir()}
        self.assertEqual(before, after)

    def test_selection_output_and_cli(self):
        a = self.archive('a')
        self.archive('b')
        entries, _ = self.generate([a])
        self.assertEqual(len(entries), 1)
        with self.assertRaises(ValueError):
            d.discover([a,a])
        for output in (Path('/tmp/dashboard.html'), a/'dashboard.html', self.results/'dashboard.html', self.root/'report.py'):
            with self.subTest(output=output), self.assertRaises(ValueError):
                d.generate_dashboard([a], output, results=self.results)
        with self.assertRaises(ValueError):
            d.generate_dashboard([a], self.root/'dashboard.html')
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(d.main([str(a), '-o', str(self.root/'cli.html')]), 0)
        bad = self.archive('bad')
        (bad/'scenario.json').write_text('[]')
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(d.main([str(bad), '-o', str(self.root/'bad.html')]), 1)

    def test_latest_uses_chronology_and_excludes_dry_run(self):
        self.archive('early', records=[self.record(started_at='2026-01-01T01:00:00+02:00')])
        self.archive('late', records=[self.record(started_at='2026-01-01T00:00:00Z')])
        dry = self.archive('dry', records=[], dry=True)
        m = json.loads((dry/'manifest.json').read_text())
        m['started_at'] = '2099-01-01T00:00:00Z'
        (dry/'manifest.json').write_text(json.dumps(m))
        entries = d.collect(d.discover(results=self.results))
        self.assertEqual(d.overview(entries)['latest'][0].isoformat(), '2026-01-01T00:00:00+00:00')

    def test_options_and_thinking_separate_workloads(self):
        first = self.record()
        seed = self.record()
        seed['request']['options']['seed'] = 99
        thinking = self.record(think=True)
        self.archive(records=[first, seed, thinking])
        entries, _ = self.generate()
        self.assertEqual(len({r['family'] for r in entries[0]['rows']}), 3)

    def test_unknown_plan_and_inconsistent_request(self):
        a = self.archive('unknown')
        manifest = json.loads((a/'manifest.json').read_text())
        manifest.pop('planned_runs')
        (a/'manifest.json').write_text(json.dumps(manifest))
        mismatch = self.record()
        mismatch['request']['options']['num_ctx'] = 8192
        self.archive('invalid', records=[mismatch])
        entries, html = self.generate()
        totals = d.overview(entries)
        self.assertEqual(totals['pending_unknown'], 1)
        self.assertEqual(totals['invalid'], 1)
        self.assertIn('Plananzahl fehlt', html)

    def test_symlink_outputs_and_archive_selection(self):
        a = self.archive()
        link = self.root/'linked.html'
        link.symlink_to(a/'hidden.html')
        with self.assertRaises(ValueError):
            d.generate_dashboard([a], link)
        archive_link = self.results/'linked-archive'
        archive_link.symlink_to(a, target_is_directory=True)
        with self.assertRaises(ValueError):
            d.discover([archive_link])

    @unittest.skipUnless(shutil.which('node'), 'Optional Node executable unavailable; no runtime JS engine in Python stdlib')
    def test_real_javascript_filter_sort_and_missing_values(self):
        # Execute the exact shipped script with a minimal offline DOM, no npm dependencies.
        harness = '''
const fixture = [
 {id:'a',dataset:{model:'m1',mode:'cpu_only',status:'complete',speed:'10',runtime:'5'}},
 {id:'b',dataset:{model:'m2',mode:'automatic',status:'interrupted',speed:'30',runtime:'2'}},
 {id:'c',dataset:{model:'m1',mode:'automatic',status:'complete',speed:'',runtime:''}},
 {id:'d',dataset:{model:'m1',mode:'automatic',status:'complete',speed:'0',runtime:'9'}}];
const elements = {};
['model-filter','mode-filter','status-filter'].forEach(k=>elements[k]={value:'',addEventListener(){}});
elements['sort-order']={value:'archive',addEventListener(){}};
elements['visible-count']={};
const tbody={querySelectorAll(){return fixture;},appendChild(){}};
const document={querySelector(){return tbody;},getElementById(id){return elements[id];}};
'''
        checks = '''
function ids(model, mode, status, sort){return selectRows(fixture,model,mode,status,sort).map(r=>r.id);}
const output = [ids('m1','automatic','complete','speed-desc'),ids('','','','speed-desc'),
 ids('','','','speed-asc'),ids('','','','runtime-desc'),ids('','','','runtime-asc'),
 ids('','','','archive'),ids('none','','','speed-desc')];
elements['model-filter'].value='m2';update();
output.push(fixture.filter(r=>!r.hidden).map(r=>r.id));
console.log(JSON.stringify(output));
'''
        process = subprocess.run([shutil.which('node'), '-e', harness+d.SCRIPT+checks],
                                 capture_output=True, text=True, timeout=10, check=True)
        actual = json.loads(process.stdout)
        self.assertEqual(actual, [['d','c'],['b','a','d','c'],['d','a','b','c'],['d','a','b','c'],
                                  ['b','a','d','c'],['a','b','c','d'],[],['b']])


if __name__ == '__main__':
    unittest.main()
