#!/usr/bin/env python3
"""S2 local planning and portable validation. Never runs models, tools or tests."""
import argparse
import ctypes
import errno
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, localcontext, ROUND_HALF_UP
import json
import ipaddress
from fractions import Fraction
import os
from pathlib import Path
import re
import sys
import uuid
import unicodedata

import definitions as d

ROOT = Path(__file__).resolve().parent
PARAMETERS = ('threads', 'gpu_mode', 'num_ctx', 'temperature', 'seed', 'think', 'num_predict')
PLAN_FIELDS = ('kind', 'schema_version', 'run_id', 'competition', 'rubric', 'participants',
               'limits', 'repetitions', 'preparation', 'policy', 'engine')
CONFIG_FIELDS = ('participants', 'limits', 'repetitions', 'preparation', 'policy', 'engine')
RUN_STATES = ('planned', 'running', 'completed', 'cancel_requested', 'cancelled', 'interrupted', 'failed')
ATTEMPT_STATES = ('planned', 'running', 'succeeded', 'failed', 'timed_out', 'cancelled', 'uncertain')
TERMINAL = frozenset(('succeeded', 'failed', 'timed_out', 'cancelled'))
METRICS = ('total_duration_ns', 'load_duration_ns', 'prompt_eval_duration_ns', 'eval_duration_ns',
           'prompt_eval_count', 'eval_count', 'wall_duration_ns',
           'tokens_per_second', 'prompt_tokens_per_second')


def require(ok, code, location='$'):
    d.require(ok, code, location)


def _object(v, fields, location='$', optional=()):
    d._object(v, fields, location, optional)


def _integer(v, location='$', minimum=0):
    d._int(v, location, minimum)


def _uuid(v, location='$'):
    d._uuid(v, location)


def _boolean(v, location='$'):
    require(type(v) is bool, 'boolean_invalid', location)


def _not_address(v):
    try:ipaddress.ip_address(v)
    except ValueError:return
    raise d.DefinitionError('private_address_forbidden')


def _label(v, location='$'):
    # Portable identifiers, never endpoint URLs, credentials or filesystem roots.
    require(type(v) is str and 0 < len(v) <= 256 and v[0].isalnum()
            and all(c.isalnum() or unicodedata.category(c).startswith('M') or c in '._:-' for c in v),
            'portable_identifier_invalid', location)
    _not_address(v)


def _model_name(v):
    require(type(v) is str and 0 < len(v) <= 256 and v[0].isalnum()
            and all(c.isalnum() or unicodedata.category(c).startswith('M') or c in '._/:-' for c in v)
            and '://' not in v and '..' not in v.split('/') and '//' not in v
            and not re.match(r'^[A-Za-z]:/', v), 'model_name_invalid')
    _not_address(v)


def _header(v, kind):
    d._header(v, kind)


def _copy(v):
    return d.parse_json_bytes(d.canonical_json_bytes(v))


def competition_reference(competition):
    return dict(competition_id=competition['competition_id'],
                definition_revision=competition['definition_revision'],
                definition_sha256=d.content_sha256(competition),
                prompt_version=competition['prompt']['version'],
                prompt_sha256=competition['prompt']['sha256'])


def _reference(v):
    _object(v, ('competition_id', 'definition_revision', 'definition_sha256',
                'prompt_version', 'prompt_sha256'), '$.competition')
    _uuid(v['competition_id'])
    _integer(v['definition_revision'], minimum=1)
    _integer(v['prompt_version'], minimum=1)
    d._hash(v['definition_sha256']);d._hash(v['prompt_sha256'])


def _participant(p):
    _object(p, ('participant_id', 'execution_adapter', 'adapter_version', 'provider',
                'model', 'parameters', 'hardware'), '$.participants[]')
    _uuid(p['participant_id'])
    require(p['execution_adapter'] == 'ollama' and p['provider'] == 'ollama', 'adapter_unsupported')
    _label(p['adapter_version'])
    _object(p['model'], ('name', 'revision_digest'), '$.participants[].model')
    _model_name(p['model']['name'])
    digest = p['model']['revision_digest']
    require(digest is None or type(digest) is str and bool(
        re.fullmatch(r'(?:sha256:)?[a-f0-9]{64}', digest)), 'model_digest_invalid')
    o = p['parameters']
    _object(o, PARAMETERS, '$.participants[].parameters')
    for key in ('threads', 'num_ctx', 'num_predict'):
        _integer(o[key], '$.participants[].parameters.'+key, 1)
    _integer(o['seed'], '$.participants[].parameters.seed')
    _boolean(o['think'], '$.participants[].parameters.think')
    require(o['gpu_mode'] in ('cpu_only', 'automatic'), 'gpu_mode_unsupported')
    d.validate_decimal_string(o['temperature'], nonnegative=True)
    _object(p['hardware'], ('profile_id', 'profile_revision', 'verified'), '$.participants[].hardware')
    hw = p['hardware'];_boolean(hw['verified'])
    if hw['verified']:
        _uuid(hw['profile_id']);_integer(hw['profile_revision'], minimum=1)
        # S2 has no inventory/probe/archive authority. Never turn a boolean into evidence.
        raise d.DefinitionError('hardware_evidence_unavailable')
    require(hw['profile_id'] is None and hw['profile_revision'] is None, 'hardware_unknown_inconsistent')


