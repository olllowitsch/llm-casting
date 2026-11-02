#!/usr/bin/env python3
"""S4 performance CLI. validate/dry-run/inspect never contact Ollama."""
import json
import os
from pathlib import Path
import sys

import benchmark as legacy
import definitions as d
import planning as p
import workspaces as w
import ollama_adapter as a


def main(argv=None):
    try:
        parser=w._Parser(description=__doc__)
        sub=parser.add_subparsers(dest='command',required=True)
        sub.add_parser('build-info')
        for name in ('validate','dry-run','run','inspect','resume'):
            cmd=sub.add_parser(name)
            for key in ('plan','competition','rubric'):
                cmd.add_argument('--'+key,type=Path,required=True)
            cmd.add_argument('--expected-plan-sha256',required=True)
            cmd.add_argument('--assets',type=Path);cmd.add_argument('--rubric-assets',type=Path)
            if name in ('run','inspect','resume'):
                cmd.add_argument('--root',type=Path,required=True)
                cmd.add_argument('--expected-head')
                cmd.add_argument('--output',type=Path)
            if name in ('run','resume'):cmd.add_argument('--api-url')
        args=parser.parse_args(argv)
        if args.command=='build-info':
            manifest=a.build_manifest()
            obj=dict(ok=True,engine=dict(version=a.VERSION,source_sha256=d.content_sha256(manifest)),
                     adapter_version=a.ADAPTER_VERSION,manifest=manifest)
        else:
            plan=p.validate_run_plan(d.load_json(args.plan),d.load_json(args.competition),d.load_json(args.rubric),
                asset_root=args.assets,rubric_asset_root=args.rubric_assets,expected_sha256=args.expected_plan_sha256)
            if args.command in ('validate','dry-run'):
                a.validate_execution_plan(plan)
                obj=dict(ok=True,plan_sha256=plan.sha256,planned_slots=len(p.measurement_slots(plan)),
                         http_performed=False,agent_execution=False)
            else:
                # Create no client/HTTP activity in inspect. No model calls during CLI setup.
                with w.WorkspaceStore(args.root,create=args.command=='run') as store:
                    if args.command=='run':
                        a.validate_execution_plan(plan)
                        if args.expected_head:store.validate_journal(plan,expected_head=args.expected_head)
                        store.register_run(plan,asset_root=args.assets,rubric_asset_root=args.rubric_assets)
                    coordinator=a.RunCoordinator(store,plan)
                    if args.command=='inspect':report=coordinator.inspect(expected_head=args.expected_head)
                    else:
                        url=a.api_url(args.api_url if args.api_url is not None else
                                      os.environ.get('OLLAMA_API_URL',legacy.DEFAULT_API_URL))
                        adapter=a.OllamaAdapter(a.OllamaHTTPClient(url,plan.as_dict()['limits']['request_timeout_seconds']))
                        report=coordinator.run(adapter,resume=args.command=='resume',expected_head=args.expected_head,
                            progress=lambda value:print(json.dumps(dict(progress=value)),file=sys.stderr,flush=True))
                    if args.output:
                        p.write_json_exclusive(args.output,report['result'],protected_roots=[store.root]+[
                            x for x in (args.assets,args.rubric_assets) if x])
                    obj=dict(ok=True,**report)
        print(d.canonical_json_bytes(obj).decode('utf-8'))
        if args.command in ('run','resume'):
            return 0 if obj['result']['status']=='completed' and obj['result']['progress']['failed_slots']==0 else 1
        return 0
    except KeyboardInterrupt:
        print(json.dumps(dict(ok=False,code='execution_outcome_unknown')),file=sys.stderr);return 130
    except d.DefinitionError as error:
        print(json.dumps(dict(ok=False,code=error.code,location=error.location)),file=sys.stderr);return 2
    except (OSError,ValueError,TypeError,KeyError):
        print(json.dumps(dict(ok=False,code='execution_archive_invalid')),file=sys.stderr);return 2


if __name__=='__main__':
    sys.exit(main())
