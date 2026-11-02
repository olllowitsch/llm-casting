# S6-C – synthetisches Isolations-Prüfpaket v1

Nur Vorbereitung/Teilprüfung, kein Executor. Vollständiges Verfahren und spätere
Operatorbefehle: [S6_ISOLATION_TEST_PLAN.md](../../docs/S6_ISOLATION_TEST_PLAN.md).
Keine Installation oder Unitaktivierung durch diese Werkzeuge.

| Datei | Zweck |
| --- | --- |
| contract.py | Striktes, begrenztes JSON, privater Profil-/Berichtsvertrag und Statusberechnung |
| probe.py | Eigene Prozessmetadaten und harmlose Dateiprüfungen ausschließlich in der vorgesehenen Test-Unit |
| verify.py | Offline-Konsistenzprüfung mit extern vorgegebenen Profil-/Berichtshashes |
| fixtures/child.py | Genau ein fester, selbst nach acht Sekunden endender Kindprozess; keine Shell, Sockets oder Allokationsschleife |
| fixtures/profile.example.json | Nicht startbereites Beispiel: UID/GID, Test-ID, Host-Mount-Namespace und Zeit müssen durch Betreiber festgelegt werden |
| unit-templates/llm-casting-isolation-probe@.service | Geprüfte systemd-255-Vorlage, nicht installiert; benötigt eigenes Rootfs, Benutzer, Paket und Profilpin |

Keine externen Python-Pakete. Das Paket ist separat kopierbar; keine Imports
oder Änderungen am Engine-Laufzeitcode und keine Erweiterung normativer S1/S2-
Schemas. Die Werkzeuge öffnen niemals echte Secrets, Provider oder Browserpfade.

## Lokale automatisierte Prüfung

```sh
python3 -m unittest discover -s tests -p test_isolation.py -v
python3 -m unittest discover -s tests -q
systemd-analyze --generators=no --man=no verify tests/isolation/unit-templates/llm-casting-isolation-probe@.service
```

Die Unit-Tests sperren sämtliche Prozessstarts und Socket-/HTTP-Zugriffe. Nur
eigene temporäre synthetische Dateien unter dem Projekt werden bearbeitet.
Es wird kein Kindprozess gestartet; die Kindprozess-Zustände sind synthetisch.
systemd-analyze prüft lediglich die Vorlage und startet weder Unit noch Generator.

## Private Verträge

Profil: kind=isolation_test_profile, profile_version=1, test_id (kanonische UUID),
created_at (UTC-Z), expected (UID/GID, exakter Unitname/Cgroup und erwarteter
Host-Mount-Namespace-Inode), feste Dateisystem-/Netzwerkpolicy samt expliziten
Erwartungen sowie begrenzte Ressourcenwerte. Alle Prüfungen sind verpflichtend;
ein Profil kann keine davon optional schalten oder ihre Erwartungen abschwächen.
Keine frei konfigurierbaren Kommandos, URLs oder Prüfpfade.

Bericht: kind=isolation_test_report, Profil-/Test-/Berichtsidentität, Profilhash,
observed_at, stage, observations, berechnete checks, overall_status,
isolation_verified, assurance und missing_evidence. Einzelstatus ist passed,
failed oder not_verified. Ein Beobachtungswert darf nicht als Messung einer
anderen Eigenschaft ausgegeben werden: z.B. CapEff=0 ist kein Mountnachweis.

JSON ist UTF-8, max. 256 KiB, Tiefe 20, max. 10000 Knoten, String max. 64 KiB,
Integer max. 128 Bit. Keine Floats/NaN, doppelten Schlüssel, unbekannten Felder,
Versionen oder Bool-als-Integer. Kanonische Bytes: sortierte Schlüssel,
ensure_ascii=false, keine Zwischenräume/Zeilenumbrüche; SHA256 über diese Bytes.
Ein pretty-printed JSON hat daher gewöhnlich einen anderen Dateihash.

## Ausführungs- und Freigabegrenzen

