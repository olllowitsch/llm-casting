# S3 – Workspaces, Artefaktarchiv und lokale Persistenz

`workspaces.py` ergänzt S1/S2 ohne deren Formate oder Implementierungen zu ändern.
Alle Funktionen arbeiten lokal mit der Standardbibliothek, Python 3.10+ und Linux.
Keine Modelle, Agenten, Tests aus Wettbewerbs-Assets, Shellkommandos oder fremden
Programme werden gestartet. Keine Datenbank, Netzwerkverbindung oder Installation.

**Ausführung bleibt gesperrt.** Getrennte Verzeichnisse, Dateimodi und Python-
Prüfungen sind keine Betriebssystem-Sandbox. `archived` ist ein Speicherzustand,
kein Nachweis einer Modellausführung, eines erfolgreichen Tests oder Prozessendes.
S3 erzeugt keine Execution-Belege, Messungen oder Zeugnisse. Die vorhandene
Performance-Engine und ihre Resume-Semantik bleiben unverändert.

## Struktur und Eigentümerschaft

Ein explizit gewählter, neuer Root innerhalb des Projekts:

```text
casting-root/                       # privat, von Git ausgeschlossen
  store.json                        # Formatkennung v1
  writer.lock                       # niemals ersetzen/löschen
  journals/<run-id>/
    bundle.json                     # S2-Plan, S1-Definitionen, initiales S2-Result
    00000001.json                   # nummerierte, unveränderliche Ereignisse
    00000002.json
    inputs/...                      # gemeinsamer geprüfter Wettbewerbssnapshot
    rubric-assets/...               # separate private Test-Suite-Assets
  workspaces/<run-id>/<participant-id>/<attempt-id>/
    inputs/...                      # eigene identische Kopie je Versuch
    outputs/...                     # einziger vorgesehener Teilnehmerschreibbereich
  artifacts/<run-id>/<participant-id>/<attempt-id>/
    files/...                       # unabhängige normale Kopien
    manifest.json
```

Die früher im Run-Vertrag gezeigte Run-zentrierte Struktur war eine logische
Skizze. Diese getrennten drei Wurzeln sind das konkrete S3-Speicherlayout.
Es gibt keine neue Interpretation des portablen Plan-/Resultschemas.

Namen werden ausschließlich aus geprüften S2-UUIDs und festen Segmenten gebildet.
Modellnamen, Prompts oder Fehlertexte werden nicht als Pfade verwendet. Freie
Outputpfade sind nur innerhalb eines expliziten relativen Inventars zulässig.
S1-Pfadregeln bleiben maßgeblich; S3 begrenzt Nutzpfade zusätzlich auf 16 Komponenten,
1024 UTF-8-Bytes und 128 Bytes je Komponente. Die vollständigen internen Pfade
sind auf 32 Komponenten und 4096 Bytes begrenzt. S1/S2 verbieten wiederholte
Pfadkomponenten; kollidierende UUID-Pfadsegmente werden deshalb vor der Workspace-
Absicht abgewiesen. Mit `new_attempt_identity` erzeugte unabhängige UUIDs verwenden.

Neue Verzeichnisse werden mit 0700 erzeugt; bestehende Verzeichnisse werden nicht
umkonfiguriert. Ein Store wird nur mit eigener UID und ohne Gruppen-/Fremdrechte
angenommen. Es gibt keine Anforderungen an fremdverwaltete Elternpfade und keine
chmod/chown/ACL-Aktionen dort. Persistierte Dateien werden mit 0600 angelegt und
vor Veröffentlichung über ihren eigenen Dateideskriptor auf 0400 gesetzt.
Inputs und Archivkopien haben keine Ausführungsbits oder Hardlinks. Nur die
Engine schreibt Journal und Archiv; spätere Teilnehmer dürfen weder diese
Verzeichnisse noch Inputs beschreiben. Diese Trennung muss der spätere Executor
über eine echte Sandbox mit read-only Mounts/Identitäten durchsetzen. Unter der
heutigen gleichen UID kann der Eigentümer Modi wieder ändern; S3 ist kein Schutz
gegen einen bereits gestarteten Angreifer unter dieser Identität.

Das Root muss einen existierenden Elternordner haben und wird selbst frisch
angelegt. Bereits vorhandene fremde/leere Verzeichnisse werden nicht adoptiert.
`results/`, `reports/`, `.git/`, Quell-/Test-/Dokumentationsverzeichnisse sowie Ziele
außerhalb des Projekts sind ausgeschlossen. Kein rekursives Löschen, keine
Bereinigung unbekannter Dateien, kein Überschreiben existierender Dateien.
Alternative private Roots z. B. `experiment.local` ebenfalls lokal halten.

