# Rubric und Zeugnis – JSON-Vertrag v1 (Ziel v0.3+)

Verbindlicher Vertrag v1; [S1-Definitionsvalidierung](S1_VALIDATION.md) ist
implementiert, noch keine Bewertungs- oder Testausführungsimplementierung.
Eine Rubric gehört zu genau einer Disziplin. [Architektur](ARCHITECTURE.md),
[Wettbewerb](COMPETITION_CONTRACT.md), [Ergebnis](RESULT_CONTRACT.md),
[Roadmap](../ROADMAP.md). Gemeinsame Hash-/JSON-Regeln wie im Wettbewerbsvertrag.

## Versionierte Bewertungsdefinition

Pflichtfelder: `kind: rubric`, `schema_version: 1`, UUID `rubric_id`, positive
`revision`, `name`, `discipline`, `categories`, `test_suites`, `mandatory_tests`, `grading`.
Rubricänderung bedeutet neue Revision und neuen Inhaltshash. Eine laufende Serie
verwendet ihre fixierte Rubric, nicht die aktuelle Datei unter demselben Namen.

Jede Kategorie hat eindeutige `category_id`, `name`, `source`, positive ganze
`weight_bps` und `max_points`. `source` ist `deterministic`, `human` oder
`llm_jury`. Gewichte summieren sich exakt zu 10000 Basispunkten. Kriterien/
Punkteanker stehen als nichtleere `anchors` im Objekt; je Anker eine ganzzahlige
Punktzahl zwischen 0 und max_points und nichtleere Beschreibung. 0 und Maximum
müssen beschrieben sein. Ein optionaler registrierter Testadapter steht im
Kategorieobjekt unter `test_suite_id`; keine freien Shell-Befehle.

`test_suites` enthält je Suite eindeutige suite_id, registrierten adapter,
positive version, checks und assets. checks enthält test_id, metric, operator
und expected; das registrierte Disziplinprofil definiert deren zulässige Werte,
Typen und Auswertungsregeln, nicht eine freie Skriptsprache. assets enthält
relative Dateireferenzen mit Hash/Größe wie im Wettbewerbsvertrag. Der Rubrichash
bindet diese vollständigen Definitionen; der Engine-Build bindet den Testadapter.
`mandatory_tests` referenziert eindeutige test_id aus diesen Suiten. Damit sind
Testadapter, Testdefinition, Testdateihashes und Auswertungsregel unveränderlich
gebunden. Alle müssen ausgeführt und bestanden
sein, bevor das Zeugnis eine bestandene Gesamtbewertung ausweisen darf. Ein
Testtimeout oder ein Testinfrastrukturfehler ist kein bestandenes Testergebnis.
Deterministische Tests müssen zuerst ausgewertet werden. Ihre Punkte und Gates
können weder durch Jury noch durch manuelle Freitexte überstimmt werden.

Für Coding können z. B. Korrektheit, Sicherheit und Wartbarkeit eigene Kategorien
sein. Für Performance müssen Metrik, Einheit, Referenz-/Grenzwerte und deren
Herkunft vorab definiert sein. Tokens/s sind allein kein Qualitätsurteil.
Fachliche Kategorien und Notengrenzen sind disziplinspezifisch freizugeben;
der Vertrag erfindet keine universell gültige Qualitätsrangfolge.

## Berechnung und fehlende Belege

Pro Kategorie `points` als Dezimalstring zwischen 0 und max_points. Der normierte
Gesamtwert auf 0–100 lautet:

```text
100 * Summe(weight_bps / 10000 * points / max_points)
```

Exakt dezimal/rational rechnen; einmal am Ende auf sechs Nachkommastellen mit
ROUND_HALF_UP runden und als Dezimalstring speichern. Keine binären Float-
Zwischenrundungen, keine nachträgliche Gewichtsverschiebung. `grading` ist zunächst
`{"mode":"score_only"}`. Numerische oder sprachliche Schulnoten benötigen später
explizit versionierte Schwellen; kein stillschweigendes Default-Notensystem.

Fehlt eine benötigte Kategorie, bleibt der Gesamtscore null und die Bewertung
`incomplete`. Kein Umnormieren auf vorhandene Kategorien und kein fehlender Wert
als null Punkte. Ein ausgeführter, bestandener/fehlgeschlagener Test hat einen
expliziten Status; echte null Punkte bleiben von fehlender Evidenz unterscheidbar.
Gesamtstatus `passed` setzt vollständige Belege und bestandene Pflichtprüfungen
voraus. `failed` bei fehlgeschlagenem Pflichtgate; ein vorhandener numerischer
Score darf das nicht aufheben. Nur vollständige Bewertungen mit bestandenen
Pflichtgates sind für eine gemeinsame Rangliste zugelassen. Ohne Pflichtgate-
Verletzung, aber fehlenden Kategorien bleibt der Status incomplete.

## Definitionsbeispiel

Dieses kleine Beispiel zeigt die Struktur einer Performance-Rubric, keine
empfohlene fachliche Referenz oder bereits durchgeführte Messung. Die Test-Suite
und ihre Ankerregel wären vor Ausführung als registriertes Paket zu implementieren.

