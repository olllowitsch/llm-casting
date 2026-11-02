"""S6 protocol simulation only. No process, socket, live transport or coding executor.

The normative S2 v1 plan still supports only Ollama performance. Its separately
labelled synthetic reference plans test status/storage projection, not OpenCode
execution. See docs/S6_OPENCODE_ADAPTER.md before using this private profile.
"""
from dataclasses import dataclass
import os
import re
from urllib.parse import urlsplit
import ipaddress

import definitions as d
import planning as p
import workspaces as w

PROFILE = 'casting-opencode-simulation-v1'
REFERENCE_VERSION = 's6-simulation-only'
REFERENCE_ADAPTER = 's6-reference-only'
MAX_FRAME_BYTES = 65536
MAX_EVENTS = 128
MAX_TRACE_BYTES = 524288
FILES = ('binding.json', 'start-intent.json', 'observation.json')


def _need(ok, code):
    d.require(ok, code)


def safety_gate():
    """No caller-supplied booleans, environment settings or plug-ins grant trust."""
    return dict(executable=False, os_isolation_verified=False,
                binary_version_verified=False, coding_plan_supported=False,
                reasons=['os_executor_not_accepted', 'opencode_wire_protocol_unverified',
                         'coding_plan_profile_unavailable'])


def execute(*_args, **_kwargs):
    """Always deny, including force/unsafe/enable/isolation=True arguments."""
    raise d.DefinitionError('opencode_execution_disabled')


def request_cancel(*_args, **_kwargs):
    """Future live cancellation requires an authenticated executor handle."""
    raise d.DefinitionError('opencode_execution_disabled')


def build_manifest():
    parent = d._open_directory(w.ROOT)
    try:
        return dict(version=REFERENCE_VERSION, files=[
            dict(path=name, sha256=d.hashlib.sha256(d._read_fd(parent, name, 1048576)[0]).hexdigest())
            for name in ('opencode_adapter.py', 'definitions.py', 'planning.py', 'workspaces.py')])
    finally:
        os.close(parent)


def _reference(plan):
    value = p._context(plan)
    _need(value['engine'] == dict(version=REFERENCE_VERSION,
          source_sha256=d.content_sha256(build_manifest())), 'simulation_reference_required')
    _need(all(x['adapter_version'] == REFERENCE_ADAPTER and x['model']['revision_digest']
              for x in value['participants']), 'simulation_reference_required')
    _need(value['policy']['network_allowed'] is False, 'simulation_network_forbidden')
    return value


def bind(plan, identity, config):
    """Pin an explicit, non-executable candidate; never consume ambient settings.

    config is private operator data, not a portable plan or OpenCode config file.
    No CLI command is constructed, and no environment/credential file is read.
    """
    value = _reference(plan);identity = w._identity(identity, plan)
    config = p._copy(config)
    d._object(config, ('profile', 'provider', 'model', 'model_digest', 'endpoint',
                      'tools', 'network', 'resources'), '$.config')
    _need(config['profile'] == PROFILE, 'opencode_profile_unsupported')
    participant = next(x for x in value['participants'] if x['participant_id'] == identity['participant_id'])
    _need(config['provider'] == 'ollama' and config['provider'] == participant['provider'],
          'opencode_provider_binding_invalid')
    _need(config['model'] == participant['model']['name'] and
          config['model_digest'] == participant['model']['revision_digest'], 'opencode_model_binding_invalid')
    _need(type(config['endpoint']) is str, 'opencode_endpoint_invalid')
    try:
        url = urlsplit(config['endpoint'])
        allowed = (url.scheme == 'http' and url.port is not None and url.port > 0 and
                   ipaddress.ip_address(url.hostname).is_loopback and url.path == '/v1' and
                   not url.username and not url.password and not url.query and not url.fragment)
    except (ValueError, TypeError):
        allowed = False
    _need(allowed, 'opencode_endpoint_invalid')
    tools = config['tools'];d._list(tools, '$.tools')
    _need(len(tools) == len(set(x for x in tools if type(x) is str)) and
          all(type(x) is str and x in ('read_reference', 'write_output') for x in tools),
          'opencode_tool_policy_invalid')
    _need(config['network'] == 'deny', 'opencode_network_policy_invalid')
    resources = config['resources']
    d._object(resources, ('cpu_seconds', 'memory_bytes', 'wall_seconds'), '$.resources')
    for number in resources.values():
        _need(type(number) is int and number > 0, 'opencode_resource_limit_invalid')
    _need(resources['wall_seconds'] <= value['limits']['attempt_deadline_seconds'] and
          resources['wall_seconds'] <= value['limits']['run_deadline_seconds'], 'opencode_deadline_invalid')
    manifest = build_manifest()
    _need(d.content_sha256(manifest) == value['engine']['source_sha256'], 'simulation_reference_required')
    return dict(kind='opencode_simulation_binding', profile=PROFILE, simulation_only=True,
                executable=False, identity=identity, competition=value['competition'],
                discipline=plan.competition()['discipline'], inputs=plan.competition()['assets'],
                prompt=plan.competition()['prompt'], reference_parameters=participant['parameters'],
                config=config, model_selector=config['provider']+'/'+config['model'],
                engine=value['engine'], engine_build=manifest, upstream_binary_version=None)


