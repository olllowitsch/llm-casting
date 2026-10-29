# LLM Casting – Phase 1

Eigenständiger, sequenzieller Ollama-Benchmark mit Python-Standardbibliothek.
Keine Installation von Python-Paketen, keine Systemänderungen und keine automatischen
Modelldownloads. Voraussetzung: Python **3.10 oder neuer** sowie bereits auf dem
Ollama-Server installierte Modelle. Das Smoke-Szenario verwendet `phi4-mini:3.8b`; dieses Modell muss bereits
auf dem Ollama-Server vorhanden sein.

## Installation

Das Projektarchiv entpacken und das Verzeichnis `llm-casting` öffnen.
Es sind weder `pip install` noch administrative Rechte erforderlich.
Voraussetzungen: Python 3.10+, eine erreichbare Ollama-API mit `/api/generate`,
`/api/ps`, `/api/tags` und `/api/version` sowie Unterstützung der verwendeten
Request-Optionen. Modelle müssen bereits auf dem Server vorhanden sein.

## API-Konfiguration

Priorität: `--api-url` → Umgebungsvariable `OLLAMA_API_URL` →
`http://127.0.0.1:11434`. Ein explizit leerer oder ungültiger Wert wird abgewiesen.

```bash
export OLLAMA_API_URL=http://127.0.0.1:11434
python3 benchmark.py scenarios/smoke.json --dry-run
```

Eine `.env`-Datei wird nicht automatisch geladen. API-Zugangsdaten gehören nicht
in Szenarien oder Kommandozeilen-URLs. Der Runner bietet keine eigene
Authentifizierungsverwaltung.

## Dry-Run und Tests

Im Projektverzeichnis:

```bash
cd llm-casting
python3 benchmark.py scenarios/smoke.json --dry-run
python3 -m unittest discover -s tests -v
```

## Echter Benchmark

Ein echter Test wird ausdrücklich per Aufruf ohne `--dry-run` gestartet:

```bash
python3 benchmark.py scenarios/smoke.json
python3 benchmark.py scenarios/smoke.json --api-url http://127.0.0.1:11434 --output results
```

Der Dry-Run validiert das Szenario und schreibt ausschließlich Plan und Metadaten.
Er führt **keine API-Aufrufe**, Vorbereitungen oder Inferenz aus und erzeugt keine
Messwerte. Szenario und Ergebnisziel müssen innerhalb dieses Projektverzeichnisses
liegen. Ergebnisverzeichnisse erhalten UTC-Zeitstempel und UUIDs.

Exitcodes: `0` erfolgreich (auch Dry-Run), `1` mindestens ein fehlgeschlagener
Durchlauf, `2` Eingabe-/Dateifehler, `130` Benutzerabbruch.

## Szenarioformat

`scenarios/smoke.json` enthält zwei Threadzahlen, beide GPU-Modi und genau eine
Messwiederholung pro Konfiguration: insgesamt vier gemessene Anfragen bei einem
echten Aufruf. Vorbereitung kommt zusätzlich hinzu.

| Feld | Bedeutung / Standard |
| --- | --- |
| `models` | Erforderliche Liste von Modellnamen; Reihenfolge wird eingehalten |
| `threads` | Erforderliche Liste positiver CPU-Threadzahlen (`num_thread`) |
| `gpu_modes` | `cpu_only` und/oder `automatic` |
| `repetitions` | Messwiederholungen je Konfiguration, Standard 1 |
| `unload_before` | Vor jeder Konfiguration Zielmodell entladen, Standard true |
| `preload` | Leeren Prompt mit Konfigurationsoptionen senden, Standard true |
| `warmup` | Anzahl ungemessener Warmup-Anfragen, Standard 1 |
| `prompt` | Nichtleerer identischer Mess-/Warmup-Prompt |
| `think` | Boolean, Standard false; explizit auf oberster Request-Ebene |
| `num_ctx` | Positive ganze Kontextgröße, Standard 16384; in `options` |
| `num_predict` | Maximale Ausgabetokens, Standard 64 |
| `seed` | Zufallsstartwert, Standard 42; Temperatur ist fest 0 |
| `timeout_seconds` | Timeout pro HTTP-Anfrage, Standard 300 |
| `keep_alive` | Ollama-Dauer als Text, Standard `5m` |

