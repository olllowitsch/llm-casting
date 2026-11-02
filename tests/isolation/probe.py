#!/usr/bin/env python3
"""S6-C synthetic probe. Active operations require the exact dedicated test unit.

No service control, network access, model calls, arbitrary commands or installation.
"""
import argparse
import errno
import os
from pathlib import Path
import re
import select
import stat
import subprocess
import sys
import uuid

try:
    from . import contract as c
except ImportError:
    import contract as c


def _text(path):
    path = Path(path);parent = c.directory(path.parent)
    try:
        fd = c.leaf(parent, path.name)
        try:
            data = os.read(fd, 8193);c.need(len(data) <= 8192, 'metadata_limit')
            return data.decode('ascii').strip()
        finally:os.close(fd)
    finally:os.close(parent)


def local_observations():
    status = {}
    try:
        status = dict(line.split(':', 1) for line in _text('/proc/'+str(os.getpid())+'/status').splitlines() if ':' in line)
    except (OSError, ValueError):pass
    def number(key, base=10):
        try:return int(status[key].strip(), base)
        except (KeyError, ValueError):return None
    try:
        entries = [line.split('::', 1)[1] for line in _text('/proc/'+str(os.getpid())+'/cgroup').splitlines() if line.startswith('0::')]
        group = entries[0] if len(entries) == 1 else None
    except (OSError, ValueError):group = None
    try:namespace = os.stat('/proc/self/ns/mnt').st_ino
    except OSError:namespace = None
    resources = dict(memory_max_bytes=None, cpu_quota_usec_per_sec=None, tasks_max=None)
    # Only the dedicated unit's public cgroup metadata, never arbitrary paths.
    if group and re.fullmatch(r'/system.slice/llm-casting-isolation-probe@[0-9a-f-]{36}\.service', group):
        base = '/sys/fs/cgroup'+group
        for key, name in (('memory_max_bytes', 'memory.max'), ('tasks_max', 'pids.max')):
            try:resources[key] = int(_text(base+'/'+name))
            except (OSError, ValueError):pass
        try:
            quota, period = map(int, _text(base+'/cpu.max').split())
            if period > 0 and quota > 0 and quota*1000000 % period == 0:
                resources['cpu_quota_usec_per_sec'] = quota*1000000//period
        except (OSError, ValueError):pass
    return dict(identity=dict(uid=os.geteuid(), gid=os.getegid(), groups=sorted(set(os.getgroups())),
                cap_eff=number('CapEff', 16), no_new_privileges=number('NoNewPrivs'),
                mount_namespace_inode=namespace, unit=group.rsplit('/', 1)[-1] if group else None,
                cgroup=group, invocation_id=os.environ.get('INVOCATION_ID')),
                filesystem={key: 'not_verified' for key in c.FS}, resources=resources,
                child=dict(state='not_run', pid=None, parent_pid=None, cgroup=None, alive_at_observation=None),
                network={key: 'not_verified' for key in c.NETWORK}, termination='not_verified')


def guard(profile, observations):
    """No JSON enable/force claims: compare current kernel observations first."""
    c.validate_profile(profile, c.digest(profile))
    c.validate_observations(observations)
    i = observations['identity'];e = profile['expected']
    c.need(i['uid'] > 0 and i['uid'] == e['uid'] and i['gid'] == e['gid'] and set(i['groups']) <= {e['gid']},
           'test_identity_required')
    c.need(i['unit'] == e['unit'] and i['cgroup'] == e['cgroup'] and i['invocation_id'] is not None,
           'dedicated_test_unit_required')
    c.need(i['cap_eff'] == 0 and i['no_new_privileges'] == 1, 'test_process_safety_required')
    c.need(i['mount_namespace_inode'] is not None and e['host_mount_namespace_inode'] is not None and
           i['mount_namespace_inode'] != e['host_mount_namespace_inode'], 'private_mount_namespace_required')
    c.need(all(observations['resources'][key] == profile['limits'][key]
               for key in observations['resources']), 'bounded_test_resources_required')


def approved_root(path, profile):
    fd = c.directory(path)
    try:
        info = os.fstat(fd)
        c.need(info.st_uid == 0 and not info.st_mode & 0o022, 'operator_owned_test_root_required')
        marker_fd = c.leaf(fd, 'marker.json')
        try:
            s = os.fstat(marker_fd)
            c.need(s.st_uid == 0 and not s.st_mode & 0o022, 'operator_marker_required')
            marker = c.parse(os.read(marker_fd, c.MAX_BYTES+1))
        finally:os.close(marker_fd)
        c.need(c.canonical(marker) == c.canonical(dict(kind='synthetic_isolation_test_root', profile_version=c.VERSION,
               test_id=profile['test_id'], profile_sha256=c.digest(profile))), 'test_root_binding_invalid')
        return fd
    except BaseException:
        os.close(fd);raise


def canary(profile, role):
    return ('llm-casting-isolation-canary:'+role+':'+profile['test_id']+'\n').encode('ascii')


def _area(root, name):
    return os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root)


def _access(root, area, *, write=False, expected=None):
    try:
        parent = _area(root, area)
    except OSError:
        return 'not_verified'  # Cannot confirm the canary exists behind an inaccessible directory.
    try:
        try:fd = c.leaf(parent, 'canary.txt', os.O_WRONLY if write else os.O_RDONLY)
        except OSError as exc:
            return 'denied' if exc.errno in (errno.EACCES, errno.EPERM, errno.EROFS) else 'not_verified'
        try:
            if write:return 'allowed'  # No truncation and no write to a negative canary.
            data = os.read(fd, 256)
            return 'matched' if data == expected else 'mismatch'
        finally:os.close(fd)
    finally:os.close(parent)


