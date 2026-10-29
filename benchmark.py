#!/usr/bin/env python3
"""Sequential, standard-library-only Ollama benchmark runner."""
import argparse
import csv
from contextlib import contextmanager
import fcntl
import io
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import statistics
import sys
import time
import urllib.error
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parent
DEFAULT_API_URL = 'http://127.0.0.1:11434'
TIMINGS = ('total_duration', 'load_duration', 'prompt_eval_duration', 'eval_duration')
COUNTS = ('prompt_eval_count', 'eval_count')
METRICS = TIMINGS + COUNTS + ('tokens_per_second', 'prompt_tokens_per_second', 'wall_seconds')


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def save(path, data):
    temporary = path.with_suffix(path.suffix + '.tmp')
    with temporary.open('w', encoding='utf-8') as handle:
        handle.write(json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False) + '\n')
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)
    fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def validate(source):
    if not isinstance(source, dict):
        raise ValueError('Scenario must be an object')
    s = dict(source)
    allowed = {'models', 'threads', 'gpu_modes', 'repetitions', 'warmup', 'num_predict', 'seed',
               'timeout_seconds', 'unload_before', 'preload', 'prompt', 'keep_alive', 'think', 'num_ctx'}
    if set(s) - allowed:
        raise ValueError('Unknown scenario keys: ' + ', '.join(sorted(set(s) - allowed)))
    for key in ('models', 'threads', 'gpu_modes'):
        if not isinstance(s.get(key), list) or not s[key]:
            raise ValueError(key + ' must be a nonempty list')
        if len(s[key]) != len(set(map(str, s[key]))):
            raise ValueError(key + ' must not contain duplicates')
    if any(not isinstance(m, str) or not m.strip() for m in s['models']):
        raise ValueError('models must contain nonempty names')
    if any(type(n) is not int or n < 1 for n in s['threads']):
        raise ValueError('threads must contain positive integers')
    if any(m not in ('cpu_only', 'automatic') for m in s['gpu_modes']):
        raise ValueError('Unsupported GPU mode')
    for key, default, minimum in [('repetitions', 1, 1), ('warmup', 1, 0), ('num_predict', 64, 1), ('seed', 42, 0), ('num_ctx', 16384, 1)]:
        s.setdefault(key, default)
        if type(s[key]) is not int or s[key] < minimum:
            raise ValueError(key + ' has an invalid integer value')
    s.setdefault('timeout_seconds', 300)
    value = s['timeout_seconds']
    if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
        raise ValueError('timeout_seconds must be finite and positive')
    for key, default in [('unload_before', True), ('preload', True), ('think', False)]:
        s.setdefault(key, default)
        if type(s[key]) is not bool:
            raise ValueError(key + ' must be boolean')
    s.setdefault('prompt', 'Explain in three short sentences how a CPU works.')
    if not isinstance(s['prompt'], str) or not s['prompt'].strip():
        raise ValueError('prompt must be nonempty text')
    s.setdefault('keep_alive', '5m')
    if not isinstance(s['keep_alive'], str) or not s['keep_alive'].strip():
        raise ValueError('keep_alive must be a duration string')
    return s