Unbekannte Felder und doppelte Matrixeinträge werden abgewiesen. Beliebige
GPU-Schichtvorgaben sind nicht vorgesehen. `cpu_only` setzt `num_gpu=0`;
`automatic` lässt `num_gpu` vollständig weg und überlässt Ollama die Verteilung.

## Messmethodik

Die Schleifenreihenfolge ist Modell → Threadzahl → GPU-Modus → Wiederholung.
Alle HTTP-Anfragen und Modelltests laufen nacheinander. Entladen verwendet
`/api/generate` mit `keep_alive=0`; Vorladen verwendet einen leeren Prompt.
Danach folgen Warmups und Messwiederholungen. Jede Generierungsanfrage setzt
`stream=false`. `think` wird bei allen Anfragen explizit auf oberster Ebene
gesetzt; `num_ctx` steht in jedem `options`-Objekt, auch beim Vorladen und
Entladen. Messungen und Warmups verwenden identische Werte. Das Smoke-Szenario
setzt ausdrücklich `think=false` und `num_ctx=16384`. Beide Werte sind im
archivierten Szenario, im Manifest-Plan, pro Messergebnis und in den gespeicherten
Requests dokumentiert. Entladen, Vorladen und Warmup gehören nicht zur Messstatistik.
Ihre Antworten, Zeitpunkte, Anfragen und Laufzeiten werden separat beim Durchlauf
archiviert. Bei fehlgeschlagener Vorbereitung werden die Wiederholungen dieser
Konfiguration als fehlgeschlagen protokolliert, ohne eine unvorbereitete Messung
zu starten. Die nächste Konfiguration wird trotzdem bearbeitet. Einzelne
Messfehler verhindern keine weiteren Wiederholungen. Es gibt keine automatischen
Retries, die die Messbedingungen unbemerkt verändern könnten.

Ollamas `total_duration`, `load_duration`, `prompt_eval_duration` und
`eval_duration` bleiben unverändert in **Nanosekunden**. Tokenzahlen werden aus
`prompt_eval_count` und `eval_count` übernommen. Generierungsdurchsatz ist
`eval_count * 1e9 / eval_duration`; Promptdurchsatz entsprechend. Fehlende Werte
und Durchsatz bei Dauer null bleiben `null`. `wall_seconds` misst clientseitig
nur die gemessene HTTP-Anfrage einschließlich Übertragung, nicht den nachfolgenden
`/api/ps`-Abruf. Serienlaufzeit umfasst Vorbereitungen, Metadatenabrufe und
Ergebnisspeicherung. Alle Zeitstempel sind UTC.

Nach jeder Messung wird die vollständige Antwort von `/api/ps` archiviert,
insbesondere die von der Serverversion gelieferten Felder wie `size`, `size_vram`,
`context_length`, `expires_at` und `digest`. Diese zeigen den Zustand **nach** der
Anfrage, keine kontinuierliche GPU-Auslastung und keine garantierte Zahl von
GPU-Schichten. Der Digest stammt bevorzugt vom passenden geladenen Modell aus
`/api/ps`, ersatzweise vom initialen `/api/tags`-Snapshot. Die Herkunft wird
mitgespeichert; ohne verfügbare Metadaten bleibt er `null`. Ein fehlgeschlagener
Metadatenabruf allein macht eine erfolgreiche Inferenz nicht erfolglos.

Die CSV enthält pro Konfiguration Anzahl Versuche, Erfolge, Fehler sowie
Mittelwert, Median und **Stichprobenstandardabweichung** für jedes Messfeld.
Nur erfolgreiche Durchläufe mit vorhandenem Wert zählen; die jeweilige
Stichprobengröße steht in `*_samples`. Bei weniger als zwei Werten ist die
Standardabweichung leer/null. Eine Wiederholung erlaubt keine Streuungsschätzung.

Feste Optionen verbessern Vergleichbarkeit, garantieren aber keine bitgenaue
Reproduzierbarkeit. Prompt-Caches, laufende Fremdlast, Speicherzustand, thermische
Effekte und Ollama-/Modellversion beeinflussen Ergebnisse. Ein Entladen garantiert
keinen kalten Betriebssystem-Dateicache. Threadzahlen sind Anforderungen an
Ollama, keine Messung tatsächlich belegter CPU-Kerne. NUMA-Bindung, Serverkonfiguration,
Treiber und andere laufende Modelle werden nicht verändert. Für spätere belastbare
Vergleiche mehrere Wiederholungen und gleichbleibende Serverbedingungen verwenden.

