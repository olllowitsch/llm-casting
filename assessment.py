#!/usr/bin/env python3
"""S5 read-only evidence assessment. No HTTP, untrusted code, processes or jury."""
import argparse
from dataclasses import dataclass
from fractions import Fraction
import json
import os
import stat
from pathlib import Path
import sys
import uuid

import definitions as d
import planning as p
import workspaces as w
from ollama_adapter import RunCoordinator

VERSION = 's5-v1'
NAMESPACE = uuid.UUID('35b692ef-6059-4cc8-8957-07d29fe85441')
MARKER = dict(kind='assessment_repository', schema_version=1)
MAX_RECORDS = 1000
MAX_REPOSITORY_BYTES = 64*1024*1024
MAX_BITS = 16384


def _need(value, code):
    d.require(value, code)


def utc_now():
    return w._now()


def _build():
    parent = d._open_directory(w.ROOT)
    try:
        files = []
        for name in ('assessment.py', 'definitions.py', 'planning.py', 'workspaces.py', 'ollama_adapter.py'):
            data, _ = d._read_fd(parent, name, 1024*1024)
            files.append(dict(path=name, sha256=d.hashlib.sha256(data).hexdigest()))
        return dict(version=VERSION, files=files)
    finally:
        os.close(parent)


def _rubric(value):
    value = p._copy(value)
    d._rubric_shape(value, d.DEFAULT_REGISTRY, d.DEFAULT_LIMITS)
    _need(value['discipline'] == 'performance', 'assessment_discipline_unsupported')
    _need(len(value['categories']) <= 128, 'assessment_category_limit')
    return value


def _number(value):
    d.validate_decimal_string(value, nonnegative=True)
    _need(len(value) <= 2048, 'assessment_decimal_limit')
    return Fraction(value)


def calculate_score(rubric, categories):
    """Pure arithmetic only, not an evidence verifier or authority to award points."""
    rubric = _rubric(rubric)
    categories = p._copy(categories)
    d._list(categories, '$.categories')
    known = {c['category_id']: c for c in rubric['categories']}
    seen = {};total = Fraction(0)
    for cat in categories:
        d._object(cat, ('category_id', 'points', 'status', 'evidence'), '$.categories[]')
        _need(type(cat['category_id']) is str and cat['category_id'] in known, 'assessment_category_unknown')
        _need(cat['category_id'] not in seen, 'assessment_category_duplicate')
        seen[cat['category_id']] = cat
        _need(cat['status'] in ('complete', 'missing', 'error'), 'assessment_category_status_invalid')
        _need((cat['status'] == 'complete') == (cat['points'] is not None), 'assessment_category_inconsistent')
        d._list(cat['evidence'], '$.evidence')
        if cat['points'] is None:
            continue
        points = _number(cat['points']);definition = known[cat['category_id']]
        _need(points <= definition['max_points'], 'assessment_points_invalid')
        term = Fraction(definition['weight_bps'], 100)*points/definition['max_points']
        _need(total.denominator.bit_length()+term.denominator.bit_length() <= MAX_BITS*2,
              'assessment_precision_limit')
        total += term
        _need(max(total.numerator.bit_length(), total.denominator.bit_length()) <= MAX_BITS,
              'assessment_precision_limit')
    if set(seen) != set(known) or any(c['status'] != 'complete' for c in seen.values()):
        return None
    # Exactly one nonnegative ROUND_HALF_UP operation, no decimal context/float.
    q, remainder = divmod(total.numerator*1000000, total.denominator)
    q += int(2*remainder >= total.denominator)
    whole, fraction = divmod(q, 1000000)
    return str(whole) + ('.'+f'{fraction:06d}'.rstrip('0') if fraction else '')


@dataclass(frozen=True)
class BinaryCategoryRule:
    """Explicit trusted adapter policy, never inferred from free-text anchors."""
    rubric_sha256: str
    category_id: str
    test_id: str
    passed_points: str
    failed_points: str

    def as_dict(self):
        return dict(vars(self))


