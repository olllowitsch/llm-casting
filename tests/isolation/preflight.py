#!/usr/bin/env python3
"""S6-D read-only operator preflight. Never installs, starts, stops or cleans up.

An approval record is a declaration, not an authorization mechanism. This tool
has no Phase-2 operations and never grants isolation/OpenCode approval.
"""
import argparse
from datetime import timedelta
import grp
import hashlib
import os
from pathlib import Path
import pwd
import re
import stat
import subprocess

try:
    from . import contract as c
except ImportError:
    import contract as c

IDENTITY = 'llm-casting-probe'
INSTALL = Path('/opt/llm-casting-isolation-probe')
STATE = Path('/var/lib/llm-casting-isolation-probe')
TEMPLATE = 'llm-casting-isolation-probe@.service'
UNIT_DIRS = tuple(Path(x) for x in (
    '/etc/systemd/system','/run/systemd/system','/usr/lib/systemd/system',
    '/etc/systemd/system.control','/run/systemd/system.control','/run/systemd/transient',
    '/run/systemd/generator.early','/etc/systemd/system.attached','/run/systemd/system.attached',
    '/run/systemd/generator','/usr/local/lib/systemd/system','/run/systemd/generator.late'))
BUNDLE_FILES = ('contract.py', 'probe.py', 'verify.py', 'preflight.py', 'host_collect.py',
                'fixtures/child.py', 'fixtures/profile.example.json', 'unit-templates/s6d/'+TEMPLATE)
UNIT_FIELDS = ('Id', 'User', 'Group', 'InvocationID', 'ControlGroup', 'MainPID', 'ActiveState', 'SubState',
               'Result', 'ExecMainCode', 'ExecMainStatus', 'Job', 'MemoryMax', 'CPUQuotaPerSecUSec',
               'TasksMax', 'RuntimeMaxUSec', 'KillMode', 'Restart', 'NoNewPrivileges')


def unit_for(test_id):
    c.identifier(test_id)
    return 'llm-casting-isolation-probe@'+test_id+'.service'


def properties(text):
    result = {}
    c.need(type(text) is str and len(text.encode()) <= 65536, 'manager_output_limit')
    for line in text.splitlines():
        c.need('=' in line, 'manager_output_invalid')
        key, value = line.split('=', 1)
        c.need(key not in result, 'manager_duplicate_property');result[key] = value
    return result


def file_hash(path, *, protected=False, limit=1048576, magic=None):
    """Hash a stable normal single-link file; reject exchanged names/directories."""
    path = Path(path);parent = c.directory(path.parent)
    try:
        fd = c.leaf(parent, path.name)
        try:
            before = os.fstat(fd)
            c.need(before.st_size <= limit, 'artifact_size_limit')
            if protected:c.need(before.st_uid == 0 and before.st_mode & 0o022 == 0, 'artifact_unprotected')
            h = hashlib.sha256();length = 0;first = b''
            while True:
                data = os.read(fd, min(65536, limit+1-length))
                if not data:break
                if not first:first = data[:4]
                length += len(data);c.need(length <= limit, 'artifact_size_limit');h.update(data)
            sig = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns, s.st_nlink, s.st_mode, s.st_uid)
            c.need(sig(before) == sig(os.fstat(fd)) == sig(os.stat(path.name, dir_fd=parent, follow_symlinks=False)),
                   'artifact_changed')
            with_fd = c.directory(path.parent)
            try:c.need(os.fstat(with_fd).st_ino == os.fstat(parent).st_ino and
                       os.fstat(with_fd).st_dev == os.fstat(parent).st_dev, 'artifact_directory_changed')
            finally:os.close(with_fd)
            if magic is not None:c.need(first == magic, 'root_image_format_invalid')
            return h.hexdigest()
        finally:os.close(fd)
    finally:os.close(parent)


def protected_directory(path):
    fd = c.directory(path)
    try:
        s = os.fstat(fd);c.need(s.st_uid == 0 and s.st_mode & 0o022 == 0, 'directory_unprotected')
    finally:os.close(fd)


def bundle_manifest(package=None, *, protected=False):
    package = Path(package or Path(__file__).parent).absolute()
    if protected:
        for directory in (package, package/'fixtures', package/'unit-templates', package/'unit-templates/s6d'):
            protected_directory(directory)
    return dict(kind='isolation_operator_bundle', version=1,
                files=[dict(path=name, sha256=file_hash(package/name, protected=protected)) for name in BUNDLE_FILES])


