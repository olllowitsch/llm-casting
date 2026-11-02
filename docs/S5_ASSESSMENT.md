# S5 – Deterministische Bewertung vorhandener Belege

Implementierter **Teilumfang** des offenen Roadmap-Schritts S5: Offline-Prüfung
vorhandener S4-Performance-Belege, exakte Scoreformel, Pflichtgates, explizite
Punkteregeln und unveränderliche S2-Zeugnisse. Keine HTTP-/Ollama-/Cloud-Aufrufe,
Jury, Agenten, Unterprozesse oder Ausführung von Testdateien. Python-Standardbibliothek.
Die Drei-Projekt-Architektur bleibt unverändert; keine Web-/DB-/dicomat-Abhängigkeit.

S5 wird **nicht vollständig abgehakt**: tatsächliche isolierte Testausführung und
die fachliche Freigabe produktiver Rubrics/Testpakete bleiben offen. Die vorhandenen
Anker sind Freitext und definieren keine allgemeine maschinenlesbare Punktefunktion.
S5 errät diese Funktion nicht. Bestehende Verträge und Golden-Fixtures bleiben
unverändert; insbesondere keine zusätzlichen Felder im Assessment- oder Resultobjekt.

## Unterstützte Disziplin und Kategorien

Aktuell nur performance mit performance_checks, Version 1, aus dem S1-Register:

| Prüfgröße | Operatoren | Quelle |
| --- | --- | --- |
| execution.status | eq | Validierter, terminaler S4-Ausführungsbeleg |
| tokens_per_second | gte/lte | Validierte S2-Metrik mit Counts-/Dauerbindung |
| prompt_tokens_per_second | gte/lte | Validierte S2-Metrik mit Counts-/Dauerbindung |

Die Vergleichswerte stehen in der gepinnten Rubric. Keine neuen fachlichen
Grenzwerte, Notenschwellen oder Qualitätsversprechen. Ein Durchsatztest ist nur
bei ausdrücklich definiertem Kriterium relevant; er beweist keine Antwortqualität.
Modellantworten und darin behauptete Punkte/Testerfolge werden nie ausgewertet.

Punkte werden nur für source=deterministic und eine ausdrücklich registrierte
BinaryCategoryRule vergeben. Diese bindet den **vollständigen Rubrichash**, eine
Kategorie, genau einen Test ihrer verknüpften Suite sowie zwei explizite numerische
Werte passed_points/failed_points. Die Werte müssen kanonische Dezimalstrings
zwischen 0 und dem vorhandenen max_points sein. Es gibt keine implizite Regel
"bestanden = Maximum" und keine Ableitung aus Freitextankern. Die Fachverantwortung
für die numerische Zuordnung bleibt beim registrierenden Betreiber/Anwendungscode.

Ohne Regel bleibt die Kategorie missing mit points=null. Human-/Jurykategorien
werden nicht automatisch bewertet. Nicht anwendbar wird mit dem vorhandenen
Status missing ausgedrückt; es gibt keinen neuen S2-Status und kein Umgewichten.
Suiten mit Testdateien bleiben ebenfalls missing: der Metadatenadapter interpretiert
oder startet diese Dateien nicht. Deren Eingabeinventar wird dennoch S1-validiert.

## Formel und Pflichtgates

```text
100 * Summe(weight_bps / 10000 * points / max_points)
```

Fraction-Arithmetik, kein Float; genau eine Rundung am Ende auf sechs Dezimalstellen
ROUND_HALF_UP, danach kanonischer Dezimalstring. Gewichte summieren sich wie in S1
exakt zu 10000. Fehlende Kategorien ergeben keinen numerischen Gesamtscore; keine
Normalisierung auf verfügbare Werte. Echte 0 Punkte bleiben von null unterscheidbar.

Pflichtprüfungen verwenden die bestehenden Statuswerte passed/failed/missing/error.
missing/error bedeuten fachlich nicht nachgewiesen, nicht bestandenes Pflichtgate
failed. Priorität:

1. Mindestens ein failed-Gate: Gesamtstatus failed. Bei vollständigen Kategorien
   kann ein diagnostischer Score vorhanden sein; er hebt den Gatefehler nicht auf.
