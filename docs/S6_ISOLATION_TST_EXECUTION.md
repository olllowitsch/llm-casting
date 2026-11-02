# S6-D Phase 2 – TST-Vorprüfung und Betreiber-Haltepunkt

**Stand: Phase A durchgeführt, Haltepunkt B erreicht. Phase C nicht ausgeführt.**
Die allgemeine Beauftragung ist ausdrücklich keine Installationsfreigabe.
Nach unabhängiger MCP-Prüfung ist eine gesonderte Betreiberentscheidung nötig.
isolation_verified bleibt false; S5 und S6 bleiben insgesamt offen.

Dieses Dokument konkretisiert das bestehende
[Operator-Runbook](S6_ISOLATION_OPERATOR_RUNBOOK.md), ersetzt weder dessen
Installationskonventionen noch die [V1-Grenzen](S6_ISOLATION_TEST_PLAN.md).
Es ist kein Installer. Alle unten aufgeführten Systembefehle sind **geplant,
nicht ausgeführt** und ausschließlich vom autorisierten Betreiber zu bedienen.

## 1. Tatsächlich geprüfter Bestand

| Punkt | Lesender Befund |
| --- | --- |
| Zielhost | testomat |
| Repository | main, cb66d60eca43337baefac26af3b931f681aadd16 |
| Working Copy bei Beginn | sauber; Prüfprogramme und Vorlage entsprechen HEAD |
| Betriebssystem/Kernel | Ubuntu 24.04.4 LTS, 6.8.0-147-generic, x86_64 |
| systemd | 255.4-1ubuntu8.18, +SECCOMP; Vorlage statisch erfolgreich geprüft |
| Cgroups | v2, cpu/memory/pids verfügbar; keine Cgroup verändert |
| Aktuelle Ausführungsidentität | EUID 1001, EGID 1003; keine Privilegieneskalation versucht |
| Testidentität | llm-casting-probe: Benutzer und Gruppe nicht vorhanden |
| Installationswurzeln | /opt/llm-casting-isolation-probe und /var/lib/llm-casting-isolation-probe frei |
| Test-Units | keine laufende/geladene passende Unit, keine passende statische Unitdatei oder Zielkollision im Preflight |
| Unit-Suchpfade | zwölf systemd-255-Pfade stimmen mit dem festen Prüfprofil überein |
| Python im Host | /usr/bin/python3: 3.12.3; kein Nachweis eines Root-Image-Interpreters |
| Image-Werkzeug | mksquashfs im PATH; nur passive Feststellung, nicht gestartet |
| Root-Image | kein freigegebenes konkretes Artefakt/Hash/Herkunftsbeleg bereitgestellt |

OpenCode wurde nicht ausgeführt. Keine Credentials, SSH-Dateien, geschützten
Anwendungskonfigurationen oder produktiven Provider als Testziele geöffnet.
Keine Benutzer-/Gruppenanlage, Installation, Unitsteuerung, Mount-/Netzwerk- oder
Firewalländerung. Keine Änderung an dicomat-refactor oder llm-casting-show.

## 2. Reproduzierbarer tatsächlicher Preflight

Nur als Planungsidentität angelegt, **kein Testlauf und keine Systemressource**:

```text
Test-ID: 26c21d74-2ee4-4b09-9dca-3877101d61b2
Unit: llm-casting-isolation-probe@26c21d74-2ee4-4b09-9dca-3877101d61b2.service
Bundle-SHA256: 0f1114c9501767aa5e7c226b0cadfd6cd3d29e6fc6112061d07accb9c50dbf21
Vorlagen-SHA256: 34171c07fa38316aa95c75c2c9dc30988ecfc7f305730f7ad710c218911791c7
```

Zweimal derselbe bestehende Preflight, ausschließlich lesend:

```sh
python3 tests/isolation/preflight.py \
  --test-id 26c21d74-2ee4-4b09-9dca-3877101d61b2 \
  --expected-bundle-sha256 0f1114c9501767aa5e7c226b0cadfd6cd3d29e6fc6112061d07accb9c50dbf21
```

Beide Läufe: **Exit 1, 57 Checks bestanden**, identische Ergebnisse außer
observed_at. Kein Fehler des Prüfprogramms; folgende fünf Stopps sind erwartet:

| Check | Einordnung / nächster notwendiger Schritt |
| --- | --- |
| operator_rights | Betreiberaktion erforderlich: aktueller Prozess führt keine administrativen Aktionen aus |
| operator_declaration | Betreiber-Haltepunkt: gesonderte ausdrückliche Entscheidung fehlt |
| prepared_fixture | Betreiberaktion erforderlich: noch keine Testinstallation/Canaries/Identität eingerichtet |
| root_image_ready | unbekannt/offen: geprüftes Image samt unabhängigem Hash/Herkunftsbeleg fehlt |
| protected_bundle_ready | Betreiberaktion erforderlich: noch keine geschützte Prüfinstallation |

Damit sind Versions-/Kollisions-/Paketprüfungen erfüllt, nicht die Voraussetzungen
für einen praktischen Start. Aktuell keine Kollision/Sicherheitsverletzung
festgestellt; dies ist kein Nachweis effektiver Isolation. Manuelle Reviews
zu UID-Dateieigentum, Privilegienregeln, Imageinhalt und Belegziel bleiben offen.

Maschinenlesbare lokale Belege: s6d-phase2-plan.local.json (Manifest, beide
Preflights), s6d-phase2-baseline.local.json, s6d-phase2-archive-baseline.local.json
und s6d-phase2-tests.local.log. Sie bleiben Git-ignoriert. Die hier ermittelten
Hashes identifizieren die geprüften Bytes, ersetzen aber keine externe Freigabe.

## 3. Exakter Freigabeumfang und noch fehlende Eingaben

Vor irgendeinem Systemeingriff muss der Betreiber festlegen/freigeben:

1. Einen unabhängig geprüften, gegen Änderung geschützten Export des achtteiligen
   Bundles aus dem genannten Commit; keine privilegierte Ausführung aus der
   beschreibbaren Working Copy. Externer Review-/Prüfsummenbeleg erforderlich.
2. Ein minimales Ubuntu-kompatibles Python-SquashFS als normale einzelne Datei,
   passenden Loader/Standardbibliothek und leere Mountziele /fixtures, /opt/isolation
   und API-Dateisysteme. Keine Hostroot-/Home-/Git-/S3-/dicomat-Kopie, kein OpenCode,
   keine Secrets. Inhalt, Python-Abhängigkeiten und Herkunft separat prüfen;
   mksquashfs-Verfügbarkeit oder ein Datei-Magic beweisen keine Bootfähigkeit.
3. Neuanlage von llm-casting-probe ohne Login/Home, privilegierte Gruppen oder
   Sonderrechte. UID/GID werden **erst danach tatsächlich gelesen**, nicht aus
   dem Beispielprofil 62001 übernommen. Kein Nachweis fehlender dicomat-
   Dateieigentümer durch Öffnen echter Anwendungsdateien: Betreiberinventar nutzen.
4. Genau die beiden freien Runbook-Wurzeln, die eine geplante Testinstanz,
   root-eigene Paket-/Profil-/Inputdateien und den einzigen Worker-Outputbereich.
5. Ein neues privates Belegziel außerhalb aller Worker-Mounts; dessen Elternpfad
   wird nicht umkonfiguriert. Pfad, Rechte und freier Platz separat prüfen.
6. Eine einmalige harmlose Testausführung mit höchstens einem festen Kind,
   unabhängige Hostaufnahmen, gezielten Abbruch und später separat kontrollierten
   Rückbau. Keine Freigabe für zusätzliche Netzwerkfixtures oder Belastungstests.

Für alle Befehle gelten: nur testomat, keine parallele Installation, erneute
Kollisionsprüfung unmittelbar davor, keine Übernahme/Überschreibung existierender
Objekte. Bei Drift seit dieser Vorprüfung zurück an den Haltepunkt. Eine
approval.json dokumentiert eine bereits externe Entscheidung und erzeugt sie nicht.

## 4. Geordnete Operatorbefehle – nur nach gesonderter Freigabe

Die vollständigen Profil-/Canary-Erzeugungsbefehle und Felddefinitionen stehen
unverändert im [Runbook, Abschnitte 4–7](S6_ISOLATION_OPERATOR_RUNBOOK.md).
Die folgenden Bindungen und Guards konkretisieren genau diese eine Instanz.
Keiner dieser Blöcke ist in diesem Codex-Durchlauf ausgeführt worden.

