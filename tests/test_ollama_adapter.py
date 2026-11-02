"""S4 fake-only integration. Every test disables HTTP/network and process launch."""
import contextlib
import copy
import io
import json
import os
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch
import urllib.error
import uuid

import benchmark as legacy
import definitions as d
import planning as p
import workspaces as w
import ollama_adapter as a
import casting

ROOT=Path(__file__).resolve().parents[1]
S1=ROOT/'tests/fixtures/definitions/valid'
S2=ROOT/'tests/fixtures/planning'
DIGEST='a'*64


class FakeOllama:
    base_url='http://ollama.invalid:11434'
    timeout=300
    def __init__(self):
        self.calls=[];self.digest=DIGEST;self.present=True;self.fail=None;self.generations=0
        self.modify=None;self.before=None
    def request(self,endpoint,payload=None):
        if self.before:self.before(endpoint,payload)
        self.calls.append((endpoint,copy.deepcopy(payload),self.timeout))
        if endpoint=='/api/tags':
            return dict(models=[dict(name='example-model',digest=self.digest)] if self.present else [])
        if endpoint=='/api/ps':return dict(models=[dict(name='example-model',digest=self.digest,size_vram=42)])
        self.generations+=1
        if self.fail and self.generations==self.fail[0]:raise self.fail[1]
        response=dict(model='example-model',response='synthetic response',done=True,
                      total_duration=4_000_000_000,load_duration=100,prompt_eval_count=10,
                      prompt_eval_duration=1_000_000_000,eval_count=20,eval_duration=2_000_000_000)
        if self.modify:response=self.modify(response,self.generations)
        return response


class Case(unittest.TestCase):
    def setUp(self):
        # All actual transport/process functions are forbidden in this complete S4 suite.
        for target in ('urllib.request.urlopen','socket.socket','socket.create_connection','subprocess.Popen'):
            guard=patch(target,side_effect=AssertionError('external operation forbidden'))
            guard.start();self.addCleanup(guard.stop)
        self.tmp=tempfile.TemporaryDirectory(dir=ROOT);self.addCleanup(self.tmp.cleanup)
        self.folder=Path(self.tmp.name);self.root=self.folder/'casting.local'
        self.c=d.load_json(S1/'competition.json');self.r=d.load_json(S1/'rubric.json')
        self.config=d.load_json(S2/'config.json')
        self.config['run_id']=str(uuid.uuid4())
        self.config['engine']=dict(version=a.VERSION,source_sha256=d.content_sha256(a.build_manifest()))
        self.config['participants'][0]['adapter_version']=a.ADAPTER_VERSION
        self.config['participants'][0]['model']['revision_digest']=DIGEST
        self.config['preparation']=dict(unload_before=False,preload=False,warmup_count=0)
        self.plan=self.make_plan();self.client=FakeOllama()
    def make_plan(self):
        return p.create_run_plan(self.c,self.r,self.config,asset_root=S1/'assets')
    def store(self):
        store=w.WorkspaceStore(self.root).__enter__();self.addCleanup(store.__exit__)
        store.register_run(self.plan,asset_root=S1/'assets');return store
    def run_plan(self):
        store=self.store();coordinator=a.RunCoordinator(store,self.plan)
        return store,coordinator,coordinator.run(a.OllamaAdapter(self.client))
    def fails(self,code,fn,*args,**kwargs):
        with self.assertRaises(d.DefinitionError) as error:fn(*args,**kwargs)
        if code:self.assertEqual(error.exception.code,code)
        return error.exception
    def snap(self):
        return {str(f.relative_to(self.root)):f.read_bytes() for f in self.root.rglob('*') if f.is_file()}
    def args(self,command):
        planfile=self.folder/'plan.json';planfile.write_bytes(p.serialize_run_plan(self.plan))
        return [command,'--plan',str(planfile),'--competition',str(S1/'competition.json'),
                '--rubric',str(S1/'rubric.json'),'--assets',str(S1/'assets'),
                '--expected-plan-sha256',self.plan.sha256]


