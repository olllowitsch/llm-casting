# S6-C – reproduzierbare OS-Isolationsprüfung vorbereiten

Stand: Vorbereitung auf main/e7c0448, TST, systemd 255/Cgroup v2. **Keine reale
OS-Abnahme, kein installierter Executor.** S5/S6 bleiben insgesamt offen.
Verbindliche Grundlage: [S6-B](S6_SANDBOX_FEASIBILITY.md),
[S6-A](S6_OPENCODE_ADAPTER.md), [S3](S3_WORKSPACES.md),
[Architektur](ARCHITECTURE.md), [Roadmap](../ROADMAP.md).

## 1. Umfang und klare Nachweisgrenze

Implementiert ist das eigenständige Standardbibliotheks-Prüfpaket unter
[tests/isolation](../tests/isolation/README.md), mit Profilvalidator, konservativer
Statusberechnung, begrenzten synthetischen Dateiproben, Live-Kontext-Gate,
Offline-Verifier, fester Kindprozessfixture und nicht installierter Unitvorlage.
Keine Engine-, normativen S1/S2-, Altfixture- oder Archivänderungen.

V1 ist ausdrücklich ein **Teilprüf-/Vorbereitungsprofil**. Ein erfolgreicher
Datei-Open-Test oder gelesener Cgroup-Konfigurationswert wird nicht zur globalen
Isolationsbehauptung. Unabhängige Host-/Prozessendbelege, effektive Ressourcen-
und Netzwerkprüfungen sind noch nicht implementiert. Sie bleiben obligatorisch
not_verified; V1 erzeugt daher niemals isolation_verified=true oder Exit 0.
Diese Sperre wird durch spätere Operatorstarts nicht automatisch aufgehoben.

Ein späteres vollständig positives Verfahren benötigt einen separat geprüften
Hostcollector und eine neue akzeptierte Profilversion. Das wäre ein weiterer
Implementierungs-/Freigabeschritt, keine Änderung einiger Berichtswerte.

## 2. Dateien und Vertrag

| Bestandteil | Aufgabe |
| --- | --- |
| tests/isolation/contract.py | Begrenzter JSON-Vertrag, Pins, Typ-/Versionsprüfung und deterministische Statusberechnung |
| tests/isolation/probe.py | Eigene Kernel-/Cgroupmetadaten, ausschließlich synthetische Dateiproben; optional genau ein festes Kind |
| tests/isolation/verify.py | Bericht und Profil lesen, Konsistenz neu berechnen; keine Dienst-, Netzwerk- oder Prozesssteuerung |
| fixtures/profile.example.json | Beispiel, kein startbereites Profil; Host-Mount-Namespace ist bewusst null |
| fixtures/child.py | Höchstens acht Sekunden lebendes Kind, PID/PPID/Cgroup-Ack, keine Shell/Sockets/Lastschleife |
| unit-templates/llm-casting-isolation-probe@.service | Temporärer System-Service je Test-UUID, kein produktiver Executor |
| tests/test_isolation.py | Lokale reine Unit-/Dateitests mit verbotenen Prozess-/Netzwerkstarts |

Die erwartete Unit ist exakt llm-casting-isolation-probe@TEST-UUID.service, ihre
Cgroup /system.slice/UNIT. Slice=system.slice verhindert den sonst möglichen
eigenen Template-Slice-Pfad. Andere Namen/Pfade sind keine freigebbaren Optionen.
UID/GID sind positive numerische Werte; zusätzliche effektive Gruppen sind
unzulässig. Eine leere Supplementärgruppenliste lässt die primäre GID bestehen.

Profil v1 enthält Testidentität, Erstellungszeit, erwartete Identität/Unit/Cgroup,
Host-Mount-Namespace, feste explizite FS-/Netzwerkerwartungen und Ressourcenlimits.
Grenzen: max. 256 MiB MemoryMax, 1 CPU Quota, 32 Tasks, 15 Sekunden Laufzeit;
alle Werte positiv und typisiert. Das Beispiel setzt 128 MiB, 25%, 16 Tasks, 5s.
Ein Profil kann weder Pflichtprüfungen entfernen noch Erwartungen abschwächen.

Berichte enthalten Test-/Profil-/Berichtsidentität, Beobachtungszeit, stage,
Rohbeobachtungen, berechnete Pflichtchecks, overall_status, isolation_verified,
assurance und missing_evidence. stage=pre_stop ist kein Endbeleg. Ein verlorener
Abschluss ist unknown/not_verified und niemals ein stiller Erfolg.