def _reference_checks(execution, suite):
    result = []
    for check in suite['checks']:
        if suite['assets']:
            # This metadata-only adapter cannot interpret or execute test packages.
            status = 'missing'
        else:
            actual = execution['status'] if check['metric'] == 'execution.status' else execution['metrics'][check['metric']]
            if actual is None:
                status = 'missing'
            else:
                expected = check['expected']
                if check['metric'] != 'execution.status':
                    actual = _number(actual);expected = _number(expected)
                matched = {'eq': lambda: actual == expected, 'gte': lambda: actual >= expected,
                           'lte': lambda: actual <= expected}[check['operator']]()
                status = 'passed' if matched else 'failed'
        refs = [a['artifact_id'] for a in execution['artifacts']] if status in ('passed', 'failed') else []
        result.append(dict(test_id=check['test_id'], status=status, evidence=refs))
    return result


@dataclass(frozen=True)
class ReadOnlyTestAdapter:
    discipline: str
    name: str
    version: int
    identity: str
    implementation_sha256: str
    verifier: object
    executes_code: bool = False


class TestAdapterRegistry:
    """Trusted Python registration only. No JSON plugins, shell or module loading."""
    def __init__(self, adapters=()):
        self._adapters = {}
        for adapter in adapters:
            self.register(adapter)

    def register(self, adapter):
        _need(type(adapter) is ReadOnlyTestAdapter and adapter.executes_code is False,
              'test_execution_isolation_unavailable')
        _need(adapter.discipline == 'performance' and adapter.name == 'performance_checks'
              and type(adapter.version) is int and adapter.version == 1, 'test_adapter_unsupported')
        p._label(adapter.identity);d._hash(adapter.implementation_sha256)
        _need(callable(adapter.verifier), 'test_adapter_invalid')
        key = (adapter.discipline, adapter.name, adapter.version)
        _need(key not in self._adapters, 'test_adapter_duplicate')
        self._adapters[key] = adapter

    def resolve(self, discipline, suite):
        key = (discipline, suite['adapter'], suite['version'])
        _need(key in self._adapters, 'test_adapter_unsupported')
        return self._adapters[key]


def default_registry():
    digest = next(x['sha256'] for x in _build()['files'] if x['path'] == 'assessment.py')
    return TestAdapterRegistry((ReadOnlyTestAdapter('performance', 'performance_checks', 1,
                                's5-performance-metadata-v1', digest, _reference_checks),))


def _method(rubric, rules, registry):
    selected = [];seen = set();cats = {c['category_id']: c for c in rubric['categories']}
    suites = {s['suite_id']: s for s in rubric['test_suites']}
    for rule in rules:
        _need(type(rule) is BinaryCategoryRule, 'category_rule_invalid')
        _need(rule.rubric_sha256 == d.content_sha256(rubric), 'category_rule_rubric_mismatch')
        _need(type(rule.category_id) is str and type(rule.test_id) is str, 'category_rule_invalid')
        _need(rule.category_id in cats and rule.category_id not in seen, 'category_rule_duplicate_or_unknown')
        seen.add(rule.category_id);category = cats[rule.category_id]
        _need(category['source'] == 'deterministic' and category.get('test_suite_id') in suites,
              'category_rule_not_applicable')
        _need(rule.test_id in {c['test_id'] for c in suites[category['test_suite_id']]['checks']},
              'category_rule_test_mismatch')
        for value in (rule.passed_points, rule.failed_points):
            _need(_number(value) <= category['max_points'], 'assessment_points_invalid')
        selected.append(rule.as_dict())
    adapters = []
    for suite in rubric['test_suites']:
        adapter = registry.resolve(rubric['discipline'], suite)
        adapters.append(dict(suite_id=suite['suite_id'], identity=adapter.identity,
                             implementation_sha256=adapter.implementation_sha256))
    return dict(build=_build(), rules=sorted(selected, key=lambda x: x['category_id']), adapters=adapters)