### O0 – Eingaben und nicht verändernde Guards

Voraussetzung: neue ausdrückliche Freigabe; Artefakt- und Belegpfade vom Betreiber
eingesetzt. Nachweis: externe Freigabe, Paketmanifest, Imageprüfsumme und erneutes
Preflight-JSON. Rückbau: keiner, dieser Block liest nur bzw. bindet Shellvariablen.

```sh
set -euC
umask 022
test "$(hostname)" = testomat
test "$(id -u)" -eq 0
s6d_test_id=26c21d74-2ee4-4b09-9dca-3877101d61b2
s6d_unit="llm-casting-isolation-probe@${s6d_test_id}.service"
s6d_root="/var/lib/llm-casting-isolation-probe/${s6d_test_id}"
s6d_pkg=/opt/llm-casting-isolation-probe/package
s6d_bundle_pin=0f1114c9501767aa5e7c226b0cadfd6cd3d29e6fc6112061d07accb9c50dbf21
: "${S6D_APPROVED_BUNDLE:?Geprüfter geschützter Bundleexport fehlt}"
: "${S6D_APPROVED_CHECKSUMS:?Extern freigegebene GNU-SHA256-Checkdatei fehlt}"
: "${s6d_approved_image:?Geprüftes Image fehlt}"
: "${s6d_image_pin:?Extern geprüfter Image-Dateihash fehlt}"
: "${s6d_evidence:?Freigegebenes neues privates Belegziel fehlt}"
( cd "$S6D_APPROVED_BUNDLE" && sha256sum --check --strict "$S6D_APPROVED_CHECKSUMS" )
printf '%s  %s\n' "$s6d_image_pin" "$s6d_approved_image" | sha256sum --check --strict
if getent passwd llm-casting-probe; then exit 1; else test "$?" -eq 2; fi
if getent group llm-casting-probe; then exit 1; else test "$?" -eq 2; fi
for s6d_path in /opt/llm-casting-isolation-probe /var/lib/llm-casting-isolation-probe "$s6d_evidence"
do
  test ! -e "$s6d_path"
  test ! -L "$s6d_path"
done
python3 -E -s -B "$S6D_APPROVED_BUNDLE/preflight.py" \
  --test-id "$s6d_test_id" --expected-bundle-sha256 "$s6d_bundle_pin"
```

Der letzte Befehl endet im noch nicht installierten Zustand erwartungsgemäß mit
1. Wegen set -e ist das zugleich ein bewusster Blockabschluss. Nur die oben
benannten erwarteten Stopps prüfen; keine anderen Fehler ignorieren und nicht
automatisch mit dem nächsten Block fortfahren. Erst nach Betreiberprüfung und
dem freigegebenen Installationsscope weiterarbeiten.

### O1 – Geschütztes Paket und Testidentität

Voraussetzung: alle Kollisionen frei, Identitäts-/Privilegieninventar geprüft,
O0 geprüft und Installationsfreigabe vorhanden. Befehle: Runbook Abschnitt 4,
useradd --system --user-group --no-create-home --home-dir /nonexistent
--shell /usr/sbin/nologin llm-casting-probe sowie exklusive mkdir-Ziele und der
feste achtteilige install-Dateisatz. Keine Rootwurzeln mit mkdir -p adoptieren.
Vor jedem Kopieren muss sein Ziel in den gerade neu angelegten root-eigenen
Verzeichnissen fehlen; bei vorhandener Datei oder Symlink stoppen.

Nachweis: id llm-casting-probe, tatsächlich zugeteilte UID/GID, normale
Einzel-Link-Dateien, root-Eigentum und keine Gruppen-/Fremdschreibrechte des
Pakets, Bundlehash identisch. Testidentität darf keine Engine-/dicomat-Dateien
besitzen oder beschreiben; keine SSH-/Providerkonfiguration bereitstellen.
Rückbau: nur eigene neue, nach Inventar geprüfte Paketdateien/Verzeichnisse und
die ausschließlich neu angelegte unbenutzte Identität, niemals fremde Daten.

### O2 – Genau ein synthetischer Testroot

