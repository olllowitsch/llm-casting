"""S2 synthetic objects only. No model/process/network execution by the planner."""
import copy
import contextlib
import io
from dataclasses import FrozenInstanceError
import errno
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import definitions as d
import planning as p

ROOT = Path(__file__).resolve().parents[1]
S1 = ROOT/'tests/fixtures/definitions/valid'
FIX = ROOT/'tests/fixtures/planning'
AID='44444444-4444-4444-8444-444444444444'
BID='55555555-5555-4555-8555-555555555555'
ART='77777777-7777-4777-8777-777777777777'
AT='2026-01-01T00:00:00Z'
END='2026-01-01T00:00:02Z'


class PlanningCase(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=ROOT);self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.c=d.load_json(S1/'competition.json');self.r=d.load_json(S1/'rubric.json')
        self.config=d.load_json(FIX/'config.json')
        self.assets=S1/'assets'

    def plan(self,config=None,**kwargs):
        return p.create_run_plan(self.c,self.r,config if config is not None else self.config,
                                 asset_root=self.assets,**kwargs)

    def resolved(self):
        config=copy.deepcopy(self.config)
        config['participants'][0]['model']['revision_digest']='a'*64
        config['engine']['source_sha256']='b'*64
        config['run_id']='dddddddd-dddd-4ddd-8ddd-dddddddddddd'
        return self.plan(config)

    def fails(self,code,fn,*args,**kwargs):
        with self.assertRaises(d.DefinitionError) as error:fn(*args,**kwargs)
        if code is not None:self.assertEqual(error.exception.code,code)
        return error.exception

    def execution(self,plan,status='succeeded',**overrides):
        v=dict(kind='execution',schema_version=1,**p.new_attempt_identity(plan,plan.as_dict()['participants'][0]['participant_id'],1),
               status=status,started_at=AT,finished_at=END,metrics={k:None for k in p.METRICS},error=None,
               artifacts=[],provenance={},supersedes_attempt_id=None)
        v['attempt_id']=AID
        if status in ('running','uncertain'):v['finished_at']=None
        if status=='planned':v.update(started_at=None,finished_at=None)
        if status in ('failed','timed_out'):v['error']=dict(code='synthetic_failure',phase='execution',retryable=False,evidence=[])
        v.update(overrides)
        return v

    def result(self,plan,e=None,status='completed'):
        v=p.initial_result(plan,at=AT);v.update(status=status,updated_at=END)
        if e is not None:v['executions']=[dict(execution=e,sha256=d.content_sha256(e))]
        self.recount(v,plan)
        return v

    def recount(self,result,plan):
        result['progress']=p._progress(result['executions'],plan)[0]