def _checks(execution, rubric, registry):
    all_checks = []
    for suite in rubric['test_suites']:
        adapter = registry.resolve(rubric['discipline'], suite)
        reported = p._copy(adapter.verifier(p._copy(execution), p._copy(suite)))
        d._list(reported, '$.checks')
        expected = {c['test_id']: c for c in _reference_checks(execution, suite)}
        found = {}
        for item in reported:
            d._object(item, ('test_id', 'status', 'evidence'), '$.checks[]')
            _need(type(item['test_id']) is str and item['test_id'] in expected, 'test_evidence_unknown')
            _need(item['test_id'] not in found, 'test_evidence_duplicate')
            _need(item['status'] in ('passed', 'failed', 'missing', 'error'), 'test_evidence_status_invalid')
            p._evidence(item['evidence'], execution['artifacts'])
            if item['status'] in ('passed', 'failed'):
                _need(bool(item['evidence']), 'test_evidence_missing')
                _need(item['status'] == expected[item['test_id']]['status'], 'test_evidence_contradictory')
                supporting={a['artifact_id'] for a in execution['artifacts'] if a['path'].endswith('/outcome.json')}
                _need(bool(supporting.intersection(item['evidence'])),'test_evidence_incomplete')
            found[item['test_id']] = item
        for check in suite['checks']:
            all_checks.append(found.get(check['test_id'], dict(test_id=check['test_id'],status='missing',evidence=[])))
    return all_checks


def evaluate(execution, rubric, *, rules=(), registry=None):
    """Evaluate a structurally validated terminal execution. No persistence/authority."""
    rubric = _rubric(rubric)
    rules = tuple(rules)
    execution = p._copy(execution)
    p.validate_metrics(execution['metrics'])
    _need(execution['status'] in p.TERMINAL, 'execution_not_terminal')
    registry = registry if registry is not None else default_registry()
    method = _method(rubric, rules, registry)
    checks = _checks(execution, rubric, registry);by_test = {c['test_id']: c for c in checks}
    result = _evaluate_checks(rubric, tuple(rules), checks)
    return dict(result, method=method)


def _evaluate_checks(rubric, rules, checks):
    by_test = {c['test_id']: c for c in checks}
    by_category = {r.category_id: r for r in rules}
    categories = []
    for category in rubric['categories']:
        rule = by_category.get(category['category_id'])
        item = dict(category_id=category['category_id'], points=None, status='missing', evidence=[])
        if rule is not None:
            check = by_test[rule.test_id]
            if check['status'] in ('passed', 'failed'):
                item.update(points=rule.passed_points if check['status']=='passed' else rule.failed_points,
                            status='complete', evidence=p._copy(check['evidence']))
            else:
                item.update(status=check['status'], evidence=p._copy(check['evidence']))
        categories.append(item)
    gates = [p._copy(by_test[test]) for test in rubric['mandatory_tests']]
    score = calculate_score(rubric, categories)
    # Known gate failure takes priority even when another gate/category is missing.
    if any(g['status']=='failed' for g in gates):status='failed'
    elif score is None or any(g['status']!='passed' for g in gates):status='incomplete';score=None
    else:status='passed'
    return dict(categories=categories, mandatory_tests=gates, status=status, total_score=score,
                checks=checks)


@dataclass(frozen=True)
class VerifiedRun:
    plan: p.PinnedPlan
    _result: bytes
    head_sha256: str

    def result(self):
        return d.parse_json_bytes(self._result)


def verify_run(source, plan, *, result=None, expected_result_sha256=None, expected_head=None):
    """Real S1/S2/S3/S4 verification; never calls RunCoordinator.run or HTTP."""
    p._context(plan)
    folder = source.root/'journals'/plan.as_dict()['run_id']
    p.validate_run_plan(plan.as_dict(),plan.competition(),plan.rubric(),asset_root=folder/'inputs',
                        rubric_asset_root=folder/'rubric-assets',expected_sha256=plan.sha256)
    report = RunCoordinator(source,plan).inspect(expected_head=expected_head)
    actual = report['result']
    if result is not None:
        claimed = p.validate_result(result,plan,expected_sha256=expected_result_sha256)
        _need(claimed == actual,'execution_source_mismatch')
    elif expected_result_sha256 is not None:
        d.verify_content_sha256(actual,expected_result_sha256)
    return VerifiedRun(plan,d.canonical_json_bytes(actual),report['head_sha256'])


def _execution(verified, attempt_id):
    d._uuid(attempt_id,'$.attempt_id')
    result = p.validate_result(verified.result(),verified.plan)
    matching = [w for w in result['executions'] if w['execution']['attempt_id']==attempt_id]
    _need(len(matching)==1,'assessment_attempt_missing')
    _need(matching[0]['execution']['status'] in p.TERMINAL,'execution_not_terminal')
    return matching[0]


