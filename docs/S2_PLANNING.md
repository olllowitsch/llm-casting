# S2 – Unveränderliche Laufpläne und portable Ergebnisse

Implementierter lokaler Planungs-/Validierungsstand, keine Ausführungsengine.
[Run](RUN_CONTRACT.md), [Result](RESULT_CONTRACT.md),
[Competition](COMPETITION_CONTRACT.md), [Rubric](RUBRIC_CONTRACT.md) und
[S1](S1_VALIDATION.md) bleiben maßgeblich. Die nachfolgenden S2-Profilregeln
präzisieren bislang offene Unterobjekte innerhalb der vorhandenen Feldnamen.
Alle bisherigen Vertragsbeispiele bleiben gültig; kein neues Top-Level-Feld
wird in Laufplan oder Ergebnis eingeführt. Unbekannte Felder werden abgewiesen.

## Öffentliche API in planning.py

| Schnittstelle | Bedeutung |
| --- | --- |
| `create_run_plan(competition, rubric, config, *, asset_root=None, rubric_asset_root=None)` | Beide S1-Definitionen/Assetinventare prüfen, Referenzen ableiten und PinnedPlan erzeugen |
| `validate_run_plan(value, competition, rubric, *, asset_root=None, rubric_asset_root=None, expected_sha256=None, previous=None)` | Vollständige Bindung prüfen; optional vertrauenswürdigen Hash oder bisherigen PinnedPlan vergleichen |
| `PinnedPlan.as_dict()`, `.sha256`, `.competition()`, `.rubric()` | Unveränderliche kanonische Bytes; Getter liefern unabhängige Kopien |
| `serialize_run_plan(plan)` | Validierte kanonische Planbytes ohne Schlusszeilenumbruch |
| `competition_reference(competition)` | Bestehende fünf Referenzfelder aus einer bereits geprüften Definition ableiten |
| `plan_readiness(plan)` | Immer executable=false; Gründe für nicht nachgewiesene Fähigkeiten/fehlende Identitäten, GPU-Nutzung not_measured |
| `measurement_slots(plan)` | Feste `(participant_id, repetition)`-Schlüssel, keine Versuche starten |
| `new_attempt_identity(plan, participant_id, repetition)` | Neue UUID und Referenzen, keine Persistenz oder Start-/Retry-Freigabe |
| `initial_result(plan, *, at=None)` | Leeres geplantes Result; nur Erstellungszeit, keine Messwerte oder Zeugnisse |
| `validate_execution(value, plan)` | Einen gemeldeten Ausführungsbeleg strukturell prüfen |
| `validate_result(value, plan, *, expected_sha256=None, previous=None, assessment_rubrics=())` | Plan-/Beleg-/Fortschritts-/Zeugnisreferenzen prüfen, unabhängiges Dict zurückgeben |
| `serialize_result(value, plan, *, assessment_rubrics=())` | Validierte kanonische Resultbytes für Standalone und Integration |
| `validate_metrics(metrics)`, `validate_artifacts(artifacts, *, max_files=1000, max_bytes=104857600)` | Metrik-/Metadatenregeln prüfen; keine Artefaktbytes lesen oder übernehmen |
| `validate_run_transition(before, after)`, `validate_attempt_transition(before, after)` | Reine Übergangsprüfung, keine Zustandsmaschine mit Nebenwirkungen |
| `write_json_exclusive(path, value, *, protected_roots=())` | Ein explizites begrenztes JSON-Ziel atomar ohne Überschreiben veröffentlichen; kein fachlicher Validator |

Alle JSON-/Hashoperationen verwenden definitions.py. Keine zweite kanonische
Serialisierung oder SHA256-Implementierung. PinnedPlan hält zusätzliche private
S1-Snapshots im Speicher, aber seine portable as_dict-Ausgabe enthält ausschließlich
die Run-Vertragsfelder. Sein repr zeigt keine Definitionen/Prompttexte.

Disziplin, gemeinsamer Prompt und vollständiges Assetinventar sind transitiv über
competition.definition_sha256 gebunden, die Rubric zusätzlich direkt über rubric.
Es gibt keine zusätzlichen Prompt-/Asset-/Disziplinfelder pro Teilnehmer oder im
Plan. Gemeinsame Vorbereitung, Limits, Policy und Wiederholungen stehen einmal im
Plan. Modell-/Hardwareparameter bleiben genau in participants[].parameters.