## Workspace-Lifecycle

| Zustand | Bedeutung und Fortsetzung |
| --- | --- |
| planned | Dauerhafte Vorbereitungsabsicht; Verzeichnis kann fehlen oder unvollständig sein. Nach Prozessverlust effective_status=uncertain; keine Wiederholung. |
| prepared | Gemeinsame Inputs vollständig geprüft/kopiert, Outputverzeichnis angelegt. Nach erneutem Journal-/Inputvergleich sicher lesbar und sammelbar. |
| active | Reserviert für einen nachweisbar isolierten Executor. S3 verweigert Aktivierung und solche Journalzustände mit execution_disabled. |
| collecting | Vollständiges Outputinventar, neue Artefakt-IDs und erwarteter Manifesthash dauerhaft gebunden; Dateikopie ist noch nicht bestätigt. |
| archived | Kopien und Manifest geprüft und dauerhaft als übernommen protokolliert. Kein Ausführungserfolg. |
| failed | Explizit festgestellter Speicherfehler vor Sammlung. Keine automatische Umdeutung und kein Wiederöffnen. |
| uncertain | Unsicherer Speichervorgang. Wird insbesondere aus planned/collecting nach Neustart rekonstruiert; keine automatische Fortsetzung. |

Normale Übergänge: `planned → prepared → collecting → archived`.
Vor Sammlung auch `planned/prepared → failed/uncertain`. Terminale Zustände werden
nicht verändert. S3 hat keinen Prozessstart; deshalb wird active ausdrücklich
nicht durch einen manuell gesetzten Status oder ein fremdes PID-Feld aktiviert.

Runstatus und Executionstatus aus S2 bleiben getrennt. Das Bundle enthält ein
initiales geplantes Result mit leeren executions/assessments. Workspace-Zustände
verändern dieses Result nicht. Alle Resultprojektionen mit echter Ausführung
bleiben Aufgabe von S4. Archivierung allein setzt niemals `succeeded/completed`.

## Journalformat und Integrität

Alle Journaldateien verwenden S1-Canonical-JSON, UTF-8 ohne letzten Zeilenumbruch.
Ein Ereignis ist ein Wrapper mit genau `event` und `sha256`. Der Hash bindet den
vollständigen event-Körper, ohne Selbsthash. Körperfelder:

| Feld | Vertrag |
| --- | --- |
| kind / schema_version | workspace_event / Integer 1 |
| sequence | Lückenlose Folge ab 1, Dateiname achtstellig |
| previous_sha256 | null bei Genesis, sonst SHA256 des vorherigen event-Körpers |
| run_id / plan_sha256 | Identität und unveränderlicher S2-Pin |
| bundle_sha256 | SHA256 des vollständigen unveränderlichen Bundles |
| at | UTC-Z, monoton nicht abnehmend |
| state | Vollständiger Speicherzustand aus phase und attempts |

`phase` ist zuerst initializing und nach bestätigter Übernahme beider Input-
Inventare ready. initializing nach Neustart ist ungewiss. attempts enthält exakt:

- identity: S2-Felder run_id, participant_id, repetition, attempt_id, plan_sha256.
- status: Workspace-Zustand, nicht Executionstatus.
- manifest_sha256: null vor Sammlung, danach gepinnter Manifesthash.
- artifacts: leer vor Sammlung, danach das vollständige S2-Artefaktinventar.

Die Zustandshistorie ist append-only: Identitäten, bisherige Reihenfolge,
archivierte Belege und eingefrorene Sammlungsinventare dürfen nicht umgeschrieben
werden. Zustände und Übergänge, Fortschrittsbeziehungen, Artefakt-IDs/-Pfade,
Anzahl/Bytes und S2-Planbindung werden bei jeder Rekonstruktion validiert.
Run-Bundle: genau kind=run_bundle, schema_version=1, plan, competition, rubric,
initial_result. Bereits geladene Definitionen bleiben S1/S2-geprüft; das Bundle
muss den vollständigen, vom Aufrufer übergebenen PinnedPlan-Snapshots entsprechen.