2. Kein failed-Gate, aber ein unbekanntes Gate oder fehlende Kategorie:
   incomplete und total_score=null.
3. Alle Kategorien vollständig und Pflichtgates bestanden: passed mit Score.
   Das ist Vollständigkeit/Gate-Erfolg, keine erfundene fachliche Bestehensschwelle;
   daher kann auch ein vollständig belegter Score 0 diesen Status tragen.

Unbekannte, doppelte oder widersprüchliche Testbelege, ungültige Referenzen und
Manipulationen führen zum Fehler vor Veröffentlichung. Bekannte Testergebnisse
müssen mit den prüfbaren Execution-/Metrikdaten übereinstimmen. Ein behauptetes
passed kann einen fehlenden Messwert nicht ersetzen.

## Quellen, Registrierung und Integrität

verify_run verwendet S1-/S2-Validatoren und die rein lesende S4-Resultrekonstruktion
über S3. Geprüft werden Definitionen, Rubric-/Plan-/Promptbindungen, tatsächliche
Inputinventare, Journalkette, Manifest- und Artefaktbytes. Ein optional eingereichtes
Result muss dem rekonstruierten Original exakt entsprechen. Die sechs bestehenden
Kernmodule/CLIs werden nicht verändert. Alte v0.2-Archive ohne diese Grundlagen
sind keine S5-Bewertungsquelle; kein automatischer Import oder Erfinden von Belegen.

Der zu bewertende Versuch muss terminal sein. running/uncertain werden abgewiesen,
keine Wiederaufnahme/Modellarbeit ausgelöst. Ein terminal fehlgeschlagener Versuch
kann dagegen gemäß expliziter Rubric bewertet werden. Andere offene Versuche im
selben Run werden dadurch nicht als beendet oder erfolgreich behandelt.

TestAdapterRegistry registriert ausschließlich vertrauenswürdige Python-
ReadOnlyTestAdapter. Kein JSON-Plugin, dynamischer Import, Testdateipfad oder
Shellkommando. executes_code=true wird abgewiesen; das Flag ist **keine Sandbox**.
Registrierter Anwendungscode ist Teil der Vertrauensbasis und darf nicht aus
untrusted Archiven geladen werden. Der ausgelieferte Adapter rechnet nur mit
bereits verifizierten Metadaten. Eigene vertrauenswürdige Verifier können fehlende
oder fehlerhafte Belege melden; bekannte Resultate werden unabhängig gegen die
bestehenden performance_checks-Semantiken geprüft. Hinweise auf neue, isolierte
Executorprofile sind eine spätere Erweiterung, keine vorhandene Fähigkeit.

Bekannte Testergebnisse brauchen eindeutige Referenzen auf Artefakte desselben
Versuchs, einschließlich dessen verifiziertem outcome.json. Keine beliebigen
Belegidentitäten oder bloßen Modellbehauptungen. Die öffentlichen Zeugnisse
referenzieren ausschließlich bestehende Execution-Artefakte, wie S2 es verlangt.

Methodenmanifest: Hashes der relevanten lokalen Python-Quellen, explizite Regeln
und registrierte Adapteridentitäten/-Hashes. evaluator.type=deterministic,
version=s5-v1, `identity=s5-<Methodenmanifest-SHA256>`. Das ist Nachvollziehbarkeit,
keine Signatur oder OS-/Interpreterattestierung. Competition/Revision/Prompt sind
transitiv durch execution_sha256 und den gepinnten Plan gebunden; die Zielrubric
steht in den bestehenden Feldern rubric_id/revision/sha256.

Externe Plan-/Rubric-/Result-/Journal-/Zeugnispins sind von lokalen Hashen zu
unterscheiden. Geschützter Store und vertrauenswürdige Betreiber bleiben nötig.
Eine gemeinsam ersetzte Hashkette ist ohne separat aufbewahrten Pin nicht
kryptografisch als Manipulation erkennbar. Quelldateien dürfen nicht parallel
unter Umgehung des kooperierenden Writer-Locks verändert werden.

## Persistenz ohne zweite Journalengine

