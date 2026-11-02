# S6-D – Operator-Runbook für die praktische TST-Isolationsprüfung

Basis: main/1a6afeb, Ubuntu 24.04.4, systemd 255, Cgroup v2. **Dieser Kandidat
bereitet ausschließlich Phase 1 vor. Keine Installation, kein Unitstart,
keine praktische Abnahme.** Phase 2 benötigt nach unabhängiger MCP-Prüfung einen
neuen ausdrücklichen Betreiberauftrag. S5/S6 bleiben insgesamt offen.

Grundlagen: [Machbarkeit](S6_SANDBOX_FEASIBILITY.md),
[S6-C-Testplan](S6_ISOLATION_TEST_PLAN.md), [Prüfpaket](../tests/isolation/README.md).
Die historischen S6-C-Pfade/Accountnamen bleiben dokumentiert, werden aber nicht
übernommen. Für diesen Ablauf gelten ausschließlich die folgenden S6-D-Ziele.

## 1. Inventar, Verantwortlichkeiten und Freigabegrenze

| Gegenstand | S6-D-Ziel |
| --- | --- |
| Identität | llm-casting-probe, neue unprivilegierte lokale Systemidentität ohne Login/Home |
| Geschütztes Paket | /opt/llm-casting-isolation-probe/package |
| Synthetischer Testroot | /var/lib/llm-casting-isolation-probe/TEST-UUID |
| Test-Unit | llm-casting-isolation-probe@TEST-UUID.service, Slice=system.slice |
| Unitvorlage | tests/isolation/unit-templates/s6d/llm-casting-isolation-probe@.service |
| Root-Dateisystem | separat geprüftes normales rootfs.squashfs, extern gepinnter Dateihash |
| Belege | separates, vom Betreiber geprüftes privates Belegziel außerhalb aller Worker-Mounts |

Neue Werkzeuge: preflight.py und host_collect.py. Beide sind nur lesend, schreiben
nur JSON auf stdout und besitzen keine Installations-/Start-/Stop-/Cleanup-API.
Keine Shell, frei wählbaren Kommandos, fremden Unitnamen oder Browserpfade.
Systemctl-Aufrufe sind fest auf show/list-units und freigegebene Metadaten
begrenzt. Keine Environment-/ExecStart-Ausgabe, kein Zugriff auf Secrets.

Ein approval.json ist eine zeitlich begrenzte, profil-/paket-/imagegebundene
**Erklärung**, keine technische Authentifizierung und keine Freigabe durch Codex.
Selbst bei komplett passenden Checks bleibt phase2_execution_available=false.
preflight_checks_passed=true oder Exit 0 erlauben keinen Start. Manuelle Reviews
und die ausdrückliche spätere Betreiberentscheidung bleiben zwingend.

## 2. Jetzt zulässiges, nicht veränderndes Preflight

Im Projekt, ohne administrative Rechte und ohne Installation:

```sh
python3 tests/isolation/preflight.py --inventory
python3 tests/isolation/preflight.py \
  --test-id GEPRUEFTE_TEST_UUID \
  --expected-bundle-sha256 EXTERN_FESTGEHALTENER_BUNDLE_PIN
```

--inventory liefert das feste Dateiinventar mit Einzelhashes und Canonical-SHA256.
Das ist zunächst Inhaltsidentität, kein Installationsvertrauen. Vor privilegierter
Ausführung müssen diese Dateien gegen einen unabhängig freigegebenen Build-/
Reviewbeleg geprüft und geschützt bereitgestellt werden. Nicht root aus einem
beschreibbaren Entwicklungsverzeichnis starten.

Defaultmodus plan: Keine Übernahme bestehender Pfade/Accounts/Units. Auch
Symlinks, Instanzdateien und Drop-ins in den zwölf auf TST lesend ermittelten
systemd-255-Suchpfaden, einschließlich .control, Generator-/Transient-/Attached-
Pfaden, sind Kollisionen. Auch ungeladene statische Test-Units werden geprüft.
Bei abweichender Ausgabe von systemd-analyze unit-paths vor Nutzung stoppen und
das feste Prüfprofil überprüfen. Keine Ownership-/Modusannahmen für fremdverwaltete Elternpfade
und keinerlei Änderung ihrer Rechte. Bei Kollision stoppen, nicht löschen oder
automatisch eine andere Installation wählen.

