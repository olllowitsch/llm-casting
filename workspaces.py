#!/usr/bin/env python3
"""S3 local workspace/journal/archive management. Never executes participant code."""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import stat
import sys
import uuid

import definitions as d
import planning as p

ROOT = Path(__file__).resolve().parent
STATES = ('planned', 'prepared', 'active', 'collecting', 'archived', 'failed', 'uncertain')
MEDIA_TYPES = frozenset(('text/plain', 'text/markdown', 'text/x-python', 'text/html',
                         'application/json', 'application/octet-stream'))
MAX_EVENTS = 1000
MAX_ENTRIES = 10000
MAX_FILE_BYTES = 16 * 1024 * 1024
MAX_TOTAL_BYTES = 100 * 1024 * 1024


def _need(ok, code):
    d.require(ok, code)


def _now():
    return datetime.now(timezone.utc).isoformat(timespec='microseconds').replace('+00:00', 'Z')


def _checkpoint(_name):
    """Fault-injection seam; no external hooks or executable configuration."""


def _path(value):
    parts = d._asset_path(value)
    _need(len(value.encode('utf-8')) <= 4096 and len(parts) <= 32
          and all(len(s.encode('utf-8')) <= 128 for s in parts), 'path_limit')
    return parts


def _leaf_path(value):
    parts = _path(value)
    _need(len(parts) <= 16 and len(value.encode('utf-8')) <= 1024, 'path_limit')
    return parts


def _identity(value, plan):
    d._object(value, ('run_id', 'participant_id', 'repetition', 'attempt_id', 'plan_sha256'), '$.identity')
    for name in ('run_id', 'participant_id', 'attempt_id'):
        d._uuid(value[name], '$.identity.'+name)
    _need(type(value['repetition']) is int and
          (value['participant_id'], value['repetition']) in p.measurement_slots(plan), 'measurement_slot_invalid')
    _need(value['run_id'] == plan.as_dict()['run_id'] and value['plan_sha256'] == plan.sha256,
          'identity_plan_mismatch')
    # S2 inventory paths retain S1's no-repeated-components rule. Fail before any intent.
    _path(_base(value, 'workspaces')+'/inputs')
    _path(_base(value, 'artifacts')+'/files')
    return p._copy(value)


def _base(identity, area):
    return '/'.join((area, identity['run_id'], identity['participant_id'], identity['attempt_id']))


def _specs(value, policy):
    d._list(value, '$.outputs')
    _need(len(value) <= min(policy['max_files'], 1000), 'artifact_count_limit')
    seen = set()
    for item in value:
        d._object(item, ('path', 'media_type'), '$.outputs[]')
        _leaf_path(item['path'])
        _need(item['path'] not in seen, 'artifact_duplicate')
        _need(item['media_type'] in MEDIA_TYPES, 'media_type_unsupported')
        seen.add(item['path'])
    # A file cannot simultaneously be an ancestor of another file.
    _need(not any('/'.join(_path(x)[:n]) in seen for x in seen
                  for n in range(1, len(_path(x)))), 'artifact_path_conflict')
    return p._copy(value)


def isolation_check(plan=None):
    """Declarative requirements and passive availability, NEVER an execution permit."""
    if plan is not None:
        p._context(plan)
    return dict(kind='isolation_check', schema_version=1, executable=False,
                profile='s3_storage_only', os_isolation_verified=False,
                process_quiescence='unknown', unknown_children='block_execution',
                capabilities=dict(dir_fd=os.open in os.supports_dir_fd,
                                  nofollow=hasattr(os, 'O_NOFOLLOW'),
                                  flock=hasattr(fcntl, 'flock'),
                                  no_replace_publish=hasattr(p.ctypes.CDLL(None), 'renameat2')),
                required=dict(write='own_output_only', read='pinned_inputs_and_runtime_only',
                              network='deny_by_default', subprocess='deny_until_adapter_verified',
                              environment='explicit_allowlist_no_inherited_secrets',
                              cpu='hard_limit_required', ram='hard_limit_required',
                              disk='hard_quota_required', cancellation='verified_process_tree_stop',
                              host='no_host_mounts_or_shared_writable_files'),
                reasons=['execution_not_implemented', 'os_sandbox_not_implemented',
                         'resource_enforcement_not_implemented', 'process_control_not_implemented'])


