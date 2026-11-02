"""Synthetic S6 fixtures. Every test denies network and real process startup."""
import copy
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import uuid

import definitions as d
import planning as p
import workspaces as w
import opencode_adapter as a

ROOT = Path(__file__).resolve().parents[1]
S1 = ROOT/'tests/fixtures/definitions/valid'
S2 = ROOT/'tests/fixtures/planning'


class Case(unittest.TestCase):
    def setUp(self):
        for target in ('urllib.request.urlopen', 'urllib.request.OpenerDirector.open',
                       'socket.socket', 'socket.create_connection', 'subprocess.Popen',
                       'os.system', 'os.posix_spawn', 'os.posix_spawnp', 'os.fork', 'os.execve'):
            guard = patch(target, side_effect=AssertionError('external operation forbidden'))
            guard.start();self.addCleanup(guard.stop)
        self.tmp = tempfile.TemporaryDirectory(dir=ROOT);self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name);self.root = self.folder/'simulation.local'
        self.c = d.load_json(S1/'competition.json');self.r = d.load_json(S1/'rubric.json')
        self.config = d.load_json(S2/'config.json')
        self.config['run_id'] = str(uuid.uuid4())
        self.config['engine'] = dict(version=a.REFERENCE_VERSION, source_sha256=d.content_sha256(a.build_manifest()))
        self.config['participants'][0]['adapter_version'] = a.REFERENCE_ADAPTER
        self.config['participants'][0]['model']['revision_digest'] = 'a'*64
        self.plan = self.make_plan()
        self.identity = p.new_attempt_identity(self.plan, self.config['participants'][0]['participant_id'], 1)
        self.private = dict(profile=a.PROFILE, provider='ollama', model='example-model', model_digest='a'*64,
                            endpoint='http://127.0.0.1:11434/v1', tools=['read_reference', 'write_output'],
                            network='deny', resources=dict(cpu_seconds=60, memory_bytes=67108864, wall_seconds=60))

    def make_plan(self, assets=S1/'assets'):
        return p.create_run_plan(self.c, self.r, self.config, asset_root=assets)

    def store(self):
        store = w.WorkspaceStore(self.root).__enter__();self.addCleanup(store.__exit__)
        return store

    def adapter(self):
        store = self.store();adapter = a.OpenCodeAdapter(store, self.plan)
        self.binding = adapter.prepare(self.identity, self.private, asset_root=S1/'assets')
        return adapter

    def frame(self, number, kind, data=None, session='ses_fixture'):
        return d.canonical_json_bytes(dict(profile=a.PROFILE, sequence=number, type=kind,
                                           session_id=session, data={} if data is None else data))

    def frames(self, binding=None):
        binding = binding or getattr(self, 'binding', None) or a.bind(self.plan, self.identity, self.private)
        start = {k: binding['config'][k] for k in ('provider', 'model', 'model_digest')}
        start['binding_sha256'] = d.content_sha256(binding)
        return (self.frame(1, 'started', start), self.frame(2, 'completed'))

    def fail(self, code, function, *args, **kwargs):
        with self.assertRaises(d.DefinitionError) as caught:
            function(*args, **kwargs)
        if code:
            self.assertEqual(caught.exception.code, code)

    def change(self, **values):
        config = copy.deepcopy(self.private);config.update(values)
        return config

    def result(self, end=a.FakeEnd(), frames=None):
        adapter = self.adapter()
        output = adapter.simulate(self.identity, self.private,
                                  a.FakeTransport(self.frames() if frames is None else frames, end))
        return adapter, output, output['result']['executions'][0]['execution']

    def snapshot(self):
        return {str(f.relative_to(self.root)): f.read_bytes() for f in self.root.rglob('*') if f.is_file()}


