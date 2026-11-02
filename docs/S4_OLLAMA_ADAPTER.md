# S4 – Ollama-Adapter und Laufkoordination

Implementiert: Performance-Wettbewerbe über die unveränderten S1-/S2-Verträge und
S3-Persistenz. Keine Coding-Agenten, Prozesse, Jury oder Bewertung. Der bisherige
benchmark.py-Runner, seine CLI, Resume-Regeln und Archive bleiben unverändert.
S4-Tests benutzen ausschließlich Fakes; echte Inferenz ist keine lokale Abnahme.

## Komponenten und Wiederverwendung

- ollama_adapter.py: OllamaHTTPClient, OllamaAdapter, RunCoordinator und S2-Projektion.
- casting.py: Standalone-CLI build-info/validate/dry-run/run/inspect/resume.
- tests/test_ollama_adapter.py: Fake-API, Transportbrücke, Persistenz-/Resume-Tests.

Verwendet werden benchmark.Client.request, payload, generate, digest_for, snapshot
sowie TIMINGS/COUNTS. Es gibt keine kopierte Benchmarkschleife, HTTP-/JSON-
Antwortimplementierung, Statistikengine oder neue Journal-Engine. Die alte
run-Schleife wird nicht aufgerufen: ihre bestehende Intent-Wiederholung ist für
das neue strikte Resume ungeeignet. Die neue Koordination ordnet S2-Messplätze zu,
pinnt Belege und übersetzt Rohmetriken in S2-Einheiten/Dezimalstrings.

### HTTP-Brücke ohne Änderung am Legacy-Client

OllamaHTTPClient erbt von benchmark.Client. Er verwendet exakt dessen
request-Codeobjekt mit einer **instanzlokalen Kopie** der Funktionsglobals, in der
nur urllib.request.urlopen durch einen beschränkten Opener ersetzt ist.
Hintergrund: Die unveränderte Legacy-Methode bietet keine Opener-Injektion.
Keine globalen Monkeypatches, kein install_opener, kein eval/exec und keine
Programmtexte aus Nutzdaten. Diese kleine interne Abhängigkeit wird durch den
Buildpin und eigene Tests abgesichert. Andere Legacy-Clients bleiben unverändert.

Der Opener verhindert Redirects und Umgebungsproxies. Es sind ausschließlich der
konfigurierte API-Root und /api/tags, /api/generate, /api/ps zulässig. HTTP(S),
keine Userinfo/Zugangsdaten, Queries, Fragmente oder freien Basispfade. Anfrage-
und Antwortbytes maximal 1 MiB; Lesefehler oder ein zu großer Generierungsreply
beweisen kein Generierungsende. HTTP-Fehlerbehandlung/JSON-Decoding bleiben die
bestehende Client-Methode. HTTPS nutzt die Standard-Zertifikatsprüfung.

## Plan-, Build- und Modellbindung

Vor Ausführung: S1-Wettbewerb, Rubric und tatsächliche Inputs validieren; S2-Plan
mit erwartetem SHA256 pinnen; S3-Journal und Snapshots vollständig prüfen.
Vor jedem neuen Messplatz werden die archivierten S1-Assets erneut validiert.
Vor jeder HTTP-Anfrage werden Build und privater API-Root erneut geprüft.

S4 verlangt engine.version=s4-v1 und adapter_version=ollama-s4-v1. source_sha256
ist der S1-Inhaltshash des vollständigen engine_build-Manifests aus build-info.
Es inventarisiert benchmark.py, definitions.py, planning.py, workspaces.py,
ollama_adapter.py und casting.py mit exakten Dateigrößen/SHA256. Das Manifest wird
privat mit den Versuchsbelegen archiviert. Quell-/Versionsänderungen erfordern
neue Pläne, keine stillen Ergänzungen bestehender Runs. Das ist eine Prüfung
lokaler Quellbytes, keine Signatur oder Attestierung des Interpreters/Hosts.
Nicht vertrauenswürdige Eingriffe derselben UID bleiben außerhalb dieser Garantie.