def filesystem(root, profile):
    """Only fixed leaf names under a pinned synthetic root. Never follow links."""
    result = {key: 'not_verified' for key in c.FS}
    result['reference_read'] = _access(root, 'reference', expected=canary(profile, 'reference'))
    result['reference_write'] = _access(root, 'reference', write=True)
    result['outside_write'] = _access(root, 'outside', write=True)
    other = _access(root, 'other', expected=canary(profile, 'other'))
    result['other_read'] = 'allowed' if other == 'matched' else other
    output = _area(root, 'output');name = 'probe-'+str(uuid.uuid4())+'.tmp'
    owned = None
    try:
        try:
            fd = os.open(name, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=output)
            owned = os.fstat(fd)
            try:
                data = canary(profile, 'output');os.write(fd, data);os.lseek(fd, 0, os.SEEK_SET)
                result['output_write'] = 'allowed' if os.read(fd, 256) == data else 'mismatch'
            finally:os.close(fd)
        except OSError as exc:
            result['output_write'] = 'denied' if exc.errno in (errno.EACCES, errno.EPERM, errno.EROFS) else 'not_verified'
        finally:
            if owned is not None:
                current = os.stat(name, dir_fd=output, follow_symlinks=False)
                c.need((current.st_dev, current.st_ino) == (owned.st_dev, owned.st_ino), 'scratch_file_changed')
                os.unlink(name, dir_fd=output)
        # Only a verified harmless reference canary can be a hardlink source.
        if result['reference_read'] == 'matched':
            reference = _area(root, 'reference');link = 'hardlink-'+str(uuid.uuid4())
            try:
                source = c.leaf(reference, 'canary.txt')
                try:signature = os.fstat(source)
                finally:os.close(source)
                try:
                    os.link('canary.txt', link, src_dir_fd=reference, dst_dir_fd=output, follow_symlinks=False)
                except OSError as exc:
                    result['hardlink'] = 'denied' if exc.errno in (errno.EXDEV, errno.EPERM, errno.EACCES, errno.EROFS) else 'not_verified'
                else:
                    current = os.stat(link, dir_fd=output, follow_symlinks=False)
                    c.need((current.st_dev, current.st_ino) == (signature.st_dev, signature.st_ino), 'scratch_file_changed')
                    result['hardlink'] = 'allowed';os.unlink(link, dir_fd=output)
            finally:os.close(reference)
    finally:os.close(output)
    return result


def child_fixture(args, profile, observations):
    """At most one fixed, self-terminating child; never accepts an executable/command."""
    current = local_observations()
    guard(profile, current)
    c.need(current['identity'] == observations['identity'] and current['resources'] == observations['resources'],
           'live_test_context_changed')
    root = approved_root(args.test_root, profile);os.close(root)
    command = [sys.executable, '-E', '-s', '-B', str(Path(__file__).parent/'fixtures/child.py'),
               '--profile', str(args.profile), '--expected-profile-sha256', args.expected_profile_sha256,
               '--test-root', str(args.test_root)]
    child = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                             env={'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8',
                                  'INVOCATION_ID': observations['identity']['invocation_id']}, close_fds=True)
    try:
        ready, _, _ = select.select([child.stdout], [], [], 2)
        raw = os.read(child.stdout.fileno(), 4097) if ready else b''
        try:
            ack = c.parse(raw);c.obj(ack, ('pid', 'parent_pid', 'cgroup'))
            c.need(ack['pid'] == child.pid and ack['parent_pid'] == os.getpid(), 'child_ack_invalid')
            c.need(type(ack['cgroup']) is str, 'child_ack_invalid')
        except (c.Invalid, ValueError):
            info = dict(state='lost_early', pid=child.pid, parent_pid=os.getpid(),
                        cgroup='', alive_at_observation=False)
        else:
            alive = child.poll() is None
            info = dict(state='observed' if alive else 'lost_early', pid=child.pid,
                        parent_pid=ack['parent_pid'], cgroup=ack['cgroup'], alive_at_observation=alive)
        observations['child'] = info
        # Publish before the independent operator-controlled tree-stop test.
        print(c.canonical(c.make_report(profile, observations, stage='pre_stop')).decode(), flush=True)
        return info
    finally:
        # The protected fixture exits itself after eight seconds. No arbitrary kill API.
        # A host-side tree-stop receipt remains required regardless of this wait.
        try:child.wait(timeout=10)
        finally:child.stdout.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', required=True, type=Path)
    parser.add_argument('--expected-profile-sha256', required=True)
    parser.add_argument('--test-root', required=True, type=Path)
    parser.add_argument('--with-child', action='store_true')
    args = parser.parse_args(argv)
    try:
        profile = c.validate_profile(c.read(args.profile), args.expected_profile_sha256)
        observations = local_observations()
        try:
            guard(profile, observations)  # Before any synthetic filesystem action or child startup.
        except c.Invalid:
            print(c.canonical(c.make_report(profile, observations, stage='gate_rejected')).decode())
            return 2
        root = approved_root(args.test_root, profile)
        try:observations['filesystem'] = filesystem(root, profile)
        finally:os.close(root)
        if args.with_child:
            observations['child'] = child_fixture(args, profile, observations)
        else:
            report = c.make_report(profile, observations)
            print(c.canonical(report).decode('utf-8'))
        return 1  # Preparation v1 never grants full isolation approval.
    except (c.Invalid, OSError, ValueError, subprocess.SubprocessError):
        print('{"error":"isolation_probe_not_verified","isolation_verified":false}')
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
