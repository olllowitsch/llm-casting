"""S6-D read-only logic tests. System commands, children and sockets are mocked."""
import copy
from datetime import timedelta
import io
import os
import subprocess
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from isolation import contract as c, preflight as p, host_collect as h

ROOT=Path(__file__).resolve().parents[1]
PACKAGE=ROOT/'tests/isolation'
TEST='55555555-5555-4555-8555-555555555555'
BOOT='11111111-1111-4111-8111-111111111111'
INVOCATION='a'*32


class System:
    def __init__(self):self.existing=set();self.identity=None;self.active=[];self.files=[];self.uid_pids=[];self.uid=0
    def absent(self,path):return str(path) not in self.existing
    def account(self):return self.identity
    def units(self):return self.active
    def unit_files(self):return self.files
    def manager(self):return dict(Version='255.4',Features='+SECCOMP')
    def controllers(self):return ['cpu','memory','pids']
    def euid(self):return self.uid
    def host_mount_inode(self):return 42
    def uid_processes(self,uid):return self.uid_pids


class Case(unittest.TestCase):
    def setUp(self):
        for name in ('subprocess.run','subprocess.Popen','socket.socket','socket.create_connection',
                     'urllib.request.urlopen','os.system','os.fork','os.posix_spawn','os.posix_spawnp'):
            guard=patch(name,side_effect=AssertionError('external operation forbidden'))
            guard.start();self.addCleanup(guard.stop)
        self.temp=tempfile.TemporaryDirectory(dir=ROOT);self.addCleanup(self.temp.cleanup)
        self.folder=Path(self.temp.name);self.system=System();self.pin=c.digest(p.bundle_manifest())
        self.profile=c.read(PACKAGE/'fixtures/profile.example.json')
        self.profile['expected'].update(uid=23001,gid=23002,host_mount_namespace_inode=42)
        self.profile['limits']['runtime_seconds']=15
        self.account=dict(uid=23001,gid=23002,group_gid=23002,groups=[23002],shell='/usr/sbin/nologin',
                          home='/nonexistent',uid_aliases=1,gid_aliases=1)

    def inspect(self,**kwargs):return p.inspect(TEST,self.pin,system=self.system,**kwargs)
    def row(self,result,name):return next(x for x in result['checks'] if x['check_id']==name)
    def fails(self,fn,*args,**kwargs):
        with self.assertRaises((c.Invalid,OSError)):fn(*args,**kwargs)
    def declaration(self):
        now=c.timestamp(c.now())
        return dict(kind='isolation_operator_declaration',version=1,approval_id=BOOT,test_id=TEST,
                    scope='one_synthetic_test_only',issued_at=(now-timedelta(seconds=1)).isoformat().replace('+00:00','Z'),
                    expires_at=(now+timedelta(minutes=10)).isoformat().replace('+00:00','Z'),
                    bundle_sha256=self.pin,profile_sha256=c.digest(self.profile),image_sha256='b'*64)


