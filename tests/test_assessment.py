"""S5 synthetic, verified S3/S4 fixtures. No real transport/process is permitted."""
import contextlib
import copy
from fractions import Fraction
import io
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
import uuid

import assessment as a
import definitions as d
import planning as p
import workspaces as w
import ollama_adapter as o
from test_ollama_adapter import FakeOllama

ROOT=Path(__file__).resolve().parents[1]
S1=ROOT/'tests/fixtures/definitions/valid'
S2=ROOT/'tests/fixtures/planning'


class Case(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        for target in ('urllib.request.urlopen','socket.socket','socket.create_connection','subprocess.Popen'):
            guard=patch(target,side_effect=AssertionError('S5 external operation forbidden'))
            guard.start();cls.addClassCleanup(guard.stop)
        template=tempfile.TemporaryDirectory(dir=ROOT);cls.addClassCleanup(template.cleanup)
        cls.template=Path(template.name)/'source'
        cls.c=d.load_json(S1/'competition.json');cls.r=d.load_json(S1/'rubric.json')
        config=d.load_json(S2/'config.json');config['run_id']=str(uuid.uuid4())
        config['participants'][0]['adapter_version']=o.ADAPTER_VERSION
        config['participants'][0]['model']['revision_digest']='a'*64
        config['engine']=dict(version=o.VERSION,source_sha256=d.content_sha256(o.build_manifest()))
        config['preparation']=dict(unload_before=False,preload=False,warmup_count=0)
        cls.plan=p.create_run_plan(cls.c,cls.r,config,asset_root=S1/'assets')
        fake=FakeOllama()
        with w.WorkspaceStore(cls.template) as store:
            store.register_run(cls.plan,asset_root=S1/'assets')
            cls.original=o.RunCoordinator(store,cls.plan).run(o.OllamaAdapter(fake))['result']
        cls.aid=cls.original['executions'][0]['execution']['attempt_id']

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=ROOT);self.addCleanup(self.tmp.cleanup)
        self.folder=Path(self.tmp.name);self.source_root=self.folder/'source';self.archive_root=self.folder/'assessment.local'
        shutil.copytree(self.template,self.source_root)
        self.source=w.WorkspaceStore(self.source_root,create=False).__enter__();self.addCleanup(self.source.__exit__)
        self.archive=w.WorkspaceStore(self.archive_root).__enter__();self.addCleanup(self.archive.__exit__)
        self.repo=a.AssessmentRepository(self.archive)
        self.rubric=copy.deepcopy(self.r)

    def rules(self,rubric=None,**overrides):
        rubric=rubric or self.rubric
        sha=d.content_sha256(rubric)
        return tuple(a.BinaryCategoryRule(sha,c['category_id'],
             next(s['checks'][0]['test_id'] for s in rubric['test_suites'] if s['suite_id']==c['test_suite_id']),
             overrides.get(c['category_id'],str(c['max_points'])),'0')
             for c in rubric['categories'] if c['source']=='deterministic' and 'test_suite_id' in c)

    def assess(self,*,rubric=None,rules=None,**kwargs):
        rubric=rubric or self.rubric
        return a.assess(self.source,self.repo,self.plan,self.aid,rubric,
            expected_rubric_sha256=d.content_sha256(rubric),rules=self.rules(rubric) if rules is None else rules,**kwargs)

    def fails(self,code,fn,*args,**kwargs):
        with self.assertRaises(d.DefinitionError) as error:fn(*args,**kwargs)
        if code:self.assertEqual(error.exception.code,code)
        return error.exception

    def snapshot(self,root=None):
        root=root or self.source_root
        return {str(f.relative_to(root)):f.read_bytes() for f in root.rglob('*') if f.is_file() and not f.is_symlink()}

    def categories(self,rubric=None,points=None):
        rubric=rubric or self.rubric
        return [dict(category_id=c['category_id'],points=(points or {}).get(c['category_id'],str(c['max_points'])),
                     status='complete',evidence=[]) for c in rubric['categories']]


