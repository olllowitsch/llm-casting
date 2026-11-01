# Wettbewerb – JSON-Vertrag v1 (Ziel v0.3+)

Verbindlicher Entwurf, noch kein vorhandener Parser. Grundlage:
[Architektur](ARCHITECTURE.md); Umsetzung: [Roadmap](../ROADMAP.md).
Ein bestehendes Performance-Szenario ist noch keine Wettbewerbsdefinition.

## Identität und gemeinsame Aufgabe

Ein Wettbewerb hat eine unveränderliche UUID `competition_id`, einen Namen,
eine `discipline` und positive ganzzahlige `definition_revision`. Die erste
Disziplin ist `performance`; spätere registrierte Disziplinen können etwa
Coding-Aufgaben abbilden. Unbekannte Disziplinen erlauben keine Ausführung und
keine automatische Auswahl einer fremden Rubric.

Genau ein `prompt`-Objekt enthält den gemeinsamen nichtleeren Text, seine positive
`version` und `sha256`. Keine Promptliste pro Modell. Alle Teilnehmer eines Laufs
erhalten dieselben Promptbytes und Eingabedateien. Modell-/Hardwareparameter,
Zeitlimits und Wiederholungen gehören in den [Lauf](RUN_CONTRACT.md).

| Pflichtfeld | Vertrag |
| --- | --- |
| `kind`, `schema_version` | `competition`, ganzzahlig 1 |
| `competition_id`, `name` | UUID, nichtleerer Anzeigename |
| `definition_revision` | Positive ganze Zahl; Änderung jedes Definitionsinhalts erhöht sie |
| `discipline` | Registrierter Disziplinbezeichner |
| `prompt` | Genau `version`, `text`, `sha256` |
| `assets` | Liste vorbereiteter gemeinsamer Eingaben; leer zulässig |
| `rubric` | Genau `rubric_id`, `revision`, `sha256` einer passenden Rubric |

Anzeigenamen sind keine Pfade oder Identitäten. Ein neuer Prompttext erfordert
neue Promptversion und Definitionsrevision. Derselbe Wettbewerb und dieselbe
Versionsnummer dürfen niemals andere Bytes bezeichnen. Andere Assets oder eine
andere Rubric erhöhen ebenfalls die Definitionsrevision; eine Rubricänderung
ändert nicht automatisch die Promptversion. Bereits gestartete Läufe behalten
ihren fixierten Definitionssnapshot.

## Eingabedateien und Tests

Jedes Asset enthält `path` (normalisierter relativer POSIX-Pfad), `sha256`,
`size_bytes` (nichtnegative ganze Zahl) und `role`: `input` oder `test`.
Vollständiges Inventar, keine Globs, absoluten Pfade, `..`, leeren Komponenten,
Symlinks, Hardlinks, Spezialdateien oder doppelten Pfade. Inhalt und Größe werden
vor Kopieren und vor Ausführung geprüft. Größen-/Anzahllimits sind in der
Engine-Policy begrenzt und im Laufplan fixiert; Überschreitung ist ein Fehler.
Keine Hostpfade oder Zugangsdaten im portablen Vertrag.

Testdateien sind Daten, keine Freigabe ihrer Ausführung. Disziplin-/Testadapter
und die Ausführungsrichtlinie entscheiden, ob und wie sie isoliert ausgeführt
werden dürfen. Definitionen enthalten keine freien Shell-Befehle. Verdeckte Tests
werden als gleichbleibende Testbelege für alle Teilnehmer versioniert, getrennt
vom an Teilnehmer freigegebenen Eingabematerial. Ihre Referenzen gehören zur
Rubric; Inhalte/Hashes können im öffentlichen Export aus Datenschutzgründen
entfallen, im privaten Prüfarchiv müssen sie gebunden bleiben.

## JSON- und Hashregeln (für alle neuen Verträge)

JSON ist UTF-8 ohne BOM. Doppelte Objektschlüssel, nichtendliche Zahlen und falsche
Typen werden abgewiesen; Boolean ist keine Ganzzahl. Unbekannte Kernfelder und
Versionen werden strikt abgewiesen. Erweiterungen erfordern eine veröffentlichte
Vertragsänderung, keine stillschweigende Interpretation.

`sha256` ist jeweils ein kleingeschriebener Hexwert mit 64 Zeichen, ohne Präfix.
Prompt- und Datei-Hashes beziehen sich auf exakte UTF-8- beziehungsweise Dateibytes.
Keine implizite Unicode-Normalisierung oder Zeilenumbruchkonvertierung; ein letzter
Zeilenumbruch ist Teil des Prompts. Validierung weist abweichende Hashes zurück.

Definitions- und Plan-Hashes beziehen sich auf das vollständige JSON-Objekt:
Schlüssel rekursiv lexikografisch sortiert, Arrays in gegebener Reihenfolge,
`ensure_ascii=False`, Separatoren `,` und `:`, `allow_nan=False`, UTF-8 ohne letzten
Zeilenumbruch. Für diese gehashten Objekte sind ausschließlich Strings, ganze
Zahlen, Boolean, null, Listen und Objekte zulässig; Parameter mit Dezimalwerten
werden als kanonische Dezimalstrings ohne Exponent und unnötige Nullen gespeichert
(z. B. `"0"`, `"0.25"`). Kein objektinterner Selbsthash; der Inhaltshash steht
im referenzierenden Dokument. Namen, ID und Revision sind im Hash enthalten.
Nicht-Python-Implementierungen müssen dieselben Bytes anhand gemeinsamer Fixtures
nachweisen; das ist kein Verweis auf eine bereits implementierte JSON-Normbibliothek.

## Schematisches Beispiel

Die konkreten, zusammenpassenden JSON-Beispiele in den vier Verträgen sind reine
Definitions-/Planungsbeispiele. Sie enthalten keine gemessenen Benchmarkwerte.
Der Wettbewerbsinhaltshash wird im Lauf gespeichert, nicht in dieser Definition.

```json
{
  "kind": "competition",
  "schema_version": 1,
  "competition_id": "11111111-1111-4111-8111-111111111111",
  "name": "Schematischer Performance-Wettbewerb",
  "definition_revision": 1,
  "discipline": "performance",
  "prompt": {
    "version": 1,
    "text": "Erkläre in drei kurzen Sätzen, wie ein Computerprozessor arbeitet.",
    "sha256": "7df1c900720fdbdecd6bde9c91460763f4900e2fb2991c4b83e9438ef24f84a6"
  },
  "assets": [],
  "rubric": {
    "rubric_id": "66666666-6666-4666-8666-666666666666",
    "revision": 1,
    "sha256": "1fa2b8558aa62edcb5466c85e5681f4753bd6ea72e69862e5699564e635f2f74"
  }
}
```

## Validierung und Kompatibilität

Beim Anlegen alle Pflichtfelder, UUIDs, positiven Revisionen, Disziplin, Hashes,
Assetinventar und Rubricbindung prüfen. Beim Laufstart Definition und alle
referenzierten Inhalte unveränderlich archivieren. Bei Resume dieselben Belege
prüfen, keine aktuelle Wettbewerbsdatei nachladen. Fehler führen zum sicheren
Abbruch vor Adapterarbeit. Pflichtprüfungen: Promptänderung ohne Versionswechsel,
mutierte Assets, Traversal/Links, Duplikate, falsche Rubric/Disziplin und unbekannte
Schema-Versionen. Formale JSON-Schema-Dateien und Validatoren entstehen erst im
ersten Implementierungsschritt, diese Dokumente behaupten deren Existenz nicht.
