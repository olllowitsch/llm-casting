# S1 – Definitionsvalidatoren und Inhaltsbindungen

Implementierter, unabhängig testbarer Stand; keine Laufkoordination, Ausführung,
Bewertung, Jury, Datenbank oder Cloud-Anbindung. Maßgeblich bleiben
[Competition](COMPETITION_CONTRACT.md), [Rubric](RUBRIC_CONTRACT.md) und
[Roadmap](../ROADMAP.md). Nur Python-Standardbibliothek, Python 3.10+ und Linux-
Dateisystemoperationen mit dir_fd/O_NOFOLLOW; keine Installation von Paketen.

## Öffentliche Schnittstellen in definitions.py

| Funktion/Typ | Wirkung |
| --- | --- |
| `parse_json_bytes(data, *, limits=DEFAULT_LIMITS)` | Strikte bytes-Eingabe, UTF-8 ohne BOM, doppelte Schlüssel/ungültige Zahlen/Surrogate ablehnen |
| `load_json(path, *, limits=DEFAULT_LIMITS)` | Begrenztes Lesen einer normalen Datei ohne Links; sichere Fehlercodes statt Hostpfaden |
| `canonical_json_bytes(value, *, limits=DEFAULT_LIMITS)` | Vertragliche kanonische UTF-8-Bytes ohne Schlusszeilenumbruch |
| `content_sha256(value, *, limits=DEFAULT_LIMITS)` | SHA256 der kanonischen JSON-Bytes, 64 kleine Hexzeichen |
| `verify_content_sha256(value, expected, *, limits=DEFAULT_LIMITS)` | Erwarteten Hash prüfen; tatsächlichen Hash zurückgeben oder DefinitionError |
| `validate_decimal_string(value, *, nonnegative=False)` | Kanonischen Dezimalstring prüfen; keine Berechnung oder Umformatierung |
| `validate_assets(assets, root=None, *, limits=DEFAULT_LIMITS)` | Vollständiges dediziertes Inventar gegen Dateigrößen und Bytes prüfen; Rückgabe None |
| `validate_rubric(value, *, asset_root=None, previous=None, registry=DEFAULT_REGISTRY, limits=DEFAULT_LIMITS)` | Struktur, Profil, Referenzen, Gewichte, Anker und Assetbytes prüfen; unabhängige JSON-Kopie zurückgeben |
| `validate_competition(value, rubric, *, asset_root=None, rubric_asset_root=None, previous=None, registry=DEFAULT_REGISTRY, limits=DEFAULT_LIMITS)` | Genau einen Prompt, Rubric-ID/Revision/Hash/Disziplin und beide Assetinventare prüfen; unabhängige Kopie zurückgeben |
| `Limits` | Explizite unveränderliche Ressourcenlimits, an reine Python-APIs übergebbar |
| `CheckRule`, `DisciplineProfile`, `DisciplineRegistry` | Erweiterbare Registrierung reiner Definitionsprofile im Python-Code; keine dynamischen JSON-Plugins |
| `DefinitionError` | ValueError mit stabilen Attributen `code` und `location` |

Validatoren ändern weder das Eingabeobjekt noch Dateien. JSON-Eingaben über
load_json/parse_json_bytes laden: Ein bereits durch einen fremden Parser
zusammengeführtes Python-Dict kann verlorene doppelte Schlüssel nicht nachweisen. Zur dauerhaften Bindung
muss der Aufrufer die zurückgegebene Kopie und ihren Inhaltshash aufbewahren.
Hashes sind keine Signaturen und beweisen keine vertrauenswürdige Herkunft.

## CLI – ausschließlich lesend

Im Projektverzeichnis die mitgelieferten synthetischen Beispiele prüfen:

```sh
python3 definitions.py rubric tests/fixtures/definitions/valid/rubric.json
python3 definitions.py competition tests/fixtures/definitions/valid/competition.json \
  --rubric tests/fixtures/definitions/valid/rubric.json \
  --assets tests/fixtures/definitions/valid/assets
```

Bei Wettbewerben ist `--rubric` erforderlich. `--assets` bezeichnet einen dedizierten
Inventarroot für den Wettbewerb, `--rubric-assets` den gemeinsamen separaten Root
aller Test-Suite-Assets der Rubric. Ohne Dateien kann der jeweilige Root entfallen.
Bei angegebener leerer Inventarliste darf ein Root keine zusätzlichen Dateien
enthalten. Der Definitionsordner selbst ist kein Assetroot: seine JSON-Dateien
wären zusätzliche, nicht inventarisierte Eingaben. Testdateien werden nur gelesen.

Ein erwarteter negativer Aufruf (Exitcode 2):