class HttpBridgeTests(Case):
    def test_exact_legacy_http_code_with_local_bounded_opener(self):
        client=a.OllamaHTTPClient(self.client.base_url,9)
        self.assertIs(client._legacy_request.__code__,legacy.Client.request.__code__)
        response=io.BytesIO(b'{"done":true}')
        with patch.object(client._opener,'open',return_value=response) as opened:
            self.assertEqual(client.request('/api/generate',dict(model='example-model')),dict(done=True))
        request=opened.call_args.args[0]
        self.assertEqual(request.full_url,self.client.base_url+'/api/generate')
        self.assertEqual(json.loads(request.data),dict(model='example-model'))
        self.assertEqual(opened.call_args.kwargs['timeout'],9)
        self.assertTrue(response.closed)

    def test_http_bridge_denies_unlisted_endpoint_before_send(self):
        client=a.OllamaHTTPClient(self.client.base_url,9)
        with patch.object(client._opener,'open',side_effect=AssertionError('must not send')):
            with self.assertRaises(a.RequestFailure) as error:client.request('/api/delete',{})
        self.assertEqual(error.exception.state,'not_sent')

    def test_response_read_is_bounded_and_unknown(self):
        client=a.OllamaHTTPClient(self.client.base_url,9)
        response=io.BytesIO(b'X'*(d.DEFAULT_LIMITS.max_json_bytes+10))
        with patch.object(client._opener,'open',return_value=response):
            with self.assertRaises(a.RequestFailure) as error:client.request('/api/generate',{})
        self.assertEqual(error.exception.code,'ollama_response_limit')
        self.assertEqual(error.exception.state,'unknown');self.assertTrue(response.closed)

    def test_redirect_is_never_followed(self):
        request=legacy.urllib.request.Request(self.client.base_url+'/api/generate')
        with self.assertRaises(urllib.error.HTTPError) as error:
            a._NoRedirect().redirect_request(request,None,302,'redirect',{},'https://other.invalid')
        self.assertEqual(a._failure(error.exception).state,'unknown')

    def test_environment_proxy_not_used(self):
        with patch.dict(os.environ,{'http_proxy':'http://proxy.invalid','https_proxy':'http://proxy.invalid'}):
            client=a.OllamaHTTPClient(self.client.base_url,9)
        self.assertTrue(all(not getattr(handler,'proxies',{}) for handler in client._opener.handlers))

    def test_legacy_http_error_cause_preserved_for_classification(self):
        client=a.OllamaHTTPClient(self.client.base_url,9)
        error=urllib.error.HTTPError(self.client.base_url,404,'synthetic',{},io.BytesIO(b'private error'))
        with patch.object(client._opener,'open',side_effect=error):
            with self.assertRaises(RuntimeError) as raised:client.request('/api/generate',{})
        self.assertIs(raised.exception.__cause__,error)
        self.assertEqual(a._failure(raised.exception).state,'completed')