def _plan_shape(v):
    d.canonical_json_bytes(v)
    _object(v, PLAN_FIELDS)
    _header(v, 'run_plan');_uuid(v['run_id']);_reference(v['competition'])
    _object(v['rubric'], ('rubric_id', 'revision', 'sha256'), '$.rubric')
    _uuid(v['rubric']['rubric_id']);_integer(v['rubric']['revision'], minimum=1);d._hash(v['rubric']['sha256'])
    d._list(v['participants'], '$.participants', True)
    seen = set()
    for p in v['participants']:
        _participant(p)
        require(p['participant_id'] not in seen, 'participant_duplicate')
        seen.add(p['participant_id'])
    _integer(v['repetitions'], '$.repetitions', 1)
    require(len(seen)*v['repetitions'] <= 10000, 'measurement_slot_limit')
    _object(v['limits'], ('request_timeout_seconds', 'attempt_deadline_seconds', 'run_deadline_seconds'), '$.limits')
    for key, val in v['limits'].items():_integer(val, '$.limits.'+key, 1)
    t = v['limits']
    require(t['request_timeout_seconds'] <= t['attempt_deadline_seconds'] <= t['run_deadline_seconds'],
            'time_budget_inconsistent')
    _object(v['preparation'], ('unload_before', 'preload', 'warmup_count'), '$.preparation')
    _boolean(v['preparation']['unload_before']);_boolean(v['preparation']['preload'])
    _integer(v['preparation']['warmup_count'])
    _object(v['policy'], ('max_asset_bytes', 'max_artifact_bytes', 'max_files', 'network_allowed', 'isolation_profile'), '$.policy')
    for key in ('max_asset_bytes', 'max_artifact_bytes', 'max_files'):_integer(v['policy'][key], minimum=1)
    _boolean(v['policy']['network_allowed'])
    require(v['policy']['isolation_profile'] == 'inference_only', 'isolation_profile_unsupported')
    _object(v['engine'], ('version', 'source_sha256'), '$.engine')
    _label(v['engine']['version'])
    if v['engine']['source_sha256'] is not None:d._hash(v['engine']['source_sha256'])


@dataclass(frozen=True, slots=True)
class PinnedPlan:
    """Validated immutable bytes. Accessors return independent copies, not live mappings."""
    _bytes: bytes = field(repr=False)
    _competition: bytes = field(repr=False)
    _rubric: bytes = field(repr=False)

    def as_dict(self):
        return d.parse_json_bytes(self._bytes)

    @property
    def sha256(self):
        return d.content_sha256(self.as_dict())

    def competition(self):
        return d.parse_json_bytes(self._competition)

    def rubric(self):
        return d.parse_json_bytes(self._rubric)


def validate_run_plan(value, competition, rubric, *, asset_root=None, rubric_asset_root=None,
                      expected_sha256=None, previous=None):
    """Bind the complete S1 definitions/assets, not just their display names."""
    v = _copy(value);_plan_shape(v)
    if expected_sha256 is not None:d.verify_content_sha256(v, expected_sha256)
    if previous is not None:
        require(type(previous) is PinnedPlan, 'pinned_plan_required')
        require(v['run_id'] == previous.as_dict()['run_id'], 'run_identity_conflict')
        require(d.canonical_json_bytes(v) == previous._bytes, 'plan_immutable')
    c = d.validate_competition(competition, rubric, asset_root=asset_root, rubric_asset_root=rubric_asset_root)
    r = d.validate_rubric(rubric, asset_root=rubric_asset_root)
    require(v['competition'] == competition_reference(c), 'competition_binding_mismatch')
    require(v['rubric'] == c['rubric'], 'rubric_binding_mismatch')
    assets = c['assets'] + [a for suite in r['test_suites'] for a in suite['assets']]
    require(all(a['size_bytes'] <= v['policy']['max_asset_bytes'] for a in assets), 'plan_asset_size_limit')
    require(len(assets) <= v['policy']['max_files'], 'plan_asset_count_limit')
    return PinnedPlan(d.canonical_json_bytes(v), d.canonical_json_bytes(c), d.canonical_json_bytes(r))


def create_run_plan(competition, rubric, config, *, asset_root=None, rubric_asset_root=None):
    config = _copy(config)
    _object(config, CONFIG_FIELDS, '$.config', ('run_id',))
    # Validation before construction ensures even planning does not skip S1 checks.
    c = d.validate_competition(competition, rubric, asset_root=asset_root, rubric_asset_root=rubric_asset_root)
    v = dict(config, kind='run_plan', schema_version=1,
             run_id=config.get('run_id', str(uuid.uuid4())), competition=competition_reference(c), rubric=_copy(c['rubric']))
    return validate_run_plan(v, c, rubric, asset_root=asset_root, rubric_asset_root=rubric_asset_root)