probe.py verlangt vor Schreibzugriffen/Kindstart die **aktuell gelesene** passende
Unit-/Cgroup-/UID-/GID-Zuordnung, keine weiteren effektiven Gruppen, leere
Capabilities, NoNewPrivileges, einen vom gepinnten Host unterschiedlichen
Mount-Namespace und passende begrenzte Cgroupwerte. Ein Kindstart liest diese
Werte erneut; ein übergebenes JSON kann den Live-Gatecheck nicht ersetzen.
Der ausdrücklich bereitgestellte synthetische Root und sein profilgebundener
Marker müssen root gehören und gegen Gruppen-/Fremdschreiben geschützt sein.

Negative Dateitests nutzen nur feste Canarynamen unter diesem Root. Ein
Schreib-Open wird ohne O_TRUNC und ohne tatsächliche Canaryänderung geprüft.
Nur eine eigene, exklusiv neu angelegte Scratchdatei wird geschrieben/entfernt;
ein unerwartet erlaubter Hardlink zum bekannten synthetischen Referenzcanary
wird als Fehler gewertet und nur dieser eigene Link entfernt. Keine Links oder
Traversal in eingelesenen Dateipfaden. Ein nicht sichtbarer/fehlender Canary
ist not_verified, kein Beweis einer erfolgreichen Sperre.

**V1 erteilt grundsätzlich keine OS-Abnahme.** Ressourcenwerte sind nur gelesene
Konfiguration; Ressourcenwirkung, Laufzeitlimit, vollständiges Baumende,
Abbruchwirkung, finale Bestätigung, OS-Traversal-/Mount-/Gesamtsicht und sämtliche
Netzwerkprüfungen bleiben not_verified. Aktive Netzwerkprüfungen sind noch nicht
implementiert. Der direkte Ollama-Endpunkt wird weder ermittelt noch kontaktiert.
Die dazu nötigen späteren synthetischen Endpunkte und unabhängigen Hostbelege
sind im Testplan beschrieben, nicht durch JSON-Behauptungen nachrüstbar.

verify.py rechnet Einzelstatus/Gesamtstatus/fehlende Belege neu und weist
inkonsistente Erfolgsbehauptungen zurück. Prüfsummen schützen die Bindung an
extern vorgegebene Bytes, authentisieren aber keinen Urheber. Ein Angreifer,
der Bericht **und** erwartete Prüfsumme kontrolliert, kann Selbstbeobachtungen
nachbauen; auch dann entsteht mit diesem Profil niemals isolation_verified=true.
Eine vollständig positive Abnahme benötigt einen später geprüften unabhängigen
Hostcollector und ein neues akzeptiertes Profil, nicht nur andere JSON-Werte.

## Offline-Verifikation eines späteren Berichts

Mit tatsächlichen, extern festgehaltenen Pins; keine Platzhalter als Belege:

```sh
python3 tests/isolation/verify.py \
  --profile /ABSOLUTER/SYNTHETISCHER/TESTROOT/profile.json \
  --report /ABSOLUTER/PRUEFBELEG/probe.json \
  --expected-profile-sha256 PROFILPIN \
  --expected-report-sha256 BERICHTSPIN
```

Das Werkzeug schreibt ausschließlich JSON auf stdout. Exit 1 bedeutet konsistent,
aber failed/not_verified; Exit 2 ungültig oder nicht sicher prüfbar. Exit 0 wird
in V1 nicht vergeben. consistency_verified=true ist keine Isolationserlaubnis.
Wiederholtes Prüfen verändert weder Quelldaten noch Berichtsidentität.

probe.py ist für Operatorstart in der Vorlage vorgesehen. Ohne --with-child
liefert es einen Teilbericht; mit --with-child publiziert es einen pre_stop-
Bericht vor dem maximal acht Sekunden lebenden Kind. Danach ist weiterhin ein
unabhängiger Endbeleg erforderlich. Unit-Timeout/abgebrochene Ausgabe sind kein
Erfolg. Bei Fehlern bleiben Belege erhalten; keine automatische Wiederholung,
Bereinigung, Signalgebung oder Lockerung der Unitregeln.
