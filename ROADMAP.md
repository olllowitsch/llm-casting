# LLM Casting Show – verbindliche Roadmap v0.3+

Status: S1–S3 sowie S4-Ollama-Adapter und sequenzielle Performance-Koordination
sind implementiert und lokal mit Fakes geprüft (310 bestehende Tests). Reale
Providerabnahme, Coding-Ausführung, tatsächliche OS-Isolation und die vollständige
Bewertung sind weiterhin offen. S5 ergänzt ausschließlich die belegbasierte
Offline-Teilbewertung; S6 ergänzt das gesperrte lokale Protokollsimulationsprofil.
S10 plant die eigenständige LLM Casting Show Web-App,
S11 ausschließlich deren optionalen dicomat-Adapter; beides ist nicht implementiert.
Keine Versionsnummer hier behauptet einen veröffentlichten Git-Tag.

Verträge: [Architektur](docs/ARCHITECTURE.md),
[Wettbewerb](docs/COMPETITION_CONTRACT.md), [Lauf](docs/RUN_CONTRACT.md),
[Ergebnis](docs/RESULT_CONTRACT.md), [Rubric](docs/RUBRIC_CONTRACT.md).
Die [Web-App-Zielarchitektur](docs/WEB_APP_ARCHITECTURE.md) trennt drei unabhängig
versionierbare Projekte: Python-Engine, eigenständige Web-App und optionalen
dicomat-Adapter. Diese Datei ist die maßgebliche Entwicklungsreihenfolge. `[x]` bedeutet im
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
oder Datenbankaufrufe. Workspace-/Artefaktübernahme und Journal wurden anschließend in S3 ergänzt;
echte Ausführungsisolation bleibt eine gesperrte spätere Voraussetzung.

### S3 – Workspace, Artefaktarchiv und Isolationsgrenze

- [x] Abgeschlossen
- Ziel: getrennte, überprüfbare Eingaben/Workspaces und belastbare Persistenz.
- Komponenten: workspaces.py, tests/test_workspaces.py, docs/S3_WORKSPACES.md;
  Workspace-/Artefaktdienst, hashgebundenes Journal, exklusiver Store-Lock,
  atomare No-Replace-Publikation; passiver Isolationscheck ohne Ausführungsfreigabe.
- Akzeptanz: eigene Räume je Lauf/Teilnehmer/Versuch; feste Inventare und Grenzen;
  sichere Unterbrechung, keine fremden Dateien, keine Secrets/Hostfreigaben.
  Reale Agenten-/Testausführung ohne nachgewiesene Isolation bleibt deaktiviert.
- Tests: Symlink/Hardlink/Traversal, Dateiaustausch, Limits, fremde Dateien,
  Crash an Schreibgrenzen, konkurrierende Writer und Rekonstruktion.
- Abhängigkeiten: S2. Betriebssystem-Isolation vor späterer Ausführung konkret wählen und prüfen;
  Workspace-Trennung allein gilt ausdrücklich nicht als Sandbox.

Lokaler Nachweis: 78 eigenständige synthetische S3-Tests plus alle 165 bisherigen
Tests (243/243, keine Skips). API, Layout, Journal-/Manifestformat, Limits,
Fehler-/Resume-Grenzen und CLI: [S3_WORKSPACES.md](docs/S3_WORKSPACES.md).
S3 umfasst die lokale Speicherschicht und ein explizit gesperrtes Isolationsprofil:
kein Prozessstart, keine Ausführungsergebnisse und kein automatischer Retry.
Geprüfte prepared/archived-Zustände sind idempotent lesbar; unsichere Absichten
bleiben nach Neustart gesperrt. Tatsächliche Sandbox-, Prozessbaum- und harte
Ressourcenkontrolle sind nicht implementiert und vor Coding-Agent-Ausführung
zwingend nachzuweisen. Der S3-Abschluss behauptet keine solche Betriebsabnahme.

### S4 – Ollama-Adapter im neuen Kern, Legacy erhalten

