"""S3 synthetic storage tests. No participant/agent code is executed."""
import contextlib
import copy
import io
import json
import multiprocessing
import os
from pathlib import Path
import socket
import stat
import tempfile
import unittest
from unittest.mock import patch
import uuid

import definitions as d
import planning as p
import workspaces as w

ROOT = Path(__file__).resolve().parents[1]
S1 = ROOT/'tests/fixtures/definitions/valid'
S2 = ROOT/'tests/fixtures/planning'


def _competing_writer(root, send):
    try:
        with w.WorkspaceStore(root, create=False):
            send.send('unexpected_success')
    except d.DefinitionError as error:
        send.send(error.code)
    finally:
        send.close()


class WorkspaceCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=ROOT)
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.root = self.folder/'casting'
        self.c = d.load_json(S1/'competition.json')
        self.r = d.load_json(S1/'rubric.json')
        self.config = d.load_json(S2/'config.json')
        self.plan = p.create_run_plan(self.c, self.r, self.config, asset_root=S1/'assets')
        self.i = p.new_attempt_identity(self.plan, self.config['participants'][0]['participant_id'], 1)
        self.outputs = [dict(path='answer.txt', media_type='text/plain')]

    def store(self):
        store = w.WorkspaceStore(self.root).__enter__()
        self.addCleanup(store.__exit__, None, None, None)
        store.register_run(self.plan, asset_root=S1/'assets')
        return store

    def prepared(self):
        store = self.store()
        store.prepare(self.plan, self.i)
        return store

    def output(self, name='answer.txt', data=b'synthetic output'):
        path = self.root/w._base(self.i, 'workspaces')/'outputs'/name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def fails(self, code, fn, *args, **kwargs):
        with self.assertRaises(d.DefinitionError) as got:
            fn(*args, **kwargs)
        if code:
            self.assertEqual(got.exception.code, code)
        return got.exception

    def snapshot(self):
        return {str(f.relative_to(self.root)): f.read_bytes() for f in self.root.rglob('*') if f.is_file()}