Preflight plan wurde tatsächlich auf TST ausgeführt: Kollisions-/Basischecks bestanden;
Exit 1 mit fünf expliziten Stopps: fehlende administrative Rechte für spätere
Aktionen, ausstehende Betreiberentscheidung, nicht bereitgestellte Testumgebung,
fehlendes geprüftes Root-Image und fehlende geschützte Installation. Zielpfade,
Account/Gruppe und Test-Unitnamen waren kollisionsfrei. Phase 2 bleibt gesperrt.

## 3. Vor jeder späteren Installation manuell bestätigen

Alle folgenden Abschnitte sind **NICHT in diesem Auftrag ausgeführte**
Operatorbefehle. Je Block einzeln prüfen; bei unerwartetem Ergebnis stoppen.
Keine sudo-Aufrufe durch Codex, keine Ausführung auf Krankenhausstandorten.

Erforderlich sind:

- Neuer ausdrücklicher TST-Auftrag mit Test-/Abbruch-/Rückbauscope, keine
  produktive Executor-/OpenCode-Freigabe.
- Root-/Betreiberrechte für genau diese neue Identität, Dateien und Unit.
  Kein allgemeines sudo/polkit-Recht für Engine oder Testbenutzer.
- Unabhängig geprüfte Paketbytes und ein geprüftes minimales Python-SquashFS-
  Image. CONFIG_SQUASHFS=y wurde lesend festgestellt; Mount/Boot wurde nicht
  getestet. Ein konkretes freigegebenes Image liegt noch nicht vor: Stopppunkt.
- Geschütztes privates Belegziel, ausreichender Platz und eindeutiges Installations-
  inventar. Belegziel separat prüfen; es wird nicht vom Tool angelegt/freigegeben.
- Prüfung der UID-Neuvergabe anhand Betreiberinventar: keine alten dicomat-
  Dateieigentümer, keine UID-/GID-Aliasse, kein Login/Home, keine privilegierten
  Gruppen, keine sudo-/sonstigen Sonderregeln. Der Code liest keine sudoers oder
  dicomat-Konfigurationen; diesen Nachweis kann er nicht automatisch ersetzen.

Keine echten Dateien unter /etc/dicomat, Git-Repositories, fremden Homes oder
SSH-Verzeichnissen für Zugriffsversuche öffnen. Keine solchen Daten im Image.
Nichts von vorhandenen OpenCode-Servern übernehmen; OpenCode wird nicht ausgeführt.

## 4. Geschützte Bereitstellung – erst nach gesonderter Freigabe

Administrative Sitzung. S6D_APPROVED_BUNDLE bezeichnet ein bereits unabhängig
geprüftes Artefaktverzeichnis, nicht ungeprüft den Entwicklungs-Webroot.
Alle PIN-Werte werden vom Betreiber extern übernommen, nicht erfunden.

```sh
# Vorab geprüftes Inventar: sha256sum --check "$S6D_APPROVED_CHECKSUMS"
# Bei vorhandenem Account/Gruppe: STOPP, keine automatische Übernahme.
set -eu
if getent passwd llm-casting-probe; then exit 1; else test "$?" -eq 2; fi
if getent group llm-casting-probe; then exit 1; else test "$?" -eq 2; fi
# Nur Exit 2 (eindeutig nicht gefunden) ist als Ausgangszustand zulässig.
useradd --system --user-group --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin llm-casting-probe
id llm-casting-probe

# Neue Zielwurzeln müssen fehlen; mkdir ohne -p soll Kollisionen melden.
mkdir -m 0755 /opt/llm-casting-isolation-probe
mkdir -m 0700 /var/lib/llm-casting-isolation-probe
mkdir -m 0755 /opt/llm-casting-isolation-probe/package
mkdir -m 0755 /opt/llm-casting-isolation-probe/package/fixtures
mkdir -m 0755 /opt/llm-casting-isolation-probe/package/unit-templates
mkdir -m 0755 /opt/llm-casting-isolation-probe/package/unit-templates/s6d
for s6d_file in contract.py probe.py verify.py preflight.py host_collect.py fixtures/child.py fixtures/profile.example.json unit-templates/s6d/llm-casting-isolation-probe@.service
do
  install -m 0644 -- "$S6D_APPROVED_BUNDLE/$s6d_file" "/opt/llm-casting-isolation-probe/package/$s6d_file"
done
```

