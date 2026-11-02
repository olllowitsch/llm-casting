"""S4: contract adapter over benchmark helpers; S3 remains the only journal writer."""
from decimal import Decimal, localcontext, ROUND_HALF_UP
import json
import math
import os
from pathlib import Path
import socket
import time
import types
import urllib.request
import urllib.error
from urllib.parse import urlsplit

import benchmark as legacy
import definitions as d
import planning as p
import workspaces as w

VERSION = 's4-v1'
ADAPTER_VERSION = 'ollama-s4-v1'
BUILD_FILES = ('benchmark.py', 'definitions.py', 'planning.py', 'workspaces.py', 'ollama_adapter.py', 'casting.py')


def build_manifest():
    files = []
    parent = d._open_directory(legacy.ROOT)
    try:
        for name in BUILD_FILES:
            data, _ = d._read_fd(parent, name, 1024*1024)
            files.append(dict(path=name, size_bytes=len(data), sha256=d.hashlib.sha256(data).hexdigest()))
    finally:
        os.close(parent)
    return dict(kind='engine_build', schema_version=1, version=VERSION, files=files)


def validate_execution_plan(plan):
    v = p._context(plan)
    d.require(plan.competition()['discipline'] == 'performance', 'discipline_unsupported')
    d.require(v['engine'] == dict(version=VERSION, source_sha256=d.content_sha256(build_manifest())),
              'engine_build_mismatch')
    for participant in v['participants']:
        d.require(participant['adapter_version'] == ADAPTER_VERSION, 'adapter_version_mismatch')
        d.require(participant['model']['revision_digest'] is not None, 'model_digest_required')
        temperature = Decimal(participant['parameters']['temperature'])
        wire = float(temperature)
        d.require(math.isfinite(wire) and Decimal(str(wire)) == temperature, 'temperature_not_representable')
    # Reserve upper bounds for the existing S3 event and inventory limits before HTTP.
    prep = v['preparation']
    calls = 1 + int(prep['unload_before']) + int(prep['preload']) + prep['warmup_count']
    files_per_slot = 3 + 2*(2+3*calls)  # binding/running/outcome plus all request/response witnesses
    slots = len(p.measurement_slots(plan))
    d.require(2+4*slots <= w.MAX_EVENTS and slots <= 1000, 's4_event_budget_exceeded')
    d.require(files_per_slot*slots <= min(1000, v['policy']['max_files']), 's4_artifact_budget_exceeded')
    return v


def api_url(value):
    d.require(type(value) is str and value.strip() == value and bool(value), 'api_url_invalid')
    try:
        u = urlsplit(value)
        d.require(u.scheme in ('http', 'https') and u.hostname and u.port != 0
                  and u.username is None and u.password is None and not u.query and not u.fragment
                  and '?' not in value and '#' not in value
                  and u.path in ('', '/'), 'api_url_invalid')
    except ValueError:
        raise d.DefinitionError('api_url_invalid') from None
    return value.rstrip('/')


def _decimal(value):
    text = format(value, 'f')
    return text.rstrip('0').rstrip('.') if '.' in text else text


def project_metrics(response, wall_ns):
    """Map legacy raw metrics into strict S2 units/decimal precision, without defaults."""
    d.require(type(response) is dict, 'ollama_metrics_invalid')
    result = {name: None for name in p.METRICS}
    for name in legacy.TIMINGS + legacy.COUNTS:
        value = response.get(name)
        d.require(value is None or type(value) is int and value >= 0, 'ollama_metrics_invalid')
        result[name+'_ns' if name in legacy.TIMINGS else name] = value
    result['wall_duration_ns'] = wall_ns
    for name, count, duration in (('tokens_per_second','eval_count','eval_duration'),
                                 ('prompt_tokens_per_second','prompt_eval_count','prompt_eval_duration')):
        if response.get(count) is not None and response.get(duration):
            with localcontext() as context:
                context.prec = 6000
                rate = (Decimal(response[count])*1000000000/Decimal(response[duration])).quantize(
                    Decimal('0.000001'), rounding=ROUND_HALF_UP)
            result[name] = _decimal(rate)
    return p.validate_metrics(result)


class RequestFailure(Exception):
    def __init__(self, code, state):
        self.code, self.state = code, state
        super().__init__(code)