Strikte UTF-8-JSON-Regeln und Canonical-SHA256 sind in der Paket-README erklärt.
Jede ungültige/unbekannte Version, jeder fehlende/zusätzliche Schlüssel und jede
inkonsistente Erfolgsangabe wird abgewiesen. Profile/Reports werden nur über
normale einzelne Dateien ohne Symlink/Hardlink/Traversal gelesen. Ausgaben
enthalten keine geöffneten Canaryinhalte, Secrets oder Modelltexte.

## 3. Welche Prüfungen was belegen

| Prüfung | Umsetzung in V1 | Grenze |
| --- | --- | --- |
| EUID/EGID/Gruppen, CapEff, NoNewPrivileges | Aus eigenen /proc-Metadaten/OS-APIs; Erwartungsvergleich | Selbstbeobachtung des geschützten Testprogramms, keine signierte Attestation |
| Mount-Namespace | Tatsächlicher Inode gegen gepinnten Host-Inode | Ungleiche Inodes beweisen nicht automatisch die richtige Sicht |
| Unit/Cgroup | Eigene Cgroup und passend abgeleiteter Unitname, Invocation-ID | Keine unabhängige Manager-/Boot-/Invocation-Zuordnung |
| Eigener Output | Einzigartige Scratchdatei exklusiv anlegen, schreiben/lesen, nur eigenen Inode entfernen | Kein Zugriff außerhalb des freigegebenen Roots |
| Referenz lesen | Exakter bekannter synthetischer Inhalt | Fehlender/fremder Inhalt ist kein erfolgreicher Test |
| Referenz-/Außenbereich schreiben | O_WRONLY ohne O_TRUNC und ohne Datenänderung | Ablehnung kann DAC oder read-only Mount sein; Mountwirkung separat unbekannt |
| Anderen synthetischen Workspace lesen | Nur fester Canaryname | Unzugänglicher Ordner/fehlender Canary ist not_verified, kein Existenzbeleg |
| Hardlink | Nur bekannter normaler Referenzcanary; unerwarteten eigenen Link entfernen und Fehler melden | Kein Angriff auf echte Dateien; keine Behauptung über alle fremden Inodes |
| Symlink/Traversal | Pfadreader weist Links/Traversal zurück; automatisiert getestet | Das ist Werkzeugschutz, noch kein praktischer OS-Ausbruchstest |
| Ressourcen | Eigene memory.max/cpu.max/pids.max lesen | Abweichung failed, passende Werte nur not_verified: keine gemessene Wirkung |
| Kind | Optional fester Kindprozess; PID/PPID/Ack und Cgroup, früher Verlust failed | Kein Parentende als Baumende; kein aktiver Kill aus Python |
| Baumabbruch/Ende/finale Bestätigung | Unabhängiger späterer Hostbeleg erforderlich | Immer not_verified in V1 |
| Netzwerk | Nur versionierte Erwartungen und späterer Testplan | Keine Socket-/DNS-/Ollama-/externen Verbindungsversuche implementiert |

Eine fehlende oder unsicher prüfbare Eigenschaft bleibt fehlend. Die Rohwerte
können durch JSON-Selbstbehauptung nicht zu End-/Netzwerkbelegen erweitert werden.
verify.py rechnet alle Einzel-/Gesamtstatus und missing_evidence erneut aus.
Ein widersprüchlich neu gehashter Report mit isolation_verified=true wird ebenso
abgewiesen wie einer mit entfernten Pflichtchecks.

**Vertrauensgrenze:** SHA256 beweist Inhaltsbindung, keinen Urheber. Wer Bericht
und erwartete Prüfsumme gemeinsam kontrolliert, kann eine konsistente
Selbstbeobachtung nachbauen. V1 benennt assurance=untrusted_probe_observations;
auch ein solcher neu konstruierter Bericht kann niemals eine OS-Abnahme erzeugen.
Das ist kein Schutz gegen Administratoren, die Programm und Host manipulieren.

## 4. Live-Gate und ungefährliche Fixtures

