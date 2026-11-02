"""S6-C pure/local synthetic tests. No unit, child, socket or agent is started."""
import copy
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from isolation import contract as c
from isolation import probe, verify

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT/'tests/isolation'


class Case(unittest.TestCase):
    def setUp(self):
        for target in ('subprocess.Popen', 'subprocess.run', 'socket.socket', 'socket.create_connection',
                       'urllib.request.urlopen', 'os.system', 'os.fork', 'os.posix_spawn', 'os.posix_spawnp'):
            guard = patch(target, side_effect=AssertionError('external operation forbidden'))
            guard.start();self.addCleanup(guard.stop)
        self.tmp = tempfile.TemporaryDirectory(dir=ROOT);self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.profile = c.read(PACKAGE/'fixtures/profile.example.json')
        self.profile['expected']['host_mount_namespace_inode'] = 11
        self.obs = dict(identity=dict(uid=62001, gid=62001, groups=[62001], cap_eff=0, no_new_privileges=1,
                        mount_namespace_inode=12, unit=self.profile['expected']['unit'],
                        cgroup=self.profile['expected']['cgroup'], invocation_id='a'*32),
                        filesystem=dict(zip(c.FS, ('allowed','matched','denied','denied','denied','denied'))),
                        resources={key:self.profile['limits'][key] for key in
                                   ('memory_max_bytes','cpu_quota_usec_per_sec','tasks_max')},
                        child=dict(state='not_run',pid=None,parent_pid=None,cgroup=None,alive_at_observation=None),
                        network={key:'not_verified' for key in c.NETWORK},termination='not_verified')

    def report(self, **kwargs):
        return c.make_report(self.profile, self.obs, **kwargs)

    def check(self, name, report=None):
        return next(row for row in (report or self.report())['checks'] if row['check_id']==name)['status']

    def fails(self, function, *args, **kwargs):
        with self.assertRaises((c.Invalid, OSError)):
            function(*args, **kwargs)

    def validate(self, report=None, **kwargs):
        report = report or self.report()
        return c.validate_report(report, self.profile, kwargs.get('profile_hash',c.digest(self.profile)),
                                 kwargs.get('report_hash',c.digest(report)))


class ContractTests(Case):
    def test_profile_valid_and_canonical_roundtrip(self):
        self.assertEqual(c.validate_profile(self.profile,c.digest(self.profile)),self.profile)
        self.assertEqual(c.parse(c.canonical(self.profile)),self.profile)

    def test_profile_hash_is_required(self):
        self.fails(c.validate_profile,self.profile,'a'*64)

    def test_unknown_profile_versions(self):
        for value in (True,0,2,'1',None):
            p=copy.deepcopy(self.profile);p['profile_version']=value
            self.fails(c.validate_profile,p,c.digest(p))

    def test_unknown_profile_fields_and_enable_flags(self):
        for name in ('force','enable','isolation_verified','optional_checks','executable'):
            p=copy.deepcopy(self.profile);p[name]=True
            self.fails(c.validate_profile,p,c.digest(p))

    def test_missing_profile_fields(self):
        for name in self.profile:
            p=copy.deepcopy(self.profile);del p[name]
            self.fails(c.validate_profile,p,c.digest(p))

    def test_unit_cgroup_and_uuid_are_closed(self):
        for name,value in (('unit','other.service'),('unit','--host=other'),('cgroup','/../../etc'),
                           ('cgroup','/system.slice/other.service')):
            p=copy.deepcopy(self.profile);p['expected'][name]=value
            self.fails(c.validate_profile,p,c.digest(p))
        self.profile['test_id']='not-a-uuid'
        self.fails(c.validate_profile,self.profile,c.digest(self.profile))

    def test_no_root_identity(self):
        for name in ('uid','gid'):
            p=copy.deepcopy(self.profile);p['expected'][name]=0
            self.fails(c.validate_profile,p,c.digest(p))

    def test_resource_types_ranges_and_unbounded_values(self):
        for name in self.profile['limits']:
            for value in (True,0,-1,None,'max',2**64):
                p=copy.deepcopy(self.profile);p['limits'][name]=value
                self.fails(c.validate_profile,p,c.digest(p))

    def test_policies_cannot_disable_checks(self):
        for name in ('filesystem_policy','network_policy'):
            p=copy.deepcopy(self.profile);p[name]='allow_all'
            self.fails(c.validate_profile,p,c.digest(p))

    def test_filesystem_and_network_expectations_cannot_be_weakened(self):
        for name,key in (('filesystem_expected','outside_write'),('network_expected','external_ipv4')):
            p=copy.deepcopy(self.profile);p[name][key]='allow'
            self.fails(c.validate_profile,p,c.digest(p))

    def test_duplicate_keys_nonfinite_float_bom_utf8(self):
        for raw in (b'{"a":1,"a":2}',b'{"a":1.2}',b'{"a":NaN}',b'{"a":Infinity}',b'\xff',b'\xef\xbb\xbf{}'):
            self.fails(c.parse,raw)

    def test_json_limits_and_non_json_types(self):
        self.fails(c.parse,b'x'*(c.MAX_BYTES+1))
        nested=[]
        for _ in range(22):nested=[nested]
        self.fails(c.canonical,nested)
        self.fails(c.canonical,{'x':2**200})
        self.fails(c.canonical,{'x':'x'*65537})
        self.fails(c.canonical,{'x':object()})

    def test_aggregate_json_output_is_bounded(self):
        self.fails(c.canonical,['x'*65536]*5)

    def test_timestamp_and_future_profile(self):
        for value in ('invalid','2026-13-01T00:00:00Z','2026-11-02T00:00:00+00:00'):
            p=copy.deepcopy(self.profile);p['created_at']=value
            self.fails(c.validate_profile,p,c.digest(p))
        self.fails(self.report,observed_at='2020-01-01T00:00:00Z')

    def test_no_unknown_test_states(self):
        for field in c.FS:
            obs=copy.deepcopy(self.obs);obs['filesystem'][field]='probably_safe'
            self.fails(c.make_report,self.profile,obs)

    def test_untrusted_objects_do_not_load_plugins(self):
        obs=copy.deepcopy(self.obs);obs['exec']='arbitrary'
        self.fails(c.make_report,self.profile,obs)