Der Writer hält einen nichtblockierenden exklusiven flock auf einem stabilen,
normalen Single-Link-Lockfile für den gesamten Store. Das ist bewusst strenger
als ein Lock pro Run. Kooperierende Prozesse können nicht gleichzeitig schreiben.
Austausch von Root-/Lockpfad wird erkannt. Locks sind keine Berechtigungsschranke
gegen einen Prozess derselben UID, der das Protokoll absichtlich ignoriert.

Publikation: eigene O_EXCL/O_NOFOLLOW-Datei → schreiben/flush → 0400 → Datei-fsync
→ Inhalt/Inode/Parent prüfen → Linux renameat2(RENAME_NOREPLACE) → Verzeichnis-fsync
→ veröffentlichte Datei/Identität erneut prüfen. Verzeichnisse werden ebenfalls
über Deskriptoren erzeugt und synchronisiert. S1/S2-Lese-/Hash-/Publish-Hilfen
werden wiederverwendet; keine zweite JSON-Kanonisierung oder Vertragsimplementierung.
Kein Hardlink-Zwischenzustand, kein os.replace, kein stilles Überschreiben.

Ein Fehler vergiftet den betroffenen Live-Writer nach möglicher Veröffentlichung;
weitere Schreibversuche werden verweigert. Temporärdateien bleiben als Belege
liegen. Ein vollständiges Ereignis mit nachfolgendem fsync-Fehler kann bereits
sichtbar sein: der Aufrufer erhält keine Erfolgsaussage. Nach Neustart entscheidet
nur die validierte dauerhafte Kette; unvollständige Ereignisse oder Fremddateien
sperren die Rekonstruktion. Absichten ohne Abschluss bleiben uncertain.

**Vertrauensanker:** Der Aufrufer hält den PinnedPlan und vorzugsweise den letzten
bestätigten head_sha256 getrennt vom Store. inspect/validate melden ausdrücklich
head_pin_checked=false, wenn kein externer Headpin geprüft wurde. `expected_head` erkennt auch Entfernung
eines sonst selbstkonsistenten Journalendes. Ohne diesen externen Pin kann eine
vollständig entfernte Endsequenz oder gemeinsam umgeschriebene Hashkette nicht
kryptografisch als Rollback bewiesen werden. Ein Hash im selben beschreibbaren
Archiv ist keine Signatur, Herkunftsbestätigung oder Manipulationsautorität.
Dateisystem, Eigentümer und separat gesicherte Pins gehören zur Vertrauensbasis.
Keine S3-Garantie gegen Stromverlust trotz eines unzuverlässigen fsync/Dateisystems.

## Input- und Artefaktübernahme

S1-Prüfung einschließlich Quelleninventar vor und nach der Kopie. Jede Datei wird
beim Kopieren erneut bounded über O_NOFOLLOW/O_NONBLOCK geöffnet, Größe/Hash und
Identität geprüft. Das Zielinventar wird anschließend vollständig gegengeprüft.
Wettbewerbsassets bleiben allen Teilnehmern identisch; Rubric-Testdateien werden
separat im privaten Run-Bundle-Bereich gespeichert, nicht in Teilnehmerinputs.
Kein Asset wird ausgeführt. Inputs erhalten eigene Kopien je Versuch.

Zur Sammlung liefert der Betreiber eine vollständige Liste mit genau path und
media_type. Keine automatische Discovery-Freigabe. Erlaubte Typdeklarationen:
text/plain, text/markdown, text/x-python, text/html, application/json und
application/octet-stream. Typangaben sind keine Inhalts- oder Sicherheitsgarantie.
Unbekannte Typen, Dateien, leere zusätzliche Verzeichnisse und Pfadkonflikte werden
abgewiesen. Eine leere Liste ist nur bei tatsächlich leerem Outputverzeichnis
zulässig und erzeugt trotzdem ein bestätigtes Manifest. Fehlende Dateien werden
niemals als leeres erfolgreiches Archiv behandelt.

Limits: höchstens 1000 Versuche und 1000 Journalereignisse pro Run, 10000 gescannte
Einträge je Inventar, 16 MiB je Datei. Runweite Artefaktzahl/Bytes sind das Minimum
aus Planpolicy und S3-Obergrenzen von 1000 Dateien/100 MiB. Die S1-JSON-Grenzen
(1 MiB, Tiefe/Knoten etc.) gelten zusätzlich; große Vollzustandsjournale werden
abgewiesen statt abgeschnitten. S1-Assetlimits gelten unverändert. Dies sind
Speicheroperation-Limits, keine harten Diskquotas für einen späteren Agenten.

