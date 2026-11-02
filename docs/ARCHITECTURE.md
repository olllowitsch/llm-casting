# LLM Casting Show – Architektur v0.3+

Status: verbindlicher Zielvertrag; S1-Definitionsvalidatoren und reine S2-Plan-/
Ergebnisvalidierung sowie lokale Workspace-/Artefaktpersistenz sind implementiert
([S1](S1_VALIDATION.md), [S2](S2_PLANNING.md), [S3](S3_WORKSPACES.md)).
S4 ergänzt die sequenzielle Performance-Koordination über einen Ollama-Adapter
([S4](S4_OLLAMA_ADAPTER.md)); Coding-Ausführung und vollständige Bewertung sind noch geplant; der lesende
S5-Bewertungsteil ist in [S5_ASSESSMENT.md](S5_ASSESSMENT.md) beschrieben. Die Freigabe dieses Entwurfs ist keine Ausführungs- oder
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
nach ausdrücklicher Freigabe übertragen. S8 beginnt mit manuellem Import bereits
vorhandener Codex-Ergebnisse: keine automatischen Cloud-Aufrufe, API-Schlüsselpflicht
oder vorausgesetzten zusätzlichen API-Kosten. OAuth-/Codex-Anbindung bleibt eine
spätere Option mit offener rechtlicher/technischer Freigabe; keine konkrete
OpenAI-Freigabe oder Verfügbarkeit wird behauptet. Keine automatische Cloud-Nutzung
bei lokalen Fehlern. Neubewertung erzeugt ein neues Zeugnis auf denselben fixierten
Artefakten, keine erneute Modellarbeit und kein Überschreiben alter Urteile.

## Drei unabhängig versionierbare Projekte

