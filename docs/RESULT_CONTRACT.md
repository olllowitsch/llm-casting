# Portables Ergebnis – JSON-Vertrag v1 (Ziel v0.3+)

Verbindlicher Vertrag; [S2-Validierung/Serialisierung](S2_PLANNING.md) ist
implementiert, weiterhin kein Ersatz heutiger Archive. Verweise:
[Architektur](ARCHITECTURE.md), [Wettbewerb](COMPETITION_CONTRACT.md),
[Lauf](RUN_CONTRACT.md), [Rubric/Zeugnis](RUBRIC_CONTRACT.md),
[Roadmap](../ROADMAP.md). Gemeinsame JSON-/Hashregeln wie im Wettbewerbsvertrag.

## Ein Vertrag für Standalone und Integration

Das Ergebnisobjekt hat exakt `kind: result`, `schema_version: 1`, `run_id`,
`plan_sha256`, `competition`, `status`, `created_at`, `updated_at`, `progress`,
`executions` und `assessments`. `competition` enthält competition_id,
definition_revision, definition_sha256, prompt_version und prompt_sha256.
Der vollständige private Plan bleibt über plan_sha256 gebunden und archiviert.
Zeitpunkte sind ISO-8601 UTC mit `Z`; fehlende Zeitpunkte/Messwerte sind null.
Das Planungsbeispiel enthält bewusst noch keine Ausführungs- oder Bewertungsdaten.

```json
{
  "kind": "result",
  "schema_version": 1,
  "run_id": "22222222-2222-4222-8222-222222222222",
  "plan_sha256": "0cb18f78370b260f1915efe057815e5c5e413f79b4788105eab5d7a5193bc543",
  "competition": {
    "competition_id": "11111111-1111-4111-8111-111111111111",
    "definition_revision": 1,
    "definition_sha256": "0038e746a42218336e3294860f2d3efff277465b1dc27987a07c2ff6986af030",
    "prompt_version": 1,
    "prompt_sha256": "7df1c900720fdbdecd6bde9c91460763f4900e2fb2991c4b83e9438ef24f84a6"
  },
  "status": "planned",
  "created_at": "2026-01-01T00:00:00Z",
  "updated_at": "2026-01-01T00:00:00Z",
  "progress": {
    "planned_slots": 1,
    "started_attempts": 0,
    "terminal_slots": 0,
    "successful_slots": 0,
    "failed_slots": 0,
    "pending_slots": 1
  },
  "executions": [],
  "assessments": []
}
```

`progress` enthält geplante Messplätze (`planned_slots`), gestartete Anläufe
(`started_attempts`), abgeschlossene Messplätze (`terminal_slots`), erfolgreiche,
fehlgeschlagene und offene Messplätze. timed_out/cancelled zählen als terminale
nicht erfolgreiche Plätze; uncertain bleibt offen. Falls ein ausdrücklich neuer
Anlauf einen unklaren Anlauf ersetzt, bleibt dieser im Archiv, zählt aber nicht
zusätzlich als abgeschlossener Messplatz. Kein Zähler ersetzt die Einzelbelege.

`executions` referenziert für jeden Teilnehmer/Wiederholung die archivierten
Ausführungsbelege. Ein Beleg (`kind: execution`, schema_version 1) enthält
run_id, participant_id, repetition, attempt_id, plan_sha256, status,
started_at, finished_at, metrics, error, artifacts, provenance und
`supersedes_attempt_id` (null oder vorheriger unklarer Anlauf desselben Platzes).
Sein execution_sha256 wird außerhalb dieses Objekts berechnet. Finale Belege
werden nicht geändert; Zustandswechsel vorher stehen im Journal. Die aktuelle
Ergebnisprojektion enthält den referenzierten Beleg als `execution` sowie seinen
`sha256`; ersetzte Anläufe bleiben ebenfalls enthalten und explizit zugeordnet.

`assessments` enthält eigenständige Zeugnisse gemäß Rubricvertrag. Ihre Referenzen
binden denselben Ausführungsbeleg, keine mutable Ergebnisgesamtdatei. result.json
ist eine atomar erneuerbare Projektion aus Journal und unveränderlichen Belegen;
ihr Dateihash kann sich bei Fortschritt oder neuer Bewertung ändern. Für einen
Export wird der Hash des konkreten Exportdokuments separat im Exportinventar
festgehalten. Bewertung verändert keine Ausführungs- oder Artefakthashes.