class WorkspaceTests(WorkspaceCase):
    def test_prepare_persist_inspect_idempotent(self):
        store = self.prepared()
        before = self.snapshot()
        self.assertEqual(store.prepare(self.plan, self.i)['status'], 'prepared')
        report = store.inspect(self.plan)
        self.assertTrue(report['resumable'])
        self.assertFalse(report['executable'])
        self.assertEqual(report['state']['attempts'][0]['effective_status'], 'prepared')
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(store.register_run(self.plan, asset_root=S1/'assets')['phase'], 'ready')
        self.assertEqual(self.snapshot(), before)

    def test_independent_participants_repetitions_identical_inputs(self):
        config = copy.deepcopy(self.config)
        second = copy.deepcopy(config['participants'][0])
        second['participant_id'] = str(uuid.uuid4());second['model']['name'] = 'different-model'
        config['participants'].append(second);config['repetitions'] = 2
        self.plan = p.create_run_plan(self.c, self.r, config, asset_root=S1/'assets')
        store = self.store();inodes = [];manifests = []
        for n, (participant, repetition) in enumerate(p.measurement_slots(self.plan)):
            self.i = p.new_attempt_identity(self.plan, participant, repetition)
            store.prepare(self.plan, self.i)
            inp = self.root/w._base(self.i, 'workspaces')/'inputs/input.txt'
            self.assertEqual(inp.read_bytes(), (S1/'assets/input.txt').read_bytes())
            inodes.append(inp.stat().st_ino)
            self.output(data=str(n).encode())
            manifests.append(store.collect(self.plan, self.i, self.outputs))
        self.assertEqual(len(set(inodes)), 4)
        self.assertEqual(len({m['artifacts'][0]['sha256'] for m in manifests}), 4)
        self.assertEqual(len(store.inspect(self.plan)['state']['attempts']), 4)

    def test_multiple_competitions_and_new_runs(self):
        store = self.prepared()
        old = self.snapshot()
        c = copy.deepcopy(self.c);c['competition_id'] = str(uuid.uuid4())
        config = copy.deepcopy(self.config);config['run_id'] = str(uuid.uuid4())
        plan = p.create_run_plan(c, self.r, config, asset_root=S1/'assets')
        store.register_run(plan, asset_root=S1/'assets')
        i = p.new_attempt_identity(plan, config['participants'][0]['participant_id'], 1)
        store.prepare(plan, i)
        self.assertEqual({k:self.snapshot()[k] for k in old}, old)

    def test_inputs_are_copies_nonexecutable_and_private(self):
        self.prepared()
        src = S1/'assets/input.txt';dst = self.root/w._base(self.i, 'workspaces')/'inputs/input.txt'
        self.assertNotEqual(src.stat().st_ino, dst.stat().st_ino)
        self.assertEqual(dst.stat().st_nlink, 1)
        self.assertEqual(stat.S_IMODE(dst.stat().st_mode), 0o400)
        self.assertEqual(stat.S_IMODE(self.root.stat().st_mode), 0o700)
        self.assertEqual(os.stat(self.root/'writer.lock').st_nlink, 1)

    def test_mutated_input_detected(self):
        store = self.prepared()
        path = self.root/w._base(self.i, 'workspaces')/'inputs/input.txt'
        path.chmod(0o600);path.write_bytes(b'X'*path.stat().st_size)
        self.fails('asset_hash_mismatch', store.inspect, self.plan)

    def test_shared_snapshot_mutation_detected(self):
        store = self.prepared()
        path = self.root/'journals'/self.i['run_id']/'inputs/input.txt'
        path.chmod(0o600);path.write_bytes(b'X'*path.stat().st_size)
        self.fails('asset_hash_mismatch', store.inspect, self.plan)

    def test_fresh_source_revalidation(self):
        self.c['assets'][0]['sha256'] = 'a'*64
        self.fails(None, p.create_run_plan, self.c, self.r, self.config, asset_root=S1/'assets')

    def test_invalid_identity_fields(self):
        store = self.store()
        for key, bad in [('run_id','../bad'), ('participant_id','/absolute'), ('attempt_id','x'*300),
                         ('plan_sha256','f'*64), ('repetition',True), ('repetition',9)]:
            identity = dict(self.i);identity[key] = bad
            self.fails(None, store.prepare, self.plan, identity)
        self.assertEqual(store.inspect(self.plan)['state']['attempts'], [])

    def test_unknown_participant_and_attempt_identity_conflict(self):
        store = self.prepared()
        identity = dict(self.i);identity['participant_id'] = str(uuid.uuid4())
        self.fails('measurement_slot_invalid', store.prepare, self.plan, identity)
        identity = dict(self.i);identity['attempt_id'] = str(uuid.uuid4())
        self.fails('measurement_slot_duplicate', store.prepare, self.plan, identity)

    def test_explicit_storage_failure_not_execution_failure(self):
        store = self.prepared()
        self.assertEqual(store.fail_workspace(self.plan, self.i)['status'], 'failed')
        self.fails('operation_uncertain', store.prepare, self.plan, self.i)
        self.fails('workspace_not_prepared', store.collect, self.plan, self.i, self.outputs)
        bundle = d.load_json(self.root/'journals'/self.i['run_id']/'bundle.json')
        self.assertEqual(bundle['initial_result']['executions'], [])

    def test_unknown_workspace_files(self):
        store = self.prepared()
        (self.root/w._base(self.i, 'workspaces')/'unknown').write_bytes(b'bad')
        self.fails('workspace_layout_invalid', store.inspect, self.plan)

    def test_unknown_attempt_directory(self):
        store = self.prepared()
        (self.root/'workspaces'/self.i['run_id']/self.i['participant_id']/str(uuid.uuid4())).mkdir()
        self.fails('unknown_attempt_path', store.inspect, self.plan)

    def test_read_only_inspect_missing_root_does_not_create(self):
        with self.assertRaises(OSError):
            with w.WorkspaceStore(self.root, create=False):
                pass
        self.assertFalse(self.root.exists())

    def test_protected_root_names_and_outside_project(self):
        for path in [ROOT, ROOT/'results/new', ROOT/'reports/new', ROOT/'tests/new', ROOT/'.git/new',
                     ROOT/'../outside', Path('/casting-root')]:
            self.fails('store_path_invalid', w.WorkspaceStore, path)

    def test_no_adoption_of_existing_directory_or_unsafe_permissions(self):
        self.root.mkdir(mode=0o700)
        with self.assertRaises(OSError):
            with w.WorkspaceStore(self.root):
                pass
        self.root.chmod(0o770)
        self.fails('store_permissions_unsafe', w.WorkspaceStore(self.root).__enter__)

    def test_root_symlink_and_parent_symlink(self):
        target = self.folder/'real';target.mkdir()
        self.root.symlink_to(target, target_is_directory=True)
        with self.assertRaises(OSError):
            with w.WorkspaceStore(self.root):
                pass
        with self.assertRaises(OSError):
            with w.WorkspaceStore(self.root/'nested'):
                pass
        self.assertEqual(list(target.iterdir()), [])


