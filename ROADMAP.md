# LLM Casting Show – verbindliche Roadmap v0.3+

Status: S1 und S2 implementiert und lokal geprüft; für S2 stehen unabhängige
MCP-Prüfung und Commit-Freigabe aus. Laufkoordination, Ausführung und Bewertung
sind weiterhin geplant.
Keine Versionsnummer hier behauptet einen veröffentlichten Git-Tag.

Verträge: [Architektur](docs/ARCHITECTURE.md),
[Wettbewerb](docs/COMPETITION_CONTRACT.md), [Lauf](docs/RUN_CONTRACT.md),
[Ergebnis](docs/RESULT_CONTRACT.md), [Rubric](docs/RUBRIC_CONTRACT.md).
Diese Datei ist die maßgebliche Entwicklungsreihenfolge. `[x]` bedeutet im
bestehenden Code implementiert, `[ ]` noch nicht als Schritt abgenommen.
Jeder offene Schritt wird einzeln abgeschlossen; keine parallele zweite Engine.
Zielversionen sind Planungsgrenzen, keine Termine oder Zusagen zur Provider-API.

## Bestehende Basis v0.2.0

- [x] **B1 – Sequenzieller Performance-Benchmark**
  - Ziel: reproduzierbare Ollama-Messmatrix; Komponenten: benchmark.py, smoke.json.
  - Akzeptanz: Threads und beide GPU-Modi, Vorbereitung/Warmup/Wiederholungen,
    think/num_ctx, Timings/Digests, Fehlerfortsetzung, Konsole/JSON/CSV und Dry-Run.
  - Tests: vorhandene BenchmarkTests mit FakeClient, Payloads, Statistik, Timeouts,
    API-Konfiguration und netzwerkfreiem Dry-Run.
  - Abhängigkeiten: Python 3.10+; echte Inferenz benötigt separat verfügbares Ollama.
- [x] **B2 – Robuste Serien und Resume**
  - Ziel: gesicherte Messungen erhalten; Komponenten: session/manifest/intent/run,
    Prüfsummen, Lock und atomare Speicherung in benchmark.py.
  - Akzeptanz: keine erneute erfolgreiche/terminal fehlgeschlagene Messung;
    Kompatibilitätsprüfung, Fortschrittsrekonstruktion und Korruptionsabbruch.
  - Tests: vorhandene ResumeTests für Abbruch, Digest-/Runnerdrift und Parallelzugriff.
  - Abhängigkeiten: B1; verlässliches lokales flock-/Rename-Dateisystem.
    Offene Ollama-Intents können heute erneut angefragt werden; keine Agenten-
    Resume-Garantie daraus ableiten.
- [x] **B3 – Offline-Einzel- und Vergleichsberichte**
  - Ziel: bestehende Archive auswerten; Komponenten: report.py, test_report.py.
  - Akzeptanz: Tabellen/Diagramme, Einheiten/Statistik, fehlende Werte, Escaping,
    Archivvergleich ohne Vermischung und keine Änderung der Quelldaten.
  - Tests: bestehende ReportTests, einschließlich Datenschutz und Netzwerkfreiheit.
  - Abhängigkeiten: B1-Archivstruktur; kein laufendes Ollama erforderlich.
- [x] **B4 – Zentrales Offline-Dashboard**
  - Ziel: Archive gemeinsam überblicken; Komponenten: dashboard.py, report.py.
  - Akzeptanz: Discovery, Übersicht/Details, Workload-/Digest-Trennung, Filter,
    Sortierung, lokale Ressourcen und sichtbarer Ausschluss beschädigter Archive.
  - Tests: vorhandene DashboardTests; optional vorhandenes Node für echte eingebettete
    JS-Filterlogik, keine Node-Abhängigkeit der Engine.
  - Abhängigkeiten: B3; Hardwareangaben können weiterhin unbekannt sein.

## v0.3 – Verträge und Standalone-Kern

### S1 – Versionierte Definitionsvalidatoren

- [x] Abgeschlossen
- Ziel: Wettbewerb und Rubric ohne Ausführung sicher laden und pinnen.
- Komponenten: definitions.py, schemas/competition.schema.json und
  schemas/rubric.schema.json, tests/test_definitions.py und synthetische Fixtures;
  vorhandene CLIs unverändert.