class VerificationTests(Case):
    def test_complete_consistent_partial_report_remains_unverified(self):
        report=self.report();self.assertEqual(self.validate(report),report)
        self.assertFalse(report['isolation_verified']);self.assertEqual(report['overall_status'],'not_verified')
        self.assertTrue(report['missing_evidence'])
        self.assertTrue(all(row['mandatory'] for row in report['checks']))

    def test_false_uid_gid_and_groups(self):
        for key,value in (('uid',99),('gid',99),('groups',[27,62001])):
            obs=copy.deepcopy(self.obs);obs['identity'][key]=value
            report=c.make_report(self.profile,obs)
            self.assertEqual(report['overall_status'],'failed');self.assertFalse(report['isolation_verified'])

    def test_wrong_unit_and_cgroup(self):
        for key in ('unit','cgroup'):
            self.obs['identity'][key]='other'
            self.assertEqual(self.check(key),'failed')

    def test_missing_unit_and_cgroup_are_not_verified(self):
        self.obs['identity']['unit']=None;self.obs['identity']['cgroup']=None
        self.assertEqual(self.check('unit'),'not_verified');self.assertEqual(self.check('cgroup'),'not_verified')

    def test_capabilities_and_no_new_privileges(self):
        self.obs['identity']['cap_eff']=1;self.obs['identity']['no_new_privileges']=0
        self.assertEqual(self.check('capabilities'),'failed');self.assertEqual(self.check('no_new_privileges'),'failed')

    def test_mount_namespace_same_or_unknown(self):
        self.obs['identity']['mount_namespace_inode']=11
        self.assertEqual(self.check('mount_namespace'),'failed')
        self.obs['identity']['mount_namespace_inode']=None
        self.assertEqual(self.check('mount_namespace'),'not_verified')

    def test_wrong_resource_limits_fail(self):
        for key in self.obs['resources']:
            obs=copy.deepcopy(self.obs);obs['resources'][key]+=1
            report=c.make_report(self.profile,obs)
            self.assertEqual(self.check(key,report),'failed')

    def test_configured_resource_limits_are_not_effectiveness_proof(self):
        for name in (*self.obs['resources'],'runtime_limit_effective'):
            self.assertEqual(self.check(name),'not_verified')

    def test_missing_resource_limits(self):
        self.obs['resources']={key:None for key in self.obs['resources']}
        for name in self.obs['resources']:self.assertEqual(self.check(name),'not_verified')

    def test_missing_filesystem_isolation(self):
        for name in ('reference_write','outside_write','other_read','hardlink'):
            obs=copy.deepcopy(self.obs);obs['filesystem'][name]='allowed'
            self.assertEqual(self.check(name,c.make_report(self.profile,obs)),'failed')

    def test_unavailable_canaries_remain_unknown(self):
        self.obs['filesystem']={key:'not_verified' for key in c.FS}
        for name in c.FS:self.assertEqual(self.check(name),'not_verified')

    def test_write_denial_does_not_prove_read_only_mount_or_host_visibility(self):
        for name in ('read_only_mount_effective','filesystem_visibility_boundary','symlink_traversal_os_boundary'):
            self.assertEqual(self.check(name),'not_verified')

    def test_no_network_success_from_json(self):
        for name in c.NETWORK:
            obs=copy.deepcopy(self.obs);obs['network'][name]='passed'
            self.fails(c.make_report,self.profile,obs)
            self.assertEqual(self.check(name),'not_verified')

    def test_no_process_end_success_from_json(self):
        self.obs['termination']=True
        self.fails(self.report)

    def test_no_process_tree_abort_or_ack_proof(self):
        for name in ('process_tree_abort','complete_process_end','final_acknowledgement'):
            self.assertEqual(self.check(name),'not_verified')

    def test_child_membership_success_is_not_tree_end(self):
        self.obs['child']=dict(state='observed',pid=42,parent_pid=41,cgroup=self.profile['expected']['cgroup'],
                               alive_at_observation=True)
        self.assertEqual(self.check('child_membership'),'passed')
        self.assertEqual(self.check('complete_process_end'),'not_verified')

    def test_wrong_child_cgroup(self):
        self.obs['child']=dict(state='observed',pid=42,parent_pid=41,cgroup='/other',alive_at_observation=True)
        self.assertEqual(self.check('child_membership'),'failed')

    def test_premature_child_loss(self):
        self.obs['child']=dict(state='lost_early',pid=42,parent_pid=41,cgroup=self.profile['expected']['cgroup'],
                               alive_at_observation=False)
        self.assertEqual(self.check('child_membership'),'failed')

    def test_incomplete_child_acknowledgement(self):
        self.obs['child']['state']='observed'
        self.fails(self.report)

    def test_incomplete_reports(self):
        for key in self.report():
            report=self.report();del report[key]
            self.fails(self.validate,report)

    def test_rejected_success_claim_even_with_recomputed_hash(self):
        for field,value in (('isolation_verified',True),('overall_status','passed'),('missing_evidence',[]),
                            ('assurance','trusted_host')):
            report=self.report();report[field]=value
            self.fails(self.validate,report)

    def test_cannot_erase_mandatory_or_failed_checks(self):
        report=self.report();report['checks'][0]['mandatory']=False
        self.fails(self.validate,report)
        report=self.report();report['checks']=report['checks'][1:]
        self.fails(self.validate,report)

    def test_tampered_bytes_with_old_digest(self):
        report=self.report();before=c.digest(report);report['observations']['identity']['uid']=7
        self.fails(self.validate,report,report_hash=before)

    def test_profile_drift(self):
        report=self.report();self.profile['limits']['tasks_max']=17
        self.fails(self.validate,report)

    def test_wrong_test_identity_and_profile_version(self):
        for key,value in (('test_id','66666666-6666-4666-8666-666666666666'),('profile_version',2)):
            report=self.report();report[key]=value
            self.fails(self.validate,report)

    def test_boolean_is_not_an_integer(self):
        self.obs['identity']['uid']=True
        self.fails(self.report)

    def test_repeated_verification_is_read_only_and_idempotent(self):
        report=self.report();before=c.canonical(report)
        first=verify.verify(self.profile,report,c.digest(self.profile),c.digest(report))
        second=verify.verify(self.profile,report,c.digest(self.profile),c.digest(report))
        self.assertEqual(first,second);self.assertEqual(c.canonical(report),before)

    def test_repeated_probes_have_distinct_receipt_ids(self):
        a=self.report();b=self.report()
        self.assertNotEqual(a['report_id'],b['report_id']);self.assertEqual(a['test_id'],b['test_id'])