## Erstes Modell-/Policyprofil

S2 unterstützt die Definition von Performance-Plänen mit execution_adapter=ollama
und provider=ollama. Das ist keine laufende Ollama-Anbindung. OpenCode und andere
Provider werden mit adapter_unsupported abgewiesen, nicht mit Ollama-Parametern
versehen. Die sieben Pflichtparameter sind exakt threads, gpu_mode, num_ctx,
temperature, seed, think und num_predict. Positive Integer für Threads/Kontext/
Ausgabetokens, nichtnegativer Integer für Seed, Boolean für think, cpu_only oder
automatic für gpu_mode und nichtnegativer kanonischer Dezimalstring für temperature.
Keine freien Provideroptionen. Boolean ist nie Integer, Float nie Dezimalstring.

Modellnamen sind portable Bezeichner einschließlich optionalem Namespace/Tag;
keine URLs, absoluten/Windows-/Traversal-Pfade oder IP-Adressen. Versionen und
Evaluatoridentitäten sind begrenzte Bezeichner, keine Endpoints oder Freitexte.
Unicode bleibt erhalten und wird nicht normalisiert. Die Erkennung ersetzt keine
Prüfung organisationsspezifischer vertraulicher Modellnamen vor Veröffentlichung.
revision_digest ist null oder ein kleiner SHA256-Hexwert mit 64 Stellen, optional
mit sha256:-Präfix; keine implizite Umschreibung. Dieses Format ist das initiale
Ollama-Profil, keine Zusage für zukünftige Provider-Digests.

Unbekannte Hardware bleibt exakt profile_id=null, profile_revision=null,
verified=false. S2 besitzt weder Hardwareprobe noch Inventararchivierung;
verified=true wird deshalb explizit mit hardware_evidence_unavailable abgewiesen.
Die spätere Beleganbindung erweitert die Implementierungsfähigkeiten, nicht die
Bedeutung dieses Flags. automatic beweist niemals GPU-Nutzung. Auch ein gelieferter
Modelldigest/Enginehash ist zunächst eine gebundene Deklaration, kein Nachweis einer
aktuellen Providerantwort oder tatsächlich ausgeführter Software.

Das initiale bekannte Policylabel ist inference_only. network_allowed ist eine
angeforderte Richtlinie, keine erteilte Netzwerkberechtigung. S2 implementiert
keine Sandbox. Engine-Version und source_sha256 sind Pflichtfelder; der Hash kann
im nicht ausführbaren Entwurf null sein. Fehlender Digest/Enginehash verbietet
Belege mit tatsächlich begonnenen Versuchen. Die Planung bleibt trotzdem möglich.

Zeitlimits sind positive ganze Sekunden mit request_timeout_seconds <=
attempt_deadline_seconds <= run_deadline_seconds. Wiederholungen sind positive
Integer; höchstens 10000 Messplätze. Kein Scheduler nutzt diese Budgets in S2.
Vorbereitungszahlen sind explizit, keine Defaults. Plan-Policy-Asset-/Anzahllimits
werden gegen die geprüften Wettbewerbs- und Testinventare geprüft.

## Unveränderlichkeit und Vertrauensgrenzen

Eine Definition wird vor Planerzeugung mit S1 inklusive tatsächlicher Assetbytes
geprüft. Danach hält PinnedPlan die kanonischen Plan-/Definitionssnapshots.
Änderungen an Prompt, Assetinventar, Rubric, Teilnehmern, Digest oder Parametern
ändern Hash und Inhalt. previous verlangt denselben Lauf und identische Bytes;
expected_sha256 vergleicht mit einer getrennt aufbewahrten Inhaltsbindung.

S2 besitzt keine globale ID-Datenbank und keinen Archivworker. Ohne vorherigen
vertrauenswürdigen Pin kann ein selbstkonsistenter fremder Plan nicht als Manipulation
erkannt werden. Die CLI meldet bei Prüfung deshalb pin_checked=false, wenn weder
--previous noch --expected-sha256 geliefert wurde. Ein Hash in derselben austauschbaren
Datei ist keine Autorität. Für einen bereits bekannten Lauf muss der spätere
Archiv-/Integrationsaufrufer seinen bisherigen Pin mitgeben. Finalisierung eines
Entwurfs mit neuem Digest/Build erhält eine neue run_id. create-plan erzeugt diese
UUID standardmäßig; eine explizite config.run_id dient unter anderem Golden-Fixtures.