def _context(plan):
    require(type(plan) is PinnedPlan, 'pinned_plan_required')
    v = plan.as_dict();_plan_shape(v)
    c = plan.competition();r = plan.rubric()
    d._competition_shape(c, d.DEFAULT_REGISTRY);d._inventory(c['assets'], d.DEFAULT_LIMITS)
    d._rubric_shape(r, d.DEFAULT_REGISTRY, d.DEFAULT_LIMITS)
    require(c['discipline'] == r['discipline'], 'plan_context_invalid')
    require(v['competition'] == competition_reference(c)
            and v['rubric'] == plan.competition()['rubric']
            and v['rubric']['sha256'] == d.content_sha256(r)
            and v['rubric']['rubric_id'] == r['rubric_id'] and v['rubric']['revision'] == r['revision'],
            'plan_context_invalid')
    return v


def serialize_run_plan(plan):
    _context(plan)
    return d.canonical_json_bytes(plan.as_dict())


def plan_readiness(plan):
    v = _context(plan)
    reasons = ['s2_execution_not_implemented', 'provider_capabilities_unverified']
    if v['engine']['source_sha256'] is None:reasons.append('engine_build_unknown')
    if any(p['model']['revision_digest'] is None for p in v['participants']):reasons.append('model_digest_unknown')
    if any(not p['hardware']['verified'] for p in v['participants']):reasons.append('hardware_unconfirmed')
    return {'executable': False, 'reasons': reasons, 'gpu_usage': 'not_measured'}


def measurement_slots(plan):
    v = _context(plan)
    return tuple((p['participant_id'], repetition) for p in v['participants']
                 for repetition in range(1, v['repetitions']+1))


def _timestamp(value, nullable=False):
    if nullable and value is None:return None
    require(type(value) is str and bool(re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,9})?Z', value)),
            'timestamp_invalid')
    try:
        whole, dot, fraction = value[:-1].partition('.')
        dt = datetime.fromisoformat(whole).replace(tzinfo=timezone.utc)
        delta = dt-datetime(1970, 1, 1, tzinfo=timezone.utc)
        return (delta.days*86400+delta.seconds)*1000000000+int(fraction.ljust(9, '0') if dot else '0')
    except ValueError:raise d.DefinitionError('timestamp_invalid') from None


def validate_run_transition(before, after):
    require(before in RUN_STATES and after in RUN_STATES, 'run_status_invalid')
    edges = {'planned': ('running',), 'running': ('completed', 'cancel_requested', 'interrupted', 'failed'),
             'cancel_requested': ('cancelled', 'interrupted', 'failed'), 'interrupted': ('running',)}
    require(after == before or after in edges.get(before, ()), 'run_transition_invalid')


def validate_attempt_transition(before, after):
    require(before in ATTEMPT_STATES and after in ATTEMPT_STATES, 'attempt_status_invalid')
    edges = {'planned': ('running', 'cancelled'), 'running': ('succeeded', 'failed', 'timed_out', 'cancelled', 'uncertain')}
    require(after == before or after in edges.get(before, ()), 'attempt_transition_invalid')


def _publish_no_replace(parent, source, destination):
    function = getattr(ctypes.CDLL(None, use_errno=True), 'renameat2', None)
    require(function is not None, 'output_publish_unavailable')
    function.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    function.restype = ctypes.c_int
    if function(parent, os.fsencode(source), parent, os.fsencode(destination), 1):
        code = ctypes.get_errno()
        if code == errno.EEXIST:raise d.DefinitionError('output_exists')
        if code in (errno.ENOSYS, errno.EINVAL):raise d.DefinitionError('output_publish_unavailable')
        raise OSError(code, 'output_publish_failed')