class SafetyTests(Case):
    def fake_child_run(self, raw=None, *, early=False, timeout=False):
        class Output:
            closed=False
            def fileno(self):return 123456
            def close(self):self.closed=True
        class Child:
            pid=42
            stdout=Output()
            def poll(self):return 0 if early else None
            def wait(self, *, timeout):
                self.wait_timeout=timeout
                if fail_wait:raise subprocess.TimeoutExpired('synthetic child',timeout)
                return 0
        class Args:
            profile=PACKAGE/'fixtures/profile.example.json'
            expected_profile_sha256=c.digest(self.profile)
            test_root=self.root
        fail_wait=timeout;child=Child()
        ack=raw if raw is not None else c.canonical(dict(pid=42,parent_pid=os.getpid(),
                                                        cgroup=self.profile['expected']['cgroup']))
        with patch.object(probe,'local_observations',return_value=copy.deepcopy(self.obs)), \
             patch.object(probe,'approved_root',return_value=c.directory(self.root)), \
             patch.object(probe.subprocess,'Popen',return_value=child) as started, \
             patch.object(probe.select,'select',return_value=([child.stdout],[],[])), \
             patch.object(probe.os,'read',return_value=ack), contextlib.redirect_stdout(io.StringIO()) as out:
            if timeout:
                with self.assertRaises(subprocess.TimeoutExpired):probe.child_fixture(Args(),self.profile,self.obs)
            else:probe.child_fixture(Args(),self.profile,self.obs)
        self.assertTrue(child.stdout.closed);self.assertEqual(child.wait_timeout,10)
        self.assertEqual(started.call_count,1)
        command=started.call_args.args[0]
        self.assertEqual(command[1:4],['-E','-s','-B'])
        self.assertTrue(command[4].endswith('/fixtures/child.py'))
        self.assertNotIn('shell',started.call_args.kwargs)
        self.assertEqual(set(started.call_args.kwargs['env']),{'PATH','LANG','INVOCATION_ID'})
        report=c.parse(out.getvalue().encode());self.assertEqual(report['stage'],'pre_stop')
        self.assertFalse(report['isolation_verified'])
        return report

    def test_fixed_child_protocol_with_no_real_process(self):
        self.assertEqual(self.check('child_membership',self.fake_child_run()),'passed')

    def test_lost_or_early_child_ack_is_failure(self):
        for raw,early in ((b'{',False),(None,True)):
            self.obs['child']=dict(state='not_run',pid=None,parent_pid=None,cgroup=None,alive_at_observation=None)
            self.assertEqual(self.check('child_membership',self.fake_child_run(raw,early=early)),'failed')

    def test_lost_final_wait_is_not_tree_end(self):
        self.assertEqual(self.check('complete_process_end',self.fake_child_run(timeout=True)),'not_verified')

    def test_live_guard_rejects_current_non_test_unit(self):
        self.fails(probe.guard,self.profile,probe.local_observations())

    def test_guard_requires_every_identity_and_resource_boundary(self):
        probe.guard(self.profile,self.obs)
        for key,value in (('uid',0),('unit','other'),('cap_eff',1),('no_new_privileges',0),
                          ('mount_namespace_inode',11),('invocation_id',None)):
            obs=copy.deepcopy(self.obs);obs['identity'][key]=value
            self.fails(probe.guard,self.profile,obs)
        self.obs['resources']['memory_max_bytes']=None
        self.fails(probe.guard,self.profile,self.obs)

    def test_empty_supplementary_group_list_keeps_primary_gid(self):
        self.obs['identity']['groups']=[]
        probe.guard(self.profile,self.obs)
        self.assertEqual(self.check('groups'),'passed')

    def test_forged_json_context_cannot_start_child(self):
        class Args:
            profile=PACKAGE/'fixtures/profile.example.json'
            expected_profile_sha256=c.digest(self.profile)
            test_root=self.root
        with patch.object(probe.subprocess,'Popen',side_effect=AssertionError('must not start')) as start:
            self.fails(probe.child_fixture,Args(),self.profile,self.obs)
            start.assert_not_called()

    def test_no_operator_root_or_marker_adoption(self):
        (self.root/'marker.json').write_bytes(c.canonical(dict(kind='synthetic_isolation_test_root',
                  profile_version=c.VERSION,test_id=self.profile['test_id'],profile_sha256=c.digest(self.profile))))
        self.fails(probe.approved_root,self.root,self.profile)

    def test_reader_rejects_symlinks_hardlinks_and_traversal(self):
        normal=self.root/'normal.json';normal.write_bytes(b'{}')
        link=self.root/'link.json';link.symlink_to(normal)
        self.fails(c.read,link)
        hard=self.root/'hard.json';os.link(normal,hard)
        self.fails(c.read,hard)
        self.fails(c.directory,self.root/'..')
        directory=self.root/'directory';directory.symlink_to(self.root,target_is_directory=True)
        self.fails(c.read,directory/'normal.json')

    def test_reader_rejects_fifo_without_blocking(self):
        fifo=self.root/'fifo';os.mkfifo(fifo)
        self.fails(c.read,fifo)

    def test_fixed_leaf_guard_does_not_follow_symlink(self):
        fd=c.directory(self.root)
        try:
            for name in ('../secret','/etc/passwd','a/b','a\\b','..'):
                self.fails(c.leaf,fd,name)
        finally:os.close(fd)

    def test_harmless_filesystem_fixture_detects_missing_isolation(self):
        for role in ('reference','outside','other','output'):(self.root/role).mkdir()
        for role in ('reference','outside','other'):
            (self.root/role/'canary.txt').write_bytes(probe.canary(self.profile,role))
        before={p:p.read_bytes() for p in self.root.rglob('*.txt')}
        fd=c.directory(self.root)
        try:result=probe.filesystem(fd,self.profile)
        finally:os.close(fd)
        self.assertEqual(result['output_write'],'allowed');self.assertEqual(result['reference_write'],'allowed')
        self.assertEqual(result['other_read'],'allowed');self.assertEqual(result['hardlink'],'allowed')
        self.assertTrue(all(p.read_bytes()==raw for p,raw in before.items()))
        self.assertFalse(list((self.root/'output').iterdir()))

    def test_missing_canary_is_never_denial_proof(self):
        (self.root/'outside').mkdir();fd=c.directory(self.root)
        try:self.assertEqual(probe._access(fd,'outside',write=True),'not_verified')
        finally:os.close(fd)

    def test_kernel_access_denial_is_classified(self):
        (self.root/'outside').mkdir();fd=c.directory(self.root)
        try:
            with patch.object(c,'leaf',side_effect=PermissionError(13,'synthetic')):
                self.assertEqual(probe._access(fd,'outside',write=True),'denied')
        finally:os.close(fd)

    def test_probe_cli_outside_unit_never_writes_or_starts(self):
        file=self.root/'profile.json';file.write_bytes(c.canonical(self.profile))
        with contextlib.redirect_stdout(io.StringIO()) as out:
            rc=probe.main(['--profile',str(file),'--expected-profile-sha256',c.digest(self.profile),
                           '--test-root',str(self.root),'--with-child'])
        self.assertEqual(rc,2);self.assertFalse(json.loads(out.getvalue())['isolation_verified'])
        self.assertEqual(list(self.root.iterdir()),[file])

    def test_verify_cli_reports_partial_status_and_never_zero(self):
        profile=self.root/'profile.json';profile.write_bytes(c.canonical(self.profile))
        report=self.root/'report.json';value=self.report();report.write_bytes(c.canonical(value))
        with contextlib.redirect_stdout(io.StringIO()) as out:
            rc=verify.main(['--profile',str(profile),'--report',str(report),
                            '--expected-profile-sha256',c.digest(self.profile),
                            '--expected-report-sha256',c.digest(value)])
        self.assertEqual(rc,1);self.assertTrue(json.loads(out.getvalue())['consistency_verified'])
        self.assertFalse(json.loads(out.getvalue())['isolation_verified'])

    def test_verify_cli_corruption_is_invalid(self):
        file=self.root/'invalid.json';file.write_bytes(b'{')
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(verify.main(['--profile',str(file),'--report',str(file),
                    '--expected-profile-sha256','a'*64,'--expected-report-sha256','b'*64]),2)

    def test_no_positive_output_from_all_boolean_claims(self):
        report=self.report()
        for row in report['checks']:row['status']='passed'
        report.update(isolation_verified=True,overall_status='passed',missing_evidence=[])
        self.fails(self.validate,report)


if __name__=='__main__':
    unittest.main()
