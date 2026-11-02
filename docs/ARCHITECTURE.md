# LLM Casting Show – Architektur v0.3+

Status: verbindlicher Zielvertrag; S1-Definitionsvalidatoren und reine S2-Plan-/
Ergebnisvalidierung sowie lokale Workspace-/Artefaktpersistenz sind implementiert
([S1](S1_VALIDATION.md), [S2](S2_PLANNING.md), [S3](S3_WORKSPACES.md)).
Ausführungsengine und Bewertung sind noch geplant. Die Freigabe dieses Entwurfs ist keine Ausführungs- oder
Veröffentlichungsfreigabe. Umsetzung in [ROADMAP.md](../ROADMAP.md).

## Bestehender Stand v0.2.0

Die Bezeichnung v0.2.0 beschreibt den vorhandenen Funktionsumfang, nicht einen
hier geprüften Git-Release/Tag. Codeanalyse: `benchmark.py`, `report.py`,
`dashboard.py`, `scenarios/smoke.json` und die drei vorhandenen Testmodule.

| Komponente | Implementiert | Grenze |
| --- | --- | --- |
| `benchmark.py` | JSON-Szenarien; sequenzielle Modell-/Thread-/GPU-Matrix; Entladen, Vorladen, Warmup, Wiederholungen; explizites Thinking/Kontext; Timings und Digests; JSON/CSV, Fortschritt und Dry-Run | Ollama-Anfragen, keine Coding-Agenten oder Qualitätsbewertung |
| Resume | `session.json`, Runner-/Szenario-/API-Bindung, Digestvergleich, feste Messidentitäten, Intentdateien, Checksummen, flock und atomare Speicherung | Dauerhaft gespeicherte Fehler werden nicht wiederholt; unklare offene Inferenz kann beim Resume erneut angefragt werden; vorher serverseitiges Ende sicherstellen |
| `report.py` | Offline-Einzel-/Vergleichsberichte, Statistik, Einheiten, Warnungen und HTML-Schutz | Keine Jury, Noten oder Wettbewerbsverwaltung |
| `dashboard.py` | Archivübersicht, integrierte Details, Filter, Sortierung, Workload-/Digest-Trennung und HTML/CSS-Diagramme | Statische Momentaufnahme; keine Laufsteuerung |

Python-Standardbibliothek, Python 3.10+, lokale Archivdateien. Der Runner verwendet
intern `RUNNER_VERSION='2.0-resume'` und Sitzungsformat 2; diese Bezeichnungen
werden nicht nachträglich als neue Vertragsversion interpretiert. Vorhandene
Szenarien und Archive bleiben unverändert lesbar. Bestehende Runnerdaten beschreiben
keine verlässlich inventarisierte entfernte Hardware. Details zur heutigen
Bedienung und Messmethodik: [README.md](../README.md).

## Verbindliche Systemgrenzen

Die Engine gehört ausschließlich zu llm-casting. Sie benötigt weder dicomat noch
PostgreSQL, WebUI, Login oder einen eigenen Webserver. Standalone bleibt ein
vollwertiger Betriebsweg. Die Kernlogik verwendet weiterhin die Python-
Standardbibliothek; externe Werkzeuge sind optionale Adaptervoraussetzungen.

Geplante Verantwortlichkeiten, keine bereits vorhandenen Pakete/API-Signaturen:

| Bereich | Verantwortung |
| --- | --- |
| Verträge/Validierung | Wettbewerbe, Rubrics, Laufpläne, Ergebnisse und deren Versionen |
| Laufkoordination | Aufgelöster unveränderlicher Plan, sequenzielle Ausführung, Ereignisse, Abbruch und Resume |
| Adapter | Ollama-Inferenz bzw. OpenCode-Agentenausführung; Fähigkeiten und Grenzen explizit melden |
| Workspace-/Artefaktdienst | Getrennte Arbeitsräume, sichere relative Artefakte, Limits, atomare Publikation |
| Bewertung | Deterministische Tests, disziplinspezifische Rubrics, optionale Jury/Referenz und neue Zeugnisse |
| Projektionen | Derselbe Ergebnisvertrag für Konsole, JSON-Datei, HTML und externe Integration |