- Akzeptanz: eindeutige IDs/Revisionen, genau ein gemeinsamer Prompt, Assetinventar,
  passende Disziplin/Rubric, eindeutige Canonical-JSON-Bytes und Versionsablehnung.
- Tests: gültige Roundtrips, unbekannte Felder/Versionen, Bool/Integer, doppelte
  JSON-Schlüssel, Hash-/Promptdrift, Traversal/Links, Gewichte und Punkteanker.
- Abhängigkeiten: unabhängige Prüfung der hier definierten Verträge. Kein Ollama,
  OpenCode, DB oder neuer Prozessadapter nötig.

Lokaler Nachweis: 49 neue S1-Tests und alle 61 bisherigen Tests bestanden
(110/110, keine Skips). API, Limits, Profil und Revisionsvertrauensgrenze:
[S1_VALIDATION.md](docs/S1_VALIDATION.md). Keine Inferenz oder Testadapterausführung.

### S2 – Unveränderlicher Laufplan und portables Ergebnis

- [x] Abgeschlossen
- Ziel: vollständig aufgelöste Modellauswahl und Parameter vor jedem Start.
- Komponenten: planning.py, reine Planungs-/Validierungs-/Serialisierungsfunktionen,
  atomarer Einzeldatei-Export und Golden-Fixtures unter tests/fixtures/planning;
  private Zielkonfiguration getrennt von portablen Objekten.
- Akzeptanz: Plan-, Prompt-/Asset-/Rubricbindung, Teilnehmer-/Versuchsidentitäten,
  Limits und Capability-Prüfung; Konsole/Datei nutzen dieselben Objekte.
- Tests: Hashfixtures, Modell-/Parameterdrift, fehlende Hardware, Einheiten,
  Status-/Fortschrittsinvarianten, Standalone-/Integrations-JSON-Roundtrip.
- Abhängigkeiten: S1. Der Dry-Run führt keinerlei Adapterarbeit aus.

Lokaler Nachweis: 55 unabhängige S2-Tests plus alle 110 bisherigen Tests bestanden
(165/165, keine Skips). Dokumentation: [S2_PLANNING.md](docs/S2_PLANNING.md).
Alle bestehenden Vertragsbeispiele bleiben gültig; keine Modell-/Agenten-/Cloud-
oder Datenbankaufrufe. Workspace-/Artefaktübernahme, Isolation und Journal bleiben
in S3 ausdrücklich offen.

### S3 – Workspace, Artefaktarchiv und Isolationsgrenze

- [ ] Abgeschlossen
- Ziel: getrennte, überprüfbare Eingaben/Workspaces und belastbare Persistenz.
- Komponenten: Workspace-/Artefaktdienst, Journal, Einzelwriter-Lock, atomare Writes;
  Isolationsprofil als expliziter Ausführungsvertrag.
- Akzeptanz: eigene Räume je Lauf/Teilnehmer/Versuch; feste Inventare und Grenzen;
  sichere Unterbrechung, keine fremden Dateien, keine Secrets/Hostfreigaben.
  Reale Agenten-/Testausführung ohne nachgewiesene Isolation bleibt deaktiviert.
- Tests: Symlink/Hardlink/Traversal, Dateiaustausch, Limits, fremde Dateien,
  Crash an Schreibgrenzen, konkurrierende Writer und Rekonstruktion.
- Abhängigkeiten: S2. Betriebssystem-Isolation konkret wählen und prüfen;
  Workspace-Trennung allein gilt ausdrücklich nicht als Sandbox.

### S4 – Ollama-Adapter im neuen Kern, Legacy erhalten

- [ ] Abgeschlossen
- Ziel: Performance als erste Standalone-Disziplin auf den neuen Vertrag abbilden.
- Komponenten: Ollama-Adapter, Laufkoordination; bestehende Payload-/Metriklogik
  wiederverwenden, benchmark.py-CLI und alte Archive erhalten.
- Akzeptanz: fixierte Modelle/Parameter, sequenzielle Vorbereitung/Messung,
  Status/Abbruch/Resume; unklare serverseitige Arbeit blockiert einen neuen Start.
  Kein stiller Wechsel auf die heutige schwächere Intent-Wiederholungsregel.