def write_json_exclusive(path, value, *, protected_roots=()):
    """Publish one bounded JSON file atomically; no existing destination is replaced."""
    data = d.canonical_json_bytes(value) + b'\n'
    require(len(data) <= d.DEFAULT_LIMITS.max_json_bytes, 'output_size_limit')
    path = Path(path).absolute()
    require('..' not in path.parts and path.suffix.lower() == '.json'
            and path.is_relative_to(ROOT) and not path.is_relative_to(ROOT/'results')
            and not path.is_relative_to(ROOT/'reports') and '.git' not in path.relative_to(ROOT).parts
            and not any(path.is_relative_to(Path(p).absolute()) for p in protected_roots), 'output_path_invalid')
    # Also protect every pre-existing tracked/untracked file: publication uses
    # no-replace renameat2(), never os.replace(). Parent must already exist.
    parent = None;temporary = None;published = False;owned_identity = None
    try:
        parent = d._open_directory(path.parent)
        identity = d._signature(os.fstat(parent))
        try:
            os.stat(path.name, dir_fd=parent, follow_symlinks=False)
        except FileNotFoundError:pass
        else:raise d.DefinitionError('output_exists')
        for folder in (path.parent, *path.parent.parents):
            if not folder.is_relative_to(ROOT):break
            require(not any(os.path.lexists(folder/name) for name in ('manifest.json', 'session.json', 'scenario.json')),
                    'output_archive_forbidden')
        temporary = '.s2-'+uuid.uuid4().hex+'.tmp'
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent)
        created = os.fstat(fd);owned_identity = (created.st_dev, created.st_ino)
        with os.fdopen(fd, 'wb') as out:
            out.write(data);out.flush();os.fsync(out.fileno())
        current = d._open_directory(path.parent)
        try:
            require(os.fstat(current).st_dev == identity[0] and os.fstat(current).st_ino == identity[1], 'output_parent_changed')
        finally:os.close(current)
        actual, signature = d._read_fd(parent, temporary, d.DEFAULT_LIMITS.max_json_bytes)
        require(actual == data and signature[:2] == owned_identity, 'output_file_changed')
        _publish_no_replace(parent, temporary, path.name)
        published = True;temporary = None;os.fsync(parent)
        final_data, final_signature = d._read_fd(parent, path.name, d.DEFAULT_LIMITS.max_json_bytes)
        require(final_data == data and final_signature[:2] == owned_identity, 'output_file_changed')
        current = d._open_directory(path.parent)
        try:
            require((os.fstat(current).st_dev, os.fstat(current).st_ino) == identity[:2], 'output_parent_changed')
        finally:os.close(current)
    except d.DefinitionError:raise
    except OSError:
        # If publication occurred, an fsync failure has an uncertain durability
        # outcome. Do not remove a possibly visible final result or retry it.
        raise d.DefinitionError('output_durability_unknown' if published else 'output_write_failed') from None
    finally:
        if temporary is not None and parent is not None:
            try:
                info = os.stat(temporary, dir_fd=parent, follow_symlinks=False)
                if (info.st_dev, info.st_ino) == owned_identity:os.unlink(temporary, dir_fd=parent)
            except OSError:pass
        if parent is not None:os.close(parent)


def validate_metrics(metrics):
    """Validate units and internally consistent rates, never invent or fill values."""
    _object(metrics, METRICS, '$.metrics')
    for key in METRICS[:-2]:
        if metrics[key] is not None:_integer(metrics[key], '$.metrics.'+key)
    for rate, count, duration in [('tokens_per_second', 'eval_count', 'eval_duration_ns'),
                                  ('prompt_tokens_per_second', 'prompt_eval_count', 'prompt_eval_duration_ns')]:
        value = metrics[rate]
        if value is None:continue
        d.validate_decimal_string(value, nonnegative=True)
        require(metrics[count] is not None and metrics[duration] not in (None, 0), 'metric_rate_without_basis')
        require(len(value) <= 2048, 'metric_decimal_limit')
        exact = Fraction(metrics[count]*1000000000, metrics[duration])
        if Fraction(value) != exact:
            # A finite decimal cannot encode every rational. Exact finite rates
            # are accepted at any canonical precision; recurring rates round once.
            with localcontext() as ctx:
                ctx.prec = 6000
                rounded = (Decimal(exact.numerator)/Decimal(exact.denominator)).quantize(
                    Decimal('0.000001'), rounding=ROUND_HALF_UP)
            require(Decimal(value) == rounded, 'metric_rate_inconsistent')
    return _copy(metrics)


def validate_artifacts(artifacts, *, max_files=1000, max_bytes=104857600):
    """Metadata/reference validation only. Reading/copying artifact bytes belongs to S3."""
    d._list(artifacts, '$.artifacts')
    require(len(artifacts) <= max_files, 'artifact_count_limit')
    ids = set();paths = set();total = 0
    for a in artifacts:
        _object(a, ('artifact_id', 'path', 'sha256', 'size_bytes', 'media_type', 'classification'), '$.artifacts[]')
        _uuid(a['artifact_id']);d._asset_path(a['path']);d._hash(a['sha256'])
        _integer(a['size_bytes'])
        require(a['artifact_id'] not in ids and a['path'] not in paths, 'artifact_duplicate')
        ids.add(a['artifact_id']);paths.add(a['path']);total += a['size_bytes']
        require(type(a['media_type']) is str and bool(re.fullmatch(r'[A-Za-z0-9.+-]+/[A-Za-z0-9.+-]+', a['media_type'])),
                'media_type_invalid')
        require(a['classification'] in ('private', 'shareable'), 'artifact_classification_invalid')
    require(total <= max_bytes, 'artifact_total_limit')
    return _copy(artifacts)


def _evidence(refs, artifacts):
    d._list(refs, '$.evidence')
    seen = set();known = {a['artifact_id'] for a in artifacts}
    for ref in refs:
        _uuid(ref)
        require(ref not in seen, 'evidence_duplicate')
        require(ref in known, 'evidence_reference_missing')
        seen.add(ref)


def _provenance(value, participant, plan, artifacts):
    require(type(value) is dict, 'object_required', '$.provenance')
    if not value:return  # Unknown is not invented provenance.
    _object(value, ('engine', 'adapter_version', 'model_revision_digest', 'evidence'), '$.provenance')
    require(value['engine'] == plan['engine'] and value['adapter_version'] == participant['adapter_version']
            and value['model_revision_digest'] == participant['model']['revision_digest'], 'provenance_binding_mismatch')
    _evidence(value['evidence'], artifacts)