Manifestfelder: kind=artifact_manifest, schema_version=1, identity, artifacts.
Jeder Artefakteintrag verwendet unverändert die sechs S2-Felder artifact_id,
path, sha256, size_bytes, media_type, classification. path bezeichnet die wirkliche
relative Datei `artifacts/RUN/PARTICIPANT/ATTEMPT/files/RELATIVE` im Casting-Root.
Alle Artefakte werden als private markiert. Neue UUIDs entstehen vor Kopierbeginn
und werden mit dem erwarteten Manifesthash in collecting gebunden. Archivdateien
sind unabhängige Single-Link-Kopien. Validierung prüft Metadaten **und** vollständige
Archivbytes; fehlende, zusätzliche oder veränderte Dateien sind Fehler.

HTML und Programmdateien bleiben opaque Daten. Keine Anzeige, kein Import,
keine Ausführung und keine automatische Veröffentlichung. Ausgabedateien können
Secrets enthalten; weder MIME-Typ noch Escaping ersetzt eine Freigabeprüfung.

## Python-Schnittstellen

Alle folgenden Operationen verwenden `WorkspaceStore(root)` als Context Manager.
`create=False` öffnet ausschließlich einen bestehenden Store, ohne ihn anzulegen.
Auch lesende Inspektion hält den exklusiven Lock für einen konsistenten Zeitpunkt.
Rückgaben sind unabhängige Kopien; DefinitionError besitzt feste code/location.
OS-Zugriffsfehler können an der Python-Grenze als OSError auftreten; die CLI
übersetzt sie in einen festen Code ohne Pfade/Rohmeldungen.

| API | Funktion |
| --- | --- |
| register_run(plan, asset_root=..., rubric_asset_root=...) | Plan/Definitionen und beide Inputinventare erneut prüfen, Bundle und Snapshots dauerhaft anlegen; bestehender kompatibler Run wird nur geprüft |
| prepare(plan, identity) | Neue Vorbereitungsabsicht, eigene Inputs/Outputs, bestätigtes prepared; vorbereitete/archivierte identische ID idempotent prüfen |
| inspect(plan, expected_head=None) | Rekonstruktion mit effective_status, resumable, executable=false; keine Statusdatei schreiben |
| validate_journal(plan, expected_head=None) | Vollständige Kette/Snapshots/Workspace- und Archivbelege prüfen |
| fail_workspace(plan, identity) | Bekannten Speicherfehler aus prepared explizit dokumentieren |
| activate(plan, identity) | Immer execution_disabled; keine Prozesse starten |
| prepare_artifact_archive(plan, identity, outputs) | Outputinventar prüfen und Sammlungsabsicht pinnen; noch keine Archivkopie |
| validate_inventory(plan, identity, manifest) | Outputbytes gegen gebundenes Manifest prüfen; begrenzte Kopierbytes zurückgeben |
| archive_artifacts(plan, identity) | Nur eine im selben Live-Writer vorbereitete Absicht übernehmen und bestätigen |
| collect(plan, identity, outputs) | Vorbereitung und Archivierung in einem Aufruf; bestätigtes identisches Archiv idempotent prüfen |
| validate_archive(plan, identity, expected_manifest=HASH) | Manifestpin und tatsächliches Datei-/Verzeichnisinventar samt Bytes prüfen |
| validate_manifest(value, plan, identity, expected_sha256=None) | Reine Metadaten-/S2-/Pfad-/Identitätsprüfung |
| isolation_check(plan=None) | Passive Bibliotheksfähigkeiten und verpflichtende, noch unerfüllte Isolationsanforderungen; niemals Ausführung freigeben |

`validate_journal(..., verify_files=False)` ist ausschließlich für die interne
Append-Prüfung bestimmt. Die normale öffentliche Prüfung liest alle relevanten
Bytes. Keine Erfolgsaussage aus der eingeschränkten Variante ableiten.

## CLI

Alle Befehle geben JSON aus, Exitcode 0 bei erfolgreicher Speicher-/Prüfoperation,
2 bei Fehler und 130 bei Benutzerabbruch (operation_interrupted, uncertain=true). Hilfe ist die normale argparse-Hilfe; Syntaxfehler sind sichere
JSON-Fehler. Konsolenquittungen enthalten keine Prompts, Modellantworten, Pfade
oder Rohfehler. `executable` bleibt false. `resumable` heißt nur Speicheroperationen
sind fortsetzbar, nicht Agenten-/Serverstillstand oder Ausführbarkeit.

Beispiel ausschließlich mit mitgelieferten synthetischen Definitionen:

```sh
# S2-Identität lokal erzeugen; kein Modellstart
python3 - <<'PY'
from pathlib import Path
import definitions as d
import planning as p
s = Path('tests/fixtures/definitions/valid')
f = Path('tests/fixtures/planning')
plan = p.validate_run_plan(d.load_json(f/'run-plan.json'),
    d.load_json(s/'competition.json'), d.load_json(s/'rubric.json'), asset_root=s/'assets')
identity = p.new_attempt_identity(plan, plan.as_dict()['participants'][0]['participant_id'], 1)
p.write_json_exclusive('identity.local.json', identity)
print(plan.sha256)
PY

# Angezeigten Planhash als separat gesicherten Pin einsetzen.
python3 workspaces.py prepare --root casting-root \
  --plan tests/fixtures/planning/run-plan.json \
  --competition tests/fixtures/definitions/valid/competition.json \
  --rubric tests/fixtures/definitions/valid/rubric.json \
  --assets tests/fixtures/definitions/valid/assets \
  --expected-plan-sha256 6ec50382d3eba5c0d582d728a4fe48a5bc04a8a0c330435bce5fe700c16e7dea \
  --identity identity.local.json

python3 workspaces.py isolation-check
```

Für `inspect` und `validate` dieselben root/plan/competition/rubric/assets/Hash-
Argumente verwenden, aber keine identity. Optional `--expected-head HASH` mit dem
zuletzt separat gesicherten Journalpin. Beide prüfen vollständig und schreiben
keine Belege; sie legen keinen fehlenden Store an. Plan-CLI-Prüfung liest erneut
die angegebenen S1-Quellen; die private Archivbindung bleibt unabhängig erhalten.

`collect` erwartet dieselben Argumente plus `--identity identity.local.json` und
`--outputs outputs.local.json`. Die Outputdatei enthält beispielsweise
`[{"path":"answer.txt","media_type":"text/plain"}]`. answer.txt muss bereits als
synthetische normale Datei im eigenen outputs-Verzeichnis vorliegen. S3 erstellt
keine Modellantwort. `--expected-plan-sha256` ist für alle Storebefehle Pflicht;
Planänderungen unter derselben Run-ID werden abgewiesen. Bei prepare mit vorhandenem
Store `--expected-head` zur Rollbackbindung mitgeben. Einen falschen Headpin kann
ein neuer Run nicht nachträglich erfüllen; zuerst bestehenden Stand prüfen.

## Wiederholung, Abbruch und Wiederherstellung

- Neue Austragung: neue Run-ID in einem neu validierten Plan, neue Versuch-IDs.
  Bestehende Definitionen/Artefakte bleiben unverändert.
- Geplante Wiederholung: eigener S2-Messplatz repetition und neue attempt_id.
  Mehrere Teilnehmer und Wiederholungen besitzen getrennte Kopien.
- Bereits prepared/archived: identischen Inhalt erneut prüfen ist idempotent.
  Kein zweites Inventar, keine neuen Artefakt-IDs und keine doppelte Zählung.
- Eine explizite neue Attempt-ID ist nach einem bekannten failed-Speicherzustand
  vor Sammlung zulässig. Alle alten Workspaces/Journale bleiben erhalten. Da es
  noch keinen Execution-Beleg gibt, ist das keine Wiederholung einer terminalen
  S2-Ausführung und erzeugt keine zusätzliche Messplatzwertung. Sonst erhält ein
  Messplatz nur eine Workspace-ID. Eine Ersatz-Attempt-ID nach
  uncertain setzt später kompatible Ausführungs-/Stillstandsbelege und S2-
  supersedes-Verknüpfung voraus. S3 besitzt diese Autorität nicht und verweigert
  sie, statt eine unsichere Wiederholung zu implementieren. Kein Retry-Scheduler.
- collecting lebt nur im Writer, der die Absicht erfolgreich angelegt hat.
  Nach Neustart oder unbekanntem Ausgang wird sie nicht automatisch wiederholt;
  selbst ein vollständiges Manifest allein beendet den Journalvorgang nicht.
  Ein vollständiger, dauerhafter archived-Eintrag kann nach erneuter Byteprüfung
  sicher gelesen werden. Outputs bleiben erhalten und werden ebenfalls geprüft.