def _failure(exc):
    if isinstance(exc, RequestFailure):
        return exc
    cause = exc.__cause__ if isinstance(exc.__cause__, urllib.error.HTTPError) else exc
    if isinstance(cause, urllib.error.HTTPError) and cause.code in (400, 401, 403, 404, 405, 413, 422):
        return RequestFailure('ollama_rejected', 'completed')
    reason = exc.reason if isinstance(exc, urllib.error.URLError) else exc
    if isinstance(reason, (ConnectionRefusedError, socket.gaierror)):
        return RequestFailure('request_not_sent', 'not_sent')
    return RequestFailure('request_outcome_unknown', 'unknown')


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, 'redirect_rejected', headers, fp)


class _BoundedResponse:
    def __init__(self, response):
        self.response = response
    def __enter__(self):
        self.response.__enter__()
        return self
    def __exit__(self, *args):
        return self.response.__exit__(*args)
    def read(self, size=-1):
        cap = d.DEFAULT_LIMITS.max_json_bytes
        data = self.response.read(cap+1 if size < 0 else min(size, cap+1))
        if len(data) > cap:
            raise RequestFailure('ollama_response_limit', 'unknown')
        return data


class OllamaHTTPClient(legacy.Client):
    """Reuse the exact legacy HTTP method with an instance-local restricted urlopen.

    Function globals are copied, never mutated. This dependency bridge is needed
    because the unchanged legacy method has no opener argument. No second HTTP or
    JSON-response implementation, no process-wide monkeypatch/install_opener.
    """
    def __init__(self, base_url, timeout):
        super().__init__(api_url(base_url), timeout)
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
        scope = dict(legacy.Client.request.__globals__)
        scope['urllib'] = types.SimpleNamespace(error=urllib.error,
            request=types.SimpleNamespace(Request=urllib.request.Request, urlopen=self._open))
        self._legacy_request = types.FunctionType(legacy.Client.request.__code__, scope)

    def _open(self, request, *, timeout):
        if request.full_url not in {self.base_url+ep for ep in ('/api/tags','/api/ps','/api/generate')}:
            raise RequestFailure('request_policy_rejected', 'not_sent')
        if request.data is not None and len(request.data) > d.DEFAULT_LIMITS.max_json_bytes:
            raise RequestFailure('request_policy_rejected', 'not_sent')
        return _BoundedResponse(self._opener.open(request, timeout=timeout))

    def request(self, endpoint, payload=None):
        return self._legacy_request(self, endpoint, payload)


class _AuditClient:
    """Durable immutable request witnesses via S3, not a second journal/HTTP stack."""
    def __init__(self, delegate, plan, store, identity, deadline):
        self.delegate, self.plan, self.store, self.identity = delegate, plan, store, identity
        self.base_url = api_url(delegate.base_url)
        self.deadline = deadline
        self.base = w._base(identity, 'workspaces')+'/outputs/'
        self.counter = 0
        self.last = None
        self.completed = False
        self.last_wall_ns = None

    def request(self, endpoint, payload=None):
        validate_execution_plan(self.plan)
        d.require(api_url(self.delegate.base_url) == self.base_url, 'api_binding_mismatch')
        remaining = self.deadline-time.monotonic()
        if remaining <= 0:
            raise RequestFailure('deadline_before_send', 'not_sent')
        timeout = min(self.plan.as_dict()['limits']['request_timeout_seconds'], remaining)
        self.counter += 1
        stem = '%04d'%self.counter
        wire = None if payload is None else json.dumps(payload)
        self.store._json(self.base+'request_'+stem+'.json', dict(endpoint=endpoint, body_json=wire,
                        identity=self.identity, at=w._now()))
        # fsync may consume the remaining budget: never send using a stale timeout.
        validate_execution_plan(self.plan)
        d.require(api_url(self.delegate.base_url) == self.base_url, 'api_binding_mismatch')
        remaining = self.deadline-time.monotonic()
        if remaining <= 0:
            self.store._json(self.base+'response_'+stem+'.json',
                             dict(code='deadline_before_send',transport_state='not_sent',at=w._now()))
            raise RequestFailure('deadline_before_send','not_sent')
        timeout = min(self.plan.as_dict()['limits']['request_timeout_seconds'], remaining)
        previous_timeout = getattr(self.delegate, 'timeout', None)
        self.delegate.timeout = timeout
        self.last = None;self.completed = False
        try:
            try:
                transport_started = time.monotonic_ns()
                try:
                    response = self.delegate.request(endpoint, payload)
                finally:
                    self.last_wall_ns = time.monotonic_ns()-transport_started
            except Exception as exc:
                failure = _failure(exc)
                self.store._json(self.base+'response_'+stem+'.json', dict(code=failure.code,
                                 transport_state=failure.state, at=w._now()))
                # GET cannot start a generation; failure does not establish model identity.
                if payload is None:
                    raise RequestFailure('catalog_request_failed', 'not_sent') from None
                raise failure from None
        finally:
            self.delegate.timeout = previous_timeout
        self.last = response
        self.completed = type(response) is dict and response.get('done') is True
        try:
            text = json.dumps(response, ensure_ascii=False, allow_nan=False).encode('utf-8')
            d.require(len(text) <= d.DEFAULT_LIMITS.max_json_bytes, 'ollama_response_limit')
        except (ValueError, TypeError, d.DefinitionError):
            self.store._json(self.base+'response_'+stem+'.json', dict(code='ollama_response_invalid', at=w._now()))
            raise RequestFailure('ollama_response_invalid', 'completed' if self.completed else 'unknown') from None
        self.store._publish(self.base+'response_'+stem+'.json', text)
        return response


