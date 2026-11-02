#!/usr/bin/env python3
"""S6-D independent read-only host snapshots. No probe assertions are consumed.

Snapshot agreement is not global OS isolation approval. Exported JSON still
requires a trusted operator capture and an independently retained checksum.
"""
import argparse
import os
from pathlib import Path
import re
import stat
import subprocess

try:
    from . import contract as c, preflight as p, probe
except ImportError:
    import contract as c
    import preflight as p
    import probe


def usec(value):
    if type(value) is not str:return None
    match = re.fullmatch(r'(\d+)(us|ms|s)?',value)
    if not match:return None
    return int(match[1])*{None:1,'us':1,'ms':1000,'s':1000000}[match[2]]


def numeric(value):
    return int(value) if type(value) is str and value.isascii() and value.isdigit() else None


class Host(p.LocalSystem):
    def boot_id(self):return probe._text('/proc/sys/kernel/random/boot_id')

    def process(self, pid):
        c.integer(pid,1,2**31-1);base='/proc/'+str(pid)
        def start():return int(probe._text(base+'/stat').rsplit(')',1)[1].split()[19])
        before=start()
        status=dict(line.split(':',1) for line in probe._text(base+'/status').splitlines() if ':' in line)
        uid=list(map(int,status['Uid'].split()));gid=list(map(int,status['Gid'].split()))
        group=probe._text(base+'/cgroup')
        c.need(group.startswith('0::') and len(group.splitlines())==1,'process_cgroup_ambiguous')
        value=dict(pid=pid,start_ticks=before,uids=uid,gids=gid,cgroup=group[3:],
                   cap_eff=int(status['CapEff'].strip(),16),no_new_privileges=int(status['NoNewPrivs'].strip()))
        c.need(before==start(),'process_identity_changed')
        return value

    def cgroup(self, path):
        # The caller provides only the exact validated profile-derived cgroup.
        c.need(type(path) is str and bool(re.fullmatch(
            r'/system.slice/llm-casting-isolation-probe@[0-9a-f-]{36}\.service',path)),'cgroup_invalid')
        base=Path('/sys/fs/cgroup'+path)
        fd=c.directory(base)
        try:
            identity=os.fstat(fd);pids=set();entries=[0]
            def walk(parent,depth):
                c.need(depth<=8,'cgroup_depth_limit')
                proc=c.leaf(parent,'cgroup.procs')
                try:raw=os.read(proc,8193);c.need(len(raw)<=8192,'cgroup_pid_limit')
                finally:os.close(proc)
                for item in raw.split():
                    pid=int(item);c.integer(pid,1,2**31-1);pids.add(pid)
                c.need(len(pids)<=64,'cgroup_pid_limit')
                with os.scandir(parent) as children:
                    for child in children:
                        entries[0]+=1;c.need(entries[0]<=2048,'cgroup_entry_limit')
                        s=child.stat(follow_symlinks=False)
                        c.need(not stat.S_ISLNK(s.st_mode),'cgroup_symlink')
                        if stat.S_ISDIR(s.st_mode):
                            sub=os.open(child.name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=parent)
                            try:walk(sub,depth+1)
                            finally:os.close(sub)
            walk(fd,0)
            def text(name):
                leaf=c.leaf(fd,name)
                try:
                    data=os.read(leaf,8193);c.need(len(data)<=8192,'cgroup_metadata_limit');return data.decode('ascii').strip()
                finally:os.close(leaf)
            events=dict(line.split() for line in text('cgroup.events').splitlines())
            quota=text('cpu.max').split()
            q=numeric(quota[0]);period=numeric(quota[1]) if len(quota)==2 else None
            cpu=q*1000000//period if q is not None and period and q*1000000%period==0 else None
            cpu_stat=dict(line.split() for line in text('cpu.stat').splitlines())
            result=dict(device=identity.st_dev,inode=identity.st_ino,path=path,pids=sorted(pids),
                        populated=numeric(events.get('populated')),memory_max_bytes=numeric(text('memory.max')),
                        tasks_max=numeric(text('pids.max')),cpu_quota_usec_per_sec=cpu,
                        memory_current=numeric(text('memory.current')),pids_current=numeric(text('pids.current')),
                        cpu_usage_usec=numeric(cpu_stat.get('usage_usec')))
            current=c.directory(base)
            try:c.need((os.fstat(current).st_dev,os.fstat(current).st_ino)==(identity.st_dev,identity.st_ino),'cgroup_changed')
            finally:os.close(current)
            return result
        finally:os.close(fd)