Eigener privater Zielroot, beispielsweise assessments.local, strikt außerhalb des
Quellroots und ohne dessen Überlappung. Beide Roots verwenden WorkspaceStore-
Locks. Der Quellroot bleibt einschließlich Originalresultaten/Artefakten unverändert.
S5 verwendet dieselben S3-Reader, Writer, No-Replace-Publikation, Inode-/Linkprüfung
und fsync-Grenzen. Es gibt keine nachgebildeten Messläufe, neue Journalengine oder
zweite veränderliche Fortschrittsdatei.

```text
assessments.local/
  store.json, writer.lock            # unveränderte S3-Grundstruktur
  workspaces/                       # leer, reserviert
  journals/                         # leer, keine S5-Hashkette
  artifacts/
    assessment-store.json            # Kennung des privaten S5-Speicherprofils
    <assessment-id>.json             # jeweils ein atomar veröffentlichtes Objekt
```

Dies ist ein dediziertes Speicherprofil auf S3-Primitiven, **kein ausführbares
S3-/S4-Runarchiv**. Es darf nicht mit casting.py als Laufroot verwendet werden.
Ein bestehender Quell-/Runstore wird nicht als AssessmentRepository adoptiert.
Neue Roots sind privat; keine fremden Elternrechte, Dienste oder Systeme ändern.

Jedes Objekt enthält den unveränderten S2-Assessmentkörper plus seinen SHA256,
Zielrubric, Methodenmanifest, geprüfte Checkbelege, Auftragsbasis und ursprünglichen
S2-Resultsnapshot mit dessen Hash sowie den beobachteten Quell-Journalhead.
Das ist eine private Speicherenveloppe, **kein konkurrierender Ergebnisvertrag**.
Die Envelope bindet Bewertungsprovenienz außerhalb der unveränderlichen Execution;
neue Post-hoc-Belege werden nicht als zusätzliche Execution-Artefakte ausgegeben.
record_sha256 wird als separat aufbewahrbarer Pin zurückgegeben.

Ein Einzelobjekt enthält alle notwendigen Bewertungsmetadaten und wird einmalig
kanonisch über S3._json veröffentlicht: Dateiflush/fsync, No-Replace-Rename,
Verzeichnis-fsync, erneute Identitäts-/Inhaltsprüfung. Keine Teilzeugnisse oder
Überschreibung. Öffentlich bleibt assessment exakt der bestehende S2-Vertrag.
Der ursprüngliche Execution-Artefaktbestand muss weiterhin erhalten bleiben;
die Envelope ersetzt kein vollständiges portables Roharchiv.

Limits: 1 MiB je JSON-Objekt, höchstens 1000 Repositoryobjekte/64 MiB Gesamtbytes,
höchstens 128 Zeugnisse je Plan und 128 Kategorien. Exakte Arithmetik ist auf
16384 Zähler-/Nennerbits begrenzt; Überschreitung wird abgewiesen, nicht gerundet
oder abgeschnitten. Die bestehenden S1-/S2-/S3-Limits gelten zusätzlich.

## Idempotenz, Neubewertung und Wiederanlauf

Die deterministische Assessment-UUID wird aus einer versionierten Namespace-UUID
und SHA256 der Auftragsbasis gebildet: Plan-/Execution-/Rubric-/Methodenhash,
supersedes samt vorherigem Assessmenthash und optionaler request_id. Mutable
Gesamtresult-/Journalheads sind nicht Teil dieses Schlüssels; ein späterer
Runfortschritt verändert keinen unveränderten Execution-Beleg.

Identische Aufträge liefern dieselbe Identität, denselben Zeitpunkt und dieselben
Zeugnisbytes. Vor Rückgabe werden Quelle und gespeicherte Belege erneut geprüft.
Eine bewusste Wiederholung derselben Grundlagen kann eine explizite neue UUID
request_id verwenden; sie ersetzt kein früheres Zeugnis. Andere Rubric/Revision
oder Methode ergeben ebenfalls einen neuen Auftrag. supersedes ist optional,
explizit und muss ein vorhandenes Zeugnis desselben Versuchs referenzieren.
Revisionsrückschritte oder andere Inhalte unter derselben Revision werden
abgewiesen. Originalpläne, Artefakte und Zeugnisse werden nie überschrieben.