- Tests: Fake-API, Digest-/Konfigurationsdrift, verspätete Antwort, Timeouts ohne
  bestätigten Serverstillstand, doppelte Requests, keine Doppelzählung und
  vollständige bestehende Benchmark-/Resume-Regression.
- Abhängigkeiten: S3. Reale Adapterabnahme ist ein später ausdrücklich beauftragter
  Test, nicht Bestandteil dieser Dokumentationsarbeit.

### S5 – Deterministische Bewertung und Zeugnisse

- [ ] Abgeschlossen
- Ziel: fachliche Qualität getrennt von Durchsatz bewerten.
- Komponenten: Rubric-Auswertung, registrierte disziplinspezifische Testadapter,
  isolierte Testausführung und unveränderliche assessment-Belege.
- Akzeptanz: versionierte Kategorien/Gewichte/Maxima, Pflichtgates vor Jury,
  nachvollziehbare Belege, keine Noten ohne Definition, Neubewertung ohne neue
  Modellarbeit und ohne Überschreiben alter Zeugnisse.
- Tests: Scoreformel/Rundung, fehlende Werte, Pflichtgatepriorität, Provenienz,
  Testtimeout, manipulierte Artefakte und wiederholte Neubewertung.
- Abhängigkeiten: S4; erste fachliche Rubric und Testpaket separat freigeben.

### S6 – OpenCode-Ausführungsadapter

- [ ] Abgeschlossen
- Ziel: Coding-Wettbewerbe über dieselbe Laufkoordination ermöglichen.
- Komponenten: OpenCode-Adapter und Providerbindung, Disziplinprofil; kein
  zweiter Scheduler, keine eingebettete Kopie eines Coding-Agenten.
- Akzeptanz: tatsächlich nachgewiesenes Protokoll/Version, gemeinsamer Prompt/Input,
  feste Tool-/Netzwerkpolicy, Prozessbaum-Abbruch, Status und sichere Resume-Grenze.
  Explizite Provideranforderungen statt unbemerkter Cloud-Nutzung.
- Tests: zunächst Fake-Prozess-/Adapterfixtures; Promptidentität, Secret-/Host-
  isolation, Zeitbudget, verbliebene Kinder und verlorene Abschlussbestätigung.
- Abhängigkeiten: S5 und konkret abgenommene Isolation aus S3; OpenCode-
  Machbarkeitsprüfung. Reale Agenten nur nach gesondertem Ausführungsauftrag.

## v0.4+ – Bewertung erweitern, Anzeigen und Integration

### S7 – Optionale unabhängige LLM-Jury

- [ ] Abgeschlossen
- Ziel: ergänzende qualitative Zeugnisse ohne harte Tests zu überstimmen.
- Komponenten: Juryadapter, Bewertungsprovenienz und Interessenkonfliktprüfung.
- Akzeptanz: ohne Jury vollständig nutzbarer Kern; fixierter Juryprompt/-modell,
  strukturierte begründete Punkte, keine Überschreibung deterministischer Gates,
  explizite Freigabe vertraulicher Daten und neuer Bewertungsbeleg bei Wiederholung.
- Tests: Jury-/Teilnehmeridentität, ungültiges JSON, Prompt-Injection in Artefakten,
  Timeout, fehlende Kategorien und unveränderte Originalzeugnisse.
- Abhängigkeiten: S6; Provider-/Datenschutz-/Budgetvertrag und Jury-Rubrics.

### S8 – Optionale Cloud-Codex-Referenz

- [ ] Abgeschlossen
- Ziel: getrennt gekennzeichnete Referenzlösung auf derselben Aufgabe.
- Komponenten: optionaler Referenzadapter, Datenfreigabe-/Budgetkonfiguration.
- Akzeptanz: keine Core-Abhängigkeit oder automatischer Fallback; gleicher Prompt/
  Input, dokumentierte Toolabweichungen, separate Messklasse und Provenienz;
  Referenz nicht automatisch als Wahrheit/Jury oder Wettbewerbssieger behandeln.
- Tests: deaktiviert bedeutet null Aufrufe; nur freigegebene Daten, Budget/Timeout,
  Fehler ohne Lokalabbruch, keine Vermischung lokaler Hardwarestatistik.