Keine pauschalen chmod/chown/ACL-Aktionen an /opt, /var/lib, Home oder bestehenden
Anwendungsdateien. Nur neue eigene Ziele bereitstellen. Keine Benutzeranlage,
wenn Identitäts-/Privilegieninventar unvollständig ist.

## 5. Frische Testidentität und synthetische Fixture-Daten

Neue UUID, keine Wiederverwendung nach unklarem Ausgang. Die Variablen bleiben
bis zum Rückbau in derselben kontrollierten Sitzung erhalten:

```sh
s6d_test_id=$(python3 -c 'import uuid; print(uuid.uuid4())')
s6d_unit="llm-casting-isolation-probe@${s6d_test_id}.service"
s6d_root="/var/lib/llm-casting-isolation-probe/${s6d_test_id}"
s6d_pkg=/opt/llm-casting-isolation-probe/package
# Betreiber setzt: s6d_bundle_pin, s6d_image_pin, s6d_approved_image,
# sowie s6d_evidence auf ein neues Ziel in seinem geprüften privaten Belegroot.
mkdir -m 0755 -- "$s6d_root"
mkdir -m 0755 -- "$s6d_root/reference" "$s6d_root/outside" "$s6d_root/other"
mkdir -m 0700 -- "$s6d_root/output"
# Ausdrücklich nur dieses gerade neu angelegte Outputverzeichnis:
chown -- llm-casting-probe:llm-casting-probe "$s6d_root/output"
mkdir -m 0700 -- "$s6d_evidence"
install -m 0444 -- "$s6d_approved_image" "$s6d_root/rootfs.squashfs"
```

Imagequelle ist ausschließlich das vorab freigegebene Artefakt. Das minimale
Image enthält Python/Loader/Standardbibliothek, notwendige synthetische passwd/
group-Einträge und leere Ziele für /fixtures, /opt/isolation sowie API-Dateisysteme.
Keine Hostroot-Kopie, Host-Home, Enginecode/.git, S3-Store, Secrets oder OpenCode.
Das Format wird nur am Magic/Hash geprüft; Inhalt und Bootfähigkeit bleiben ein
separater Betreiberreview-/Praxistest. Kein automatischer Imagebuilder/Download.

Profil und Canaries mit bereits geprüftem Paket erzeugen. UID/GID werden hier
aus dem gerade eingerichteten Account gelesen, niemals numerisch angenommen:

```sh
python3 - "$s6d_test_id" <<'PY'
import os, pwd, sys
from pathlib import Path
sys.path.insert(0, '/opt/llm-casting-isolation-probe/package')
import contract as c
import preflight as p
test_id = sys.argv[1]; c.identifier(test_id)
root = p.STATE / test_id
profile = c.read(p.INSTALL/'package/fixtures/profile.example.json')
account = pwd.getpwnam(p.IDENTITY)
profile['test_id'] = test_id
profile['created_at'] = c.now()
profile['expected'] = dict(uid=account.pw_uid, gid=account.pw_gid, unit=p.unit_for(test_id),
    cgroup='/system.slice/'+p.unit_for(test_id), host_mount_namespace_inode=os.stat('/proc/self/ns/mnt').st_ino)
profile['limits']['runtime_seconds'] = 15
pin = c.digest(profile); c.validate_profile(profile, pin)
p.validate_account(p.LocalSystem().account(), profile)
marker = dict(kind='synthetic_isolation_test_root', profile_version=1, test_id=test_id, profile_sha256=pin)
for name, value in (('profile.json', profile), ('marker.json', marker)):
    with (root/name).open('xb') as stream: stream.write(c.canonical(value))
for role in ('reference', 'outside', 'other'):
    with (root/role/'canary.txt').open('xb') as stream:
        stream.write(('llm-casting-isolation-canary:'+role+':'+test_id+'\n').encode('ascii'))
print(pin)
PY
```

Den ausgegebenen kanonischen Profilpin extern als s6d_profile_pin festhalten und
Profil unverändert in das private Belegziel sichern. Marker/Profil/Canaries sind
root-eigen, nicht durch den Testbenutzer beschreibbar. Nur output gehört ihm.
Diese Dateien enthalten ausschließlich künstliche Daten.

Mit vi die zeitlich begrenzte Operatorerklärung erstellen:

```sh
vi "$s6d_root/approval.json"
```

Exakt folgende Felder, keine boolesche Freigabe: kind=isolation_operator_declaration,
version=1, approval_id als neue UUID, test_id, scope=one_synthetic_test_only,
issued_at/expires_at als UTC-Z (max. eine Stunde, kurze Testfrist), bundle_sha256,
profile_sha256 und image_sha256. Werte müssen den extern geprüften Pins entsprechen.
Die Erklärung ist ein Auditvermerk zur bereits extern erteilten Entscheidung;
sie kann keine fehlende Betreiberfreigabe herstellen.

## 6. Unit und letzter Preflight

```sh
# Zielkollisionen vorher erneut prüfen, auch /run und /usr/lib samt Drop-ins.
install -m 0644 -- "$s6d_pkg/unit-templates/s6d/llm-casting-isolation-probe@.service" /etc/systemd/system/llm-casting-isolation-probe@.service
mkdir -m 0755 -- "/etc/systemd/system/${s6d_unit}.d"
vi "/etc/systemd/system/${s6d_unit}.d/10-profile.conf"
```

Drop-in **bytegenau** (64-Zeichen-Pin ersetzen, abschließender Zeilenumbruch):

```ini
[Service]
Environment=LLM_CASTING_PROFILE_SHA256=GEPRUEFTER_64_HEX_PROFILPIN
```

```sh
systemd-analyze --generators=no --man=no verify /etc/systemd/system/llm-casting-isolation-probe@.service
systemctl daemon-reload
python3 -E -s -B "$s6d_pkg/preflight.py" --mode prepared --test-id "$s6d_test_id" \
  --expected-bundle-sha256 "$s6d_bundle_pin" --expected-profile-sha256 "$s6d_profile_pin" \
  --expected-image-sha256 "$s6d_image_pin"
```

Vorlage: dedizierter User/Group, eigene RootImage-/Mount-/Cgroup-Grenze,
ProtectSystem=strict, ProtectHome, PrivateTmp/Devices/Network, leere Capabilities,
NoNewPrivileges, nur AF_UNIX, Syscall-/Namespacebeschränkungen; 128 MiB plus kein
Swap, 25% CPU, 16 Tasks, 15s äußere Laufzeit, 2s Stopfrist, KillMode=control-group,
Restart=no. Kein Install-Abschnitt, kein enable/Timer/Bootstart. Ausgeführt wird
nur probe.py, niemals OpenCode. Das feste Kind lebt selbst maximal acht Sekunden.

prepared prüft geschützte Paket-/Dateihashes, Profil-/Image-/Markerbindung,
aktuelle UID/GID/Namespacezuordnung, frischen Output, Canaries, exakte Unitbytes
und einzig zulässiges Instanz-Drop-in. Fremde Overrides, Prozesse derselben UID
oder bereits geladene Testinstanzen stoppen den Ablauf. Profilgrenzen müssen
der festen Vorlage entsprechen. Keine automatische Anpassung oder Reparatur.

Auch bei Exit 0 sind die manuell erforderlichen Reviews und die gesonderte
Startfreigabe noch zwingend. Jede unbekannte/fehlende Voraussetzung: STOPP.

## 7. Einmaliger Teststart und unabhängige Hostbelege

Nur nach ausdrücklicher Startfreigabe alle Befehle vorbereitet ausführen. Nicht
zwischen Start und erstem Hostsample interaktiv Dateien bearbeiten: die Fixture
lebt kurz. Hostcollector ausschließlich aus der geschützten Installation.

```sh
systemctl start "$s6d_unit"
s6d_invocation=$(systemctl show "$s6d_unit" --property=InvocationID --value)
s6d_boot=$(cat /proc/sys/kernel/random/boot_id)
python3 -E -s -B "$s6d_pkg/host_collect.py" --test-id "$s6d_test_id" --phase during \
  --expected-bundle-sha256 "$s6d_bundle_pin" --expected-profile-sha256 "$s6d_profile_pin" \
  --expected-boot-id "$s6d_boot" --expected-invocation-id "$s6d_invocation" \
  > "$s6d_evidence/during.json"
```