class ScoreTests(Case):
    def test_score_formula_weights_and_maxima(self):
        categories=self.categories(points={'response':'5','rate':'10'})
        self.assertEqual(a.calculate_score(self.rubric,categories),'65')
        rubric=copy.deepcopy(self.rubric);rubric['categories'][0]['weight_bps']=1000
        rubric['categories'][1]['weight_bps']=9000
        self.assertEqual(a.calculate_score(rubric,categories),'95')
        rubric['categories'][0]['max_points']=100;rubric['categories'][0]['anchors'][-1]['points']=100
        categories[0]['points']='50'
        self.assertEqual(a.calculate_score(rubric,categories),'95')

    def test_exact_round_half_up_tie_and_below(self):
        cats=self.categories(points={'response':'0.00000005','rate':'0.00000005'})
        self.assertEqual(a.calculate_score(self.rubric,cats),'0.000001')
        cats=self.categories(points={'response':'0.000000049','rate':'0.000000049'})
        self.assertEqual(a.calculate_score(self.rubric,cats),'0')

    def test_repeating_fraction_single_rounding(self):
        rubric=copy.deepcopy(self.rubric)
        for c in rubric['categories']:c['max_points']=3;c['anchors'][-1]['points']=3
        cats=self.categories(rubric,points={'response':'1','rate':'1'})
        self.assertEqual(a.calculate_score(rubric,cats),'33.333333')

    def test_zero_is_valid_not_missing(self):
        cats=self.categories(points={'response':'0','rate':'0'})
        self.assertEqual(a.calculate_score(self.rubric,cats),'0')

    def test_missing_category_no_renormalization(self):
        cats=self.categories();cats.pop()
        self.assertIsNone(a.calculate_score(self.rubric,cats))
        cats=self.categories();cats[0].update(points=None,status='missing')
        self.assertIsNone(a.calculate_score(self.rubric,cats))

    def test_error_category_no_free_points(self):
        cats=self.categories();cats[0].update(points=None,status='error')
        self.assertIsNone(a.calculate_score(self.rubric,cats))

    def test_invalid_points_duplicates_and_types(self):
        for bad in ('11','-1','1.0',True,1.0):
            cats=self.categories();cats[0]['points']=bad
            self.fails(None,a.calculate_score,self.rubric,cats)
        self.fails('assessment_category_duplicate',a.calculate_score,self.rubric,self.categories()*2)

    def test_invalid_weights_rejected(self):
        self.rubric['categories'][0]['weight_bps']=1
        self.fails('weight_sum_invalid',a.calculate_score,self.rubric,self.categories())

    def test_metadata_only_no_implicit_anchor_interpretation(self):
        output=self.assess(rules=())['assessment']
        self.assertEqual(output['status'],'incomplete');self.assertIsNone(output['total_score'])
        self.assertTrue(all(c['points'] is None for c in output['categories']))
        self.assertEqual(output['mandatory_tests'][0]['status'],'passed')

    def test_not_applicable_human_category_is_missing(self):
        self.rubric['revision']+=1;self.rubric['categories'][1]['source']='human'
        output=self.assess()['assessment']
        self.assertEqual(output['status'],'incomplete');self.assertIsNone(output['total_score'])
        self.assertEqual(output['categories'][1]['status'],'missing')

    def test_no_jury_required(self):
        output=self.assess()['assessment']
        self.assertEqual(output['evaluator']['type'],'deterministic')
        self.assertEqual(output['total_score'],'100');self.assertEqual(output['status'],'passed')
        self.assertTrue(output['evidence'])
        self.assertEqual(output['sha256'],d.content_sha256(self.rubric))

    def test_unknown_category_status_rejected(self):
        cats=self.categories();cats[0]['status']='not_applicable'
        self.fails('assessment_category_status_invalid',a.calculate_score,self.rubric,cats)


class GateTests(Case):
    def test_gate_passed(self):
        result=self.assess()['assessment'];self.assertEqual(result['mandatory_tests'][0]['status'],'passed')
        p.validate_result(self.assess()['result'],self.plan)

    def test_gate_failed_beats_high_points(self):
        self.rubric['revision']+=1
        self.rubric['test_suites'][0]['checks'][0]['expected']='failed'
        rules=list(self.rules());rules[0]=a.BinaryCategoryRule(d.content_sha256(self.rubric),'response','response_complete','10','10')
        result=self.assess(rules=tuple(rules))['assessment']
        self.assertEqual(result['total_score'],'100');self.assertEqual(result['status'],'failed')
        self.assertEqual(result['mandatory_tests'][0]['status'],'failed')

    def test_missing_metric_gate_incomplete(self):
        # An explicitly unavailable verifier cannot supply proof of a mandatory check.
        registry=a.TestAdapterRegistry()
        descriptor=a.default_registry().resolve('performance',self.rubric['test_suites'][0])
        registry.register(a.ReadOnlyTestAdapter('performance','performance_checks',1,'synthetic-missing',
                           descriptor.implementation_sha256,lambda execution,suite:[]))
        result=self.assess(registry=registry)['assessment']
        self.assertEqual(result['status'],'incomplete');self.assertIsNone(result['total_score'])
        self.assertEqual(result['mandatory_tests'][0]['status'],'missing')

    def test_gate_unknown_with_complete_other_categories_no_score(self):
        self.rubric['revision']+=1
        self.rubric['test_suites'].append(dict(suite_id='extra',adapter='performance_checks',version=1,
             assets=[],checks=[dict(test_id='extra_gate',metric='execution.status',operator='eq',expected='succeeded')]))
        self.rubric['mandatory_tests']=['extra_gate']
        descriptor=a.default_registry().resolve('performance',self.rubric['test_suites'][0])
        registry=a.TestAdapterRegistry((a.ReadOnlyTestAdapter('performance','performance_checks',1,'synthetic-filter',
           descriptor.implementation_sha256,lambda execution,suite: [] if suite['suite_id']=='extra' else a._reference_checks(execution,suite)),))
        result=self.assess(registry=registry)['assessment']
        self.assertTrue(all(c['status']=='complete' for c in result['categories']))
        self.assertEqual(result['status'],'incomplete');self.assertIsNone(result['total_score'])

    def test_gate_error_not_passed(self):
        descriptor=a.default_registry().resolve('performance',self.rubric['test_suites'][0])
        registry=a.TestAdapterRegistry((a.ReadOnlyTestAdapter('performance','performance_checks',1,'synthetic-error',
            descriptor.implementation_sha256,lambda e,s:[dict(test_id=c['test_id'],status='error',evidence=[]) for c in s['checks']]),))
        result=self.assess(registry=registry)['assessment']
        self.assertEqual(result['mandatory_tests'][0]['status'],'error');self.assertEqual(result['status'],'incomplete')

    def test_failed_gate_and_missing_categories_stays_failed(self):
        self.rubric['revision']+=1;self.rubric['test_suites'][0]['checks'][0]['expected']='failed'
        result=self.assess(rules=())['assessment']
        self.assertEqual(result['status'],'failed');self.assertIsNone(result['total_score'])

    def test_no_arbitrary_pass_mark(self):
        rules=self.rules(response='0',rate='0')
        result=self.assess(rules=rules)['assessment']
        self.assertEqual(result['status'],'passed');self.assertEqual(result['total_score'],'0')