def _running_execution(plan, identity, started):
    return p.validate_execution(dict(kind='execution', schema_version=1, **identity,
        status='running', started_at=started, finished_at=None, metrics={k:None for k in p.METRICS},
        error=None, artifacts=[], provenance={}, supersedes_attempt_id=None),plan)


class OllamaAdapter:
    """Only local HTTP orchestration, using legacy Client/payload/generate/digest/snapshot."""
    def __init__(self, client):
        self.client = client
        self.base_url = api_url(client.base_url)

    def body(self, plan, participant, *, prompt=None):
        params = participant['parameters']
        scenario = dict(prompt=plan.competition()['prompt']['text'], keep_alive='5m',
                        num_predict=params['num_predict'], seed=params['seed'],
                        num_ctx=params['num_ctx'], think=params['think'])
        result = legacy.payload(scenario, participant['model']['name'], params['threads'], params['gpu_mode'], prompt)
        # Legacy supports fixed zero; S2 makes the same Ollama option explicit.
        result['options']['temperature'] = float(Decimal(params['temperature']))
        return result

    def _identity(self, participant, client):
        tags = client.request('/api/tags')
        d.require(type(tags) is dict and type(tags.get('models')) is list, 'model_catalog_invalid')
        name = participant['model']['name']
        aliases = {name} | ({name+':latest'} if ':' not in name else set())
        entries = [x for x in tags['models'] if type(x) is dict and
                   (x.get('name') in aliases or x.get('model') in aliases)]
        d.require(bool(entries), 'model_not_found')
        d.require(len(entries) == 1, 'model_identity_ambiguous')
        digest, _ = legacy.digest_for(name, {}, dict(data=tags))
        d.require(digest == participant['model']['revision_digest'], 'model_digest_changed')

    def execute(self, plan, participant, identity, store, *, run_remaining):
        validate_execution_plan(plan)
        w._identity(identity,plan)
        declared=next(x for x in plan.as_dict()['participants'] if x['participant_id']==identity['participant_id'])
        d.require(participant==declared,'participant_binding_mismatch')
        d.require(type(run_remaining) in (int,float) and math.isfinite(run_remaining),'time_budget_invalid')
        _,record=store._record(plan,identity)
        d.require(record['status']=='prepared','workspace_not_prepared')
        d.require(api_url(self.client.base_url) == self.base_url, 'api_binding_mismatch')
        created=store._json_read('journals/'+identity['run_id']+'/bundle.json')['initial_result']['created_at']
        started = w._now();clock = time.monotonic()
        persisted_remaining=plan.as_dict()['limits']['run_deadline_seconds']-(p._timestamp(started)-p._timestamp(created))/1e9
        deadline = clock+min(run_remaining,persisted_remaining,plan.as_dict()['limits']['attempt_deadline_seconds'])
        client = _AuditClient(self.client, plan, store, identity, deadline)
        # This immutable witness is published before any HTTP request.
        binding = dict(api_url=self.base_url, engine_build=build_manifest())
        store._json(client.base+'binding.json', dict(identity=identity, started_at=started, binding=binding))
        p.validate_run_transition('planned','running')
        store._json(client.base+'running.json', _running_execution(plan,identity,started))
        metrics = {name:None for name in p.METRICS}
        status='succeeded';code=None;fatal=False;phase='identity';server='not_sent'
        try:
            self._identity(participant, client)
            prep = plan.as_dict()['preparation'];actions=[]
            if prep['unload_before']:
                actions.append(('unload', dict(self.body(plan,participant,prompt=''),keep_alive=0)))
            if prep['preload']:
                actions.append(('preload', self.body(plan,participant,prompt='')))
            actions.extend(('warmup',self.body(plan,participant)) for _ in range(prep['warmup_count']))
            actions.append(('measurement', self.body(plan,participant)))
            for phase, body in actions:
                self._identity(participant, client)
                server='unknown'
                try:
                    response=legacy.generate(client,body)
                except RequestFailure:
                    raise
                except (ValueError, TypeError):
                    raise RequestFailure('ollama_response_invalid','completed' if client.completed else 'unknown') from None
                server='completed'
                model=response.get('model')
                name=participant['model']['name']
                d.require(model in (name, name+':latest') if ':' not in name else model == name,
                          'response_model_mismatch')
                wall=client.last_wall_ns
                self._identity(participant, client)
                if time.monotonic() > deadline:
                    raise RequestFailure('deadline_exceeded','completed')
                if phase=='measurement':
                    metrics=project_metrics(response,wall)
            phase='observation'
            # Observation only: neither /ps nor size_vram is proof of server quiescence/GPU use.
            legacy.snapshot(client,'/api/ps')
            if time.monotonic() > deadline:
                raise RequestFailure('deadline_exceeded','completed')
        except RequestFailure as exc:
            code=exc.code
            fatal=code=='catalog_request_failed'
            if server=='unknown' and exc.state=='not_sent':
                # Only explicit pre-send failure for this generate request proves it never ran.
                server='not_sent'
            elif exc.state=='unknown':server='unknown'
            elif exc.state=='completed':server='completed'
            if server=='unknown':status='uncertain';fatal=True
            else:status='timed_out' if code.startswith('deadline_') else 'failed'
        except d.DefinitionError as exc:
            # Storage failures must escape: a partial workspace is not a completed outcome.
            if exc.code not in ('model_catalog_invalid','model_not_found','model_identity_ambiguous',
                                'model_digest_changed','response_model_mismatch','ollama_metrics_invalid'):
                raise
            code=exc.code;status='failed';fatal=code != 'ollama_metrics_invalid'
        if code is not None:metrics={name:None for name in p.METRICS}
        observed=w._now()
        return dict(kind='ollama_outcome',schema_version=1,identity=identity,started_at=started,
                    finished_at=None if status=='uncertain' else observed, observed_at=observed,
                    status=status,metrics=metrics,error_code=code,phase=phase,server_state=server,
                    fatal=fatal,binding=binding,request_count=client.counter)