class PlanTests(PlanningCase):
    def test_valid_plan_roundtrip_and_golden(self):
        plan=self.plan();self.assertEqual(plan.as_dict(),d.load_json(FIX/'run-plan.json'))
        self.assertEqual(d.canonical_json_bytes(plan.as_dict()),(FIX/'run-plan.canonical.json').read_bytes())
        self.assertEqual(plan.sha256,d.load_json(FIX/'vectors.json')['run-plan.json'])
        self.assertEqual(p.validate_run_plan(plan.as_dict(),self.c,self.r,asset_root=self.assets),plan)

    def test_immutable_plan_copies_and_external_hash_pin(self):
        plan=self.plan();value=plan.as_dict();value['participants'][0]['parameters']['threads']=8
        self.assertNotEqual(value,plan.as_dict())
        self.fails('content_hash_mismatch',p.validate_run_plan,value,self.c,self.r,asset_root=self.assets,expected_sha256=plan.sha256)
        self.fails('plan_immutable',p.validate_run_plan,value,self.c,self.r,asset_root=self.assets,previous=plan)
        with self.assertRaises(FrozenInstanceError):plan._bytes=b'{}'
        self.assertEqual(p.validate_run_plan(plan.as_dict(),self.c,self.r,asset_root=self.assets,previous=plan),plan)

    def test_plan_hash_and_previous_comparison_ignore_only_json_field_order(self):
        plan=self.plan()
        def reverse(v):
            if isinstance(v,dict):return {k:reverse(x) for k,x in reversed(list(v.items()))}
            if isinstance(v,list):return [reverse(x) for x in v]
            return v
        reversed_plan=p.validate_run_plan(reverse(plan.as_dict()),self.c,self.r,asset_root=self.assets,previous=plan)
        self.assertEqual(reversed_plan.sha256,plan.sha256)
        self.assertEqual(p.serialize_run_plan(reversed_plan),p.serialize_run_plan(plan))

    def test_shared_prompt_assets_rubric_and_discipline_bound_transitively(self):
        plan=self.plan();value=plan.as_dict()
        c=copy.deepcopy(self.c);c['prompt']['text']+='\n'
        self.fails('prompt_hash_mismatch',p.validate_run_plan,value,c,self.r,asset_root=self.assets)
        c['prompt']['sha256']=__import__('hashlib').sha256(c['prompt']['text'].encode()).hexdigest()
        self.fails('competition_binding_mismatch',p.validate_run_plan,value,c,self.r,asset_root=self.assets)
        c=copy.deepcopy(self.c);c['assets'][0]['sha256']='0'*64
        self.fails('asset_hash_mismatch',p.validate_run_plan,value,c,self.r,asset_root=self.assets)
        r=copy.deepcopy(self.r);r['name']='changed'
        self.fails('rubric_hash_mismatch',p.validate_run_plan,value,self.c,r,asset_root=self.assets)
        for extra in ['prompt','assets','rubric','discipline']:
            v=copy.deepcopy(value);v['participants'][0][extra]={}
            self.fails('unknown_field',p.validate_run_plan,v,self.c,self.r,asset_root=self.assets)

    def test_unbound_changed_or_missing_digest(self):
        a=self.plan();self.assertIn('model_digest_unknown',p.plan_readiness(a)['reasons'])
        b=self.resolved();self.assertNotEqual(a.sha256,b.sha256)
        v=b.as_dict();v['participants'][0]['model']['revision_digest']='c'*64
        self.fails('plan_immutable',p.validate_run_plan,v,self.c,self.r,asset_root=self.assets,previous=b)
        for digest in ['latest','http://private.invalid/model','not-a-digest',True,4]:
            config=copy.deepcopy(self.config);config['participants'][0]['model']['revision_digest']=digest
            self.fails('model_digest_invalid',self.plan,config)

    def test_requested_automatic_never_means_gpu_verified(self):
        config=copy.deepcopy(self.config);config['participants'][0]['parameters']['gpu_mode']='automatic'
        plan=self.plan(config);readiness=p.plan_readiness(plan)
        self.assertFalse(readiness['executable']);self.assertEqual(readiness['gpu_usage'],'not_measured')
        self.assertFalse(plan.as_dict()['participants'][0]['hardware']['verified'])
        config['participants'][0]['parameters']['gpu_mode']='cpu_only';self.plan(config)
        config['participants'][0]['parameters']['gpu_mode']='force_all_layers'
        self.fails('gpu_mode_unsupported',self.plan,config)

    def test_no_capabilities_or_hardware_invented(self):
        config=copy.deepcopy(self.config);hw=config['participants'][0]['hardware']
        hw.update(verified=True,profile_id=ART,profile_revision=1)
        self.fails('hardware_evidence_unavailable',self.plan,config)
        hw['verified']=False;self.fails('hardware_unknown_inconsistent',self.plan,config)
        hw.update(profile_id=None,profile_revision=None,verified=1)
        self.fails('boolean_invalid',self.plan,config)

    def test_no_opencode_parameter_translation(self):
        config=copy.deepcopy(self.config);config['participants'][0]['execution_adapter']='opencode'
        self.fails('adapter_unsupported',self.plan,config)
        config['participants'][0]['execution_adapter']='ollama';config['participants'][0]['provider']='cloud'
        self.fails('adapter_unsupported',self.plan,config)

    def test_unknown_options_bools_integers_and_decimals(self):
        for key,bad,code in [('threads',True,'integer_invalid'),('num_ctx',0,'integer_invalid'),
                             ('seed',False,'integer_invalid'),('think',1,'boolean_invalid'),
                             ('temperature','1.00','decimal_invalid'),('temperature',0.5,'json_type_invalid')]:
            config=copy.deepcopy(self.config);config['participants'][0]['parameters'][key]=bad
            self.fails(code,self.plan,config)
        config=copy.deepcopy(self.config);config['participants'][0]['parameters']['api_key']='PRIVATE'
        self.fails('unknown_field',self.plan,config)

    def test_budget_repetitions_and_measurement_limits(self):
        for key,bad,code in [('repetitions',True,'integer_invalid'),('repetitions',0,'integer_invalid'),
                             ('repetitions',10001,'measurement_slot_limit')]:
            self.fails(code,self.plan,dict(self.config,**{key:bad}))
        config=copy.deepcopy(self.config);config['limits']['request_timeout_seconds']=1201
        self.fails('time_budget_inconsistent',self.plan,config)
        config=copy.deepcopy(self.config);config['policy']['max_asset_bytes']=1
        self.fails('plan_asset_size_limit',self.plan,config)

    def test_duplicate_participants_uuid_and_schema_errors(self):
        config=copy.deepcopy(self.config);config['participants'].append(config['participants'][0])
        self.fails('participant_duplicate',self.plan,config)
        config=copy.deepcopy(self.config);config['participants'][0]['participant_id']='bad'
        self.fails('uuid_invalid',self.plan,config)
        plan=self.plan().as_dict()
        for version in [True,2,'1']:
            self.fails('schema_version_unsupported',p.validate_run_plan,dict(plan,schema_version=version),self.c,self.r,asset_root=self.assets)
        self.fails('unknown_field',self.plan,dict(self.config,api_url='http://private.invalid'))

    def test_separate_slots_and_attempt_ids(self):
        config=copy.deepcopy(self.config);config['repetitions']=2
        other=copy.deepcopy(config['participants'][0]);other['participant_id']=BID;config['participants'].append(other)
        plan=self.plan(config);self.assertEqual(len(p.measurement_slots(plan)),4)
        a=p.new_attempt_identity(plan,BID,1);b=p.new_attempt_identity(plan,BID,1)
        self.assertNotEqual(a['attempt_id'],b['attempt_id']);self.assertEqual(a['plan_sha256'],b['plan_sha256'])
        self.fails('measurement_slot_invalid',p.new_attempt_identity,plan,BID,True)

    def test_model_names_versions_and_private_addresses(self):
        for name in ['http://private.invalid/model','/private/model','C:/secret/model','192.0.2.1']:
            config=copy.deepcopy(self.config);config['participants'][0]['model']['name']=name
            self.fails(None,self.plan,config)
        config=copy.deepcopy(self.config);config['engine']['version']='file:///etc/private'
        self.fails('portable_identifier_invalid',self.plan,config)

    def test_dry_planning_has_no_network_or_child_processes(self):
        with (patch('socket.socket',side_effect=AssertionError('network')),
              patch('urllib.request.urlopen',side_effect=AssertionError('network')),
              patch('subprocess.Popen',side_effect=AssertionError('process'))):
            plan=self.plan();p.initial_result(plan,at=AT);p.plan_readiness(plan)

    def test_documented_examples_remain_compatible_without_new_core_fields(self):
        import re
        values={}
        for name in ['COMPETITION','RUBRIC','RUN','RESULT']:
            doc=(ROOT/'docs'/(name+'_CONTRACT.md')).read_text()
            values[name]=d.parse_json_bytes(re.search(r'```json\n(.*?)\n```',doc,re.S)[1].encode())
        plan=p.validate_run_plan(values['RUN'],values['COMPETITION'],values['RUBRIC'])
        p.validate_result(values['RESULT'],plan)

    def test_actual_asset_byte_drift_is_detected_before_plan_creation(self):
        root=self.root/'assets';root.mkdir();data=(self.assets/'input.txt').read_bytes()
        (root/'input.txt').write_bytes(data);p.create_run_plan(self.c,self.r,self.config,asset_root=root)
        (root/'input.txt').write_bytes(b'x'*len(data))
        self.fails('asset_hash_mismatch',p.create_run_plan,self.c,self.r,self.config,asset_root=root)

    def test_unicode_model_names_are_preserved_without_normalization(self):
        config=copy.deepcopy(self.config);config['participants'][0]['model']['name']='模型-é'
        a=self.plan(config);config['participants'][0]['model']['name']='模型-e\u0301'
        b=self.plan(config);self.assertNotEqual(a.sha256,b.sha256)