class EvidenceTests(Case):
    def registry(self,verifier):
        desc=a.default_registry().resolve('performance',self.rubric['test_suites'][0])
        return a.TestAdapterRegistry((a.ReadOnlyTestAdapter('performance','performance_checks',1,'synthetic',
                                                          desc.implementation_sha256,verifier),))

    def test_duplicate_evidence_ids_rejected(self):
        def duplicate(e,s):
            rows=a._reference_checks(e,s);rows[0]['evidence']*=2;return rows
        self.fails('evidence_duplicate',self.assess,registry=self.registry(duplicate))

    def test_duplicate_test_ids_rejected(self):
        self.fails('test_evidence_duplicate',self.assess,
                   registry=self.registry(lambda e,s:a._reference_checks(e,s)*2))

    def test_contradictory_test_status_rejected(self):
        def false(e,s):
            rows=a._reference_checks(e,s);rows[0]['status']='failed';return rows
        self.fails('test_evidence_contradictory',self.assess,registry=self.registry(false))

    def test_missing_evidence_for_pass_rejected(self):
        def missing(e,s):
            rows=a._reference_checks(e,s);rows[0]['evidence']=[];return rows
        self.fails('test_evidence_missing',self.assess,registry=self.registry(missing))

    def test_unknown_evidence_reference_rejected(self):
        def unknown(e,s):
            rows=a._reference_checks(e,s);rows[0]['evidence']=[str(uuid.uuid4())];return rows
        self.fails('evidence_reference_missing',self.assess,registry=self.registry(unknown))

    def test_unknown_test_identity_rejected(self):
        self.fails('test_evidence_unknown',self.assess,
                   registry=self.registry(lambda e,s:[dict(test_id='unknown',status='passed',evidence=[])]))

    def test_unsupported_adapter_registry(self):
        self.fails('test_adapter_unsupported',self.assess,registry=a.TestAdapterRegistry())
        self.rubric['test_suites'][0]['adapter']='shell'
        self.fails('test_adapter_unsupported',self.assess)

    def test_untrusted_code_adapter_registration_blocked(self):
        desc=a.ReadOnlyTestAdapter('performance','performance_checks',1,'unsafe','a'*64,lambda e,s:[],True)
        self.fails('test_execution_isolation_unavailable',a.TestAdapterRegistry,(desc,))

    def test_unsupported_discipline(self):
        self.rubric['discipline']='coding'
        self.fails('discipline_unsupported',self.assess)

    def test_rule_bound_to_rubric_and_test(self):
        rules=list(self.rules())
        rules[0]=a.BinaryCategoryRule('b'*64,'response','response_complete','10','0')
        self.fails('category_rule_rubric_mismatch',self.assess,rules=rules)
        rules[0]=a.BinaryCategoryRule(d.content_sha256(self.rubric),'response','minimum_rate','10','0')
        self.fails('category_rule_test_mismatch',self.assess,rules=rules)

    def test_source_claim_cannot_award_points(self):
        claimed=copy.deepcopy(self.original);e=claimed['executions'][0]['execution']
        e['metrics']['tokens_per_second']='11';e['metrics']['eval_count']=22
        claimed['executions'][0]['sha256']=d.content_sha256(e)
        self.fails('execution_source_mismatch',self.assess,result=claimed)

    def test_wrong_result_hash(self):
        self.fails('content_hash_mismatch',self.assess,result=self.original,expected_result_sha256='f'*64)

    def test_wrong_plan_binding(self):
        result=copy.deepcopy(self.original);result['plan_sha256']='f'*64
        self.fails('result_plan_mismatch',self.assess,result=result)

    def test_wrong_rubric_revision_and_pin(self):
        wrong=copy.deepcopy(self.rubric);wrong['revision']+=1
        self.fails('content_hash_mismatch',a.assess,self.source,self.repo,self.plan,self.aid,wrong,
                   expected_rubric_sha256=d.content_sha256(self.rubric))
        wrong=copy.deepcopy(self.rubric);wrong['categories'][0]['name']='changed without revision'
        self.fails('revision_conflict',self.assess,rubric=wrong)

    def test_invalid_rubric_weights(self):
        self.rubric['categories'][0]['weight_bps']=10
        self.fails('weight_sum_invalid',self.assess)

    def test_corrupt_source_artifact(self):
        artifact=self.original['executions'][0]['execution']['artifacts'][0]
        file=self.source_root/artifact['path'];file.chmod(0o600);file.write_bytes(b'bad')
        self.fails(None,self.assess)
        self.assertEqual(self.repo._names(),[])

    def test_corrupt_source_journal(self):
        file=self.source_root/'journals'/self.plan.as_dict()['run_id']/'00000004.json'
        row=d.load_json(file);row['sha256']='f'*64;file.chmod(0o600);file.write_bytes(d.canonical_json_bytes(row))
        self.fails('content_hash_mismatch',self.assess)

    def test_source_head_pin(self):
        self.fails('journal_head_mismatch',self.assess,expected_head='f'*64)