Fehlergruppen: json_*/asset_*/file_* und S2-Vertragscodes; writer_busy,
lock_changed, store_root_changed, store_permissions_unsafe, filesystem_boundary,
inventory_mismatch/inventory_changed, archive_incomplete, archive_uncommitted_files, unknown_attempt_path,
unknown_run_path, journal_missing/journal_sequence_invalid/journal_binding_mismatch,
journal_head_mismatch, journal_uncommitted_files, workspace_transition_invalid,
workspace_not_prepared, collection_conflict, execution_disabled, operation_uncertain,
store_write_uncertain, storage_commit_uncertain und storage_access_failed (CLI).
Keine Rohparser-, Provider-, OS- oder Quellinhaltmeldungen weiterreichen.

Bei Ungewissheit: keine weiteren Schreibaufrufe; externen Plan-/Headpin sichern,
Originalstore inklusive temporärer Dateien erhalten, schreibende Prozesse durch
Betreiber ausschließen, vollständige read-only Prüfung versuchen. Bei beschädigten
Belegen sicher stoppen. Keine automatische Reparatur, kein Löschen, Rekopieren,
Reset oder Ableiten eines Erfolgs aus vorhandenen Verzeichnissen. S3 hat keinen
administrativen Recovery-Schreibpfad. Neue getrennte Austragung ist möglich,
beweist aber keinen Stillstand möglicherweise fremder Prozesse.

## Isolationsprofil und Voraussetzungen für S4/S6

Das implementierte Profil `s3_storage_only` beschreibt die Verwaltung; es ändert
nicht das S2-Planlabel inference_only. Der passive Check prüft nur Verfügbarkeit
von dir_fd/O_NOFOLLOW/flock/renameat2, keine tatsächliche Sandboxfunktion.
Auch bei verfügbaren Bibliotheksfunktionen bleibt executable=false.

Vor Agenten-/Testausführung muss ein Linux-Sandboxadapter separat implementiert
und mit harmlosen synthetischen Prozessen nachgewiesen werden: erlaubte Inputs
read-only, nur eigene Outputs beschreibbar, kein Host-/Fremdworkspacezugriff,
standardmäßig kein Netzwerk, klare Prozessrechte, explizite Umgebungsvariablen
statt geerbter Secrets, harte CPU/RAM/Disk/PID-Limits, überprüfte gesamte
Prozessbaumterminierung und blockierende Behandlung unbekannter Kinder.
S3 kann keinen Prozessstillstand bestätigen und erbt deshalb keine solche Zusage.
Für Ollama benötigt S4 zusätzlich die bestätigte Provider-/Serverruhe nach
Timeout/Verbindungsverlust. S6 benötigt eine tatsächlich geprüfte Coding-Sandbox.
Keine Docker-/Systemd-/Namespace-Installation wird hier vorgenommen.

Lokale Dateisysteme mit verlässlichem flock, dir_fd, O_NOFOLLOW, renameat2 mit
RENAME_NOREPLACE und fsync sind Voraussetzung. Keine Zusage für NFS, verteilte
Writer, mountfähige Angreifer oder Manipulationen durch dieselbe privilegierte UID.
Deskriptor-/Inode-/Hashprüfungen erkennen beobachtete Wechsel; ohne Kernelisolation
lassen sich beliebige Änderungen nach einem erfolgreich geprüften Zeitpunkt
nicht verhindern. Signierte/extern gesicherte Belege und Exportprofile bleiben
separate spätere Aufgaben.


## Lokaler Abnahmestand

78 eigenständige synthetische S3-Tests sowie alle 165 bisherigen Tests bestehen
(243/243, keine Skips). Die separate S3-Suite prüft insbesondere Reader-/Writer-
Rennen, manipulierte Hashketten/Artefakte, mehrere Wettbewerbe/Modelle/Versuche,
getrennte Kopien, konkurrierende Prozesse, Publikation vor/nach fsync,
verlorene Rename-Bestätigung, unvollständige Archive und gesperrte Ausführung.
CLI-Smoke: prepare → inspect → validate → collect → inspect an synthetischen
Dateien sowie isolation-check. Netz-/Prozessaufrufe der S3-API/CLI werden in Tests
explizit gesperrt; separate Testprozesse dienen ausschließlich dem Writer-Locktest.
Alte Quellen, Fixtures, Golden-Hashes und bestehende Archive werden bytegenau
gegen den Ausgangsstand geprüft. Kein Commit/Push; unabhängige MCP-Prüfung und
Commit-Freigabe stehen aus. Nächster Schritt S4: neuer Ollama-Adapter mit strikter
Identitäts-/Timeout-/Stillstands- und Resultbindung, zunächst nur mit Fake-API.