class RunCoordinator:
    """Sequential S2 slots; all durable writes and commits go through WorkspaceStore."""
    def __init__(self, store, plan):
        self.store,self.plan=store,plan
        p._context(plan)

    def _outcome(self, record):
        identity=record['identity']
        manifest=self.store.validate_archive(self.plan,identity,expected_manifest=record['manifest_sha256'])
        outcome=d.parse_json_bytes(self.store._read(w._base(identity,'artifacts')+'/files/outcome.json'))
        d._object(outcome,('kind','schema_version','identity','started_at','finished_at','observed_at',
                          'status','metrics','error_code','phase','server_state','fatal','binding','request_count'),'$.outcome')
        d._header(outcome,'ollama_outcome')
        d.require(outcome['identity']==identity,'outcome_identity_mismatch')
        d.require(type(outcome['fatal']) is bool,'outcome_invalid')
        d.require(type(outcome['request_count']) is int and 0 <= outcome['request_count'] <= 1000,'outcome_invalid')
        binding=self.store._json_read(w._base(identity,'artifacts')+'/files/binding.json')
        d.require(binding==dict(identity=identity,started_at=outcome['started_at'],binding=outcome['binding']),
                  'outcome_binding_mismatch')
        start=self.store._json_read(w._base(identity,'artifacts')+'/files/running.json')
        d.require(start==_running_execution(self.plan,identity,outcome['started_at']),'outcome_binding_mismatch')
        p.validate_attempt_transition(start['status'],outcome['status'])
        expected={'binding.json','running.json','outcome.json'} | {kind+'_%04d.json'%n
                  for n in range(1,outcome['request_count']+1) for kind in ('request','response')}
        prefix=w._base(identity,'artifacts')+'/files/'
        d.require({a['path'][len(prefix):] for a in manifest['artifacts']}==expected,'outcome_inventory_mismatch')
        d._object(outcome['binding'],('api_url','engine_build'),'$.binding')
        api_url(outcome['binding']['api_url'])
        d.require(d.content_sha256(outcome['binding']['engine_build'])==self.plan.as_dict()['engine']['source_sha256'],
                  'engine_build_mismatch')
        d.require(outcome['status'] in ('succeeded','failed','timed_out','uncertain') and
                  outcome['server_state'] in ('completed','not_sent','unknown'),'outcome_invalid')
        d.require((outcome['status']=='uncertain')==(outcome['server_state']=='unknown'),'outcome_invalid')
        if outcome['status']=='succeeded':
            d.require(outcome['server_state']=='completed' and outcome['error_code'] is None
                      and outcome['metrics'].get('wall_duration_ns') is not None,'outcome_invalid')
        d.require(outcome['finished_at'] is None if outcome['status']=='uncertain' else
                  outcome['finished_at']==outcome['observed_at'],'outcome_invalid')
        p._timestamp(outcome['observed_at'])
        d.require(p._timestamp(outcome['observed_at'])>=p._timestamp(outcome['started_at']),'outcome_invalid')
        return outcome,manifest

    def inspect(self, *, expected_head=None):
        journal=self.store.validate_journal(self.plan,expected_head=expected_head)
        folder='journals/'+self.plan.as_dict()['run_id']
        result=self.store._json_read(folder+'/bundle.json')['initial_result']
        result['updated_at']=self.store._json_read(folder+'/%08d.json'%journal['sequence'])['event']['at']
        fatal=False
        allocation_times={}
        if any(record['status']!='archived' for record in journal['state']['attempts']):
            for number in range(1,journal['sequence']+1):
                event=self.store._json_read(folder+'/%08d.json'%number)['event']
                for reserved in event['state']['attempts']:
                    allocation_times.setdefault(reserved['identity']['attempt_id'],event['at'])
        for record in journal['state']['attempts']:
            identity=record['identity'];participant=next(x for x in self.plan.as_dict()['participants']
                                                       if x['participant_id']==identity['participant_id'])
            if record['status']=='archived':
                outcome,manifest=self._outcome(record)
                artifacts=manifest['artifacts']
                d.require(p._timestamp(outcome['observed_at']) <= p._timestamp(result['updated_at']),'outcome_invalid')
                started=outcome['started_at'];finished=outcome['finished_at'];status=outcome['status']
                metrics=outcome['metrics'];code=outcome['error_code'];phase=outcome['phase'];fatal|=outcome['fatal']
            else:
                # No archived outcome => conservative execution intent, never replay the slot.
                started=allocation_times[identity['attempt_id']]
                finished=None;status='uncertain';metrics={k:None for k in p.METRICS}
                code='execution_outcome_unknown';phase='reconstruction';artifacts=[]
            refs=[a['artifact_id'] for a in artifacts]
            execution=dict(kind='execution',schema_version=1,**identity,status=status,started_at=started,
                           finished_at=finished,metrics=metrics,artifacts=artifacts,
                           error=None if code is None else dict(code=code,phase=phase,retryable=False,evidence=refs),
                           provenance=dict(engine=self.plan.as_dict()['engine'],adapter_version=participant['adapter_version'],
                                           model_revision_digest=participant['model']['revision_digest'],evidence=refs),
                           supersedes_attempt_id=None)
            p.validate_execution(execution,self.plan)
            result['executions'].append(dict(execution=execution,sha256=d.content_sha256(execution)))
        result['progress']=p._progress(result['executions'],self.plan)[0]
        if any(x['execution']['status']=='uncertain' for x in result['executions']):result['status']='interrupted'
        elif fatal:result['status']='failed'
        elif result['progress']['pending_slots']==0:result['status']='completed'
        elif result['executions']:result['status']='running'
        # Initializing has no compatible writable continuation even without an execution.
        p.validate_result(result,self.plan)
        return dict(result=result,head_sha256=journal['head_sha256'],
                    head_pin_checked=expected_head is not None,
                    resumable=journal['state']['phase']=='ready' and result['status'] in ('planned','running','completed'),
                    server_quiescence='unknown' if result['status']=='interrupted' else 'no_unresolved_own_request',
                    agent_execution=False)

    def run(self, adapter, *, resume=False, expected_head=None, progress=None):
        validate_execution_plan(self.plan)
        report=self.inspect(expected_head=expected_head)
        result=report['result']
        if not report['resumable']:
            if result['status']=='failed':raise d.DefinitionError('run_terminal')
            if result['status']=='interrupted':raise d.DefinitionError('server_quiescence_unconfirmed')
            raise d.DefinitionError('archive_initialization_incomplete')
        if result['executions'] and not resume:
            raise d.DefinitionError('resume_required')
        # A single trusted store per endpoint is required. Other pending stores/runs are never ignored.
        for run in self.store._names('journals'):
            if run==self.plan.as_dict()['run_id']:continue
            bundle=self.store._json_read('journals/'+run+'/bundle.json')
            other=p.PinnedPlan(d.canonical_json_bytes(bundle['plan']),d.canonical_json_bytes(bundle['competition']),
                               d.canonical_json_bytes(bundle['rubric']))
            other_report=RunCoordinator(self.store,other).inspect()
            other_journal=self.store.validate_journal(other)
            d.require(other_journal['state']['phase']=='ready' and
                      other_report['server_quiescence']=='no_unresolved_own_request','other_run_not_quiescent')
        journal=self.store.validate_journal(self.plan)
        for record in journal['state']['attempts']:
            if record['status']=='archived':
                outcome,_=self._outcome(record)
                d.require(outcome['binding']['api_url']==adapter.base_url,'api_binding_mismatch')
        if result['status']=='completed':return report
        done={(x['execution']['participant_id'],x['execution']['repetition']) for x in result['executions']}
        created=p._timestamp(result['created_at'])
        for participant in self.plan.as_dict()['participants']:
            for repetition in range(1,self.plan.as_dict()['repetitions']+1):
                if (participant['participant_id'],repetition) in done:continue
                remaining=self.plan.as_dict()['limits']['run_deadline_seconds']-(p._timestamp(w._now())-created)/1e9
                d.require(remaining>0,'run_deadline_exceeded')
                snapshot=self.store.root/'journals'/self.plan.as_dict()['run_id']
                p.validate_run_plan(self.plan.as_dict(),self.plan.competition(),self.plan.rubric(),
                    asset_root=snapshot/'inputs',rubric_asset_root=snapshot/'rubric-assets',expected_sha256=self.plan.sha256)
                identity=p.new_attempt_identity(self.plan,participant['participant_id'],repetition)
                self.store.prepare(self.plan,identity)
                if progress:progress(dict(participant_id=participant['participant_id'],repetition=repetition,
                                          planned_slots=len(p.measurement_slots(self.plan))))
                remaining=self.plan.as_dict()['limits']['run_deadline_seconds']-(p._timestamp(w._now())-created)/1e9
                outcome=adapter.execute(self.plan,participant,identity,self.store,run_remaining=remaining)
                base=w._base(identity,'workspaces')+'/outputs/'
                self.store._json(base+'outcome.json',outcome)
                files=sorted({'binding.json','running.json','outcome.json'} | {kind+'_%04d.json'%n
                              for n in range(1,outcome['request_count']+1) for kind in ('request','response')})
                self.store.collect(self.plan,identity,[dict(path=name,media_type='application/json') for name in files])
                report=self.inspect()
                w._checkpoint('s4_attempt_committed')
                if not report['resumable']:return report
        return report
