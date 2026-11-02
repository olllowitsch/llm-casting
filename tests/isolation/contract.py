"""Private S6-C v1 contract. Independent of normative S1/S2 and never an approval.

JSON reports are untrusted observations, not authenticated host attestations.
This preparation profile cannot produce isolation_verified=true.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import uuid
from datetime import datetime, timezone

VERSION = 1
MAX_BYTES = 262144
NETWORK = ('external_ipv4', 'external_ipv6', 'dns', 'unix_forbidden', 'gateway', 'direct_ollama')
FS = ('output_write', 'reference_read', 'reference_write', 'outside_write', 'other_read', 'hardlink')
FS_EXPECTED = dict(zip(FS, ('allowed', 'matched', 'denied', 'denied', 'denied', 'denied')))
NETWORK_EXPECTED = {key: 'allow_local_synthetic' if key == 'gateway' else 'deny' for key in NETWORK}


class Invalid(ValueError):
    """Stable error code only; never include paths, secrets or input text."""


def need(ok, code):
    if not ok:
        raise Invalid(code)


def obj(value, fields):
    need(type(value) is dict and set(value) == set(fields), 'fields_invalid')


def integer(value, low=0, high=2**63-1):
    need(type(value) is int and low <= value <= high, 'integer_invalid')


def identifier(value):
    try:
        need(type(value) is str and str(uuid.UUID(value)) == value, 'uuid_invalid')
    except (ValueError, AttributeError):
        raise Invalid('uuid_invalid') from None


def timestamp(value):
    need(type(value) is str and bool(re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?Z', value)),
         'timestamp_invalid')
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        raise Invalid('timestamp_invalid') from None


def now():
    return datetime.now(timezone.utc).isoformat(timespec='microseconds').replace('+00:00', 'Z')


def _tree(value, depth=0, count=None):
    count = [0] if count is None else count
    count[0] += 1
    need(depth <= 20 and count[0] <= 10000, 'json_structure_limit')
    if value is None or type(value) is bool:
        return
    if type(value) is int:
        need(value.bit_length() <= 128, 'integer_limit');return
    if type(value) is str:
        need(len(value) <= 65536 and len(value.encode('utf-8')) <= 65536, 'string_limit');return
    if type(value) is list:
        for item in value:_tree(item, depth+1, count)
        return
    if type(value) is dict:
        for key, item in value.items():
            need(type(key) is str, 'json_key_invalid');_tree(key, depth+1, count);_tree(item, depth+1, count)
        return
    raise Invalid('json_type_invalid')


def canonical(value):
    try:
        _tree(value)
        raw = bytearray()
        encoder = json.JSONEncoder(sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)
        for chunk in encoder.iterencode(value):
            part = chunk.encode('utf-8')
            need(len(raw)+len(part) <= MAX_BYTES, 'json_size_limit')
            raw.extend(part)
    except (ValueError, UnicodeError, RecursionError):
        raise Invalid('json_invalid') from None
    need(len(raw) <= MAX_BYTES, 'json_size_limit')
    return bytes(raw)


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def hash_value(value):
    need(type(value) is str and bool(re.fullmatch(r'[0-9a-f]{64}', value)), 'hash_invalid')


def parse(raw):
    need(type(raw) is bytes and len(raw) <= MAX_BYTES, 'json_size_limit')
    def pairs(items):
        result = {}
        for key, value in items:
            need(key not in result, 'json_duplicate_key');result[key] = value
        return result
    def forbidden(_):
        raise Invalid('json_number_invalid')
    try:
        value = json.loads(raw.decode('utf-8'), object_pairs_hook=pairs,
                           parse_float=forbidden, parse_constant=forbidden)
        canonical(value)
        return value
    except (ValueError, UnicodeError, RecursionError):
        raise Invalid('json_invalid') from None


def directory(path):
    """No symlink in any path component, no traversal or relative roots."""
    path = Path(path)
    need(path.is_absolute() and '..' not in path.parts, 'root_invalid')
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in path.parts[1:]:
            other = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd);fd = other
        return fd
    except BaseException:
        os.close(fd);raise


def leaf(fd, name, flags=os.O_RDONLY):
    need(type(name) is str and name not in ('', '.', '..') and '/' not in name and '\\' not in name,
         'leaf_invalid')
    out = os.open(name, flags | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
    try:
        info = os.fstat(out)
        need(stat.S_ISREG(info.st_mode) and info.st_nlink == 1, 'file_unsafe')
        return out
    except BaseException:
        os.close(out);raise


def read(path):
    path = Path(path);parent = directory(path.parent)
    try:
        fd = leaf(parent, path.name)
        try:
            before = os.fstat(fd);data = bytearray()
            while len(data) <= MAX_BYTES:
                chunk = os.read(fd, min(65536, MAX_BYTES+1-len(data)))
                if not chunk:break
                data.extend(chunk)
            after = os.fstat(fd)
            sig = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns, s.st_nlink)
            need(sig(before) == sig(after) and sig(after) == sig(os.stat(path.name, dir_fd=parent, follow_symlinks=False)),
                 'file_changed')
            need(len(data) <= MAX_BYTES, 'json_size_limit')
            return parse(bytes(data))
        finally:
            os.close(fd)
    finally:
        os.close(parent)


def validate_profile(value, expected_sha256):
    canonical(value);hash_value(expected_sha256)
    need(digest(value) == expected_sha256, 'profile_hash_mismatch')
    obj(value, ('kind', 'profile_version', 'test_id', 'created_at', 'expected', 'filesystem_policy',
                'network_policy', 'filesystem_expected', 'network_expected', 'limits'))
    need(value['kind'] == 'isolation_test_profile' and type(value['profile_version']) is int and
         value['profile_version'] == VERSION, 'profile_version_unsupported')
    identifier(value['test_id']);timestamp(value['created_at'])
    expected = value['expected'];obj(expected, ('uid', 'gid', 'unit', 'cgroup', 'host_mount_namespace_inode'))
    for key in ('uid', 'gid'):integer(expected[key], 1, 2**31-1)
    unit = 'llm-casting-isolation-probe@'+value['test_id']+'.service'
    need(expected['unit'] == unit and expected['cgroup'] == '/system.slice/'+unit, 'profile_identity_invalid')
    if expected['host_mount_namespace_inode'] is not None:integer(expected['host_mount_namespace_inode'], 1)
    need(value['filesystem_policy'] == 'synthetic-root-only-v1' and
         value['network_policy'] == 'local-fixtures-only-v1', 'policy_unsupported')
    need(canonical(value['filesystem_expected']) == canonical(FS_EXPECTED) and
         canonical(value['network_expected']) == canonical(NETWORK_EXPECTED), 'expectations_unsupported')
    limits = value['limits'];obj(limits, ('memory_max_bytes', 'cpu_quota_usec_per_sec', 'tasks_max', 'runtime_seconds'))
    for key, low, high in (('memory_max_bytes', 1048576, 268435456), ('cpu_quota_usec_per_sec', 1, 1000000),
                           ('tasks_max', 4, 32), ('runtime_seconds', 1, 15)):
        integer(limits[key], low, high)
    return value


def validate_observations(value):
    canonical(value);obj(value, ('identity', 'filesystem', 'resources', 'child', 'network', 'termination'))
    identity = value['identity']
    obj(identity, ('uid', 'gid', 'groups', 'cap_eff', 'no_new_privileges', 'mount_namespace_inode',
                   'unit', 'cgroup', 'invocation_id'))
    for key in ('uid', 'gid'):integer(identity[key])
    need(type(identity['groups']) is list, 'groups_invalid')
    for item in identity['groups']:integer(item)
    need(identity['groups'] == sorted(set(identity['groups'])), 'groups_invalid')
    for key in ('cap_eff', 'no_new_privileges', 'mount_namespace_inode'):
        if identity[key] is not None:integer(identity[key])
    need(identity['no_new_privileges'] in (None, 0, 1), 'nnp_invalid')
    for key in ('unit', 'cgroup', 'invocation_id'):
        need(identity[key] is None or type(identity[key]) is str, 'identity_invalid')
    if identity['invocation_id'] is not None:
        need(bool(re.fullmatch(r'[0-9a-f]{32}', identity['invocation_id'])), 'invocation_invalid')
    obj(value['filesystem'], FS)
    for outcome in value['filesystem'].values():
        need(type(outcome) is str and outcome in ('allowed', 'denied', 'matched', 'mismatch', 'not_verified'),
             'filesystem_observation_invalid')
    resources = value['resources'];obj(resources, ('memory_max_bytes', 'cpu_quota_usec_per_sec', 'tasks_max'))
    for amount in resources.values():
        if amount is not None:integer(amount, 1)
    child = value['child'];obj(child, ('state', 'pid', 'parent_pid', 'cgroup', 'alive_at_observation'))
    need(child['state'] in ('not_run', 'observed', 'lost_early'), 'child_state_invalid')
    for key in ('pid', 'parent_pid'):
        if child[key] is not None:integer(child[key], 1)
    need(child['cgroup'] is None or type(child['cgroup']) is str, 'child_cgroup_invalid')
    need(child['alive_at_observation'] is None or type(child['alive_at_observation']) is bool, 'child_alive_invalid')
    if child['state'] == 'not_run':
        need(all(child[k] is None for k in ('pid', 'parent_pid', 'cgroup', 'alive_at_observation')), 'child_inconsistent')
    else:
        need(all(child[k] is not None for k in ('pid', 'parent_pid', 'cgroup', 'alive_at_observation')), 'child_inconsistent')
    obj(value['network'], NETWORK)
    need(all(x == 'not_verified' for x in value['network'].values()), 'unsupported_network_attestation')
    need(value['termination'] == 'not_verified', 'unsupported_end_attestation')
    return value


def checks(profile, observations):
    """Recompute every status. Observations are not authenticated OS attestation."""
    validate_observations(observations)
    expected = profile['expected'];identity = observations['identity'];result = []
    def add(name, status, reason):
        result.append(dict(check_id=name, mandatory=True, status=status, reason=reason))
    def compare(name, actual, target):
        add(name, 'not_verified' if actual is None or target is None else 'passed' if actual == target else 'failed',
            'observed_match' if actual is not None and target is not None and actual == target else 'missing_or_mismatch')
    compare('uid', identity['uid'], expected['uid']);compare('gid', identity['gid'], expected['gid'])
    compare('groups', sorted(set(identity['groups']) | {identity['gid']}), [expected['gid']])
    compare('capabilities', identity['cap_eff'], 0);compare('no_new_privileges', identity['no_new_privileges'], 1)
    compare('unit', identity['unit'], expected['unit']);compare('cgroup', identity['cgroup'], expected['cgroup'])
    add('invocation', 'passed' if identity['invocation_id'] else 'not_verified', 'local_invocation_only')
    a = identity['mount_namespace_inode'];b = expected['host_mount_namespace_inode']
    add('mount_namespace', 'not_verified' if a is None or b is None else 'passed' if a != b else 'failed',
        'namespace_comparison_only')
    for key, wanted in FS_EXPECTED.items():
        actual = observations['filesystem'][key]
        add(key, 'not_verified' if actual == 'not_verified' else 'passed' if actual == wanted else 'failed',
            'synthetic_probe_observation')
    add('symlink_traversal_os_boundary', 'not_verified', 'safe_path_guard_is_not_os_proof')
    add('read_only_mount_effective', 'not_verified', 'write_denial_is_not_mount_attestation')
    add('filesystem_visibility_boundary', 'not_verified', 'single_canary_is_not_complete_host_boundary')
    for key in ('memory_max_bytes', 'cpu_quota_usec_per_sec', 'tasks_max'):
        actual = observations['resources'][key]
        add(key, 'failed' if actual is not None and actual != profile['limits'][key] else 'not_verified',
            'configured_value_is_not_effectiveness')
    add('runtime_limit_effective', 'not_verified', 'independent_timer_evidence_missing')
    child = observations['child']
    if child['state'] == 'not_run':state = 'not_verified'
    elif child['state'] == 'lost_early' or not child['alive_at_observation']:state = 'failed'
    else:state = 'passed' if child['cgroup'] == expected['cgroup'] else 'failed'
    add('child_membership', state, 'bounded_fixture_observation')
    for name in ('process_tree_abort', 'complete_process_end', 'final_acknowledgement'):
        add(name, 'not_verified', 'independent_host_end_receipt_missing')
    for name in NETWORK:add(name, 'not_verified', 'active_network_test_not_implemented')
    return result


def make_report(profile, observations, *, report_id=None, observed_at=None, stage='complete'):
    validate_profile(profile, digest(profile));validate_observations(observations)
    need(stage in ('complete', 'pre_stop', 'gate_rejected'), 'stage_invalid')
    report_id = str(uuid.uuid4()) if report_id is None else report_id;identifier(report_id)
    observed_at = now() if observed_at is None else observed_at
    need(timestamp(observed_at) >= timestamp(profile['created_at']), 'report_time_invalid')
    rows = checks(profile, observations)
    return dict(kind='isolation_test_report', profile_version=VERSION, test_id=profile['test_id'],
                report_id=report_id, profile_sha256=digest(profile), observed_at=observed_at, stage=stage,
                observations=observations, checks=rows,
                overall_status='failed' if any(x['status'] == 'failed' for x in rows) else 'not_verified',
                isolation_verified=False, assurance='untrusted_probe_observations',
                missing_evidence=[x['check_id'] for x in rows if x['status'] == 'not_verified'])


def validate_report(report, profile, expected_profile_sha256, expected_report_sha256):
    validate_profile(profile, expected_profile_sha256);hash_value(expected_report_sha256)
    need(digest(report) == expected_report_sha256, 'report_hash_mismatch')
    obj(report, ('kind', 'profile_version', 'test_id', 'report_id', 'profile_sha256', 'observed_at', 'stage',
                 'observations', 'checks', 'overall_status', 'isolation_verified', 'assurance', 'missing_evidence'))
    expected = make_report(profile, report['observations'], report_id=report['report_id'],
                           observed_at=report['observed_at'], stage=report['stage'])
    need(canonical(report) == canonical(expected), 'report_claim_inconsistent')
    return report