class AdapterTests(Case):
    def test_success_result_s2_units_and_provenance(self):
        store,coordinator,report=self.run_plan();result=report['result']
        self.assertEqual(result['status'],'completed');self.assertEqual(result['progress']['successful_slots'],1)
        e=result['executions'][0]['execution'];m=e['metrics']
        self.assertEqual(m['tokens_per_second'],'10');self.assertEqual(m['prompt_tokens_per_second'],'10')
        self.assertEqual(m['eval_duration_ns'],2_000_000_000);self.assertGreaterEqual(m['wall_duration_ns'],0)
        self.assertEqual(e['provenance']['model_revision_digest'],DIGEST)
        self.assertEqual(e['provenance']['engine'],self.plan.as_dict()['engine'])
        self.assertTrue(e['artifacts']);self.assertEqual(e['provenance']['evidence'],[x['artifact_id'] for x in e['artifacts']])
        self.assertTrue(all(x['classification']=='private' for x in e['artifacts']))
        p.validate_result(result,self.plan);self.assertEqual(result['assessments'],[])
        self.assertEqual(report['server_quiescence'],'no_unresolved_own_request')
        self.assertFalse(report['agent_execution'])

    def test_multiple_participants_repetitions_order_no_parallel(self):
        second=copy.deepcopy(self.config['participants'][0]);second['participant_id']=str(uuid.uuid4())
        second['parameters']['threads']=8;second['parameters']['gpu_mode']='automatic'
        self.config['participants'].append(second);self.config['repetitions']=2;self.plan=self.make_plan()
        _,_,report=self.run_plan();calls=[b for ep,b,_ in self.client.calls if ep=='/api/generate']
        self.assertEqual([b['options']['num_thread'] for b in calls],[4,4,8,8])
        self.assertEqual(report['result']['progress']['successful_slots'],4)
        self.assertEqual(len({x['execution']['attempt_id'] for x in report['result']['executions']}),4)
        self.assertEqual([x['execution']['repetition'] for x in report['result']['executions']],[1,2,1,2])

    def test_preparation_sequence_and_shared_prompt(self):
        self.config['preparation']=dict(unload_before=True,preload=True,warmup_count=2);self.plan=self.make_plan()
        _,_,report=self.run_plan();calls=[b for ep,b,_ in self.client.calls if ep=='/api/generate']
        self.assertEqual(len(calls),5);self.assertEqual(calls[0]['keep_alive'],0)
        self.assertEqual([b['prompt'] for b in calls[:2]],['',''])
        self.assertEqual([b['prompt'] for b in calls[2:]],[self.c['prompt']['text']]*3)
        self.assertEqual(report['result']['executions'][0]['execution']['metrics']['eval_count'],20)

    def test_parameters_cpu_only(self):
        self.config['participants'][0]['parameters'].update(threads=7,num_ctx=8192,think=True,seed=11,
                                                          temperature='0.25',num_predict=23)
        self.plan=self.make_plan();self.run_plan()
        body=next(b for ep,b,_ in self.client.calls if ep=='/api/generate')
        self.assertEqual(body['options'],dict(num_thread=7,num_ctx=8192,seed=11,temperature=0.25,num_predict=23,num_gpu=0))
        self.assertIs(body['think'],True);self.assertIs(body['stream'],False)

    def test_automatic_omits_num_gpu_and_does_not_claim_gpu(self):
        self.config['participants'][0]['parameters']['gpu_mode']='automatic';self.plan=self.make_plan()
        _,_,report=self.run_plan()
        self.assertTrue(all('num_gpu' not in b['options'] for ep,b,_ in self.client.calls if ep=='/api/generate'))
        self.assertFalse(self.plan.as_dict()['participants'][0]['hardware']['verified'])
        self.assertNotIn('gpu_used',report['result']['executions'][0]['execution'])

    def test_legacy_payload_generate_digest_helpers_are_used(self):
        with patch.object(legacy,'payload',wraps=legacy.payload) as payload, patch.object(legacy,'generate',wraps=legacy.generate) as generate, patch.object(legacy,'digest_for',wraps=legacy.digest_for) as digest:
            self.run_plan()
            self.assertTrue(payload.called);self.assertTrue(generate.called);self.assertTrue(digest.called)

    def test_digest_mismatch_before_generate(self):
        self.client.digest='b'*64
        _,_,report=self.run_plan()
        self.assertEqual(self.client.generations,0);self.assertEqual(report['result']['status'],'failed')
        self.assertEqual(report['result']['executions'][0]['execution']['error']['code'],'model_digest_changed')

    def test_digest_drift_after_done_is_fatal(self):
        def drift(response,n):self.client.digest='c'*64;return response
        self.client.modify=drift
        self.config['repetitions']=2;self.plan=self.make_plan()
        _,_,report=self.run_plan();self.assertEqual(self.client.generations,1)
        self.assertEqual(report['result']['status'],'failed')
        self.assertEqual(report['result']['executions'][0]['execution']['status'],'failed')

    def test_model_missing_no_fallback(self):
        self.client.present=False
        _,coordinator,report=self.run_plan();self.assertEqual(self.client.generations,0)
        self.assertEqual(report['result']['executions'][0]['execution']['error']['code'],'model_not_found')
        self.fails('run_terminal',coordinator.run,a.OllamaAdapter(self.client),resume=True)

    def test_response_model_mismatch(self):
        self.client.modify=lambda r,n:dict(r,model='different-model')
        _,_,report=self.run_plan()
        self.assertEqual(report['result']['status'],'failed')
        self.assertEqual(report['result']['executions'][0]['execution']['error']['code'],'response_model_mismatch')

    def test_preparation_rejected_final_status_no_measurement(self):
        self.config['preparation']['preload']=True;self.plan=self.make_plan()
        http=urllib.error.HTTPError(self.client.base_url,404,'synthetic',None,None)
        exc=RuntimeError('opaque private error');exc.__cause__=http
        self.client.fail=(1,exc)
        _,_,report=self.run_plan();self.assertEqual(self.client.generations,1)
        e=report['result']['executions'][0]['execution']
        self.assertEqual(e['status'],'failed');self.assertEqual(e['error']['phase'],'preload')
        self.assertTrue(all(x is None for x in e['metrics'].values()))

    def test_warmup_timeout_blocks_measurement(self):
        self.config['preparation']['warmup_count']=1;self.plan=self.make_plan()
        self.client.fail=(1,TimeoutError('synthetic timeout'))
        _,_,report=self.run_plan();self.assertEqual(self.client.generations,1)
        e=report['result']['executions'][0]['execution']
        self.assertEqual(e['status'],'uncertain');self.assertEqual(e['error']['phase'],'warmup')

    def test_warmup_explicit_error_is_terminal_and_skips_measurement(self):
        self.config['preparation']['warmup_count']=1;self.plan=self.make_plan()
        self.client.modify=lambda r,n:dict(r,error='synthetic error')
        _,_,report=self.run_plan();e=report['result']['executions'][0]['execution']
        self.assertEqual(self.client.generations,1);self.assertEqual(e['status'],'failed')
        self.assertEqual(e['error']['phase'],'warmup');self.assertIsNotNone(e['finished_at'])

    def test_known_failed_measurement_continues_next_scheduled_slot(self):
        self.config['repetitions']=2;self.plan=self.make_plan()
        self.client.fail=(1,urllib.error.HTTPError('http://ollama.invalid',400,'synthetic',None,None))
        _,_,report=self.run_plan()
        self.assertEqual(self.client.generations,2)
        self.assertEqual(report['result']['status'],'completed')
        self.assertEqual(report['result']['progress']['successful_slots'],1)
        self.assertEqual(report['result']['progress']['failed_slots'],1)

    def test_measurement_wall_time_excludes_durable_archive_writes(self):
        store=self.store();coordinator=a.RunCoordinator(store,self.plan)
        clock=[0];publish=store._publish
        def slow_write(relative,data):
            result=publish(relative,data);clock[0]+=1000000
            return result
        self.client.before=lambda endpoint,body:clock.__setitem__(0,clock[0]+7)
        with patch.object(store,'_publish',slow_write),patch.object(a.time,'monotonic_ns',side_effect=lambda:clock[0]):
            report=coordinator.run(a.OllamaAdapter(self.client))
        self.assertEqual(report['result']['executions'][0]['execution']['metrics']['wall_duration_ns'],7)

    def test_missing_counts_and_zero_duration_are_unknown(self):
        self.client.modify=lambda r,n:dict(r,eval_count=None,eval_duration=0,prompt_eval_count=None)
        _,_,report=self.run_plan();metrics=report['result']['executions'][0]['execution']['metrics']
        self.assertIsNone(metrics['tokens_per_second']);self.assertIsNone(metrics['prompt_tokens_per_second'])
        self.assertEqual(metrics['eval_duration_ns'],0)

    def test_negative_float_bool_and_invalid_metrics(self):
        for key,bad in [('eval_count',True),('eval_count',1.5),('eval_duration',-1),('prompt_eval_count','10')]:
            with self.subTest(key=key,bad=bad):
                self.fails('ollama_metrics_invalid',a.project_metrics,{key:bad},0)

    def test_metric_failure_after_done_is_terminal_not_success(self):
        self.client.modify=lambda r,n:dict(r,eval_count=True)
        _,_,report=self.run_plan();e=report['result']['executions'][0]['execution']
        self.assertEqual(e['status'],'failed');self.assertIsNotNone(e['finished_at'])
        self.assertEqual(e['error']['code'],'ollama_metrics_invalid')

    def test_decimal_rate_rounding(self):
        metrics=a.project_metrics(dict(eval_count=1,eval_duration=3_000_000_000),1)
        self.assertEqual(metrics['tokens_per_second'],'0.333333')
        self.assertEqual(a.project_metrics(dict(eval_count=1,eval_duration=1),1)['tokens_per_second'],'1000000000')

    def test_incomplete_response_is_uncertain(self):
        self.client.modify=lambda r,n:dict(r,done=False)
        _,_,report=self.run_plan();self.assertEqual(report['result']['status'],'interrupted')
        self.assertIsNone(report['result']['executions'][0]['execution']['finished_at'])

    def test_nonobject_response_is_uncertain(self):
        self.client.modify=lambda r,n:['invalid']
        _,_,report=self.run_plan();self.assertEqual(report['result']['status'],'interrupted')

    def test_nan_response_is_not_success(self):
        self.client.modify=lambda r,n:dict(r,eval_count=float('nan'))
        _,_,report=self.run_plan();self.assertEqual(report['result']['executions'][0]['execution']['status'],'failed')

    def test_catalog_bad_schema(self):
        original=self.client.request
        self.client.request=lambda ep,payload=None:dict(models='invalid') if ep=='/api/tags' else original(ep,payload)
        _,_,report=self.run_plan();self.assertEqual(self.client.generations,0)
        self.assertEqual(report['result']['status'],'failed')

    def test_explicit_adapter_build_and_digest_required(self):
        for kind in ('adapter','build','digest','temperature'):
            config=copy.deepcopy(self.config)
            if kind=='adapter':config['participants'][0]['adapter_version']='unknown-v1'
            if kind=='build':config['engine']['source_sha256']='b'*64
            if kind=='digest':config['participants'][0]['model']['revision_digest']=None
            if kind=='temperature':config['participants'][0]['parameters']['temperature']='0.1234567890123456789'
            plan=p.create_run_plan(self.c,self.r,config,asset_root=S1/'assets')
            self.fails(None,a.validate_execution_plan,plan)
        self.assertEqual(self.client.calls,[])

    def test_public_adapter_refuses_parameters_outside_pinned_participant(self):
        store=self.store();participant=self.config['participants'][0]
        identity=p.new_attempt_identity(self.plan,participant['participant_id'],1);store.prepare(self.plan,identity)
        adapter=a.OllamaAdapter(self.client)
        for field in ('parameters','model','participant_id'):
            changed=copy.deepcopy(participant)
            if field=='parameters':changed['parameters']['threads']+=1
            if field=='model':changed['model']['revision_digest']='b'*64
            if field=='participant_id':changed['participant_id']=str(uuid.uuid4())
            self.fails('participant_binding_mismatch',adapter.execute,self.plan,changed,identity,store,run_remaining=10)
        self.assertFalse(self.client.calls)
        self.assertEqual(store._names(w._base(identity,'workspaces')+'/outputs'),[])

    def test_unsupported_option_rejected_s2(self):
        self.config['participants'][0]['parameters']['num_gpu']=99
        self.fails('unknown_field',self.make_plan)

    def test_api_configuration_and_private_credentials_rejected(self):
        for value in ('','ftp://example.invalid','http://user:secret@example.invalid','http://@example.invalid',
                      'http://example.invalid/path','http://example.invalid?token=secret','http://example.invalid:0'):
            self.fails('api_url_invalid',a.api_url,value)
        self.assertEqual(a.api_url('http://127.0.0.1:11434/'),'http://127.0.0.1:11434')

    def test_capacity_preflight_no_http(self):
        self.config['policy']['max_files']=1;self.plan=self.make_plan()
        self.fails('s4_artifact_budget_exceeded',a.validate_execution_plan,self.plan)
        self.assertFalse(self.client.calls)


