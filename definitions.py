#!/usr/bin/env python3
"""Read-only S1 definition validation. No execution, network, database or scoring."""
import argparse
from dataclasses import dataclass
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import stat
import sys
import uuid


class DefinitionError(ValueError):
    """Stable code and schema location; never includes untrusted values/host paths."""
    def __init__(self, code, location='$'):
        self.code, self.location = code, location
        super().__init__(code + ' at ' + location)


def require(condition, code, location='$'):
    if not condition:
        raise DefinitionError(code, location)


@dataclass(frozen=True)
class Limits:
    max_json_bytes: int = 1024 * 1024
    max_depth: int = 32
    max_nodes: int = 50000
    max_string_bytes: int = 262144
    max_integer_bits: int = 4096
    max_assets: int = 1000
    max_asset_bytes: int = 16 * 1024 * 1024
    max_total_asset_bytes: int = 64 * 1024 * 1024
    max_directory_entries: int = 10000

    def __post_init__(self):
        for value in vars(self).values():
            require(type(value) is int and value > 0, 'limits_invalid')


DEFAULT_LIMITS = Limits()
HASH = re.compile(r'[0-9a-f]{64}\Z')
DECIMAL = re.compile(r'-?(?:0|[1-9][0-9]*)(?:\.[0-9]*[1-9])?\Z')
RESERVED_DISCIPLINES = frozenset(('coding', 'code_analysis', 'question_answer'))


def _tree(value, limits):
    """Iterative validation prevents recursion/cycle crashes before JSON encoding."""
    stack = [(value, int(type(value) in (dict, list)), frozenset())]
    count = 0
    while stack:
        v, depth, ancestors = stack.pop()
        count += 1
        require(count <= limits.max_nodes, 'json_node_limit')
        require(depth <= limits.max_depth, 'json_depth_limit')
        if type(v) is str:
            try:
                data = v.encode('utf-8', errors='strict')
            except UnicodeError:
                raise DefinitionError('json_unicode_invalid') from None
            require(len(data) <= limits.max_string_bytes, 'json_string_limit')
        elif type(v) is int:
            require(v.bit_length() <= limits.max_integer_bits, 'json_integer_limit')
        elif v is None or type(v) is bool:
            pass
        elif type(v) in (dict, list):
            require(id(v) not in ancestors, 'json_cycle')
            chain = ancestors | {id(v)}
            require(len(v) <= limits.max_nodes, 'json_node_limit')
            if type(v) is dict:
                require(all(type(k) is str for k in v), 'json_key_type')
                stack.extend((k, depth, chain) for k in v)
                stack.extend((x, depth + int(type(x) in (dict, list)), chain) for x in v.values())
            else:
                stack.extend((x, depth + int(type(x) in (dict, list)), chain) for x in v)
        else:
            raise DefinitionError('json_type_invalid')


def canonical_json_bytes(value, *, limits=DEFAULT_LIMITS):
    _tree(value, limits)
    try:
        encoder = json.JSONEncoder(sort_keys=True, ensure_ascii=False,
                                   separators=(',', ':'), allow_nan=False)
        parts, size = [], 0
        for chunk in encoder.iterencode(value):
            data = chunk.encode('utf-8')
            size += len(data)
            require(size <= limits.max_json_bytes, 'json_size_limit')
            parts.append(data)
        return b''.join(parts)
    except DefinitionError:
        raise
    except (ValueError, RecursionError, UnicodeError):
        raise DefinitionError('json_encoding_invalid') from None


def content_sha256(value, *, limits=DEFAULT_LIMITS):
    return hashlib.sha256(canonical_json_bytes(value, limits=limits)).hexdigest()


def _hash(value, location='$'):
    require(type(value) is str and HASH.fullmatch(value), 'sha256_invalid', location)


def verify_content_sha256(value, expected, *, limits=DEFAULT_LIMITS):
    _hash(expected)
    actual = content_sha256(value, limits=limits)
    require(hmac.compare_digest(actual, expected), 'content_hash_mismatch')
    return actual


