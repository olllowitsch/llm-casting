# LLM Casting Show – eigenständige Webanwendung

Verbindliche Architekturentscheidung für die zukünftigen Schritte S10/S11.
**Implementierungsstand:** Nur die Python-Engine S1–S4 und ihre bestehenden
CLI-/JSON-Verträge sind implementiert. Dieses Dokument implementiert weder
Web-App noch Dienst, HTTP-Endpunkte, Datenbank oder dicomat-Adapter.
Alle nachfolgenden Schnittstellenbeschreibungen sind **Entwürfe/Anforderungen**;
konkrete HTTP-Routen, Auth-Protokolle und interne Prozessnachrichten sind offen.
Maßgeblicher Fortschritt: [ROADMAP.md](../ROADMAP.md).

## Projektgrenzen und Versionierung

| Projekt | Aufgabe | Unabhängigkeit |
| --- | --- | --- |
| [llm-casting](https://github.com/olllowitsch/llm-casting) | Python-Engine: Wettbewerbsdefinitionen, Ausführungspläne, Modelladapter, Workspaces/Artefakte, geplante Bewertung/Zeugnisse, portable JSON-Verträge | Ohne WebUI, dicomat oder PostgreSQL nutzbar; bestehende Standardbibliotheks-CLIs bleiben erhalten |
| [llm-casting-show](https://github.com/olllowitsch/llm-casting-show) | Vorgesehenes eigenständiges Open-Source-Webprojekt mit Node.js/TypeScript, HTTP-/JSON-API und eigener Persistenz | Ohne dicomat installierbar und vollständig benutzbar; keine Engine-/Bewertungsduplikation |
| dicomat-refactor | Optionaler späterer Integrationsadapter | Kommuniziert serverseitig nur mit der Casting-Show-API; kein direkter Python-Aufruf, kein Engine-Dateisystem-/DB-Zugriff, keine zweite WebUI |

Der Webprojekt-Link benennt das vorgesehene Repository, keine hier geprüfte
Verfügbarkeit oder angelegte Implementierung. In diesem Auftrag wird kein
Repository erstellt. Die drei Projekte erhalten unabhängige Releases.
Produktversion, HTTP-API-Version, internes Engine-Protokoll, Engine-JSON-
schema_version, Definitionsrevision und Inhaltshash bleiben getrennte Größen.
Eine gemeinsame Release-Nummer ist keine Kompatibilitätsvoraussetzung.

## Vorgesehener Betrieb – Entwurf

```text
Browser
  | HTTP-/JSON-API und WebUI
llm-casting-show.service (Node.js/TypeScript)
  | kontrollierte lokale Engine-Schnittstelle
llm-casting (Python)
  | Modelladapter
Ollama / später optionale Agenten

Optional: dicomat-Server -> Casting-Show-HTTP-API
```

Die Web-App soll einen eigenen systemd-Dienst llm-casting-show.service und einen
konfigurierbaren HTTP-Port besitzen. **8090 ist ausschließlich ein Beispiel**,
keine bereits eingerichtete Bindung oder verbindliche Standardeinstellung.
Installations-/Update-/Backup-/Wiederherstellungsdokumentation, Dienstidentität,
Dateirechte, Konfiguration, Netzwerkbindung und Zugriffsschutz gehören zu S10.
Keine Installation oder Dienst-/Portänderung in diesem Dokumentationsauftrag.

SQLite ist als einfaches Standalone-Backend vorgesehen; PostgreSQL kann später
optional ergänzt werden. Datenbankbibliothek, Migrationswerkzeug, Framework,
Node-Version und konkrete Prozessprotokolle werden vor Implementierung entschieden.
Es werden weder Pakete noch SQLite-Schemata oder PostgreSQL-Tabellen festgelegt.
Die Python-Engine erhält dadurch keine Node.js-/Datenbank-/Web-Abhängigkeit.

## Vier Haupttabs – geplante Verantwortung

| Tab | Geplante Aufgabe |
| --- | --- |
| Wettbewerbe | Definitionen anlegen/versionieren, gemeinsamen Prompt und Inputs verwalten; fachliche Prüfung durch die Engine |
| Läufe | Gepinnte Pläne, Modellauswahl/Parameter, unterstützte Laufaktionen und Fortschritt darstellen |
| Benchmarks | Vorhandene und neue Messungen mit Vergleichbarkeitsgrenzen, Diagrammen und Historie anzeigen |
| Zeugnisse | Engine-Bewertungen und deren Rubrics, Belege und Neubewertungshistorie darstellen; keine zweite Punkteberechnung |

Die Tabs gehören zur eigenständigen Casting Show. Dicomat übernimmt diese WebUI
nicht als eigene Implementierung. Nicht implementierte Engine-Funktionen bleiben
sichtbar als nicht verfügbar gekennzeichnet; die Web-App erfindet keine Bewertung,
Abbruchbestätigung oder Resume-Freigabe.

## HTTP-API für Browser und Integrationsclients – Entwurf

Die Web-App soll eine explizit versionierte HTTP-/JSON-API bereitstellen für
Wettbewerbsverwaltung, Laufaufträge/Status, erlaubte Abbruch-/Resume-Anforderungen,
Benchmarkübersichten, Zeugnisse und kontrollierten Artefakt-/Archivzugriff.
Diese Aufzählung ist **kein Endpunktkatalog implementierter Funktionen**.
URL-Pfade, HTTP-Methoden, API-Hülle, Fehlerkatalog, Pagination, Uploadgrenzen und
Authentifizierungsverfahren werden im Webprojekt als eigener Vertrag festgelegt.

Zugriff wird serverseitig authentifiziert und pro Aktion/Ressource autorisiert.
Insbesondere administrative Aktionen, Start, Abbruch, Resume, Import und private
Artefakte benötigen ausdrückliche Berechtigungen. Browserseitiges Ausblenden ist
keine Autorisierung. Lesender Zugriff auf vertrauliche Daten ist ebenfalls zu
schützen. Identitäten, Secrets und Dienstberechtigungen werden nicht ungeprüft
zwischen Browser, dicomat und Casting Show weitergereicht. CSRF-/Origin-/Session-
oder Tokenregeln hängen vom später gewählten Auth-Verfahren ab und sind zu testen.

Clients liefern validierte IDs und strukturierte Parameter. Keine freien
Shell-Kommandos, Executable-Namen, Umgebungsvariablen oder ungeprüften absoluten/
relativen Hostpfade aus Browserdaten. Administrative Rootkonfiguration bleibt
vertrauenswürdige Serverkonfiguration. Datei-/Archivzugriff erfolgt über IDs,
freigegebene Wurzeln, Inventare, Limits und Traversal-/Linkschutz. Modellantworten
und HTML-Artefakte sind untrusted Daten, keine ausführbaren WebUI-Inhalte.

## Lokale Webserver-/Engine-Schnittstelle – Entwurf

Der Webserver soll nur einen begrenzten, dokumentierten lokalen Engine-Adapter
verwenden. Ein kontrollierter Prozess-/CLI-Transport mit strukturiertem JSON ist
ein möglicher Ausgangspunkt; vorhandene CLIs sind **noch kein vollständiges
Webserver-Prozessprotokoll**. Transport, Nachrichtenframing, Lebenszyklus und
Kompatibilitätsprüfung bleiben Implementierungsentscheidungen von S10.

Anforderungen: feste erlaubte Engine-Aktionen, vertrauenswürdig konfigurierte
Programme/Argumente, keine Shellinterpretation von Browserdaten, begrenzte
Ein-/Ausgaben, explizite Secret-/Umgebungsfreigabe und überprüfte Prozessidentität.
Enginefehler und Uncertain-Zustände müssen unverfälscht zurückgemeldet werden.
Die Web-App orchestriert Aufträge, führt aber keine eigene Benchmark-, Retry-,
Digest-, Isolations- oder Bewertungsengine ein. Engine-Validatoren und sichere
Archivfunktionen bleiben maßgeblich; zusätzliche HTTP-Validierung schützt die
Transportgrenze und ersetzt keine fachliche Engine-Prüfung.

Ein Webserver-Requesttimeout, Prozessverlust oder Dienstneustart bestätigt weder
Engine- noch Ollama-Stillstand. Es darf keine zweite Engine-Operation für denselben
Lauf starten, nur weil ein Web-DB-Eintrag veraltet erscheint. Eigentümerschaft,
Auftrags-ID/Idempotenz, Lockkonflikte und Rekonstruktion sind in S10 explizit zu
prüfen. Die bestehenden Engine-Writer-Locks bleiben wirksam.

## Status, Abbruch und Resume – Entwurf mit bestehender Grenze

Die UI/API soll Enginezustände nachvollziehbar darstellen; HTTP-Auftragsannahme
ist keine bestätigte Ausführung. Angeforderter Abbruch ist kein bestätigtes Ende.
Webserver- und Engine-Auftragszustände sind getrennt zu versionieren/zuordnen.
Die genaue Statusübermittlung (z. B. Abfrage oder Ereignisse) ist noch nicht gewählt.

S4 kann bestätigte Belege rekonstruieren und sichere geplante Messplätze fortsetzen.
Ein unbekannter Generate-Ausgang oder Speicherabschluss bleibt uncertain bzw.
interrupted. /api/ps ist kein unabhängiger Stillstandsnachweis. Die zukünftige
Web-App darf dies weder durch einen Neustart, Force-Schalter, neuen DB-Status noch
unbemerkten neuen Lauf umgehen. Eine tatsächliche sichere Abbruchmöglichkeit muss
zuerst vom Engine-/Provideradapter unterstützt und belegt sein; die API darf sie
bis dahin nicht als verfügbar oder erfolgreich anbieten. Siehe
[S4_OLLAMA_ADAPTER.md](S4_OLLAMA_ADAPTER.md).

## Eigene Persistenz und Übernahme vorhandener Archive – Entwurf

Die Casting Show besitzt ihre eigene Datenhaltung für Verwaltung, Zugriffsschutz,
Aufträge, Indizes und Historie. Bestätigte Ausführungsbelege, Planbindungen,
Artefakthashes und Bewertungen stammen weiterhin aus der Engine. Web-DB-Projektionen
ersetzen keine maßgeblichen Enginejournale und erzeugen keine zusätzlichen Scores.
Transaktions-/Recoveryregeln zwischen Auftragsverwaltung und Engine sind vor S10
festzulegen; unbekannte Ergebnisse dürfen nicht als Erfolg importiert werden.

Vorhandene Performance-Archive sollen über den in S9 geplanten lesenden Legacy-
Import übernommen/indiziert werden, neue Archive über die portablen Engineverträge.
Keine automatische Umschreibung der Originale oder erfundenen historischen
Promptversionen, Digests, Hardwarebelege und Zeugnisse. Herkunft, Format und
fehlende Werte bleiben sichtbar. Konfigurierbare freigegebene Quellwurzeln,
begrenzte Leser, Konsistenzprüfung und idempotente Run-/Attempt-/Hashzuordnung
sind erforderlich. Ein Browserpfad darf keine beliebigen Serverdateien auswählen.

Die Engineobjekte bleiben fachlich identisch für CLI, Datei, Web-App und spätere
API-Clients. HTTP-/DB-Schlüssel und UI-Metadaten gehören in separate Hüllen.
Unbekannte Schema-/API-Versionen müssen explizit abgewiesen oder über veröffentlichte
Kompatibilitätsregeln behandelt werden. TypeScript muss Unicode- und Integer-
Präzision der vorhandenen Golden-Fixtures beachten; kein verlustbehaftetes
Number-Parsing gehashter JSON-Objekte. Es werden hier keine Verträge geändert.

## Optionaler dicomat-Adapter und bestehende Benchmark-Seite – S11

Der dicomat-Server soll über die versionierte Casting-Show-API kommunizieren.
Browser-Menüeinbindung, Navigation/Weiterleitung und gegebenenfalls API-vermittelte
Kontextanzeige dürfen keine zweite WebUI oder Engine-/Bewertungslogik erzeugen.
Dicomat erhält weder direkte Zugänge zur Casting-Show-DB noch zu Engine-Dateien
oder Python-Prozessen. Authentifizierungs-/Berechtigungsgrenzen beider Anwendungen
bleiben eigenständig; ein dicomat-Login ist kein automatischer Casting-Show-Zugang.
SSO/Delegation oder Dienstidentitäten werden erst nach gesondertem Auth-Entwurf
gewählt. Direkter gemeinsamer DB-Zugriff ist kein Integrationsweg. API-Zieladresse/Port
stammen aus geprüfter Serverkonfiguration, nicht aus einer frei wählbaren
Browser-Proxy-URL.

Die vorhandene dicomat-Benchmark-Seite und ihr bestehender Zugriff bleiben bis
zur genehmigten Umstellung erhalten. S11 muss zuerst Verweise, Daten/Historie,
Berechtigungen und Betriebsabhängigkeiten inventarisieren. Danach sind Menülink,
gezielte Ablösung oder Weiterleitung zur eigenständigen App samt Rechteprüfung,
Ausfallanzeige und Rückfallweg zu planen und freizugeben. Kein kommentarloses
Entfernen und keine automatische Datenmigration. Dicomat-Regression und
Standalone-Betrieb ohne Adapter sind getrennt nachzuweisen. Das dicomat-Projekt
wird in diesem Auftrag weder geändert noch als architektonisch geprüft behauptet.

## Codex-Referenz – Entscheidung für S8

Zunächst werden vorhandene Codex-Ergebnisse manuell importiert, mit derselben
Aufgaben-/Prompt-/Inputbindung, sichtbaren Toolabweichungen und Herkunftsbelegen.
Keine automatischen Cloud-Aufrufe, API-Schlüsselpflicht oder vorausgesetzten
zusätzlichen API-Kosten. Fehlende Belege bleiben unbekannt; Referenz, Jury und
lokale Hardwaremessung bleiben getrennt. Daraus folgt keine Aussage über Preise,
kostenlose Nutzung oder bestehende Codex-Berechtigungen.

Eine spätere OAuth-/Codex-Anbindung bleibt optional. Rechts-/Nutzungsbedingungen,
technische Machbarkeit, verfügbare Schnittstellen und Datenfreigabe sind noch offen.
Es wird keine konkrete OpenAI-Freigabe oder OAuth-/API-Verfügbarkeit behauptet.
Kein bestehender S1–S4-Ausführungspfad oder JSON-Vertrag wird dadurch geändert.

## Vor Implementierung zu entscheiden

- Web-Framework, unterstützte Node-Version und Build-/Testwerkzeuge.
- SQLite-Bibliothek, Datenmodell/Migrationen, Backup/Restore und optionale spätere
  PostgreSQL-Anbindung der Web-App.
- HTTP-Versionierungs-/Fehler-/Auth-Vertrag und kontrolliertes lokales
  Engine-Protokoll einschließlich Status-/Abbruch-/Resume-Fähigkeiten.
- Dienstidentität, Roots/Rechte, Netzbindung/TLS, Secretverwaltung und Installation.
- Importprofile/Aufbewahrung sowie späterer Auth-/Ablösungsplan für dicomat.
- Codex-Importformat und separat freizugebende optionale spätere Anbindung.

Diese Entscheidungen erfordern spätere Implementierungsaufträge. Dieser Stand
ändert ausschließlich Dokumentation und behauptet keine eingerichteten Dienste,
Repositorys, DBs, Endpunkte, Modellaufrufe oder Deployments.