class LocalSystem:
    """Only fixed read-only commands. No generic command, shell or action API."""
    def query(self, kind, unit=None):
        if kind == 'manager':args = ['show', '--no-pager', '--property=Version,Features']
        elif kind == 'units':
            args = ['list-units', '--all', '--plain', '--no-legend', '--no-pager', 'llm-casting-isolation-probe@*.service']
        elif kind == 'unit_files':
            # A filtered empty result exits 1 on systemd 255. Require a successful
            # complete metadata listing instead; never interpret an error as absence.
            args = ['list-unit-files','--full','--no-legend','--no-pager']
        elif kind == 'unit':
            c.need(type(unit) is str and unit == unit_for(unit.removeprefix('llm-casting-isolation-probe@').removesuffix('.service')),
                   'unit_invalid')
            args = ['show', '--no-pager', '--property='+','.join(UNIT_FIELDS), unit]
        else:raise c.Invalid('read_only_query_required')
        result = subprocess.run(['/usr/bin/systemctl', *args], stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=5,
                                env={'PATH':'/usr/bin:/bin', 'LANG':'C.UTF-8'}, check=False)
        c.need(result.returncode == 0 and len(result.stdout) <= 65536, 'manager_unavailable')
        return result.stdout.decode('utf-8')

    def absent(self, path):
        path = Path(path);c.need(path.is_absolute() and '..' not in path.parts, 'path_invalid')
        # Inspect each existing component without following symlinks. Ownership of
        # foreign parent directories is deliberately not prescribed or changed.
        current = Path('/')
        for part in path.parts[1:]:
            current /= part
            try:s = current.lstat()
            except FileNotFoundError:return True
            c.need(not stat.S_ISLNK(s.st_mode), 'path_symlink')
        return False

    def account(self):
        try:user = pwd.getpwnam(IDENTITY)
        except KeyError:user = None
        try:group = grp.getgrnam(IDENTITY)
        except KeyError:group = None
        if user is None and group is None:return None
        c.need(user is not None and group is not None, 'partial_identity_collision')
        return dict(uid=user.pw_uid, gid=user.pw_gid, group_gid=group.gr_gid,
                    groups=sorted(set(os.getgrouplist(IDENTITY, user.pw_gid))),
                    shell=user.pw_shell, home=user.pw_dir,
                    uid_aliases=sum(x.pw_uid == user.pw_uid for x in pwd.getpwall()),
                    gid_aliases=sum(x.gr_gid == group.gr_gid for x in grp.getgrall()))

    def manager(self):return properties(self.query('manager'))
    def units(self):return self.query('units').splitlines()
    def unit_files(self):
        return [line.split()[0] for line in self.query('unit_files').splitlines()
                if line.split() and line.split()[0].startswith('llm-casting-isolation-probe@')]
    def unit(self, name):return properties(self.query('unit', name))
    def controllers(self):return Path('/sys/fs/cgroup/cgroup.controllers').read_text().split()
    def euid(self):return os.geteuid()
    def host_mount_inode(self):return os.stat('/proc/self/ns/mnt').st_ino

    def uid_processes(self, uid):
        """UID metadata only; no cmdline/environment/executable/configuration reads."""
        found = [];unknown = False
        for directory in Path('/proc').iterdir():
            if not directory.name.isdecimal():continue
            try:
                with (directory/'status').open() as stream:
                    lines = stream.read(8193).splitlines()
                ids = next(line.split()[1:] for line in lines if line.startswith('Uid:'))
                if uid in map(int, ids):found.append(int(directory.name))
            except (FileNotFoundError, ProcessLookupError):continue
            except (OSError, ValueError, StopIteration):unknown = True
        c.need(not unknown and len(found) <= 64, 'process_inventory_incomplete')
        return sorted(found)


def validate_account(account, profile):
    c.need(type(account) is dict, 'test_identity_missing')
    c.need(type(profile) is dict, 'profile_missing')
    c.need(account['uid'] == profile['expected']['uid'] > 0 and
           account['gid'] == account['group_gid'] == profile['expected']['gid'] > 0, 'test_identity_mismatch')
    c.need(set(account['groups']) <= {account['gid']} and account['uid_aliases'] == account['gid_aliases'] == 1,
           'privileged_or_ambiguous_identity')
    c.need(account['shell'] in ('/usr/sbin/nologin', '/sbin/nologin', '/bin/false') and
           account['home'] == '/nonexistent', 'test_identity_login_enabled')


def validate_approval(record, test_id, bundle_pin, profile_pin, image_pin, *, at=None):
    c.obj(record, ('kind', 'version', 'approval_id', 'test_id', 'scope', 'issued_at', 'expires_at',
                   'bundle_sha256', 'profile_sha256', 'image_sha256'))
    c.need(record['kind'] == 'isolation_operator_declaration' and type(record['version']) is int and record['version'] == 1,
           'approval_version_invalid')
    c.identifier(record['approval_id'])
    c.need(record['test_id'] == test_id and record['scope'] == 'one_synthetic_test_only', 'approval_scope_invalid')
    for key, pin in (('bundle_sha256',bundle_pin),('profile_sha256',profile_pin),('image_sha256',image_pin)):
        c.hash_value(pin);c.need(record[key] == pin, 'approval_binding_invalid')
    current = c.timestamp(at or c.now());issued = c.timestamp(record['issued_at']);expires = c.timestamp(record['expires_at'])
    c.need(issued <= current < expires and expires-issued <= timedelta(hours=1), 'approval_expired_or_invalid')
    return record  # A declaration never authorizes a command in this program.