def decode_events(frames, binding):
    """Strict, bounded normalized fixture protocol, NOT a verified OpenCode wire decoder.

    Executor end proofs are deliberately absent from this untrusted event stream.
    """
    _need(type(frames) is tuple and len(frames) <= MAX_EVENTS, 'opencode_event_limit')
    _need(all(type(raw) is bytes for raw in frames), 'opencode_frame_invalid')
    _need(sum(map(len, frames)) <= MAX_TRACE_BYTES, 'opencode_trace_limit')
    result = [];session = None;terminal = False
    for number, raw in enumerate(frames, 1):
        _need(len(raw) <= MAX_FRAME_BYTES, 'opencode_frame_limit')
        event = d.parse_json_bytes(raw)
        d._object(event, ('profile', 'sequence', 'type', 'session_id', 'data'), '$.event')
        _need(event['profile'] == PROFILE, 'opencode_profile_unsupported')
        _need(type(event['sequence']) is int and event['sequence'] == number, 'opencode_sequence_invalid')
        _need(type(event['session_id']) is str and
              re.fullmatch(r'ses_[A-Za-z0-9]{1,80}', event['session_id']), 'opencode_session_invalid')
        _need(not terminal, 'opencode_event_after_terminal')
        kind = event['type'];data = event['data']
        _need(type(kind) is str and kind in ('started', 'text', 'tool', 'completed', 'error'),
              'opencode_event_unknown')
        if number == 1:
            _need(kind == 'started', 'opencode_start_missing')
            session = event['session_id']
        _need(event['session_id'] == session, 'opencode_session_changed')
        if kind == 'started':
            _need(number == 1, 'opencode_start_duplicate')
            d._object(data, ('provider', 'model', 'model_digest', 'binding_sha256'), '$.event.data')
            expected = {key: binding['config'][key] for key in ('provider', 'model', 'model_digest')}
            expected['binding_sha256'] = d.content_sha256(binding)
            _need(data == expected, 'opencode_started_binding_mismatch')
        elif kind == 'text':
            d._object(data, ('text',), '$.event.data')
            _need(type(data['text']) is str, 'opencode_text_invalid')
        elif kind == 'tool':
            d._object(data, ('capability', 'area', 'path'), '$.event.data')
            tool = data['capability']
            _need(type(tool) is str and tool in binding['config']['tools'], 'opencode_tool_denied')
            _need(data['area'] == {'read_reference': 'inputs', 'write_output': 'outputs'}[tool],
                  'opencode_host_access_denied')
            parts = d._asset_path(data['path'])
            _need(not any(x.startswith('.') or x in ('journals', 'artifacts', 'workspaces',
                      'ssh', 'secrets', 'credentials', 'config') for x in parts), 'opencode_host_access_denied')
            if tool == 'read_reference':
                _need(data['path'] in {x['path'] for x in binding['inputs']}, 'opencode_input_unknown')
            # Symbolic requests only: never open a path or run a tool from an event.
        elif kind == 'completed':
            d._object(data, (), '$.event.data');terminal = True
        else:
            d._object(data, ('code',), '$.event.data')
            _need(type(data['code']) is str and re.fullmatch(r'[a-z][a-z0-9_]{0,79}', data['code']),
                  'opencode_error_invalid')
            terminal = True
        result.append(event)
    return result


@dataclass(frozen=True)
class FakeEnd:
    """Trusted TEST fixture, never accepted as real isolation/end attestation."""
    reason: str = 'complete'
    tree: str = 'stopped'
    exit_code: object = 0

    def validate(self):
        _need(self.reason in ('complete', 'prestart_error', 'start_error', 'timeout',
                             'contact_lost', 'cancel', 'lost_ack', 'process_error'), 'fake_reason_invalid')
        _need(self.tree in ('not_started', 'stopped', 'active', 'unknown'), 'fake_tree_invalid')
        _need(self.exit_code is None or type(self.exit_code) is int and 0 <= self.exit_code <= 255,
              'fake_exit_invalid')
        _need((self.reason == 'prestart_error') == (self.tree == 'not_started'), 'fake_end_inconsistent')
        _need(self.tree != 'not_started' or self.exit_code is None, 'fake_end_inconsistent')


@dataclass(frozen=True)
class FakeTransport:
    """Data only: no injected callbacks, executable, environment or live connection."""
    frames: tuple = ()
    end: FakeEnd = FakeEnd()