class PreflightTests(Case):
    def test_plan_observes_absent_paths_but_never_authorizes_phase2(self):
        value=self.inspect()
        self.assertEqual(self.row(value,'install_root_absent')['status'],'passed')
        self.assertEqual(self.row(value,'operator_declaration')['status'],'blocked')
        self.assertFalse(value['phase2_execution_available']);self.assertFalse(value['isolation_verified'])

    def test_path_collision(self):
        self.system.existing.add(str(p.INSTALL))
        self.assertEqual(self.row(self.inspect(),'install_root_absent')['reason'],'path_collision')

    def test_unit_collision(self):
        self.system.active=['unexpected test unit']
        self.assertEqual(self.row(self.inspect(),'no_test_units')['status'],'blocked')

    def test_unloaded_other_static_test_unit_is_collision(self):
        self.system.files=['llm-casting-isolation-probe@other.service']
        self.assertEqual(self.row(self.inspect(),'no_test_unit_files')['status'],'blocked')

    def test_dropin_and_vendor_unit_collision(self):
        self.system.existing.add(str(p.UNIT_DIRS[2]/p.TEMPLATE))
        self.assertTrue(any(r['reason']=='unit_path_collision' for r in self.inspect()['checks']))

    def test_identity_collision(self):
        self.system.identity=self.account
        self.assertEqual(self.row(self.inspect(),'identity_absent')['status'],'blocked')

    def test_missing_operator_rights(self):
        self.system.uid=1001
        self.assertEqual(self.row(self.inspect(),'operator_rights')['status'],'blocked')

    def test_missing_controllers(self):
        self.system.controllers=lambda:['cpu']
        self.assertEqual(self.row(self.inspect(),'cgroup_controllers')['status'],'blocked')

    def test_wrong_systemd_version(self):
        self.system.manager=lambda:dict(Version='252')
        self.assertEqual(self.row(self.inspect(),'systemd')['status'],'blocked')

    def test_missing_seccomp_feature(self):
        self.system.manager=lambda:dict(Version='255.4',Features='-SECCOMP')
        self.assertEqual(self.row(self.inspect(),'seccomp_build_support')['status'],'blocked')

    def test_bundle_pin_drift(self):
        value=p.inspect(TEST,'b'*64,system=self.system)
        self.assertEqual(self.row(value,'bundle_hash')['reason'],'bundle_hash_mismatch')

    def test_account_actual_ids_no_fixed_assumption(self):
        p.validate_account(self.account,self.profile)
        for key in ('uid','gid','group_gid'):
            account=copy.deepcopy(self.account);account[key]+=1
            self.fails(p.validate_account,account,self.profile)

    def test_no_root_extra_groups_or_aliases(self):
        for key,value in (('uid',0),('groups',[27,23002]),('uid_aliases',2),('gid_aliases',2),('shell','/bin/bash')):
            account=copy.deepcopy(self.account);account[key]=value
            self.fails(p.validate_account,account,self.profile)

    def test_no_partial_profile_adoption(self):
        self.fails(p.validate_account,self.account,None)

    def test_approval_is_narrow_bound_and_expiring(self):
        record=self.declaration()
        self.assertEqual(p.validate_approval(record,TEST,self.pin,c.digest(self.profile),'b'*64),record)
        for key,value in (('scope','opencode_execution'),('test_id',BOOT),('bundle_sha256','c'*64),
                          ('profile_sha256','d'*64),('image_sha256','e'*64),('version',True),
                          ('expires_at','2020-01-01T00:00:00Z')):
            altered=copy.deepcopy(record);altered[key]=value
            self.fails(p.validate_approval,altered,TEST,self.pin,c.digest(self.profile),'b'*64)

    def test_no_boolean_approval_bypass(self):
        record=self.declaration();record['approved']=True
        self.fails(p.validate_approval,record,TEST,self.pin,c.digest(self.profile),'b'*64)

    def test_cleanup_requires_saved_bound_profile(self):
        self.assertEqual(self.row(self.inspect(mode='cleanup'),'no_saved_test_uid_processes')['status'],'blocked')
        file=self.folder/'profile.json';file.write_bytes(c.canonical(self.profile))
        self.system.uid_pids=[42]
        value=self.inspect(mode='cleanup',saved_profile=file,profile_pin=c.digest(self.profile))
        self.assertEqual(self.row(value,'no_saved_test_uid_processes')['reason'],'test_processes_remain')

    def test_cleanup_wrong_profile(self):
        profile=copy.deepcopy(self.profile);profile['test_id']=BOOT
        file=self.folder/'profile.json';file.write_bytes(c.canonical(profile))
        self.assertEqual(self.row(self.inspect(mode='cleanup',saved_profile=file,profile_pin=c.digest(profile)),
                                  'no_saved_test_uid_processes')['status'],'blocked')

    def test_cleanup_absence_is_informational_not_execution_permission(self):
        file=self.folder/'profile.json';file.write_bytes(c.canonical(self.profile))
        value=self.inspect(mode='cleanup',saved_profile=file,profile_pin=c.digest(self.profile))
        self.assertTrue(value['preflight_checks_passed']);self.assertFalse(value['phase2_execution_available'])

    def test_invalid_names_cannot_be_commands(self):
        for name in ('../../etc','dicomat.service','--host=elsewhere'):
            self.fails(p.unit_for,name)
        self.fails(p.LocalSystem().query,'start',p.unit_for(TEST))

    def test_system_query_is_fixed_read_only(self):
        class Result:returncode=0;stdout=b'Id=synthetic\n'
        with patch.object(p.subprocess,'run',return_value=Result()) as called:
            p.LocalSystem().query('unit',p.unit_for(TEST))
        args=called.call_args.args[0]
        self.assertEqual(args[:2],['/usr/bin/systemctl','show'])
        self.assertEqual(args[-1],p.unit_for(TEST))
        self.assertNotIn('shell',called.call_args.kwargs)

    def test_complete_unit_file_query_filters_only_own_namespace(self):
        class Result:
            returncode=0
            stdout=b'unrelated.service enabled enabled\nllm-casting-isolation-probe@.service static -\n'
        with patch.object(p.subprocess,'run',return_value=Result()) as called:
            names=p.LocalSystem().unit_files()
        self.assertEqual(names,[p.TEMPLATE])
        self.assertEqual(called.call_args.args[0],['/usr/bin/systemctl','list-unit-files','--full','--no-legend','--no-pager'])

    def test_duplicate_manager_properties_rejected(self):
        self.fails(p.properties,'Id=a\nId=b\n')

    def test_path_symlink_collision_and_parent_traversal(self):
        link=self.folder/'link';link.symlink_to(self.folder,target_is_directory=True)
        self.fails(p.LocalSystem().absent,link/'new')
        self.fails(p.LocalSystem().absent,self.folder/'..'/'new')

    def test_file_hash_detects_links_content_and_limits(self):
        file=self.folder/'data';file.write_bytes(b'synthetic')
        before=p.file_hash(file);file.write_bytes(b'changed')
        self.assertNotEqual(before,p.file_hash(file))
        self.fails(p.file_hash,file,limit=1)
        link=self.folder/'link';link.symlink_to(file);self.fails(p.file_hash,link)
        hard=self.folder/'hard';os.link(file,hard);self.fails(p.file_hash,file)

    def test_root_image_magic_is_checked_without_mounting(self):
        file=self.folder/'image';file.write_bytes(b'not-a-root-image')
        self.fails(p.file_hash,file,magic=b'hsqs')

    def test_missing_prepared_tree_is_a_reported_stop(self):
        with patch.object(p,'INSTALL',self.folder/'absent'),patch.object(p,'STATE',self.folder/'no-state'):
            value=self.inspect(mode='prepared',profile_pin='a'*64,image_pin='b'*64)
        self.assertFalse(value['preflight_checks_passed']);self.assertFalse(value['phase2_execution_available'])

    def test_even_complete_prepared_facts_never_enable_execution(self):
        manifest=p.bundle_manifest();profile_pin=c.digest(self.profile);root=p.STATE/TEST
        self.system.identity=self.account
        self.system.files=[p.TEMPLATE]
        marker=dict(kind='synthetic_isolation_test_root',profile_version=1,test_id=TEST,profile_sha256=profile_pin)
        records={str(root/'profile.json'):self.profile,str(root/'marker.json'):marker,
                 str(root/'approval.json'):self.declaration()}
        def hashes(path,**kwargs):
            path=Path(path)
            if path.name=='rootfs.squashfs':return 'b'*64
            if path.name=='canary.txt':
                raw=('llm-casting-isolation-canary:'+path.parent.name+':'+TEST+'\n').encode()
                return p.hashlib.sha256(raw).hexdigest()
            if path.name=='10-profile.conf':
                return p.hashlib.sha256(('[Service]\nEnvironment=LLM_CASTING_PROFILE_SHA256='+profile_pin+'\n').encode()).hexdigest()
            return 'c'*64
        fd=os.open(self.folder,os.O_RDONLY|os.O_DIRECTORY)
        with patch.object(p,'bundle_manifest',return_value=manifest),patch.object(p,'protected_directory'), \
             patch.object(p,'file_hash',side_effect=hashes),patch.object(c,'read',side_effect=lambda path:records[str(path)]), \
             patch.object(c,'directory',return_value=fd), \
             patch.object(p.os,'fstat',return_value=SimpleNamespace(st_uid=23001,st_gid=23002,st_mode=0o700)), \
             patch.object(p.os,'listdir',side_effect=lambda path:[] if type(path) is int else ['10-profile.conf']):
            value=self.inspect(mode='prepared',profile_pin=profile_pin,image_pin='b'*64)
        self.assertTrue(value['preflight_checks_passed'],value['checks'])
        self.assertEqual(value['profile_sha256'],profile_pin);self.assertEqual(value['image_sha256'],'b'*64)
        self.assertFalse(value['phase2_execution_available']);self.assertTrue(value['operator_decision_required'])