class BindingTests(Case):
    def test_profile_and_pins(self):
        binding = a.bind(self.plan, self.identity, self.private)
        self.assertFalse(binding['executable']);self.assertTrue(binding['simulation_only'])
        self.assertEqual(binding['prompt'], self.c['prompt']);self.assertEqual(binding['inputs'], self.c['assets'])
        self.assertEqual(binding['identity']['plan_sha256'], self.plan.sha256)
        self.assertEqual(binding['competition']['definition_revision'], self.c['definition_revision'])
        self.assertEqual(binding['discipline'], 'performance');self.assertIsNone(binding['upstream_binary_version'])

    def test_missing_provider_is_not_defaulted(self):
        config = self.change();del config['provider']
        self.fail(None, a.bind, self.plan, self.identity, config)

    def test_provider_fallback_forbidden(self):
        for provider in ('openai', '', None, 'anthropic', 'default'):
            with self.subTest(provider=provider):
                self.fail('opencode_provider_binding_invalid', a.bind, self.plan, self.identity,
                          self.change(provider=provider))

    def test_no_ambient_credentials_or_configuration(self):
        with patch.dict(os.environ, {'OPENCODE_CONFIG': '/unreadable/secret',
                                    'OPENCODE_CONFIG_CONTENT': 'invalid', 'OPENAI_API_KEY': 'synthetic-test-value'}):
            self.assertEqual(a.bind(self.plan, self.identity, self.private)['config'], self.private)

    def test_models_and_digests_explicit(self):
        for change in (dict(model='other'), dict(model_digest=None), dict(model_digest='b'*64)):
            self.fail('opencode_model_binding_invalid', a.bind, self.plan, self.identity, self.change(**change))

    def test_only_explicit_loopback_provider_endpoint(self):
        for url in ('https://cloud.invalid/v1', 'http://localhost:11434/v1', 'http://127.0.0.1/v1',
                    'http://user:pass@127.0.0.1:11434/v1', 'http://127.0.0.1:11434/v1?token=x',
                    'file:///private', 'http://127.0.0.1:bad/v1', ''):
            with self.subTest(url=url):
                self.fail('opencode_endpoint_invalid', a.bind, self.plan, self.identity, self.change(endpoint=url))

    def test_unknown_configuration_cannot_enable_execution(self):
        for key in ('force', 'unsafe', 'enable', 'environment', 'command', 'isolation_verified'):
            self.fail(None, a.bind, self.plan, self.identity, self.change(**{key: True}))

    def test_resource_limits_are_typed_positive_and_plan_bounded(self):
        for key, value in (('cpu_seconds', True), ('memory_bytes', 0), ('wall_seconds', 601), ('wall_seconds', '60')):
            config = self.change();config['resources'][key] = value
            self.fail(None, a.bind, self.plan, self.identity, config)

    def test_network_policy_and_tools_are_explicit(self):
        for change in (dict(network='allow'), dict(tools=['bash']), dict(tools=['read_reference']*2),
                       dict(tools=[{}]), dict(tools='read_reference')):
            self.fail(None, a.bind, self.plan, self.identity, self.change(**change))

    def test_protocol_version_rejected(self):
        self.fail('opencode_profile_unsupported', a.bind, self.plan, self.identity, self.change(profile='future-v2'))

    def test_real_s4_plan_is_not_relabelled_opencode(self):
        config = copy.deepcopy(self.config);config['engine']['version'] = 's4-v1'
        plan = p.create_run_plan(self.c, self.r, config, asset_root=S1/'assets')
        self.fail('simulation_reference_required', a.bind, plan, self.identity, self.private)

    def test_missing_build_and_model_pins(self):
        for target in ('engine', 'model'):
            config = copy.deepcopy(self.config)
            if target == 'engine':config['engine']['source_sha256'] = None
            else:config['participants'][0]['model']['revision_digest'] = None
            plan = p.create_run_plan(self.c, self.r, config, asset_root=S1/'assets')
            self.fail('simulation_reference_required', a.bind, plan, self.identity, self.private)

    def test_plan_identity_drift(self):
        identity = copy.deepcopy(self.identity);identity['plan_sha256'] = 'f'*64
        self.fail('identity_plan_mismatch', a.bind, self.plan, identity, self.private)

    def test_prompt_hash_drift_and_revision_binding(self):
        self.c['prompt']['text'] += 'different'
        self.fail('prompt_hash_mismatch', self.make_plan)
        self.c['prompt']['sha256'] = d.hashlib.sha256(self.c['prompt']['text'].encode()).hexdigest()
        changed = self.make_plan()
        self.assertNotEqual(changed.sha256, self.plan.sha256)
        self.fail('identity_plan_mismatch', a.bind, changed, self.identity, self.private)

    def test_asset_integrity(self):
        assets = self.folder/'inputs';assets.mkdir();(assets/'input.txt').write_text('changed', encoding='utf-8')
        self.fail(None, p.validate_run_plan, self.plan.as_dict(), self.c, self.r, asset_root=assets)

    def test_coding_remains_unsupported_by_normative_profiles(self):
        self.c['discipline'] = 'coding'
        self.fail('discipline_unsupported', self.make_plan)