class ArchiveTests(WorkspaceCase):
    def test_collect_manifest_byte_validation_and_idempotence(self):
        store = self.prepared();out = self.output()
        manifest = store.collect(self.plan, self.i, self.outputs)
        self.assertEqual(manifest['artifacts'][0]['classification'], 'private')
        archive = self.root/manifest['artifacts'][0]['path']
        self.assertEqual(archive.read_bytes(), out.read_bytes())
        self.assertNotEqual(archive.stat().st_ino, out.stat().st_ino)
        self.assertEqual(archive.stat().st_nlink, 1)
        self.assertEqual(stat.S_IMODE(archive.stat().st_mode), 0o400)
        before = self.snapshot()
        self.assertEqual(store.collect(self.plan, self.i, self.outputs), manifest)
        self.assertEqual(before, self.snapshot())
        self.fails('collection_conflict', store.collect, self.plan, self.i, [])
        self.assertEqual(store.inspect(self.plan)['state']['attempts'][0]['effective_status'], 'archived')

    def test_empty_artifacts_require_explicit_complete_inventory(self):
        store = self.prepared()
        manifest = store.collect(self.plan, self.i, [])
        self.assertEqual(manifest['artifacts'], [])
        self.assertTrue((self.root/w._base(self.i, 'artifacts')/'manifest.json').is_file())
        self.assertEqual(store.inspect(self.plan)['state']['attempts'][0]['status'], 'archived')

    def test_missing_output_is_not_empty_success(self):
        store = self.prepared()
        self.fails('inventory_mismatch', store.collect, self.plan, self.i, self.outputs)
        self.assertEqual(store.inspect(self.plan)['state']['attempts'][0]['status'], 'prepared')

    def test_unknown_output_and_directory(self):
        store = self.prepared();self.output('unknown.bin')
        self.fails('inventory_mismatch', store.collect, self.plan, self.i, [])
        self.output('answer.txt');self.output('unknown.bin').unlink()
        (self.root/w._base(self.i, 'workspaces')/'outputs/empty').mkdir()
        self.fails('inventory_mismatch', store.collect, self.plan, self.i, self.outputs)

    def test_path_traversal_absolute_windows_glob_and_name_limits(self):
        store = self.prepared()
        for name in ('../out', '/out', 'a/../../out', 'a//b', './out', 'C:\\out', '*.txt', 'x'*129):
            self.fails(None, store.collect, self.plan, self.i, [dict(path=name,media_type='text/plain')])

    def test_duplicate_and_prefix_paths_unknown_fields_types(self):
        store = self.prepared()
        for specs in (self.outputs*2, self.outputs+[dict(path='answer.txt/child',media_type='text/plain')],
                      [dict(path='answer.txt',media_type='image/unknown')],
                      [dict(path='answer.txt',media_type='text/plain',classification='shareable')]):
            self.fails(None, store.collect, self.plan, self.i, specs)

    def test_nested_output_inventory(self):
        store = self.prepared();self.output('sub/result.json', b'{"synthetic":true}')
        specs = [dict(path='sub/result.json',media_type='application/json')]
        manifest = store.collect(self.plan, self.i, specs)
        self.assertTrue((self.root/manifest['artifacts'][0]['path']).is_file())

    def test_symlink_file_and_directory(self):
        store = self.prepared()
        path = self.root/w._base(self.i, 'workspaces')/'outputs/answer.txt'
        path.symlink_to(S1/'assets/input.txt')
        self.fails('file_unsafe', store.collect, self.plan, self.i, self.outputs)
        path.unlink();path.symlink_to(S1/'assets', target_is_directory=True)
        self.fails('file_unsafe', store.collect, self.plan, self.i, self.outputs)

    def test_hardlink_rejected(self):
        store = self.prepared();path = self.output()
        os.link(path, self.folder/'alias')
        self.fails('file_unsafe', store.collect, self.plan, self.i, self.outputs)

    def test_fifo_socket_and_device_types(self):
        store = self.prepared()
        path = self.root/w._base(self.i, 'workspaces')/'outputs/answer.txt'
        os.mkfifo(path)
        self.fails('file_unsafe', store.collect, self.plan, self.i, self.outputs)
        path.unlink()
        folder_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            with socket.socket(socket.AF_UNIX) as local_socket:
                local_socket.bind('/proc/self/fd/'+str(folder_fd)+'/answer.txt')
                self.fails('file_unsafe', store.collect, self.plan, self.i, self.outputs)
        finally:
            os.close(folder_fd)
        path.unlink();self.output()
        actual = os.DirEntry.stat
        def device(entry, **kwargs):
            st = actual(entry, **kwargs)
            if entry.name == 'answer.txt':
                values = list(st);values[0] = stat.S_IFCHR | 0o600
                return os.stat_result(values)
            return st
        with patch.object(os.DirEntry, 'stat', device):
            self.fails('file_unsafe', store.collect, self.plan, self.i, self.outputs)

    def test_count_and_byte_limits(self):
        config = copy.deepcopy(self.config);config['policy']['max_files'] = 1
        config['policy']['max_artifact_bytes'] = 3
        self.plan = p.create_run_plan(self.c,self.r,config,asset_root=S1/'assets')
        self.i = p.new_attempt_identity(self.plan,self.config['participants'][0]['participant_id'],1)
        store = self.prepared();self.output(data=b'1234')
        self.fails('artifact_total_limit', store.collect,self.plan,self.i,self.outputs)
        self.fails('artifact_count_limit', store.collect,self.plan,self.i,self.outputs*2)

    def test_single_file_limit_and_directory_entry_limit(self):
        store = self.prepared();self.output(data=b'1234')
        with patch.object(w, 'MAX_FILE_BYTES', 3):
            self.fails('file_size_limit',store._tree,w._base(self.i,'workspaces')+'/outputs')
        with patch.object(w, 'MAX_ENTRIES', 1):
            self.output('other')
            self.fails('directory_entry_limit',store._tree,w._base(self.i,'workspaces')+'/outputs')

    def test_manifest_identity_hash_and_private_metadata(self):
        store = self.prepared();self.output()
        manifest = store.collect(self.plan,self.i,self.outputs)
        for field, value in [('classification','shareable'), ('path','../bad'), ('size_bytes',True)]:
            bad = copy.deepcopy(manifest);bad['artifacts'][0][field] = value
            self.fails(None,w.validate_manifest,bad,self.plan,self.i)
        self.fails('content_hash_mismatch',w.validate_manifest,manifest,self.plan,self.i,expected_sha256='f'*64)
        bad = copy.deepcopy(manifest);bad['identity']['attempt_id'] = str(uuid.uuid4())
        self.fails('manifest_identity_mismatch',w.validate_manifest,bad,self.plan,self.i)

    def test_archive_mutation_missing_files_and_manifest(self):
        store = self.prepared();self.output()
        manifest = store.collect(self.plan,self.i,self.outputs)
        path = self.root/manifest['artifacts'][0]['path']
        path.chmod(0o600);path.write_bytes(b'X'*path.stat().st_size)
        self.fails('asset_hash_mismatch',store.inspect,self.plan)
        path.unlink()
        self.fails('inventory_mismatch',store.inspect,self.plan)

    def test_missing_manifest_cannot_be_success(self):
        store = self.prepared();self.output();store.collect(self.plan,self.i,self.outputs)
        (self.root/w._base(self.i,'artifacts')/'manifest.json').unlink()
        self.fails('archive_incomplete',store.inspect,self.plan)

    def test_output_replacement_during_read(self):
        store = self.prepared();path = self.output();actual = d.os.read;changed = False
        def swapped(fd, size):
            nonlocal changed
            result = actual(fd,size)
            if not changed and result == b'synthetic output':
                changed = True
                path.rename(path.with_suffix('.old'))
                path.write_bytes(b'synthetic output')
            return result
        with patch.object(d.os,'read',swapped):
            self.fails('file_changed',store.collect,self.plan,self.i,self.outputs)

    def test_output_change_between_inventory_reads(self):
        store = self.prepared();path = self.output();actual = store._read
        def changed(relative,*args):
            data = actual(relative,*args)
            if relative.endswith('/outputs/answer.txt'):
                path.write_bytes(b'X'*len(data))
            return data
        with patch.object(store,'_read',changed):
            self.fails('inventory_changed',store.prepare_artifact_archive,self.plan,self.i,self.outputs)

    def test_output_change_after_intent(self):
        store = self.prepared();path = self.output()
        store.prepare_artifact_archive(self.plan,self.i,self.outputs)
        path.write_bytes(b'X'*path.stat().st_size)
        self.fails('asset_hash_mismatch',store.archive_artifacts,self.plan,self.i)

    def test_html_is_opaque_private_data(self):
        store = self.prepared();self.output('evil.html',b'<script>throw "not executed"</script>')
        manifest = store.collect(self.plan,self.i,[dict(path='evil.html',media_type='text/html')])
        self.assertEqual(manifest['artifacts'][0]['classification'],'private')
        self.assertFalse(store.inspect(self.plan)['executable'])