class ResultTests(PlanningCase):
    def test_initial_result_golden_no_measured_values(self):
        plan=self.plan();result=p.initial_result(plan,at=AT)
        self.assertEqual(result,d.load_json(FIX/'initial-result.json'))
        self.assertEqual(p.serialize_result(result,plan),(FIX/'initial-result.canonical.json').read_bytes())
        self.assertEqual(result['executions'],[]);self.assertEqual(result['progress']['pending_slots'],1)
        self.assertEqual(d.content_sha256(result),d.load_json(FIX/'vectors.json')['initial-result.json'])

    def test_completed_result_has_unknown_metrics_not_zero_or_failure(self):
        plan=self.resolved();e=self.execution(plan);result=self.result(plan,e)
        p.validate_result(result,plan)
        self.assertTrue(all(v is None for v in result['executions'][0]['execution']['metrics'].values()))
        self.assertEqual(result['progress']['successful_slots'],1)
        self.assertEqual(p.validate_result(d.parse_json_bytes(p.serialize_result(result,plan)),plan),result)

    def test_metrics_units_zero_and_rate_consistency(self):
        metrics={k:None for k in p.METRICS};metrics.update(eval_count=20,eval_duration_ns=2000000000,tokens_per_second='10')
        self.assertEqual(p.validate_metrics(metrics),metrics)
        metrics['tokens_per_second']='11';self.fails('metric_rate_inconsistent',p.validate_metrics,metrics)
        metrics.update(eval_count=0,tokens_per_second='0');p.validate_metrics(metrics)
        metrics['eval_duration_ns']=0;self.fails('metric_rate_without_basis',p.validate_metrics,metrics)
        metrics['tokens_per_second']=None;p.validate_metrics(metrics)
        metrics['eval_count']=True;self.fails('integer_invalid',p.validate_metrics,metrics)

    def test_recurring_rates_round_once_and_invalid_decimals_fail(self):
        m={k:None for k in p.METRICS};m.update(eval_count=1,eval_duration_ns=3000000000,tokens_per_second='0.333333')
        p.validate_metrics(m)
        for value in ['0.333334','0.3333331','0.3333330','NaN']:
            m['tokens_per_second']=value;self.fails(None,p.validate_metrics,m)

    def test_mutated_hash_and_external_result_pin(self):
        plan=self.resolved();result=self.result(plan,self.execution(plan));digest=d.content_sha256(result)
        result['executions'][0]['execution']['metrics']['eval_count']=7
        self.fails('content_hash_mismatch',p.validate_result,result,plan)
        result['executions'][0]['sha256']=d.content_sha256(result['executions'][0]['execution'])
        self.fails('content_hash_mismatch',p.validate_result,result,plan,expected_sha256=digest)

    def test_execution_references_duplicates_and_invalid_attempt_ids(self):
        plan=self.resolved();e=self.execution(plan)
        for key,bad,code in [('attempt_id','bad','uuid_invalid'),('run_id',BID,'execution_plan_mismatch'),
                             ('participant_id',BID,'measurement_slot_invalid'),('repetition',True,'integer_invalid')]:
            self.fails(code,p.validate_execution,dict(e,**{key:bad}),plan)
        result=self.result(plan,e);result['executions'].append(result['executions'][0])
        self.fails('attempt_duplicate',p.validate_result,result,plan)
        e2=dict(e,attempt_id=BID);result['executions'][1]={'execution':e2,'sha256':d.content_sha256(e2)}
        self.fails('measurement_slot_duplicate',p.validate_result,result,plan)

    def test_error_failure_timeout_and_missing_errors(self):
        plan=self.resolved()
        for status in ['failed','timed_out','cancelled']:
            result=self.result(plan,self.execution(plan,status));p.validate_result(result,plan)
            self.assertEqual(result['progress']['failed_slots'],1)
        e=self.execution(plan,'failed');e['error']=None
        self.fails('execution_error_missing',p.validate_execution,e,plan)
        e=self.execution(plan);e['error']={'code':'x','phase':'execution','retryable':False,'evidence':[]}
        self.fails('execution_error_conflict',p.validate_execution,e,plan)

    def test_timestamps_chronology_and_nano_precision(self):
        plan=self.resolved();e=self.execution(plan)
        for timestamp in ['2026-01-01','2026-99-01T00:00:00Z','2026-01-01T00:00:00+00:00']:
            self.fails('timestamp_invalid',p.validate_execution,dict(e,started_at=timestamp),plan)
        self.fails('execution_time_invalid',p.validate_execution,dict(e,started_at=END,finished_at=AT),plan)
        e.update(started_at='2026-01-01T00:00:00.000000002Z',finished_at='2026-01-01T00:00:00.000000001Z')
        self.fails('execution_time_invalid',p.validate_execution,e,plan)

    def test_planning_cannot_claim_execution_with_unresolved_model(self):
        plan=self.plan();e=self.execution(plan)
        self.fails('execution_plan_unresolved',p.validate_execution,e,plan)
        e=self.execution(plan,'planned');p.validate_execution(e,plan)
        e['metrics']['eval_count']=0;self.fails('unstarted_metrics_forbidden',p.validate_execution,e,plan)

    def test_uncertain_attempts_replacements_never_count_twice(self):
        plan=self.resolved();old=self.execution(plan,'uncertain');new=self.execution(plan,attempt_id=BID,supersedes_attempt_id=AID)
        result=self.result(plan,old,'interrupted')
        self.assertEqual(result['progress']['pending_slots'],1);p.validate_result(result,plan)
        result['executions'].append({'execution':new,'sha256':d.content_sha256(new)});result['status']='completed';self.recount(result,plan)
        p.validate_result(result,plan)
        self.assertEqual(result['progress']['started_attempts'],2);self.assertEqual(result['progress']['terminal_slots'],1)
        self.assertEqual(result['progress']['successful_slots'],1)

    def test_terminal_error_cannot_be_silently_retried(self):
        plan=self.resolved();old=self.execution(plan,'failed');new=self.execution(plan,attempt_id=BID,supersedes_attempt_id=AID)
        wrappers=[{'execution':e,'sha256':d.content_sha256(e)}for e in [old,new]]
        self.fails('attempt_supersedes_invalid',p._progress,wrappers,plan)

    def test_status_and_progress_invariants(self):
        plan=self.resolved();e=self.execution(plan);result=self.result(plan,e)
        result['progress']['successful_slots']=0;self.fails('progress_inconsistent',p.validate_result,result,plan)
        result=self.result(plan,self.execution(plan,'uncertain'),'completed')
        self.fails('completed_has_pending',p.validate_result,result,plan)
        result['status']='running';self.fails('uncertain_requires_interrupted',p.validate_result,result,plan)
        result=self.result(plan,self.execution(plan,'running'),'interrupted')
        self.fails('interrupted_has_running_attempt',p.validate_result,result,plan)
        result=self.result(plan,self.execution(plan,'running'),'cancelled')
        self.fails('cancelled_has_pending_attempt',p.validate_result,result,plan)

    def test_previous_final_execution_and_assessments_cannot_be_overwritten(self):
        plan=self.resolved();result=self.result(plan,self.execution(plan));changed=copy.deepcopy(result)
        changed['executions'][0]['execution']['metrics']['eval_count']=1
        changed['executions'][0]['sha256']=d.content_sha256(changed['executions'][0]['execution'])
        self.fails('execution_after_terminal_run',p.validate_result,changed,plan,previous=result)
        self.fails('run_transition_invalid',p.validate_run_transition,'completed','running')
        self.fails('attempt_transition_invalid',p.validate_attempt_transition,'failed','running')

    def test_unknown_result_fields_schema_and_sensitive_metadata(self):
        plan=self.plan();result=p.initial_result(plan,at=AT)
        self.fails('unknown_field',p.validate_result,dict(result,api_url='http://private.invalid'),plan)
        for version in [True,2,'1']:
            self.fails('schema_version_unsupported',p.validate_result,dict(result,schema_version=version),plan)
        plan=self.resolved();e=self.execution(plan);e['provenance']={'password':'SECRET'}
        self.fails('unknown_field',p.validate_execution,e,plan)
        e['provenance']={};e['error']={'message':'SECRET'}
        self.fails('unknown_field',p.validate_execution,e,plan)

    def test_artifact_inventory_and_evidence_references(self):
        plan=self.resolved();e=self.execution(plan,'failed')
        artifact=dict(artifact_id=ART,path='artifacts/log.txt',sha256='c'*64,size_bytes=8,media_type='text/plain',classification='private')
        e['artifacts']=[artifact];e['error']['evidence']=[ART];p.validate_execution(e,plan)
        for key,bad,code in [('path','../file','asset_path_invalid'),('path','/private/file','asset_path_invalid'),
                             ('sha256','x','sha256_invalid'),('size_bytes',True,'integer_invalid')]:
            wrong=copy.deepcopy(e);wrong['artifacts'][0][key]=bad;self.fails(code,p.validate_execution,wrong,plan)
        e['error']['evidence']=[BID];self.fails('evidence_reference_missing',p.validate_execution,e,plan)
        self.fails('artifact_duplicate',p.validate_artifacts,[artifact,artifact])

    def certificate(self,plan):
        return dict(kind='assessment',schema_version=1,assessment_id=ART,run_id=plan.as_dict()['run_id'],
                    participant_id=plan.as_dict()['participants'][0]['participant_id'],attempt_id=AID,
                    execution_sha256=d.content_sha256(self.execution(plan)),**plan.as_dict()['rubric'],
                    evaluator={'type':'human','version':'v1','identity':'synthetic-reviewer'},created_at=END,
                    categories=[],mandatory_tests=[],status='incomplete',total_score=None,supersedes=None,evidence=[])

    def test_optional_existing_certificates_are_referenced_not_generated(self):
        plan=self.resolved();result=self.result(plan,self.execution(plan));certificate=self.certificate(plan)
        result['assessments']=[certificate];p.validate_result(result,plan)
        self.assertEqual(result['assessments'][0]['total_score'],None)
        self.assertEqual(p.initial_result(plan,at=AT)['assessments'],[])

    def test_assessment_links_and_duplicate_ids_fail(self):
        plan=self.resolved();result=self.result(plan,self.execution(plan));result['assessments']=[self.certificate(plan)]
        original=copy.deepcopy(result)
        for key,bad,code in [('attempt_id',BID,'assessment_attempt_missing'),('execution_sha256','0'*64,'assessment_execution_mismatch'),
                             ('sha256','0'*64,'assessment_rubric_missing')]:
            changed=copy.deepcopy(original);changed['assessments'][0][key]=bad
            self.fails(code,p.validate_result,changed,plan)
        result['assessments']*=2;self.fails('assessment_duplicate',p.validate_result,result,plan)

    def test_new_rubric_certificate_does_not_rewrite_original_plan(self):
        plan=self.resolved();result=self.result(plan,self.execution(plan));before=plan.sha256
        new_rubric=copy.deepcopy(self.r);new_rubric.update(revision=2,name='Revised synthetic rubric')
        certificate=self.certificate(plan);certificate.update(revision=2,sha256=d.content_sha256(new_rubric))
        result['assessments']=[certificate]
        self.fails('assessment_rubric_missing',p.validate_result,result,plan)
        p.validate_result(result,plan,assessment_rubrics=[new_rubric])
        self.assertEqual(plan.sha256,before)

    def test_existing_certificate_cannot_be_silently_edited(self):
        plan=self.resolved();result=self.result(plan,self.execution(plan));result['assessments']=[self.certificate(plan)]
        changed=copy.deepcopy(result);changed['assessments'][0]['evaluator']['identity']='another-reviewer'
        self.fails('assessment_immutable',p.validate_result,changed,plan,previous=result)

    def test_assessment_ranges_unknown_fields_and_sensitive_evaluator(self):
        plan=self.resolved();result=self.result(plan,self.execution(plan));result['assessments']=[self.certificate(plan)]
        for key,value,code in [('total_score','101','assessment_score_invalid'),('total_score',True,'decimal_invalid'),
                               ('extra','SECRET','unknown_field')]:
            r=copy.deepcopy(result);r['assessments'][0][key]=value
            self.fails(code,p.validate_result,r,plan)
        result['assessments'][0]['evaluator']['identity']='https://private.invalid'
        self.fails('portable_identifier_invalid',p.validate_result,result,plan)

    def test_provenance_binds_declared_engine_adapter_and_digest(self):
        plan=self.resolved();e=self.execution(plan);v=plan.as_dict()
        e['provenance']=dict(engine=v['engine'],adapter_version=v['participants'][0]['adapter_version'],
                             model_revision_digest=v['participants'][0]['model']['revision_digest'],evidence=[])
        p.validate_execution(e,plan)
        e['provenance']['model_revision_digest']='c'*64
        self.fails('provenance_binding_mismatch',p.validate_execution,e,plan)

    def test_previous_running_attempt_transition_and_removal(self):
        plan=self.resolved();old=self.result(plan,self.execution(plan,'running'),'running')
        finished=self.result(plan,self.execution(plan));p.validate_result(finished,plan,previous=old)
        missing=p.initial_result(plan,at=AT);missing.update(status='interrupted',updated_at=END)
        self.fails('execution_removed',p.validate_result,missing,plan,previous=old)

    def test_unstarted_cancellation_has_no_invented_measurement(self):
        plan=self.plan();e=self.execution(plan,'cancelled',started_at=None)
        result=self.result(plan,e,'cancelled');p.validate_result(result,plan)
        self.assertEqual(result['progress']['started_attempts'],0)
        self.assertEqual(result['progress']['terminal_slots'],1)


    def test_imported_certificate_cannot_claim_pass_with_missing_evidence(self):
        plan=self.resolved();result=self.result(plan,self.execution(plan));a=self.certificate(plan)
        a.update(status='passed',total_score='100');result['assessments']=[a]
        self.fails('assessment_pass_inconsistent',p.validate_result,result,plan)
        a.update(status='incomplete',total_score=None)
        a['mandatory_tests']=[dict(test_id='response_complete',status='failed',evidence=[])]
        self.fails('assessment_mandatory_gate_conflict',p.validate_result,result,plan)


    def test_terminal_cancelled_or_failed_run_cannot_accept_new_executions(self):
        plan=self.resolved()
        for status in ['cancelled','failed']:
            old=p.initial_result(plan,at=AT);old['status']=status
            new=self.result(plan,self.execution(plan),status)
            self.fails('execution_after_terminal_run',p.validate_result,new,plan,previous=old)