Voraussetzung: O1 nachgewiesen, neue Instanzpfade und Belegziel weiterhin frei.
Befehle: Runbook Abschnitt 5 mit den oben gebundenen Variablen; mkdir exklusiv,
nur neuer output mit chown llm-casting-probe:llm-casting-probe, geprüftes Image
als rootfs.squashfs kopieren. Kein rekursives chmod/chown und keine Elternpfadänderung.
Vor der Kopie muss die Zieldatei fehlen; Imagehash anschließend erneut vergleichen.
Die vier anfänglichen Variablenzuweisungen aus Abschnitt 5 nicht erneut ausführen:
insbesondere keine neue UUID erzeugen, sondern die in O0 festgehaltene Planungs-ID
verwenden. Bei späterer Drift/unklarem Ausgang ist dieser Plan nicht wiederzuverwenden.

Profil-/Canary-Generator aus Abschnitt 5 ausschließlich aus geschütztem geprüftem
Paket benutzen. Er liest die tatsächlichen UID/GID, aktuellen Host-Mount-Namespace
und UTC-Zeit; runtime_seconds muss 15 sein. Alle Schreibdateien neu/exklusiv.
Profile/Marker/Referenz-/Außen-/Fremd-Canaries root-eigen und für den Worker
nicht beschreibbar, nur output mit dessen UID/GID und 0700. Externe Pins und
unveränderte Profilkopie im Belegziel sichern. Danach mit vi approval.json gemäß
Runbook erstellen; keine boolesche Freigabe und keine erfundenen Hashwerte.

Nachweis: Profil-/Markerbindung, Canaryhashes, Imagehash, Modus-/Besitzinventar
und frischer leerer Output. Rückbau: diese selbst neu erzeugten Dateien nach
Inventar; Belege bleiben erhalten. Noch kein Start und keine OS-Wirksamkeitsaussage.

### O3 – Temporäre Test-Unit und letzter Guard

Voraussetzung: O2 belegt, erneute Kollisionsprüfung in allen zwölf Unit-Suchpfaden
einschließlich .control/Generator/Attached/Transient und sämtlicher Drop-ins.
Vorlagenhash muss dem oben genannten Wert entsprechen. Keine andere Instanz oder
Prozess derselben Test-UID darf aktiv sein. Nur folgende Unit-/Drop-in-Ziele:

```sh
test ! -e /etc/systemd/system/llm-casting-isolation-probe@.service
test ! -L /etc/systemd/system/llm-casting-isolation-probe@.service
# noclobber: vorhandene Unitdateien nicht überschreiben.
cat -- "$s6d_pkg/unit-templates/s6d/llm-casting-isolation-probe@.service" \
  > /etc/systemd/system/llm-casting-isolation-probe@.service
mkdir -m 0755 -- "/etc/systemd/system/${s6d_unit}.d"
: "${s6d_profile_pin:?Extern festgehaltener kanonischer Profilpin fehlt}"
printf '%s\n' '[Service]' "Environment=LLM_CASTING_PROFILE_SHA256=${s6d_profile_pin}" \
  > "/etc/systemd/system/${s6d_unit}.d/10-profile.conf"
systemd-analyze --generators=no --man=no verify /etc/systemd/system/llm-casting-isolation-probe@.service
systemctl daemon-reload
python3 -E -s -B "$s6d_pkg/preflight.py" --mode prepared --test-id "$s6d_test_id" \
  --expected-bundle-sha256 "$s6d_bundle_pin" --expected-profile-sha256 "$s6d_profile_pin" \
  --expected-image-sha256 "$s6d_image_pin"
```

Nachweis: exakte Unitbytes/Drop-in, Root-/Profil-/Paketchecks, zusätzliche manuelle
Reviews abgeschlossen. Umask 022 in der administrativen Sitzung sicherstellen;
kein vi-Backup/weiterer Drop-in in diesem Verzeichnis. Bei Exit 1/2 stoppen.
Exit 0 bedeutet nur passende Preflight-Fakten, keine Startfreigabe. Rückbau:
unveränderte eigene Unit/Drop-in entfernen, leere Instanzdirectory mit rmdir,
danach daemon-reload. Kein enable, Timer oder Bootstart.

### O4 – Einmaliger Teiltest, Hostbelege und gezielter Abbruch