Wettbewerb → unveränderlicher Laufplan → Teilnehmer/Versuche → Artefakte und
Messungen → eigenständige Bewertungen → abgeleitete Anzeigen. Der Laufplan
pinnt Wettbewerb, Prompt, Eingabedateien, Rubric, Modelle und Parameter. Änderungen
an Definitionen verändern keinen bestehenden Lauf.

## Adapter und Ausführungsgrenze

Ollama ist zunächst der Inferenzadapter für den bestehenden Performance-Fall.
OpenCode ist ein geplanter Ausführungsadapter für Agentenarbeit. Ein OpenCode-
Teilnehmer kann Ollama als Modellprovider verwenden: Adapter und Modellprovider
sind unterschiedliche Felder, keine automatisch zwei konkurrierenden Ausführungen.
Es wird kein nicht geprüftes OpenCode-Protokoll oder bestimmter CLI-Schalter als
bereits unterstützt zugesichert. Der Adapter muss vor Freigabe Fähigkeiten,
Version, Terminierungs- und Resume-Verhalten nachweisen.

Modell-/Lauf-/Versuchs-Workspaces sind voneinander getrennt. Der gemeinsame Prompt
und die gemeinsamen Eingabedateien bleiben für alle Teilnehmer identisch.
Adapterspezifische Transporthüllen und Toolrichtlinien werden vor dem Lauf
festgehalten; verdeckte Umformulierungen oder zusätzliche Modellhilfen sind
unzulässig. Fehlt eine geforderte Fähigkeit, wird die Konfiguration abgewiesen.

Ein eigener Workspace ist keine Betriebssystem-Sandbox. Agentencode und
vorbereitete Tests sind potenziell ausführbarer, nicht vertrauenswürdiger Inhalt.
Vor realer OpenCode-/Testausführung sind ein überprüfter Isolationsmodus,
Dateisystem-/Prozess-/Ressourcenlimits und standardmäßig gesperrtes Netzwerk
verpflichtend. Keine geerbten Secrets, freien Shell-Kommandos aus Browserdaten,
Hostzugriffe oder automatischen Paketinstallationen. Ohne diese Voraussetzungen
bleibt reale Agentenausführung deaktiviert; reine Definition/Planung funktioniert.

## Bewertung und Referenzen

Deterministische Tests haben Vorrang vor subjektiver Beurteilung. Eine Jury kann
keine gescheiterten Pflichtprüfungen überstimmen. Unabhängige LLM-Jury und Cloud-
Codex-Referenz sind explizite Optionen, keine Standalone-Voraussetzung.
Unabhängigkeit, Interessenkonflikte und Datenfreigabe werden dokumentiert;
Modellunabhängigkeit allein garantiert keine objektive Beurteilung.

Eine Cloud-Referenz liefert eine getrennt gekennzeichnete Vergleichslösung;
sie ist weder automatisch Wahrheit noch Gewinner noch Jury. Ihre Leistung darf
nicht als lokale Ollama-Hardwaremessung ausgegeben werden. Inhalte werden nur
nach ausdrücklicher Freigabe übertragen. Keine automatische Cloud-Nutzung bei
lokalen Fehlern. Neubewertung erzeugt ein neues Zeugnis auf denselben fixierten
Artefakten, keine erneute Modellarbeit und kein Überschreiben alter Urteile.

## Dicomat als getrennte Anwendung

Dicomat verwaltet Wettbewerbe und Laufaufträge, persistiert den portablen Vertrag
in PostgreSQL und stellt DataGrids, Diagramme und Historie dar. Bestehende
Authentifizierung und Berechtigungen schützen Verwaltung, Start, Abbruch,
Dateizugriff und Export. PostgreSQL-Schema und UI sind ausschließlich Sache der
Integration, keine importierbaren Engine-Abhängigkeiten.

Die geplante Tabstruktur lautet **Wettbewerbe / Läufe / Benchmarks / Zeugnisse**.
Die bestehende Benchmark-Seite bleibt erhalten. Diese Struktur ist eine Vorgabe
für die spätere Integration, keine in S1 implementierte WebUI.