```sh
python3 definitions.py rubric tests/fixtures/definitions/invalid/rubric-weights.json
```

Die CLI schreibt ausschließlich eine kurze JSON-Antwort auf stdout: bei Erfolg
ok/kind/sha256, `executable:false` und `history_checked`; bei Validierungsfehlern
ok=false, code und eine feste Schemaposition. Keine Prompts, Eingabedaten oder
absoluten Dateipfade in diesen Antworten. Exitcode 0 bestätigt ausschließlich die Definitionsgültigkeit,
weder Ausführbarkeit noch eine erfolgreiche Bewertung. Exitcode 2 bedeutet Eingabe-/Datei- oder
Validierungsfehler; argparse behandelt Syntaxfehler ebenfalls mit Exitcode 2.

## Revisionsvergleich und Vertrauensgrenze

`previous` beziehungsweise CLI `--previous DATEI` bindet die Prüfung an eine
bereits vertrauenswürdig aufbewahrte Definition derselben UUID. Rückwärtsrevisionen
und andere Inhalte unter gleicher Definitions-/Rubricrevision werden abgewiesen.
Geänderte Promptbytes benötigen zusätzlich eine höhere Promptversion. Ein letzter
Zeilenumbruch ist Teil der Promptbytes. Keine Unicode-Normalisierung.

Ohne previous kann S1 nur die einzelne Definition und ihre internen Hashbindungen
prüfen; es kennt keine globale Versionshistorie. Die CLI meldet deshalb
history_checked=false. Das bedeutet nicht, dass Änderungen unter gleicher Version
historisch erlaubt wären. Der spätere S2-Aufrufer muss bei bereits bekannter UUID
immer die vertrauenswürdige bisherige Definition vergleichen. Eine vom gleichen
Angreifer austauschbare previous-Datei bietet keine zusätzliche Autorität.
Für Vergleiche werden alte Inventare strukturell geprüft; ihre historischen
Dateien müssen nicht am aktuellen Assetroot vorliegen.

## Festgelegtes initiales Performance-Definitionsprofil

Nur `performance` ist standardmäßig registriert. `coding`, `code_analysis` und
`question_answer` sind reservierte Ausbauziele, aber nicht registriert und werden
wie unbekannte Profile mit discipline_unsupported abgewiesen. Es gibt keinen
Fallback auf Performance. Eigene Profile können bewusst über eine separate
DisciplineRegistry registriert werden; JSON kann weder Module noch Programme laden.
Die formalen S1-Schemas beschreiben ausschließlich das Standardprofil.

`performance_checks`, Version 1, ist ein Definitionsprofil, kein vorhandener
Testexecutor. Es akzeptiert:

| Metrik | Operatoren | Typ des erwarteten Werts |
| --- | --- | --- |
| execution.status | eq | succeeded, failed, timed_out oder cancelled |
| tokens_per_second | gte, lte | Nichtnegativer kanonischer Dezimalstring |
| prompt_tokens_per_second | gte, lte | Nichtnegativer kanonischer Dezimalstring |

Diese explizite Auswahl präzisiert die im Rubricvertrag an das Disziplinregister
delegierten Metriken/Operatoren/Typen. Nichts wird ausgewertet. Andere Adapter,
Versionen, Metriken oder Operatoren sind nicht bekannt. Alle registrierten S1-
Profile haben executable=false; Executors und fachliche Punktvergabe folgen erst
in späteren Schritten. Die Beispiel-Rubric ist keine empfohlene Qualitätsnorm.

UUIDs verwenden die kanonische kleingeschriebene Bindestrichdarstellung ohne
URN-/Klammer-/Kurzformen; es erfolgt keine automatische Umformung. Andere IDs
(Kategorien, Suiten, Tests) sind opake nichtleere Texte, keine Pfade. Dezimalwerte
wie "1.00", "01", "1e2", "+1", "-0" und Nichtzahlen sind nicht kanonisch.
Nichtnegative metrische Schwellen dürfen auch keinen negativen Wert enthalten.

## Limits und Dateisicherheit

| Grenze | Standard |
| --- | --- |
| JSON-Eingabe und kanonische Ausgabe | Je 1 MiB |
| Verschachtelung | 32 ineinander liegende Container |
| JSON-Knoten, einschließlich Objektschlüssel | 50000 |
| Einzelstring | 256 KiB UTF-8 |
| Ganzzahl | 4096 Bits |
| Assets | 1000 pro vollständigem Wettbewerbs-/Rubricinventar |
| Einzelasset / Gesamtbytes | 16 MiB / 64 MiB |
| Verzeichniseinträge beim Scannen | 10000 |