Vor jeder aktiven Dateiprüfung fordert probe.py die passende aktuelle unprivilegierte
Identität, echte eigene Cgroup, Invocation-ID, leere effektive Capabilities,
NoNewPrivileges=1, unterschiedlichen Mount-Namespace und passende begrenzte
Cgroupwerte. Vor einem Kindstart liest es den Kontext nochmals neu. Übergebene
JSON-Beobachtungen oder force/enable-Optionen können dies nicht ersetzen.
Der Testroot und sein profilgebundener Marker müssen root gehören und vor
Gruppen-/Fremdschreiben geschützt sein. Die Engine-UID wird nicht als root ersetzt.

Nur feste Leafnamen unter diesem explizit bereitgestellten synthetischen Root
werden angesprochen. Keine Profile mit frei wählbaren Kommandos, Prüfzielen,
URLs oder Hostdateien. Scratchnamen sind frisch und exklusiv; kein bestehender
Output wird überschrieben. Fehlgeschlagene Gates schreiben keine Testdateien
und starten kein Kind; soweit möglich entsteht ein gate_rejected-Diagnosebericht.

Das Kind wird ausschließlich über den fest eingebauten child.py-Pfad gestartet,
mit minimaler Umgebung, ohne Shell, geschlossenem stdin und begrenztem Ack.
Es erzeugt keine weiteren Prozesse und beendet sich selbst nach acht Sekunden.
Die Vorlage setzt zusätzlich RuntimeMaxSec=5s. Der Parent publiziert davor einen
pre_stop-Bericht. Fehlende oder vorzeitig verlorene Ack wird als Fehler behandelt.
Ein Wait/Timeout wird niemals als nachgewiesener Cgroup-Abbruch ausgegeben.

Kein Fork-Bomben-, Last-, unkontrollierter Allokations- oder echter Secret-Test.
Keine Änderung an S3-Rechten, Engine-Home, bestehenden Archiven oder dicomat.

## 5. Temporäre Struktur und Unitvorlage

Erst nach Betreiberfreigabe neu bereitzustellen, Namen sind Zielplanung:

```text
/usr/local/lib/llm-casting-isolation/  geschütztes geprüftes Paket
  contract.py, probe.py, verify.py, fixtures/child.py
/var/lib/llm-casting-isolation/TEST-UUID/  neuer synthetischer Testroot
  profile.json, marker.json
  reference/canary.txt, outside/canary.txt, other/canary.txt
  output/                                  nur dedizierte Testidentität
  rootfs/                                  geprüftes minimales Python-Rootfs
/etc/systemd/system/llm-casting-isolation-probe@.service
/etc/systemd/system/llm-casting-isolation-probe@TEST-UUID.service.d/10-profile.conf
```

Eigene neue Identität llm-casting-isolation-test, ohne Login/Home und ohne fremde
Gruppen. Keine vorhandene ähnlich benannte Identität ungeprüft übernehmen.
Das Paket/rootfs/Profil/Marker und Input-/Negativcanaries sind root-eigen und für
den Worker nicht beschreibbar. Nur der neue Outputbereich gehört dem Testuser.
Keine pauschalen chmod/chown/ACL-Aktionen oder Anforderungen an Besitzrechte
fremdverwalteter Elternpfade. Die neuen kontrollierten Ziele müssen geschützt
bereitgestellt werden; keine bestehenden Verzeichnisse umkonfigurieren.

Das Rootfs muss separat aus vertrauenswürdiger Quelle bereitgestellt werden:
passendes /usr/bin/python3 samt Loader/Standardbibliothek, synthetische
Benutzer-/Gruppendateien, leere Mountziele für /opt/isolation und /fixtures sowie
API-Dateisysteme. Keine Host-/etc-/home-/Engine-/Git-/S3-Kopie als Abkürzung.
Ein konkretes geprüftes Rootfs ist noch nicht vorhanden: **Stopppunkt**.

Die Vorlage bindet nur geprüftes Testpaket, Profil/Marker/Canaries und eigenen
Output ein. /sys/fs/cgroup wird allein zur lesenden Probe-Metadatenprüfung
eingebunden; dies ist ausdrücklich kein produktives OpenCode-Sandboxprofil.
PrivateTmp, PrivateNetwork, ProtectSystem=strict, ProtectHome, NoNewPrivileges,
leere Capabilities, AF_UNIX, PrivateDevices, Namespace-/Syscallbeschränkungen und
Ressourcen-/Stopgrenzen sind enthalten. Keine PrivatePIDs-Direktive für systemd 255.