def parse_json_bytes(data, *, limits=DEFAULT_LIMITS):
    require(type(data) is bytes, 'json_input_type')
    require(len(data) <= limits.max_json_bytes, 'json_size_limit')
    require(not data.startswith(b'\xef\xbb\xbf'), 'json_bom_forbidden')
    try:
        text = data.decode('utf-8', errors='strict')
    except UnicodeError:
        raise DefinitionError('json_utf8_invalid') from None
    # Bound depth before the recursive standard-library decoder sees the input.
    depth = 0
    quoted = escaped = False
    for c in text:
        if quoted:
            if escaped:
                escaped = False
            elif c == '\\':
                escaped = True
            elif c == '"':
                quoted = False
        elif c == '"':
            quoted = True
        elif c in '[{':
            depth += 1
            require(depth <= limits.max_depth, 'json_depth_limit')
        elif c in ']}':
            depth -= 1
    def pairs(items):
        obj = {}
        for key, value in items:
            require(key not in obj, 'json_duplicate_key')
            obj[key] = value
        return obj
    def forbidden(_):
        raise DefinitionError('json_number_forbidden')
    try:
        value = json.loads(text, object_pairs_hook=pairs, parse_float=forbidden,
                           parse_constant=forbidden)
    except DefinitionError:
        raise
    except (ValueError, RecursionError):
        raise DefinitionError('json_invalid') from None
    _tree(value, limits)
    return value


def _signature(st):
    return (st.st_dev, st.st_ino, st.st_mode, st.st_size, st.st_mtime_ns,
            st.st_ctime_ns, st.st_nlink)


def _read_fd(parent, name, limit, *, expected_size=None):
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
    try:
        before = os.fstat(fd)
        require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1, 'file_unsafe')
        require(before.st_size <= limit, 'file_size_limit')
        if expected_size is not None:
            require(before.st_size == expected_size, 'asset_size_mismatch')
        parts, size = [], 0
        while size <= limit:
            part = os.read(fd, min(65536, limit + 1 - size))
            if not part:
                break
            parts.append(part)
            size += len(part)
        after = os.fstat(fd)
        current = os.stat(name, dir_fd=parent, follow_symlinks=False)
        require(_signature(before) == _signature(after) == _signature(current)
                and size == after.st_size and size <= limit, 'file_changed')
        return b''.join(parts), _signature(after)
    finally:
        os.close(fd)


def _open_directory(path):
    """Walk all path components without following links. No owner/mode assumptions."""
    path = Path(path).absolute()
    require('..' not in path.parts, 'path_unsafe')
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        return fd
    except BaseException:
        os.close(fd)
        raise


def load_json(path, *, limits=DEFAULT_LIMITS):
    """Read a bounded ordinary file; never writes or echoes a filesystem path."""
    parent = None
    try:
        path = Path(path).absolute()
        parent = _open_directory(path.parent)
        identity_parent = _signature(os.fstat(parent))
        data, identity = _read_fd(parent, path.name, limits.max_json_bytes)
        value = parse_json_bytes(data, limits=limits)
        require(_signature(os.stat(path.name, dir_fd=parent, follow_symlinks=False)) == identity,
                'file_changed')
        current = _open_directory(path.parent)
        try:
            require(_signature(os.fstat(current)) == identity_parent, 'file_changed')
        finally:
            os.close(current)
        return value
    except (OSError, TypeError, UnicodeError):
        raise DefinitionError('file_access_failed') from None
    finally:
        if parent is not None:
            os.close(parent)


def validate_decimal_string(value, *, nonnegative=False):
    require(type(value) is str and DECIMAL.fullmatch(value) and value != '-0',
            'decimal_invalid')
    require(not nonnegative or not value.startswith('-'), 'decimal_negative')
    return value


def _object(value, required, location, optional=()):
    require(type(value) is dict, 'object_required', location)
    require(not set(value) - set(required) - set(optional), 'unknown_field', location)
    require(set(required) <= set(value), 'missing_field', location)


def _text(value, location):
    require(type(value) is str and bool(value.strip()), 'text_invalid', location)