class OutputAndCliTests(PlanningCase):
    def test_atomic_explicit_output_without_overwrite(self):
        file=self.root/'output.json';obj=p.initial_result(self.plan(),at=AT)
        p.write_json_exclusive(file,obj);self.assertEqual(d.load_json(file),obj)
        original=file.read_bytes();self.fails('output_exists',p.write_json_exclusive,file,{'different':True})
        self.assertEqual(original,file.read_bytes());self.assertFalse(list(self.root.glob('.s2-*')))

    def test_forbidden_roots_symlinks_and_archives(self):
        for file in [ROOT/'results/new.json',ROOT/'reports/new.json',ROOT/'.git/new.json',self.root/'../bad.json']:
            self.fails('output_path_invalid',p.write_json_exclusive,file,{})
        alias=self.root/'alias';alias.symlink_to(self.root,target_is_directory=True)
        self.fails('output_write_failed',p.write_json_exclusive,alias/'new.json',{})
        protected=self.root/'inputs';protected.mkdir()
        self.fails('output_path_invalid',p.write_json_exclusive,protected/'new.json',{},protected_roots=[protected])
        (self.root/'manifest.json').write_text('{}')
        self.fails('output_archive_forbidden',p.write_json_exclusive,self.root/'new.json',{})

    def test_short_write_fsync_and_publish_failures_are_safe(self):
        file=self.root/'output.json'
        with patch.object(p.os,'fsync',side_effect=OSError(errno.EIO,'PRIVATE')):
            self.fails('output_write_failed',p.write_json_exclusive,file,{})
        self.assertFalse(file.exists());self.assertFalse(list(self.root.glob('.s2-*')))
        with patch.object(p,'_publish_no_replace',side_effect=OSError(errno.EIO,'PRIVATE')):
            self.fails('output_write_failed',p.write_json_exclusive,file,{})
        self.assertFalse(file.exists());self.assertFalse(list(self.root.glob('.s2-*')))

    def test_parent_exchange_and_destination_race(self):
        folder=self.root/'output';folder.mkdir();target=folder/'new.json';fsync=p.os.fsync
        def swap(fd):
            fsync(fd)
            if not (self.root/'old').exists():folder.rename(self.root/'old');folder.mkdir()
        with patch.object(p.os,'fsync',side_effect=swap):
            self.fails('output_parent_changed',p.write_json_exclusive,target,{})
        self.assertFalse(target.exists())
        publish=p._publish_no_replace
        def racing(parent,source,destination):
            target.write_text('original');publish(parent,source,destination)
        with patch.object(p,'_publish_no_replace',side_effect=racing):
            self.fails('output_exists',p.write_json_exclusive,target,{})
        self.assertEqual(target.read_text(),'original')

    def test_durability_failure_does_not_delete_published_result(self):
        file=self.root/'output.json';fsync=p.os.fsync;count=0
        def fail_second(fd):
            nonlocal count
            count+=1
            if count==2:raise OSError(errno.EIO,'private')
            return fsync(fd)
        with patch.object(p.os,'fsync',side_effect=fail_second):
            self.fails('output_durability_unknown',p.write_json_exclusive,file,{'valid':True})
        self.assertEqual(d.load_json(file),{'valid':True})

    def test_cli_create_validate_hash_and_initial_result(self):
        base=[sys.executable,'-B',str(ROOT/'planning.py')]
        common=['--competition',str(S1/'competition.json'),'--rubric',str(S1/'rubric.json'),'--assets',str(self.assets)]
        path=self.root/'plan.json'
        result=subprocess.run(base+['create-plan','--config',str(FIX/'config.json'),'--dry-run','--output',str(path)]+common,capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr);self.assertEqual(json.loads(result.stdout),self.plan().as_dict())
        result=subprocess.run(base+['validate-plan','--plan',str(path)]+common,capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr);self.assertFalse(json.loads(result.stdout)['readiness']['executable'])
        initial=self.root/'result.json'
        result=subprocess.run(base+['initial-result','--plan',str(path),'--at',AT,'--output',str(initial)]+common,capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        result=subprocess.run(base+['validate-result','--plan',str(path),'--result',str(initial)]+common,capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr);self.assertTrue(json.loads(result.stdout)['ok'])
        result=subprocess.run(base+['hash',str(path)],capture_output=True,text=True)
        self.assertEqual(json.loads(result.stdout)['sha256'],self.plan().sha256)

    def test_cli_duplicate_json_keys_and_safe_errors(self):
        config=self.root/'config.json';config.write_text('{"repetitions":1,"repetitions":2}')
        result=subprocess.run([sys.executable,'-B',str(ROOT/'planning.py'),'create-plan','--config',str(config),
                              '--competition',str(S1/'competition.json'),'--rubric',str(S1/'rubric.json'),'--assets',str(self.assets)],capture_output=True,text=True)
        self.assertEqual(result.returncode,2);self.assertEqual(json.loads(result.stderr)['code'],'json_duplicate_key')
        self.assertNotIn(str(ROOT),result.stderr);self.assertEqual(result.stdout,'')

    def test_direct_cli_dry_run_no_sockets_processes_or_files(self):
        args=['create-plan','--config',str(FIX/'config.json'),'--competition',str(S1/'competition.json'),
              '--rubric',str(S1/'rubric.json'),'--assets',str(self.assets),'--dry-run']
        before=sorted(x.name for x in self.root.iterdir())
        with (patch('socket.socket',side_effect=AssertionError('network')),
              patch('socket.create_connection',side_effect=AssertionError('network')),
              patch('urllib.request.urlopen',side_effect=AssertionError('network')),
              patch('subprocess.Popen',side_effect=AssertionError('process')),
              contextlib.redirect_stdout(io.StringIO()) as output):
            self.assertEqual(p.main(args),0)
        self.assertEqual(json.loads(output.getvalue()),self.plan().as_dict())
        self.assertEqual(sorted(x.name for x in self.root.iterdir()),before)

    def test_cli_symlinked_json_is_refused_without_sensitive_details(self):
        link=self.root/'PRIVATE_ALIAS';link.symlink_to(FIX/'run-plan.json')
        with contextlib.redirect_stderr(io.StringIO()) as error:
            self.assertEqual(p.main(['hash',str(link)]),2)
        self.assertEqual(json.loads(error.getvalue())['code'],'file_access_failed')
        self.assertNotIn('PRIVATE_ALIAS',error.getvalue())

    def test_output_size_extension_and_missing_parent_are_safe(self):
        self.fails('output_path_invalid',p.write_json_exclusive,self.root/'out.txt',{})
        self.fails('output_write_failed',p.write_json_exclusive,self.root/'missing/out.json',{})
        self.fails('json_size_limit',p.write_json_exclusive,self.root/'big.json',['x'*262144]*5)
        self.assertFalse((self.root/'big.json').exists())

    def test_temporary_file_tampering_is_not_published(self):
        target=self.root/'out.json';read=d._read_fd
        def tamper(parent,name,limit,**kwargs):
            fd=os.open(name,os.O_WRONLY|os.O_TRUNC,dir_fd=parent)
            try:os.write(fd,b'{}')
            finally:os.close(fd)
            return read(parent,name,limit,**kwargs)
        with patch.object(d,'_read_fd',side_effect=tamper):
            self.fails('output_file_changed',p.write_json_exclusive,target,{'not_empty':True})
        self.assertFalse(target.exists())

    def test_all_golden_vectors_have_exact_canonical_bytes_and_digests(self):
        vectors=d.load_json(FIX/'vectors.json')
        for name,digest in vectors.items():
            obj=d.load_json(FIX/name)
            self.assertEqual(d.content_sha256(obj),digest)
            self.assertEqual(d.canonical_json_bytes(obj),(FIX/name.replace('.json','.canonical.json')).read_bytes())
        plan=p.validate_run_plan(d.load_json(FIX/'resolved-plan.json'),self.c,self.r,asset_root=self.assets)
        p.validate_result(d.load_json(FIX/'synthetic-completed-result.json'),plan)

    def test_parent_exchange_after_publication_does_not_report_success(self):
        folder=self.root/'out';folder.mkdir();fsync=p.os.fsync;count=0
        def swap_second(fd):
            nonlocal count
            count+=1;fsync(fd)
            if count==2:folder.rename(self.root/'old');folder.mkdir()
        with patch.object(p.os,'fsync',side_effect=swap_second):
            self.fails('output_parent_changed',p.write_json_exclusive,folder/'data.json',{'valid':True})
        self.assertFalse((folder/'data.json').exists())
        self.assertEqual(d.load_json(self.root/'old/data.json'),{'valid':True})



if __name__=='__main__':unittest.main()