Belegdateien nur neu/exklusiv anlegen (z.B. noclobber in der kontrollierten
Sitzung); niemals überschreiben. during muss konsistente eigene Unit-, Boot-,
Invocation-, UID/GID-/Capability-/NoNewPrivileges- und Cgroupbelege enthalten.
Fehler/Exit 1/2: keine Annahme eines erfolgreichen Starts, keine Wiederholung;
falls nötig nur die eigene Unit kontrolliert stoppen und Diagnose sichern.

Der Hostcollector liest keine Probe-Selbstangaben: er fragt die exakt gebundene
Unit über systemctl show ab, liest alle Unter-Cgroups begrenzt und prüft einzelne
Prozesse mit PID-Startticks gegen PID-Reuse. Zwei UID-Inventare umfassen auch
Prozesse außerhalb der erwarteten Cgroup. Es werden weder cmdline noch environ,
SSH-Dateien oder Anwendungskonfigurationen gelesen. Unlesbare/rassende Metadaten
bleiben fehlende Belege. Ressourcenwerte sind konfiguriert/Verbrauch beobachtet,
**nicht** als Wirkung eines Belastungstests bestätigt.

Den during-Bericht kanonisch hashen und den Pin extern als s6d_during_pin sichern,
z.B. mit c.digest(c.read(Path(...))) aus dem geschützten contract-Modul. Anschließend
gezielt nur diese eigene Unit abbrechen und die Endaufnahme binden:

```sh
systemctl stop "$s6d_unit"
python3 -E -s -B "$s6d_pkg/host_collect.py" --test-id "$s6d_test_id" --phase after \
  --expected-bundle-sha256 "$s6d_bundle_pin" --expected-profile-sha256 "$s6d_profile_pin" \
  --expected-boot-id "$s6d_boot" --expected-invocation-id "$s6d_invocation" \
  --previous "$s6d_evidence/during.json" --expected-previous-sha256 "$s6d_during_pin" \
  > "$s6d_evidence/after.json"
journalctl --no-pager --output=cat "_SYSTEMD_INVOCATION_ID=${s6d_invocation}" SYSLOG_IDENTIFIER=llm-casting-isolation-probe _TRANSPORT=stdout
```

Nur den einen vollständigen passenden Probebericht sichern und mit verify.py
samt externen Pins auf Konsistenz prüfen. Kein Suchen in fremden Logs. Belege:
Profil/Marker, Erklärung, Bundle-/Imagepins, Preflight-JSON, Probe-JSON, during/
after samt Pins, eigene Unit-Enddiagnose und späteres Cleanup-JSON. Alles privat.

Endstatus observed_empty_bound_cgroup_and_uid_at_samples setzt eine gebundene
Startaufnahme, unveränderte Boot-/Invocation-/Cgroupidentität, terminale Unit,
MainPID=0, keinen Managerjob, leere UID-Inventare sowie dieselbe leere Cgroup
(populated=0) voraus. Fehlende, ersetzte oder bereits vom Manager entfernte
Cgroups bleiben **not_verified**, auch bei fehlenden UID-Prozessen. Dieses
Snapshotverfahren kann den kurzen Leermoment vor Cgroup-GC verpassen. Ein
verlässlicher dauerhaft gehaltener FD-/Ereignisnachweis ist dann vor weiterer
Abnahme separat zu entwickeln/testen; nicht aus Abwesenheit Erfolg ableiten.

Auch ein passendes Endsample ist ein zeitgebundener Hostbefund, keine globale
OS-/OpenCode-Freigabe. Exportiertes JSON ist nicht signiert: Operatorcapture,
geschützter Code und extern festgehaltene Pins bilden die Vertrauensgrenze.

## 8. Netzwerk und Ergebnisbewertung

Alle Netzwerkprüfungen bleiben zunächst not_verified. PrivateNetwork/AF_UNIX
sind statisch konfiguriert, nicht praktisch bewiesen. Keine aktiven externen IP-/
DNS-/Ollama-Versuche und kein realer Provider. Als nächste separat freizugebende
Ausbaustufe: lokale IPv4-/IPv6-Außen-Sentinels, Dummy-DNS, eigener erlaubter
Gateway-/verbotener Unix-Socket samt positivem Kontrolltest. Dafür fehlen noch
implementierte Fixtures und unabhängige Laufzeitbelege; nicht als vorhanden melden.

