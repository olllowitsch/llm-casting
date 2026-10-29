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
`benchmark.py`, `report.py`, `scenarios/smoke.json`, `tests/test_benchmark.py`,
`tests/test_report.py`, `README.md`,
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

## Serien fortsetzen (Resume)

```bash
python3 benchmark.py scenarios/smoke.json --resume results/SERIENVERZEICHNIS
```

Die API-Konfiguration muss dieselbe sein wie beim Start. Ein Dry-Run-Archiv kann
nur mit zusätzlichem `--dry-run` fortgesetzt werden; dies bleibt netzwerkfrei.
Neue Archive enthalten `session.json` mit Formatversion, Runner-Version,
Runner-SHA-256, vollständigem Szenario und API-Ziel. Jede Änderung des Runners
(auch des Quelltextes), des wirksamen Szenarios, der API-Adresse oder des
Dry-Run-Modus führt zum sicheren Abbruch vor einer Inferenz. Alte Archive ohne
Resume-Metadaten werden nicht migriert oder überschrieben.

Vor einer Fortsetzung mit offenen Messungen werden die Modelldigests aus der
ursprünglichen Modellliste mit `/api/tags` verglichen. Fehlende oder abweichende
Digests verhindern die Fortsetzung. Modellnamen allein reichen nicht aus.
Archiviertes Original- und wirksames Szenario werden ebenfalls geprüft.

Jede Kombination aus Modell, Threads, GPU-Modus und Wiederholung hat eine feste
`run_index` und Dateinummer. Bereits gespeicherte **Erfolge und Fehler** werden
beibehalten und nicht automatisch wiederholt. Eine vollständig abgearbeitete
Serie mit Fehlern behält Exitcode 1. Für eine bewusste Wiederholung fehlgeschlagener
Tests eine neue Serie starten. Vor noch offenen Messungen einer Konfiguration
werden Entladen, Vorladen und Warmup gemäß Szenario erneut durchgeführt.

`manifest.json` enthält geplante, abgeschlossene, erfolgreiche, fehlgeschlagene
und offene Messungen sowie die aktuelle Konfiguration/Wiederholung. Die Anzeige
nennt die feste Messnummer und Wiederholung. Beim Resume werden Fortschritt und
Statistik aus den Messdateien rekonstruiert; ein hinterherhinkendes Manifest
führt daher nicht zum doppelten Zählen. Manifest und Zusammenfassungen werden
neu geschrieben. Die ursprünglichen Umgebungsdaten bleiben erhalten.

### Abstürze, Dateifehler und Sperren

Unter Linux/Ubuntu schützt eine nichtblockierende `fcntl.flock`-Sperre auf
`.runner.lock` das gesamte Ergebnisverzeichnis. Ein zweiter Runner bricht mit
Exitcode 2 ab. Die Sperre wird vom Kernel auch nach Prozessabbruch freigegeben;
die Sperrdatei bleibt bestehen und darf nicht während eines laufenden Tests
entfernt werden. Verwende ein lokales Dateisystem mit verlässlicher `flock`- und
atomarer Rename-Unterstützung. Die Sperre schützt kooperierende Runner-Prozesse,
nicht externe manuelle Dateimanipulationen.

JSON-Schreibvorgänge verwenden temporäre Dateien, `fsync` und atomaren Austausch.
Unfertige `.tmp`-Dateien zählen nicht als abgeschlossene Messungen. Messdateien
enthalten Prüfsummen und werden auf Identität, Konfiguration und Ergebnisstruktur
geprüft. Beschädigte Dateien oder laut Manifest fehlende abgeschlossene Messungen
führen zum Abbruch; sie werden nicht stillschweigend übersprungen. Prüfsummen
sind Integritätsprüfungen, keine Signaturen gegen absichtliche Manipulation.

Vor jedem Messversuch wird `intent_XXXXX.json` dauerhaft geschrieben. Ein Abbruch
nach Absenden der Anfrage, aber vor dem dauerhaften Speichern der Antwort lässt
sich ohne serverseitige Transaktionsunterstützung nicht als Erfolg rekonstruieren.
Beim Resume wird diese offene Messung erneut versucht; die Anzahl unklarer früherer
Versuche steht unter `uncertain_previous_attempts`. Es wird nur die dauerhaft
abgeschlossene Messung gezählt. Bereits dauerhaft gespeicherte Erfolge werden
niemals erneut angefragt. Ollama kann nach einem Client-Abbruch noch beschäftigt
sein; vor dem Resume serverseitig das Ende einer solchen Anfrage sicherstellen.

Das kumulierte `wall_seconds` erfasst die gespeicherten Ausführungszeiten der
Sessions, ohne Pausen zwischen Neustarts. Bei hartem Prozessabbruch kann die seit
dem letzten Manifest verstrichene Laufzeit fehlen. Fehlende/zerstörte grundlegende
Sitzungsmetadaten werden nicht automatisch repariert; dann eine neue Serie starten.


## Statische HTML-Auswertung (v0.2.0 – Schritt 2)

`report.py` ist ein eigenständiges Offline-CLI mit ausschließlich Python-
Standardbibliothek (Python 3.10+). Ollama muss für die Auswertung nicht laufen.
Es liest vorhandene Archive und verändert weder Messdateien noch Runner-Code.

Einzelbericht:

```bash
python3 report.py results/RUN_ID --output reports/einzelbericht.html
```

Vergleich mehrerer Archive:

```bash
python3 report.py results/RUN_A results/RUN_B --output reports/vergleich.html
```

Die HTML-Datei kann direkt im lokalen Browser geöffnet werden. Sie enthält alle
Styles und Balkendiagramme selbst, benötigt weder JavaScript noch externe Fonts,
CDNs oder Netzwerkzugriffe und passt sich mobilen Bildschirmen an. Breite Tabellen
können horizontal gescrollt werden. Exitcode 0 bedeutet erfolgreiche Erzeugung,
Exitcode 2 einen Eingabe-, Archiv- oder Dateifehler.

Eingaben müssen innerhalb des Projekts liegen. Ausgabedateien müssen die Endung
`.html` haben und innerhalb des Projekts, aber außerhalb von `results/` und den
angegebenen Archiven liegen. Bestehende Dateien werden nicht überschrieben.
Generierte Berichte unter `reports/` sind in `.gitignore` ausgeschlossen.

### Inhalt und Statistik

Der Bericht zeigt je Archiv Start/Ende, Status und Gesamtlaufzeit aus dem Manifest,
geplante, abgeschlossene, erfolgreiche und fehlgeschlagene Messungen. Die
Konfigurationstabelle enthält Modellname, Digest, Threads, GPU-Modus, Kontextgröße
und Thinking-Einstellung. Unterschiedliche Digests oder Konfigurationen werden
getrennt gruppiert. Archivnummern entsprechen der Reihenfolge der CLI-Argumente;
Archivpfade werden nicht im HTML angezeigt.

Für Generierungsdurchsatz und Promptverarbeitung (tokens/s) sowie Generierungsdauer
(in Sekunden) werden Mittelwert, Median, Stichprobenstandardabweichung und die
jeweilige Anzahl gültiger Werte angezeigt. Statistiken werden aus `run_*.json`
neu berechnet, statt möglicherweise veraltete `summary.json`-/CSV-Werte zu verwenden.
Fehlgeschlagene Messungen bleiben in den Fehlerzahlen, fließen aber nicht in
Leistungsstatistiken ein. Dauerwerte werden von Nanosekunden in Sekunden umgerechnet;
Durchsatz wird aus Tokenzahl und zugehöriger Dauer berechnet. Fehlende Werte und
Durchsatz bei Dauer null erscheinen als `—`; die Standardabweichung ist erst ab
zwei gültigen Messungen verfügbar. Fehlende alte Kontext-/Thinking-Angaben werden
nicht durch heutige Standardwerte ersetzt.

Balken zeigen den mittleren Generierungsdurchsatz auf gemeinsamer Skala, farblich
nach `cpu_only` und `automatic` getrennt. `automatic` bedeutet automatische
Ollama-Verteilung, keine bestätigte GPU-Nutzung. Vergleiche mehrerer Archive werden
nicht zu einer gemeinsamen Statistik vermischt. Abweichende Szenarien werden
markiert; gleiche Szenarien garantieren keine identischen Serverbedingungen.

### Unvollständige Archive und Datenschutz

`manifest.json` und `scenario.json` müssen gültige JSON-Objekte sein. Fehlerhafte
JSON-Dateien, ungültige Messwerte, widersprüchliche Messidentitäten oder abweichende
vorhandene Messprüfsummen führen zum Abbruch. Ältere Messdateien ohne Prüfsumme
werden unterstützt; diese bieten keine entsprechende Integritätsbestätigung.
Fehlende Einzelmessungen, Dry-Runs und unvollständige Serien werden als Warnungen
angezeigt; ausgewertet werden ausschließlich tatsächlich vorhandene Messdateien.
Temporäre Dateien zählen nicht als abgeschlossene Messungen. Für eine konsistente
Auswertung vorzugsweise ein ruhendes Archiv verwenden; der Report verändert keine
Sperrdateien und hält eine laufende Benchmark-Serie nicht an.

Fehlermeldungen und dokumentierte unklare frühere Versuche erscheinen in einem
aufklappbaren Abschnitt. `intent_*.json` ohne zugehöriges Messergebnis wird als
offener Versuch mit unbekanntem Ausgang ausgewiesen. Es werden keine Messwerte
aus begonnenen oder unterbrochenen Versuchen erfunden.

Alle aus Archiven angezeigten Texte werden HTML-escaped. Eine Content Security
Policy blockiert Skripte und externe Ressourcen. API-Adresse, Runner-Hostname,
Archivpfade, Prompts und Modellantworttexte werden nicht als Metadaten übernommen.
Bekannte lokale Hostangaben sowie URL-, IP- und typische Benutzer-/Systempfade in
Freitext werden redigiert. Das ersetzt keine vollständige Anonymisierung: etwa
Modellnamen oder beliebige Fehlermeldungen können weitere vertrauliche Angaben
enthalten. Den fertigen Bericht vor einer Weitergabe prüfen.

Die Report-Tests decken Escaping, fehlende Messwerte, fehlerhafte/teilweise Archive,
Archivvergleich, Gruppierung, Statistik und Einheiten, Datenschutz, Pfadbegrenzung,
Netzwerkfreiheit sowie unveränderte Quelldaten ab. Alle Tests starten wie bisher mit:

```bash
python3 -m unittest discover -s tests -v
```