class SafetyTests(Case):
    def test_timeout_no_next_model_no_retry_even_ps_idle(self):
        self.config['repetitions']=2;self.plan=self.make_plan();self.client.fail=(1,TimeoutError('private'))
        store,coordinator,report=self.run_plan();self.assertEqual(self.client.generations,1)
        self.assertFalse(report['resumable']);self.assertEqual(report['server_quiescence'],'unknown')
        before=self.snap();calls=copy.deepcopy(self.client.calls)
        self.fails('server_quiescence_unconfirmed',coordinator.run,a.OllamaAdapter(self.client),resume=True)
        self.assertEqual(before,self.snap());self.assertEqual(calls,self.client.calls)
        self.assertFalse(any(ep=='/api/ps' for ep,_,_ in self.client.calls))

    def test_connection_definitely_refused_is_known_not_sent(self):
        self.client.fail=(1,urllib.error.URLError(ConnectionRefusedError('synthetic')))
        _,_,report=self.run_plan();e=report['result']['executions'][0]['execution']
        self.assertEqual(e['status'],'failed');self.assertEqual(e['error']['code'],'request_not_sent')
        self.assertTrue(report['resumable'])

    def test_connection_lost_after_possible_send_is_uncertain(self):
        self.client.fail=(1,ConnectionResetError('synthetic'))
        _,_,report=self.run_plan();self.assertFalse(report['resumable'])
        self.assertEqual(report['result']['executions'][0]['execution']['status'],'uncertain')

    def test_untyped_runtime_error_is_uncertain(self):
        self.client.fail=(1,RuntimeError('raw credentials must remain private'))
        _,_,report=self.run_plan()
        self.assertEqual(report['result']['executions'][0]['execution']['status'],'uncertain')
        self.assertNotIn('credentials',json.dumps(report))

    def test_http_500_does_not_prove_server_stopped(self):
        self.client.fail=(1,urllib.error.HTTPError('http://ollama.invalid',500,'synthetic',None,None))
        _,_,report=self.run_plan();self.assertFalse(report['resumable'])

    def test_request_intent_durable_before_transport(self):
        store=self.store();coordinator=a.RunCoordinator(store,self.plan)
        def check(endpoint,body):
            journal=store.validate_journal(self.plan)
            self.assertEqual(journal['state']['attempts'][-1]['status'],'prepared')
            identity=journal['state']['attempts'][-1]['identity']
            folder=self.root/w._base(identity,'workspaces')/'outputs'
            requests=sorted(folder.glob('request_*.json'))
            self.assertTrue(requests)
            self.assertEqual(d.load_json(requests[-1])['endpoint'],endpoint)
            self.assertEqual(requests[-1].stat().st_mode & 0o777,0o400)
            start=d.load_json(folder/'running.json');p.validate_execution(start,self.plan)
            self.assertEqual(start['status'],'running')
        self.client.before=check
        coordinator.run(a.OllamaAdapter(self.client))

    def test_confirmed_resume_after_commit_skips_original_success(self):
        self.config['repetitions']=2;self.plan=self.make_plan()
        store=self.store();coordinator=a.RunCoordinator(store,self.plan)
        def stop(name):
            if name=='s4_attempt_committed':raise KeyboardInterrupt
        with patch.object(w,'_checkpoint',stop):
            with self.assertRaises(KeyboardInterrupt):coordinator.run(a.OllamaAdapter(self.client))
        first=copy.deepcopy(coordinator.inspect()['result']['executions'][0])
        self.assertEqual(self.client.generations,1)
        store.__exit__()
        with w.WorkspaceStore(self.root,create=False) as reopened:
            report=a.RunCoordinator(reopened,self.plan).run(a.OllamaAdapter(self.client),resume=True)
        self.assertEqual(self.client.generations,2);self.assertEqual(report['result']['executions'][0],first)
        self.assertEqual(report['result']['progress']['successful_slots'],2)

    def test_completed_resume_no_calls_no_changes(self):
        store,coordinator,report=self.run_plan();before=self.snap();calls=copy.deepcopy(self.client.calls)
        again=coordinator.run(a.OllamaAdapter(self.client),resume=True)
        self.assertEqual(report,again);self.assertEqual(calls,self.client.calls);self.assertEqual(before,self.snap())

    def test_failed_terminal_measurement_not_repeated(self):
        self.client.modify=lambda r,n:dict(r,eval_count=-1)
        _,coordinator,report=self.run_plan()
        self.assertEqual(report['result']['progress']['failed_slots'],1)
        count=self.client.generations;coordinator.run(a.OllamaAdapter(self.client),resume=True)
        self.assertEqual(self.client.generations,count)

    def test_keyboard_interrupt_during_request_blocks_resume(self):
        self.client.fail=(1,KeyboardInterrupt())
        store=self.store();coordinator=a.RunCoordinator(store,self.plan)
        with self.assertRaises(KeyboardInterrupt):coordinator.run(a.OllamaAdapter(self.client))
        report=coordinator.inspect();self.assertFalse(report['resumable'])
        self.assertEqual(report['result']['executions'][0]['execution']['status'],'uncertain')
        self.fails('server_quiescence_unconfirmed',coordinator.run,a.OllamaAdapter(self.client),resume=True)

    def test_no_outcome_even_before_transport_is_conservatively_blocked(self):
        store=self.store();identity=p.new_attempt_identity(self.plan,self.config['participants'][0]['participant_id'],1)
        store.prepare(self.plan,identity)
        coordinator=a.RunCoordinator(store,self.plan)
        report=coordinator.inspect()
        self.assertFalse(report['resumable'])
        reserved=store._json_read('journals/'+identity['run_id']+'/00000003.json')['event']['at']
        self.assertEqual(report['result']['executions'][0]['execution']['started_at'],reserved)
        self.fails('server_quiescence_unconfirmed',coordinator.run,a.OllamaAdapter(self.client),resume=True)
        self.assertFalse(self.client.calls)

    def test_persistence_failure_after_http_does_not_replay(self):
        store=self.store();coordinator=a.RunCoordinator(store,self.plan);publish=store._json
        def fault(relative,value):
            if relative.endswith('/outcome.json'):raise KeyboardInterrupt
            return publish(relative,value)
        with patch.object(store,'_json',fault):
            with self.assertRaises(KeyboardInterrupt):coordinator.run(a.OllamaAdapter(self.client))
        self.assertEqual(self.client.generations,1);self.assertFalse(coordinator.inspect()['resumable'])
        self.fails('server_quiescence_unconfirmed',coordinator.run,a.OllamaAdapter(self.client),resume=True)

    def test_partial_collection_after_response_never_claims_success(self):
        store=self.store();coordinator=a.RunCoordinator(store,self.plan)
        with patch.object(store,'archive_artifacts',side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):coordinator.run(a.OllamaAdapter(self.client))
        self.assertEqual(self.client.generations,1)
        report=coordinator.inspect();self.assertEqual(report['result']['status'],'interrupted')
        self.assertEqual(report['result']['progress']['successful_slots'],0)

    def test_changed_private_api_binding_blocks_resume(self):
        _,coordinator,_=self.run_plan();self.client.base_url='http://different.invalid:11434'
        before=len(self.client.calls)
        self.fails('api_binding_mismatch',coordinator.run,a.OllamaAdapter(self.client),resume=True)
        self.assertEqual(len(self.client.calls),before)

    def test_new_run_cannot_bypass_uncertain_old_run(self):
        store,_,report=self.run_plan()
        # Replace with a separate run in this store that has a durable unfinished intent.
        cfg=copy.deepcopy(self.config);cfg['run_id']=str(uuid.uuid4())
        other=p.create_run_plan(self.c,self.r,cfg,asset_root=S1/'assets')
        store.register_run(other,asset_root=S1/'assets')
        store.prepare(other,p.new_attempt_identity(other,cfg['participants'][0]['participant_id'],1))
        cfg=copy.deepcopy(self.config);cfg['run_id']=str(uuid.uuid4())
        fresh=p.create_run_plan(self.c,self.r,cfg,asset_root=S1/'assets');store.register_run(fresh,asset_root=S1/'assets')
        calls=len(self.client.calls)
        self.fails('other_run_not_quiescent',a.RunCoordinator(store,fresh).run,a.OllamaAdapter(self.client))
        self.assertEqual(calls,len(self.client.calls))

    def test_new_run_after_known_fatal_failure_does_not_require_fake_recovery(self):
        self.client.present=False
        store,_,report=self.run_plan();self.assertEqual(report['result']['status'],'failed')
        config=copy.deepcopy(self.config);config['run_id']=str(uuid.uuid4())
        fresh=p.create_run_plan(self.c,self.r,config,asset_root=S1/'assets')
        store.register_run(fresh,asset_root=S1/'assets');self.client.present=True
        report=a.RunCoordinator(store,fresh).run(a.OllamaAdapter(self.client))
        self.assertEqual(report['result']['status'],'completed');self.assertEqual(self.client.generations,1)

    def test_journal_corruption_stops_before_any_new_request(self):
        store,coordinator,_=self.run_plan();folder=self.root/'journals'/self.plan.as_dict()['run_id']
        file=folder/'00000004.json';obj=d.load_json(file);obj['sha256']='f'*64
        file.chmod(0o600);file.write_bytes(d.canonical_json_bytes(obj))
        calls=len(self.client.calls)
        self.fails('content_hash_mismatch',coordinator.run,a.OllamaAdapter(self.client),resume=True)
        self.assertEqual(calls,len(self.client.calls))

    def test_plan_prompt_and_rubric_drift_rejected(self):
        store,_,_=self.run_plan()
        for field in ('prompt','rubric','parameters'):
            c=copy.deepcopy(self.c);r=copy.deepcopy(self.r);cfg=copy.deepcopy(self.config)
            if field=='prompt':
                c['prompt']['text']='different prompt';c['prompt']['version']+=1;c['definition_revision']+=1
                c['prompt']['sha256']=d.hashlib.sha256(c['prompt']['text'].encode()).hexdigest()
            if field=='rubric':
                r['revision']+=1;c['rubric']['revision']+=1;c['rubric']['sha256']=d.content_sha256(r);c['definition_revision']+=1
            if field=='parameters':cfg['participants'][0]['parameters']['threads']+=1
            other=p.create_run_plan(c,r,cfg,asset_root=S1/'assets')
            self.fails('bundle_plan_mismatch',a.RunCoordinator(store,other).inspect)

    def test_artifact_tampering_stops_projection(self):
        store,coordinator,report=self.run_plan();artifact=report['result']['executions'][0]['execution']['artifacts'][0]
        file=self.root/artifact['path'];file.chmod(0o600);file.write_bytes(b'changed')
        self.fails(None,coordinator.inspect)

    def test_expected_head_detects_rollback(self):
        _,coordinator,_=self.run_plan()
        self.fails('journal_head_mismatch',coordinator.inspect,expected_head='c'*64)

    def test_writer_lock_shared_with_s3(self):
        self.store()
        self.fails('writer_busy',w.WorkspaceStore(self.root,create=False).__enter__)

    def test_deadline_pre_send_makes_no_transport_call(self):
        store=self.store();identity=p.new_attempt_identity(self.plan,self.config['participants'][0]['participant_id'],1)
        store.prepare(self.plan,identity)
        outcome=a.OllamaAdapter(self.client).execute(self.plan,self.config['participants'][0],identity,store,run_remaining=0)
        self.assertEqual(outcome['status'],'timed_out');self.assertFalse(self.client.calls)

    def test_slow_durable_intent_cannot_send_after_deadline(self):
        store=self.store();identity=p.new_attempt_identity(self.plan,self.config['participants'][0]['participant_id'],1)
        store.prepare(self.plan,identity);clock=[0];publish=store._json
        def slow(relative,value):
            result=publish(relative,value)
            if '/request_' in relative:clock[0]=2
            return result
        with patch.object(a.time,'monotonic',side_effect=lambda:clock[0]),patch.object(store,'_json',slow):
            outcome=a.OllamaAdapter(self.client).execute(self.plan,self.config['participants'][0],identity,store,run_remaining=1)
        self.assertEqual(outcome['status'],'timed_out');self.assertEqual(outcome['server_state'],'not_sent')
        self.assertEqual(outcome['request_count'],1);self.assertFalse(self.client.calls)

    def test_request_timeout_respects_remaining_budget(self):
        self.run_plan()
        self.assertTrue(all(0<t<=self.config['limits']['request_timeout_seconds'] for _,_,t in self.client.calls))
        self.assertEqual(self.client.timeout,300)

    def test_complete_response_returned_late_is_not_uncertain(self):
        store=self.store();identity=p.new_attempt_identity(self.plan,self.config['participants'][0]['participant_id'],1)
        store.prepare(self.plan,identity);clock=[0]
        def late(response,n):clock[0]=2;return response
        self.client.modify=late
        with patch.object(a.time,'monotonic',side_effect=lambda:clock[0]):
            outcome=a.OllamaAdapter(self.client).execute(self.plan,self.config['participants'][0],identity,store,run_remaining=1)
        self.assertEqual(self.client.generations,1)
        self.assertEqual(outcome['server_state'],'completed');self.assertEqual(outcome['status'],'timed_out')
        self.assertIsNotNone(outcome['finished_at'])

    def test_unexpected_output_not_automatically_archived(self):
        store=self.store();coordinator=a.RunCoordinator(store,self.plan)
        def unexpected(endpoint,body):
            if endpoint=='/api/generate':
                record=store.validate_journal(self.plan)['state']['attempts'][0]
                path=self.root/w._base(record['identity'],'workspaces')/'outputs/unexpected.txt'
                path.write_bytes(b'not in the explicit inventory')
        self.client.before=unexpected
        self.fails('inventory_mismatch',coordinator.run,a.OllamaAdapter(self.client))
        self.assertFalse(coordinator.inspect()['resumable'])