- [x] Abgeschlossen
- Ziel: Performance als erste Standalone-Disziplin auf den neuen Vertrag abbilden.
- Komponenten: ollama_adapter.py, casting.py, tests/test_ollama_adapter.py;
  Legacy-HTTP/Generierungs-/Payload-/Digesthelfer und S3-Lock/Journal/Archiv
  wiederverwenden, unveränderte S2-Resultprojektion und alte Archive erhalten.
- Akzeptanz: fixierte Modelle/Parameter, sequenzielle Vorbereitung/Messung,
  Status/Abbruch/Resume; unklare serverseitige Arbeit blockiert einen neuen Start.
  Kein stiller Wechsel auf die heutige schwächere Intent-Wiederholungsregel.
- Tests: Fake-API, Digest-/Konfigurationsdrift, verspätete Antwort, Timeouts ohne
  bestätigten Serverstillstand, doppelte Requests, keine Doppelzählung und
  vollständige bestehende Benchmark-/Resume-Regression.
- Abhängigkeiten: S3. Reale Adapterabnahme ist ein später ausdrücklich beauftragter
  Test und in diesem Implementierungsauftrag ausdrücklich nicht durchgeführt.

Lokaler Nachweis: 67 unabhängige S4-Tests mit gesperrten Socket-/HTTP-/Popen-
Funktionen und Fake-Ollama; alle 243 bisherigen Tests bleiben erhalten
(310/310, keine Skips). [S4_OLLAMA_ADAPTER.md](docs/S4_OLLAMA_ADAPTER.md) beschreibt
API, CLI, genaue Transportklassifikation und Grenzen. Bestätigte Resultate sind
idempotent rekonstruierbar; unklare Requests oder Speicherabschlüsse sperren
weitere Modellarbeit. /api/ps ist kein Serverruhebeleg. Keine Force-Resume-Option,
keine reale Inferenz, keine lokale Agenten-/Testausführung und keine Änderung
von benchmark.py, definitions.py, planning.py, workspaces.py, report.py oder
dashboard.py. Die tatsächliche Ollama-Abnahme und Coding-Sandbox bleiben offen.

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

Implementierter S5-Teilumfang: [S5_ASSESSMENT.md](docs/S5_ASSESSMENT.md),
assessment.py, tests/test_assessment.py und eigene numerische Golden-Vektoren.

- [x] Verifizierte S4-Quellen/Artefakte und Performance-Metadatenchecks ohne Netz.
- [x] Exakte Scoreformel, Pflichtgatevorrang und explizite rubricgebundene Punkteregeln.
- [x] Unveränderliche S2-Zeugnisse, getrennte S3-Primitivpersistenz, Idempotenz und
  Neubewertung ohne Änderung der Originale; keine zweite Journalengine.
- [ ] Tatsächliche isolierte Testausführung und produktive Executorabnahme.
- [ ] Fachliche Freigabe einer produktiven Rubric/Testpaket-/Punktezuordnung.

Lokaler Nachweis: 78 eigenständige S5-Tests und alle 310 bisherigen Tests bestanden
(388/388, keine Skips), ausschließlich mit synthetischen Quellen/Fake-Ollama.
S1–S4-Laufzeitcode, Schemas, alte Golden-Fixtures und Archive bleiben unverändert.

S5 bleibt als Gesamtschritt offen. Freitextanker definieren keine allgemeine
maschinenlesbare Punktefunktion: ohne explizite Regel bleibt eine Kategorie
missing. Registry/Fake- bzw. Metadatenadapter sind keine OS-Sandbox. S6 wird
hiermit nicht freigegeben; S7-Jury und S8-Codex bleiben eigenständige spätere Schritte.

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

Implementierter erster Teil: [S6_OPENCODE_ADAPTER.md](docs/S6_OPENCODE_ADAPTER.md),
opencode_adapter.py und tests/test_opencode_adapter.py.

- [x] Offizielle CLI-/Config-/Permission-/Providerdokumentation recherchiert;
  dokumentierte Annahmen von lokal ungeprüfter Binary-/Wire-Kompatibilität getrennt.
- [x] Explizites normalisiertes Fake-Profil, Provider-/Modell-/Prompt-/Input-/
  Planbindung, Tool-/Netzwerk-/Ressourcenvertrag; reale Ausführung immer gesperrt.