Die Unit hat keinen Install-Abschnitt: kein enable, kein Autostart, Restart=no.
Der ungefüllte Hashplatzhalter scheitert am Profilvalidator. Per-Instance-Drop-in
statt globaler Profiländerung, damit andere Testinstanzen unbeeinflusst bleiben.
Syntaxprüfung mit installiertem systemd 255 war erfolgreich; keine tatsächliche
Wirksamkeit der Kombination oder Rootfs-Kompatibilität wurde getestet.

## 6. Spätere Operatoraktionen – NICHT in diesem Auftrag ausgeführt

Die folgenden Befehle sind **nur** für einen später ausdrücklich freigegebenen
TST-Test gedacht. Ausführung durch autorisierten Betreiber in einer administrativen
Sitzung, niemals automatisch durch Codex oder einen Browser. Bei vorhandenen
Zielen/Accounts/Drop-ins stoppen und Zustand prüfen; nicht blind überschreiben.

Vorher Paketinhalt/Prüfsummen gegen einen unabhängig freigegebenen Buildbeleg
prüfen. Ein Hash aus demselben beschreibbaren Entwicklungsverzeichnis ist kein
Installationsvertrauen. Keine Projektdatei als ungeprüftes privilegiertes Skript
ausführen. Die vorbereiteten Dateien sind noch kein freigegebenes Installationspaket.

### Bereitstellung nach separater Installationsfreigabe

Erforderliche administrative Schritte, jeweils nur in frischen Zielverzeichnissen:

```sh
# Zuvor prüfen: getent passwd llm-casting-isolation-test
# Existiert der Account bereits: STOPP, nicht automatisch übernehmen.
useradd --system --user-group --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin llm-casting-isolation-test

# Neues Ziel muss fehlen; mkdir soll bei vorhandener Installation abbrechen.
mkdir -m 0755 /usr/local/lib/llm-casting-isolation
mkdir -m 0755 /usr/local/lib/llm-casting-isolation/fixtures
install -m 0644 tests/isolation/contract.py /usr/local/lib/llm-casting-isolation/contract.py
install -m 0644 tests/isolation/probe.py /usr/local/lib/llm-casting-isolation/probe.py
install -m 0644 tests/isolation/verify.py /usr/local/lib/llm-casting-isolation/verify.py
install -m 0644 tests/isolation/fixtures/child.py /usr/local/lib/llm-casting-isolation/fixtures/child.py
```

Die gemeinsame /var/lib-Testbasis nur nach Rechteprüfung neu anlegen. Pro Test
eine neue UUID und neue Instanz verwenden; Profile/Marker/Canaries exakt nach
fixtures/README erzeugen, nie bestehende Testroots recyceln. Vor dem Start:

```sh
id -u llm-casting-isolation-test
id -g llm-casting-isolation-test
stat -Lc '%i' /proc/self/ns/mnt
```

Diese tatsächlichen IDs, den Host-Namespace, aktuelle UTC-Zeit und die neue UUID
im Profil festhalten; Unit/Cgroup daraus exakt ableiten. Nicht mit den
Beispielwerten 62001/null starten. Profil kanonisch validieren und Hash extern
festhalten, z.B. mit dem bereits geprüften geschützten Modul:

```sh
python3 - <<'PY'
import sys
from pathlib import Path
sys.path.insert(0, '/usr/local/lib/llm-casting-isolation')
import contract as c
# Betreiber ersetzt diesen ausschließlich synthetischen Pfad vor Ausführung.
profile = c.read(Path('/var/lib/llm-casting-isolation/TEST-UUID/profile.json'))
pin = c.digest(profile)
c.validate_profile(profile, pin)
print(pin)
PY
```

Marker = kind synthetic_isolation_test_root, profile_version 1, test_id und
dieser profile_sha256. Canarybytes stehen in fixtures/README; keine freien
Pfad-/Inhaltsangaben. Nach Bereitstellung: Root/Marker/Profil und Negativ-/
Referenzdateien vor Workerschreiben schützen; nur frischen Output gezielt der
dedizierten Identität zuordnen. Keine Rechte vorhandener Daten verändern.

Nach Rootfs-/Staging-/Paketprüfung die Unitvorlage als neue Datei installieren
und ausschließlich für diese Instanz den geprüften Profilpin setzen:

```sh
install -m 0644 tests/isolation/unit-templates/llm-casting-isolation-probe@.service /etc/systemd/system/llm-casting-isolation-probe@.service
# Neues Instanz-Drop-in 10-profile.conf:
# [Service]
# Environment=LLM_CASTING_PROFILE_SHA256=DER_GEPRUEFTE_64_HEX_PIN
systemd-analyze --generators=no --man=no verify /etc/systemd/system/llm-casting-isolation-probe@.service
systemctl daemon-reload
```

Noch kein Start, bevor diese Voraussetzungen und die spezifische Startfreigabe
bestätigt sind. Ohne passendes Rootfs/Profil/Paket/Account bleibt der Test blockiert.

### Ein freigegebener Probe-/Abbruchlauf

Der Betreiber setzt die Variablen auf die **bereits überprüfte** Instanz:

```sh
s6c_test_id=GEPRUEFTE_TEST_UUID
s6c_test_unit="llm-casting-isolation-probe@${s6c_test_id}.service"
systemctl start "$s6c_test_unit"
s6c_invocation=$(systemctl show "$s6c_test_unit" --property=InvocationID --value)
systemctl show "$s6c_test_unit" --property=Id,InvocationID,ControlGroup,MainPID,ActiveState,SubState,MemoryMax,CPUQuotaPerSecUSec,TasksMax,RuntimeMaxUSec,KillMode,NoNewPrivileges
```

Genau eine feste Kindfixture innerhalb der Unit ist vorgesehen. Erwartet:
profilidentische Unit/Cgroup/IDs, pre_stop-JSON aus der Probe und anschließend
Timeout/Stop der **ganzen** Unit, nicht bloß ein beendeter Parent. Ein Runtime-
Timeout ist erwarteter Testausgang, aber allein kein erfolgreicher Endbeleg.
Die Kindfixture ist auch ohne wirksamen Timer selbst auf acht Sekunden begrenzt.

Nur wenn ein manuell freigegebener Abbruchtest oder ein Fehler dies erfordert:

```sh
systemctl stop "$s6c_test_unit"
```

Danach ausschließlich eigene Unit und fest zugeordnete Cgroup prüfen: Manager-
Identität/Invocation/Bootzuordnung, MainPID/Exitursache, ausstehende Jobs und
Unterbaum mit cgroup.events populated=0. Verschwundene Cgroup oder MainPID=0
allein sind kein Beweis, dass alle Kinder ordentlich beendet wurden. Fehlende
Belege bleiben not_verified; kein automatischer Wiederanlauf.

Nur die synthetische Probeausgabe dieser Invocation sichern, z.B. nach externem
Festhalten und Prüfung der Invocation-ID:

```sh
journalctl --no-pager --output=cat "_SYSTEMD_INVOCATION_ID=${s6c_invocation}" SYSLOG_IDENTIFIER=llm-casting-isolation-probe _TRANSPORT=stdout
```

Genau ein vollständiger passender JSON-Bericht muss erhalten bleiben. Bei mehreren
Zeilen, Abbruch, ungültigem JSON, falschen IDs oder abgeschnittener Ausgabe stoppen.
Keine unkontrollierte Suche in anderen Anwendungslogs. Bericht unverändert in
neuer eigener Belegdatei sichern; Profil-/Berichtspin separat dokumentieren.
Aufruf von verify.py wie in der Paket-README. Erwartetes V1-Ergebnis bleibt
isolation_verified=false mit vollständiger Liste fehlender Belege.

## 7. Spätere Netzwerk- und Ressourcenabnahme

Keine der folgenden aktiven Prüfungen ist hier implementiert/ausgeführt oder
durch einen Test-Unit-Start automatisch freigegeben. Nur neue lokale synthetische
Endpunkte, keine echten externen IPs, DNS-Resolver oder produktiven Provider:

| Grenze | Spätere sichere Prüfung | Bis dahin |
| --- | --- | --- |
| Externes IPv4/IPv6 | Genehmigte lokale simulierte Außenendpunkte in getrennten Testgrenzen; IPv4/IPv6 separat, tatsächliche Netzansicht belegen | not_verified; keine Verbindungen zu Internet-/Produktionsadressen |
| DNS | Eigener lokaler synthetischer Resolver/Sentinel; kein getaddrinfo gegen echte Namen/Resolver | not_verified |
| Unzulässige Unix-Sockets | Eigener Dummy-Socket außerhalb der genehmigten Sicht, unabhängig bestätigte Existenz | not_verified; ENOENT allein ist keine Sperre |
| Erlaubtes Gateway | Eigener eng begrenzter lokaler Echo-/Provider-Dummy mit fester Kennung; positiver Kontrolltest | not_verified; kein echter Ollama-Endpunkt |
| Direkter produktiver Ollama-Zugriff | Keine aktive Verbindung; spätere lokale Ersatzstrecke und unabhängige Namespace-/Routing-/Egressbelege | not_verified; Zieladresse wird nicht gelesen/abgefragt |
| Memory/Tasks/CPU | Separat freigegebene minimale, hart begrenzte Fixtures samt Hostmessung und positiver Kontrollstrecke | Konfiguration allein not_verified, keine Last-/Fork-Bomben |
| Laufzeit/Kinder | Eindeutige Start-/Endreceipts, vollständiger Unterbaum, unabhängige Prüfung nach Stop | not_verified, auch bei Exit 0/Timeout |

Wenn nur ein echter externer Versuch einen Anspruch prüfen könnte, bleibt er
zunächst offen. PrivateNetwork, AF_UNIX oder IP-Filterwerte sind allein keine
praktischen Netzbelege. Verlorener Provider-/IPC-Kontakt bleibt unbekannte Arbeit.

## 8. Fehler, Abbruch, Bereinigung und Rollback

Stopppunkte: abweichender HEAD/Pakethash, bestehende unbekannte Zielinstallation,
fehlende Rechte/Rootfs/Identität, ungültiger Pin, falsche Unit/Cgroup, zusätzliche
Gruppen/Caps, falscher Namespace, unbeschränkte Ressourcen, möglicher Fremdzugriff,
fehlende Kinder-/Endbelege oder manipulierte Ausgabe. Keine Lockerung von
ProtectHome/ProtectSystem/AppArmor/Capabilities und kein force=true als Lösung.

Bei Fehlern zuerst nur die zugeordnete Test-Unit stoppen; unbekannte/fremde
Prozesse oder Dienste nicht anfassen. Belege und Testroot erhalten. Kein Reset
oder Neuversuch derselben Instanz, solange Prozess-/Cgroupzustand unbekannt ist.

Rollback ist kein Engine-Revert: Es wurden nur eigene neue Testartefakte
bereitgestellt. Nach separat bestätigtem vollständigem Stillstand und Sicherung
der Belege darf der Betreiber **ausschließlich** diese eigenen neu installierten
Unit-/Instanzdateien entfernen und daemon-reload ausführen. Keine pauschale
Löschung nach Glob oder rekursiver Aufräumcode im Werkzeug. Testroot/rootfs/Paket
zunächst aufbewahren; spätere Entfernung gezielt anhand Installationsinventar.
Den Testaccount erst entfernen, wenn er ausschließlich neu für diesen Test
angelegt wurde und keinerlei Prozesse/Dateizuordnungen mehr offen sind. Bei
Unklarheit stehenlassen und eskalieren; keine Daten anderer Anwendungen löschen.

## 9. Prüfstand dieses Kandidaten

Die neuen Python-Tests blockieren HTTP-/Socket-/Popen-/Fork-/Spawn-/Shell-Aufrufe.
Sie arbeiten nur mit synthetischen Daten im Projekt und testen auch, dass ein
gefälschtes JSON den Live-Kindstart-Gatecheck nicht überwindet. Die Vorlage wurde
mit systemd-analyze --generators=no --man=no verify auf systemd 255 erfolgreich
geprüft; keine Unit/Generatoren gestartet oder installiert. Alle enthaltenen
Direktiven sind in den lokal installierten systemd-Handbüchern dokumentiert.

Lokaler Kandidatennachweis: **518/518 Tests erfolgreich**, davon 62 neue S6-C-
Tests und alle 456 bisherigen Tests, keine Skips. Syntax-, Diff-/Whitespace-/
Secret-/Link-/Bestandsschutzprüfung erfolgreich; alter Laufzeitcode, alte Tests,
Schemas, Golden-Fixtures und Archive unverändert. Keine Test-Unit oder Agenten
gestartet; der Systemmanager listet keine LLM-Casting-Isolations-Test-Unit.

Tests und synthetische Statusfälle sind keine praktische OS-Abnahme. Das reale
Verfahren bleibt bis zur ausdrücklichen Betreiberfreigabe und Bereitstellung
blockiert. Unabhängige MCP-Prüfung vor weiteren Schritten.