Getrennt ausweisen: statisch konfiguriert, zur Laufzeit beobachtet, unabhängig am
Host beobachtet, nicht nachgewiesen. Probe-/Hostverträge liefern weiterhin
isolation_verified=false. Kein Belastungs-/Fork-Bomben-Test, keine zusätzliche
Paketinstallation, kein OpenCode, keine Ollama-/Cloud-Anfrage.

## 9. Abbruch, Cleanup und Rollback

Bei falscher Unit/UID/Cgroup, Hash-/Profilabweichung, unlesbaren Prozessdaten,
verbliebenen Kindern oder unbekanntem Ende sofort stoppen. Nur die eigene exakt
gebundene Unit stoppen; keine fremden Dienste/Prozesse anfassen. Belege erhalten.
Nicht automatisch neu starten, keine Sicherheitsdirektive lockern und keine
Produktionssysteme als Ersatztest verwenden.

**Cleanup erst nach unabhängig geprüfter Arbeitsruhe und Betreiberfreigabe.**
Dateien vor Entfernung gegen das eigene Installationsinventar/Hashpins prüfen.
Bei Ersatz-/Fremddateien stoppen. Keine rekursiven Löschungen oder pauschalen Globs.

```sh
# Nur die selbst neu installierten, unveränderten Dateien:
rm -- "/etc/systemd/system/${s6d_unit}.d/10-profile.conf"
rmdir -- "/etc/systemd/system/${s6d_unit}.d"
rm -- /etc/systemd/system/llm-casting-isolation-probe@.service
systemctl daemon-reload
```

Danach Paket-/Testdateien einzeln anhand des gesicherten Inventars entfernen,
leere Verzeichnisse mit rmdir. Rootimage und private Belege vorher sichern;
Belegziel nicht mit aufräumen. Unbekannte Outputdateien nicht blind löschen.
Account erst entfernen, wenn UID-/GID-Inventar und Prozesse leer/geklärt sind,
keine anderen Dateizuordnungen bestehen und seine ausschließliche Neuanlage belegt ist:

```sh
userdel llm-casting-probe
# Falls die eigene neue Gruppe danach noch existiert und unbenutzt ist:
groupdel llm-casting-probe
python3 -E -s -B "$S6D_APPROVED_BUNDLE/preflight.py" --mode cleanup --test-id "$s6d_test_id" \
  --expected-bundle-sha256 "$s6d_bundle_pin" --saved-profile "$s6d_evidence/profile.json" \
  --expected-profile-sha256 "$s6d_profile_pin"
```

Cleanup-Prüfer liest nur: Zielpfade/Identität/Units/Overrides müssen fehlen,
gesicherte profilgebundene UID darf keine Prozesse haben. Unvollständige Scans,
Restdateien oder falsches Profil ergeben Stop. Exit 0 ist nur eine erfolgreiche
Abwesenheitsprüfung, keine Berechtigung zum Löschen oder Isolationsfreigabe.
Rollback lässt Engine/Archive/dicomat unverändert: nur eigene neue Testartefakte
zurücknehmen. Unklaren Zustand stehenlassen und berichten, nicht automatisch reparieren.

## 10. Nachweise dieses Phase-1-Kandidaten

Durchgeführt: lesende Bestandsaufnahme, CLI-Preflight plan, reine neue Unit-Tests,
Gesamtregression, Python-Syntaxprüfung, statische systemd-255-Prüfung ohne
Generatoren/Installation, Diff-/Secret-/Konflikt-/Bestandsschutzprüfung.
Nicht durchgeführt: Accountanlage, Installation, Imagebau/Mount, Unitstart/-stop,
praktische Datei-/Ressourcen-/Netzwerkprüfung, reale Hostcollector-Aufnahme einer
Test-Unit, Cleanup oder OpenCode-/Modellaufruf.

Lokaler Kandidatennachweis: **568/568 Tests erfolgreich**, davon 50 neue S6-D-
Tests und alle 518 bisherigen Tests; keine Skips. Syntax-, statische Unit-,
Diff-/Whitespace-/Secret-/Konflikt-/Linkprüfung erfolgreich. Engine-Code,
bisherige Tests, normative Schemas, Golden-Fixtures und Archive unverändert.
Lokale Prüfbelege bleiben Git-ignoriert. Finaler Dateisatz im Abschlussbericht.
Erst unabhängige MCP-Prüfung, danach gesonderter Auftrag zur
praktischen TST-Ausführung. Keine automatische produktive Freigabe.