def validate_manifest(value, plan, identity, *, expected_sha256=None):
    """Validate immutable S2 artifact metadata and exact attempt-relative binding."""
    _identity(identity, plan)
    v = p._copy(value)
    d._object(v, ('kind', 'schema_version', 'identity', 'artifacts'), '$.manifest')
    d._header(v, 'artifact_manifest')
    _need(v['identity'] == identity, 'manifest_identity_mismatch')
    policy = plan.as_dict()['policy']
    p.validate_artifacts(v['artifacts'], max_files=min(policy['max_files'], 1000),
                         max_bytes=min(policy['max_artifact_bytes'], MAX_TOTAL_BYTES))
    prefix = _base(identity, 'artifacts') + '/files/'
    for a in v['artifacts']:
        _need(a['path'].startswith(prefix), 'artifact_binding_mismatch')
        _leaf_path(a['path'][len(prefix):])
        _need(a['size_bytes'] <= MAX_FILE_BYTES, 'file_size_limit')
        _need(a['classification'] == 'private', 'artifact_not_private')
        _need(a['media_type'] in MEDIA_TYPES, 'media_type_unsupported')
    if expected_sha256 is not None:
        d.verify_content_sha256(v, expected_sha256)
    return v


class WorkspaceStore:
    """Exclusive local writer context. All returned states are copies; no executor."""
    def __init__(self, root, *, create=True):
        self.root = Path(root).absolute()
        _need(self.root.is_relative_to(ROOT) and self.root != ROOT
              and '..' not in self.root.parts
              and not any(x in ('.git', 'results', 'reports', 'tests', 'scenarios', 'docs', 'schemas')
                          for x in self.root.relative_to(ROOT).parts), 'store_path_invalid')
        self.create = create
        self.fd = self.lock = None
        self.poisoned = False
        self._collections = {}

    def __enter__(self):
        parent = None
        _need(self.fd is None and not self.poisoned, 'store_write_uncertain')
        try:
            parent = d._open_directory(self.root.parent)
            try:
                if not self.create:
                    raise FileExistsError
                os.mkdir(self.root.name, 0o700, dir_fd=parent)
                os.fsync(parent)
                fresh = True
            except FileExistsError:
                fresh = False
            self.fd = d._open_directory(self.root)
            info = os.fstat(self.fd)
            _need(info.st_uid == os.geteuid() and info.st_mode & 0o077 == 0, 'store_permissions_unsafe')
            flags = os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK
            self.lock = os.open('writer.lock', flags | (os.O_CREAT | os.O_EXCL if fresh else 0),
                                0o600, dir_fd=self.fd)
            st = os.fstat(self.lock)
            _need(stat.S_ISREG(st.st_mode) and st.st_nlink == 1, 'lock_unsafe')
            try:
                fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise d.DefinitionError('writer_busy') from None
            self._bound()
            if fresh:
                for name in ('workspaces', 'artifacts', 'journals'):
                    self._mkdir(name)
                self._json('store.json', dict(kind='workspace_store', schema_version=1))
            _need(set(self._names('')) == {'writer.lock', 'store.json', 'workspaces', 'artifacts', 'journals'},
                  'store_layout_invalid')
            _need(self._json_read('store.json') == dict(kind='workspace_store', schema_version=1),
                  'store_version_invalid')
            for name in ('workspaces', 'artifacts', 'journals'):
                with self._dir(name):
                    pass
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise
        finally:
            if parent is not None:
                os.close(parent)

    def __exit__(self, *_):
        if self.lock is not None:
            os.close(self.lock)
            self.lock = None
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None
        self._collections.clear()

    def _bound(self):
        _need(self.fd is not None and self.lock is not None, 'store_not_open')
        current = d._open_directory(self.root)
        try:
            info = os.fstat(current)
            _need(info.st_uid == os.geteuid() and info.st_mode & 0o077 == 0, 'store_permissions_unsafe')
            _need((os.fstat(current).st_dev, os.fstat(current).st_ino) ==
                  (os.fstat(self.fd).st_dev, os.fstat(self.fd).st_ino), 'store_root_changed')
            a = os.fstat(self.lock)
            b = os.stat('writer.lock', dir_fd=self.fd, follow_symlinks=False)
            _need(d._signature(a) == d._signature(b) and a.st_nlink == 1, 'lock_changed')
        finally:
            os.close(current)

    def _writable(self):
        self._bound()
        _need(not self.poisoned, 'store_write_uncertain')

    @contextmanager
    def _dir(self, relative):
        parts = _path(relative) if relative else []
        fd = os.dup(self.fd)
        try:
            for name in parts:
                child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd)
                fd = child
                _need(os.fstat(fd).st_dev == os.fstat(self.fd).st_dev, 'filesystem_boundary')
            yield fd
        finally:
            os.close(fd)

    def _names(self, relative):
        with self._dir(relative) as fd:
            names = []
            with os.scandir(fd) as entries:
                for entry in entries:
                    names.append(entry.name)
                    _need(len(names) <= MAX_ENTRIES, 'directory_entry_limit')
            return sorted(names)

    def _mkdir(self, relative, *, existing=False):
        parts = _path(relative)
        for n in range(1, len(parts)+1):
            with self._dir('/'.join(parts[:n-1])) as fd:
                try:
                    os.mkdir(parts[n-1], 0o700, dir_fd=fd)
                    os.fsync(fd)
                except FileExistsError:
                    _need(n != len(parts) or existing, 'directory_exists')
            with self._dir('/'.join(parts[:n])):
                pass
        self._bound()

    def _read(self, relative, limit=MAX_FILE_BYTES):
        parts = _path(relative)
        with self._dir('/'.join(parts[:-1])) as fd:
            data, signature = d._read_fd(fd, parts[-1], limit)
            _need(signature[0] == os.fstat(self.fd).st_dev, 'filesystem_boundary')
            # Reopen the path to catch directory exchange while the descriptor was pinned.
            with self._dir('/'.join(parts[:-1])) as current:
                st = os.stat(parts[-1], dir_fd=current, follow_symlinks=False)
                _need(d._signature(st) == signature, 'file_changed')
        self._bound()
        return data

    def _json_read(self, relative):
        return d.parse_json_bytes(self._read(relative, d.DEFAULT_LIMITS.max_json_bytes))

    def _publish(self, relative, data):
        self._writable()
        parts = _path(relative)
        _need(type(data) is bytes and len(data) <= MAX_FILE_BYTES, 'file_size_limit')
        tmp = '.s3-' + uuid.uuid4().hex + '.tmp'
        try:
            with self._dir('/'.join(parts[:-1])) as parent:
                fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent)
                owned = os.fstat(fd)
                with os.fdopen(fd, 'wb') as out:
                    out.write(data)
                    out.flush()
                    os.fchmod(out.fileno(), 0o400)
                    os.fsync(out.fileno())
                _checkpoint('file_synced')
                actual, signature = d._read_fd(parent, tmp, MAX_FILE_BYTES)
                _need(actual == data and signature[:2] == (owned.st_dev, owned.st_ino), 'file_changed')
                with self._dir('/'.join(parts[:-1])) as current:
                    _need((os.fstat(current).st_dev, os.fstat(current).st_ino) ==
                          (os.fstat(parent).st_dev, os.fstat(parent).st_ino), 'directory_changed')
                self._bound()
                _checkpoint('before_publication')
                p._publish_no_replace(parent, tmp, parts[-1])
                _checkpoint('published_before_fsync')
                os.fsync(parent)
                _need(self._read(relative) == data, 'file_changed')
                final = os.stat(parts[-1], dir_fd=parent, follow_symlinks=False)
                _need((final.st_dev, final.st_ino) == (owned.st_dev, owned.st_ino), 'file_changed')
                _checkpoint('publication_synced')
        except OSError:
            self.poisoned = True
            raise d.DefinitionError('storage_commit_uncertain') from None
        except BaseException:
            # Never delete a possibly published file or a replaced temporary file.
            self.poisoned = True
            raise

    def _json(self, relative, value):
        self._publish(relative, d.canonical_json_bytes(value))

    def _tree(self, relative):
        """Exact bounded tree of ordinary single-link files, including empty dirs."""
        result = {};dirs = set();observed = [];count = 0
        def walk(folder, prefix, depth):
            nonlocal count
            _need(depth <= 16, 'path_limit')
            with os.scandir(folder) as entries:
                for entry in entries:
                    count += 1
                    _need(count <= MAX_ENTRIES, 'directory_entry_limit')
                    name = prefix + entry.name
                    _path(name)
                    info = entry.stat(follow_symlinks=False)
                    _need(info.st_dev == os.fstat(self.fd).st_dev, 'filesystem_boundary')
                    observed.append((relative+'/'+name, d._signature(info)))
                    if stat.S_ISDIR(info.st_mode):
                        dirs.add(name)
                        child = os.open(entry.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=folder)
                        try:
                            _need(d._signature(os.fstat(child)) == d._signature(info), 'file_changed')
                            walk(child, name+'/', depth+1)
                        finally:
                            os.close(child)
                    else:
                        _need(stat.S_ISREG(info.st_mode) and info.st_nlink == 1, 'file_unsafe')
                        _need(info.st_size <= MAX_FILE_BYTES, 'file_size_limit')
                        result[name] = d._signature(info)
        with self._dir(relative) as fd:
            before = d._signature(os.fstat(fd))
            walk(fd, '', 0)
        for name, signature in observed:
            parts = _path(name)
            with self._dir('/'.join(parts[:-1])) as folder:
                _need(d._signature(os.stat(parts[-1], dir_fd=folder, follow_symlinks=False)) == signature,
                      'file_changed')
        with self._dir(relative) as current:
            _need(d._signature(os.fstat(current)) == before, 'directory_changed')
        return result, dirs

    def _inventory(self, relative, expected):
        """Verify exact inventory, bytes, directory names and all size limits."""
        files, dirs = self._tree(relative)
        _need(set(files) == {x['path'] for x in expected}, 'inventory_mismatch')
        allowed_dirs = {'/'.join(_path(x['path'])[:n]) for x in expected
                        for n in range(1, len(_path(x['path'])))}
        _need(dirs == allowed_dirs, 'inventory_mismatch')
        captured = []
        for item in expected:
            _need(files[item['path']][3] == item['size_bytes'], 'asset_size_mismatch')
            data = self._read(relative+'/'+item['path'])
            _need(len(data) == item['size_bytes'] and d.hashlib.sha256(data).hexdigest() == item['sha256'],
                  'asset_hash_mismatch')
            captured.append((item['path'], data))
        _need(self._tree(relative) == (files, dirs), 'inventory_changed')
        return captured

    def _copy_assets(self, assets, source, destination):
        self._mkdir(destination)
        d.validate_assets(assets, source)
        for asset in assets:
            _leaf_path(asset['path'])
            parent = None
            try:
                path = Path(source)/asset['path']
                parent = d._open_directory(path.parent)
                data, _ = d._read_fd(parent, path.name, MAX_FILE_BYTES, expected_size=asset['size_bytes'])
                _need(d.hashlib.sha256(data).hexdigest() == asset['sha256'], 'asset_hash_mismatch')
                if '/' in asset['path']:
                    self._mkdir(destination+'/'+asset['path'].rsplit('/', 1)[0], existing=True)
                self._publish(destination+'/'+asset['path'], data)
            finally:
                if parent is not None:
                    os.close(parent)
        d.validate_assets(assets, source)
        self._inventory(destination, assets)

    def register_run(self, plan, *, asset_root=None, rubric_asset_root=None):
        """Pin definitions and both input snapshots, or validate an existing exact run."""
        self._writable()
        p._context(plan)
        c = plan.competition();r = plan.rubric()
        for asset in c['assets'] + [a for suite in r['test_suites'] for a in suite['assets']]:
            _leaf_path(asset['path'])
        p.validate_run_plan(plan.as_dict(), c, r, asset_root=asset_root, rubric_asset_root=rubric_asset_root,
                            expected_sha256=plan.sha256)
        run = plan.as_dict()['run_id'];folder = 'journals/'+run
        if run in self._names('journals'):
            state = self.validate_journal(plan)['state']
            _need(state['phase'] == 'ready', 'operation_uncertain')
            return state
        try:
            self._mkdir(folder)
            bundle = dict(kind='run_bundle', schema_version=1, plan=plan.as_dict(), competition=c, rubric=r,
                          initial_result=p.initial_result(plan))
            self._json(folder+'/bundle.json', bundle)
            state = dict(phase='initializing', attempts=[])
            self._append(plan, state, bundle_sha256=d.content_sha256(bundle))
            self._copy_assets(c['assets'], asset_root, folder+'/inputs')
            tests = [a for suite in r['test_suites'] for a in suite['assets']]
            self._copy_assets(tests, rubric_asset_root, folder+'/rubric-assets')
            state['phase'] = 'ready'
            self._append(plan, state)
            return p._copy(state)
        except BaseException:
            self.poisoned = True
            raise

    def _append(self, plan, state, *, bundle_sha256=None):
        self._writable()
        folder = 'journals/'+plan.as_dict()['run_id']
        if bundle_sha256 is None:
            previous = self.validate_journal(plan, verify_files=False)
            seq = previous['sequence']+1;before = previous['head_sha256']
            bundle_sha256 = previous['bundle_sha256']
            _transition(previous['state'], state)
        else:
            seq = 1;before = None
        _state(state, plan)
        _need(seq <= MAX_EVENTS, 'journal_event_limit')
        event = dict(kind='workspace_event', schema_version=1, sequence=seq, previous_sha256=before,
                     run_id=plan.as_dict()['run_id'], plan_sha256=plan.sha256,
                     bundle_sha256=bundle_sha256, at=_now(), state=p._copy(state))
        self._json(folder+'/%08d.json'%seq, dict(event=event, sha256=d.content_sha256(event)))
        return event

    def validate_journal(self, plan, *, expected_head=None, verify_files=True):
        """Reconstruct a bounded chain; caller's plan/head pins are trust anchors."""
        self._bound();p._context(plan)
        folder = 'journals/'+plan.as_dict()['run_id']
        names = self._names(folder)
        events = [n for n in names if len(n) == 13 and n[:8].isdigit() and n.endswith('.json')]
        _need(len(events) <= MAX_EVENTS and events, 'journal_missing')
        _need(set(names) <= set(events) | {'bundle.json', 'inputs', 'rubric-assets'}, 'journal_uncommitted_files')
        _need(events == ['%08d.json'%n for n in range(1, len(events)+1)], 'journal_sequence_invalid')
        bundle = self._json_read(folder+'/bundle.json')
        d._object(bundle, ('kind', 'schema_version', 'plan', 'competition', 'rubric', 'initial_result'), '$.bundle')
        d._header(bundle, 'run_bundle')
        _need(bundle['plan'] == plan.as_dict() and bundle['competition'] == plan.competition()
              and bundle['rubric'] == plan.rubric(), 'bundle_plan_mismatch')
        p.validate_result(bundle['initial_result'], plan)
        _need(bundle['initial_result']['status'] == 'planned', 'bundle_result_invalid')
        digest = d.content_sha256(bundle);head = None;state = None;at = None
        for number, name in enumerate(events, 1):
            wrapped = self._json_read(folder+'/'+name)
            d._object(wrapped, ('event', 'sha256'), '$.journal')
            event = wrapped['event'];d.verify_content_sha256(event, wrapped['sha256'])
            d._object(event, ('kind', 'schema_version', 'sequence', 'previous_sha256', 'run_id',
                             'plan_sha256', 'bundle_sha256', 'at', 'state'), '$.event')
            d._header(event, 'workspace_event')
            _need(type(event['sequence']) is int and event['sequence'] == number
                  and event['previous_sha256'] == head and event['bundle_sha256'] == digest
                  and event['plan_sha256'] == plan.sha256 and event['run_id'] == plan.as_dict()['run_id'],
                  'journal_binding_mismatch')
            when = p._timestamp(event['at'])
            _need(at is None or when >= at, 'journal_time_invalid');at = when
            _state(event['state'], plan)
            if state is None:
                _need(event['state'] == dict(phase='initializing', attempts=[]), 'journal_genesis_invalid')
            else:
                _transition(state, event['state'])
            state = event['state'];head = wrapped['sha256']
        if expected_head is not None:
            d._hash(expected_head)
            _need(head == expected_head, 'journal_head_mismatch')
        if verify_files and state['phase'] == 'ready':
            self._audit_attempt_paths(plan, state)
            self._inventory(folder+'/inputs', plan.competition()['assets'])
            self._inventory(folder+'/rubric-assets', [a for s in plan.rubric()['test_suites'] for a in s['assets']])
            for record in state['attempts']:
                if record['status'] in ('prepared', 'collecting', 'archived'):
                    self._verify_workspace(plan, record)
                if record['status'] in ('collecting', 'archived'):
                    self.validate_inventory(plan, record['identity'], dict(kind='artifact_manifest', schema_version=1,
                                            identity=record['identity'], artifacts=record['artifacts']))
                if record['status'] == 'archived':
                    self.validate_archive(plan, record['identity'], expected_manifest=record['manifest_sha256'])
        self._bound()
        return dict(sequence=len(events), head_sha256=head, bundle_sha256=digest, state=p._copy(state))

    def _audit_attempt_paths(self, plan, state):
        run = plan.as_dict()['run_id']
        known_runs = set(self._names('journals'))
        for name in known_runs:
            d._uuid(name, '$.run_id')
            with self._dir('journals/'+name):
                pass
        for area in ('workspaces', 'artifacts'):
            _need(set(self._names(area)) <= known_runs, 'unknown_run_path')
            allowed = {}
            for rec in state['attempts']:
                if area == 'artifacts' and rec['status'] not in ('collecting', 'archived'):
                    continue
                i = rec['identity']
                allowed.setdefault(i['participant_id'], set()).add(i['attempt_id'])
            if run not in self._names(area):
                continue
            base = area+'/'+run
            _need(set(self._names(base)) <= set(allowed), 'unknown_attempt_path')
            for participant in self._names(base):
                _need(set(self._names(base+'/'+participant)) <= allowed[participant], 'unknown_attempt_path')
                for attempt in self._names(base+'/'+participant):
                    location = base+'/'+participant+'/'+attempt
                    with self._dir(location):
                        pass
                    if area == 'artifacts':
                        record = next(r for r in state['attempts'] if r['identity']['attempt_id'] == attempt)
                        if record['status'] == 'collecting':
                            files, directories = self._tree(location)
                            prefix = location+'/'
                            expected = {'manifest.json'} | {a['path'][len(prefix):] for a in record['artifacts']}
                            allowed_dirs = {'files'} | {'/'.join(name.split('/')[:n]) for name in expected
                                                        for n in range(1, len(name.split('/')))}
                            _need(set(files) <= expected and directories <= allowed_dirs,
                                  'archive_uncommitted_files')

    def _record(self, plan, identity):
        identity = _identity(identity, plan)
        journal = self.validate_journal(plan)
        _need(journal['state']['phase'] == 'ready', 'operation_uncertain')
        records = journal['state']['attempts']
        found = [x for x in records if x['identity'] == identity]
        _need(len(found) == 1, 'attempt_missing')
        return journal['state'], found[0]

    def _verify_workspace(self, plan, record):
        base = _base(record['identity'], 'workspaces')
        _need(set(self._names(base)) == {'inputs', 'outputs'}, 'workspace_layout_invalid')
        self._inventory(base+'/inputs', plan.competition()['assets'])
        # Prepared outputs can change, but must remain bounded normal files.
        self._tree(base+'/outputs')

    def prepare(self, plan, identity):
        """Persist intent first. Existing compatible prepared/archive states are read-only."""
        self._writable();identity = _identity(identity, plan)
        journal = self.validate_journal(plan)
        _need(journal['state']['phase'] == 'ready', 'operation_uncertain')
        state = journal['state']
        for record in state['attempts']:
            if record['identity']['attempt_id'] == identity['attempt_id']:
                _need(record['identity'] == identity, 'attempt_identity_conflict')
                _need(record['status'] in ('prepared', 'archived'), 'operation_uncertain')
                return p._copy(record)
            # An uncertain storage operation blocks further preparation in this run.
            _need(record['status'] not in ('planned', 'active', 'collecting', 'uncertain'), 'operation_uncertain')
            _need((record['identity']['participant_id'], record['identity']['repetition']) !=
                  (identity['participant_id'], identity['repetition']) or record['status'] == 'failed',
                  'measurement_slot_duplicate')
        _need(len(state['attempts']) < 1000, 'attempt_count_limit')
        record = dict(identity=identity, status='planned', manifest_sha256=None, artifacts=[])
        state['attempts'].append(record)
        self._append(plan, state)
        try:
            base = _base(identity, 'workspaces')
            self._mkdir(base)
            self._copy_assets(plan.competition()['assets'], self.root/'journals'/identity['run_id']/'inputs', base+'/inputs')
            self._mkdir(base+'/outputs')
            record['status'] = 'prepared'
            self._append(plan, state)
            return p._copy(record)
        except BaseException:
            self.poisoned = True
            raise

    def activate(self, plan, identity):
        _identity(identity, plan)
        raise d.DefinitionError('execution_disabled')

    def fail_workspace(self, plan, identity):
        """Record a known storage-only failure before collection; never an execution outcome."""
        self._writable()
        state, record = self._record(plan, identity)
        _need(record['status'] == 'prepared', 'workspace_not_prepared')
        record['status'] = 'failed'
        self._append(plan, state)
        return p._copy(record)

    def inspect(self, plan, *, expected_head=None):
        """Read-only reconstruction; never converts directory existence into success."""
        report = self.validate_journal(plan, expected_head=expected_head)
        unsafe = report['state']['phase'] != 'ready'
        for record in report['state']['attempts']:
            record['effective_status'] = ('uncertain' if record['status'] in ('planned', 'active', 'collecting')
                                          else record['status'])
            unsafe |= record['effective_status'] == 'uncertain'
        report.update(resumable=not unsafe, executable=False, head_pin_checked=expected_head is not None,
                      execution_status='not_started_by_s3')
        return report

    def prepare_artifact_archive(self, plan, identity, outputs):
        """Freeze an explicit complete output inventory in a durable collection intent."""
        self._writable();state, record = self._record(plan, identity)
        _need(record['status'] == 'prepared', 'workspace_not_prepared')
        _need(not any(r['status'] in ('planned', 'collecting', 'uncertain', 'active')
                      for r in state['attempts']), 'operation_uncertain')
        policy = plan.as_dict()['policy'];specs = _specs(outputs, policy)
        base = _base(identity, 'workspaces')+'/outputs'
        files, dirs = self._tree(base)
        _need(set(files) == {s['path'] for s in specs}, 'inventory_mismatch')
        allowed_dirs = {'/'.join(_path(s['path'])[:n]) for s in specs for n in range(1, len(_path(s['path'])))}
        _need(dirs == allowed_dirs, 'inventory_mismatch')
        _need(sum(sig[3] for sig in files.values()) <= min(policy['max_artifact_bytes'], MAX_TOTAL_BYTES),
              'artifact_total_limit')
        artifacts = []
        for s in specs:
            data = self._read(base+'/'+s['path'])
            artifacts.append(dict(artifact_id=str(uuid.uuid4()), path=_base(identity, 'artifacts')+'/files/'+s['path'],
                                  sha256=d.hashlib.sha256(data).hexdigest(), size_bytes=len(data),
                                  media_type=s['media_type'], classification='private'))
        _need(self._tree(base) == (files, dirs), 'inventory_changed')
        manifest = dict(kind='artifact_manifest', schema_version=1, identity=p._copy(identity), artifacts=artifacts)
        validate_manifest(manifest, plan, identity)
        existing = [a for rec in state['attempts'] for a in rec['artifacts']]
        p.validate_artifacts(existing+artifacts, max_files=min(policy['max_files'], 1000),
                             max_bytes=min(policy['max_artifact_bytes'], MAX_TOTAL_BYTES))
        record.update(status='collecting', artifacts=artifacts, manifest_sha256=d.content_sha256(manifest))
        self._append(plan, state)
        self._collections[identity['attempt_id']] = manifest
        return p._copy(manifest)

    def validate_inventory(self, plan, identity, manifest):
        manifest = validate_manifest(manifest, plan, identity)
        prefix = _base(identity, 'artifacts')+'/files/'
        expected = [dict(path=a['path'][len(prefix):], sha256=a['sha256'], size_bytes=a['size_bytes'])
                    for a in manifest['artifacts']]
        return self._inventory(_base(identity, 'workspaces')+'/outputs', expected)

    def archive_artifacts(self, plan, identity):
        """Only the live owner of this collection intent may copy; never crash-retry."""
        self._writable();state, record = self._record(plan, identity)
        _need(record['status'] == 'collecting' and identity['attempt_id'] in self._collections, 'operation_uncertain')
        manifest = self._collections.pop(identity['attempt_id'])
        try:
            files = self.validate_inventory(plan, identity, manifest)
            base = _base(identity, 'artifacts')
            self._mkdir(base);self._mkdir(base+'/files')
            for name, data in files:
                if '/' in name:
                    self._mkdir(base+'/files/'+name.rsplit('/', 1)[0], existing=True)
                self._publish(base+'/files/'+name, data)
            self.validate_inventory(plan, identity, manifest)
            self._json(base+'/manifest.json', manifest)
            self.validate_archive(plan, identity, expected_manifest=record['manifest_sha256'])
            record['status'] = 'archived'
            self._append(plan, state)
            return p._copy(manifest)
        except BaseException:
            self.poisoned = True
            raise

    def collect(self, plan, identity, outputs):
        state, record = self._record(plan, identity)
        if record['status'] == 'archived':
            manifest = self.validate_archive(plan, identity, expected_manifest=record['manifest_sha256'])
            specs = _specs(outputs, plan.as_dict()['policy'])
            prefix = _base(identity, 'artifacts')+'/files/'
            _need(specs == [dict(path=a['path'][len(prefix):], media_type=a['media_type'])
                            for a in manifest['artifacts']], 'collection_conflict')
            return manifest
        self.prepare_artifact_archive(plan, identity, outputs)
        return self.archive_artifacts(plan, identity)

    def validate_archive(self, plan, identity, *, expected_manifest):
        """Validate bytes, not just self-reported manifest metadata."""
        _identity(identity, plan)
        d._hash(expected_manifest)
        base = _base(identity, 'artifacts')
        _need(set(self._names(base)) == {'files', 'manifest.json'}, 'archive_incomplete')
        manifest = validate_manifest(self._json_read(base+'/manifest.json'), plan, identity,
                                     expected_sha256=expected_manifest)
        prefix = base+'/files/'
        expected = [dict(path=a['path'][len(prefix):], sha256=a['sha256'], size_bytes=a['size_bytes'])
                    for a in manifest['artifacts']]
        self._inventory(base+'/files', expected)
        return manifest