def _project(result, plan, assessments, rubrics):
    projected = p._copy(result)
    projected['assessments'] = p._copy(assessments)
    if assessments:
        projected['updated_at'] = max([result['updated_at']]+[a['created_at'] for a in assessments], key=p._timestamp)
    return p.validate_result(projected,plan,assessment_rubrics=rubrics)


class AssessmentRepository:
    """Dedicated S3 primitive store, immutable single-file records, NO second journal."""
    def __init__(self, store):
        self.store = store
        _need(not store._names('journals') and not store._names('workspaces'),'assessment_store_incompatible')
        names = store._names('artifacts')
        if not names:
            store._json('artifacts/assessment-store.json',MARKER)
        self._names()
        _need(store._json_read('artifacts/assessment-store.json')==MARKER,'assessment_store_incompatible')

    def _names(self):
        names = self.store._names('artifacts')
        _need('assessment-store.json' in names,'assessment_publication_uncertain')
        docs = [];total=0
        for name in names:
            if name == 'assessment-store.json':continue
            _need(name.endswith('.json'),'assessment_publication_uncertain')
            try:d._uuid(name[:-5],'$.assessment_id')
            except d.DefinitionError:raise d.DefinitionError('assessment_publication_uncertain') from None
            with self.store._dir('artifacts') as folder:
                info=os.stat(name,dir_fd=folder,follow_symlinks=False)
                _need(stat.S_ISREG(info.st_mode) and info.st_nlink==1,'file_unsafe')
                _need(info.st_dev==os.fstat(self.store.fd).st_dev,'filesystem_boundary')
                _need(info.st_size<=d.DEFAULT_LIMITS.max_json_bytes,'json_size_limit')
                total+=info.st_size
                _need(total<=MAX_REPOSITORY_BYTES,'assessment_repository_size_limit')
            docs.append(name)
        _need(len(docs)<=MAX_RECORDS,'assessment_record_limit')
        return docs

    def read(self, identity, *, expected_sha256=None):
        d._uuid(identity,'$.assessment_id');self._names()
        record = self.store._json_read('artifacts/'+identity+'.json')
        if expected_sha256 is not None:d.verify_content_sha256(record,expected_sha256)
        d._object(record,('assessment','assessment_sha256','rubric','method','request','source_result',
                         'source_result_sha256','source_head_sha256','checks'),'$.record')
        d._object(record['request'],('plan_sha256','execution_sha256','rubric_sha256','method_sha256',
                                   'supersedes','supersedes_sha256','request_id'),'$.request')
        for key in ('plan_sha256','execution_sha256','rubric_sha256','method_sha256'):
            d._hash(record['request'][key])
        for key in ('supersedes','request_id'):
            if record['request'][key] is not None:d._uuid(record['request'][key],'$.request.'+key)
        if record['request']['supersedes_sha256'] is not None:d._hash(record['request']['supersedes_sha256'])
        _need(record['request']['supersedes']==record['assessment']['supersedes'],'assessment_history_mismatch')
        d.verify_content_sha256(record['method'],record['request']['method_sha256'])
        d.verify_content_sha256(record['assessment'],record['assessment_sha256'])
        d.verify_content_sha256(record['source_result'],record['source_result_sha256'])
        d._hash(record['source_head_sha256'])
        _need(str(uuid.uuid5(NAMESPACE,d.content_sha256(record['request'])))==identity,'assessment_identity_mismatch')
        _need(record['assessment']['assessment_id']==identity,'assessment_identity_mismatch')
        return record

    def _confirm(self, identity, record):
        # Re-establish directory durability after an earlier possibly lost acknowledgement.
        self.store._writable()
        try:
            with self.store._dir('artifacts') as parent:
                os.fsync(parent)
            _need(self.store._json_read('artifacts/'+identity+'.json')==record,'file_changed')
        except OSError:
            self.store.poisoned=True
            raise d.DefinitionError('assessment_durability_unknown') from None
        except BaseException:
            self.store.poisoned=True
            raise

    def publish(self, record):
        self._names()
        identity = record['assessment']['assessment_id']
        _need(identity+'.json' not in self.store._names('artifacts'),'assessment_exists')
        _need(len(self._names())<MAX_RECORDS,'assessment_record_limit')
        self.store._json('artifacts/'+identity+'.json',record)
        self._confirm(identity,record)