def _int(value, location, minimum=1):
    require(type(value) is int and value >= minimum, 'integer_invalid', location)


def _id(value, location):
    _text(value, location)


def _uuid(value, location):
    try:
        require(type(value) is str and str(uuid.UUID(value)) == value, 'uuid_invalid', location)
    except (ValueError, AttributeError):
        raise DefinitionError('uuid_invalid', location) from None


def _header(value, kind):
    require(value['kind'] == kind, 'kind_invalid')
    require(type(value['schema_version']) is int and value['schema_version'] == 1,
            'schema_version_unsupported')


def _list(value, location, nonempty=False):
    require(type(value) is list and (bool(value) or not nonempty), 'list_invalid', location)


@dataclass(frozen=True)
class CheckRule:
    metric: str
    operators: tuple
    expected: str  # 'decimal' or 'status'


@dataclass(frozen=True)
class DisciplineProfile:
    name: str
    adapters: tuple
    rules: tuple
    # Definition support is deliberately independent of executable adapters.
    executable: bool = False


class DisciplineRegistry:
    """Explicit Python registration only; JSON cannot import or execute plugins."""
    def __init__(self, profiles=()):
        self._profiles = {}
        for profile in profiles:
            self.register(profile)

    def register(self, profile):
        require(type(profile) is DisciplineProfile and profile.executable is False,
                'profile_invalid')
        _id(profile.name, '$.profile')
        require(profile.name not in self._profiles, 'profile_duplicate')
        require(type(profile.adapters) is tuple and bool(profile.adapters)
                and all(type(name) is str for name in profile.adapters)
                and len(set(profile.adapters)) == len(profile.adapters), 'profile_invalid')
        for name in profile.adapters:
            _id(name, '$.profile.adapter')
        require(type(profile.rules) is tuple and bool(profile.rules), 'profile_invalid')
        seen = set()
        for rule in profile.rules:
            require(type(rule) is CheckRule and type(rule.metric) is str
                    and rule.metric and rule.metric not in seen
                    and rule.expected in ('decimal', 'status') and type(rule.operators) is tuple
                    and bool(rule.operators) and all(x in ('eq', 'gte', 'lte') for x in rule.operators),
                    'profile_invalid')
            seen.add(rule.metric)
        self._profiles[profile.name] = profile

    def get(self, name):
        _id(name, '$.discipline')
        require(name in self._profiles, 'discipline_unsupported', '$.discipline')
        return self._profiles[name]


DEFAULT_REGISTRY = DisciplineRegistry((DisciplineProfile('performance',
    ('performance_checks',), (
        CheckRule('execution.status', ('eq',), 'status'),
        CheckRule('tokens_per_second', ('gte', 'lte'), 'decimal'),
        CheckRule('prompt_tokens_per_second', ('gte', 'lte'), 'decimal'),
    )),))


def _asset_path(value):
    require(type(value) is str and bool(value) and not value.startswith('/'), 'asset_path_invalid')
    parts = value.split('/')
    require(all(p not in ('', '.', '..') for p in parts)
            and len(set(parts)) == len(parts)
            and not any(c in value for c in '\\:*?[]')
            and not any(ord(c) < 32 or ord(c) == 127 for c in value), 'asset_path_invalid')
    return parts


def _inventory(assets, limits):
    _list(assets, '$.assets')
    require(len(assets) <= limits.max_assets, 'asset_count_limit')
    paths = set()
    total = 0
    for asset in assets:
        _object(asset, ('path', 'sha256', 'size_bytes', 'role'), '$.assets[]')
        _asset_path(asset['path'])
        require(asset['path'] not in paths, 'asset_duplicate')
        paths.add(asset['path'])
        _hash(asset['sha256'], '$.assets[].sha256')
        _int(asset['size_bytes'], '$.assets[].size_bytes', 0)
        require(asset['role'] in ('input', 'test'), 'asset_role_invalid')
        require(asset['size_bytes'] <= limits.max_asset_bytes, 'asset_size_limit')
        total += asset['size_bytes']
    require(total <= limits.max_total_asset_bytes, 'asset_total_limit')
    return paths


