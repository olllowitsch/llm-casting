#!/usr/bin/env python3
"""Build an offline dashboard using the existing report archive reader and statistics."""
import argparse
import base64
import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys

import report

ROOT = report.ROOT
STATUS = {
    'complete': 'Vollständig', 'errors': 'Vollständig mit Fehlern',
    'interrupted': 'Offen / unterbrochen', 'dry': 'Dry-Run', 'unknown': 'Status unbekannt',
}

# Only this constant is executable. No archive data is interpolated into JavaScript.
SCRIPT = r"""'use strict';
function selectRows(rows, model, mode, status, sort) {
  const selected = rows.filter(row => (!model || row.dataset.model === model) &&
    (!mode || row.dataset.mode === mode) && (!status || row.dataset.status === status));
  if (sort !== 'archive') {
    const key = sort.startsWith('speed') ? 'speed' : 'runtime';
    const direction = sort.endsWith('asc') ? 1 : -1;
    selected.sort((a, b) => {
      const av = a.dataset[key] === '' ? null : Number(a.dataset[key]);
      const bv = b.dataset[key] === '' ? null : Number(b.dataset[key]);
      if (av === null || !Number.isFinite(av)) return bv === null || !Number.isFinite(bv) ? 0 : 1;
      if (bv === null || !Number.isFinite(bv)) return -1;
      return direction * (av - bv);
    });
  }
  return selected;
}
const body = document.querySelector('#benchmarks tbody');
const rows = Array.from(body.querySelectorAll('tr[data-model]'));
function update() {
  const chosen = selectRows(rows, document.getElementById('model-filter').value,
    document.getElementById('mode-filter').value, document.getElementById('status-filter').value,
    document.getElementById('sort-order').value);
  const visible = new Set(chosen);
  rows.forEach(row => { row.hidden = !visible.has(row); });
  chosen.forEach(row => body.appendChild(row));
  document.getElementById('visible-count').textContent = chosen.length + ' Konfigurationen sichtbar';
}
['model-filter', 'mode-filter', 'status-filter', 'sort-order'].forEach(id => {
  document.getElementById(id).addEventListener('change', update);
});
update();
"""


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False)


def timestamp(value):
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if dt.tzinfo is None:
            return None
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


def validate_dashboard_archive(archive):
    """Additional dashboard assumptions; the shared reader handles measurements/checksums."""
    m = archive['manifest']
    if 'dry_run' in m and type(m['dry_run']) is not bool:
        raise ValueError('Invalid dry-run marker')
    for row in archive['records']:
        model, digest, threads, mode, ctx, think = report.config(row, archive['scenario'])
        if digest is not None and not isinstance(digest, str):
            raise ValueError('Invalid model digest')
        if threads is not None and (type(threads) is not int or threads < 1):
            raise ValueError('Invalid thread count')
        if mode is not None and mode not in ('cpu_only', 'automatic'):
            raise ValueError('Invalid GPU mode')
        if ctx is not None and (type(ctx) is not int or ctx < 1):
            raise ValueError('Invalid context size')
        if think is not None and type(think) is not bool:
            raise ValueError('Invalid thinking setting')
    planned = archive['planned']
    if planned is not None and (len(archive['records']) > planned or
                                any(r['_index'] > planned for r in archive['records']) or
                                any(i > planned for i in archive['pending_intents'])):
        raise ValueError('Measurement outside the planned series')
    if m.get('dry_run') and archive['records']:
        raise ValueError('Dry-run contains measurements')