## Messungen, Qualität und Vergleichbarkeit

Performance-Metriken behalten Rohdauerwerte in ganzzahligen Nanosekunden:
total_duration_ns, load_duration_ns, prompt_eval_duration_ns, eval_duration_ns;
prompt_eval_count und eval_count als nichtnegative ganze Zahlen. Client-
wall_duration_ns bleibt eine separate Messgröße. Durchsätze als Dezimalstrings
in tokens_per_second und prompt_tokens_per_second; count * 1e9 / duration,
bei Dauer null oder fehlendem Count null. Andere Adapter melden nur belegte
Metriken, keine erfundenen Ollama-Timings. Vorbereitung bleibt separat in provenance.

Fehlerobjekte enthalten sicheren `code`, `phase`, Boolean `retryable` und private
Evidenzreferenzen. retryable ist eine Diagnose, keine automatische Retry-Freigabe.
Öffentliche Ansichten übernehmen weder rohe Providerfehler noch beliebige Logs.
Modellausführungserfolg, bestandene Tests und Qualitätsbewertung sind getrennte
Sachverhalte. Eine schnelle oder technisch erfolgreiche Antwort kann fachlich
falsch sein. Fehlgeschlagene Ausführungen gehen nicht in Erfolgs-Durchsatzstatistik
ein, bleiben aber in Fehlerquote und Zeugnis sichtbar.

Aggregate bleiben abgeleitet: je Metrik gültige Stichprobengröße, Mittelwert,
Median und Stichprobenstandardabweichung. Fehlende Werte nicht als 0 behandeln;
Streuung bei weniger als zwei Stichproben null. Exakte Ausführungsbelege bleiben
maßgeblich. Definition/Prompt-/Asset-/Rubricversion, Digest, Parameter und
Toolrichtlinie dürfen nicht stillschweigend vermischt werden. Vergleichsachsen
(z. B. Threads, CPU/GPU oder Hardwareprofil) müssen vorab explizit benannt sein;
alle anderen Bedingungen bleiben gleich. Fehlende Hardwareevidenz oder Digests
sichtbar als unbestätigt markieren. Cloud-Referenzen bilden eigene Klassen.

## Artefakte und privates Archiv

Jeder Artefakteintrag enthält `artifact_id` (UUID), `path`, `sha256`, size_bytes,
media_type und classification (`private` oder `shareable`). Pfade sind relative
Inventarpfade innerhalb des Laufarchivs, keine URLs oder absoluten Hostpfade.
Normale Einzeldateien, keine Links/Traversal/Spezialdateien. MIME-Typ und
Dateiendung erlauben keine HTML-/JavaScript-Ausführung. Größen-/Anzahllimits,
fd-/Identitätsprüfung beim Übernehmen, Hashprüfung und atomare Veröffentlichung
sind Voraussetzung. Hash ist Integritätsschutz, keine Signatur gegen veränderbare
Originaldaten; Zugriffsrechte und optional spätere Signierung sind getrennt.

Private Roharchive dürfen Prompts, Antworten und Testausgaben enthalten und sind
standardmäßig von Git/öffentlichem Export ausgeschlossen. Shareable bedeutet
exportierbar nach Prüfung, keine automatische Veröffentlichung. Ein bereinigter
Export verweist auf ausgelassene Artefakte als nicht verfügbar und behauptet
keine erneute unabhängige Verifikation ohne die Originale.

## Darstellung, Datenschutz und Web-Integration

Konsole, Datei und HTML sind Projektionen desselben Ergebnisobjekts. Die Konsole
kann Fortschritt kurz anzeigen, die portable JSON-Ausgabe bleibt maßgeblich.
HTML lädt keine externen Ressourcen und escaped sämtliche dynamischen Texte.
Standard-HTML enthält keine Prompts, Antworten, Hostnamen, Endpoints, Zugangsdaten
oder lokalen Pfade. Auch Freitextbegründungen vor Export prüfen; Escaping allein
anonymisiert keine Daten. Eine bereinigte Ansicht ist kein zweiter Ergebnisvertrag.

Die geplante eigenständige llm-casting-show-Web-App übernimmt denselben portablen
Vertrag über ihre kontrollierte lokale Engine-Schnittstelle. Web-DB-Schlüssel,
Zugriffsschutz und UI-Metadaten bleiben außerhalb des Engineobjekts. Wiederholter
Import anhand run_id, attempt_id, Hashes und assessment_id darf keine Doppelzählung
erzeugen. Widersprüchliche Inhalte unter derselben unveränderlichen ID werden
abgewiesen; die Engine bleibt für Ausführung und Bewertung maßgeblich.

