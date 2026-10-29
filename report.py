#!/usr/bin/env python3
"""Offline HTML reports from Ollama benchmark archives (standard library only)."""
import argparse
from datetime import datetime, timezone
import hashlib
import html
import json
import math
from pathlib import Path
import re
import statistics
import sys

ROOT = Path(__file__).resolve().parent
METRICS = ('tokens_per_second', 'prompt_tokens_per_second', 'eval_seconds')


def number(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def read_object(path):
    if path.is_symlink() or not path.resolve().is_relative_to(ROOT):
        raise ValueError('Archive files must be regular files inside the project')
    try:
        value = json.loads(path.read_text(encoding='utf-8'),
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (OSError, ValueError):
        raise ValueError('Missing or invalid JSON archive file: ' + path.name) from None
    if not isinstance(value, dict):
        raise ValueError('Expected a JSON object: ' + path.name)
    return value


def stats(values):
    values = [v for v in values if number(v)]
    return {'samples': len(values), 'mean': statistics.mean(values) if values else None,
            'median': statistics.median(values) if values else None,
            'stdev': statistics.stdev(values) if len(values) > 1 else None}


def metric(record, key):
    if key == 'eval_seconds':
        value = record.get('eval_duration')
        return value / 1e9 if number(value) else None
    # Recompute from authoritative counts/durations, avoiding rounded/stale summaries.
    count, duration = ('eval_count', 'eval_duration') if key == 'tokens_per_second' else ('prompt_eval_count', 'prompt_eval_duration')
    n, d = record.get(count), record.get(duration)
    return n * 1e9 / d if number(n) and number(d) and d > 0 else None


def config(record, scenario):
    options = (record.get('request') or {}).get('options') or {}
    return (record.get('model'), record.get('model_digest'), record.get('threads'),
            record.get('gpu_mode'), record.get('num_ctx', options.get('num_ctx', scenario.get('num_ctx'))),
            record.get('think', (record.get('request') or {}).get('think', scenario.get('think'))))


def load_archive(directory):
    directory = directory.resolve()
    if not directory.is_relative_to(ROOT) or not directory.is_dir():
        raise ValueError('Archive must be a directory inside the project')
    manifest = read_object(directory / 'manifest.json')
    scenario = read_object(directory / 'scenario.json')
    warnings, records, identifiers = [], [], set()
    for path in sorted(directory.glob('run_*.json')):
        if not re.fullmatch(r'run_\d{5,}\.json', path.name):
            raise ValueError('Unexpected measurement filename')
        record = read_object(path)
        index = int(path.stem[4:])
        if index < 1 or index in identifiers or ('run_index' in record and record['run_index'] != index):
            raise ValueError('Duplicate or inconsistent measurement identity')
        identifiers.add(index)
        digest = record.get('record_sha256')
        if digest is not None:
            encoded = json.dumps({k:v for k,v in record.items() if k != 'record_sha256'}, sort_keys=True, allow_nan=False).encode()
            if hashlib.sha256(encoded).hexdigest() != digest:
                raise ValueError('Measurement checksum mismatch: ' + path.name)
        if type(record.get('success')) is not bool:
            raise ValueError('Invalid measurement outcome: ' + path.name)
        if not isinstance(record.get('model'), str) or not record['model']:
            raise ValueError('Missing model name: ' + path.name)
        request = record.get('request')
        if request is not None and (not isinstance(request, dict) or not isinstance(request.get('options', {}), dict)):
            raise ValueError('Invalid archived request: ' + path.name)
        for key in ('eval_duration', 'eval_count', 'prompt_eval_duration', 'prompt_eval_count'):
            value = record.get(key)
            if value is not None and not number(value):
                raise ValueError('Invalid measurement metric: ' + path.name)
        uncertain = record.get('uncertain_previous_attempts', 0)
        if type(uncertain) is not int or uncertain < 0:
            raise ValueError('Invalid interrupted-attempt count')
        if record['success'] and record.get('error'):
            raise ValueError('Contradictory measurement outcome')
        if 'response' in record and record['success']:
            if not isinstance(record['response'], dict) or record['response'].get('done') is not True:
                raise ValueError('Incomplete successful model response')
        if not record['success'] and not record.get('error'):
            warnings.append(f'Messung {index}: Fehler ohne Fehlermeldung.')
        # Missing configuration is visible as missing, never replaced by guessed defaults.
        for key in ('threads', 'gpu_mode'):
            if record.get(key) is None:
                warnings.append(f'Messung {index}: {key} fehlt.')
        record['_index'] = index
        records.append(record)
    committed = manifest.get('completed_indices', [])
    if not isinstance(committed, list) or any(type(i) is not int for i in committed):
        raise ValueError('Invalid completed measurement list')
    if not set(committed).issubset(identifiers):
        warnings.append('Laut Manifest abgeschlossene Messdateien fehlen; Statistik umfasst nur vorhandene Dateien.')
    groups = {}
    for record in records:
        key = config(record, scenario)
        try:
            groups.setdefault(key, []).append(record)
        except TypeError:
            raise ValueError('Invalid model configuration') from None
    rows = []
    for key, group in groups.items():
        good = [r for r in group if r['success']]
        rows.append({'config': key, 'successes': len(good), 'failures': len(group)-len(good),
                     'metrics': {k: stats([metric(r, k) for r in good]) for k in METRICS}})
    pending_intents = []
    for path in sorted(directory.glob('intent_*.json')):
        intent = read_object(path)
        index = intent.get('run_index')
        if type(index) is not int or index < 1 or path.name != f'intent_{index:05d}.json':
            raise ValueError('Invalid measurement intent')
        if index not in identifiers:
            pending_intents.append(index)
    planned = manifest.get('planned_runs')
    if planned is not None and (type(planned) is not int or planned < 0):
        raise ValueError('Invalid planned measurement count')
    if planned is not None and planned < len(records):
        warnings.append('Mehr Messdateien als laut Manifest geplant.')
    if not records:
        warnings.append('Keine abgeschlossenen Messungen vorhanden (z. B. Dry-Run oder früher Abbruch).')
    if planned is not None and planned > len(records):
        warnings.append('Unvollständige Serie: geplante Messungen fehlen.')
    if any(not r.get('model_digest') for r in records):
        warnings.append('Mindestens ein Modelldigest fehlt.')
    if list(directory.glob('*.tmp')):
        warnings.append('Unfertige temporäre Dateien vorhanden; diese werden nicht ausgewertet.')
    private = []
    env_path = directory / 'environment.json'
    if env_path.exists():
        env = read_object(env_path)
        private = [v for k in ('runner_host', 'api_url') if isinstance((v := env.get(k)), str) and v]
        from urllib.parse import urlsplit
        try:
            host = urlsplit(env.get('api_url', '')).hostname
            if host:
                private.append(host)
        except (ValueError, TypeError, AttributeError):
            pass
    return dict(manifest=manifest, scenario=scenario, records=records, rows=rows, warnings=warnings,
                pending_intents=pending_intents, planned=planned, private=private)


def text(value, private=()):
    if value is None:
        return '—'
    value = str(value)
    for secret in sorted(private, key=len, reverse=True):
        value = value.replace(secret, '[lokal]')
    value = re.sub(r'https?://[^\s<>\"\x27]+', '[Adresse entfernt]', value, flags=re.I)
    value = re.sub(r'\b(?:\d{1,3}\.){3}\d{1,3}\b', '[IP entfernt]', value)
    value = re.sub(r'(?:/(?:home|Users|var|tmp|etc|opt|srv|root|mnt)/[^\s<>\"\x27]*|[A-Za-z]:[\\/][^\s<>\"\x27]*)', '[Pfad entfernt]', value)
    return html.escape(value, quote=True)


def fmt(value):
    return f'{value:.3f}' if number(value) else '—'


def render(archives):
    private = [str(ROOT)] + [s for a in archives for s in a['private']]
    esc = lambda v: text(v, private)
    parts = ['''<!doctype html><html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">
<title>LLM Casting – Benchmarkbericht</title><style>
:root{color-scheme:light dark;font-family:system-ui,sans-serif}body{max-width:1500px;margin:auto;padding:1.2rem;line-height:1.5}
h1,h2,h3{line-height:1.2}.scroll{overflow-x:auto}table{border-collapse:collapse;width:100%;margin:1rem 0}th,td{padding:.6rem;text-align:left;border-bottom:1px solid #888;vertical-align:top}th{background:#7772}code,td{overflow-wrap:anywhere}.notice{border-left:4px solid #c78b22;padding:.7rem;background:#c78b2215}.barrow{display:grid;grid-template-columns:minmax(14rem,1fr) 2fr;gap:1rem;align-items:center;margin:.8rem 0}.track{background:#8882;min-height:1.8rem}.bar{background:#2867ac;height:1.8rem;min-width:0}.automatic{background:#398047}.legend{font-size:.9rem}small{display:block}section{margin:2rem 0}details{margin:.5rem 0}
@media(max-width:650px){body{padding:.6rem}.barrow{grid-template-columns:1fr;gap:.2rem}th,td{padding:.4rem}h1{font-size:1.7rem}}
</style></head><body><h1>LLM Casting – Benchmarkbericht</h1>''']
    parts.append('<p>Erzeugt: ' + esc(datetime.now(timezone.utc).isoformat()) + '</p>')
    parts.append('<p>Offline-Auswertung. — bedeutet fehlend oder nicht berechenbar. Statistiken verwenden ausschließlich erfolgreiche Messungen; σ ist die Stichprobenstandardabweichung (erst ab n ≥ 2).</p>')
    if len(archives) > 1:
        parts.append('<p class="notice">Archivvergleich: Serien werden getrennt ausgewertet, nicht zusammengefasst. Abweichende Prompts, Modelle, Digests oder Optionen können Vergleiche einschränken.</p>')
        fingerprints = {json.dumps(a['scenario'], sort_keys=True) for a in archives}
        if len(fingerprints) > 1:
            parts.append('<p class="notice">Die archivierten Szenarien unterscheiden sich.</p>')
    chart_rows = []
    for i, archive in enumerate(archives, 1):
        m, records = archive['manifest'], archive['records']
        good = sum(r['success'] for r in records)
        uncertain = sum(r.get('uncertain_previous_attempts', 0) for r in records)
        parts.append(f'<section><h2>Archiv {i}</h2>')
        parts.append('<p>Start: ' + esc(m.get('started_at')) + ' · Ende: ' + esc(m.get('finished_at')) + ' · Gesamtlaufzeit: ' + fmt(m.get('wall_seconds')) + ' s · Status: ' + esc(m.get('status')) + '</p>')
        parts.append(f'<p>Geplant: {esc(archive["planned"])} · Abgeschlossen: {len(records)} · Erfolgreich: {good} · Fehlgeschlagen: {len(records)-good} · Unklare frühere Versuche: {uncertain} · Offene Versuche: {len(archive["pending_intents"])}</p>')
        for warning in archive['warnings']:
            parts.append('<p class="notice">' + esc(warning) + '</p>')
        parts.append('<div class="scroll"><table><caption>Konfigurationen und Statistiken</caption><thead><tr><th>Modell / Digest</th><th>Threads / Modus</th><th>Kontext / Thinking</th><th>Erfolg / Fehler</th><th>Generierung tokens/s<br>Mittel / Median / σ (n)</th><th>Prompt tokens/s<br>Mittel / Median / σ (n)</th><th>Generierungsdauer s<br>Mittel / Median / σ (n)</th></tr></thead><tbody>')
        for row in archive['rows']:
            model, digest, threads, mode, ctx, think = row['config']
            parts.append('<tr><td>' + esc(model) + '<small>Digest: ' + esc(digest) + '</small></td><td>' + esc(threads) + ' / ' + esc(mode) + '</td><td>' + esc(ctx) + ' / ' + esc(think) + f'</td><td>{row["successes"]} / {row["failures"]}</td>')
            for key in METRICS:
                v = row['metrics'][key]
                parts.append('<td>' + ' / '.join(fmt(v[k]) for k in ('mean', 'median', 'stdev')) + f' (n={v["samples"]})</td>')
            parts.append('</tr>')
            chart_rows.append((i, row))
        if not archive['rows']:
            parts.append('<tr><td colspan="7">Keine Messwerte vorhanden.</td></tr>')
        parts.append('</tbody></table></div><details><summary>Fehler und unterbrochene Versuche</summary><ul>')
        details = 0
        for r in records:
            if not r['success'] or r.get('uncertain_previous_attempts', 0):
                details += 1
                parts.append('<li>Messung ' + str(r['_index']) + ' · ' + esc(r['model']) + ' · Wiederholung ' + esc(r.get('repetition')) + ': ' + esc(r.get('error')) + ' · Unklare frühere Versuche: ' + str(r.get('uncertain_previous_attempts', 0)) + '</li>')
        for index in archive['pending_intents']:
            details += 1
            parts.append(f'<li>Messung {index}: Anfrage begonnen, kein dauerhaftes Ergebnis vorhanden; Ausgang unklar.</li>')
        if not details:
            parts.append('<li>Keine dokumentierten Fehler oder unterbrochenen Versuche.</li>')
        parts.append('</ul></details></section>')
    maximum = max((r['metrics']['tokens_per_second']['mean'] or 0 for _, r in chart_rows), default=0)
    parts.append('<section><h2>Generierungsdurchsatz im Vergleich</h2><p class="legend">Blau: cpu_only · Grün: automatic (Ollama entscheidet; GPU-Nutzung nicht garantiert). Balken zeigen Mittelwerte auf gemeinsamer Skala.</p>')
    for i, row in chart_rows:
        model, digest, threads, mode, ctx, think = row['config']
        v = row['metrics']['tokens_per_second']['mean']
        label = f'Archiv {i} · {model} · {threads} Threads · {mode} · Kontext {ctx} · think={think} · Digest {digest}'
        parts.append('<div class="barrow"><div>' + esc(label) + '<strong> · ' + fmt(v) + ' tokens/s</strong></div>')
        width = 100 * v / maximum if v is not None and maximum else 0
        cls = ' automatic' if mode == 'automatic' else ''
        parts.append(f'<div class="track"><div class="bar{cls}" style="width:{width:.3f}%"></div></div></div>')
    parts.append('</section><p>API-Adressen, Runner-Hostnamen, Archivpfade, Prompts und Modellantworttexte werden nicht aufgenommen. Fehlermeldungen werden redigiert; vertrauliche Freitexte vor Weitergabe trotzdem prüfen. Gesamtlaufzeiten stammen aus dem Manifest und können nach hartem Abbruch unvollständig sein.</p></body></html>')
    return ''.join(parts)


def generate_report(directories, output):
    directories = [Path(d).resolve() for d in directories]
    if len(set(directories)) != len(directories):
        raise ValueError('The same archive was specified more than once')
    output = Path(output).resolve()
    if not output.is_relative_to(ROOT) or output.suffix.lower() != '.html':
        raise ValueError('Output must be an HTML file inside the project')
    # Never write into any results archive, or overwrite any existing project file.
    if output.is_relative_to(ROOT / 'results') or any(output.is_relative_to(d) for d in directories):
        raise ValueError('Output must be outside result archives')
    if output.exists():
        raise ValueError('Output already exists; choose a new filename')
    archives = [load_archive(d) for d in directories]
    document = render(archives)
    output.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation also prevents concurrent reporters overwriting one another.
    with output.open('x', encoding='utf-8') as handle:
        handle.write(document)
    return archives


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archives', type=Path, nargs='+')
    parser.add_argument('--output', '-o', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        archives = generate_report(args.archives, args.output)
        print(f'HTML report created ({len(archives)} archive(s)).')
        return 0
    except (ValueError, OSError) as exc:
        # Never print absolute input paths from filesystem exceptions.
        print('Report error: ' + (str(exc) if isinstance(exc, ValueError) else 'File operation failed'), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