- [x] Vorhandene S3-Persistenz und S2-Statusprojektion für ausdrücklich synthetische
  Referenzpläne; konservative Intent-/Timeout-/Abbruch-/Resume- und Idempotenztests.
- [ ] Versioniertes produktives Coding-/OpenCode-Planprofil; S1/S2-v1 bleiben erhalten.
- [ ] OpenCode-Wire-Decoder und konkrete Binary-/Provider-/Modellabnahme.
- [ ] Nachgewiesener OS-Executor, Ressourcenlimits, Prozessbaumende und reale
  Artefaktübernahme; keine Installation oder produktive Workspacefreigabe erfolgt.

S6 bleibt insgesamt offen. Das lokale Profil ist kein OpenCode-Wireformat und
keine Coding-Planfreigabe. S5 bleibt ebenfalls offen; fachliche Rubrics und
isolierte Testausführung sind weiterhin nicht abgenommen.

Lokaler Nachweis: 68 neue S6-Fake-/Vertragstests und alle 388 bisherigen Tests
bestanden (456/456, keine Skips). Keine realen Agenten-/Modellaufrufe. Alter
Laufzeitcode, normative Schemas, bisherige Tests/Golden-Fixtures und Archive
bleiben unverändert; das Safety-Gate verweigert jede reale Ausführung.

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
- Ziel: getrennt gekennzeichnete Referenzlösung auf derselben Aufgabe, zunächst
  durch manuellen Import bereits vorhandener Codex-Ergebnisse.
- Komponenten: optionaler Importadapter, Herkunfts-/Integritätsprüfung und
  Datenfreigabe; spätere OAuth-/Codex-Anbindung ausschließlich als Ausbauoption.
- Akzeptanz: gleicher Prompt/Input, dokumentierte Toolabweichungen, separate
  Messklasse und Provenienz; unbekannte Belege sichtbar markieren. Keine
  Core-Abhängigkeit, automatischen Cloud-Aufrufe, Fallbacks oder API-Schlüsselpflicht.
  Keine zusätzlichen API-Kosten voraussetzen; keine Aussage über kostenlose
  Codex-Nutzung. Referenz ist nicht automatisch Wahrheit/Jury oder Gewinner.
- Tests: manueller Import ohne Netzwerk/Schlüssel; ungültige/fehlende Belege,
  Prompt-/Versionsabweichungen und wiederholter Import; kein Überschreiben und
  keine Vermischung mit lokalen Hardwaremessungen. Eine deaktivierte spätere
  Cloud-Anbindung erzeugt null Aufrufe; Budget-/Timeouttests erst für diese Option.
- Abhängigkeiten: S7; Importformat und zulässige Herkunftsbelege festlegen.
  Rechtliche/technische Freigabe einer späteren OAuth-/Codex-Integration ist offen;
  keine konkrete OpenAI-Freigabe, Schnittstellenverfügbarkeit oder API zugesichert.

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

### S10 – Eigenständige LLM Casting Show Web-App

- [ ] Abgeschlossen
- Ziel: eigenständig installierbare und ohne dicomat benutzbare Open-Source-Web-App
  im vorgesehenen Repository github.com/olllowitsch/llm-casting-show.
- Komponenten: Node.js-/TypeScript-Runtime, eigener llm-casting-show.service,
  konfigurierbarer HTTP-Port (Beispiel 8090), versionierte HTTP-/JSON-API,
  eigene Persistenz mit vorgesehenem SQLite-Backend; PostgreSQL später optional.
  Vier Haupttabs: Wettbewerbe / Läufe / Benchmarks / Zeugnisse.
  Kontrollierte lokale Schnittstelle zur separat versionierten Python-Engine;
  keine duplizierte Ausführungs-/Bewertungslogik und keine dicomat-Abhängigkeit.
- Akzeptanz: Repository und Runtime als eigener Implementierungsauftrag einrichten;
  App ohne dicomat starten, Wettbewerbe verwalten, unterstützte Laufaktionen und
  Archivübernahme über dieselben Engine-Verträge bereitstellen. Administrative
  Aktionen authentifizieren/autorisieren; keine freien Browser-Kommandos/Pfade.
  Status/Abbruch/Resume respektieren Engine-Fähigkeiten und Uncertain-Sperren.
  Installations-, Konfigurations-, Update-, Backup- und Betriebsdokumentation
  einschließlich Dienst/Port, Berechtigungen und API-Kompatibilität bereitstellen.
