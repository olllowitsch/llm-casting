#!/usr/bin/env python3
"""One fixed synthetic child. No sockets, allocation loop, grandchild or shell."""
import argparse
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import contract as c
import probe


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', required=True, type=Path)
    parser.add_argument('--expected-profile-sha256', required=True)
    parser.add_argument('--test-root', required=True, type=Path)
    args = parser.parse_args()
    profile = c.validate_profile(c.read(args.profile), args.expected_profile_sha256)
    observation = probe.local_observations();probe.guard(profile, observation)
    root = probe.approved_root(args.test_root, profile);os.close(root)
    print(c.canonical(dict(pid=os.getpid(), parent_pid=os.getppid(),
                           cgroup=observation['identity']['cgroup'])).decode(), flush=True)
    time.sleep(8)


if __name__ == '__main__':
    main()