Alle Teilnehmer benötigen einen unveränderlichen, nicht-null Modell-Digest. Vor
der Vorbereitung und vor/nach jedem generate wird /api/tags mit digest_for geprüft.
Es muss genau ein passender Modelleindruck mit exakt deklariertem Digest vorliegen.
Kein Modellpull, Ersatzmodell oder Wechsel des Providers. Der bestätigte Reply
muss denselben Modellnamen tragen. Die bekannte :latest-Aliasregel des Legacy-
Helfers wird erhalten; Digeststrings werden nicht umgeschrieben.

Wichtig: Katalogprüfungen attestieren keine Gewichte atomar zur Generierung.
Der Betreiber muss den ausgewählten Modellbestand und den expliziten Server
exklusiv verwalten; kein gleichzeitiges Ersetzen von Modell-Tags. Beobachtete
Digestdrift führt zum fatalen Abbruch. Unbekannte Hardware bleibt unverifiziert.
Ein automatic-Modus und /api/ps.size_vram beweisen keine tatsächliche GPU-Nutzung.
Providerfähigkeiten/Parameterwirkung benötigen vor realer Abnahme einen separat
freigegebenen Test mit einer geeigneten Ollama-Version; dry-run behauptet dies nicht.

## Parameter und Reihenfolge

| S2 | Ollama |
| --- | --- |
| threads | options.num_thread |
| gpu_mode=cpu_only | options.num_gpu=0 |
| gpu_mode=automatic | num_gpu vollständig weglassen |
| num_ctx / seed / num_predict | gleichnamige options-Felder |
| temperature | Numerischer Transportwert aus dem gepinnten Dezimalstring |
| think | Boolean auf oberster Requestebene |

stream=false, kein aggressiver GPU-Layerwert. Der Legacy-Payloadbuilder liefert
alle gemeinsamen Felder. Nur dessen festes Temperatur-0-Feld wird durch den
expliziten S2-Wert ersetzt. Nicht verlustfrei darstellbare numerische Temperaturen,
unbekannte Optionen/Adapter oder Disziplinen werden vor HTTP abgewiesen.

Reihenfolge: Teilnehmer in Planreihenfolge → repetition aufsteigend. Für jeden
Messplatz: Identität → optional Unload → optional Preload → Warmups → Messung →
optionale /ps-Beobachtung → S3-Archivabschluss. Keine parallelen Requests.
Vorbereitung gilt je Wiederholung, nicht nur einmal pro Teilnehmer. Unload/Preload
verwenden leere Prompts, Warmup und Messung exakt dieselben gemeinsamen Promptbytes
und Parameter. Vorbereitungsantworten werden nicht als Messwerte gezählt.

Requesttimeout wird auf das verbleibende Attempt-/Runbudget begrenzt. Attempt-
Budget umfasst Vorbereitung und Beobachtung; Runbudget läuft ab dem persistierten
S3-Bundle-Zeitpunkt und zählt Resume-Ausfallzeiten mit. Monotone Uhren messen
lokale Dauern; UTC bindet Archivzeitpunkte. Ein spät bestätigt beendeter Reply
kann timed_out sein, ohne uncertain zu werden. Sockettimeouts sind keine harten
OS-Laufzeitlimits und terminieren keine Serverarbeit. Ist das Runbudget bereits
aufgebraucht, wird kein neuer Messplatz angelegt.

## Persistenz, Resultprojektion und Provenienz

Alle Schreiboperationen verwenden den bestehenden WorkspaceStore und seinen
exklusiven Lock, No-Replace-Publisher, fsync, Inventarvalidator und Hashjournal.
Keine eigenen Locks, Commitmarker, veränderlichen Fortschrittsdateien oder
separate Hashkette. Vor HTTP wird der S3-Messplatz dauerhaft prepared angelegt.

Im privaten outputs-Bereich entstehen ausschließlich explizit inventarisierte
normale Dateien:

- binding.json: Identität, Beginn und privater API-/Buildbeleg.
- running.json: mit S2 validierter begonnener Execution-Beleg ohne Messwerte.
- request_NNNN.json: dauerhaft veröffentlichte Anfrageabsicht **vor** Transport,
  mit Identität, Endpoint, Zeitpunkt und dem JSON-Body als String.