class PersistenceTests(Case):
    def test_idempotent_order_same_identity_timestamp_bytes(self):
        first=self.assess();before=self.snapshot(self.archive_root)
        again=self.assess()
        self.assertTrue(again['idempotent']);self.assertFalse(first['idempotent'])
        self.assertEqual(first['assessment'],again['assessment']);self.assertEqual(first['result'],again['result'])
        self.assertEqual(before,self.snapshot(self.archive_root))

    def test_reevaluation_new_rubric_originals_unchanged(self):
        original_source=self.snapshot();first=self.assess();before=self.snapshot(self.archive_root)
        self.rubric['revision']+=1;self.rubric['categories'][0]['weight_bps']=5000
        self.rubric['categories'][1]['weight_bps']=5000
        second=self.assess(supersedes=first['assessment']['assessment_id'])
        self.assertNotEqual(first['assessment']['assessment_id'],second['assessment']['assessment_id'])
        self.assertEqual(second['assessment']['supersedes'],first['assessment']['assessment_id'])
        self.assertEqual(len(second['result']['assessments']),2)
        self.assertEqual(original_source,self.snapshot())
        self.assertEqual(before,{name:self.snapshot(self.archive_root)[name] for name in before})
        self.assertEqual(second['assessment'],self.assess(supersedes=first['assessment']['assessment_id'])['assessment'])

    def test_explicit_new_request_keeps_old_certificate(self):
        first=self.assess();second=self.assess(request_id=str(uuid.uuid4()))
        self.assertNotEqual(first['assessment']['assessment_id'],second['assessment']['assessment_id'])
        self.assertEqual(len(second['result']['assessments']),2)
        self.assertEqual(self.repo.read(first['assessment']['assessment_id'])['assessment'],first['assessment'])

    def test_no_source_or_existing_artifact_modification(self):
        before=self.snapshot();self.assess();self.assertEqual(before,self.snapshot())

    def test_atomic_write_failure_before_publish_blocks_retry(self):
        def stop(name):
            if name=='file_synced':raise KeyboardInterrupt
        with patch.object(w,'_checkpoint',stop):
            with self.assertRaises(KeyboardInterrupt):self.assess()
        self.archive.__exit__()
        with w.WorkspaceStore(self.archive_root,create=False) as reopened:
            self.fails('assessment_publication_uncertain',a.AssessmentRepository,reopened)

    def test_lost_ack_after_publish_recovers_existing_no_overwrite(self):
        def stop(name):
            if name=='published_before_fsync':raise KeyboardInterrupt
        with patch.object(w,'_checkpoint',stop):
            with self.assertRaises(KeyboardInterrupt):self.assess()
        files=[p for p in (self.archive_root/'artifacts').glob('*.json') if p.name!='assessment-store.json']
        self.assertEqual(len(files),1);before=files[0].read_bytes()
        self.archive.__exit__()
        with w.WorkspaceStore(self.archive_root,create=False) as reopened:
            repo=a.AssessmentRepository(reopened)
            result=a.assess(self.source,repo,self.plan,self.aid,self.rubric,
                expected_rubric_sha256=d.content_sha256(self.rubric),rules=self.rules())
            self.assertTrue(result['idempotent']);self.assertEqual(files[0].read_bytes(),before)

    def test_fsync_failure_never_returns_success(self):
        actual=os.fsync;published=[False]
        def checkpoint(name):
            if name=='published_before_fsync':published[0]=True
        def sync(fd):
            if published[0]:raise OSError('synthetic storage failure')
            return actual(fd)
        with patch.object(w,'_checkpoint',checkpoint),patch.object(os,'fsync',sync):
            self.fails('storage_commit_uncertain',self.assess)

    def test_source_and_assessment_writer_locks(self):
        self.fails('writer_busy',w.WorkspaceStore(self.source_root,create=False).__enter__)
        self.fails('writer_busy',w.WorkspaceStore(self.archive_root,create=False).__enter__)

    def test_original_source_cannot_be_used_as_assessment_repository(self):
        self.fails('assessment_store_incompatible',a.AssessmentRepository,self.source)

    def test_bogus_supersedes(self):
        self.fails('assessment_history_missing',self.assess,supersedes=str(uuid.uuid4()))

    def test_rollback_rubric_in_reassessment(self):
        self.rubric['revision']=3;first=self.assess()
        self.rubric['revision']=2
        self.fails('revision_rollback',self.assess,supersedes=first['assessment']['assessment_id'])

    def test_tampered_assessment_rehashed_is_rejected(self):
        result=self.assess();file=self.archive_root/'artifacts'/(result['assessment']['assessment_id']+'.json')
        record=d.load_json(file);record['assessment']['categories'][0]['points']='5'
        record['assessment']['total_score']='65';record['assessment_sha256']=d.content_sha256(record['assessment'])
        file.chmod(0o600);file.write_bytes(d.canonical_json_bytes(record))
        self.fails('assessment_evidence_mismatch',self.assess)

    def test_record_pin_and_filename_hash(self):
        result=self.assess();self.repo.read(result['assessment']['assessment_id'],expected_sha256=result['record_sha256'])
        self.fails('content_hash_mismatch',self.repo.read,result['assessment']['assessment_id'],expected_sha256='f'*64)
        file=self.archive_root/'artifacts'/(result['assessment']['assessment_id']+'.json')
        other=self.archive_root/'artifacts'/(str(uuid.uuid4())+'.json');shutil.copyfile(file,other)
        self.fails('assessment_identity_mismatch',self.assess)

    def test_extra_or_missing_record_fields_rejected(self):
        result=self.assess();file=self.archive_root/'artifacts'/(result['assessment']['assessment_id']+'.json')
        record=d.load_json(file);record['unexpected']='not a contract field'
        file.chmod(0o600);file.write_bytes(d.canonical_json_bytes(record))
        self.fails('unknown_field',self.assess)

    def test_same_rubric_id_new_revision_without_supersedes_retains_history(self):
        first=self.assess();self.rubric['revision']+=1
        result=self.assess();self.assertEqual(len(result['result']['assessments']),2)
        self.assertIsNone(result['assessment']['supersedes'])
        self.assertNotEqual(first['assessment']['assessment_id'],result['assessment']['assessment_id'])

    def test_no_model_or_agent_calls_during_assessment(self):
        with patch.object(o.OllamaAdapter,'execute',side_effect=AssertionError('model work forbidden')), \
             patch.object(o.RunCoordinator,'run',side_effect=AssertionError('execution forbidden')):
            self.assess()