def _state(value, plan):
    d._object(value, ('phase', 'attempts'), '$.state')
    _need(value['phase'] in ('initializing', 'ready'), 'journal_phase_invalid')
    d._list(value['attempts'], '$.state.attempts')
    _need(len(value['attempts']) <= 1000, 'attempt_count_limit')
    ids = set();slots = {};artifacts = []
    for rec in value['attempts']:
        d._object(rec, ('identity', 'status', 'manifest_sha256', 'artifacts'), '$.attempt')
        i = _identity(rec['identity'], plan)
        _need(i['attempt_id'] not in ids, 'attempt_duplicate');ids.add(i['attempt_id'])
        slot = (i['participant_id'], i['repetition'])
        _need(slot not in slots or slots[slot] == 'failed', 'measurement_slot_duplicate')
        slots[slot] = rec['status']
        _need(rec['status'] in STATES, 'workspace_status_invalid')
        # S3 has no executor and cannot make active/process-quiescence declarations.
        _need(rec['status'] != 'active', 'execution_disabled')
        if rec['status'] in ('collecting', 'archived'):
            manifest = dict(kind='artifact_manifest', schema_version=1, identity=i, artifacts=rec['artifacts'])
            validate_manifest(manifest, plan, i, expected_sha256=rec['manifest_sha256'])
            _need(rec['manifest_sha256'] is not None, 'manifest_hash_missing')
        else:
            _need(rec['manifest_sha256'] is None and rec['artifacts'] == [], 'workspace_state_inconsistent')
        artifacts.extend(rec['artifacts'])
    policy = plan.as_dict()['policy']
    p.validate_artifacts(artifacts, max_files=min(policy['max_files'], 1000),
                         max_bytes=min(policy['max_artifact_bytes'], MAX_TOTAL_BYTES))
    _need(value['phase'] != 'initializing' or not value['attempts'], 'journal_phase_invalid')