Die Integration ruft dieselbe Engine auf und importiert dieselben Ergebnis-
objekte wie Standalone. Kein kopierter Runner, keine zweite Bewertungslogik.
Lauf-ID, Versuchs-ID, Ergebnishash und Zeugnis-ID machen Wiederholungen beim
Import idempotent; PostgreSQL-IDs sind keine Engine-Identitäten. Browser liefern
IDs statt Dateisystempfaden. Ein Engine-Schreibzugriff pro Lauf bleibt maßgeblich;
ein Datenbankstatus darf ein noch laufendes Engine-Verfahren nicht duplizieren.

Der spätere Start-/Status-/Abbruchtransport ist ein schmales zu prüfendes
Integrationsdetail. Kein neuer HTTP-Dienst oder freier Remote-Shell-Endpunkt wird
mit dieser Architektur festgelegt. Ein beschränkter Prozess-/CLI-Transport ist
der bevorzugte erste Integrationskandidat. Bis zur gesonderten Integrations-
umsetzung bleibt ein vorhandener read-only Exportweg davon unberührt. In diesem
Auftrag wird dicomat weder geprüft noch verändert; keine Behauptung seiner Abnahme.

## Kompatibilität und Sicherheit

Produktversion, Dokumenttyp/Schema-Version, Adapterversion, Definition-Revision
und Inhaltshash sind verschiedene Identitäten. Die neuen JSON-Verträge verwenden
zunächst jeweils `schema_version: 1` mit eigenem `kind`. Sie ersetzen nicht das
vorhandene Sitzungsformat 2. Unbekannte Versionen werden vor Ausführung abgewiesen.

Alte Performance-Archive bleiben Rohbelege. Ein späterer lesender Import kann
sie als `legacy_performance` referenzieren; fehlende Wettbewerbs-, Hardware- oder
Bewertungsdaten bleiben unbekannt. Keine erfundenen Promptversionen, Digests oder
Scores. Die heutigen CLI-Aufrufe und Reportfunktionen bleiben erhalten.

Artefakte und JSON-Integrität sind von Zugriffsrechten zu unterscheiden: SHA256
ist keine Signatur und keine Autorisierung. Private Rohdaten, Prompts, Antworten,
Logs und Workspaces werden nicht automatisch veröffentlicht. Öffentliche HTML-
Projektionen zeigen keine Prompts, Secrets oder internen Pfade; Escaping und
lokale Ressourcen bleiben verpflichtend. Aufbewahrung und selektiver Export sind
explizite Betreiberentscheidungen.

## Dokumentationshoheit und noch zu prüfende Details

[Competition](COMPETITION_CONTRACT.md), [Run](RUN_CONTRACT.md),
[Result](RESULT_CONTRACT.md) und [Rubric](RUBRIC_CONTRACT.md) definieren gemeinsam
das Ziel. Nur [ROADMAP.md](../ROADMAP.md) führt den Arbeitsfortschritt.
Offen sind die konkrete OpenCode-Anbindung, Isolationsimplementierung,
Cloud-/Juryprovider, fachliche Rubrics/Notengrenzen und der dicomat-Transport.
Diese Details dürfen die festgelegte Unabhängigkeit, gemeinsame Promptversion,
Unveränderlichkeit und Sicherheitsgrenzen nicht aufweichen.


## Implementierte S3-Speichergrenze

workspaces.py verwaltet getrennte workspaces/artifacts/journals unter einem
privaten, explizit konfigurierten Casting-Root. S1/S2-Validierung, Canonical-JSON,
Hashbindungen und No-Replace-Publikation werden wiederverwendet. Bestehende
Performance-Archive und deren Runner-/Report-/Dashboardquellen bleiben unverändert.
Details und das konkrete Layout ersetzen die frühere logische Verzeichnisskizze:
[S3_WORKSPACES.md](S3_WORKSPACES.md).

Die Schicht persistiert Absichten, prüft eigene Inputs und unabhängige Artefaktkopien
und rekonstruiert unterbrochene Speicheroperationen. Sie erstellt keine Execution-
Belege oder Noten. active ist ohne echten Executor gesperrt, archived bestätigt
nur Speicherübernahme. Journale und Archive sind privat; externe Plan-/Headpins
und sichere Dateisystemrechte bilden die Vertrauensbasis. Getrennte Verzeichnisse
und SHA256 sind keine Sandbox oder Signatur. Die passive Isolationsprüfung meldet
immer executable=false; tatsächliche OS-Isolation/Prozesskontrolle bleibt vor
Coding-Agenten verpflichtend und noch unimplementiert.