- response_NNNN.json: empfangene API-JSON-Daten oder sichere Transportfehlercodes.
- outcome.json: versionierter privater Adapterabschluss mit Identität, Zeitpunkten,
  terminalem/uncertain Status, Metriken, Fehlercode/Phase, Serverzustand, fatal,
  Requestanzahl und privater Bindung. Kein zweiter portabler Resultvertrag.

Request-/Antwortdateien sind Adapterbelege, keine zusätzliche Journalengine.
JSON-Responses werden wie im Legacy-Runner dekodiert und erneut serialisiert;
das ist kein bitgenauer Mitschnitt ursprünglicher HTTP-Bytes/Headers.
Unbekannte zusätzliche Dateien werden bei der expliziten S3-Sammlung abgewiesen.
Erst der bestätigte S3-Status archived macht den vollständigen Abschlussbeleg
maßgeblich. Ein vorhandenes Verzeichnis/outcome.json/Manifest allein genügt nicht.

RunCoordinator.inspect rekonstruiert deterministisch das identische S2-result:
Execution-Belege aus bestätigten Outcomes plus tatsächliche S3-Artefakt-IDs,
Dateihashes, Pfade und private Klassifikation aus den Manifesten. Das vermeidet
eine zyklische Selbstreferenz zwischen Resultdatei und eigenem Artefakthash.
Der persistierte Outcome **zusammen mit** Manifest und Journal enthält vollständig
die Daten für die portable Resultprojektion; eine separate result.json ist ein
optional expliziter Export, kein zweiter maßgeblicher Zustand.

Das S2-Result bindet Plan-/Prompt-/Rubricreferenzen und Teilnehmer/Attempt-IDs.
Parameter und Modellnamen/Digests bleiben über den unveränderlichen Plan gebunden.
Metriken: Legacy-Rohzeiten als Integer-Nanosekunden, Counts als nichtnegative
Integer, fehlende Werte null. S2-Durchsätze werden ohne binäre Float-Rechnung auf
sechs Stellen ROUND_HALF_UP projiziert und erneut mit validate_metrics geprüft.
wall_duration_ns umfasst ausschließlich die Messanfrage; Start/Ende des Versuchs
schließen Vorbereitung ein. Ungültige Counts, Boolean/Float-Timings oder negative
Werte liefern keine erfolgreiche Messung. error/provenance referenzieren die
wirklichen privaten S3-Artefakte; keine Rohfehler, Endpoints, Prompts oder Antworten
im portablen Result. Keine Scores, Zeugnisse oder behaupteten GPU-Messwerte.

S2-Fortschritt wird über dessen vorhandenen Validator aus Einzelbelegen berechnet.
completed heißt alle Messplätze terminal, auch bei einzelnen Fehlern. Fatale
Identitäts-/Katalogfehler stoppen den Run als failed. Bekannte terminale Mess- oder
Vorbereitungsfehler können zum nächsten geplanten Messplatz weitergehen; der alte
Versuch wird niemals wiederholt. Die Resultprojektion und bereits bestätigte
Execution-Hashes bleiben bei identischer Inspektion/Resume bytegleich.

## Timeout, Abbruch und Serverruhe

| Beobachtung | Behandlung |
| --- | --- |
| Validierung/Budget verhindert Versand | Kein Generate-Versand; bestätigter Fehler/Timeout |
| Explizite Verbindungsverweigerung oder DNS-Fehler | request_not_sent, terminal failed |
| Explizite HTTP-400/401/403/404/405/413/422-Ablehnung | Terminale Ablehnung; kein erfolgreicher Beleg |
| Vollständiger done=true-Reply | Bestätigtes eigenes Requestende; Schema/Metriken/Identität trotzdem prüfen |
| done=false, abgeschnittener Reply, Reset, Timeout, untypisierter Transportfehler, HTTP-5xx/Redirect | uncertain, Ende nicht bestätigt |
| Unbekannter Speicherabschluss/fehlender S3-Archivcommit | uncertain, keine Wiederholung |