def _transition(before, after):
    if before['phase'] == 'initializing':
        _need(after == dict(phase='ready', attempts=[]), 'workspace_transition_invalid')
        return
    _need(after['phase'] == 'ready', 'workspace_transition_invalid')
    old = before['attempts'];new = after['attempts']
    _need(len(new) in (len(old), len(old)+1), 'workspace_history_changed')
    changed = 0
    edges = {'planned': ('prepared', 'failed', 'uncertain'), 'prepared': ('collecting', 'failed', 'uncertain'),
             'collecting': ('archived',)}
    for a, b in zip(old, new):
        _need(a['identity'] == b['identity'], 'workspace_history_changed')
        if a == b:
            continue
        changed += 1
        _need(b['status'] in edges.get(a['status'], ()), 'workspace_transition_invalid')
        if a['status'] == 'collecting':
            _need(a['artifacts'] == b['artifacts'] and a['manifest_sha256'] == b['manifest_sha256'],
                  'workspace_history_changed')
    if len(new) > len(old):
        _need(changed == 0 and new[-1]['status'] == 'planned', 'workspace_transition_invalid')
    else:
        _need(changed == 1, 'workspace_transition_invalid')


class _Parser(argparse.ArgumentParser):
    def error(self, _message):
        raise d.DefinitionError('cli_arguments_invalid')