def _records(repository, verified):
    records=[]
    for name in repository._names():
        record=repository.read(name[:-5])
        if record['request']['plan_sha256']==verified.plan.sha256:
            records.append(record)
    _need(len(records)<=128,'assessment_history_limit')
    by_id={r['assessment']['assessment_id']:r for r in records}
    rubrics=[_rubric(r['rubric']) for r in records]
    definitions={}
    for rubric in [verified.plan.rubric()]+rubrics:
        key=(rubric['rubric_id'],rubric['revision']);digest=d.content_sha256(rubric)
        _need(key not in definitions or definitions[key]==digest,'revision_conflict')
        definitions[key]=digest
    for record in records:
        request=record['request'];certificate=record['assessment'];rubric=_rubric(record['rubric'])
        _need(d.content_sha256(rubric)==request['rubric_sha256']==certificate['sha256'],'assessment_rubric_mismatch')
        method=record['method']
        d._object(method,('build','rules','adapters'),'$.method')
        d._object(method['build'],('version','files'),'$.build')
        _need(method['build']['version']==VERSION,'assessment_method_unsupported')
        d._list(method['build']['files'],'$.build.files')
        paths=set()
        for item in method['build']['files']:
            d._object(item,('path','sha256'),'$.build.files[]')
            _need(item['path'] not in paths,'assessment_method_invalid');paths.add(item['path']);d._hash(item['sha256'])
        _need(paths=={'assessment.py','definitions.py','planning.py','workspaces.py','ollama_adapter.py'},
              'assessment_method_invalid')
        rules=[]
        d._list(method['rules'],'$.method.rules')
        for row in method['rules']:
            d._object(row,('rubric_sha256','category_id','test_id','passed_points','failed_points'),'$.rule')
            rules.append(BinaryCategoryRule(**row))
        d._list(method['adapters'],'$.adapters')
        _need(len(method['adapters'])==len(rubric['test_suites']),'assessment_method_invalid')
        adapters=[];seen_adapters={}
        for suite,descriptor in zip(rubric['test_suites'],method['adapters']):
            d._object(descriptor,('suite_id','identity','implementation_sha256'),'$.adapter')
            _need(descriptor['suite_id']==suite['suite_id'],'assessment_method_invalid')
            p._label(descriptor['identity']);d._hash(descriptor['implementation_sha256'])
            # Only data checks are replayed; never load historical implementation code.
            def replay(execution, supplied_suite, rows=record['checks']):
                known={c['test_id'] for c in supplied_suite['checks']}
                return [x for x in rows if x['test_id'] in known]
            key=(suite['adapter'],suite['version'])
            declared=(descriptor['identity'],descriptor['implementation_sha256'])
            if key in seen_adapters:
                _need(seen_adapters[key]==declared,'assessment_method_invalid')
            else:
                seen_adapters[key]=declared
                adapters.append(ReadOnlyTestAdapter('performance',suite['adapter'],suite['version'],descriptor['identity'],
                                                    descriptor['implementation_sha256'],replay))
        source=p.validate_result(record['source_result'],verified.plan)
        wrapper=_execution(verified,certificate['attempt_id'])
        _need(wrapper['sha256']==certificate['execution_sha256']==request['execution_sha256'],
              'assessment_execution_mismatch')
        d._list(record['checks'],'$.checks')
        _need(len(record['checks'])==sum(len(s['checks']) for s in rubric['test_suites']),
              'test_evidence_inventory_mismatch')
        registry=TestAdapterRegistry(adapters)
        expected=evaluate(wrapper['execution'],rubric,rules=tuple(rules),registry=registry)
        # Historical build may differ; policy and adapter descriptors must not.
        _need(expected['method']['rules']==method['rules'] and expected['method']['adapters']==method['adapters'],
              'assessment_method_mismatch')
        for key in ('categories','mandatory_tests','status','total_score','checks'):
            _need((record['checks'] if key=='checks' else certificate[key])==expected[key],
                  'assessment_evidence_mismatch')
        _need(certificate['evaluator']==dict(type='deterministic',version=VERSION,
                                            identity='s5-'+d.content_sha256(method)),'assessment_method_mismatch')
        previous=request['supersedes']
        if previous is None:
            _need(request['supersedes_sha256'] is None,'assessment_history_mismatch')
        else:
            _need(previous in by_id and request['supersedes_sha256']==by_id[previous]['assessment_sha256'],
                  'assessment_history_mismatch')
            prior=by_id[previous]['rubric']
            if prior['rubric_id']==rubric['rubric_id']:
                d._revision(rubric,prior,'rubric_id','revision',d.DEFAULT_LIMITS)
        # A historical snapshot may precede later attempts. Validate its own
        # supersession chain here, then the complete current projection below.
        chain=[record];visited={certificate['assessment_id']};node=previous
        while node is not None:
            _need(node in by_id and node not in visited,'assessment_history_mismatch')
            visited.add(node);chain.append(by_id[node]);node=by_id[node]['assessment']['supersedes']
        _project(source,verified.plan,[r['assessment'] for r in reversed(chain)],rubrics)
    _project(verified.result(),verified.plan,[r['assessment'] for r in records],rubrics)
    return records