def validate_execution(value, plan):
    v = _copy(value);p = _context(plan)
    _object(v, ('kind', 'schema_version', 'run_id', 'participant_id', 'repetition', 'attempt_id',
                'plan_sha256', 'status', 'started_at', 'finished_at', 'metrics', 'error',
                'artifacts', 'provenance', 'supersedes_attempt_id'))
    _header(v, 'execution')
    _uuid(v['run_id']);_uuid(v['participant_id']);_uuid(v['attempt_id']);d._hash(v['plan_sha256'])
    require(v['run_id'] == p['run_id'] and v['plan_sha256'] == plan.sha256, 'execution_plan_mismatch')
    _integer(v['repetition'], minimum=1)
    require((v['participant_id'], v['repetition']) in measurement_slots(plan), 'measurement_slot_invalid')
    require(v['status'] in ATTEMPT_STATES, 'attempt_status_invalid')
    started = _timestamp(v['started_at'], True);finished = _timestamp(v['finished_at'], True)
    if started is not None and finished is not None:require(finished >= started, 'execution_time_invalid')
    if v['status'] == 'planned':
        require(started is None and finished is None, 'execution_time_invalid')
    elif v['status'] in ('running', 'uncertain'):
        require(started is not None and finished is None, 'execution_time_invalid')
    elif v['status'] in ('succeeded', 'failed', 'timed_out'):
        require(started is not None and finished is not None, 'execution_time_invalid')
    else:require(finished is not None, 'execution_time_invalid')
    participant = next(x for x in p['participants'] if x['participant_id'] == v['participant_id'])
    if started is not None:
        require(participant['model']['revision_digest'] is not None and p['engine']['source_sha256'] is not None,
                'execution_plan_unresolved')
    validate_metrics(v['metrics'])
    if started is None:
        require(all(x is None for x in v['metrics'].values()), 'unstarted_metrics_forbidden')
    validate_artifacts(v['artifacts'], max_files=p['policy']['max_files'], max_bytes=p['policy']['max_artifact_bytes'])
    if v['supersedes_attempt_id'] is not None:
        _uuid(v['supersedes_attempt_id'])
        require(v['supersedes_attempt_id'] != v['attempt_id'], 'attempt_supersedes_self')
    error = v['error']
    if error is not None:
        _object(error, ('code', 'phase', 'retryable', 'evidence'), '$.error')
        for key in ('code', 'phase'):
            require(type(error[key]) is str and bool(re.fullmatch(r'[a-z][a-z0-9_]{0,79}', error[key])),
                    'error_identifier_invalid')
        _boolean(error['retryable']);_evidence(error['evidence'], v['artifacts'])
        by_id = {a['artifact_id']: a for a in v['artifacts']}
        require(all(by_id[x]['classification'] == 'private' for x in error['evidence']), 'error_evidence_not_private')
    if v['status'] in ('failed', 'timed_out'):require(error is not None, 'execution_error_missing')
    if v['status'] in ('succeeded', 'planned'):require(error is None, 'execution_error_conflict')
    _provenance(v['provenance'], participant, p, v['artifacts'])
    return v


def _execution_set(wrappers, plan):
    d._list(wrappers, '$.executions')
    require(len(wrappers) <= 10000, 'attempt_count_limit')
    by_id = {};children = {};slots = {};artifacts = set();paths = set();total_bytes = 0
    for wrapper in wrappers:
        _object(wrapper, ('execution', 'sha256'), '$.executions[]')
        d.verify_content_sha256(wrapper['execution'], wrapper['sha256'])
        e = validate_execution(wrapper['execution'], plan)
        identity = e['attempt_id'];require(identity not in by_id, 'attempt_duplicate')
        by_id[identity] = e
        slots.setdefault((e['participant_id'], e['repetition']), []).append(identity)
        for a in e['artifacts']:
            require(a['artifact_id'] not in artifacts and a['path'] not in paths, 'artifact_duplicate')
            artifacts.add(a['artifact_id']);paths.add(a['path']);total_bytes += a['size_bytes']
    p = plan.as_dict()
    require(len(artifacts) <= p['policy']['max_files'] and total_bytes <= p['policy']['max_artifact_bytes'],
            'artifact_total_limit')
    for identity, e in by_id.items():
        old = e['supersedes_attempt_id']
        if old is None:continue
        require(old in by_id and old not in children, 'attempt_supersedes_invalid')
        before = by_id[old]
        require(before['status'] == 'uncertain' and (before['participant_id'], before['repetition']) ==
                (e['participant_id'], e['repetition']), 'attempt_supersedes_invalid')
        if e['started_at'] is not None:
            require(_timestamp(e['started_at']) >= _timestamp(before['started_at']), 'execution_time_invalid')
        children[old] = identity
    current = []
    for ids in slots.values():
        roots = [x for x in ids if by_id[x]['supersedes_attempt_id'] is None]
        require(len(roots) == 1, 'measurement_slot_duplicate')
        seen = set();node = roots[0]
        while True:
            require(node not in seen, 'attempt_cycle')
            seen.add(node)
            if node not in children:break
            node = children[node]
        require(seen == set(ids), 'attempt_chain_invalid')
        current.append(by_id[node])
    return by_id, current