Die Dateiprüfung ist wie S1 eine Momentaufnahme. S2 führt keine Modelle aus und
kopiert keine Inputs. Die erneute Prüfung und sichere Übernahme vor Ausführung
gehören zu S3. Ein gültiges Metadatenobjekt beweist keine echte Messung, keinen
Prozessstillstand und keine Autorenschaft. Berechtigungen/Signaturen sind getrennt.

## Konkretisiertes Result-/Executionprofil

Der portable Result-Header und seine Felder bleiben unverändert. executions ist
eine Liste von Objekten mit genau execution und sha256. execution hat exakt die
im Resultvertrag genannten 15 Felder; sein Hash bezieht sich auf den vollständigen
Beleg ohne objektinternen Selbsthash. Widersprüche zum Plan und doppelte IDs,
Artefaktpfade oder Messplätze werden abgewiesen.

metrics enthält immer die neun im Resultvertrag benannten Felder. Nicht gelieferte
Werte sind explizit null, Rohdauerwerte und Counts nichtnegative Integer; Durchsatz
als kanonischer Dezimalstring. Ein echter Wert 0 bleibt 0 und bedeutet nicht fehlend.
Ein Durchsatz benötigt Count und Dauer > 0. Exakt darstellbare Quotienten werden
exakt akzeptiert; andere Quotienten einmal auf sechs Nachkommastellen mit
ROUND_HALF_UP gerundet, ohne redundante Nullen. Abweichende Werte werden abgewiesen.
Diese Präzisierung betrifft ausschließlich neue S2-Metadaten, keine v0.2.0-Metriken.
Es werden keine fehlenden Werte berechnet oder ergänzt. Dezimalmetriken sind auf
2048 Zeichen begrenzt; die Rohbelege bleiben maßgeblich.

Fehler sind null oder genau code, phase, retryable und evidence. Code/Phase sind
kleine technische Bezeichner; keine Rohmeldungen, Queries oder Endpoints. evidence
enthält eindeutige UUID-Verweise auf private Artefakte desselben Versuchs.
provenance ist {} für unbekannte Herkunft oder genau engine, adapter_version,
model_revision_digest und evidence. Gelieferte Deklarationen müssen zum Plan passen;
die Evidenz-IDs müssen im jeweiligen Artefaktinventar vorkommen. Keine frei
verschachtelten Providerdaten, Secrets oder Hostpfade. Artefaktmetadaten enthalten
exakt die sieben Felder des Resultvertrags. Byte-/Dateiprüfungen und Archivierung
von Artefakten sind ausdrücklich noch nicht S2.

Zeitangaben verwenden UTC-Z mit bis zu neun Nachkommastellen. Prüfung und Vergleich
erfolgen ohne Float-Zeitstempel. planned hat keine Start-/Endzeit oder Messwerte;
running/uncertain haben Start, aber kein bestätigtes Ende. succeeded/failed/timed_out
haben beide Zeiten; cancelled kann vor Start beendet worden sein. Ein fehlgeschlagener
oder abgelaufener Versuch braucht einen Fehler, ein erfolgreicher darf keinen haben.
Ein Timeout ohne bestätigtes Ende muss ein späterer Executor als uncertain melden;
S2 kann die Physik eines gemeldeten Endes nicht verifizieren und erzeugt diese Belege
nicht selbst.

Terminale Versuche und uncertain-Belege bleiben beim previous-Vergleich bytegleich.
Ein bereits completed/cancelled/failed Lauf nimmt keine neuen Ausführungsbelege
mehr auf; spätere zusätzliche Zeugnisse bleiben als getrennte Historie möglich.
Ein neuer Anlauf darf nur einen unklaren Versuch desselben Messplatzes referenzieren;
keine Wiederholung terminaler Fehler. Die gesamte Kette bleibt erhalten, ohne Zyklen
oder Verzweigungen. Das ist eine Datenbeziehung, keine automatische Retry-Freigabe.
started_attempts zählt tatsächlich begonnene Anläufe; terminal_slots zählt nur den
aktuellen terminalen Anlauf je Messplatz. Ältere unklare Anläufe zählen nicht doppelt.
Unbegonnene geplante Plätze können nach Abbruch offen/unbearbeitet bleiben.
completed verlangt null offene Plätze; running/cancel_requested enthalten keine
unklaren aktuellen Anläufe; interrupted/failed keine weiterhin laufenden Anläufe.