## Ergebnisarchiv

Jede Serie erstellt ein neues Unterverzeichnis unter `results/`:

- `scenario.original.json`: unveränderte Eingabe; `scenario.json`: wirksame Standardwerte.
- `provenance.json`: SHA-256 der Eingabe und des ausgeführten Runners.
- `environment.json`: Python, Betriebssystem, Hostname und CPU-Anzahl des **Runners**,
  API-Adresse sowie verfügbare Ollama-Version und Modellliste.
- `run_00001.json` usw.: einzelne echte Messungen einschließlich Fehlern,
  Vorbereitung, Request, vollständiger Antwort und `/api/ps`-Snapshot.
- `summary.json` und `summary.csv`: aggregierte Konfigurationsstatistik.
- `manifest.json`: Plan, Status, Start/Ende, Serienlaufzeit und Fehleranzahl.

Lokale Umgebungsdaten beschreiben nicht automatisch den entfernten Ollama-Server.
GPU-Hardware, Treiber und NUMA-Topologie werden nicht automatisch ermittelt.
JSON-Dateien werden über eine temporäre Datei im selben Verzeichnis ersetzt.
Bei Ctrl+C bleiben gespeicherte Messungen erhalten; Zusammenfassung und Manifest
werden für die bereits abgeschlossenen Messungen geschrieben. Bei Prozessabbruch
mit SIGKILL oder Dateisystemfehlern kann die Abschlussauswertung fehlen.

Der HTTP-Timeout ist der Standardbibliotheks-Sockettimeout pro blockierender
Netzwerkoperation, keine harte Deadline für die komplette Serie. Ein clientseitiger
Timeout garantiert keine sofortige Beendigung der serverseitigen Inferenz.
Es werden niemals mehrere Anfragen gleichzeitig durch diesen Runner gestartet.

## Tests

Die Tests verwenden simulierte API-Antworten und temporäre Verzeichnisse innerhalb
des Projekts. Sie prüfen Matrix, API-Payloads, Vorbereitung, Fehlerfortsetzung,
Metadaten-Fallback, Timingformeln, Statistik, HTTP-Fehler, Timeoutübergabe,
Unterbrechung, Pfadbegrenzung und den netzwerkfreien Dry-Run.

## Sicherheit und Veröffentlichung

Der Runner verändert keine Systemkonfiguration, Treiber oder Dienste. Er lädt
Modelle über die API in den Speicher und kann das jeweilige Zielmodell entladen.
Eine entfernte API nur in einer vertrauenswürdigen, geeignet abgesicherten
Umgebung verwenden. Prompts und Modellantworten werden vollständig archiviert.
Ergebnisarchive können Hostnamen, API-Adressen, Modellinformationen und vertrauliche
Inhalte enthalten und sind standardmäßig über `.gitignore` ausgeschlossen.
Auch lokale Konfiguration, Secrets und Python-Caches sind ausgeschlossen.
`.gitignore` entfernt keine bereits versionierten Dateien und schützt nicht beim
manuellen Packen eines Projektverzeichnisses.

Für eine öffentliche Quellveröffentlichung ausschließlich diese Dateien aufnehmen:
`benchmark.py`, `scenarios/smoke.json`, `tests/test_benchmark.py`, `README.md`,
`LICENSE`, `.gitignore` und `RELEASE_CHECKLIST.md`. Keine lokalen Ergebnisarchive,
Caches, lokalen Prüfberichte oder Konfigurationen übernehmen. Vor dem tatsächlichen
Release den fertigen Veröffentlichungsinhalt erneut auf vertrauliche Daten prüfen.

## Lizenzvorbereitung

Der unveränderte Apache-2.0-Lizenztext liegt in `LICENSE`; Quelle:
https://www.apache.org/licenses/LICENSE-2.0.txt . Die Veröffentlichung unter
Apache-2.0 ist vorbereitet. Vor dem Release muss der Projektinhaber den korrekten
Copyright-Inhaber und das zutreffende Copyright-Jahr bzw. den Zeitraum bestätigen.
Es wurden keine Personen oder Organisationen als Rechteinhaber erfunden.
Die offenen Schritte stehen in `RELEASE_CHECKLIST.md`.

## License and copyright

Copyright 2026 Oliver Glück. Licensed under the Apache License, Version 2.0.
See [LICENSE](LICENSE) and [NOTICE](NOTICE).