def main(argv=None):
    try:
        parser = _Parser(description=__doc__)
        sub = parser.add_subparsers(dest='command', required=True)
        sub.add_parser('isolation-check')
        for name in ('prepare', 'inspect', 'validate', 'collect'):
            cmd = sub.add_parser(name)
            for arg in ('root', 'plan', 'competition', 'rubric'):
                cmd.add_argument('--'+arg, required=True, type=Path)
            cmd.add_argument('--assets', type=Path)
            cmd.add_argument('--rubric-assets', type=Path)
            cmd.add_argument('--expected-plan-sha256', required=True)
            cmd.add_argument('--expected-head')
            if name in ('prepare', 'collect'):
                cmd.add_argument('--identity', type=Path, required=True)
            if name == 'collect':
                cmd.add_argument('--outputs', type=Path, required=True)
        args = parser.parse_args(argv)
        if args.command == 'isolation-check':
            response = isolation_check()
        else:
            plan = p.validate_run_plan(d.load_json(args.plan), d.load_json(args.competition), d.load_json(args.rubric),
                                       asset_root=args.assets, rubric_asset_root=args.rubric_assets,
                                       expected_sha256=args.expected_plan_sha256)
            with WorkspaceStore(args.root, create=args.command == 'prepare') as store:
                if args.command == 'prepare':
                    if args.expected_head:
                        store.validate_journal(plan, expected_head=args.expected_head)
                    store.register_run(plan, asset_root=args.assets, rubric_asset_root=args.rubric_assets)
                    response = store.prepare(plan, d.load_json(args.identity))
                elif args.command == 'collect':
                    if args.expected_head:
                        store.validate_journal(plan, expected_head=args.expected_head)
                    response = store.collect(plan, d.load_json(args.identity), d.load_json(args.outputs))
                else:
                    response = store.inspect(plan, expected_head=args.expected_head)
                    # No prompts, paths, model names, artifacts or raw errors on console.
                    response = {key: response[key] for key in ('sequence', 'head_sha256', 'head_pin_checked', 'resumable', 'executable')}
                if args.command in ('prepare', 'collect'):
                    response = dict(status=response.get('status', 'archived'),
                                    head_sha256=store.validate_journal(plan)['head_sha256'], executable=False)
        print(d.canonical_json_bytes(dict(ok=True, **response)).decode('utf-8'))
        return 0
    except KeyboardInterrupt:
        print(json.dumps(dict(ok=False, code='operation_interrupted', uncertain=True)), file=sys.stderr)
        return 130
    except d.DefinitionError as error:
        print(json.dumps(dict(ok=False, code=error.code, location=error.location)), file=sys.stderr)
        return 2
    except (OSError, ValueError, TypeError, KeyError):
        print(json.dumps(dict(ok=False, code='storage_access_failed', location='$')), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