class HostTests(Case):
    def observation(self, *, after=False):
        manager=dict(Id=p.unit_for(TEST),User=p.IDENTITY,Group=p.IDENTITY,InvocationID=INVOCATION,
                     ControlGroup=self.profile['expected']['cgroup'],MainPID='0' if after else '42',
                     ActiveState='failed' if after else 'active',SubState='failed' if after else 'running',
                     Result='exit-code' if after else 'success',ExecMainCode='1',ExecMainStatus='1',Job='0',
                     MemoryMax='134217728',CPUQuotaPerSecUSec='250ms',TasksMax='16',RuntimeMaxUSec='15s',
                     KillMode='control-group',Restart='no',NoNewPrivileges='yes')
        group=dict(device=1,inode=99,path=self.profile['expected']['cgroup'],pids=[] if after else [42],
                   populated=0 if after else 1,memory_max_bytes=134217728,tasks_max=16,cpu_quota_usec_per_sec=250000,
                   memory_current=0 if after else 2048,pids_current=0 if after else 1,cpu_usage_usec=100)
        process=dict(pid=42,start_ticks=100,uids=[23001]*4,gids=[23002]*4,cgroup=self.profile['expected']['cgroup'],
                     cap_eff=0,no_new_privileges=1)
        return dict(boot_id=BOOT,manager_before=copy.deepcopy(manager),manager_after=manager,
                    uid_pids_before=[] if after else [42],uid_pids_after=[] if after else [42],
                    processes=[] if after else [process],cgroup_before=copy.deepcopy(group),cgroup_after=group,read_errors=[])

    def assess(self,obs=None, *, after=False,previous=None,pin=None):
        return h.assess(self.profile,obs or self.observation(after=after),phase='after' if after else 'during',
                        expected_boot=BOOT,expected_invocation=INVOCATION,previous=previous,previous_pin=pin)

    def previous(self):
        observation=self.observation()
        return dict(kind='isolation_host_snapshot',version=1,test_id=TEST,profile_sha256=c.digest(self.profile),
                    phase='during',expected_boot_id=BOOT,expected_invocation_id=INVOCATION,
                    observation=observation,assessment=self.assess(observation),isolation_verified=False)

    def test_during_facts_are_independent_but_not_isolation_approval(self):
        value=self.assess();self.assertTrue(all(x['status']=='observed' for x in value['checks']))
        self.assertFalse(value['isolation_verified']);self.assertEqual(value['resource_effectiveness'],'not_verified')

    def fake_host(self):
        obs=self.observation()
        class FakeHost:
            def unit(self,name):return copy.deepcopy(obs['manager_after'])
            def boot_id(self):return BOOT
            def uid_processes(self,uid):return [42]
            def cgroup(self,path):return copy.deepcopy(obs['cgroup_after'])
            def process(self,pid):return copy.deepcopy(obs['processes'][0])
        return FakeHost()

    def test_collector_uses_host_backend_without_probe_data(self):
        value=h.collect(self.profile,phase='during',expected_boot=BOOT,expected_invocation=INVOCATION,host=self.fake_host())
        self.assertFalse(value['isolation_verified'])
        self.assertTrue(all(r['status']=='observed' for r in value['assessment']['checks']))

    def test_collector_manager_timeout_is_missing_evidence(self):
        host=self.fake_host()
        def timeout(name):raise subprocess.TimeoutExpired('synthetic read-only query',5)
        host.unit=timeout
        value=h.collect(self.profile,phase='during',expected_boot=BOOT,expected_invocation=INVOCATION,host=host)
        self.assertIn('manager_before',value['observation']['read_errors'])
        self.assertFalse(value['isolation_verified'])

    def test_bound_empty_tree_and_uid_after_start_sample(self):
        previous=self.previous();value=self.assess(after=True,previous=previous,pin=c.digest(previous))
        self.assertEqual(value['process_end_status'],'observed_empty_bound_cgroup_and_uid_at_samples')
        self.assertFalse(value['isolation_verified'])

    def test_after_without_start_proof_not_verified(self):
        self.assertEqual(self.assess(after=True)['process_end_status'],'not_verified')

    def test_previous_pin_without_receipt_is_rejected(self):
        self.fails(self.assess,after=True,pin='a'*64)

    def test_wrong_unit_invocation_boot_and_uid(self):
        for key,value in (('Id','dicomat.service'),('InvocationID','b'*32),('User','root')):
            obs=self.observation();obs['manager_after'][key]=value
            self.assertTrue(any(x['status']=='failed' for x in self.assess(obs)['checks']))
        obs=self.observation();obs['boot_id']=TEST
        self.assertTrue(any(x['status']=='failed' for x in self.assess(obs)['checks']))
        obs=self.observation();obs['processes'][0]['uids']=[123]*4
        self.assertTrue(any(x['status']=='failed' for x in self.assess(obs)['checks']))

    def test_wrong_process_cgroup_or_privileges(self):
        for key,value in (('cgroup','/other'),('cap_eff',1),('no_new_privileges',0)):
            obs=self.observation();obs['processes'][0][key]=value
            self.assertTrue(any(x['status']=='failed' for x in self.assess(obs)['checks']))

    def test_wrong_manager_cgroup(self):
        obs=self.observation();obs['manager_after']['ControlGroup']='/other'
        self.assertTrue(any(x['status']=='failed' for x in self.assess(obs)['checks']))

    def test_replaced_cgroup_between_start_and_end(self):
        obs=self.observation(after=True)
        obs['cgroup_before']['inode']=obs['cgroup_after']['inode']=100
        previous=self.previous()
        self.assertEqual(self.assess(obs,after=True,previous=previous,pin=c.digest(previous))['process_end_status'],'not_verified')

    def test_missing_cgroup_is_not_empty_cgroup(self):
        obs=self.observation(after=True);obs['cgroup_before']=obs['cgroup_after']=None
        previous=self.previous()
        self.assertEqual(self.assess(obs,after=True,previous=previous,pin=c.digest(previous))['process_end_status'],'not_verified')

    def test_remaining_child_even_if_parent_is_gone(self):
        obs=self.observation(after=True);obs['uid_pids_before']=obs['uid_pids_after']=[43]
        previous=self.previous()
        self.assertEqual(self.assess(obs,after=True,previous=previous,pin=c.digest(previous))['process_end_status'],'not_verified')

    def test_foreign_process_remaining_in_cgroup(self):
        obs=self.observation(after=True);obs['cgroup_after']['pids']=[43];obs['cgroup_after']['populated']=1
        previous=self.previous()
        self.assertEqual(self.assess(obs,after=True,previous=previous,pin=c.digest(previous))['process_end_status'],'not_verified')

    def test_racing_uid_or_cgroup_inventory(self):
        obs=self.observation();obs['uid_pids_after']=[42,43];obs['cgroup_after']['inode']=100
        self.assertTrue(any(x['status']=='not_verified' for x in self.assess(obs)['checks']))

    def test_unreadable_metadata_is_missing_evidence(self):
        obs=self.observation();obs['read_errors']=['process_42']
        self.assertTrue(any(x['status']=='not_verified' for x in self.assess(obs)['checks']))

    def test_unreadable_uid_inventory_is_never_observed_empty(self):
        obs=self.observation(after=True);obs['read_errors']=['uid_inventory_before','uid_inventory_after']
        value=self.assess(obs,after=True)
        row=next(x for x in value['checks'] if x['check_id']=='no_test_uid_processes')
        self.assertEqual(row['status'],'not_verified')

    def test_missing_cgroup_identity_fields_cannot_match_each_other(self):
        for key in ('device','inode','populated'):
            obs=self.observation();obs['cgroup_before'][key]=obs['cgroup_after'][key]=None
            self.fails(self.assess,obs)

    def test_tampered_previous_receipt(self):
        previous=self.previous();pin=c.digest(previous);previous['assessment']['isolation_verified']=True
        self.fails(self.assess,after=True,previous=previous,pin=pin)
        self.fails(self.assess,after=True,previous=previous,pin=c.digest(previous))

    def test_boolean_evidence_cannot_be_a_kernel_integer(self):
        obs=self.observation();obs['cgroup_after']['populated']=False
        self.fails(self.assess,obs)

    def test_duplicate_process_samples_rejected(self):
        obs=self.observation();obs['processes']*=2
        self.fails(self.assess,obs)

    def test_no_probe_report_accepted_as_host_observation(self):
        self.fails(self.assess,dict(isolation_verified=True))

    def test_systemd_time_units(self):
        self.assertEqual(h.usec('250ms'),250000);self.assertEqual(h.usec('15s'),15000000)
        self.assertIsNone(h.usec('infinity'));self.assertIsNone(h.usec(True))


if __name__=='__main__':unittest.main()