Voraussetzung: eigene ausdrückliche Start-/Stopfreigabe, O3 vollständig geprüft,
alle Befehle/Belegpfade vorab bereit. Vor dem Start Beleginventar und leeres
UID-Prozessinventar sichern; noch keine InvocationID oder UID/GID erfinden.

```sh
systemctl start "$s6d_unit"
s6d_invocation=$(systemctl show "$s6d_unit" --property=InvocationID --value)
s6d_boot=$(cat /proc/sys/kernel/random/boot_id)
python3 -E -s -B "$s6d_pkg/host_collect.py" --phase during --test-id "$s6d_test_id" \
  --expected-bundle-sha256 "$s6d_bundle_pin" --expected-profile-sha256 "$s6d_profile_pin" \
  --expected-boot-id "$s6d_boot" --expected-invocation-id "$s6d_invocation" \
  > "$s6d_evidence/during.json"
```

Kanonischen during-Berichtspin mit dem geprüften contract-Modul bestimmen und
extern als s6d_during_pin festhalten. Nicht den abweichenden pretty-JSON-Dateihash
einsetzen. Anschließend, gemäß bereits vorab freigegebenem Abbruchscope:

```sh
systemctl stop "$s6d_unit"
python3 -E -s -B "$s6d_pkg/host_collect.py" --phase after --test-id "$s6d_test_id" \
  --expected-bundle-sha256 "$s6d_bundle_pin" --expected-profile-sha256 "$s6d_profile_pin" \
  --expected-boot-id "$s6d_boot" --expected-invocation-id "$s6d_invocation" \
  --previous "$s6d_evidence/during.json" --expected-previous-sha256 "$s6d_during_pin" \
  > "$s6d_evidence/after.json"
journalctl --no-pager --output=cat "_SYSTEMD_INVOCATION_ID=${s6d_invocation}" \
  SYSLOG_IDENTIFIER=llm-casting-isolation-probe _TRANSPORT=stdout
```

Die feste Kindfixture lebt maximal acht Sekunden; äußeres RuntimeMaxSec=15s
ist eine Sicherung, kein Nachweis seiner Wirkung. Keine interaktive Bearbeitung
zwischen Start und during-Aufnahme. Geht eine Aufnahme verloren oder endet ein
Befehl unerwartet, nur die exakt gebundene eigene Unit kontrolliert stoppen,
Belege erhalten und abbrechen. set -e ersetzt diesen beaufsichtigten Fehlerpfad
nicht: ein abgebrochener Befehlsblock räumt keine laufende Unit automatisch auf.

Keine Wiederholung derselben Instanz bei unklarem Ende. Hostcollector vertraut
nicht Probe-JSON, sondern Manager-/Kernelmetadaten mit Boot/Invocation, PID-
Startticks, UID/GID und Cgroupidentität. Eine verschwundene/ersetzte Cgroup bleibt
not_verified, auch wenn MainPID=0 oder keine UID-Prozesse sichtbar sind.

### O5 – Auswertung und bewusste Nachweisgrenzen

Nur einen vollständigen, identisch gebundenen Probebericht in neuer Belegdatei
sichern. Dann bestehenden verify.py mit --profile, --report und den extern
festgehaltenen --expected-profile-sha256/--expected-report-sha256 verwenden.
Exit 1 ist bei konsistentem V1-Teilbericht erwartbar. Kein Exitcode 0 aus einem
Host-/Preflight-Werkzeug wird zu einer produktiven Isolationsfreigabe umgedeutet.

| Kriterium | Mit unverändertem V1 maximal prüfbar / offen |
| --- | --- |
| Eigener Output, Referenz | begrenzte synthetische IO-Proben; DAC vs. read-only Mount nicht vollständig getrennt |
| Fremder Workspace | unzugänglicher Parent kann nur not_verified ergeben, kein erfundener Existenz-/Sperrnachweis |
| Synthetischer Host-Canary | outside_write prüft nur verweigerten Schreib-Open; **keine Leseunzugänglichkeit** – zusätzliche Prüfung erforderlich |
| Symlink/Traversal | sicherer Programm-Pfadreader, noch kein vollständiger OS-Ausbruchstest |
| Ressourcen | konfigurierte Limits und kleine Verbrauchssnapshots, keine Stress-/Grenzwirkungsprüfung |
| Prozessende | gebundene Start-/Endbelege; Cgroup-GC kann einen belastbaren Endnachweis verhindern, dann Stop |
| IPv4/IPv6/DNS/Unix/Gateway | aktive lokale Fixtures fehlen; alles not_verified, keine externen Ersatzziele |