GET-Fehler starten selbst keine Generierung, ersetzen aber keine Identitätsprüfung.
Ein GET nach einem bestätigten Generate-Ende macht dieses Ende nicht ungeschehen.
Bei jedem unknown-Ausgang einer möglicherweise gesendeten Generierung stoppt die
Serie sofort. Kein nächstes Modell, Unload, Warmup, /ps-Polling oder Retry zur
vermeintlichen Freigabe. /api/ps liefert keinen belastbaren Abschlussbeleg einer
früheren Generierung und wird nie dafür verwendet.

Ollama liefert in diesem Adapter keinen unabhängigen Stillstandsnachweis für
verlorene Generate-Anfragen. Deshalb gibt es keinen Force-Resume-Schalter, kein
Operator-Boolean als Ersatzbeleg und keine automatische Wiederholung. Ein
uncertain-Execution ist im S2-Run interrupted und bleibt gesperrt.

Auch nach Prozessverlust wird jeder nicht archivierte, bereits reservierte
S4-Messplatz konservativ als uncertain rekonstruiert. Das kann vor dem tatsächlichen
Versand blockieren. Seine rekonstruierte Beginnzeit ist der erste Journalzeitpunkt seiner eigenen
Versuchsreservierung, kein gemessener Generierungsbeginn und nicht der Laufstart.
Es werden keine Messwerte erfunden. Unbestätigte Abschlussdateien werden nicht als Erfolg
übernommen. Ein vollständiger bestätigter Archivcommit kann dagegen read-only
rekonstruiert werden, auch wenn der frühere Aufrufer die Quittung verloren hat.

**Betriebsgrenze:** Ein vertrauenswürdiger Casting-Root pro exklusiv verwaltetem
Ollama-Endpunkt. Andere Runs mit ungewissen HTTP-/Speicherabsichten in demselben Root sperren
neue Requests. Vollständig bestätigte eigene Requestenden dürfen auch nach einem
terminalen fachlichen Fehler einen neuen getrennten Run zulassen. Ein zweiter Root, fremde Clients oder Betreiberaktionen können
nicht durch einen lokalen Lock kontrolliert werden und dürfen eine bestehende
Sperre nicht umgehen. Es gibt keine verteilte Serverlease oder automatische
Recovery. Kein Codepfad behauptet globale Serverruhe oder endet fremde Arbeit.

## Python-API

| API | Bedeutung |
| --- | --- |
| build_manifest() | Vollständiges lokales Quelleninventar, keine HTTP-Anfrage |
| validate_execution_plan(plan) | S2/Disziplin/Build/Adapter/Digest/Optionen und Persistenzkapazität prüfen |
| OllamaHTTPClient(api_url, timeout) | Eingeschränkter Legacy-HTTP-Client; Standard für reale spätere Nutzung |
| OllamaAdapter(client) | Bestehende Legacy-Operationen auf einen injizierten Client abbilden; Fakes für Tests |
| adapter.body(plan, participant, prompt=None) | Payload über Legacy-Helfer, keine Anfrage |
| adapter.execute(plan, participant, identity, store, run_remaining=...) | Einen frisch reservierten S3-Versuch sequenziell bearbeiten; privaten Outcome zurückgeben |
| RunCoordinator(store, plan) | Koordination unter dem bereits gehaltenen S3-Lock |
| coordinator.run(adapter, resume=False, expected_head=None, progress=None) | Neue geplante Messplätze ausführen bzw. bestätigte überspringen; JSON-Fortschrittscallback optional |
| coordinator.inspect(expected_head=None) | Vollständige netzwerkfreie Resultprojektion und Resume-/Serverdiagnose |
| project_metrics(response, wall_ns) | Reine Legacy→S2-Einheiten-/Dezimalprojektion mit S2-Validierung |