## Vorhandene Zeugnisse lesen, keine Bewertung erzeugen

assessments enthält die im Rubricvertrag beschriebenen assessment-Objekte.
Die Rubricreferenz hat im S2-Profil die drei flachen Felder rubric_id, revision,
sha256. evaluator enthält type (deterministic/human/llm_jury), version und identity.
Kategorien enthalten category_id, points, status (complete/missing/error) und evidence;
Pflichtprüfungen test_id, status (passed/failed/missing/error) und evidence.
Punkte/Score sind kanonische Dezimalstrings oder null. S2 prüft Typen, Grenzen,
Beleg-/Ausführungs-/Rubricbeziehungen und offensichtliche Statuswidersprüche, aber
berechnet keinen Score und prüft keine Qualität, unabhängige Jury oder fachliche
Richtigkeit eines fremden Urteils. Ein fehlgeschlagenes Pflichtgate darf nicht
als bestandenes Zeugnis erscheinen.

Neubewertungen können eine andere Rubric referenzieren, ohne den Plan zu ändern.
Die zusätzliche Definition muss über assessment_rubrics bzw. --assessment-rubric
vorliegen; S2 prüft deren S1-Metadaten, Inhaltshash und Disziplin. Historische
Testdateien werden dabei nicht ausgeführt oder eingelesen; ihre Inventarhashes
bleiben referenziert. Originalzeugnisse und vorhandene Ausführungsbelege bleiben
bei previous unverändert. initial-result erzeugt stets assessments=[], niemals
Noten. Die spätere Bewertungsengine und die eigentliche Evidenzprüfung bleiben S5.

## CLI und Ausgabe

Alle folgenden Befehle sind rein lokal, auch ohne --dry-run. Das Flag wird zur
expliziten Dokumentation des Aufrufs akzeptiert. Es startet keine Unterprozesse,
Modelle, Adapter, Netzwerkzugriffe oder Dienste.

```sh
# S1: Wettbewerb und Rubric prüfen
python3 definitions.py competition tests/fixtures/definitions/valid/competition.json \
  --rubric tests/fixtures/definitions/valid/rubric.json \
  --assets tests/fixtures/definitions/valid/assets

# S2: Plan als kanonisches JSON auf stdout
python3 planning.py create-plan --dry-run \
  --competition tests/fixtures/definitions/valid/competition.json \
  --rubric tests/fixtures/definitions/valid/rubric.json \
  --assets tests/fixtures/definitions/valid/assets \
  --config tests/fixtures/planning/config.json

# Plan prüfen: dieselben Definitionen und Assets verwenden
python3 planning.py validate-plan --dry-run \
  --competition tests/fixtures/definitions/valid/competition.json \
  --rubric tests/fixtures/definitions/valid/rubric.json \
  --assets tests/fixtures/definitions/valid/assets \
  --plan tests/fixtures/planning/run-plan.json

# Leeres geplantes Ergebnis als JSON auf stdout
python3 planning.py initial-result --dry-run \
  --competition tests/fixtures/definitions/valid/competition.json \
  --rubric tests/fixtures/definitions/valid/rubric.json \
  --assets tests/fixtures/definitions/valid/assets \
  --plan tests/fixtures/planning/run-plan.json

# Ergebnis prüfen
python3 planning.py validate-result --dry-run \
  --competition tests/fixtures/definitions/valid/competition.json \
  --rubric tests/fixtures/definitions/valid/rubric.json \
  --assets tests/fixtures/definitions/valid/assets \
  --plan tests/fixtures/planning/run-plan.json \
  --result tests/fixtures/planning/initial-result.json

python3 planning.py hash tests/fixtures/planning/run-plan.json
```