def _progress(wrappers, plan):
    by_id, current = _execution_set(wrappers, plan)
    planned = len(measurement_slots(plan))
    terminal = sum(x['status'] in TERMINAL for x in current)
    successes = sum(x['status'] == 'succeeded' for x in current)
    return dict(planned_slots=planned, started_attempts=sum(x['started_at'] is not None for x in by_id.values()),
                terminal_slots=terminal, successful_slots=successes, failed_slots=terminal-successes,
                pending_slots=planned-terminal), by_id, current


def _assessment(value, plan, wrappers, rubrics):
    """Consume certificates as structural references; never evaluate or calculate scores."""
    _object(value, ('kind', 'schema_version', 'assessment_id', 'run_id', 'participant_id', 'attempt_id',
                    'execution_sha256', 'rubric_id', 'revision', 'sha256', 'evaluator', 'created_at',
                    'categories', 'mandatory_tests', 'status', 'total_score', 'supersedes', 'evidence'), '$.assessments[]')
    _header(value, 'assessment')
    p = plan.as_dict()
    for key in ('assessment_id', 'run_id', 'participant_id', 'attempt_id', 'rubric_id'):_uuid(value[key])
    by_id = {w['execution']['attempt_id']: w for w in wrappers}
    require(value['attempt_id'] in by_id, 'assessment_attempt_missing')
    w = by_id[value['attempt_id']];e = w['execution']
    require(value['run_id'] == p['run_id'] and value['participant_id'] == e['participant_id']
            and value['execution_sha256'] == w['sha256'], 'assessment_execution_mismatch')
    _integer(value['revision'], minimum=1);d._hash(value['sha256']);d._hash(value['execution_sha256'])
    require(value['sha256'] in rubrics, 'assessment_rubric_missing')
    bound_rubric = rubrics[value['sha256']]
    require(value['rubric_id'] == bound_rubric['rubric_id'] and value['revision'] == bound_rubric['revision'],
            'assessment_rubric_mismatch')
    _integer(value['revision'], minimum=1);d._hash(value['sha256']);d._hash(value['execution_sha256'])
    _object(value['evaluator'], ('type', 'version', 'identity'), '$.evaluator')
    require(value['evaluator']['type'] in ('deterministic', 'human', 'llm_jury'), 'evaluator_type_invalid')
    _label(value['evaluator']['version']);_label(value['evaluator']['identity'])
    created = _timestamp(value['created_at'])
    require(e['status'] in TERMINAL and created >= _timestamp(e['finished_at']), 'assessment_time_invalid')
    require(value['status'] in ('passed', 'failed', 'incomplete'), 'assessment_status_invalid')
    if value['total_score'] is not None:
        d.validate_decimal_string(value['total_score'], nonnegative=True)
        require(len(value['total_score']) <= 32 and Decimal(value['total_score']) <= 100, 'assessment_score_invalid')
    if value['supersedes'] is not None:_uuid(value['supersedes'])
    _evidence(value['evidence'], e['artifacts'])
    rubric = bound_rubric;known = {c['category_id']:c for c in rubric['categories']}
    d._list(value['categories'], '$.assessment.categories');seen = set();category_states = {}
    for cat in value['categories']:
        _object(cat, ('category_id', 'points', 'status', 'evidence'), '$.assessment.categories[]')
        require(type(cat['category_id']) is str and cat['category_id'] in known, 'assessment_category_unknown')
        require(cat['category_id'] not in seen, 'assessment_category_duplicate');seen.add(cat['category_id'])
        require(cat['status'] in ('complete', 'missing', 'error'), 'assessment_category_status_invalid')
        if cat['points'] is not None:
            d.validate_decimal_string(cat['points'], nonnegative=True)
            require(len(cat['points']) <= 2048 and Decimal(cat['points']) <= known[cat['category_id']]['max_points'],
                    'assessment_points_invalid')
        require((cat['status'] == 'complete') == (cat['points'] is not None), 'assessment_category_inconsistent')
        category_states[cat['category_id']] = cat['status']
        _evidence(cat['evidence'], e['artifacts'])
    d._list(value['mandatory_tests'], '$.assessment.mandatory_tests');seen = set();test_states = {}
    for test in value['mandatory_tests']:
        _object(test, ('test_id', 'status', 'evidence'), '$.assessment.mandatory_tests[]')
        require(type(test['test_id']) is str and test['test_id'] in rubric['mandatory_tests'], 'assessment_test_unknown')
        require(test['test_id'] not in seen, 'assessment_test_duplicate');seen.add(test['test_id'])
        require(test['status'] in ('passed', 'failed', 'missing', 'error'), 'assessment_test_status_invalid')
        test_states[test['test_id']] = test['status']
        _evidence(test['evidence'], e['artifacts'])
    if value['status'] == 'incomplete':require(value['total_score'] is None, 'assessment_score_inconsistent')
    if value['status'] == 'passed':
        require(set(category_states) == set(known) and all(x == 'complete' for x in category_states.values())
                and set(test_states) == set(rubric['mandatory_tests']) and all(x == 'passed' for x in test_states.values())
                and value['total_score'] is not None, 'assessment_pass_inconsistent')
    if 'failed' in test_states.values():require(value['status'] == 'failed', 'assessment_mandatory_gate_conflict')