def workload(record, scenario):
    """Fingerprint the exact request, excluding only the two intended matrix axes.

    Older records missing a complete request are displayed but not declared compatible.
    No prompt text or hash of the prompt is emitted into HTML.
    """
    model, digest, threads, mode, ctx, think = report.config(record, scenario)
    request = record.get('request')
    if (not digest or ctx is None or think is None or threads is None or mode is None or
            not isinstance(request, dict) or not isinstance(request.get('prompt'), str) or
            not isinstance(request.get('options'), dict)):
        return None
    options = request['options']
    if not all(k in options for k in ('num_predict', 'seed', 'temperature', 'num_ctx')):
        return None
    if (request.get('model') != model or options.get('num_ctx') != ctx or
            request.get('think') is not think or options.get('num_thread') != threads or
            (mode == 'cpu_only' and options.get('num_gpu') != 0) or
            (mode == 'automatic' and 'num_gpu' in options)):
        raise ValueError('Request and measurement configuration disagree')
    fixed = copy.deepcopy(request)
    for key in ('num_thread', 'num_gpu'):
        fixed['options'].pop(key, None)
    # Model digest is necessary even if the model tag did not change.
    return canonical([model, digest, ctx, think, fixed])


def series_status(archive):
    if archive['manifest'].get('dry_run') is True:
        return 'dry'
    planned = archive['planned']
    if (archive['manifest'].get('status') == 'complete' and planned is not None and
            planned == len(archive['records']) and not archive['pending_intents']):
        return 'errors' if any(not r['success'] for r in archive['records']) else 'complete'
    if archive['manifest'].get('status') in ('running', 'interrupted') or (
            planned is not None and planned > len(archive['records'])):
        return 'interrupted'
    return 'unknown'


def discover(selected=None, results=None):
    if selected:
        directories = [Path(p) for p in selected]
    else:
        results = Path(results) if results is not None else ROOT / 'results'
        if not results.resolve().is_relative_to(ROOT):
            raise ValueError('Results directory must be inside the project')
        if not results.exists():
            return []
        if not results.is_dir():
            raise ValueError('Results path is not a directory')
        directories = sorted(p for p in results.iterdir() if p.is_dir() or p.is_symlink())
    resolved = [p.resolve() for p in directories]
    if len(set(resolved)) != len(resolved):
        raise ValueError('Duplicate archive selection')
    if any(not p.is_relative_to(ROOT) for p in resolved):
        raise ValueError('Archives must be inside the project')
    if any(p.is_symlink() for p in directories):
        raise ValueError('Archive symlinks are not accepted')
    return resolved


def collect(directories):
    entries, families, systems = [], {}, {}
    for i, directory in enumerate(directories, 1):
        entry = dict(index=i, label=f'Archiv {i}', id=f'archive-{i}', valid=False, rows=[])
        # Only conventional run IDs are published. Custom directory names may be confidential.
        entry['run_id'] = directory.name if re.fullmatch(r'\d{8}T\d{6}Z_[a-f0-9]{8,64}', directory.name) else 'Benutzerdefinierte Archiv-ID'
        try:
            archive = report.load_archive(directory)
            validate_dashboard_archive(archive)
            groups = {}
            for record in archive['records']:
                fixed = workload(record, archive['scenario'])
                # Unknown workloads never establish comparability, even within one archive.
                family_key = fixed if fixed is not None else ('unknown', i, record['_index'])
                if family_key not in families:
                    families[family_key] = f'V{len(families)+1}'
                key = (report.config(record, archive['scenario']), family_key)
                groups.setdefault(key, []).append(record)
            for (config, family_key), records in groups.items():
                good = [r for r in records if r['success']]
                entry['rows'].append(dict(config=config, family=families[family_key],
                    comparable=isinstance(family_key, str), successes=len(good), failures=len(records)-len(good),
                    metrics={k:report.stats([report.metric(r,k) for r in good]) for k in report.METRICS}))
            env_path = directory / 'environment.json'
            env = report.read_object(env_path) if env_path.exists() else {}
            hardware = env.get('server_hardware')
            if hardware is not None and not isinstance(hardware, dict):
                raise ValueError('Invalid server hardware metadata')
            # Hardware inventory is optional; never mistake runner hardware for server hardware.
            if hardware:
                system_key = canonical(hardware)
                if system_key not in systems:
                    systems[system_key] = f'H{len(systems)+1}'
                entry['hardware'] = systems[system_key] + ' (archivierte Serverhardware)'
            else:
                entry['hardware'] = 'Serverhardware unbestätigt'
            entry.update(valid=True, archive=archive, status=series_status(archive))
        except (ValueError, OSError, TypeError, KeyError, AttributeError, OverflowError, RecursionError):
            # Arbitrary parser messages/filenames could contain secrets; do not echo them.
            entry.update(error='Archiv beschädigt, unvollständig oder ungültig. Aus allen Statistiken ausgeschlossen.', rows=[])
        entries.append(entry)
    return entries