class AdditionalTests(Case):
    def test_independent_numeric_golden_vectors(self):
        for vector in d.load_json(ROOT/'tests/fixtures/assessment/score-vectors.json'):
            rubric=copy.deepcopy(self.rubric);categories=[]
            for index,category in enumerate(rubric['categories']):
                category['weight_bps']=vector['weights'][index];category['max_points']=vector['maxima'][index]
                category['anchors'][-1]['points']=category['max_points']
                points=vector['points'][index]
                categories.append(dict(category_id=category['category_id'],points=points,
                                       status='missing' if points is None else 'complete',evidence=[]))
            self.assertEqual(a.calculate_score(rubric,categories),vector['expected'])

    def test_metadata_with_nonempty_test_assets_is_not_executed(self):
        assets=self.folder/'rubric-assets';assets.mkdir();data=b'never execute this test package\n'
        (assets/'test.txt').write_bytes(data)
        self.rubric['revision']+=1
        self.rubric['test_suites'][0]['assets']=[dict(path='test.txt',role='test',size_bytes=len(data),sha256=d.hashlib.sha256(data).hexdigest())]
        output=self.assess(rubric_asset_root=assets)['assessment']
        self.assertEqual(output['mandatory_tests'][0]['status'],'missing')
        self.assertEqual(output['status'],'incomplete');self.assertIsNone(output['total_score'])

    def test_uncertain_execution_is_not_assessable(self):
        value=self.plan.as_dict();value['run_id']=str(uuid.uuid4())
        plan=p.validate_run_plan(value,self.c,self.r,asset_root=S1/'assets')
        self.source.register_run(plan,asset_root=S1/'assets')
        fake=FakeOllama();fake.fail=(1,TimeoutError('synthetic unknown outcome'))
        report=o.RunCoordinator(self.source,plan).run(o.OllamaAdapter(fake))
        attempt=report['result']['executions'][0]['execution']['attempt_id']
        self.fails('execution_not_terminal',a.assess,self.source,self.repo,plan,attempt,self.rubric,
                   expected_rubric_sha256=d.content_sha256(self.rubric),rules=self.rules())
        self.assertEqual(self.repo._names(),[])

    def test_confirmation_failure_requires_fresh_writer(self):
        actual=os.fsync;completed=[False]
        def checkpoint(name):
            if name=='publication_synced':completed[0]=True
        def fail_confirm(fd):
            if completed[0]:raise OSError('synthetic confirmation loss')
            return actual(fd)
        with patch.object(w,'_checkpoint',checkpoint),patch.object(os,'fsync',fail_confirm):
            self.fails('assessment_durability_unknown',self.assess)
        self.assertTrue(self.archive.poisoned)
        self.fails('store_write_uncertain',self.assess)
        self.archive.__exit__()
        with w.WorkspaceStore(self.archive_root,create=False) as archive:
            result=a.assess(self.source,a.AssessmentRepository(archive),self.plan,self.aid,self.rubric,
                           expected_rubric_sha256=d.content_sha256(self.rubric),rules=self.rules())
            self.assertTrue(result['idempotent'])

    def test_idempotence_survives_later_confirmed_attempts_and_certificates(self):
        value=self.plan.as_dict();value['run_id']=str(uuid.uuid4());value['repetitions']=2
        plan=p.validate_run_plan(value,self.c,self.r,asset_root=S1/'assets')
        self.source.register_run(plan,asset_root=S1/'assets');fake=FakeOllama()
        coordinator=o.RunCoordinator(self.source,plan)
        def pause(name):
            if name=='s4_attempt_committed':raise KeyboardInterrupt
        with patch.object(w,'_checkpoint',pause):
            with self.assertRaises(KeyboardInterrupt):coordinator.run(o.OllamaAdapter(fake))
        first_attempt=coordinator.inspect()['result']['executions'][0]['execution']['attempt_id']
        kwargs=dict(expected_rubric_sha256=d.content_sha256(self.rubric),rules=self.rules())
        first=a.assess(self.source,self.repo,plan,first_attempt,self.rubric,**kwargs)
        completed=coordinator.run(o.OllamaAdapter(fake),resume=True)
        second_attempt=completed['result']['executions'][1]['execution']['attempt_id']
        second=a.assess(self.source,self.repo,plan,second_attempt,self.rubric,**kwargs)
        again=a.assess(self.source,self.repo,plan,second_attempt,self.rubric,**kwargs)
        self.assertTrue(again['idempotent']);self.assertEqual(second['assessment'],again['assessment'])
        old_again=a.assess(self.source,self.repo,plan,first_attempt,self.rubric,**kwargs)
        self.assertEqual(old_again['assessment'],first['assessment'])
        self.assertEqual(len(old_again['result']['assessments']),2)
        self.assertEqual(fake.generations,2)

    def test_real_verified_missing_metric_does_not_pass_gate(self):
        value=self.plan.as_dict();value['run_id']=str(uuid.uuid4())
        plan=p.validate_run_plan(value,self.c,self.r,asset_root=S1/'assets')
        self.source.register_run(plan,asset_root=S1/'assets');fake=FakeOllama()
        fake.modify=lambda response,n:dict(response,eval_count=None)
        source=o.RunCoordinator(self.source,plan).run(o.OllamaAdapter(fake))['result']
        attempt=source['executions'][0]['execution']['attempt_id']
        target=copy.deepcopy(self.rubric);target['revision']+=1;target['mandatory_tests']=['minimum_rate']
        result=a.assess(self.source,self.repo,plan,attempt,target,
            expected_rubric_sha256=d.content_sha256(target),rules=self.rules(target))['assessment']
        self.assertEqual(result['mandatory_tests'][0]['status'],'missing')
        self.assertEqual(result['status'],'incomplete');self.assertIsNone(result['total_score'])
        self.assertIsNone(result['categories'][1]['points'])

    def test_terminal_failed_source_is_assessable_without_model_retry(self):
        value=self.plan.as_dict();value['run_id']=str(uuid.uuid4())
        plan=p.validate_run_plan(value,self.c,self.r,asset_root=S1/'assets')
        self.source.register_run(plan,asset_root=S1/'assets');fake=FakeOllama();fake.present=False
        source=o.RunCoordinator(self.source,plan).run(o.OllamaAdapter(fake))['result']
        self.assertEqual(source['status'],'failed')
        attempt=source['executions'][0]['execution']['attempt_id']
        result=a.assess(self.source,self.repo,plan,attempt,self.rubric,
            expected_rubric_sha256=d.content_sha256(self.rubric),rules=self.rules())['assessment']
        self.assertEqual(result['status'],'failed');self.assertIsNone(result['total_score'])
        self.assertEqual(result['categories'][0]['points'],'0');self.assertEqual(fake.generations,0)

    def test_known_revision_cannot_change_without_supersedes_and_old_order_is_idempotent(self):
        old_rubric=copy.deepcopy(self.rubric);first=self.assess()
        self.rubric['revision']=2;self.assess()
        before=self.snapshot(self.archive_root)
        changed=copy.deepcopy(self.rubric);changed['categories'][0]['name']='different same revision'
        self.fails('revision_conflict',self.assess,rubric=changed)
        self.assertEqual(before,self.snapshot(self.archive_root))
        old_again=self.assess(rubric=old_rubric)
        self.assertTrue(old_again['idempotent']);self.assertEqual(old_again['assessment'],first['assessment'])
        self.fails('revision_rollback',self.assess,rubric=old_rubric,request_id=str(uuid.uuid4()))

    def test_unknown_metric_cannot_be_claimed_passed(self):
        execution=copy.deepcopy(self.original['executions'][0]['execution'])
        execution['metrics']['tokens_per_second']=None
        suite=self.rubric['test_suites'][1]
        self.assertEqual(a._reference_checks(execution,suite)[0]['status'],'missing')
        self.assertNotEqual(a._reference_checks(execution,suite)[0]['status'],'passed')

    def test_evidence_that_omits_outcome_is_rejected(self):
        descriptor=a.default_registry().resolve('performance',self.rubric['test_suites'][0])
        def unsupported(e,s):
            rows=a._reference_checks(e,s)
            binding=next(x['artifact_id'] for x in e['artifacts'] if x['path'].endswith('/binding.json'))
            for row in rows:row['evidence']=[binding]
            return rows
        registry=a.TestAdapterRegistry((a.ReadOnlyTestAdapter('performance','performance_checks',1,'limited-proof',
                     descriptor.implementation_sha256,unsupported),))
        self.fails('test_evidence_incomplete',self.assess,registry=registry)

    def test_result_projection_keeps_execution_bytes_and_status(self):
        output=self.assess()
        self.assertEqual(output['result']['executions'],self.original['executions'])
        self.assertEqual(output['result']['status'],self.original['status'])
        p.validate_result(output['result'],self.plan,previous=self.original)

    def test_new_rubric_uuid_allowed_without_plan_mutation(self):
        self.rubric['rubric_id']=str(uuid.uuid4());self.rubric['revision']=1
        old_plan=self.plan.sha256;output=self.assess()
        self.assertEqual(output['assessment']['rubric_id'],self.rubric['rubric_id'])
        self.assertEqual(self.plan.sha256,old_plan)
        p.validate_result(output['result'],self.plan,assessment_rubrics=[self.rubric])

    def test_wrong_revision_same_hash_rule_rejected(self):
        rules=self.rules();self.rubric['revision']+=1
        self.fails('category_rule_rubric_mismatch',self.assess,rules=rules)

    def test_case_sensitive_duplicate_registry_and_invalid_code_flag(self):
        descriptor=a.default_registry().resolve('performance',self.rubric['test_suites'][0])
        registry=a.TestAdapterRegistry((descriptor,))
        self.fails('test_adapter_duplicate',registry.register,descriptor)
        unsupported=a.ReadOnlyTestAdapter('performance','unknown',1,'unknown','a'*64,lambda e,s:[])
        self.fails('test_adapter_unsupported',registry.register,unsupported)

    def test_corrupt_assessment_input_json_rejected(self):
        first=self.assess();file=self.archive_root/'artifacts'/(first['assessment']['assessment_id']+'.json')
        file.chmod(0o600);file.write_bytes(b'{"duplicated":1,"duplicated":2}')
        self.fails('json_duplicate_key',self.assess)

    def test_partial_unpublished_record_remains_preserved(self):
        file=self.archive_root/'artifacts'/'.s3-unfinished.tmp';file.write_bytes(b'partial')
        before=self.snapshot(self.archive_root)
        self.fails('assessment_publication_uncertain',self.assess)
        self.assertEqual(before,self.snapshot(self.archive_root))

    def test_symlink_and_hardlink_record_rejected(self):
        first=self.assess();file=self.archive_root/'artifacts'/(first['assessment']['assessment_id']+'.json')
        saved=self.folder/'saved.json';file.rename(saved);file.symlink_to(saved)
        self.fails('file_unsafe',self.assess)
        file.unlink();os.link(saved,file)
        self.fails('file_unsafe',self.assess)

    def test_assessment_file_is_private_and_normal(self):
        first=self.assess();file=self.archive_root/'artifacts'/(first['assessment']['assessment_id']+'.json')
        self.assertEqual(file.stat().st_mode & 0o777,0o400)
        self.assertEqual(file.stat().st_nlink,1)
        self.assertEqual(self.archive_root.stat().st_mode & 0o777,0o700)

    def test_repository_byte_limit(self):
        self.assess()
        with patch.object(a,'MAX_REPOSITORY_BYTES',1):
            self.fails('assessment_repository_size_limit',self.assess)

    def test_sidecar_method_tampering_rejected(self):
        first=self.assess();file=self.archive_root/'artifacts'/(first['assessment']['assessment_id']+'.json')
        record=d.load_json(file);record['method']['rules'][0]['passed_points']='1'
        file.chmod(0o600);file.write_bytes(d.canonical_json_bytes(record))
        self.fails('content_hash_mismatch',self.assess)

    def test_source_pin_and_original_result_file_validation(self):
        path=self.folder/'source-result.json';path.write_bytes(d.canonical_json_bytes(self.original))
        verified=a.verify_run(self.source,self.plan,result=d.load_json(path),expected_result_sha256=d.content_sha256(self.original))
        self.assertEqual(verified.result(),self.original)
        altered=d.load_json(path);altered['plan_sha256']='a'*64;path.write_bytes(d.canonical_json_bytes(altered))
        self.fails('result_plan_mismatch',self.assess,result=d.load_json(path))

    def test_unsupported_qualitative_category_rule_cannot_assign_points(self):
        self.rubric['revision']+=1;self.rubric['categories'][0]['source']='llm_jury'
        rule=a.BinaryCategoryRule(d.content_sha256(self.rubric),'response','response_complete','10','0')
        self.fails('category_rule_not_applicable',self.assess,rules=(rule,))

    def test_explicit_cli_offline_roundtrip_and_exitcodes(self):
        planfile=self.folder/'plan.json';planfile.write_bytes(p.serialize_run_plan(self.plan))
        args=['--source',str(self.source_root),'--archive',str(self.archive_root),'--plan',str(planfile),
              '--competition',str(S1/'competition.json'),'--rubric',str(S1/'rubric.json'),
              '--target-rubric',str(S1/'rubric.json'),'--assets',str(S1/'assets'),
              '--expected-plan-sha256',self.plan.sha256,'--expected-rubric-sha256',d.content_sha256(self.rubric),
              '--attempt-id',self.aid]
        self.source.__exit__();self.archive.__exit__();out=io.StringIO()
        with contextlib.redirect_stdout(out):self.assertEqual(a.main(args),1)
        self.assertEqual(json.loads(out.getvalue())['assessment']['status'],'incomplete')
        for rule in self.rules():args+=['--rule',rule.category_id,rule.test_id,rule.passed_points,rule.failed_points]
        out=io.StringIO()
        with contextlib.redirect_stdout(out):self.assertEqual(a.main(args),0)
        result=json.loads(out.getvalue());self.assertEqual(result['assessment']['status'],'passed')
        self.assertNotIn(str(self.source_root),out.getvalue());self.assertNotIn(self.c['prompt']['text'],out.getvalue())
        out=io.StringIO()
        with contextlib.redirect_stdout(out):self.assertEqual(a.main(args),0)
        self.assertTrue(json.loads(out.getvalue())['idempotent'])

    def test_cli_errors_and_overlapping_roots_are_safe(self):
        err=io.StringIO()
        with contextlib.redirect_stderr(err):self.assertEqual(a.main([]),2)
        self.assertEqual(json.loads(err.getvalue())['code'],'cli_arguments_invalid')
        planfile=self.folder/'plan.json';planfile.write_bytes(p.serialize_run_plan(self.plan))
        args=['--source',str(self.source_root),'--archive',str(self.source_root/'nested'),
              '--plan',str(planfile),'--competition',str(S1/'competition.json'),'--rubric',str(S1/'rubric.json'),
              '--target-rubric',str(S1/'rubric.json'),'--assets',str(S1/'assets'),'--attempt-id',self.aid,
              '--expected-plan-sha256',self.plan.sha256,'--expected-rubric-sha256',d.content_sha256(self.rubric)]
        err=io.StringIO()
        with contextlib.redirect_stderr(err):self.assertEqual(a.main(args),2)
        self.assertEqual(json.loads(err.getvalue())['code'],'assessment_roots_overlap')
        self.assertFalse((self.source_root/'nested').exists())

    def test_future_assessment_time_is_not_silently_backdated(self):
        with patch.object(a,'utc_now',return_value='2000-01-01T00:00:00Z'):
            self.fails('assessment_clock_invalid',self.assess)
        self.assertEqual(self.repo._names(),[])


if __name__=='__main__':unittest.main()