class ProtocolTests(Case):
    def parse(self, frames):
        return a.decode_events(frames, a.bind(self.plan, self.identity, self.private))

    def test_valid_normalized_json_and_session(self):
        frames = self.frames();result = self.parse(frames)
        self.assertEqual(result[0]['session_id'], 'ses_fixture');self.assertEqual(result[-1]['type'], 'completed')

    def test_duplicate_keys_float_nan_bom_and_invalid_utf8(self):
        for raw in (b'{"x":1,"x":2}', b'{"x":0.1}', b'{"x":NaN}', b'\xef\xbb\xbf{}', b'\xff', b'{'):
            with self.subTest(raw=raw):self.fail(None, self.parse, (raw,))

    def test_unknown_events_and_fields(self):
        self.fail('opencode_event_unknown', self.parse, (self.frame(1, 'shell'),))
        event = d.parse_json_bytes(self.frames()[0]);event['command'] = 'forbidden'
        self.fail(None, self.parse, (d.canonical_json_bytes(event),))

    def test_wrong_event_profile(self):
        event = d.parse_json_bytes(self.frames()[0]);event['profile'] = 'opencode-unknown'
        self.fail('opencode_profile_unsupported', self.parse, (d.canonical_json_bytes(event),))

    def test_event_size_and_total_and_count_limits(self):
        self.fail('opencode_frame_limit', self.parse, (b'x'*(a.MAX_FRAME_BYTES+1),))
        self.fail('opencode_event_limit', self.parse, (b'{}',)*(a.MAX_EVENTS+1))
        self.fail('opencode_trace_limit', self.parse, (b'x'*a.MAX_FRAME_BYTES,)*9)

    def test_event_sequence_and_session_changes(self):
        start = self.frames()[0]
        self.fail('opencode_sequence_invalid', self.parse, (start, self.frame(True, 'completed')))
        self.fail('opencode_session_changed', self.parse, (start, self.frame(2, 'completed', session='ses_other')))
        self.fail('opencode_session_invalid', self.parse, (self.frame(1, 'started', {}, session='../../bad'),))

    def test_start_required_and_cannot_repeat(self):
        self.fail('opencode_start_missing', self.parse, (self.frame(1, 'completed'),))
        event = d.parse_json_bytes(self.frames()[0]);event['sequence'] = 2
        self.fail('opencode_start_duplicate', self.parse, (self.frames()[0], d.canonical_json_bytes(event)))

    def test_start_binding_and_provider_echo(self):
        for key in ('provider', 'model', 'model_digest', 'binding_sha256'):
            event = d.parse_json_bytes(self.frames()[0]);event['data'][key] = 'changed'
            self.fail('opencode_started_binding_mismatch', self.parse, (d.canonical_json_bytes(event),))

    def test_terminal_event_not_repeated(self):
        self.fail('opencode_event_after_terminal', self.parse, self.frames()+(self.frame(3, 'completed'),))

    def test_text_is_data_not_code(self):
        frames = (self.frames()[0], self.frame(2, 'text', {'text': '<script>invalid()</script>'}), self.frame(3, 'completed'))
        self.assertIn('<script>', self.parse(frames)[1]['data']['text'])

    def test_tool_requests_are_symbolic_not_executed(self):
        for capability, area, path in (('read_reference', 'inputs', 'input.txt'), ('write_output', 'outputs', 'answer.py')):
            frames = (self.frames()[0], self.frame(2, 'tool', dict(capability=capability, area=area, path=path)))
            self.assertEqual(self.parse(frames)[-1]['type'], 'tool')

    def test_host_secret_traversal_and_unknown_inputs_denied(self):
        for area, path in (('host', 'input.txt'), ('inputs', '/etc/passwd'), ('inputs', '../secret'),
                           ('inputs', '.ssh/id_rsa'), ('inputs', 'journals/run.json'), ('inputs', 'unknown')):
            self.fail(None, self.parse, (self.frames()[0], self.frame(2, 'tool',
                      dict(capability='read_reference', area=area, path=path))))

    def test_shell_and_network_tools_denied(self):
        for tool in ('bash', 'webfetch', 'shell', 'task'):
            self.fail('opencode_tool_denied', self.parse, (self.frames()[0], self.frame(2, 'tool',
                      dict(capability=tool, area='outputs', path='answer.txt'))))

    def test_model_cannot_supply_process_end_proof(self):
        self.fail(None, self.parse, (self.frames()[0], self.frame(2, 'completed', {'tree': 'stopped'})))