create-plan erwartet eine Config mit genau participants, limits, repetitions,
preparation, policy und engine, optional run_id. Wettbewerbs-/Rubricreferenzen
werden aus den geprüften Dateien erzeugt, nicht aus einem zweiten Config-Prompt.
validate-plan und validate-result geben standardmäßig eine kurze JSON-Prüfquittung
mit Hash und nicht ausführbarer Readiness aus. --emit-json liefert stattdessen
das validierte Objekt. create-plan und initial-result liefern immer das Objekt.
Die Quittung ist kein portables Ergebnisobjekt. Fehler: Exitcode 2 mit sicherem
JSON auf stderr; Erfolg: Exitcode 0, ohne Ausführungs- oder Qualitätsaussage.

--expected-sha256 bindet einen gespeicherten Pin; --previous vergleicht eine
vorhandene Plan-/Resultdatei. --rubric-assets ist der separate Root für Rubric-
Testdateien. Dateioutput nur mit --output PFAD.json, als Zusatz zur stdout-Ausgabe.
Das Zielverzeichnis muss bereits existieren. Kein implizites Ergebnisverzeichnis,
keine Workspaces, kein eigener Webserver. Beispielsweise nach Anlage eines eigenen
leeren Planordners --output plans/run.json ergänzen; bestehende Dateien niemals
überschreiben. Keine dieser CLI-Zeilen startet eine Modellinferenz.

Der Writer arbeitet nur innerhalb dieses Projekts, außerhalb results/, reports/,
.git/, übergebener Assetroots und erkennbarer bestehender Archivwurzeln. Er nutzt
begrenzte Bytes, eine eigene temporäre Datei, fsync und Linux renameat2 mit
RENAME_NOREPLACE. Keine Hardlink-Zwischenphase. Ziel-/Parentaustausch, Schreib- und
Synchronisationsfehler liefern Fehlercodes. Nur die identifizierte eigene
Temporärdatei wird bereinigt, niemals ein ausgetauschtes Objekt. Nach Publikation
und anschließendem fsync-Fehler bleibt das endgültige Dokument erhalten und es
wird output_durability_unknown gemeldet. Kein automatischer Retry/Overwrite.
Das ist ein Einzeldatei-Export, keine vorgezogene S3-Archivverwaltung oder Isolation
gegen einen nicht kooperierenden Angreifer mit derselben UID.

## Golden-Vektoren und weitere Entwicklung

Unter tests/fixtures/planning liegen Config, nicht ausführbarer Entwurfsplan,
aufgelöster synthetischer Plan, leeres Result und synthetischer Abschlussbeleg.
Die .canonical.json-Dateien enthalten exakte UTF-8-Bytes ohne Zeilenumbruch;
vectors.json die zugehörigen S1-SHA256-Werte. Zusätzliche Unicode- und >2^53-
Integer-Vektoren sind für spätere TypeScript-Implementierungen bestimmt: normale
JS-Number-Verarbeitung und UTF-16-Schlüsselsortierung reichen nicht allgemein.
Kein Vektor ist eine echte Benchmarkmessung oder ein Ausführungsnachweis.

Zum Abschluss von S2 blieb S3 offen: sichere Workspace-/Input-/Artefaktübernahme,
Journal/Lock und Isolationsnachweis. Die inzwischen implementierte lokale
Speicherschicht und die weiterhin gesperrte Ausführungsgrenze sind in
[S3_WORKSPACES.md](S3_WORKSPACES.md) beschrieben. S2 stellt nur Datenverträge, Identitäten und Einzeldatei-Export
bereit. Ausführungsadapter, echte Hardware-/Prozessnachweise, Bewertung und WebUI
bleiben spätere gesonderte Schritte. Alte APIs und v0.2.0-Dateiformate werden nicht
umgestellt, bestehende Archive nicht migriert.


## Lokaler Abnahmestand

55 unabhängige S2-Tests und alle 110 bisherigen Tests bestanden (165/165, keine
Skips). Geprüft wurden die echten lokalen CLI-Befehle, zusätzlich die direkte
CLI unter gesperrten Socket-/HTTP-/Popen-Funktionen, Golden-Bytes/Hashes und
Schreib-/Austausch-/fsync-Fehler einschließlich Änderung nach Publikation.
Bestehende S1-/Legacy-Quellen, deren Fixtures/Schemas und die bisherigen Archive
werden separat auf unveränderte Inhalte geprüft. Unabhängige MCP-Prüfung und
Commit-Freigabe stehen aus; kein Git-Commit oder Push in diesem Auftrag.