def assess(source, repository, plan, attempt_id, rubric, *, expected_rubric_sha256,
           rules=(), registry=None, rubric_asset_root=None, supersedes=None, request_id=None,
           expected_head=None, result=None, expected_result_sha256=None):
    """Verify source, calculate, and publish one immutable existing S2 assessment."""
    _need(not repository.store.root.is_relative_to(source.root)
          and not source.root.is_relative_to(repository.store.root),'assessment_roots_overlap')
    verified=verify_run(source,plan,result=result,expected_result_sha256=expected_result_sha256,
                        expected_head=expected_head)
    wrapper=_execution(verified,attempt_id);execution=wrapper['execution']
    d.verify_content_sha256(rubric,expected_rubric_sha256)
    old=plan.rubric()
    target=d.validate_rubric(rubric,asset_root=rubric_asset_root,
                            previous=old if old['rubric_id']==rubric.get('rubric_id') else None)
    _need(target['discipline']==plan.competition()['discipline'],'rubric_discipline_mismatch')
    rules=tuple(rules);registry=registry if registry is not None else default_registry()
    method=_method(target,rules,registry)
    previous_records=_records(repository,verified)
    by_id={r['assessment']['assessment_id']:r for r in previous_records}
    if supersedes is not None:
        d._uuid(supersedes,'$.supersedes')
        _need(supersedes in by_id,'assessment_history_missing')
        _need(by_id[supersedes]['assessment']['attempt_id']==attempt_id,'assessment_history_mismatch')
        prior=by_id[supersedes]['rubric']
        if prior['rubric_id']==target['rubric_id']:
            d.validate_rubric(target,asset_root=rubric_asset_root,previous=prior)
    if request_id is not None:d._uuid(request_id,'$.request_id')
    request=dict(plan_sha256=plan.sha256,execution_sha256=wrapper['sha256'],rubric_sha256=d.content_sha256(target),
                 method_sha256=d.content_sha256(method),supersedes=supersedes,
                 supersedes_sha256=by_id[supersedes]['assessment_sha256'] if supersedes is not None else None,request_id=request_id)
    identity=str(uuid.uuid5(NAMESPACE,d.content_sha256(request)))
    existing=identity+'.json' in repository._names()
    if existing:
        record=repository.read(identity)
        _need(record['request']==request,'assessment_request_conflict')
        created=record['assessment']['created_at']
    else:
        known=[r['rubric'] for r in previous_records if r['rubric']['rubric_id']==target['rubric_id']]
        if known:
            latest=max(known,key=lambda r:r['revision'])
            d._revision(target,latest,'rubric_id','revision',d.DEFAULT_LIMITS)
    evaluated=evaluate(execution,target,rules=rules,registry=registry)
    _need(d.content_sha256(evaluated['method'])==request['method_sha256'],'assessment_method_changed')
    if not existing:
        created=utc_now()
        _need(p._timestamp(created)>=p._timestamp(verified.result()['updated_at']),'assessment_clock_invalid')
        if supersedes is not None:_need(p._timestamp(created)>=p._timestamp(by_id[supersedes]['assessment']['created_at']),
                           'assessment_clock_invalid')
    refs=[a['artifact_id'] for a in execution['artifacts']]
    certificate=dict(kind='assessment',schema_version=1,assessment_id=identity,run_id=execution['run_id'],
        participant_id=execution['participant_id'],attempt_id=attempt_id,execution_sha256=wrapper['sha256'],
        rubric_id=target['rubric_id'],revision=target['revision'],sha256=d.content_sha256(target),
        evaluator=dict(type='deterministic',version=VERSION,identity='s5-'+d.content_sha256(evaluated['method'])),
        created_at=created,categories=evaluated['categories'],mandatory_tests=evaluated['mandatory_tests'],
        status=evaluated['status'],total_score=evaluated['total_score'],supersedes=supersedes,evidence=refs)
    certificates=[x['assessment'] for x in previous_records if x['assessment']['assessment_id']!=identity]+[certificate]
    rubrics=[x['rubric'] for x in previous_records]+[target]
    projected=_project(verified.result(),plan,certificates,rubrics)
    if existing:
        _need(record['assessment']==certificate and record['rubric']==target
              and record['method']==evaluated['method'],'assessment_immutable')
        repository._confirm(identity,record)
    else:
        record=dict(assessment=certificate,assessment_sha256=d.content_sha256(certificate),rubric=target,
                    method=evaluated['method'],request=request,source_result=verified.result(),
                    source_result_sha256=d.content_sha256(verified.result()),source_head_sha256=verified.head_sha256,
                    checks=evaluated['checks'])
        repository.publish(record)
    return dict(assessment=p._copy(certificate),assessment_sha256=record['assessment_sha256'],
                record_sha256=d.content_sha256(record),idempotent=existing,result=projected)