def validate_result(value, plan, *, expected_sha256=None, previous=None, assessment_rubrics=()):
    v = _copy(value);p = _context(plan)
    _object(v, ('kind', 'schema_version', 'run_id', 'plan_sha256', 'competition', 'status',
                'created_at', 'updated_at', 'progress', 'executions', 'assessments'))
    _header(v, 'result');_uuid(v['run_id']);d._hash(v['plan_sha256']);_reference(v['competition'])
    require(v['run_id'] == p['run_id'] and v['plan_sha256'] == plan.sha256
            and v['competition'] == p['competition'], 'result_plan_mismatch')
    if expected_sha256 is not None:d.verify_content_sha256(v, expected_sha256)
    require(v['status'] in RUN_STATES, 'run_status_invalid')
    created = _timestamp(v['created_at']);updated = _timestamp(v['updated_at'])
    require(updated >= created, 'result_time_invalid')
    computed, attempts, current = _progress(v['executions'], plan)
    _object(v['progress'], tuple(computed), '$.progress')
    for key, number in v['progress'].items():_integer(number, '$.progress.'+key)
    require(v['progress'] == computed, 'progress_inconsistent')
    for e in attempts.values():
        for key in ('started_at', 'finished_at'):
            when = _timestamp(e[key], True)
            if when is not None:require(created <= when <= updated, 'result_time_invalid')
    if v['status'] == 'planned':require(not attempts and not v['assessments'], 'planned_has_execution')
    if v['status'] == 'completed':require(computed['pending_slots'] == 0, 'completed_has_pending')
    if v['status'] == 'cancelled':
        require(all(e['status'] in TERMINAL for e in current), 'cancelled_has_pending_attempt')
    if v['status'] in ('running', 'cancel_requested'):
        require(not any(e['status'] == 'uncertain' for e in current), 'uncertain_requires_interrupted')
    if v['status'] in ('interrupted', 'failed'):
        require(not any(e['status'] == 'running' for e in current), 'interrupted_has_running_attempt')
    d._list(v['assessments'], '$.assessments')
    rubrics = {d.content_sha256(plan.rubric()): plan.rubric()}
    for rubric in assessment_rubrics:
        rubric = _copy(rubric)
        d._rubric_shape(rubric, d.DEFAULT_REGISTRY, d.DEFAULT_LIMITS)
        require(rubric['discipline'] == plan.competition()['discipline'], 'rubric_discipline_mismatch')
        rubrics[d.content_sha256(rubric)] = rubric
    assessments = {}
    for a in v['assessments']:
        _assessment(a, plan, v['executions'], rubrics)
        require(a['assessment_id'] not in assessments, 'assessment_duplicate')
        require(_timestamp(a['created_at']) <= updated, 'assessment_time_invalid')
        assessments[a['assessment_id']] = a
    for a in assessments.values():
        if a['supersedes'] is None:continue
        require(a['supersedes'] in assessments and a['supersedes'] != a['assessment_id'], 'assessment_supersedes_invalid')
        before = assessments[a['supersedes']]
        require(before['attempt_id'] == a['attempt_id'] and _timestamp(before['created_at']) <= _timestamp(a['created_at']),
                'assessment_supersedes_invalid')
        seen = set();node = a
        while node['supersedes'] is not None:
            require(node['assessment_id'] not in seen, 'assessment_cycle');seen.add(node['assessment_id'])
            node = assessments[node['supersedes']]
    if previous is not None:
        old = validate_result(previous, plan, assessment_rubrics=assessment_rubrics)
        require(v['created_at'] == old['created_at'] and updated >= _timestamp(old['updated_at']), 'result_time_invalid')
        validate_run_transition(old['status'], v['status'])
        if old['status'] in ('completed', 'cancelled', 'failed'):
            require(v['executions'] == old['executions'], 'execution_after_terminal_run')
        new_by_id = {w['execution']['attempt_id']:w for w in v['executions']}
        for old_w in old['executions']:
            identity = old_w['execution']['attempt_id']
            require(identity in new_by_id, 'execution_removed')
            new_w = new_by_id[identity]
            if old_w['execution']['status'] in TERMINAL | {'uncertain'}:
                require(new_w == old_w, 'execution_immutable')
            else:
                before = old_w['execution'];after = new_w['execution']
                for key in ('participant_id', 'repetition', 'supersedes_attempt_id', 'plan_sha256', 'run_id'):
                    require(before[key] == after[key], 'execution_identity_changed')
                if before['started_at'] is not None:require(after['started_at'] == before['started_at'], 'execution_time_invalid')
                validate_attempt_transition(before['status'], after['status'])
        require(all(a['assessment_id'] in assessments and assessments[a['assessment_id']] == a for a in old['assessments']),
                'assessment_immutable')
    return v