| Projekt | Verbindliche Verantwortung | Abhängigkeiten |
| --- | --- | --- |
| [llm-casting](https://github.com/olllowitsch/llm-casting) | Python-Engine: Wettbewerbsdefinitionen, Pläne, Modelladapter, Workspaces/Artefakte, geplante Bewertung/Zeugnisse und portable JSON-Verträge | Keine WebUI-, dicomat- oder PostgreSQL-Abhängigkeit; CLI bleibt eigenständig |
| [llm-casting-show](https://github.com/olllowitsch/llm-casting-show) | Geplante eigenständige Open-Source-Web-App mit Node.js/TypeScript, versionierter HTTP-/JSON-API und eigener Persistenz | Kontrollierte lokale Engine-Schnittstelle; keine dicomat-Abhängigkeit oder duplizierte Engine-/Bewertungslogik |
| dicomat-refactor | Später optionaler Menü-/Integrationsadapter | Ausschließlich serverbasierte Kommunikation mit der Casting-Show-API; keine direkte Engine-/DB-Abhängigkeit oder zweite WebUI |

Der Webprojekt-Link bezeichnet das vorgesehene Repository; in diesem Auftrag wird
kein Repository angelegt und keine Web-App implementiert. Die Komponenten werden
unabhängig veröffentlicht/versioniert; Kompatibilität richtet sich nach den
jeweiligen Schnittstellenversionen, nicht identischen Release-Nummern.

## Eigenständige Webanwendung und optionaler Adapter

S10 plant **LLM Casting Show** als vollständig ohne dicomat installierbare Anwendung
mit vier Haupttabs: **Wettbewerbe / Läufe / Benchmarks / Zeugnisse**. Vorgesehen
sind ein eigener llm-casting-show.service und ein konfigurierbarer HTTP-Port,
beispielsweise 8090. SQLite ist das vorgesehene einfache Standalone-Backend,
PostgreSQL kann später optional folgen. Framework, DB-Bibliothek und konkretes
Engine-Prozessprotokoll sind noch nicht entschieden. Die Web-App besitzt ihre
Persistenz und Zugriffskontrolle selbst; dicomat stellt diese nicht voraus.

Geplante Betriebsarchitektur, noch nicht implementiert:

```text
Browser -> llm-casting-show.service (Node.js, HTTP-Port konfigurierbar)
        -> kontrollierte lokale Engine-Schnittstelle
        -> llm-casting (Python) -> Ollama / später optionale Agenten

Optional: dicomat-Server -> versionierte Casting-Show-HTTP-API
```

Die öffentliche HTTP-API bedient Browser und spätere Integrationsclients. Die
interne Engine-Schnittstelle steuert ausschließlich unterstützte Engine-Aktionen
mit geprüften JSON-Verträgen. Kein freier Remote-Shell-Endpunkt, keine Browser-
Dateipfade oder direkte Datenbankverbindung aus dicomat. Webserver und Engine
verwechseln HTTP-Auftragsannahme nicht mit bestätigter Ausführung/Beendigung.
S4-Uncertain-Sperren bleiben auch bei Webserver-Neustart/Resume maßgeblich.

S11 ergänzt ausschließlich einen optionalen dicomat-Adapter. Die bestehende
dicomat-Benchmark-Seite bleibt bis zu einem ausdrücklich freigegebenen Ablösungs-
oder Weiterleitungsplan erhalten; kein stilles Entfernen ihrer Verweise/Historie.
Ein bestehender read-only Exportweg wird in diesem Auftrag nicht geändert.

Verbindliche Zuständigkeitsgrenzen und als Entwurf markierte API-/Betriebsplanung:
[WEB_APP_ARCHITECTURE.md](WEB_APP_ARCHITECTURE.md). Es sind keine neuen HTTP-
Endpunkte, Dienste, Datenbanktabellen oder Integrationsfunktionen implementiert.

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
Juryprovider, manuelle Codex-Importbelege und spätere OAuth-/Codex-Freigaben,
fachliche Rubrics/Notengrenzen sowie Web-Framework, DB-Bibliothek, HTTP-/lokales
Engine-Protokoll (S10) und der optionale dicomat-API-Adapter (S11).
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


## Implementierte S4-Performance-Koordination

ollama_adapter.py verbindet die unveränderten Legacy-HTTP-/Payload-/Generate-/
Digesthelfer mit S1/S2 und dem bestehenden S3-Store. casting.py bietet die
Standalone-CLI. Keine zweite Journal- oder Statistikengine und keine kopierte
Legacy-Benchmarkschleife. Private Request-/Running-/Outcome-Belege werden über
S3 dauerhaft veröffentlicht und archiviert; das portable Result bleibt das
unveränderte S2-Schema und wird deterministisch daraus projiziert.

Ausführung beschränkt sich auf sequenzielle Performance-Inferenz am expliziten
Ollama-Endpunkt. Coding-/Prozessrechte bleiben gesperrt. Ungewisse Generierung
führt zu interrupted/uncertain und blockiert Resume sowie nächste Requests;
/api/ps wird nicht als Stillstandsnachweis verwendet. Bestätigte Abschlüsse
werden unverändert erhalten. Getestet ausschließlich mit Fake-API, keine reale
Inferenzabnahme. Betriebsannahmen, Instanz-Transportbrücke, Build-/Digestbindung
und noch fehlende unabhängige Serverruhebelege: S4_OLLAMA_ADAPTER.md.


## S5 – implementierte belegbasierte Teilbewertung

assessment.py prüft vorhandene S4-Resultsnapshots und Artefakte und erzeugt
unveränderliche Zeugnisse im bestehenden S2-Vertrag. Die exakte Scoreformel und
Pflichtgates sind implementiert; numerische Punktezuordnungen benötigen explizite,
rubricgebundene Regeln. Fehlende Daten oder nicht anwendbare Kategorien werden
nicht zu kostenlosen/null Punkten oder durch Umgewichtung kompensiert.

S3-Lese-/Publikations-/Lock-/fsync-Funktionen werden für einen getrennten privaten
Assessmentstore wiederverwendet, ohne Originalarchive oder Journale zu verändern.
Es gibt keine zweite Journalengine. Methoden-/Rubric-/Sourcebelege liegen in einer
privaten Speicherenveloppe; der öffentliche Assessmentkörper erhält keine Zusatzfelder.
Neubewertung erweitert nur die separate Resultprojektion, ohne neue Modellarbeit.

Die Registrierung vertrauenswürdiger Metadatenprüfer ist keine OS-Isolation.
Untrusted Testdateien, Agenten, Jury und Cloud werden nicht ausgeführt. Produktive
Rubricfreigabe und isolierte Executorabnahme bleiben offen; S5 ist ein Teilstand.
Die Web-App (S10) und der optionale dicomat-Adapter (S11) bleiben separate zukünftige
Projekte ohne Kopie der Engine-/Bewertungslogik. Details: S5_ASSESSMENT.md.