class PersistenceTests(WorkspaceCase):
    def test_close_reopen_and_head_pin(self):
        store = self.prepared();self.output();store.collect(self.plan,self.i,self.outputs)
        head = store.inspect(self.plan)['head_sha256'];before = self.snapshot()
        store.__exit__()
        with w.WorkspaceStore(self.root,create=False) as reopened:
            self.assertEqual(reopened.inspect(self.plan,expected_head=head)['head_sha256'],head)
            self.assertEqual(before,self.snapshot())
            self.fails('journal_head_mismatch',reopened.inspect,self.plan,expected_head='f'*64)

    def test_journal_hash_corruption(self):
        store = self.prepared()
        path = self.root/'journals'/self.i['run_id']/'00000004.json'
        obj = d.load_json(path);obj['event']['state']['attempts'][0]['status'] = 'archived'
        path.chmod(0o600);path.write_bytes(d.canonical_json_bytes(obj))
        self.fails('content_hash_mismatch',store.inspect,self.plan)

    def test_chain_corruption_rehashed_and_invalid_schema(self):
        store = self.prepared()
        path = self.root/'journals'/self.i['run_id']/'00000004.json'
        obj = d.load_json(path);obj['event']['previous_sha256'] = 'a'*64
        obj['sha256'] = d.content_sha256(obj['event'])
        path.chmod(0o600);path.write_bytes(d.canonical_json_bytes(obj))
        self.fails('journal_binding_mismatch',store.inspect,self.plan)

    def test_deleted_middle_event_and_truncated_tail(self):
        store = self.prepared();head = store.inspect(self.plan)['head_sha256']
        folder = self.root/'journals'/self.i['run_id']
        tail = folder/'00000004.json';tail.unlink()
        self.fails('journal_head_mismatch',store.inspect,self.plan,expected_head=head)
        (folder/'00000002.json').unlink()
        self.fails('journal_sequence_invalid',store.inspect,self.plan)

    def test_plan_change_rejected_without_rewriting(self):
        store = self.prepared();before = self.snapshot()
        config = copy.deepcopy(self.config);config['participants'][0]['parameters']['threads'] = 8
        different = p.create_run_plan(self.c,self.r,config,asset_root=S1/'assets')
        self.fails('bundle_plan_mismatch',store.inspect,different)
        self.assertEqual(before,self.snapshot())

    def test_different_prompt_same_run_rejected(self):
        store = self.prepared()
        c = copy.deepcopy(self.c);c['prompt']['text'] = 'different common prompt'
        c['prompt']['sha256'] = d.hashlib.sha256(c['prompt']['text'].encode()).hexdigest()
        c['prompt']['version'] += 1;c['definition_revision'] += 1
        plan = p.create_run_plan(c,self.r,self.config,asset_root=S1/'assets')
        self.fails('bundle_plan_mismatch',store.inspect,plan)

    def test_second_writer_in_same_process(self):
        store = self.prepared()
        self.fails('writer_busy',w.WorkspaceStore(self.root,create=False).__enter__)
        self.assertTrue(store.inspect(self.plan)['resumable'])

    def test_second_writer_separate_process(self):
        self.prepared()
        # fork executes only this test harness, never participant code or an agent.
        ctx = multiprocessing.get_context('fork');recv,send = ctx.Pipe(duplex=False)
        child = ctx.Process(target=_competing_writer,args=(self.root,send));child.start();send.close()
        self.assertTrue(recv.poll(5))
        self.assertEqual(recv.recv(),'writer_busy');recv.close()
        child.join(5)
        self.assertEqual(child.exitcode,0)

    def test_replaced_lock_blocks_access(self):
        store = self.prepared()
        lock = self.root/'writer.lock';lock.rename(self.root/'old-lock');lock.write_bytes(b'')
        self.fails('lock_changed',store.inspect,self.plan)

    def test_root_replacement_detected(self):
        store = self.prepared();old = self.folder/'moved';self.root.rename(old)
        self.root.mkdir(mode=0o700)
        self.fails('store_root_changed',store.inspect,self.plan)
        self.assertEqual(list(self.root.iterdir()),[])

    def test_failed_workspace_prepare_is_uncertain_after_restart(self):
        store = self.store();actual = store._copy_assets
        def interrupted(*args,**kwargs):
            raise KeyboardInterrupt
        with patch.object(store,'_copy_assets',interrupted):
            with self.assertRaises(KeyboardInterrupt):
                store.prepare(self.plan,self.i)
        self.fails('store_write_uncertain',store.prepare,self.plan,self.i)
        store.__exit__()
        with w.WorkspaceStore(self.root,create=False) as reopened:
            report = reopened.inspect(self.plan)
            self.assertFalse(report['resumable'])
            self.assertEqual(report['state']['attempts'][0]['effective_status'],'uncertain')
            self.fails('operation_uncertain',reopened.prepare,self.plan,self.i)

    def test_collection_intent_not_replayed_after_restart(self):
        store = self.prepared();self.output();store.prepare_artifact_archive(self.plan,self.i,self.outputs)
        store.__exit__()
        with w.WorkspaceStore(self.root,create=False) as reopened:
            before = self.snapshot()
            self.assertFalse(reopened.inspect(self.plan)['resumable'])
            self.fails('operation_uncertain',reopened.archive_artifacts,self.plan,self.i)
            self.fails('workspace_not_prepared',reopened.collect,self.plan,self.i,self.outputs)
            self.assertEqual(before,self.snapshot())

    def test_crash_boundaries_of_atomic_publication(self):
        for boundary in ('file_synced','before_publication','published_before_fsync','publication_synced'):
            with self.subTest(boundary=boundary):
                root = self.folder/boundary
                with w.WorkspaceStore(root) as store:
                    store.register_run(self.plan,asset_root=S1/'assets')
                    def crash(name):
                        if name == boundary:
                            raise KeyboardInterrupt
                    with patch.object(w,'_checkpoint',crash):
                        with self.assertRaises(KeyboardInterrupt):
                            store.prepare(self.plan,self.i)
                    self.fails('store_write_uncertain',store.prepare,self.plan,self.i)
                with w.WorkspaceStore(root,create=False) as reopened:
                    if boundary in ('file_synced','before_publication'):
                        self.fails('journal_uncommitted_files',reopened.inspect,self.plan)
                    else:
                        report = reopened.inspect(self.plan)
                        self.assertFalse(report['resumable'])
                        self.assertEqual(report['state']['attempts'][0]['status'],'planned')
                        self.fails('operation_uncertain',reopened.prepare,self.plan,self.i)

    def test_archive_publication_before_journal_commit_remains_uncertain(self):
        store = self.prepared();self.output();store.prepare_artifact_archive(self.plan,self.i,self.outputs)
        actual = store._append
        with patch.object(store,'_append',side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                store.archive_artifacts(self.plan,self.i)
        self.assertTrue((self.root/w._base(self.i,'artifacts')/'manifest.json').is_file())
        store.__exit__()
        with w.WorkspaceStore(self.root,create=False) as reopened:
            report = reopened.inspect(self.plan)
            self.assertFalse(report['resumable'])
            self.assertEqual(report['state']['attempts'][0]['effective_status'],'uncertain')
            self.fails('operation_uncertain',reopened.archive_artifacts,self.plan,self.i)

    def test_no_replace_publication_preserves_existing_data(self):
        store = self.prepared();path = 'journals/'+self.i['run_id']+'/bundle.json'
        before = (self.root/path).read_bytes()
        self.fails('output_exists',store._publish,path,b'changed')
        self.assertEqual((self.root/path).read_bytes(),before)
        self.fails('store_write_uncertain',store._publish,path,b'retry')

    def test_fsync_error_after_publication(self):
        store = self.prepared();target = 'journals/'+self.i['run_id']+'/extra.json'
        actual = w.os.fsync;after_publication = False
        def checkpoint(name):
            nonlocal after_publication
            if name == 'published_before_fsync':after_publication = True
        def sync(fd):
            if after_publication:raise OSError('synthetic sync error')
            return actual(fd)
        with patch.object(w,'_checkpoint',checkpoint),patch.object(w.os,'fsync',sync):
            self.fails('storage_commit_uncertain',store._publish,target,b'{}')
        self.assertEqual((self.root/target).read_bytes(),b'{}')
        self.fails('store_write_uncertain',store._publish,target,b'{}')

    def test_temp_file_replacement_is_not_deleted_or_published(self):
        store = self.prepared();target = 'journals/'+self.i['run_id']+'/extra.json'
        def replace(name):
            if name == 'file_synced':
                folder = self.root/'journals'/self.i['run_id']
                tmp = next(folder.glob('.s3-*.tmp'))
                tmp.rename(tmp.with_suffix('.original'));tmp.write_bytes(b'foreign')
        with patch.object(w,'_checkpoint',replace):
            self.fails('file_changed',store._publish,target,b'{}')
        self.assertFalse((self.root/target).exists())
        self.assertTrue(any(p.read_bytes() == b'foreign' for p in (self.root/'journals'/self.i['run_id']).glob('.s3-*.tmp')))

    def test_filesystem_boundary_rejected(self):
        store = self.prepared();self.output();actual = os.DirEntry.stat
        def foreign(entry,**kwargs):
            result = actual(entry,**kwargs)
            if entry.name == 'answer.txt':
                vals = list(result);vals[2] += 1
                return os.stat_result(vals)
            return result
        with patch.object(os.DirEntry,'stat',foreign):
            self.fails('filesystem_boundary',store.collect,self.plan,self.i,self.outputs)

    def test_journal_bounded_and_unknown_files_not_ignored(self):
        store = self.prepared()
        folder = self.root/'journals'/self.i['run_id']
        (folder/'unexpected.json').write_text('{}')
        self.fails('journal_uncommitted_files',store.inspect,self.plan)

    def test_writer_publication_requires_os_capability(self):
        store = self.prepared()
        with patch.object(p.ctypes,'CDLL',return_value=object()):
            self.fails('output_publish_unavailable',store._publish,
                       'journals/'+self.i['run_id']+'/extra.json',b'{}')
        self.fails('store_write_uncertain',store.prepare,self.plan,self.i)


class IsolationAndCliTests(WorkspaceCase):
    def test_isolation_explicitly_blocks_unknown_children_and_limits(self):
        report = w.isolation_check(self.plan)
        self.assertFalse(report['executable'])
        self.assertFalse(report['os_isolation_verified'])
        self.assertEqual(report['process_quiescence'],'unknown')
        self.assertEqual(report['unknown_children'],'block_execution')
        for key in ('cpu','ram','disk','environment','cancellation','host','read','write','network','subprocess'):
            self.assertIn(key,report['required'])

    def test_missing_os_capabilities_never_enables_execution(self):
        with patch.object(p.ctypes,'CDLL',return_value=object()):
            report = w.isolation_check()
        self.assertFalse(report['capabilities']['no_replace_publish'])
        self.assertFalse(report['executable'])

    def test_no_active_workspace_permission(self):
        store = self.prepared()
        self.fails('execution_disabled',store.activate,self.plan,self.i)
        self.assertEqual(store.inspect(self.plan)['state']['attempts'][0]['status'],'prepared')

    def test_cli_local_no_network_no_process_and_safe_outputs(self):
        identity = self.folder/'identity.json';identity.write_bytes(d.canonical_json_bytes(self.i))
        outputs = self.folder/'outputs.json';outputs.write_bytes(d.canonical_json_bytes(self.outputs))
        common = ['--root',str(self.root),'--plan',str(S2/'run-plan.json'),
                  '--competition',str(S1/'competition.json'),'--rubric',str(S1/'rubric.json'),
                  '--assets',str(S1/'assets'),'--expected-plan-sha256',self.plan.sha256]
        with patch('socket.socket',side_effect=AssertionError('network')), \
             patch('socket.create_connection',side_effect=AssertionError('network')), \
             patch('urllib.request.urlopen',side_effect=AssertionError('network')), \
             patch('subprocess.Popen',side_effect=AssertionError('subprocess')):
            for args in (['isolation-check'], ['prepare',*common,'--identity',str(identity)],
                         ['inspect',*common], ['validate',*common]):
                out = io.StringIO()
                with contextlib.redirect_stdout(out):self.assertEqual(w.main(args),0)
                obj = json.loads(out.getvalue());self.assertTrue(obj['ok']);self.assertFalse(obj['executable'])
                self.assertNotIn(str(self.root),out.getvalue())
                self.assertNotIn(self.c['prompt']['text'],out.getvalue())
            self.output()
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(w.main(['collect',*common,'--identity',str(identity),'--outputs',str(outputs)]),0)

    def test_cli_errors_are_json_and_private(self):
        for args in ([], ['unknown'], ['prepare'], ['inspect','--root','/private/path']):
            err = io.StringIO()
            with contextlib.redirect_stderr(err):self.assertEqual(w.main(args),2)
            data = json.loads(err.getvalue())
            self.assertFalse(data['ok']);self.assertNotIn('/private',err.getvalue())

    def test_all_existing_sources_archives_and_fixtures_unchanged(self):
        # Runtime regression also checks each pinned Golden JSON/hash vector.
        vectors = d.load_json(S2/'vectors.json')
        for name,expected in vectors.items():
            self.assertEqual(d.content_sha256(d.load_json(S2/name)),expected)
        before = {str(f):f.read_bytes() for root in ('results','reports','scenarios')
                  for f in (ROOT/root).rglob('*') if f.is_file() and not f.is_symlink()}
        store = self.prepared();self.output();store.collect(self.plan,self.i,self.outputs);store.inspect(self.plan)
        self.assertEqual(before,{name:Path(name).read_bytes() for name in before})


class AdditionalSafetyTests(WorkspaceCase):
    def test_explicit_new_workspace_attempt_after_known_storage_failure(self):
        store = self.prepared();old = copy.deepcopy(self.i)
        store.fail_workspace(self.plan,self.i)
        self.i = p.new_attempt_identity(self.plan,old['participant_id'],old['repetition'])
        self.assertNotEqual(old['attempt_id'],self.i['attempt_id'])
        store.prepare(self.plan,self.i);self.output();store.collect(self.plan,self.i,self.outputs)
        records = store.inspect(self.plan)['state']['attempts']
        self.assertEqual([r['status'] for r in records],['failed','archived'])
        self.assertTrue((self.root/w._base(old,'workspaces')).is_dir())
        self.assertEqual(store.prepare(self.plan,self.i)['status'],'archived')
        # These are storage attempts: neither becomes an execution/success counter.
        bundle = d.load_json(self.root/'journals'/self.i['run_id']/'bundle.json')
        self.assertEqual(bundle['initial_result']['progress']['successful_slots'],0)

    def test_unknown_rename_outcome_retains_published_file_and_blocks_retry(self):
        store = self.prepared();target = 'journals/'+self.i['run_id']+'/extra.json'
        publish = p._publish_no_replace
        def lost_ack(parent,source,destination):
            publish(parent,source,destination)
            raise OSError('synthetic lost acknowledgement')
        with patch.object(p,'_publish_no_replace',lost_ack):
            self.fails('storage_commit_uncertain',store._publish,target,b'{}')
        self.assertEqual((self.root/target).read_bytes(),b'{}')
        self.fails('store_write_uncertain',store._publish,target,b'{}')

    def test_partial_archive_symlinks_and_unknown_files_are_not_ignored(self):
        store = self.prepared();self.output();store.prepare_artifact_archive(self.plan,self.i,self.outputs)
        base = self.root/w._base(self.i,'artifacts');base.mkdir(parents=True)
        (base/'files').symlink_to(S1/'assets',target_is_directory=True)
        self.fails('file_unsafe',store.inspect,self.plan)
        (base/'files').unlink();(base/'unexpected').write_bytes(b'unknown')
        self.fails('archive_uncommitted_files',store.inspect,self.plan)

    def test_cli_interruption_has_safe_json_and_exit_130(self):
        identity = self.folder/'identity.json';identity.write_bytes(d.canonical_json_bytes(self.i))
        args = ['prepare','--root',str(self.root),'--plan',str(S2/'run-plan.json'),
                '--competition',str(S1/'competition.json'),'--rubric',str(S1/'rubric.json'),
                '--assets',str(S1/'assets'),'--expected-plan-sha256',self.plan.sha256,
                '--identity',str(identity)]
        err = io.StringIO()
        with patch.object(w.WorkspaceStore,'prepare',side_effect=KeyboardInterrupt), contextlib.redirect_stderr(err):
            self.assertEqual(w.main(args),130)
        self.assertEqual(json.loads(err.getvalue()),dict(ok=False,code='operation_interrupted',uncertain=True))

    def test_private_rubric_assets_are_not_participant_inputs(self):
        test_root = self.folder/'test-assets';test_root.mkdir()
        data = b'private synthetic test data, never executed\n'
        (test_root/'hidden.py').write_bytes(data)
        rubric = copy.deepcopy(self.r)
        rubric['test_suites'][0]['assets'] = [dict(path='hidden.py',size_bytes=len(data),
            sha256=d.hashlib.sha256(data).hexdigest(),role='test')]
        c = copy.deepcopy(self.c);c['rubric']['sha256'] = d.content_sha256(rubric)
        self.plan = p.create_run_plan(c,rubric,self.config,asset_root=S1/'assets',rubric_asset_root=test_root)
        self.i = p.new_attempt_identity(self.plan,self.i['participant_id'],1)
        with w.WorkspaceStore(self.root) as store:
            store.register_run(self.plan,asset_root=S1/'assets',rubric_asset_root=test_root)
            store.prepare(self.plan,self.i)
            private = self.root/'journals'/self.i['run_id']/'rubric-assets/hidden.py'
            self.assertEqual(private.read_bytes(),data)
            self.assertEqual(stat.S_IMODE(private.stat().st_mode),0o400)
            self.assertFalse((self.root/w._base(self.i,'workspaces')/'inputs/hidden.py').exists())
            self.assertTrue(store.inspect(self.plan)['resumable'])

    def test_bundle_tampering_and_s2_initial_result_validation(self):
        store = self.prepared()
        path = self.root/'journals'/self.i['run_id']/'bundle.json'
        obj = d.load_json(path);obj['competition']['prompt']['text'] = 'tampered'
        path.chmod(0o600);path.write_bytes(d.canonical_json_bytes(obj))
        self.fails('bundle_plan_mismatch',store.inspect,self.plan)

    def test_manifest_tampering_even_with_self_consistent_hash(self):
        store = self.prepared();self.output();store.collect(self.plan,self.i,self.outputs)
        path = self.root/w._base(self.i,'artifacts')/'manifest.json'
        obj = d.load_json(path);obj['artifacts'][0]['artifact_id'] = str(uuid.uuid4())
        path.chmod(0o600);path.write_bytes(d.canonical_json_bytes(obj))
        self.fails('content_hash_mismatch',store.inspect,self.plan)

    def test_journal_symlink_and_hardlink(self):
        store = self.prepared();path = self.root/'journals'/self.i['run_id']/'00000004.json'
        original = self.folder/'saved.json';path.rename(original);path.symlink_to(original)
        with self.assertRaises(OSError):store.inspect(self.plan)
        path.unlink();os.link(original,path)
        self.fails('file_unsafe',store.inspect,self.plan)

    def test_directory_exchange_after_read(self):
        store = self.prepared();self.output();folder = self.root/w._base(self.i,'workspaces')/'outputs'
        actual = d._read_fd;swapped = False
        def exchange(fd,name,*args,**kwargs):
            nonlocal swapped
            result = actual(fd,name,*args,**kwargs)
            if name == 'answer.txt' and not swapped:
                swapped = True
                folder.rename(folder.with_name('outputs-old'))
                folder.mkdir();(folder/'answer.txt').write_bytes(result[0])
            return result
        with patch.object(d,'_read_fd',exchange):
            self.fails('file_changed',store._read,w._base(self.i,'workspaces')+'/outputs/answer.txt')

    def test_identical_temp_replacement_after_check_detected(self):
        store = self.prepared();target = 'journals/'+self.i['run_id']+'/extra.json'
        def exchange(name):
            if name == 'before_publication':
                folder = self.root/'journals'/self.i['run_id']
                temp = next(folder.glob('.s3-*.tmp'));data = temp.read_bytes()
                temp.rename(temp.with_suffix('.original'));temp.write_bytes(data)
        with patch.object(w,'_checkpoint',exchange):
            self.fails('file_changed',store._publish,target,b'{}')
        self.assertEqual((self.root/target).read_bytes(),b'{}')

    def test_no_automatic_recovery_of_partial_run_registration(self):
        store = w.WorkspaceStore(self.root).__enter__();self.addCleanup(store.__exit__)
        with patch.object(store,'_copy_assets',side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):store.register_run(self.plan,asset_root=S1/'assets')
        store.__exit__()
        with w.WorkspaceStore(self.root,create=False) as reopened:
            self.assertFalse(reopened.inspect(self.plan)['resumable'])
            self.fails('operation_uncertain',reopened.register_run,self.plan,asset_root=S1/'assets')

    def test_artifact_global_limits_cover_all_attempts(self):
        config = copy.deepcopy(self.config);config['repetitions'] = 2
        config['policy']['max_artifact_bytes'] = 5
        self.plan = p.create_run_plan(self.c,self.r,config,asset_root=S1/'assets')
        self.i = p.new_attempt_identity(self.plan,self.i['participant_id'],1)
        store = self.prepared();self.output(data=b'123')
        store.collect(self.plan,self.i,self.outputs)
        self.i = p.new_attempt_identity(self.plan,self.i['participant_id'],2)
        store.prepare(self.plan,self.i);self.output(data=b'123')
        self.fails('artifact_total_limit',store.collect,self.plan,self.i,self.outputs)
        self.assertEqual(store.inspect(self.plan)['state']['attempts'][1]['status'],'prepared')

    def test_recovery_report_does_not_mutate_original_journals_or_partial_archive(self):
        store = self.prepared();self.output();store.prepare_artifact_archive(self.plan,self.i,self.outputs)
        base = self.root/w._base(self.i,'artifacts');base.mkdir(parents=True);(base/'files').mkdir()
        (base/'files/answer.txt').write_bytes(b'partial')
        store.__exit__()
        before = self.snapshot()
        with w.WorkspaceStore(self.root,create=False) as reopened:
            self.assertFalse(reopened.inspect(self.plan)['resumable'])
            self.fails('operation_uncertain',reopened.archive_artifacts,self.plan,self.i)
        self.assertEqual(before,self.snapshot())

    def test_unknown_root_run_is_not_ignored(self):
        store = self.prepared()
        (self.root/'artifacts'/str(uuid.uuid4())).mkdir()
        self.fails('unknown_run_path',store.inspect,self.plan)

    def test_journal_transition_cannot_reopen_archived_workspace(self):
        store = self.prepared();self.output();store.collect(self.plan,self.i,self.outputs)
        state = store.validate_journal(self.plan)['state']
        state['attempts'][0].update(status='prepared',artifacts=[],manifest_sha256=None)
        self.fails('workspace_transition_invalid',store._append,self.plan,state)

    def test_unknown_journal_version_rejected(self):
        store = self.prepared();path = self.root/'journals'/self.i['run_id']/'00000004.json'
        obj = d.load_json(path);obj['event']['schema_version'] = 2
        obj['sha256'] = d.content_sha256(obj['event'])
        path.chmod(0o600);path.write_bytes(d.canonical_json_bytes(obj))
        self.fails('schema_version_unsupported',store.inspect,self.plan)

    def test_reconstructed_prepared_state_is_resumable_but_never_executable(self):
        store = self.prepared();store.__exit__()
        with w.WorkspaceStore(self.root,create=False) as reopened:
            self.assertTrue(reopened.inspect(self.plan)['resumable'])
            self.fails('execution_disabled',reopened.activate,self.plan,self.i)
            self.output();reopened.collect(self.plan,self.i,self.outputs)
            self.assertFalse(reopened.inspect(self.plan)['executable'])


if __name__ == '__main__':
    unittest.main()