def initial_result(plan, *, at=None):
    p = _context(plan)
    at = at if at is not None else datetime.now(timezone.utc).isoformat(timespec='microseconds').replace('+00:00', 'Z')
    v = dict(kind='result', schema_version=1, run_id=p['run_id'], plan_sha256=plan.sha256,
             competition=_copy(p['competition']), status='planned', created_at=at, updated_at=at,
             progress=dict(planned_slots=len(measurement_slots(plan)), started_attempts=0, terminal_slots=0,
                           successful_slots=0, failed_slots=0, pending_slots=len(measurement_slots(plan))),
             executions=[], assessments=[])
    return validate_result(v, plan)


def new_attempt_identity(plan, participant_id, repetition):
    require((participant_id, repetition) in measurement_slots(plan) and type(repetition) is int,
            'measurement_slot_invalid')
    return dict(run_id=plan.as_dict()['run_id'], participant_id=participant_id, repetition=repetition,
                attempt_id=str(uuid.uuid4()), plan_sha256=plan.sha256)


def serialize_result(value, plan, *, assessment_rubrics=()):
    return d.canonical_json_bytes(validate_result(value, plan, assessment_rubrics=assessment_rubrics))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    hash_cmd = sub.add_parser('hash', help='Canonical hash only; no claim of schema validity')
    hash_cmd.add_argument('file', type=Path)
    hash_cmd.add_argument('--dry-run', action='store_true', help='Hashing is always local-only')
    for name in ('create-plan', 'validate-plan', 'initial-result', 'validate-result'):
        cmd = sub.add_parser(name)
        cmd.add_argument('--competition', type=Path, required=True)
        cmd.add_argument('--rubric', type=Path, required=True)
        cmd.add_argument('--assets', type=Path)
        cmd.add_argument('--rubric-assets', type=Path)
        cmd.add_argument('--output', '-o', type=Path)
        cmd.add_argument('--dry-run', action='store_true', help='All S2 commands are local-only, including without this flag')
        cmd.add_argument('--emit-json', action='store_true', help='Emit the validated object instead of a validation receipt')
        if name == 'create-plan':cmd.add_argument('--config', type=Path, required=True)
        else:cmd.add_argument('--plan', type=Path, required=True)
        if name == 'validate-plan':
            cmd.add_argument('--expected-sha256')
            cmd.add_argument('--previous', type=Path)
        if name == 'initial-result':cmd.add_argument('--at', help='UTC creation timestamp; defaults to now')
        if name == 'validate-result':
            cmd.add_argument('--result', type=Path, required=True)
            cmd.add_argument('--assessment-rubric', type=Path, action='append', default=[])
            cmd.add_argument('--expected-sha256')
            cmd.add_argument('--previous', type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == 'hash':
            print(json.dumps({'sha256': d.content_sha256(d.load_json(args.file))}, separators=(',', ':')))
            return 0
        kwargs = dict(asset_root=args.assets, rubric_asset_root=args.rubric_assets)
        c = d.load_json(args.competition);r = d.load_json(args.rubric)
        if args.command == 'create-plan':
            plan = create_run_plan(c, r, d.load_json(args.config), **kwargs)
            obj = plan.as_dict()
        else:
            old_plan = None
            if args.command == 'validate-plan' and args.previous:
                old_plan = validate_run_plan(d.load_json(args.previous), c, r, **kwargs)
            plan = validate_run_plan(d.load_json(args.plan), c, r, previous=old_plan,
                                    expected_sha256=args.expected_sha256 if args.command == 'validate-plan' else None, **kwargs)
            if args.command == 'initial-result':obj = initial_result(plan, at=args.at)
            elif args.command == 'validate-result':
                obj = validate_result(d.load_json(args.result), plan, expected_sha256=args.expected_sha256,
                                      previous=d.load_json(args.previous) if args.previous else None,
                                      assessment_rubrics=[d.load_json(path) for path in args.assessment_rubric])
            else:obj = plan.as_dict()
        if args.output:
            write_json_exclusive(args.output, obj, protected_roots=[p for p in (args.assets, args.rubric_assets) if p])
        if args.command in ('create-plan', 'initial-result') or args.emit_json:
            print(d.canonical_json_bytes(obj).decode('utf-8'))
        else:
            print(json.dumps({'ok': True, 'kind': obj['kind'], 'sha256': d.content_sha256(obj),
                              'plan_sha256': plan.sha256, 'pin_checked': bool(args.expected_sha256 or args.previous),
                              'readiness': plan_readiness(plan)}, separators=(',', ':')))
        return 0
    except d.DefinitionError as error:
        print(json.dumps({'ok': False, 'code': error.code, 'location': error.location}), file=sys.stderr)
        return 2
    except (OSError, ValueError, TypeError, KeyError):
        print(json.dumps({'ok': False, 'code': 'input_invalid', 'location': '$'}), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
