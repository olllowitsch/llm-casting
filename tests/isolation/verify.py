#!/usr/bin/env python3
"""Offline consistency verification, never authentication or OS acceptance.

Read-only; prints JSON to stdout. No service manager calls or process startup.
"""
import argparse
from pathlib import Path

try:
    from . import contract as c
except ImportError:
    import contract as c


def verify(profile, report, expected_profile_sha256, expected_report_sha256):
    checked = c.validate_report(report, profile, expected_profile_sha256, expected_report_sha256)
    return dict(kind='isolation_test_verification', profile_version=c.VERSION,
                profile_sha256=c.digest(profile), report_sha256=c.digest(checked),
                test_id=profile['test_id'], report_id=checked['report_id'],
                consistency_verified=True, isolation_verified=False,
                overall_status=checked['overall_status'], missing_evidence=checked['missing_evidence'],
                warning='json_checksums_are_not_authenticated_host_evidence')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', required=True, type=Path)
    parser.add_argument('--report', required=True, type=Path)
    parser.add_argument('--expected-profile-sha256', required=True)
    parser.add_argument('--expected-report-sha256', required=True)
    args = parser.parse_args(argv)
    try:
        value = verify(c.read(args.profile), c.read(args.report), args.expected_profile_sha256,
                       args.expected_report_sha256)
        print(c.canonical(value).decode('utf-8'))
        return 1  # A consistent partial report is not a successful isolation test.
    except (c.Invalid, OSError, ValueError):
        print('{"error":"isolation_report_invalid","isolation_verified":false}')
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