class SimulationTests(Case):
    def test_success_and_s2_projection_no_invented_metrics(self):
        adapter, output, execution = self.result()
        self.assertEqual(execution['status'], 'succeeded');self.assertTrue(output['simulation_only'])
        self.assertFalse(output['executable']);self.assertEqual(output['result']['progress']['successful_slots'], 1)
        self.assertTrue(all(v is None for v in execution['metrics'].values()))
        self.assertEqual(execution['provenance']['adapter_version'], a.REFERENCE_ADAPTER)
        self.assertEqual(len(execution['artifacts']), 3)
        self.assertTrue(all(x['classification'] == 'private' for x in execution['artifacts']))
        self.assertEqual(adapter.project(), output)

    def test_archived_build_inventory_and_explicit_selector(self):
        adapter, _, execution = self.result()
        archived = next(x for x in execution['artifacts'] if x['path'].endswith('/binding.json'))
        binding = d.parse_json_bytes(adapter.store._read(archived['path']))
        self.assertEqual(binding['model_selector'], 'ollama/example-model')
        self.assertEqual(binding['engine_build'], a.build_manifest())
        self.assertEqual(d.content_sha256(binding['engine_build']), binding['engine']['source_sha256'])

    def test_optional_trusted_journal_head(self):
        adapter, output, _ = self.result()
        self.assertEqual(adapter.project(expected_head=output['journal_head_sha256']), output)
        self.fail('journal_head_mismatch', adapter.project, expected_head='b'*64)

    def test_simulation_cannot_be_consumed_as_real_s4_run(self):
        import ollama_adapter
        import assessment
        adapter, _, _ = self.result()
        coordinator = ollama_adapter.RunCoordinator(adapter.store, self.plan)
        self.fail('engine_build_mismatch', coordinator.run, None)
        with self.assertRaises((d.DefinitionError, OSError)):
            assessment.verify_run(adapter.store, self.plan)

    def test_confirmed_result_is_idempotent_and_source_preserved(self):
        adapter, output, _ = self.result();before = self.snapshot()
        self.assertEqual(adapter.simulate(self.identity, self.private, object()), output)
        self.assertEqual(self.snapshot(), before)

    def test_confirmed_success_survives_reopen(self):
        adapter, output, _ = self.result();adapter.store.__exit__()
        with w.WorkspaceStore(self.root) as store:
            reopened = a.OpenCodeAdapter(store, self.plan)
            self.assertEqual(reopened.project(), output)
            self.assertEqual(reopened.simulate(self.identity, self.private, object()), output)

    def test_prestart_error_has_no_fake_start_or_success(self):
        _, output, execution = self.result(a.FakeEnd('prestart_error', 'not_started', None), ())
        self.assertEqual(execution['status'], 'cancelled');self.assertIsNone(execution['started_at'])
        self.assertEqual(execution['error']['code'], 'fake_prestart_error')
        self.assertEqual(output['result']['progress']['successful_slots'], 0)

    def test_error_after_start_intent_is_uncertain(self):
        _, output, execution = self.result(a.FakeEnd('start_error', 'unknown', None))
        self.assertEqual(execution['status'], 'uncertain');self.assertEqual(output['result']['status'], 'interrupted')

    def test_confirmed_timeout(self):
        _, _, execution = self.result(a.FakeEnd('timeout', 'stopped', 137))
        self.assertEqual(execution['status'], 'timed_out');self.assertIsNotNone(execution['finished_at'])

    def test_timeout_is_not_stop_proof(self):
        _, output, execution = self.result(a.FakeEnd('timeout', 'active', None))
        self.assertEqual(execution['status'], 'uncertain');self.assertIsNone(execution['finished_at'])
        self.assertEqual(output['result']['progress']['terminal_slots'], 0)

    def test_disconnected_transport(self):
        _, _, execution = self.result(a.FakeEnd('contact_lost', 'unknown', None))
        self.assertEqual(execution['status'], 'uncertain')

    def test_cancel_request_without_end(self):
        _, _, execution = self.result(a.FakeEnd('cancel', 'active', None))
        self.assertEqual(execution['status'], 'uncertain')

    def test_confirmed_cancel(self):
        _, _, execution = self.result(a.FakeEnd('cancel', 'stopped', 143))
        self.assertEqual(execution['status'], 'cancelled')

    def test_remaining_children_prevent_success(self):
        _, _, execution = self.result(a.FakeEnd('complete', 'active', 0))
        self.assertEqual(execution['status'], 'uncertain')

    def test_unknown_tree_prevents_success(self):
        _, _, execution = self.result(a.FakeEnd('complete', 'unknown', None))
        self.assertEqual(execution['status'], 'uncertain')

    def test_lost_final_ack_prevents_success(self):
        _, _, execution = self.result(a.FakeEnd('lost_ack', 'stopped', 0))
        self.assertEqual(execution['status'], 'uncertain')

    def test_process_failure_is_not_success(self):
        _, output, execution = self.result(a.FakeEnd('process_error', 'stopped', 2))
        self.assertEqual(execution['status'], 'failed');self.assertEqual(output['result']['progress']['failed_slots'], 1)

    def test_error_event_and_exit_zero_are_not_success(self):
        adapter = self.adapter()
        frames = (self.frames()[0], self.frame(2, 'error', {'code': 'provider_error'}))
        output = adapter.simulate(self.identity, self.private, a.FakeTransport(frames))
        self.assertEqual(output['result']['executions'][0]['execution']['status'], 'failed')

    def test_invalid_event_retains_uncertainty_on_replay(self):
        adapter, output, execution = self.result(frames=(b'{',))
        self.assertEqual(execution['status'], 'uncertain');self.assertEqual(adapter.project(), output)

    def test_completed_json_without_exit_proof_is_uncertain(self):
        _, _, execution = self.result(a.FakeEnd('complete', 'stopped', None))
        self.assertEqual(execution['status'], 'uncertain')

    def test_no_terminal_event_is_not_success(self):
        adapter = self.adapter()
        output = adapter.simulate(self.identity, self.private, a.FakeTransport(self.frames()[:1]))
        self.assertEqual(output['result']['executions'][0]['execution']['status'], 'failed')

    def test_injected_live_transport_is_denied_before_intent(self):
        adapter = self.adapter();before = self.snapshot()
        self.fail('fake_transport_required', adapter.simulate, self.identity, self.private, lambda: None)
        self.assertEqual(self.snapshot(), before)

    def test_unstarted_prepared_projection(self):
        adapter = self.adapter();execution = adapter.project()['result']['executions'][0]['execution']
        self.assertEqual(execution['status'], 'planned');self.assertIsNone(execution['started_at'])

    def test_interruption_after_durable_intent_never_replays_transport(self):
        adapter = self.adapter();original = adapter.store._json
        def interrupt(path, value):
            if path.endswith('/observation.json'):raise KeyboardInterrupt()
            return original(path, value)
        with patch.object(adapter.store, '_json', side_effect=interrupt):
            with self.assertRaises(KeyboardInterrupt):adapter.simulate(self.identity, self.private, a.FakeTransport(self.frames()))
        adapter.store.__exit__()
        with w.WorkspaceStore(self.root) as store:
            reopened = a.OpenCodeAdapter(store, self.plan)
            self.assertEqual(reopened.project()['result']['executions'][0]['execution']['status'], 'uncertain')
            self.fail('simulation_outcome_uncertain', reopened.simulate,
                      self.identity, self.private, a.FakeTransport(self.frames()))

    def test_new_attempt_same_slot_after_uncertainty_denied(self):
        adapter, _, _ = self.result(a.FakeEnd('contact_lost', 'unknown', None))
        identity = p.new_attempt_identity(self.plan, self.identity['participant_id'], 1)
        self.fail('simulation_outcome_uncertain', adapter.prepare, identity, self.private, asset_root=S1/'assets')

    def test_no_automatic_new_attempt_after_success(self):
        adapter, _, _ = self.result()
        identity = p.new_attempt_identity(self.plan, self.identity['participant_id'], 1)
        self.fail('measurement_slot_duplicate', adapter.prepare, identity, self.private, asset_root=S1/'assets')

    def test_binding_changes_after_prepare_denied(self):
        adapter = self.adapter()
        self.fail('simulation_binding_changed', adapter.simulate, self.identity,
                  self.change(tools=['read_reference']), a.FakeTransport(self.frames()))

    def test_lost_storage_ack_never_retries(self):
        adapter = self.adapter()
        def crash(stage):
            if stage == 'published_before_fsync':raise KeyboardInterrupt()
        with patch.object(w, '_checkpoint', side_effect=crash):
            with self.assertRaises(KeyboardInterrupt):adapter.simulate(self.identity, self.private, a.FakeTransport(self.frames()))
        adapter.store.__exit__()
        with w.WorkspaceStore(self.root) as store:
            reopened = a.OpenCodeAdapter(store, self.plan)
            self.fail('simulation_outcome_uncertain', reopened.simulate,
                      self.identity, self.private, a.FakeTransport(self.frames()))

    def test_separate_workspaces_identical_inputs_and_prompts(self):
        second = copy.deepcopy(self.config['participants'][0]);second['participant_id'] = str(uuid.uuid4())
        second['parameters']['threads'] = 8;self.config['participants'].append(second);self.plan = self.make_plan()
        self.identity = p.new_attempt_identity(self.plan, self.config['participants'][0]['participant_id'], 1)
        adapter = self.adapter()
        identity = p.new_attempt_identity(self.plan, second['participant_id'], 1)
        binding = adapter.prepare(identity, self.change(tools=['read_reference']), asset_root=S1/'assets')
        self.assertEqual(binding['prompt'], self.binding['prompt']);self.assertEqual(binding['inputs'], self.binding['inputs'])
        self.assertNotEqual(binding['config']['tools'], self.binding['config']['tools'])
        self.assertNotEqual(adapter._base(identity), adapter._base(self.identity))
        for i in (identity, self.identity):
            copied = self.root/w._base(i, 'workspaces')/'inputs/input.txt'
            self.assertEqual(copied.read_bytes(), (S1/'assets/input.txt').read_bytes())

    def test_symlink_and_hardlink_outputs_denied(self):
        adapter = self.adapter();output = self.root/adapter._base(self.identity)
        source = self.folder/'synthetic.txt';source.write_bytes(b'synthetic')
        for kind in ('symlink', 'hardlink'):
            link = output/'foreign'
            if kind == 'symlink':link.symlink_to(source)
            else:os.link(source, link)
            try:self.fail(None, adapter.project)
            finally:link.unlink()

    def test_tampered_archived_artifact_detected(self):
        adapter, _, execution = self.result();path = self.root/execution['artifacts'][0]['path']
        path.chmod(0o600);path.write_bytes(b'corrupt')
        self.fail(None, adapter.project)

    def test_prepared_other_slot_cannot_start_after_uncertainty(self):
        self.config['repetitions'] = 2;self.plan = self.make_plan()
        self.identity = p.new_attempt_identity(self.plan, self.config['participants'][0]['participant_id'], 1)
        adapter = self.adapter()
        second = p.new_attempt_identity(self.plan, self.identity['participant_id'], 2)
        adapter.prepare(second, self.private, asset_root=S1/'assets')
        adapter.simulate(self.identity, self.private,
                         a.FakeTransport(self.frames(), a.FakeEnd('contact_lost', 'unknown', None)))
        self.fail('simulation_outcome_uncertain', adapter.simulate, second, self.private, a.FakeTransport(()))

    def test_changed_workspace_inputs_detected(self):
        adapter = self.adapter();source = self.root/w._base(self.identity, 'workspaces')/'inputs/input.txt'
        source.chmod(0o600);source.write_bytes(b'changed')
        self.fail(None, adapter.project)

    def test_partial_collection_is_never_automatically_resumed(self):
        adapter = self.adapter();archive = adapter.store.archive_artifacts
        with patch.object(adapter.store, 'archive_artifacts', side_effect=KeyboardInterrupt()):
            with self.assertRaises(KeyboardInterrupt):
                adapter.simulate(self.identity, self.private, a.FakeTransport(self.frames()))
        self.assertEqual(adapter.project()['result']['executions'][0]['execution']['status'], 'uncertain')
        with patch.object(adapter.store, 'archive_artifacts', wraps=archive) as called:
            self.fail('simulation_outcome_uncertain', adapter.simulate, self.identity, self.private, a.FakeTransport(()))
            called.assert_not_called()

    def test_original_old_fixtures_unchanged(self):
        protected = [ROOT/'benchmark.py', ROOT/'report.py', ROOT/'dashboard.py', ROOT/'casting.py', ROOT/'assessment.py']
        protected += list((ROOT/'tests/fixtures').rglob('*.json'))
        protected += [f for area in ('results', 'reports') for f in (ROOT/area).rglob('*') if f.is_file()]
        before = {f: f.read_bytes() for f in protected}
        self.result()
        self.assertTrue(all(f.read_bytes() == content for f, content in before.items()))


class GateTests(Case):
    def test_default_deny_and_no_force_bypass(self):
        self.assertFalse(a.safety_gate()['executable'])
        for kwargs in ({}, dict(force=True), dict(unsafe=True), dict(enable=True), dict(isolation_verified=True)):
            self.fail('opencode_execution_disabled', a.execute, **kwargs)
            self.fail('opencode_execution_disabled', a.OpenCodeAdapter.execute, **kwargs)

    def test_cancel_api_cannot_signal_real_process(self):
        self.fail('opencode_execution_disabled', a.request_cancel, pid=1)

    def test_all_local_operations_succeed_with_external_functions_forbidden(self):
        self.result()
        self.assertFalse(a.safety_gate()['os_isolation_verified'])


if __name__ == '__main__':
    unittest.main()