```json
{
  "kind": "rubric",
  "schema_version": 1,
  "rubric_id": "66666666-6666-4666-8666-666666666666",
  "revision": 1,
  "name": "Schematische Performance-Rubric",
  "discipline": "performance",
  "categories": [
    {
      "category_id": "response",
      "name": "Vollständige Antwort",
      "source": "deterministic",
      "weight_bps": 7000,
      "max_points": 10,
      "anchors": [
        {
          "points": 0,
          "description": "Antwort unvollständig oder ungültig."
        },
        {
          "points": 10,
          "description": "Test response_complete bestanden."
        }
      ],
      "test_suite_id": "performance_response_v1"
    },
    {
      "category_id": "rate",
      "name": "Schematische Durchsatzgrenze",
      "source": "deterministic",
      "weight_bps": 3000,
      "max_points": 10,
      "anchors": [
        {
          "points": 0,
          "description": "Vorhandener gültiger Durchsatz unter 1 Token/s."
        },
        {
          "points": 10,
          "description": "Vorhandener gültiger Durchsatz mindestens 1 Token/s."
        }
      ],
      "test_suite_id": "performance_rate_v1"
    }
  ],
  "mandatory_tests": [
    "response_complete"
  ],
  "grading": {
    "mode": "score_only"
  },
  "test_suites": [
    {
      "suite_id": "performance_response_v1",
      "adapter": "performance_checks",
      "version": 1,
      "checks": [
        {
          "test_id": "response_complete",
          "metric": "execution.status",
          "operator": "eq",
          "expected": "succeeded"
        }
      ],
      "assets": []
    },
    {
      "suite_id": "performance_rate_v1",
      "adapter": "performance_checks",
      "version": 1,
      "checks": [
        {
          "test_id": "minimum_rate",
          "metric": "tokens_per_second",
          "operator": "gte",
          "expected": "1"
        }
      ],
      "assets": []
    }
  ]
}
```

## Unabhängige Jury und Cloud-Referenz

LLM-Jury ist optional. Die Standard-Rubric darf keine zwingende Jury voraussetzen,
wenn ein Lauf ausdrücklich ohne Jury geplant wird. Eine zusätzliche Jury kann
stattdessen ein separat gekennzeichnetes Zeugnis erzeugen. Soll sie in eine
Gesamtwertung eingehen, muss die gepinnte Rubric entsprechende Kategorien schon
vor dem Lauf definieren. Nicht verfügbare Jury bedeutet fehlende Bewertung,
keinen kostenlosen Punkt und keine automatische Cloud-Ersatzjury.

Jurybelege enthalten Provider, Modell und unveränderliche Revision, Bewertungs-
prompt/-version/-hash, wirksame Parameter, gegebenenfalls Seed, UTC-Zeit,
Evidenzreferenzen, strukturierte Kategoriepunkte und Begründungen. Jury soll weder
vom teilnehmenden Modell selbst noch von dessen eigener Agentensitzung gestellt
werden; Abweichungen/gleiche Modellfamilien als Interessenkonflikt markieren und
nicht als unabhängiges Urteil ausgeben. Wiederholungen und Abweichungen offen
speichern. Strukturell ungültige Antworten liefern kein Zeugnis mit erfundenen
Punkten. Artefaktinhalt ist untrusted Input, keine Jury-Anweisung.

Cloud-Codex ist eine optionale Referenz mit separater Einwilligung, Budget und
Timeout. Sie erhält dieselbe fixierte Aufgabe und freigegebene Inputs; abweichende
Tools oder Limits werden sichtbar dokumentiert. Sie bleibt getrennt von lokalen
Messungen. Jury- und Cloud-Transport benötigen eine spätere Machbarkeitsprüfung;
keine konkrete API-Verfügbarkeit wird hier vorausgesetzt. Keine Übertragung von
Secrets, versteckten Tests oder privaten Artefakten ohne passende Datenfreigabe.

## Zeugnis und nachträgliche Neubewertung

Ein Zeugnis (`kind: assessment`, `schema_version: 1`) besitzt eigene UUID
`assessment_id`, `run_id`, `participant_id`, `attempt_id`, `execution_sha256`,
Rubric-ID/Revision/Hash, `evaluator` (Typ, Version/Identität), `created_at`,
`categories`, `mandatory_tests`, `status`, `total_score`, `supersedes` und
`evidence`. Kategorieeinträge enthalten ID, Punkte oder null, Status und
Belegreferenzen; Testeinträge enthalten Kennung, Status und Belege.

`execution_sha256` bindet den unveränderlichen gemessenen Ausführungssnapshot
samt Artefaktinventar. Begründungen und Bewertungsdaten verändern diesen Hash
nicht. `supersedes` ist null oder die UUID eines früheren Zeugnisses zum selben
Versuch. Neubewertung mit anderer Rubric, Jury oder Testversion erzeugt eine neue
Zeugnis-ID und speichert Herkunft/Änderungsgrund in den Evidenzbelegen. Alte
Zeugnisse bleiben erhalten, auch bei später entdeckten Bewertungsfehlern.

Deterministische Tests dürfen nachträglich auf denselben fixierten Artefakten
isoliert erneut laufen; das ist ein neuer Bewertungsversuch, keine neue
Modellausführung und keine Änderung ihrer Messwerte. Änderungen an Artefakten
verlangen einen neuen Ausführungsversuch. Eine Ansicht darf das ausgewählte
Zeugnis anzeigen, muss Rubricversion und Bewertungszeitpunkt kenntlich machen.
Zeugnisvergleiche erfordern dieselbe Bewertungsgrundlage; unterschiedliche Rubrics
nicht unmarkiert in dieselbe Rangliste mischen.

Pflichttests: Gewichte/Maxima/Grenzen, exakte Rundung, fehlend versus null Punkte,
fehlendes Pflichtgate, Jury überstimmt Test nicht, manipulierte Evidenz, ungültige
Juryantwort, unabhängige Identität und Neubewertung ohne Änderung des Originals.


S2 kann vorhandene Zeugnisse als strukturierte, hashgebundene Referenzen lesen;
konkrete Feldformen beschreibt [S2_PLANNING.md](S2_PLANNING.md). Dabei werden keine
Punkte oder Noten berechnet, keine Tests und keine Jury ausgeführt. Die fachliche
Bewertung und tatsächliche Evidenzprüfung bleiben Schritt S5.