def overview(entries):
    valid = [e for e in entries if e['valid']]
    models = {r['model'] for e in valid for r in e['archive']['records']}
    total = dict(archives=len(entries), valid=len(valid), invalid=len(entries)-len(valid), models=len(models),
                 complete=sum(e['status'] in ('complete', 'errors') for e in valid),
                 interrupted=sum(e['status'] == 'interrupted' for e in valid),
                 dry=sum(e['status'] == 'dry' for e in valid),
                 unknown=sum(e['status'] == 'unknown' for e in valid), success=0, failures=0, pending=0, pending_unknown=0)
    times = []
    for e in valid:
        a = e['archive']
        total['success'] += sum(r['success'] for r in a['records'])
        total['failures'] += sum(not r['success'] for r in a['records'])
        if e['status'] != 'dry':
            if a['planned'] is None:
                total['pending_unknown'] += 1
            else:
                total['pending'] += max(0, a['planned']-len(a['records']))
            # A dry-run generation timestamp is not a benchmark execution.
            times.extend((t, e['index']) for r in a['records']
                         if (t := timestamp(r.get('started_at'))) is not None)
            if a['records'] and not any(timestamp(r.get('started_at')) for r in a['records']):
                t = timestamp(a['manifest'].get('started_at'))
                if t:
                    times.append((t, e['index']))
    total['latest'] = max(times) if times else None
    return total


def privacy(entries):
    private = [str(ROOT)]
    for e in entries:
        if not e['valid']:
            continue
        a = e['archive']
        private.extend(a['private'])
        # Never allow a prompt echoed in an error or model label to leak.
        for r in a['records']:
            request = r.get('request') or {}
            for field in ('prompt', 'system'):
                if isinstance(request.get(field), str) and request[field]:
                    private.append(request[field])
        for field in ('prompt', 'system'):
            if isinstance(a['scenario'].get(field), str) and a['scenario'][field]:
                private.append(a['scenario'][field])
    return sorted(set(private), key=len, reverse=True)


def safe_text(value, private):
    if value is None:
        return '—'
    value = str(value)
    for secret in private:
        value = value.replace(secret, '[ausgeblendet]')
    # Never display arbitrary archive error text. These rules additionally cover labels.
    value = re.sub(r'(?i)\b(?:bearer\s+\S+|(?:api[_-]?key|token|password|secret)\s*[:=]\s*\S+)', '[Zugangsdaten entfernt]', value)
    value = re.sub(r'\b(?:gh[pousr]_[A-Za-z0-9_]+|AKIA[A-Z0-9]{16}|sk-[A-Za-z0-9_-]{12,})\b', '[Zugangsdaten entfernt]', value)
    value = re.sub(r'(?:[A-Za-z]:[\\/]|(?<![\w:])/)[^\s<>\"\x27]+', '[Pfad entfernt]', value)
    value = re.sub(r'\b(?:[a-fA-F0-9]{0,4}:){2,}[a-fA-F0-9:]+\b', '[IP entfernt]', value)
    return report.text(value)


def safe_archive(entry, private):
    """A display-only copy for reuse of report.render; never write it into the archive."""
    a = copy.deepcopy(entry['archive'])
    a['rows'] = entry['rows']  # report renderer uses the same metric/config schema.
    a['private'] = []
    # Redact free text before the shared renderer escapes it. Pre-escaped text would double escape.
    # Instead replace unsafe free-form fields by fixed descriptions; model fields are sanitized below.
    for r in a['records']:
        if not r['success']:
            r['error'] = 'Fehlgeschlagene Messung; Originalfehlermeldung verbleibt ausschließlich im lokalen Archiv.'
        r['model'] = display_plain(r['model'], private)
        r['repetition'] = r.get('repetition') if type(r.get('repetition')) is int else None
    a['manifest'] = {k:v for k,v in a['manifest'].items() if k in ('started_at','finished_at','wall_seconds')}
    for key in ('started_at', 'finished_at'):
        t = timestamp(a['manifest'].get(key))
        a['manifest'][key] = t.isoformat() if t else None
    a['manifest']['status'] = STATUS[entry['status']]
    a['warnings'] = ['Archivhinweis vorhanden; Datenqualität und Vollständigkeit vor Vergleichen prüfen.'] if a['warnings'] else []
    a['rows'] = copy.deepcopy(a['rows'])
    for row in a['rows']:
        row['config'] = tuple(display_plain(v, private) if isinstance(v, str) else v for v in row['config'])
    return a