def validate_assets(assets, root=None, *, limits=DEFAULT_LIMITS):
    """Validate an exact dedicated tree. Symlinks, hardlinks and extra files fail."""
    canonical_json_bytes(assets, limits=limits)
    expected = _inventory(assets, limits)
    require(root is not None or not assets, 'asset_root_required')
    if root is None:
        return
    base = None
    observed = []
    count = 0
    def open_parent(parts):
        fd = os.dup(base)
        try:
            for part in parts[:-1]:
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd)
                fd = child
            return fd
        except BaseException:
            os.close(fd)
            raise
    try:
        base = _open_directory(root)
        root_identity = _signature(os.fstat(base))
        found = set()
        def walk(folder, prefix, depth):
            nonlocal count
            require(depth <= limits.max_depth, 'asset_depth_limit')
            with os.scandir(folder) as entries:
                for entry in entries:
                    count += 1
                    require(count <= limits.max_directory_entries, 'asset_entry_limit')
                    name = prefix + entry.name
                    _asset_path(name)
                    info = entry.stat(follow_symlinks=False)
                    if stat.S_ISDIR(info.st_mode):
                        fd = os.open(entry.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=folder)
                        try:
                            identity = _signature(os.fstat(fd))
                            require(identity == _signature(info), 'file_changed')
                            observed.append((name, identity))
                            walk(fd, name + '/', depth + 1)
                        finally:
                            os.close(fd)
                    else:
                        require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1, 'file_unsafe')
                        require(name in expected, 'asset_inventory_mismatch')
                        found.add(name)
        walk(base, '', 0)
        require(found == expected, 'asset_inventory_mismatch')
        for asset in assets:
            parts = _asset_path(asset['path'])
            fd = open_parent(parts)
            try:
                data, identity = _read_fd(fd, parts[-1], limits.max_asset_bytes,
                                          expected_size=asset['size_bytes'])
                require(hmac.compare_digest(hashlib.sha256(data).hexdigest(), asset['sha256']),
                        'asset_hash_mismatch')
                observed.append((asset['path'], identity))
            finally:
                os.close(fd)
        for name, identity in observed:
            parts = _asset_path(name)
            fd = open_parent(parts)
            try:
                require(_signature(os.stat(parts[-1], dir_fd=fd, follow_symlinks=False)) == identity,
                        'file_changed')
            finally:
                os.close(fd)
        current = _open_directory(root)
        try:
            require(_signature(os.fstat(base)) == root_identity
                    and _signature(os.fstat(current)) == root_identity, 'file_changed')
        finally:
            os.close(current)
    except (OSError, TypeError, UnicodeError):
        raise DefinitionError('asset_access_failed') from None
    finally:
        if base is not None:
            os.close(base)


def _revision(value, previous, identity, revision, limits):
    require(previous[identity] == value[identity], 'previous_identity_mismatch')
    require(value[revision] >= previous[revision], 'revision_rollback')
    if value[revision] == previous[revision]:
        require(canonical_json_bytes(value, limits=limits) == canonical_json_bytes(previous, limits=limits),
                'revision_conflict')