Die zusätzliche Resultprojektion enthält alle validierten Repositoryzeugnisse
desselben Plans. Ausführungen/Fortschrittszähler und deren Status bleiben unverändert;
nur assessments und der Projektionszeitpunkt kommen hinzu. Das Originalresult
wird nicht geschrieben. Rubrics fremder Neubewertungen werden dem S2-Validator
explizit als assessment_rubrics übergeben. Historische Dateien werden nicht ausgeführt.

Bei unbekannter Veröffentlichung: keine Erfolgsmeldung, Live-Writer vergiften und
Belege erhalten. Liegt nach erneutem Öffnen ein vollständiges konsistentes Objekt
vor, kann es ohne Neuschreiben validiert und erneut synchronisiert werden; die
Quittung meldet idempotent=true. Eine temporäre Datei/unvollständige Publikation
sperrt dagegen mit assessment_publication_uncertain. Keine automatische Löschung,
Reparatur, neue Punktvergabe oder Modellwiederholung. Der alte Prozess darf einen
vergifteten Writer nicht erneut zum Bestätigen/Publizieren verwenden.

Historische s5-v1-Metadaten werden fachlich gegengeprüft, ohne alten Code zu laden.
Andere Assessorversionen oder inkonsistente Belege brauchen später einen expliziten
Import-/Migrationsvertrag; sie werden nicht still umgeschrieben. Eine mathematisch
oder integritätsseitig ungültige Altbewertung bleibt als Originaldatei erhalten,
ist aber keine automatisch akzeptierte supersedes-Grundlage.

## Öffentliche Python-API

| API | Bedeutung |
| --- | --- |
| calculate_score(rubric, categories) | Reine exakte Arithmetik mit Grenzen; keine Belegprüfung oder Vergabeautorität |
| BinaryCategoryRule(rubric_sha256, category_id, test_id, passed_points, failed_points) | Explizite rubricgebundene numerische Adapterregel; keine JSON-Vertragserweiterung |
| ReadOnlyTestAdapter / TestAdapterRegistry.register | Kontrollierte Registrierung vertrauenswürdiger Metadatenprüfer; kein Executor |
| default_registry() | Ausgelieferter performance_checks-v1-Metadatenprüfer |
| evaluate(execution, rubric, rules=(), registry=None) | Reine Auswertung bereits strukturell geprüfter Metadaten; erstellt/publiziert kein Zeugnis |
| verify_run(source, plan, result=None, expected_result_sha256=None, expected_head=None) | Vollständige S1–S4-Quellprüfung, unveränderlicher VerifiedRun-Snapshot |
| AssessmentRepository(store) | Getrennter privater S3-Primitivstore, kein zweites Journal |
| repository.read(id, expected_sha256=None) | Gebundene Speicherenveloppe lesen; allein keine vollständige Source-/Bewertungsprüfung |
| assess(source, repository, plan, attempt_id, rubric, expected_rubric_sha256=..., ...) | Quelle prüfen, Gates/Punkte berechnen, S2-Zeugnis validieren, atomar/idempotent publizieren |

assess akzeptiert außerdem rules, registry, rubric_asset_root, supersedes,
request_id, expected_head, result und expected_result_sha256. Es liefert assessment,
assessment_sha256, record_sha256, idempotent und eine zusätzliche S2-result-Projektion.
Beide Stores müssen offen und gelockt sein; Roots dürfen sich nicht überlappen.
OS-/Eingabefehler können an der Python-Grenze auftreten; die CLI meldet feste Codes.

## CLI und Beispiele

```sh
python3 assessment.py --help
python3 -m unittest discover -s tests -p test_assessment.py -v
```

Beispiel für einen **vorhandenen** gepinnten S4-Run und eine fachlich geprüfte Rubric:

```sh
python3 assessment.py \
  --source casting-root --archive assessments.local \
  --plan plans.local/run.json --competition plans.local/competition.json \
  --rubric plans.local/original-rubric.json --assets plans.local/assets \
  --target-rubric plans.local/approved-rubric.json \
  --expected-plan-sha256 "$S5_PLAN_SHA256" \
  --expected-rubric-sha256 "$S5_RUBRIC_SHA256" \
  --expected-head "$S5_SOURCE_HEAD_SHA256" --attempt-id "$S5_ATTEMPT_ID"
```