def assess(profile, observation, *, phase, expected_boot, expected_invocation, previous=None, previous_pin=None):
    """Pure conservative assessment of HOST snapshots, not an attestation verifier."""
    c.validate_profile(profile,c.digest(profile));c.identifier(expected_boot)
    c.need(type(expected_invocation) is str and bool(re.fullmatch(r'[0-9a-f]{32}',expected_invocation)), 'invocation_invalid')
    c.need(phase in ('during','after'),'phase_invalid')
    c.need((previous is None)==(previous_pin is None) and (phase!='during' or previous is None),
           'host_previous_receipt_invalid')
    c.obj(observation,('boot_id','manager_before','manager_after','uid_pids_before','uid_pids_after',
                       'processes','cgroup_before','cgroup_after','read_errors'))
    rows=[]
    def add(name,state):rows.append(dict(check_id=name,status=state))
    def compare(name,value,expected):
        add(name,'not_verified' if value is None or value=='' else 'observed' if value==expected else 'failed')
    before=observation['manager_before'];after=observation['manager_after']
    c.need(type(before) is dict and type(after) is dict,'manager_observation_invalid')
    for manager in (before,after):
        c.need(set(manager)<=set(p.UNIT_FIELDS) and all(type(v) is str for v in manager.values()),'manager_observation_invalid')
    c.need(type(observation['read_errors']) is list and
           all(type(x) is str and re.fullmatch(r'[a-z][a-z0-9_]{0,79}',x) for x in observation['read_errors']),
           'host_errors_invalid')
    for candidate in (observation['cgroup_before'],observation['cgroup_after']):
        if candidate is None:continue
        c.obj(candidate,('device','inode','path','pids','populated','memory_max_bytes','tasks_max',
                         'cpu_quota_usec_per_sec','memory_current','pids_current','cpu_usage_usec'))
        c.need(type(candidate['path']) is str and type(candidate['pids']) is list,'cgroup_observation_invalid')
        c.integer(candidate['device'],1);c.integer(candidate['inode'],1);c.integer(candidate['populated'],0,1)
        for pid in candidate['pids']:c.integer(pid,1,2**31-1)
        c.need(candidate['pids']==sorted(set(candidate['pids'])) and len(candidate['pids'])<=64,'cgroup_observation_invalid')
        for key,value in candidate.items():
            if key not in ('path','pids') and value is not None:c.integer(value)
    compare('boot',observation['boot_id'],expected_boot)
    for key,wanted in (('Id',profile['expected']['unit']),('User',p.IDENTITY),('Group',p.IDENTITY),
                       ('InvocationID',expected_invocation),('ControlGroup',profile['expected']['cgroup']),
                       ('KillMode','control-group'),('Restart','no'),
                       ('NoNewPrivileges','yes')):
        compare('manager_'+key,after.get(key),wanted)
    add('stable_manager_identity','observed' if all(before.get(k)==after.get(k) and after.get(k)
        for k in ('Id','InvocationID','User','Group','ControlGroup')) else 'not_verified')
    add('metadata_complete','observed' if not observation['read_errors'] else 'not_verified')
    for name in ('uid_pids_before','uid_pids_after'):
        c.need(type(observation[name]) is list,'pid_inventory_invalid')
        for pid in observation[name]:c.integer(pid,1,2**31-1)
        c.need(observation[name]==sorted(set(observation[name])) and len(observation[name])<=64,'pid_inventory_invalid')
    c.need(type(observation['processes']) is list and len(observation['processes'])<=64,'process_inventory_invalid')
    expected_cgroup=profile['expected']['cgroup'];group=observation['cgroup_after']
    uid_readable=not {'uid_inventory_before','uid_inventory_after'}.intersection(observation['read_errors'])
    stable_pids=uid_readable and observation['uid_pids_before']==observation['uid_pids_after']
    add('stable_uid_inventory','observed' if stable_pids else 'not_verified')
    if group is not None:
        c.obj(group,('device','inode','path','pids','populated','memory_max_bytes','tasks_max',
                     'cpu_quota_usec_per_sec','memory_current','pids_current','cpu_usage_usec'))
        compare('cgroup_path',group['path'],expected_cgroup)
        first=observation['cgroup_before']
        add('stable_cgroup_identity','observed' if type(first) is dict and
            all(first.get(k)==group[k] for k in ('device','inode','pids','path','populated')) else 'not_verified')
    else:add('cgroup_path','not_verified');add('stable_cgroup_identity','not_verified')
    limits=profile['limits']
    for key in ('memory_max_bytes','cpu_quota_usec_per_sec','tasks_max'):
        compare('cgroup_configured_'+key,group.get(key) if group else None,limits[key])
    compare('manager_memory_configured',numeric(after.get('MemoryMax')),limits['memory_max_bytes'])
    compare('manager_cpu_configured',usec(after.get('CPUQuotaPerSecUSec')),limits['cpu_quota_usec_per_sec'])
    compare('manager_tasks_configured',numeric(after.get('TasksMax')),limits['tasks_max'])
    compare('manager_runtime_configured',usec(after.get('RuntimeMaxUSec')),limits['runtime_seconds']*1000000)
    samples=observation['processes'];seen=[];members=True
    for item in samples:
        c.obj(item,('pid','start_ticks','uids','gids','cgroup','cap_eff','no_new_privileges'))
        for key in ('pid','start_ticks','cap_eff','no_new_privileges'):c.integer(item[key])
        c.need(type(item['uids']) is list and type(item['gids']) is list,'process_ids_invalid')
        for number in item['uids']+item['gids']:c.integer(number)
        members &= (item['uids']==[profile['expected']['uid']]*4 and
                    item['gids']==[profile['expected']['gid']]*4 and item['cgroup']==expected_cgroup and
                    item['cap_eff']==0 and item['no_new_privileges']==1)
        seen.append(item['pid'])
    c.need(len(seen)==len(set(seen)),'duplicate_process_sample')
    if phase=='during':
        complete=bool(seen) and sorted(seen)==observation['uid_pids_after'] and stable_pids
        add('process_identity_membership','observed' if complete and members else 'failed' if seen and not members else 'not_verified')
        if group is not None:
            add('cgroup_process_inventory','observed' if group['pids']==sorted(seen) and complete else 'not_verified')
        main=numeric(after.get('MainPID'))
        compare('main_pid_in_inventory',None if main is None else main in seen,True)
    else:
        add('no_test_uid_processes','observed' if not seen and not observation['uid_pids_after'] and stable_pids
            else 'failed' if observation['uid_pids_after'] else 'not_verified')
        compare('main_pid_ended',numeric(after.get('MainPID')),0)
        compare('unit_terminal',None if not after.get('ActiveState') else after['ActiveState'] in ('inactive','failed'),True)
        compare('no_manager_job',None if after.get('Job') is None else after['Job'] in ('0',''),True)
        add('empty_bound_cgroup','not_verified' if group is None else
            'observed' if group['pids']==[] and group['populated']==0 else 'failed')
    chain_ok=False
    if previous is not None:
        c.hash_value(previous_pin);c.need(c.digest(previous)==previous_pin,'host_previous_hash_mismatch')
        c.need(previous.get('kind')=='isolation_host_snapshot' and type(previous.get('version')) is int and
               previous['version']==1 and previous.get('phase')=='during' and previous.get('test_id')==profile['test_id'] and
               previous.get('profile_sha256')==c.digest(profile) and previous.get('expected_boot_id')==expected_boot and
               previous.get('expected_invocation_id')==expected_invocation and previous.get('isolation_verified') is False,
               'host_previous_binding_invalid')
        original=assess(profile,previous['observation'],phase='during',expected_boot=expected_boot,
                        expected_invocation=expected_invocation)
        c.need(c.canonical(original)==c.canonical(previous['assessment']),'host_previous_claim_invalid')
        chain_ok=all(r['status']=='observed' for r in original['checks'])
    end='not_verified'
    if phase=='after':
        add('independent_start_receipt','observed' if chain_ok else 'not_verified')
        previous_group=previous['observation']['cgroup_after'] if previous is not None else None
        same_group=(type(previous_group) is dict and type(group) is dict and
                    all(previous_group[k]==group[k] for k in ('device','inode','path')))
        add('cgroup_same_as_start','observed' if same_group else 'not_verified')
        # Require both bound cgroup and UID evidence. A removed cgroup is never
        # promoted to an empty one, even if two UID snapshots are empty.
        identity_names={'boot','manager_Id','manager_User','manager_Group','manager_InvocationID',
                        'manager_Restart','manager_NoNewPrivileges','manager_KillMode','manager_ControlGroup',
                        'stable_manager_identity','metadata_complete','stable_uid_inventory','no_test_uid_processes',
                        'main_pid_ended','unit_terminal','no_manager_job','independent_start_receipt',
                        'empty_bound_cgroup','stable_cgroup_identity','cgroup_path','cgroup_same_as_start'}
        if all(row['status']=='observed' for row in rows if row['check_id'] in identity_names):
            end='observed_empty_bound_cgroup_and_uid_at_samples'
    return dict(checks=rows,process_end_status=end,resource_effectiveness='not_verified',
                filesystem_effectiveness='not_verified',network_effectiveness='not_verified',isolation_verified=False)