Vor coordinator.run store.register_run(plan, asset_root=..., rubric_asset_root=...)
verwenden. Der Aufrufer verwahrt den Planpin und bestätigte Journal-Headpins
getrennt. Ohne expected_head ist kein kryptografischer Rollbacknachweis möglich;
head_pin_checked wird dann false. S3-/Hashpins sind keine Signaturen.
Produktiv nur OllamaHTTPClient verwenden; beliebige injizierte Testclients sind
keine Vertrauens-/Transportattestierung. Agenten-/Prozessrechte werden nie erteilt.

## CLI und Beispiel

```sh
python3 casting.py build-info
python3 casting.py run --help
python3 -m unittest discover -s tests -p test_ollama_adapter.py -v
```

Zuerst privat einen neuen Plan mit tatsächlichem Modellnamen/Digest, der angezeigten
Engine-/Adapterbindung und ausreichend Artefaktbudget über planning.py erstellen.
Die vorhandenen Golden-Pläne sind absichtlich keine ausführbaren Providerpläne;
keinen synthetischen Digest als echten Modellbeleg übernehmen. Beispielvariablen
zeigen auf eigene zuvor geprüfte lokale Definitionen, keine Beispielinferenz:

```sh
# Werte aus der privaten Planerstellung einsetzen; keine Secrets als Argumente.
S4_PLAN=plans.local/run.json
S4_COMPETITION=plans.local/competition.json
S4_RUBRIC=plans.local/rubric.json
S4_ASSETS=plans.local/assets
S4_PLAN_SHA256='HIER_DEN_GETRENNT_GESICHERTEN_PLANHASH_EINSETZEN'

python3 casting.py dry-run --plan "$S4_PLAN" --competition "$S4_COMPETITION" \
  --rubric "$S4_RUBRIC" --assets "$S4_ASSETS" --expected-plan-sha256 "$S4_PLAN_SHA256"

# Erst nach gesonderter Freigabe echter Inferenz:
python3 casting.py run --root casting-root --plan "$S4_PLAN" \
  --competition "$S4_COMPETITION" --rubric "$S4_RUBRIC" --assets "$S4_ASSETS" \
  --expected-plan-sha256 "$S4_PLAN_SHA256" --api-url http://127.0.0.1:11434

python3 casting.py inspect --root casting-root --plan "$S4_PLAN" \
  --competition "$S4_COMPETITION" --rubric "$S4_RUBRIC" --assets "$S4_ASSETS" \
  --expected-plan-sha256 "$S4_PLAN_SHA256" --output plans.local/result.json

# Nur nach bestätigten Abschlüssen; unsichere Zustände bleiben gesperrt:
python3 casting.py resume --root casting-root --plan "$S4_PLAN" \
  --competition "$S4_COMPETITION" --rubric "$S4_RUBRIC" --assets "$S4_ASSETS" \
  --expected-plan-sha256 "$S4_PLAN_SHA256"
```

validate hat dieselben Definitionsargumente wie dry-run. Beide sind vollständig
read-only: keine HTTP-Verbindung, Modellladung, neuen Prozesse oder Änderungen an
privaten Archiven. Sie prüfen keine Live-Providerfähigkeit. Rubric-Testdateien bei
Bedarf separat mit --rubric-assets übergeben. Diese Dateien werden nie ausgeführt.

API-Auswahl: --api-url vor OLLAMA_API_URL vor http://127.0.0.1:11434. Explizit leer
ist ungültig. .env wird nicht geladen. Die private API-Bindung wird archiviert;
bei Resume muss sie identisch sein. inspect braucht keinen Client und kein Netz,
aber dieselben gepinnten Definitionsdateien und Inputs. run legt einen neuen Store
bei Bedarf an; inspect/resume legen keinen fehlenden Store an. Vorhandene Runs
werden nicht durch erneutes run fortgesetzt: resume explizit verwenden.

--expected-head ist für run/inspect/resume als zusätzlicher separater Pin verfügbar.
--output schreibt ein neues, unverändertes S2-Result über den vorhandenen exklusiven
S2-Writer außerhalb des privaten Stores; kein Überschreiben. stdout enthält dieselbe
fachliche Resultstruktur innerhalb einer Quittung mit Head/Resume-/Serverdiagnose.
Fortschritt kommt als sichere JSON-Zeile auf stderr, ohne Prompt/Antwort/Endpoint.