Für die vollständigen Phase-C-Kriterien fehlen somit noch praktische Nachweise
und teilweise zusätzliche Prüfimplementierung. Nur ein ausdrücklich als solcher
freigegebener **Teiltest** ist mit dem aktuellen Paket planbar. Wer vollständige
Leseunzugänglichkeit oder Netzwerkabnahme als Startvoraussetzung verlangt, muss
zunächst einen separaten Ergänzungsauftrag erteilen; keine Richtlinie aufweichen.

### O6 – Rückbau nur nach eigenem Freigabepunkt

Voraussetzung: unabhängig bestätigte Arbeitsruhe und gesicherte Belege; niemals
bei unbekannter Prozess-/Cgroupzuordnung. Eigene installierte Dateien vor dem
Entfernen gegen Inventar/Hashes prüfen, fremde oder geänderte Objekte erhalten.
Runbook Abschnitt 9 ist maßgeblich: eigene Unit/Drop-in gezielt entfernen,
daemon-reload, nur einzeln inventarisierte Test-/Paketdateien entfernen, leere
Directories mit rmdir. Kein rm -rf, kein Glob-Cleanup und kein rekursives chmod/chown.

Nur falls ausschließlich neu angelegt und vollständig unbenutzt: userdel
llm-casting-probe, anschließend ggf. groupdel llm-casting-probe. Belegziel bleibt
außerhalb der abgebauten Installation erhalten. Abschließend lesend:

```sh
python3 -E -s -B "$S6D_APPROVED_BUNDLE/preflight.py" --mode cleanup --test-id "$s6d_test_id" \
  --expected-bundle-sha256 "$s6d_bundle_pin" --saved-profile "$s6d_evidence/profile.json" \
  --expected-profile-sha256 "$s6d_profile_pin"
```

Nachweis: keine eigenen Installationswurzeln/Unitdateien/Drop-ins/Identität mehr,
keine Prozesse der gesicherten Test-UID; Cleanup-JSON privat sichern. Bei Resten
oder unlesbaren Daten stoppen und diese melden. Im jetzigen Durchlauf gibt es
keinen Systemrückbau, weil keinerlei Systemressourcen angelegt wurden.

## 5. Entstehende Systemänderungen – ausschließlich konditional

Die Freigabe von O1–O6 würde eine neue lokale Systemidentität mit den üblichen
verwalteten Accountdateieinträgen, zwei neue geschützte Testwurzeln, genau eine
neue Testvorlage mit Instanz-Drop-in sowie temporäre Mount-/Cgroup-/Prozess- und
Journaleinträge erzeugen. daemon-reload liest Unitdateien neu, startet aber keine
bestehenden Dienste neu. Es gibt keinen Autostart und keine periodische Ausführung.
Fremdverwaltete Elternrechte, bestehende Dienste, Firewall, dicomat/HL7/DICOM,
Engine-Code und vorhandene Archive werden nicht verändert.

## 6. Tatsächliche Abschlussprüfungen und Haltepunkt

568/568 bestehende Tests erfolgreich, keine Skips. Syntaxprüfung aller 28 Python-
Quell-/Testdateien und statische systemd-255-Vorlagenprüfung ohne Generatoren/
Installation erfolgreich. Vorlagen-/Programmbytes entsprechen HEAD. Bestehende
109 Ergebnis-/Reportdateien entsprechen auch der vorliegenden Phase-1-Hashbaseline.
Diff-/Secret-/Konflikt-/Konsistenz- und abschließende Bestandsschutzprüfung siehe
lokale Prüfbelege und Abschlussbericht. Keine neuen Tests oder Programmänderungen.

**Haltepunkt B: hier endet dieser Auftrag.** Empfohlene nächste Betreiberaktion:
geprüftes Root-Image mit Herkunftsbeleg/Hash und privates Belegziel benennen,
danach die konkret gebundenen Operatorblöcke und den begrenzten Teiltestscope
gesondert freigeben. Die jetzige Vorprüfung ist keine Systeminstallationsfreigabe.