class CliTests(Case):
    def test_dry_run_no_http_no_process_no_private_archive_changes(self):
        self.store();before=self.snap();out=io.StringIO()
        with contextlib.redirect_stdout(out):self.assertEqual(casting.main(self.args('dry-run')),0)
        self.assertFalse(json.loads(out.getvalue())['http_performed'])
        self.assertEqual(before,self.snap());self.assertFalse(self.client.calls)

    def test_validate_and_build_info_are_offline(self):
        for args in (self.args('validate'),['build-info']):
            out=io.StringIO()
            with contextlib.redirect_stdout(out):self.assertEqual(casting.main(args),0)
            self.assertTrue(json.loads(out.getvalue())['ok'])
        self.assertFalse(self.root.exists())

    def test_cli_run_inspect_resume_and_export_same_s2_object(self):
        out=io.StringIO();err=io.StringIO();args=self.args('run')+['--root',str(self.root),'--api-url',self.client.base_url]
        with patch.object(a,'OllamaHTTPClient',return_value=self.client),contextlib.redirect_stdout(out),contextlib.redirect_stderr(err):
            self.assertEqual(casting.main(args),0)
        first=json.loads(out.getvalue());self.assertNotIn(self.client.base_url,out.getvalue())
        self.assertNotIn(self.c['prompt']['text'],out.getvalue());self.assertIn('progress',err.getvalue())
        calls=len(self.client.calls)
        for cmd in ('inspect','resume'):
            out=io.StringIO();args=self.args(cmd)+['--root',str(self.root)]
            if cmd=='resume':args+=['--api-url',self.client.base_url]
            if cmd=='inspect':args+=['--output',str(self.folder/'export.json')]
            with patch.object(a,'OllamaHTTPClient',return_value=self.client),contextlib.redirect_stdout(out):
                self.assertEqual(casting.main(args),0)
            self.assertEqual(json.loads(out.getvalue())['result'],first['result'])
        self.assertEqual(calls,len(self.client.calls))
        self.assertEqual(d.load_json(self.folder/'export.json'),first['result'])

    def test_cli_default_and_environment_api_configuration(self):
        for env,flag,expected in [({},None,legacy.DEFAULT_API_URL),({'OLLAMA_API_URL':'http://env.invalid'},None,'http://env.invalid'),
                                  ({'OLLAMA_API_URL':'http://env.invalid'},'http://flag.invalid','http://flag.invalid')]:
            self.root=self.folder/('root-'+str(uuid.uuid4()))
            args=self.args('run')+['--root',str(self.root)]
            if flag:args+=['--api-url',flag]
            self.client.base_url=expected
            with patch.dict(os.environ,env,clear=True),patch.object(a,'OllamaHTTPClient',return_value=self.client) as client,contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(casting.main(args),0)
                self.assertEqual(client.call_args.args[0],expected)

    def test_cli_uncertain_and_safe_errors(self):
        self.client.fail=(1,TimeoutError('secret raw error'))
        args=self.args('run')+['--root',str(self.root),'--api-url',self.client.base_url]
        out=io.StringIO()
        with patch.object(a,'OllamaHTTPClient',return_value=self.client),contextlib.redirect_stdout(out),contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(casting.main(args),1)
        self.assertNotIn('secret',out.getvalue())
        args=self.args('resume')+['--root',str(self.root),'--api-url',self.client.base_url]
        err=io.StringIO()
        with patch.object(a,'OllamaHTTPClient',return_value=self.client),contextlib.redirect_stderr(err):
            self.assertEqual(casting.main(args),2)
        self.assertEqual(json.loads(err.getvalue())['code'],'server_quiescence_unconfirmed')

    def test_cli_missing_invalid_syntax_json(self):
        for args in ([],['unknown'],['run']):
            err=io.StringIO()
            with contextlib.redirect_stderr(err):self.assertEqual(casting.main(args),2)
            self.assertEqual(json.loads(err.getvalue())['code'],'cli_arguments_invalid')

    def test_legacy_golden_and_archives_unchanged(self):
        before={str(f):f.read_bytes() for dirname in ('results','reports','tests/fixtures')
                for f in (ROOT/dirname).rglob('*') if f.is_file() and not f.is_symlink()}
        self.run_plan()
        self.assertEqual(before,{name:Path(name).read_bytes() for name in before})
        for name,digest in d.load_json(S2/'vectors.json').items():
            self.assertEqual(d.content_sha256(d.load_json(S2/name)),digest)


if __name__=='__main__':unittest.main()