Exitcodes: 0 erfolgreiche Prüfung bzw. vollständig erfolgreicher Run; 1 bestätigte
Einzelfehler oder interrupted/failed; 2 Validierungs-/Archivfehler oder abgewiesene
Resume-Anforderung; 130 Benutzerabbruch mit execution_outcome_unknown. Keine rohen
Exceptiontexte oder Zugangsdaten in Konsolenfehlern. Ein completed-Run mit
failed_slots>0 liefert Exitcode 1, obwohl alle Messplätze terminal sind.

## Fehlercodes, Kompatibilität und verbleibende Grenzen

Neue sichere Codes unter anderem engine_build_mismatch, adapter_version_mismatch,
model_digest_required/model_digest_changed, model_not_found/model_identity_ambiguous,
response_model_mismatch, model_catalog_invalid, temperature_not_representable,
s4_event_budget_exceeded/s4_artifact_budget_exceeded, api_url_invalid,
api_binding_mismatch, participant_binding_mismatch, time_budget_invalid, request_not_sent, request_policy_rejected, ollama_rejected,
request_outcome_unknown, ollama_response_invalid/ollama_response_limit,
ollama_metrics_invalid, deadline_before_send/deadline_exceeded/run_deadline_exceeded,
server_quiescence_unconfirmed, other_run_not_quiescent, resume_required, run_terminal,
archive_initialization_incomplete,
outcome_identity_mismatch/outcome_binding_mismatch/outcome_inventory_mismatch,
execution_archive_invalid. S1/S2/S3-Codes bleiben erhalten.

Keine Änderungen an benchmark.py, definitions.py, planning.py, workspaces.py,
report.py oder dashboard.py; keine Migration bestehender Archive, Änderung der
alten --resume-Semantik oder vorgezogene HTML-Projektion neuer S2-Resultate.
Der bisherige Runner und seine Reports bleiben mit bisherigen Archiven benutzbar.
S4 erzeugt ausschließlich neue Vertragsarchive unter dem gewählten Casting-Root.

Offen: echte separat freigegebene Ollama-Abnahme, belastbarer unabhängiger
Serverruhebeleg für verlorene Requests, verteilte Providerleases, Hardwarebelege,
Signaturen, Coding-Sandbox und OpenCode. S5 ergänzt deterministische Rubric-
Auswertung/Zeugnisse und benötigt für ausführbare Testpakete tatsächlich geprüfte
Isolation. Keine Qualitätspunkte aus Tokens/s, keine stillen Jury-/Cloud-Aufrufe.

## Lokaler Abnahmestand

67 eigenständige S4-Tests und alle 243 bisherigen Tests bestanden: **310/310,
keine Skips**. Die S4-Testbasis sperrt urlopen, socket.socket/create_connection
und subprocess.Popen für jeden Test; HTTP-Brückentests ersetzen zusätzlich den
lokalen Opener durch begrenzte In-Memory-Antworten. Fake-Ollama liefert synthetische
Daten, keine tatsächlichen Benchmarkresultate. Geprüft sind mehrere Teilnehmer/
Wiederholungen, alle Parameter, Digestdrift, bekannte/unklare Requestausgänge,
Resume ohne Wiederholung, Persistenzabbrüche, Journal-/Artefaktkorruption,
S2-Provenienz, Redirect-/Proxygrenzen und Fristablauf während dauerhafter Writes.

Die tatsächliche Standalone-CLI wurde zusätzlich in validate/dry-run mit einem
rein synthetischen, temporären Plan aufgerufen: kein HTTP, keine Inferenz und
kein angelegtes Archiv. Die bisherigen sechs Kernmodule, vorhandenen Tests,
Golden-Fixtures, Szenarien und alten Ergebnis-/Reportdateien wurden separat
gegen den Ausgangsstand gehasht und bleiben unverändert. Keine Commits/Pushes.
Unabhängige MCP-Prüfung und ausdrückliche Commit-Freigabe stehen aus.