def _observation(transport, binding):
    _need(type(transport) is FakeTransport and type(transport.end) is FakeEnd, 'fake_transport_required')
    transport.end.validate()
    end = transport.end;error = None;events = []
    try:
        events = decode_events(transport.frames, binding)
    except d.DefinitionError as exc:
        error = exc.code
    if error:
        status = 'uncertain'
    elif end.reason == 'prestart_error' and not events:
        status = 'cancelled';error = 'fake_prestart_error'
    elif end.tree != 'stopped' or end.exit_code is None or end.reason in ('lost_ack', 'contact_lost', 'start_error'):
        status = 'uncertain';error = 'fake_' + end.reason
    elif end.reason == 'timeout':
        status = 'timed_out';error = 'fake_timeout'
    elif end.reason == 'cancel':
        status = 'cancelled';error = 'fake_cancel'
    elif end.exit_code != 0 or end.reason == 'process_error':
        status = 'failed';error = 'fake_process_error'
    elif events and events[-1]['type'] == 'completed':
        status = 'succeeded'
    else:
        status = 'failed';error = 'fake_protocol_incomplete'
    return dict(profile=PROFILE, simulation_only=True, status=status, error=error,
                events=events, end=dict(vars(end)), binding_sha256=d.content_sha256(binding), at=w._now())