def display_plain(value, private):
    # report.render handles HTML escaping. Convert the already escaped, redacted label back to text.
    import html
    return html.unescape(safe_text(value, private))


def render(entries):
    private = privacy(entries)
    esc = lambda v: safe_text(v, private)
    total = overview(entries)
    # Reuse report styles and series-detail presentation, not its whole document or CSP.
    template = report.render([])
    styles = template.split('<style>', 1)[1].split('</style>', 1)[0]
    script_hash = base64.b64encode(hashlib.sha256(SCRIPT.encode()).digest()).decode()
    parts = ['<!doctype html><html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">',
             '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'; script-src \'sha256-' + script_hash + '\'; connect-src \'none\'; base-uri \'none\'; form-action \'none\'">',
             '<title>LLM Casting – Offline-Dashboard</title><style>' + styles + '''
.cards{display:flex;flex-wrap:wrap;gap:1rem}.card{padding:1rem;border:1px solid #888;border-radius:.4rem}.controls{display:flex;flex-wrap:wrap;gap:1rem;margin:1rem 0}select{font:inherit;max-width:100%;padding:.4rem}a{color:inherit}.badge{font-weight:bold}.details-series{border-top:2px solid #888;margin-top:2rem}[hidden]{display:none!important}caption{text-align:left;font-weight:bold}.barrow{grid-template-columns:minmax(12rem,1fr) 2fr}
</style></head><body><h1>LLM Casting – Offline-Dashboard</h1><p>Statischer Stand: ''',
             datetime.now(timezone.utc).isoformat(), '</p><div class="cards">']
    for label, key in [('Archive','archives'),('Gültig','valid'),('Ungültig / ausgeschlossen','invalid'),('Modelle mit Messungen','models'),
                       ('Vollständige Serien','complete'),('Offene / unterbrochene Serien','interrupted'),('Dry-Runs','dry'),
                       ('Unbekannter Status','unknown'),('Erfolgreiche Messungen','success'),('Fehlgeschlagene Messungen','failures'),('Offene Messungen','pending')]:
        parts.append(f'<div class="card">{label}<br><strong>{total[key]}</strong></div>')
    parts.append('</div>')
    if total['pending_unknown']:
        parts.append(f'<p class="notice">Offene Messungen für {total["pending_unknown"]} Serie(n) unbekannt: Plananzahl fehlt.</p>')
    if total['latest']:
        t, idx = total['latest']
        parts.append(f'<p>Letzter Benchmark-Messbeginn (UTC): {t.isoformat()} · <a href="#archive-{idx}">Archiv {idx}</a></p>')
    else:
        parts.append('<p>Letzter Benchmark-Durchlauf: — (kein dokumentierter Messbeginn).</p>')
    parts.append('<p>Dry-Runs zählen nicht als offene Benchmark-Messungen. Fehlerhafte Archive sind von allen Messstatistiken ausgeschlossen. — bedeutet fehlend; σ ist die Stichprobenstandardabweichung, erst ab n ≥ 2.</p>')
    parts.append('<h2>Archive</h2><ul>')
    for e in entries:
        label = STATUS[e['status']] if e['valid'] else 'Ungültig / ausgeschlossen'
        parts.append(f'<li><a href="#{e["id"]}">{e["label"]}</a> · {esc(e["run_id"])} · {label}</li>')
    if not entries:
        parts.append('<li>Keine Archive gefunden.</li>')
    parts.append('</ul><h2>Benchmark-Konfigurationen</h2><noscript><p>JavaScript ist deaktiviert. Alle Konfigurationen und Seriendetails bleiben lesbar; interaktive Filter und Sortierung benötigen JavaScript.</p></noscript>')
    models = sorted({r['config'][0] for e in entries for r in e['rows']})
    model_ids = {m:f'm{i}' for i,m in enumerate(models,1)}
    parts.append('<div class="controls"><label>Modell <select id="model-filter"><option value="">Alle</option>')
    for model in models:
        parts.append(f'<option value="{model_ids[model]}">{esc(model)}</option>')
    parts.append('</select></label><label>GPU-Modus <select id="mode-filter"><option value="">Alle</option><option value="cpu_only">cpu_only</option><option value="automatic">automatic</option><option value="unknown">Unbekannt</option></select></label>')
    parts.append('<label>Benchmark-Status <select id="status-filter"><option value="">Alle</option>')
    for key,label in STATUS.items():
        parts.append(f'<option value="{key}">{label}</option>')
    parts.append('</select></label><label>Sortierung <select id="sort-order"><option value="archive">Archiv-Reihenfolge</option><option value="speed-desc">Tokens/s absteigend</option><option value="speed-asc">Tokens/s aufsteigend</option><option value="runtime-desc">Serienlaufzeit absteigend</option><option value="runtime-asc">Serienlaufzeit aufsteigend</option></select></label></div><p id="visible-count" aria-live="polite"></p>')
    parts.append('<div class="scroll"><table id="benchmarks"><caption>Messwerte je Archiv und Vergleichsgruppe – keine archivübergreifende Mittelung</caption><thead><tr><th>Archiv / Status</th><th>Modell / Digest</th><th>Threads / GPU</th><th>Kontext / Thinking</th><th>Messungen<br>Erfolg / Fehler</th><th>Tokens/s<br>Mittel / Median / σ (n)</th><th>Serienlaufzeit s</th><th>Vergleich / Hardware</th></tr></thead><tbody>')
    all_rows = []
    for e in entries:
        for row in e['rows']:
            model,digest,threads,mode,ctx,think = row['config']
            speed = row['metrics']['tokens_per_second']
            runtime = e['archive']['manifest'].get('wall_seconds')
            speed_attr = str(speed['mean']) if report.number(speed['mean']) else ''
            runtime_attr = str(runtime) if report.number(runtime) else ''
            parts.append(f'<tr data-model="{model_ids[model]}" data-mode="{mode or "unknown"}" data-status="{e["status"]}" data-speed="{speed_attr}" data-runtime="{runtime_attr}">')
            parts.append(f'<td><a href="#{e["id"]}">{e["label"]}</a><small>{STATUS[e["status"]]}</small></td>')
            parts.append('<td>' + esc(model) + '<small>Digest: ' + esc(digest) + '</small></td><td>' + esc(threads) + ' / ' + esc(mode) + '</td><td>' + esc(ctx) + ' / ' + esc(think) + '</td>')
            parts.append(f'<td>{row["successes"]+row["failures"]}<small>{row["successes"]} / {row["failures"]}</small></td><td>' + ' / '.join(report.fmt(speed[k]) for k in ('mean','median','stdev')) + f' (n={speed["samples"]})</td><td>{report.fmt(runtime)}</td>')
            comparison = row['family'] + ' · Konfiguration kompatibel' if row['comparable'] else 'Nicht vergleichbar: Metadaten fehlen'
            parts.append('<td>' + comparison + '<small>' + e['hardware'] + '</small></td></tr>')
            all_rows.append((e,row))
    if not all_rows:
        parts.append('<tr><td colspan="8">Keine Messkonfigurationen vorhanden.</td></tr>')
    parts.append('</tbody></table></div><h2>CPU-, GPU- und Threadvergleiche</h2><p>Nur Zeilen derselben V-Gruppe haben übereinstimmende dokumentierte Workloads. Gruppen berücksichtigen Modellname, Digest, Kontext, Thinking, Prompt und weitere Request-Optionen. Threadzahl und GPU-Modus dürfen variieren. Zwischen Gruppen: nicht vergleichbar. Fehlende Metadaten: keine Vergleichsfreigabe.</p><p>Blau: cpu_only. Grün: automatic; tatsächliche GPU-Nutzung nicht garantiert. Hardwareangaben sind nur bei expliziten Server-Metadaten bekannt; Runner-Hostdaten werden nicht als Serverhardware interpretiert. Auch passende Workloads garantieren keine gleichen Last- oder Cachebedingungen.</p>')
    family_rows = {}
    for e,row in all_rows:
        if row['comparable']:
            family_rows.setdefault(row['family'], []).append((e,row))
    for family, rows in family_rows.items():
        parts.append('<h3>Vergleichsgruppe ' + family + '</h3>')
        maximum = max((r['metrics']['tokens_per_second']['mean'] or 0 for _,r in rows), default=0)
        if len(rows) == 1:
            parts.append('<p>Kein zweiter kompatibler Vergleichspartner vorhanden.</p>')
        for e,row in rows:
            model,digest,threads,mode,ctx,think = row['config']
            v = row['metrics']['tokens_per_second']['mean']
            width = 100*v/maximum if v is not None and maximum else 0
            css = ' automatic' if mode == 'automatic' else ''
            parts.append(f'<div class="barrow"><div><a href="#{e["id"]}">{e["label"]}</a> · {threads} Threads · {mode} · {e["hardware"]} · {report.fmt(v)} tokens/s</div><div class="track"><div class="bar{css}" style="width:{width:.3f}%"></div></div></div>')
    parts.append('<h2>Seriendetails</h2>')
    for e in entries:
        parts.append(f'<section class="details-series" id="{e["id"]}"><h3>{e["label"]} · {esc(e["run_id"])}</h3>')
        if not e['valid']:
            parts.append('<p class="notice">' + e['error'] + '</p>')
        else:
            detail = report.render([safe_archive(e, private)]).split('<body>',1)[1].rsplit('</body>',1)[0]
            # Discard the report-wide comparison chart: dashboard charts enforce workload groups.
            detail = detail.split('<section><h2>Generierungsdurchsatz im Vergleich</h2>',1)[0]
            detail = detail.replace('<h1>', '<h3>').replace('</h1>', '</h3>')
            parts.append(detail)
        parts.append('<p><a href="#top">Zur Übersicht</a></p></section>')
    parts.append('<p>Keine Prompts, Modellantworten, API-Ziele, Hostnamen oder Rohfehlermeldungen eingebettet. Archiv-IDs bleiben auf standardisierte Run-IDs beschränkt. Vor einer Veröffentlichung auch Modellnamen prüfen.</p><script>' + SCRIPT + '</script></body></html>')
    return ''.join(parts).replace('<body>', '<body id="top">', 1)


def generate_dashboard(selected, output, results=None):
    directories = discover(selected, results)
    output = Path(output).resolve()
    if not output.is_relative_to(ROOT) or output.suffix.lower() != '.html':
        raise ValueError('Output must be an HTML file inside the project')
    protected = [ROOT/'results', *directories]
    if results is not None:
        protected.append(Path(results).resolve())
    if any(output.is_relative_to(p) for p in protected):
        raise ValueError('Output must be outside result archives')
    if output.exists():
        raise ValueError('Output already exists; choose a new filename')
    entries = collect(directories)
    document = render(entries)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('x', encoding='utf-8') as handle:
        handle.write(document)
    return entries


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archives', type=Path, nargs='*', help='Optional archive selection (default: all results subdirectories)')
    parser.add_argument('--output', '-o', type=Path, default=ROOT/'reports/dashboard.html')
    args = parser.parse_args(argv)
    try:
        entries = generate_dashboard(args.archives, args.output)
        invalid = sum(not e['valid'] for e in entries)
        print(f'Dashboard created: {len(entries)} archive(s), {invalid} excluded.')
        return 1 if invalid else 0
    except (ValueError, OSError):
        print('Dashboard error: invalid selection/output, inaccessible input, or output already exists.', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