- Tests: Runtime-/Browser-Typechecks und automatisierte API-/Persistenz-/UI-Tests;
  vier Tabs, Standalone-Start ohne dicomat, Portkonfiguration, Authentifizierung,
  Pfad-/Kommandomanipulation, Idempotenz und Neustartverhalten. Integration mit
  Fake-Engine einschließlich Abbruch/unsicherem Resume sowie lesender Altarchive.
- Abhängigkeiten: S9; eigene Framework-/Datenbankbibliotheks-/Prozessprotokoll-
  Entscheidungen, Zugriffsschutz und Installationsvertrag vor Implementierung.
  Siehe [WEB_APP_ARCHITECTURE.md](docs/WEB_APP_ARCHITECTURE.md). HTTP-/interne
  Schnittstellen sind Entwürfe, noch keine vorhandenen Endpunkte oder Dienste.

### S11 – Optionaler dicomat-Integrationsadapter

- [ ] Abgeschlossen
- Ziel: Menüintegration in dicomat mit serverbasierter Kommunikation zur API der
  eigenständigen Casting Show; die Anwendung bleibt vollständig ohne dicomat nutzbar.
- Komponenten: optionaler Adapter im separat versionierten dicomat-refactor,
  Menüverweis und kontrollierte API-Client-/Authentifizierungsanbindung.
  Keine zweite WebUI, Enginekopie, direkte Python-Engine- oder DB-Abhängigkeit.
- Akzeptanz: ausschließlich die versionierte Casting-Show-API verwenden; klare
  Benutzer-/Dienstidentitäten und Berechtigungsgrenzen, keine automatischen
  Rechteübernahmen. Keine direkten Datenbankzugriffe oder Browser-Engine-Pfade.
  Bestehende dicomat-Benchmark-Seite bis zu einer ausdrücklich freigegebenen
  Ablösung erhalten; Übernahme ihrer Verweise/Historie, möglicher Link bzw.
  Weiterleitung, Ausfallverhalten und Rückfallweg vor Umstellung planen.
- Tests: bestehende dicomat-Regression unverändert erhalten; Menü/Links,
  API-Versionen, Authentifizierung/Autorisierung, Timeouts/erreichbare und
  ausgefallene Casting Show, keine Abhängigkeit vom Engine-Dateisystem oder
  Casting-Show-DB; nachweisen, dass Standalone-Betrieb ohne Adapter funktioniert.
- Abhängigkeiten: S10 mit dokumentierter API/Auth-Grenze und eigenständigem Betrieb;
  separater dicomat-Auftrag und Freigabe des Ablösungs-/Installationsplans.
  Keine Änderungen oder Abnahme des dicomat-Projekts in diesem Auftrag.

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
   für Coding-Agenten und Testausführung (S3-Profil dokumentiert; Nachweis vor S6,
   Ausführung bis dahin deaktiviert).
3. Fachliche Rubrics, Testpakete, eventuell Notenschwellen und Disziplinregister
   jenseits Performance (S1/S5).
4. Juryprovider (S7), manuelles Codex-Importformat/Herkunftsbelege (S8) und
   rechtliche/technische Freigabe optionaler späterer OAuth-/Codex-Anbindung.
   Keine zusätzlichen API-Kosten, Schlüsselpflicht oder OpenAI-Freigabe voraussetzen.
5. Web-Framework, Node-Version, DB-Bibliothek/Migrationen, HTTP-API/Auth und lokales
   Engine-Protokoll (S10); serverbasierter dicomat-API-Adapter und Ablösung der
   bestehenden Benchmark-Seite (S11). Keine Web-/DB-Felder im Engine-Ergebnis.
6. Aufbewahrungsfristen, geprüfte Exportprofile und gegebenenfalls Signierung
   zusätzlich zu Hashes (S3/S9); keine automatische Veröffentlichung.