class OpenCodeAdapter:
    """One-attempt simulation adapter over S3, not a scheduler or live executor."""
    execute = staticmethod(execute)
    request_cancel = staticmethod(request_cancel)

    def __init__(self, store, reference_plan):
        _need(type(store) is w.WorkspaceStore, 'workspace_store_required')
        _reference(reference_plan)
        self.store = store;self.plan = reference_plan

    def _base(self, identity):
        return w._base(w._identity(identity, self.plan), 'workspaces') + '/outputs'

    def prepare(self, identity, config, *, asset_root=None, rubric_asset_root=None):
        binding = bind(self.plan, identity, config)
        self.store.register_run(self.plan, asset_root=asset_root, rubric_asset_root=rubric_asset_root)
        # In contrast to S3 storage-only archived, an uncertain simulated outcome
        # must block further starts throughout this run as well as this slot.
        for rec in self.store.inspect(self.plan)['state']['attempts']:
            if rec['identity'] != identity:
                _need(self._inspect_one(rec)['status'] != 'uncertain', 'simulation_outcome_uncertain')
        self.store.prepare(self.plan, identity)
        base = self._base(identity);names = self.store._names(base)
        if not names:
            self.store._json(base+'/binding.json', binding)
        else:
            _need(self.store._json_read(base+'/binding.json') == binding, 'simulation_binding_changed')
        return p._copy(binding)

    def simulate(self, identity, config, transport):
        """Persist intent BEFORE examining fake events. Never retry an existing intent."""
        binding = bind(self.plan, identity, config)
        _, rec = self.store._record(self.plan, identity)
        base = self._base(identity)
        _need(self.store._json_read(base+'/binding.json') == binding, 'simulation_binding_changed')
        if rec['status'] == 'archived':
            return self.project()  # No consumption of another transport, no double count.
        for other in self.store.inspect(self.plan)['state']['attempts']:
            if other['identity'] != identity:
                _need(self._inspect_one(other)['status'] != 'uncertain', 'simulation_outcome_uncertain')
        _need(rec['status'] == 'prepared' and self.store._names(base) == ['binding.json'],
              'simulation_outcome_uncertain')
        _need(type(transport) is FakeTransport and type(transport.end) is FakeEnd, 'fake_transport_required')
        transport.end.validate()
        self.store._json(base+'/start-intent.json', dict(profile=PROFILE, simulation_only=True,
                         binding_sha256=d.content_sha256(binding), at=w._now()))
        observation = _observation(transport, binding)
        self.store._json(base+'/observation.json', observation)
        self.store.collect(self.plan, identity, [dict(path=name, media_type='application/json') for name in FILES])
        return self.project()

    def _inspect_one(self, rec):
        identity = rec['identity'];base = self._base(identity)
        files, _ = self.store._tree(base)
        _need(set(files) <= set(FILES), 'simulation_uncommitted_files')
        binding = self.store._json_read(base+'/binding.json')
        _need(type(binding) is dict and type(binding.get('config')) is dict, 'simulation_binding_invalid')
        _need(binding == bind(self.plan, identity, binding['config']), 'simulation_binding_changed')
        intent = None
        if 'start-intent.json' in files:
            intent = self.store._json_read(base+'/start-intent.json')
            d._object(intent, ('profile', 'simulation_only', 'binding_sha256', 'at'), '$.intent')
            _need(intent['profile'] == PROFILE and intent['simulation_only'] is True and
                  intent['binding_sha256'] == d.content_sha256(binding), 'simulation_intent_invalid')
            p._timestamp(intent['at'])
        report = dict(identity=identity, status='uncertain' if intent else 'planned',
                      binding=binding, started_at=intent['at'] if intent else None,
                      finished_at=None, error='simulation_outcome_uncertain' if intent else None, artifacts=[])
        if rec['status'] != 'archived':
            _need('observation.json' not in files or intent is not None, 'simulation_intent_missing')
            return report
        _need(set(files) == set(FILES) and intent is not None, 'simulation_archive_incomplete')
        manifest = self.store.validate_archive(self.plan, identity, expected_manifest=rec['manifest_sha256'])
        observation = self.store._json_read(base+'/observation.json')
        d._object(observation, ('profile', 'simulation_only', 'status', 'error', 'events', 'end',
                               'binding_sha256', 'at'), '$.observation')
        d._object(observation['end'], ('reason', 'tree', 'exit_code'), '$.end')
        frames = tuple(d.canonical_json_bytes(x) for x in observation['events'])
        replay = _observation(FakeTransport(frames, FakeEnd(**observation['end'])), binding)
        # A rejected stream is not retained as a valid trace. Its archived outcome
        # remains uncertain, never a fabricated successful replay.
        if observation['status'] != 'uncertain':
            _need({k: v for k, v in observation.items() if k != 'at'} ==
                  {k: v for k, v in replay.items() if k != 'at'}, 'simulation_observation_invalid')
        else:
            _need(observation['profile'] == PROFILE and observation['simulation_only'] is True and
                  observation['binding_sha256'] == d.content_sha256(binding) and
                  type(observation['error']) is str and
                  re.fullmatch(r'[a-z][a-z0-9_]{0,79}', observation['error']), 'simulation_observation_invalid')
        _need(p._timestamp(observation['at']) >= p._timestamp(intent['at']), 'simulation_time_invalid')
        report.update(status=observation['status'], error=observation['error'], artifacts=manifest['artifacts'])
        if report['status'] != 'uncertain':
            report['finished_at'] = observation['at']
        if observation['end']['reason'] == 'prestart_error' and report['status'] == 'cancelled':
            report['started_at'] = None
        return report

    def project(self, *, expected_head=None):
        """S2 structural/status projection inside a mandatory simulation wrapper.

        It is not a production OpenCode result, performance measurement or score.
        Unknown metrics stay null. S3 archived means stored, not process ended.
        """
        _reference(self.plan)
        journal = self.store.validate_journal(self.plan, expected_head=expected_head)
        result = p.initial_result(self.plan)
        bundle = self.store._json_read('journals/'+self.plan.as_dict()['run_id']+'/bundle.json')
        result['created_at'] = bundle['initial_result']['created_at']
        wrappers = []
        for rec in journal['state']['attempts']:
            info = self._inspect_one(rec);identity = info['identity']
            participant = next(x for x in self.plan.as_dict()['participants']
                               if x['participant_id'] == identity['participant_id'])
            artifacts = info['artifacts'];refs = [a['artifact_id'] for a in artifacts]
            execution = dict(kind='execution', schema_version=1, **identity,
                             status=info['status'], started_at=info['started_at'], finished_at=info['finished_at'],
                             metrics={key: None for key in p.METRICS}, artifacts=artifacts,
                             provenance=dict(engine=self.plan.as_dict()['engine'], adapter_version=REFERENCE_ADAPTER,
                                             model_revision_digest=participant['model']['revision_digest'], evidence=refs),
                             error=None if info['error'] is None else dict(code=info['error'], phase='simulation',
                                                                         retryable=False, evidence=refs),
                             supersedes_attempt_id=None)
            execution = p.validate_execution(execution, self.plan)
            wrappers.append(dict(execution=execution, sha256=d.content_sha256(execution)))
        result['executions'] = wrappers
        result['progress'] = p._progress(wrappers, self.plan)[0]
        statuses = [x['execution']['status'] for x in wrappers]
        result['status'] = ('interrupted' if 'uncertain' in statuses else
                            'completed' if not result['progress']['pending_slots'] else
                            'running' if any(s != 'planned' for s in statuses) else 'planned')
        # S2 does not permit planned with planned executions; prepared fixtures
        # are represented by a running series with unstarted attempts.
        if wrappers and result['status'] == 'planned':
            result['status'] = 'running'
        times = [result['created_at']] + [t for x in wrappers for t in
                 (x['execution']['started_at'], x['execution']['finished_at']) if t is not None]
        result['updated_at'] = max(times, key=p._timestamp)
        return dict(profile=PROFILE, simulation_only=True, executable=False,
                    journal_head_sha256=journal['head_sha256'],
                    result=p.validate_result(result, self.plan))