Ein späterer dicomat-Adapter kommuniziert ausschließlich mit der versionierten
HTTP-/JSON-API der Casting Show, nicht direkt mit Engine oder Datenbank. S10
(Web-App) und S11 (optionaler Adapter) sind getrennte zukünftige Schritte.
Schnittstellenplanung: [WEB_APP_ARCHITECTURE.md](WEB_APP_ARCHITECTURE.md).
Diese Dokumentationsänderung ergänzt keine JSON-Felder, Schemas, DB-Tabellen
oder implementierten HTTP-Endpunkte.

## Alte Archive, Fehler und Tests

Die heutigen Dateien manifest.json, run_*.json, summary.json/CSV, session.json und
intent_*.json bleiben unverändert. Der neue Vertrag wird daneben eingeführt.
Ein geplanter lesender Legacy-Import markiert die Herkunft ausdrücklich; fehlende
Wettbewerbs-/Zeugnisdaten bleiben fehlend. Kein automatisches Umschreiben und keine
neue v1-Identität als angeblich historische Originalidentität. Bestehende Reports
bleiben benutzbar; neue Renderer sollen ihre Statistik-/Escaping-Funktionen
wiederverwenden, ohne alte Resume-Identitäten zu ändern.

Pflichttests: Standalone-/Integrations-Roundtrip, unbekannte Version, fehlende Werte,
Timing-Einheiten und Formeln, widersprüchliche IDs/Hashes, Neubewertung,
Archivkorruption, Abbruch-/Intentzählung, öffentliche Datenminimierung und XSS,
Dateiaustausch/Links, keine Netzwerkzugriffe beim Rendern, unveränderte Quelldaten.


## Konkretisierung der Unterobjekte im S2-Profil

Bestehende Kernfelder/JSON-Beispiele bleiben unverändert. executions[] enthält
genau execution und sha256; der Executionkörper hat exakt die oben genannten
15 Felder. metrics enthält die neun genannten Metriken jeweils explizit, bei
fehlender Beobachtung null. Daten werden nur geprüft, nicht zu Messwerten ergänzt.
Ein nicht exakt als endlicher Dezimalstring darstellbarer Durchsatz wird einmal
mit ROUND_HALF_UP auf sechs Nachkommastellen gerundet, kanonisch ohne redundante
Nullen; exakt darstellbare Quotienten dürfen ihre exakte Präzision behalten.
Das ist eine Regel für neue S2-Objekte, keine Änderung bestehender Archive.

error ist null oder genau code, phase, retryable, evidence. evidence ist eine
Liste eindeutiger UUID-Verweise auf private Artefakte desselben Versuchs.
provenance ist {} bei unbekannter Herkunft oder genau engine, adapter_version,
model_revision_digest und evidence. Die ersten drei Werte müssen den deklarierten
Planangaben entsprechen; sie allein beweisen keine tatsächliche Providerbeobachtung.
Freie Rohmeldungen, Requestdumps, Hostpfade oder Zugangsdaten sind keine erlaubten
Provenienzfelder. Auch Belegreferenzen beweisen ohne extern gesicherte Originale
keine Authentizität. S2 liest/kopiert keine Artefaktbytes; dies bleibt S3.

Die strukturelle Zeugnisreferenz verwendet rubric_id/revision/sha256, evaluator
mit type/version/identity sowie die im [S2-Profil](S2_PLANNING.md) beschriebenen
Kategorie-/Testbelege. Eine andere Neubewertungsrubric muss separat geliefert und
gebunden werden. Es erfolgt keine Bewertung oder Scoreberechnung; nur Referenz-,
Typ-, Bereichs- und Statuskonsistenzprüfung vorhandener Daten. Plan und frühere
Zeugnisse werden nicht nachträglich überschrieben.

Alle Fortschrittswerte werden aus den gebundenen Einzelbelegen gegengeprüft.
S2 unterstützt deren Validierung und eine leere initiale Result-Erzeugung, keine
Modellausführung. Ein Timeout ohne bestätigtes Ende gehört zu uncertain; der
spätere Executor muss dies durchsetzen. Die Nachweisgrenze der reinen Metadaten-
prüfung, Zeitpräzision, Anlaufketten und CLI stehen in S2_PLANNING.md.