class Client:
    def __init__(self, base_url, timeout):
        from urllib.parse import urlsplit
        parsed = urlsplit(base_url)
        if parsed.scheme not in ('http', 'https') or not parsed.netloc or parsed.query or parsed.fragment:
            raise ValueError('API URL must be an HTTP(S) base URL')
        self.base_url = base_url.rstrip('/')
        self.timeout = timeout

    def request(self, endpoint, payload=None):
        data = None if payload is None else json.dumps(payload).encode('utf-8')
        request = urllib.request.Request(self.base_url + endpoint, data=data,
                                         headers={'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                result = json.load(response)
        except urllib.error.HTTPError as exc:
            detail = exc.read(4096).decode('utf-8', errors='replace')
            raise RuntimeError(f'HTTP {exc.code}: {detail}') from exc
        if not isinstance(result, dict):
            raise ValueError('API response must be an object')
        if result.get('error'):
            raise RuntimeError(str(result['error']))
        return result


def snapshot(client, endpoint):
    try:
        return {'captured_at': utc_now(), 'data': client.request(endpoint), 'error': None}
    except Exception as exc:
        return {'captured_at': utc_now(), 'data': None, 'error': f'{type(exc).__name__}: {exc}'}


def payload(s, model, threads, mode, prompt=None):
    options = {'num_thread': threads, 'num_predict': s['num_predict'], 'seed': s['seed'], 'temperature': 0, 'num_ctx': s['num_ctx']}
    if mode == 'cpu_only':
        options['num_gpu'] = 0
    return {'model': model, 'prompt': s['prompt'] if prompt is None else prompt,
            'stream': False, 'think': s['think'], 'keep_alive': s['keep_alive'], 'options': options}


def digest_for(model, ps, tags):
    for label, source in [('ps', ps), ('tags', tags)]:
        data = source.get('data') or {}
        for entry in data.get('models', []):
            aliases = (entry.get('name'), entry.get('model'))
            if model in aliases or (':' not in model and model + ':latest' in aliases):
                if entry.get('digest'):
                    return entry['digest'], label
    return None, None


def summarize(records):
    groups = {}
    for record in records:
        key = (record['model'], record['threads'], record['gpu_mode'])
        groups.setdefault(key, []).append(record)
    output = []
    for (model, threads, mode), rows in groups.items():
        good = [r for r in rows if r['success']]
        row = dict(model=model, threads=threads, gpu_mode=mode, runs=len(rows), successes=len(good), failures=len(rows)-len(good))
        for metric in METRICS:
            values = [r[metric] for r in good if r.get(metric) is not None]
            row[metric + '_samples'] = len(values)
            for name, fn in [('mean', statistics.mean), ('median', statistics.median),
                             ('stdev', lambda x: statistics.stdev(x) if len(x) > 1 else None)]:
                row[metric + '_' + name] = fn(values) if values else None
        output.append(row)
    return output


def generate(client, body):
    response = client.request('/api/generate', body)
    if not isinstance(response, dict):
        raise ValueError('Generate response must be an object')
    json.dumps(response, allow_nan=False)
    if response.get('error'):
        raise ValueError(str(response['error']))
    if response.get('done') is not True:
        raise ValueError('Incomplete generate response')
    return response



RUNNER_VERSION = '2.0-resume'


def checksum(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def read_json(path):
    try:
        return json.loads(path.read_text(), parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))
    except (ValueError, OSError) as exc:
        raise ValueError(f'Invalid archive file {path.name}: {exc}') from exc


@contextmanager
def archive_lock(directory):
    # Never unlink: every contender must lock the same inode. Kernel releases on exit.
    with (directory / '.runner.lock').open('a+') as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError('Result directory is already locked by another runner') from exc
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def planned_runs(s):
    return [dict(model=m, threads=t, gpu_mode=g, think=s['think'], num_ctx=s['num_ctx'],
                 repetition=r, request=payload(s, m, t, g))
            for m in s['models'] for t in s['threads'] for g in s['gpu_modes']
            for r in range(1, s['repetitions'] + 1)]


def load_records(directory, s):
    plan = planned_runs(s)
    records = {}
    for path in directory.glob('run_*.json'):
        r = read_json(path)
        if not isinstance(r, dict):
            raise ValueError('Invalid measurement object')
        index = r.get('run_index')
        if type(index) is not int or not 1 <= index <= len(plan) or path.name != f'run_{index:05d}.json':
            raise ValueError('Invalid measurement identity: ' + path.name)
        expected = plan[index-1]
        if any(r.get(k) != v for k, v in expected.items()):
            raise ValueError('Measurement configuration mismatch: ' + path.name)
        digest = r.get('record_sha256')
        if digest != checksum({k:v for k,v in r.items() if k != 'record_sha256'}):
            raise ValueError('Measurement checksum mismatch: ' + path.name)
        if type(r.get('success')) is not bool or (not r['success'] and not r.get('error')):
            raise ValueError('Invalid measurement outcome: ' + path.name)
        if r['success'] and (r.get('error') is not None or (r.get('response') or {}).get('done') is not True):
            raise ValueError('Invalid successful measurement: ' + path.name)
        for metric in METRICS:
            value = r.get(metric)
            if value is not None and (type(value) not in (int, float) or not math.isfinite(value) or value < 0):
                raise ValueError('Invalid measurement metric: ' + path.name)
        records[index] = r
    if (directory / 'manifest.json').exists():
        manifest = read_json(directory / 'manifest.json')
        if not set(manifest.get('completed_indices', [])).issubset(records):
            raise ValueError('Previously committed measurement is missing')
    return records


def run(s, client, directory, dry_run=False, resume=False):
    directory = directory.resolve()
    if not directory.is_relative_to(ROOT):
        raise ValueError('Result directory must be inside the project')
    with archive_lock(directory):
        identity = dict(format_version=2, runner_version=RUNNER_VERSION,
                        runner_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                        scenario=s, api_url=client.base_url, dry_run=dry_run)
        session_path = directory / 'session.json'
        if resume:
            if read_json(session_path) != identity:
                raise ValueError('Incompatible scenario, runner, API URL or dry-run mode')
            if read_json(directory / 'scenario.json') != s:
                raise ValueError('Archived scenario differs')
            if validate(read_json(directory / 'scenario.original.json')) != s:
                raise ValueError('Original scenario differs')
            records = load_records(directory, s)
            env = read_json(directory / 'environment.json')
            if not dry_run and len(records) < len(planned_runs(s)):
                current = snapshot(client, '/api/tags')
                for model in s['models']:
                    old, _ = digest_for(model, env.get('tags', {}), {})
                    new, _ = digest_for(model, current, {})
                    if not old or old != new:
                        raise ValueError('Model digest changed or cannot be verified: ' + model)
        else:
            if session_path.exists() or list(directory.glob('run_*.json')):
                raise ValueError('Result directory already contains a series; use resume')
            save(directory / 'scenario.json', s)
            if not (directory / 'scenario.original.json').exists():
                save(directory / 'scenario.original.json', s)
            save(session_path, identity)
            records = {}
        return _run(s, client, directory, dry_run, records, resume)


def _run(s, client, directory, dry_run=False, existing=None, resume=False):
    started, clock = utc_now(), time.perf_counter()
    env = {'captured_at': started, 'python': sys.version, 'platform': platform.platform(),
           'runner_host': platform.node(), 'runner_cpu_count': os.cpu_count(), 'api_url': client.base_url,
           'note': 'Host data describes the runner, not necessarily the remote Ollama server. GPU/NUMA/driver data is not probed.'}
    if resume:
        env = read_json(directory / 'environment.json')
    elif not dry_run:
        env['ollama_version'] = snapshot(client, '/api/version')
        env['tags'] = snapshot(client, '/api/tags')
    if not resume:
        save(directory / 'environment.json', env)
    records, plan = list((existing or {}).values()), []
    previous = read_json(directory / 'manifest.json') if resume and (directory / 'manifest.json').exists() else {}
    index = 0
    total = len(s['models']) * len(s['threads']) * len(s['gpu_modes']) * s['repetitions']
    manifest = {'started_at': previous.get('started_at', started), 'dry_run': dry_run, 'planned_runs': total, 'status': 'running',
                'completed_indices': sorted(existing or {}), 'completed_runs': len(records),
                'successes': sum(r['success'] for r in records), 'failures': sum(not r['success'] for r in records),
                'pending_runs': total-len(records), 'current': None}
    save(directory / 'manifest.json', manifest)
    try:
        for model in s['models']:
            for threads in s['threads']:
                for mode in s['gpu_modes']:
                    config = dict(model=model, threads=threads, gpu_mode=mode, think=s['think'], num_ctx=s['num_ctx'])
                    plan.append(dict(config, request=payload(s, model, threads, mode)))
                    if dry_run:
                        print(f'[dry-run] {config}', flush=True)
                        continue
                    indices = range(index+1, index+s['repetitions']+1)
                    if all(i in (existing or {}) for i in indices):
                        index += s['repetitions']
                        continue
                    preparation = []
                    actions = []
                    if s['unload_before']:
                        actions.append(('unload', dict(payload(s, model, threads, mode, ''), keep_alive=0)))
                    if s['preload']:
                        actions.append(('preload', payload(s, model, threads, mode, '')))
                    actions.extend((f'warmup_{i+1}', payload(s, model, threads, mode)) for i in range(s['warmup']))
                    prep_error = None
                    for action, body in actions:
                        t = time.perf_counter()
                        item = {'action': action, 'started_at': utc_now(), 'request': body}
                        try:
                            item['response'] = generate(client, body)
                            item['success'] = True
                        except Exception as exc:
                            prep_error = f'{action}: {type(exc).__name__}: {exc}'
                            item.update(success=False, error=prep_error)
                        item['wall_seconds'] = time.perf_counter() - t
                        preparation.append(item)
                        if prep_error:
                            break
                    for repetition in range(1, s['repetitions'] + 1):
                        index += 1
                        if index in (existing or {}):
                            continue
                        manifest['current'] = dict(config, repetition=repetition, run_index=index)
                        save(directory / 'manifest.json', manifest)
                        print(f'[{index}/{total}] {model} threads={threads} gpu={mode} repetition={repetition}', flush=True)
                        body = payload(s, model, threads, mode)
                        r = dict(config, run_index=index, repetition=repetition, started_at=utc_now(), success=False, error=None,
                                 preparation=preparation, request=body)
                        r.update({metric: None for metric in METRICS})
                        t = time.perf_counter()
                        intent_path = directory / f'intent_{index:05d}.json'
                        if intent_path.exists():
                            intent = read_json(intent_path)
                            intent['uncertain_previous_attempts'] = intent.get('uncertain_previous_attempts', 0) + 1
                        else:
                            intent = {'run_index': index, 'uncertain_previous_attempts': 0}
                        intent['started_at'] = utc_now()
                        save(intent_path, intent)
                        r['uncertain_previous_attempts'] = intent['uncertain_previous_attempts']
                        try:
                            if prep_error:
                                raise RuntimeError('Configuration preparation failed: ' + prep_error)
                            response = generate(client, body)
                            r['response'] = response
                            for metric in TIMINGS + COUNTS:
                                value = response.get(metric)
                                if value is not None and (type(value) not in (int, float) or not math.isfinite(value) or value < 0):
                                    raise ValueError('Invalid timing/count: ' + metric)
                                r[metric] = value
                            for name, count, duration in [('tokens_per_second', 'eval_count', 'eval_duration'),
                                                          ('prompt_tokens_per_second', 'prompt_eval_count', 'prompt_eval_duration')]:
                                if r[duration] and r[count] is not None:
                                    r[name] = r[count] * 1e9 / r[duration]
                            r['success'] = True
                        except Exception as exc:
                            r['error'] = f'{type(exc).__name__}: {exc}'
                        r['wall_seconds'] = time.perf_counter() - t
                        r['finished_at'] = utc_now()
                        r['ps'] = snapshot(client, '/api/ps')
                        try:
                            r['model_digest'], r['digest_source'] = digest_for(model, r['ps'], env['tags'])
                        except (AttributeError, TypeError):
                            r['model_digest'], r['digest_source'] = None, None
                        r['record_sha256'] = checksum(r)
                        save(directory / f'run_{index:05d}.json', r)
                        records.append(r)
                        manifest.update(completed_indices=sorted(r['run_index'] for r in records),
                                        completed_runs=len(records), successes=sum(r['success'] for r in records),
                                        failures=sum(not r['success'] for r in records), pending_runs=total-len(records), current=None)
                        save(directory / 'manifest.json', manifest)
                        print('  OK' if r['success'] else '  ERROR: ' + r['error'], flush=True)
        manifest['status'] = 'complete'
    except BaseException:
        manifest['status'] = 'interrupted'
        raise
    finally:
        records.sort(key=lambda r: r['run_index'])
        summary = summarize(records)
        save(directory / 'summary.json', summary)
        buffer = io.StringIO(newline='')
        fields = list(summary[0]) if summary else ['model', 'threads', 'gpu_mode', 'runs', 'successes', 'failures']
        writer = csv.DictWriter(buffer, fieldnames=fields)
        writer.writeheader()
        writer.writerows(summary)
        csv_path = directory / 'summary.csv'
        temporary = csv_path.with_suffix('.csv.tmp')
        with temporary.open('w', encoding='utf-8', newline='') as handle:
            handle.write(buffer.getvalue())
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(csv_path)
        manifest.update(finished_at=utc_now(), wall_seconds=previous.get('wall_seconds', 0)+time.perf_counter()-clock, plan=plan,
                        completed_indices=sorted(r['run_index'] for r in records), successes=sum(r['success'] for r in records),
                        pending_runs=total-len(records),
                        completed_runs=len(records), failures=sum(not r['success'] for r in records))
        save(directory / 'manifest.json', manifest)
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('scenario', type=Path)
    parser.add_argument('--api-url', default=None,
                        help='Ollama base URL (overrides OLLAMA_API_URL; default: http://127.0.0.1:11434)')
    parser.add_argument('--output', type=Path, default=ROOT / 'results')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--resume', type=Path, help='Resume an existing compatible result directory')
    args = parser.parse_args(argv)
    try:
        output = args.output.resolve()
        if not output.is_relative_to(ROOT):
            raise ValueError('Output must be inside the project directory')
        scenario_path = args.scenario.resolve()
        if not scenario_path.is_relative_to(ROOT):
            raise ValueError('Scenario must be inside the project directory')
        raw = scenario_path.read_bytes()
        s = validate(json.loads(raw))
        api_url = args.api_url if args.api_url is not None else os.environ.get('OLLAMA_API_URL', DEFAULT_API_URL)
        client = Client(api_url, s['timeout_seconds'])
        if args.resume:
            directory = args.resume.resolve()
            if not directory.is_relative_to(ROOT) or not directory.is_dir():
                raise ValueError('Resume directory must exist inside the project')
            result = run(s, client, directory, args.dry_run, resume=True)
            return 1 if result['failures'] else 0
        directory = output / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '_' + uuid.uuid4().hex)
        directory.mkdir(parents=True)
        (directory / 'scenario.original.json').write_bytes(raw)
        save(directory / 'scenario.json', s)
        save(directory / 'provenance.json', {'scenario_sha256': hashlib.sha256(raw).hexdigest(),
                                             'runner_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()})
        print(f'Results: {directory}', flush=True)
        result = run(s, client, directory, args.dry_run)
        return 1 if result['failures'] else 0
    except (ValueError, OSError) as exc:
        print(f'Error: {exc}', file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print('Interrupted; saved runs remain available.', file=sys.stderr)
        return 130


if __name__ == '__main__':
    sys.exit(main())