def _rubric_shape(value, registry, limits):
    _object(value, ('kind', 'schema_version', 'rubric_id', 'revision', 'name', 'discipline',
                    'categories', 'test_suites', 'mandatory_tests', 'grading'), '$')
    _header(value, 'rubric')
    _uuid(value['rubric_id'], '$.rubric_id')
    _int(value['revision'], '$.revision')
    _text(value['name'], '$.name')
    profile = registry.get(value['discipline'])
    _object(value['grading'], ('mode',), '$.grading')
    require(value['grading']['mode'] == 'score_only', 'grading_unsupported')
    _list(value['categories'], '$.categories', True)
    categories, total = set(), 0
    for c in value['categories']:
        _object(c, ('category_id', 'name', 'source', 'weight_bps', 'max_points', 'anchors'),
                '$.categories[]', ('test_suite_id',))
        _id(c['category_id'], '$.categories[].category_id')
        require(c['category_id'] not in categories, 'category_duplicate')
        categories.add(c['category_id'])
        _text(c['name'], '$.categories[].name')
        require(c['source'] in ('deterministic', 'human', 'llm_jury'), 'source_invalid')
        _int(c['weight_bps'], '$.categories[].weight_bps')
        total += c['weight_bps']
        _int(c['max_points'], '$.categories[].max_points')
        _list(c['anchors'], '$.categories[].anchors', True)
        anchors = set()
        for anchor in c['anchors']:
            _object(anchor, ('points', 'description'), '$.categories[].anchors[]')
            _int(anchor['points'], '$.categories[].anchors[].points', 0)
            require(anchor['points'] <= c['max_points'], 'anchor_out_of_range')
            require(anchor['points'] not in anchors, 'anchor_duplicate')
            anchors.add(anchor['points'])
            _text(anchor['description'], '$.categories[].anchors[].description')
        require({0, c['max_points']} <= anchors, 'anchor_endpoints_missing')
    require(total == 10000, 'weight_sum_invalid')
    _list(value['test_suites'], '$.test_suites')
    suites, tests, all_assets = set(), set(), []
    rules = {rule.metric: rule for rule in profile.rules}
    for suite in value['test_suites']:
        _object(suite, ('suite_id', 'adapter', 'version', 'checks', 'assets'), '$.test_suites[]')
        _id(suite['suite_id'], '$.test_suites[].suite_id')
        require(suite['suite_id'] not in suites, 'suite_duplicate')
        suites.add(suite['suite_id'])
        require(type(suite['adapter']) is str and suite['adapter'] in profile.adapters,
                'test_adapter_unsupported')
        require(type(suite['version']) is int and suite['version'] == 1,
                'test_adapter_version_unsupported')
        _list(suite['checks'], '$.test_suites[].checks', True)
        for check in suite['checks']:
            _object(check, ('test_id', 'metric', 'operator', 'expected'), '$.test_suites[].checks[]')
            _id(check['test_id'], '$.test_suites[].checks[].test_id')
            require(check['test_id'] not in tests, 'test_duplicate')
            tests.add(check['test_id'])
            require(type(check['metric']) is str and check['metric'] in rules, 'metric_unsupported')
            rule = rules[check['metric']]
            require(type(check['operator']) is str and check['operator'] in rule.operators,
                    'operator_unsupported')
            if rule.expected == 'decimal':
                validate_decimal_string(check['expected'], nonnegative=True)
            else:
                require(type(check['expected']) is str and check['expected'] in
                        ('succeeded', 'failed', 'timed_out', 'cancelled'), 'expected_invalid')
        _inventory(suite['assets'], limits)
        all_assets.extend(suite['assets'])
    for c in value['categories']:
        if 'test_suite_id' in c:
            require(type(c['test_suite_id']) is str and c['test_suite_id'] in suites,
                    'suite_reference_missing')
    _list(value['mandatory_tests'], '$.mandatory_tests')
    mandatory = set()
    for test in value['mandatory_tests']:
        _id(test, '$.mandatory_tests[]')
        require(test not in mandatory, 'mandatory_test_duplicate')
        mandatory.add(test)
        require(test in tests, 'mandatory_test_missing')
    _inventory(all_assets, limits)
    return all_assets


def validate_rubric(value, *, asset_root=None, previous=None, registry=DEFAULT_REGISTRY,
                    limits=DEFAULT_LIMITS):
    canonical_json_bytes(value, limits=limits)
    assets = _rubric_shape(value, registry, limits)
    if previous is not None:
        canonical_json_bytes(previous, limits=limits)
        _rubric_shape(previous, registry, limits)
        _revision(value, previous, 'rubric_id', 'revision', limits)
    validate_assets(assets, asset_root, limits=limits)
    return json.loads(canonical_json_bytes(value, limits=limits))