Verarbeitung endet bei Überschreitung, ohne Abschneiden oder Korrektur. Kanonische
Ausgabe wird begrenzt stückweise aufgebaut. Fließkommazahlen sind auch bei endlichem
Wert nicht Teil der neuen gehashten Definitionsobjekte; vorhandene Benchmark-
Messwerte und deren bisheriges Format bleiben davon unberührt.

Assetpfade sind relative POSIX-Namen, ohne absolute/Windows-/Globpfade, leere,
`.`-/`..`- oder wiederholte Komponenten, Backslashes und Steuerzeichen. Doppelte
Inventarpfade werden abgewiesen, auch über mehrere Test-Suiten im gemeinsamen
Rubricroot. Die Bytezahl wird vor dem Lesen kontrolliert, tatsächliche Bytes werden
gehasht. Nicht inventarisierte oder fehlende Dateien sind Fehler. Leere Verzeichnisse
sind erlaubt, werden aber gezählt. Symlinks in Dateien, Unterverzeichnissen und
Rootpfaden, Hardlinks, FIFOs und sonstige Spezialdateien werden abgewiesen.

Der Reader verwendet gepinnte Verzeichnishandles, O_NOFOLLOW, O_NONBLOCK und
Vergleiche von Device/Inode/Modus/Größe/mtime/ctime/Linkzahl vor/nach dem Lesen und
beim abschließenden Inventarabgleich. Er ändert keine Eigentümer, Dateimodi oder
Elternverzeichnisse und erzeugt keine Locks oder Workspaces. Die Prüfung ist eine
lesende Momentaufnahme, keine Isolation gegen Änderungen nach ihrer Rückkehr.
Quellen sollen ruhen; S3 muss beim späteren Kopieren/Ausführen erneut verifizieren.

`schemas/competition.schema.json` und `schemas/rubric.schema.json` sind lokale
JSON-Schema-2020-12-Beschreibungen, keine herunterzuladenden Validatoren. Der
Standardbibliotheksvalidator führt die vollständigen semantischen, Hash- und
Dateiprüfungen aus. JSON-Schema allein kann UTF-8/BOM, Duplicate Keys, Byte-/Depth-
Limits, Gewichtssumme, Anker-/Referenzbeziehungen und Dateizustand nicht bestätigen.
Es wird kein zusätzliches JSON-Schema-Pythonpaket vorausgesetzt oder installiert.

## Fehler und Prüfnachweis

Codegruppen: json_* (Encoding/Typ/Limits), file_* (Dateityp/Zugriff/Austausch),
asset_* (Pfad/Inventar/Bytebindung/Limits), schema_version_unsupported, unknown_field,
missing_field, *_invalid, *_unsupported, *_duplicate sowie
content_hash_mismatch, prompt_hash_mismatch, rubric_hash_mismatch,
rubric_reference_mismatch, rubric_discipline_mismatch, revision_conflict,
revision_rollback, previous_identity_mismatch, prompt_version_conflict und
prompt_version_rollback. Die vollständigen Codes stehen als feste Literale in
[definitions.py](../definitions.py); keine Rohparser-/OS-Fehlermeldungen ausgeben.

Synthetische positive/negative Fixtures unter tests/fixtures/definitions und die
unabhängige tests/test_definitions.py prüfen die Verträge; die bestehenden drei
Testsuiten bleiben unverändert. Vollständig ausführen:

```sh
python3 -m unittest discover -s tests -v
python3 -m unittest discover -s tests -p test_definitions.py -v
```

Es gibt keine Migration bestehender Archive, keine neue Benchmark-Engine und
keine Bewertung oder Inferenz. Die bisherige canonical/checksum-Logik der alten
Archive verwendet teilweise andere Serialisierungsregeln; sie wird bewusst nicht
durch die neuen v1-Funktionen ersetzt, weil dies bestehende Resume-Identitäten
brechen würde. Netzwerkschnittstellen werden in S1-Tests gesperrt und die CLI
wird nur an lokalen Definitionsfixtures geprüft.


## Abnahme S1 und Abgrenzung

110/110 Unit-Tests bestanden: 49 eigenständige S1-Tests sowie alle 61 bestehenden
Benchmark-/Resume-/Report-/Dashboard-Tests. CLI-Positivbeispiele geprüft;
Negativbeispiele enden mit Exitcode 2. Der Inhalt der bestehenden Runner-, Test-,
Szenario-, Ergebnis- und Reportdateien wird vor/nach der Arbeit separat verglichen.
Keine bestehende Archivmigration und kein Git-Commit oder Push in diesem Auftrag.
Unabhängige MCP-Prüfung steht noch aus. Nächster Entwicklungsschritt ist S2,
keine Agentenausführung oder Bewertungsengine im Rahmen von S1.