def inspect(test_id, bundle_pin, *, mode='plan', profile_pin=None, image_pin=None, saved_profile=None,
            system=None, package=None):
    c.identifier(test_id);c.hash_value(bundle_pin)
    c.need(mode in ('plan','prepared','cleanup'), 'mode_invalid')
    system = system or LocalSystem();rows = [];root = STATE/test_id;unit = unit_for(test_id)
    def check(name, action):
        try:
            action();rows.append(dict(check_id=name,status='passed',reason='read_only_check'))
        except (c.Invalid, OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
            reason = str(exc) if type(exc) is c.Invalid else 'unavailable_or_incomplete'
            rows.append(dict(check_id=name,status='blocked',reason=reason))
    def required(ok, code):c.need(ok,code)
    check('bundle_hash',lambda:required(c.digest(bundle_manifest(package)) == bundle_pin,'bundle_hash_mismatch'))
    check('systemd',lambda:required(system.manager().get('Version','').startswith('255.'),'systemd_version_unverified'))
    check('seccomp_build_support',lambda:required('+SECCOMP' in system.manager().get('Features','').split(),
                                                 'seccomp_support_unverified'))
    check('cgroup_controllers',lambda:required({'cpu','memory','pids'} <= set(system.controllers()),'controllers_missing'))
    check('operator_rights',lambda:required(system.euid() == 0,'administrative_rights_required_for_later_phase'))
    if mode in ('plan','cleanup'):
        for name,path in (('install_root_absent',INSTALL),('state_root_absent',STATE)):
            check(name,lambda path=path:required(system.absent(path),'path_collision'))
        check('identity_absent',lambda:required(system.account() is None,'identity_collision'))
        check('no_test_units',lambda:required(not system.units(),'unit_collision_or_activity'))
        check('no_test_unit_files',lambda:required(not system.unit_files(),'static_unit_collision'))
        for index,directory in enumerate(UNIT_DIRS):
            for suffix in (TEMPLATE,unit,unit+'.d',TEMPLATE+'.d'):
                check('unit_path_'+str(index)+'_'+suffix,
                      lambda directory=directory,suffix=suffix:required(system.absent(directory/suffix),'unit_path_collision'))
    profile = None
    if mode == 'prepared':
        check('install_root_protected',lambda:protected_directory(INSTALL))
        check('state_root_protected',lambda:protected_directory(STATE))
        check('test_root_protected',lambda:protected_directory(root))
        check('installed_bundle',lambda:required(c.digest(bundle_manifest(INSTALL/'package',protected=True)) == bundle_pin,
                                                'installed_bundle_mismatch'))
        def load_profile():
            nonlocal profile
            c.hash_value(profile_pin);file_hash(root/'profile.json',protected=True)
            candidate = c.validate_profile(c.read(root/'profile.json'),profile_pin)
            c.need(candidate['test_id'] == test_id and candidate['expected']['host_mount_namespace_inode'] is not None,
                   'profile_not_resolved')
            c.need(candidate['expected']['host_mount_namespace_inode'] == system.host_mount_inode(),
                   'host_mount_namespace_changed')
            c.need(candidate['limits']==dict(memory_max_bytes=134217728,cpu_quota_usec_per_sec=250000,
                                             tasks_max=16,runtime_seconds=15),'template_limits_mismatch')
            profile = candidate
        check('profile',load_profile)
        check('identity',lambda:validate_account(system.account(),profile))
        def marker():
            file_hash(root/'marker.json',protected=True)
            expected = dict(kind='synthetic_isolation_test_root',profile_version=1,test_id=test_id,profile_sha256=profile_pin)
            c.need(c.canonical(c.read(root/'marker.json')) == c.canonical(expected),'marker_mismatch')
        check('marker',marker)
        check('root_image',lambda:required(file_hash(root/'rootfs.squashfs',protected=True,limit=536870912,magic=b'hsqs') == image_pin,
                                         'root_image_hash_mismatch'))
        def canaries():
            c.need(profile is not None,'profile_missing')
            for role in ('reference','outside','other'):
                protected_directory(root/role)
                expected = ('llm-casting-isolation-canary:'+role+':'+test_id+'\n').encode('ascii')
                c.need(file_hash(root/role/'canary.txt',protected=True) == hashlib.sha256(expected).hexdigest(),
                       'canary_hash_mismatch')
            fd = c.directory(root/'output')
            try:
                info = os.fstat(fd);c.need(info.st_uid == profile['expected']['uid'] and
                    info.st_gid == profile['expected']['gid'] and info.st_mode & 0o077 == 0,'output_ownership_invalid')
                c.need(not os.listdir(fd),'output_not_fresh')
            finally:os.close(fd)
        check('synthetic_fixture',canaries)
        def declaration():
            file_hash(root/'approval.json',protected=True)
            validate_approval(c.read(root/'approval.json'),test_id,bundle_pin,profile_pin,image_pin)
        check('operator_declaration',declaration)
        check('no_running_test_units',lambda:required(not system.units(),'existing_test_activity'))
        check('no_test_identity_processes',lambda:required(profile is not None and
              not system.uid_processes(profile['expected']['uid']),'existing_test_identity_work'))
        def installed_unit():
            source = Path(package or Path(__file__).parent)/'unit-templates/s6d'/TEMPLATE
            c.need(file_hash(UNIT_DIRS[0]/TEMPLATE,protected=True) == file_hash(source),'installed_unit_mismatch')
            c.need(all(system.absent(d/TEMPLATE) and system.absent(d/unit) and system.absent(d/(unit+'.d'))
                       and system.absent(d/(TEMPLATE+'.d'))
                       for d in UNIT_DIRS[1:]),'runtime_or_vendor_unit_collision')
            c.need(system.absent(UNIT_DIRS[0]/unit) and system.absent(UNIT_DIRS[0]/(TEMPLATE+'.d')),
                   'unexpected_unit_override')
            folder = UNIT_DIRS[0]/(unit+'.d');protected_directory(folder)
            c.need(set(os.listdir(folder)) == {'10-profile.conf'},'unexpected_instance_dropin')
            expected = '[Service]\nEnvironment=LLM_CASTING_PROFILE_SHA256='+profile_pin+'\n'
            c.need(file_hash(folder/'10-profile.conf',protected=True) == hashlib.sha256(expected.encode()).hexdigest(),
                   'profile_dropin_mismatch')
        check('installed_unit',installed_unit)
        check('only_declared_unit_file',lambda:required(set(system.unit_files())=={TEMPLATE},'unexpected_static_test_unit'))
    if mode == 'cleanup':
        def cleanup_processes():
            c.need(saved_profile is not None,'saved_profile_required')
            profile = c.validate_profile(c.read(saved_profile),profile_pin)
            c.need(profile['test_id'] == test_id,'cleanup_test_identity_mismatch')
            c.need(not system.uid_processes(profile['expected']['uid']),'test_processes_remain')
        check('no_saved_test_uid_processes',cleanup_processes)
    if mode == 'plan':
        rows.append(dict(check_id='operator_declaration',status='blocked',reason='separate_operator_decision_pending'))
        for name,reason in (('prepared_fixture','phase2_installation_not_performed'),
                            ('root_image_ready','reviewed_root_image_required'),
                            ('protected_bundle_ready','protected_installation_required')):
            rows.append(dict(check_id=name,status='blocked',reason=reason))
    return dict(kind='isolation_operator_preflight',version=1,test_id=test_id,mode=mode,observed_at=c.now(),
                bundle_sha256=bundle_pin,profile_sha256=profile_pin,image_sha256=image_pin,unit=unit,checks=rows,
                preflight_checks_passed=all(x['status']=='passed' for x in rows),
                operator_decision_required=True,phase2_execution_available=False,isolation_verified=False,
                manual_reviews_required=['uid_file_ownership_inventory','sudo_and_other_privilege_policies',
                                         'trusted_image_contents_and_bootability','effective_local_network_boundaries'])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inventory',action='store_true')
    parser.add_argument('--test-id')
    parser.add_argument('--mode',choices=('plan','prepared','cleanup'),default='plan')
    parser.add_argument('--expected-bundle-sha256')
    parser.add_argument('--expected-profile-sha256')
    parser.add_argument('--expected-image-sha256')
    parser.add_argument('--saved-profile',type=Path)
    args = parser.parse_args(argv)
    try:
        if args.inventory:
            manifest=bundle_manifest();print(c.canonical(dict(manifest=manifest,bundle_sha256=c.digest(manifest))).decode());return 0
        value=inspect(args.test_id,args.expected_bundle_sha256,mode=args.mode,
                      profile_pin=args.expected_profile_sha256,image_pin=args.expected_image_sha256,saved_profile=args.saved_profile)
        print(c.canonical(value).decode());return 0 if value['preflight_checks_passed'] else 1
    except (c.Invalid,OSError,ValueError,TypeError):
        print('{"error":"operator_preflight_invalid","phase2_execution_available":false,"isolation_verified":false}')
        return 2


if __name__=='__main__':
    raise SystemExit(main())