def main(argv=None):
    try:
        parser=w._Parser(description=__doc__)
        for name in ('source','archive','plan','competition','rubric','target-rubric','expected-plan-sha256',
                     'expected-rubric-sha256','attempt-id'):
            parser.add_argument('--'+name,required=True)
        parser.add_argument('--assets');parser.add_argument('--rubric-assets');parser.add_argument('--target-assets')
        parser.add_argument('--expected-head');parser.add_argument('--result');parser.add_argument('--expected-result-sha256')
        parser.add_argument('--supersedes');parser.add_argument('--request-id')
        parser.add_argument('--rule',nargs=4,action='append',default=[],metavar=('CATEGORY','TEST','PASS_POINTS','FAIL_POINTS'))
        args=parser.parse_args(argv)
        source_root=Path(args.source).absolute();archive_root=Path(args.archive).absolute()
        _need(not archive_root.is_relative_to(source_root) and not source_root.is_relative_to(archive_root),
              'assessment_roots_overlap')
        plan=p.validate_run_plan(d.load_json(args.plan),d.load_json(args.competition),d.load_json(args.rubric),
             asset_root=args.assets,rubric_asset_root=args.rubric_assets,expected_sha256=args.expected_plan_sha256)
        target=d.load_json(args.target_rubric)
        rules=tuple(BinaryCategoryRule(args.expected_rubric_sha256,*row) for row in args.rule)
        with w.WorkspaceStore(source_root,create=False) as source:
            verify_run(source,plan,result=d.load_json(args.result) if args.result else None,
                       expected_result_sha256=args.expected_result_sha256,expected_head=args.expected_head)
            with w.WorkspaceStore(archive_root) as archive:
                output=assess(source,AssessmentRepository(archive),plan,args.attempt_id,target,
                    expected_rubric_sha256=args.expected_rubric_sha256,rules=rules,rubric_asset_root=args.target_assets,
                    supersedes=args.supersedes,request_id=args.request_id,expected_head=args.expected_head,
                    result=d.load_json(args.result) if args.result else None,
                    expected_result_sha256=args.expected_result_sha256)
        print(d.canonical_json_bytes(dict(ok=True,**output)).decode('utf-8'))
        return 0 if output['assessment']['status']=='passed' else 1
    except KeyboardInterrupt:
        print(json.dumps(dict(ok=False,code='assessment_publication_uncertain')),file=sys.stderr);return 130
    except d.DefinitionError as error:
        print(json.dumps(dict(ok=False,code=error.code,location=error.location)),file=sys.stderr);return 2
    except (OSError,ValueError,TypeError,KeyError):
        print(json.dumps(dict(ok=False,code='assessment_input_or_storage_invalid')),file=sys.stderr);return 2


if __name__=='__main__':
    sys.exit(main())