- Abhängigkeiten: S7; verfügbare Schnittstelle und Nutzungsbedingungen vor einer
  Implementierung prüfen. Keine bestimmte Cloud-API wird hier zugesichert.

### S9 – Neue Ergebnisprojektionen und Legacy-Leser

- [ ] Abgeschlossen
- Ziel: neue Wettbewerbe und Zeugnisse in Konsole/Datei/HTML nachvollziehbar zeigen.
- Komponenten: Renderer auf Result-Vertrag, bestehende report/dashboard-Helfer,
  lesender legacy_performance-Import und versionierte Exportprofile.
- Akzeptanz: identische fachliche Resultdaten, getrennte Bewertungs-/Hardwareklassen,
  Historie, fehlende Werte, private versus bereinigte Ansicht; alte Archive und
  heutige CLI-Aufrufe bleiben unverändert benutzbar.
- Tests: Golden-JSON/HTML, Statistik, XSS, Datenminimierung, inkompatible Vergleiche,
  keine Netzwerkzugriffe und bytegenau unveränderte Eingabearchive.
- Abhängigkeiten: S8. Keine historischen Scores oder Promptversionen erfinden.

### S10 – Dicomat-Integration als eigener Auftrag

- [ ] Abgeschlossen
- Ziel: Verwaltung/Steuerung/Persistenz und UI ergänzen, ohne die Engine zu kopieren.
- Komponenten: ausschließlich künftig im dicomat-Projekt zu entwickelnder Adapter,
  PostgreSQL-Persistenz, bestehende Authentifizierung, DataGrids/Diagramme/Historie.
  Vorgesehene Tabs: Wettbewerbe / Läufe / Benchmarks / Zeugnisse. Die bestehende
  Benchmark-Seite bleibt erhalten; keine UI-Implementierung in S1.
- Akzeptanz: Wettbewerb anlegen/versionieren, Lauf starten/Status/Abbruch/Resume
  mit denselben IDs und JSON-Verträgen; Engine bleibt standalone nutzbar;
  keine Browserpfade/freien Shell-Kommandos, keine zweite Bewertungslogik.
- Tests: Authentifizierung/Berechtigungen, Start-/Import-Idempotenz, Lockkonflikte,
  End-to-End mit Fake-Engine, JSON-Roundtrip und bestehende dicomat-Regression.
- Abhängigkeiten: S9; eigener Integrationsauftrag, Transport-/Deploymentvertrag
  und gesonderte Datenbankmigrationsfreigabe. Keine dicomat-Änderung hier.

## Abschluss jedes Schritts

Vertrag/Implementierung/Tests und aktuelle Dokumentation müssen übereinstimmen.
Bestehende Tests bleiben erhalten; Regressionen und fehlende Betriebsabnahmen
werden offengelegt. Reale Modell-/Agenten-/Cloud-Aufrufe benötigen einen expliziten
Testauftrag mit freigegebenen Daten und Budgets. Ein abgeschlossener lokaler
Schritt ist weder Commit- noch Veröffentlichungs- oder Deploymentfreigabe.

## Noch offene Architekturdetails

1. Konkretes OpenCode-Protokoll, Versionierung, Abbruch-/Resume-Evidenz und
   Trennung seiner Provider-/Toolkonfiguration (S6).
2. Konkreter nachweisbarer Isolationsmodus und betrieblich passende harte Limits
   für Coding-Agenten und Testausführung (S3, Ausführung sonst deaktiviert).
3. Fachliche Rubrics, Testpakete, eventuell Notenschwellen und Disziplinregister
   jenseits Performance (S1/S5).
4. Jury-/Cloudprovider, Identitätsnachweise, Datenfreigabe und Budgetierung
   (S7/S8); optionale Integrationen ändern die Unabhängigkeit des Kerns nicht.
5. Dicomat-Prozess-/Status-/Abbruchtransport, Persistenz und Betreiberinstallation
   (S10). Keine transport- oder datenbankspezifischen Felder im Engine-Ergebnis.
6. Aufbewahrungsfristen, geprüfte Exportprofile und gegebenenfalls Signierung
   zusätzlich zu Hashes (S3/S9); keine automatische Veröffentlichung.