def _competition_shape(value, registry):
    _object(value, ('kind', 'schema_version', 'competition_id', 'name', 'definition_revision',
                    'discipline', 'prompt', 'assets', 'rubric'), '$')
    _header(value, 'competition')
    _uuid(value['competition_id'], '$.competition_id')
    _int(value['definition_revision'], '$.definition_revision')
    _text(value['name'], '$.name')
    registry.get(value['discipline'])
    _object(value['prompt'], ('version', 'text', 'sha256'), '$.prompt')
    _int(value['prompt']['version'], '$.prompt.version')
    _text(value['prompt']['text'], '$.prompt.text')
    _hash(value['prompt']['sha256'], '$.prompt.sha256')
    require(hmac.compare_digest(hashlib.sha256(value['prompt']['text'].encode('utf-8')).hexdigest(),
                                value['prompt']['sha256']), 'prompt_hash_mismatch')
    _object(value['rubric'], ('rubric_id', 'revision', 'sha256'), '$.rubric')
    _uuid(value['rubric']['rubric_id'], '$.rubric.rubric_id')
    _int(value['rubric']['revision'], '$.rubric.revision')
    _hash(value['rubric']['sha256'], '$.rubric.sha256')


def validate_competition(value, rubric, *, asset_root=None, rubric_asset_root=None,
                         previous=None, registry=DEFAULT_REGISTRY, limits=DEFAULT_LIMITS):
    canonical_json_bytes(value, limits=limits)
    _competition_shape(value, registry)
    validated = validate_rubric(rubric, asset_root=rubric_asset_root, registry=registry, limits=limits)
    require(value['discipline'] == validated['discipline'], 'rubric_discipline_mismatch')
    require(value['rubric']['rubric_id'] == validated['rubric_id']
            and value['rubric']['revision'] == validated['revision'], 'rubric_reference_mismatch')
    require(hmac.compare_digest(value['rubric']['sha256'], content_sha256(validated, limits=limits)),
            'rubric_hash_mismatch')
    if previous is not None:
        canonical_json_bytes(previous, limits=limits)
        _competition_shape(previous, registry)
        _inventory(previous['assets'], limits)
        _revision(value, previous, 'competition_id', 'definition_revision', limits)
        require(value['prompt']['version'] >= previous['prompt']['version'], 'prompt_version_rollback')
        if value['prompt']['text'] != previous['prompt']['text']:
            require(value['prompt']['version'] > previous['prompt']['version'], 'prompt_version_conflict')
    validate_assets(value['assets'], asset_root, limits=limits)
    return json.loads(canonical_json_bytes(value, limits=limits))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('kind', choices=('competition', 'rubric'))
    parser.add_argument('file', type=Path)
    parser.add_argument('--rubric', type=Path)
    parser.add_argument('--assets', type=Path, help='Dedicated exact asset root, never modified')
    parser.add_argument('--rubric-assets', type=Path)
    parser.add_argument('--previous', type=Path, help='Previously trusted definition for revision binding')
    args = parser.parse_args(argv)
    try:
        require(args.kind == 'competition' or (args.rubric is None and args.rubric_assets is None),
                'cli_arguments_invalid')
        require(args.kind != 'competition' or args.rubric is not None, 'rubric_required')
        value = load_json(args.file)
        previous = load_json(args.previous) if args.previous else None
        if args.kind == 'competition':
            result = validate_competition(value, load_json(args.rubric), asset_root=args.assets,
                                          rubric_asset_root=args.rubric_assets, previous=previous)
        else:
            result = validate_rubric(value, asset_root=args.assets, previous=previous)
        print(json.dumps({'ok': True, 'kind': args.kind, 'sha256': content_sha256(result),
                          'executable': False, 'history_checked': previous is not None}, separators=(',', ':')))
        return 0
    except DefinitionError as exc:
        print(json.dumps({'ok': False, 'code': exc.code, 'location': exc.location}))
        return 2
    except (OSError, ValueError, TypeError):
        print(json.dumps({'ok': False, 'code': 'input_invalid', 'location': '$'}))
        return 2


if __name__ == '__main__':
    sys.exit(main())