def collect(profile, *, phase, expected_boot, expected_invocation, host=None, previous=None, previous_pin=None):
    c.validate_profile(profile,c.digest(profile));host=host or Host();errors=[]
    def read(name,action,default):
        try:return action()
        except (c.Invalid,OSError,ValueError,KeyError,IndexError,subprocess.SubprocessError):errors.append(name);return default
    unit=profile['expected']['unit'];uid=profile['expected']['uid'];path=profile['expected']['cgroup']
    before=read('manager_before',lambda:host.unit(unit),{})
    boot=read('boot_id',host.boot_id,None)
    first=read('uid_inventory_before',lambda:host.uid_processes(uid),[])
    cg1=read('cgroup_before',lambda:host.cgroup(path),None)
    samples=[]
    for pid in first:
        sample=read('process_'+str(pid),lambda pid=pid:host.process(pid),None)
        if sample is not None:samples.append(sample)
    cg2=read('cgroup_after',lambda:host.cgroup(path),None)
    last=read('uid_inventory_after',lambda:host.uid_processes(uid),[])
    after=read('manager_after',lambda:host.unit(unit),{})
    observation=dict(boot_id=boot,manager_before=before,manager_after=after,uid_pids_before=first,uid_pids_after=last,
                     processes=samples,cgroup_before=cg1,cgroup_after=cg2,read_errors=errors)
    assessment=assess(profile,observation,phase=phase,expected_boot=expected_boot,expected_invocation=expected_invocation,
                      previous=previous,previous_pin=previous_pin)
    return dict(kind='isolation_host_snapshot',version=1,test_id=profile['test_id'],profile_sha256=c.digest(profile),
                phase=phase,observed_at=c.now(),expected_boot_id=expected_boot,expected_invocation_id=expected_invocation,
                previous_sample_sha256=previous_pin,observation=observation,assessment=assessment,isolation_verified=False,
                trust='live_host_read_only_export_requires_external_operator_pin')


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--test-id',required=True)
    parser.add_argument('--expected-profile-sha256',required=True)
    parser.add_argument('--expected-bundle-sha256',required=True)
    parser.add_argument('--expected-boot-id',required=True)
    parser.add_argument('--expected-invocation-id',required=True)
    parser.add_argument('--phase',choices=('during','after'),required=True)
    parser.add_argument('--previous',type=Path)
    parser.add_argument('--expected-previous-sha256')
    args=parser.parse_args(argv)
    try:
        c.identifier(args.test_id);root=p.STATE/args.test_id
        c.hash_value(args.expected_bundle_sha256);p.protected_directory(p.INSTALL)
        c.need(c.digest(p.bundle_manifest(p.INSTALL/'package',protected=True))==args.expected_bundle_sha256,
               'host_bundle_hash_mismatch')
        p.protected_directory(p.STATE);p.protected_directory(root)
        p.file_hash(root/'profile.json',protected=True)
        profile=c.validate_profile(c.read(root/'profile.json'),args.expected_profile_sha256)
        c.need(profile['test_id']==args.test_id,'host_test_identity_mismatch')
        p.validate_account(Host().account(),profile)
        previous=c.read(args.previous) if args.previous else None
        if previous is not None:
            c.need(previous.get('bundle_sha256')==args.expected_bundle_sha256,'host_previous_bundle_mismatch')
        value=collect(profile,phase=args.phase,expected_boot=args.expected_boot_id,
                      expected_invocation=args.expected_invocation_id,previous=previous,previous_pin=args.expected_previous_sha256)
        value['bundle_sha256']=args.expected_bundle_sha256
        print(c.canonical(value).decode())
        return 1 if any(r['status']!='observed' for r in value['assessment']['checks']) else 0
    except (c.Invalid,OSError,ValueError,TypeError,KeyError,subprocess.SubprocessError):
        print('{"error":"host_collection_not_verified","isolation_verified":false}')
        return 2


if __name__=='__main__':
    raise SystemExit(main())