Ohne numerische Regeln bleiben Kategorien missing/incomplete. Nach fachlicher
Freigabe einer konkreten Zuordnung kann der Betreiber z. B.
`--rule response response_complete 10 0` hinzufügen, **nur wenn** genau diese
Kategorie/Suite/Testbindung und Maximalpunkte zur gepinnten Rubric passen. Diese
Zahlen sind ein explizites Beispiel, keine produktive Qualitätsnorm. Für neue
Rubrics keine frühere Regel ungeprüft übernehmen. --target-assets prüft getrennte
Rubric-Dateien; --result und --expected-result-sha256 prüfen einen vorhandenen
S2-Resultsnapshot gegen die reale Quelle. --supersedes und --request-id werden nur
explizit gesetzt. Keine API-URL, Cloud-Schlüssel oder freien Programme als Optionen.

Exitcodes: 0 passed, 1 failed/incomplete (gültiges diagnostisches Zeugnis),
2 Integritäts-/Vertrags-/Persistenzfehler, 130 ungewisse Veröffentlichung nach
Benutzerabbruch. stdout enthält dieselben validierten S2-Objekte in einer Quittung;
Fehler auf stderr enthalten feste Codes, keine rohen Provider-/OS-Pfade oder Secrets.
assessments.local ist durch die bestehende *.local-Regel von Git ausgeschlossen.
Zeugnisse/Rubrics und ihre Belege sind nicht automatisch zur Veröffentlichung
freigegeben. Weitere öffentliche HTML-/Webprojektionen bleiben S9/S10.

## Abgrenzung und offene Arbeit

Keine produktive fachliche Rubric wird hier freigegeben. Keine neue Disziplin,
Interpolation von Ankertexten, automatische Mehrtest-Punkteaggregation, Schulnote,
Jury (S7) oder Codex-Referenzerzeugung/Import (S8). Kein Verifier für beliebige
externe Testlogs. Belegte Performance-Metadaten sind der erste unterstützte Fall.

Für tatsächliche Coding-/Testausführung fehlen OS-Isolation, Ressourcenlimits,
Prozessbaumkontrolle und freigegebene ausführbare Adapter. Die Registrierung ist
nur eine sichere Schnittstellengrenze für vertrauenswürdige Metadatenprüfer und
behauptet keine Sandbox. S5 bleibt daher als Gesamtschritt offen; S1–S4, bestehende
CLIs und die drei unabhängig versionierbaren Projekte bleiben unverändert.


## Lokaler Testnachweis

78 eigenständige S5-Tests plus alle 310 bisherigen Tests bestanden (388/388,
keine Skips). Eigene arithmetische Golden-Vektoren prüfen Gewichte, Maximalpunkte,
Grenzrundung und fehlende Werte. S5-Tests durchlaufen echte S1-/S2-/S3-/S4-Prüfungen
an synthetischen S4-Quellarchiven. Die Fake-API dient ausschließlich deren Aufbau.
HTTP-/Socket-/Popen-Funktionen sind in allen S5-Testklassen gesperrt; ein zusätzlicher
Test verbietet explizit Modell-/Koordinationsarbeit während der Bewertung.

Geprüft sind Gatevorrang, fehlende/widersprüchliche Belege, Quell-/Zeugnistampering,
Methoden-/Rubric-/Planbindung, Idempotenz trotz späterem Runfortschritt,
unveränderte Originale und Neubewertungshistorie. Schreibabbrüche vor und nach
Publikation sowie fehlgeschlagene fsync-Bestätigung erzeugen keine Erfolgsmeldung.
Syntax, Diff, Vertragsbeispiele und bestehende Archiv-/Fixtureinhalte werden
separat geprüft. Keine echte Inferenz, kein Deployment, Commit oder Push.
S5 bleibt bis zur offenen Executor-/Isolations- und fachlichen Abnahme ein Teilstand;
dieser Stand wartet auf unabhängige MCP-Prüfung.
