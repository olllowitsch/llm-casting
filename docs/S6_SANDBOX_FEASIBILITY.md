# S6-B – Machbarkeit eines isolierten OpenCode-Executors

Stand: 2026-11-02, ausschließlich TST. Engine-Basis main, `a0b7ff4`.
**Empfehlung, keine Implementierung oder Betriebsfreigabe.** S5/S6 bleiben offen;
das S6-A-Gate verweigert unverändert jede reale Ausführung.

## Ergebnis und Nachweisstufen

Bevorzugt wird **B: ein kontrollierter Executor-Dienst mit eigener Identität und
festem Startprotokoll**, der je Versuch eine restriktive systemd-System-Service-
Unit verwaltet. Die Unit ist der Isolations-/Ressourcenbehälter, nicht der
Auftragskoordinator. Dazu gehören ein minimales Root-Dateisystem, getrenntes
Staging und ein eng begrenztes Provider-Gateway. CLI und privater OpenCode-Server
müssen gemeinsam darin laufen. Ein bloßer systemd-run-Aufruf reicht nicht.

Diese Empfehlung ist bedingt: praktische Dateisystem-/Netzwerk-/Cgroup-Tests,
vertrauenswürdige Bereitstellung und Coding-/Protokollverträge fehlen. Bei einem
fehlenden Nachweis bleibt die Ausführung gesperrt; keine schwächere Ersatzgrenze.

Kennzeichnung in diesem Dokument:

- **L – lokal geprüft:** Metadaten, rein lesende Capability-Abfragen, Versions-/
  Hilfeausgabe; keine Test-Unit, keine Agentenausführung.
- **D – dokumentiert/statisch:** offizielle Handbücher oder gepinnter Upstream-
  Quellcode; keine Garantie, dass das lokale Binary alle Eigenschaften so ausführt.
- **P – geplant:** Zielentwurf, noch nicht implementiert.
- **O – offen:** nur durch spätere, gesondert freigegebene Tests entscheidbar.

Für systemd heißt A grundsätzlich dokumentiert, B lokal lesend nachgewiesene
Voraussetzung und C später erforderlicher praktischer Wirksamkeitstest.

## 1. TST-Inventar und Grenzen der Erhebung

| Gegenstand | L: Befund | Nicht nachgewiesen |
| --- | --- | --- |
| Betriebssystem | Ubuntu 24.04.4 LTS, x86_64, VMware-Gast | Andere Standorte/Installationen |
| Kernel | 6.8.0-147-generic | Fehlerfreiheit/Sandbox-Ausbruchsicherheit |
| systemd | 255.4-1ubuntu8.18; Manager running | Wirksame Isolation einer neuen Unit |
| systemd-Build | +SECCOMP, +APPARMOR, -BPF_FRAMEWORK; unified hierarchy | Funktionsfähige IP-Filterinstallation |
| Node.js | v20.20.1 | Voraussetzung einer bestimmten OpenCode-Distribution; lokales OpenCode ist ein ELF/Bun-Bundle |
| Cgroups | cgroup2; cpu, memory, pids sowie weitere Controller vorhanden; cpu/memory/pids am Root aktiviert | Zulässige Delegation und Limits für künftige Units |
| Eigene bestehende Scope | cgroup.events, cgroup.freeze, cgroup.kill, memory.max, cpu.max, pids.max vorhanden | Kill-/Freeze-Wirkung; nichts davon geschrieben |
| Aufrufidentität | EUID 1001, primäre GID 1003, weitere Gruppe 27; effektive Linux-Capabilities leer | Administrative Berechtigung zur Sandboxbereitstellung |
| Cgroup-Verwaltung | Vorhandene System-Cgroup-Verzeichnisse für den Aufrufer nicht beschreibbar | Autorisierte StartUnit-/StartTransientUnit-Rechte |
| Werkzeuge | systemd-run/systemctl/unshare/bpftool im PATH | Einsatzbereitschaft einer Sandbox; kein Probe-/Namespace-Start |
| Nicht im PATH | bwrap/bubblewrap, podman, docker | Vollständige Inventarisierung aller nichtstandardmäßigen Installationspfade |

L: Kernelkonfiguration enthält Namespaces (User/PID/Net), Cgroups/PIDs/Memory,
CFS-Bandwidth, Seccomp/Filter und Cgroup-BPF/BPF-Syscall/JIT. AppArmor und Landlock
sind in der LSM-Liste; AppArmor ist aktiv. unprivileged_userns_clone=1 und
max_user_namespaces=63520 stehen **gleichzeitig** mit
apparmor_restrict_unprivileged_userns=1. Daraus folgt keine Freigabe für bubblewrap
oder Rootless Podman. unprivileged_bpf_disabled=2 betrifft unprivilegierte BPF-
Nutzung, nicht automatisch alle Möglichkeiten des privilegierten Systemmanagers.

Es wurden ausschließlich ausgewählte Versions-/Feature-/Metadaten gelesen:
/etc/os-release, Kernel-Compilekonfiguration, benannte /proc-/sys-Parameter,
Manager-Version/Features und lokale systemd-Handbücher. Keine Credentials,
SSH-Schlüssel, Anwendungskonfigurationsinhalte, fremden Prozessargumente oder
Prozessumgebungen. Keine Abfrage vorhandener Provider und keine Testverbindung.

Zwei OpenCode-Prozesse verschiedener UIDs waren bereits mehrere Tage vor dieser
Prüfung aktiv. Nur Name/UID/Startalter wurden festgestellt; Zweck und Workloads
bleiben unbekannt. Keine Verbindung, Unterbrechung oder Zuordnung ihrer Sessions.
Der spätere Executor darf solche bestehenden Server niemals automatisch nutzen.

## 2. Installiertes OpenCode und sichere CLI-Erhebung

L: `$OPERATOR_HOME/.opencode/bin/opencode` ist eine normale ELF-Datei, kein
Symlink, Größe 246831280 Bytes, Modus 0755. Eigentümer ist der aufrufende
Entwicklungsbenutzer; die OpenCode-/bin-Elternverzeichnisse sind 0775 und für ihn
beschreibbar. Das Binary ist damit **kein geschützter privilegierter Codepfad**.

L: Aufruf --version liefert `opencode v2.2.0`, Exitcode 0. SHA256 vor und nach den
Hilfeabfragen:

```text
87a4d6ac3c1b5691d4fb5e88f473992016b37ede6611c5cb7092fcdb1d91fad0
```

Das bestätigt beobachtete Version/Inhaltsidentität, keine Release-Signatur oder
reproduzierbare Übereinstimmung zwischen Quellcode und Binary. P: Künftig ein
geprüftes Release samt vertrauenswürdigem Installationsbeleg in geschützter
Bereitstellung außerhalb des Entwicklungs-Home verwenden. Hash gegen eine
ebenfalls beschreibbare Datei genügt nicht als Vertrauensanker.

Tatsächlich ausgeführt wurden nur --version, --help und run --help, jeweils ohne
Prompt, mit geschlossenem stdin, frischer expliziter Umgebung ohne geerbte
Credentials und projektlokalen XDG-/Config-Zielen. Alle drei endeten mit 0 und
leerem stderr. **Kein opencode run mit Auftrag**, kein models/debug-config/auth/
service/API-Befehl. Auch Hilfe legt XDG-Verzeichnisse und ein Log an: beobachtete
Projektlokalität ist deshalb wichtig; Hilfe ist kein garantiert schreibfreier
Programmweg. Lokale Prüfbelege liegen Git-ignoriert, nicht im Commit-Dateisatz.
Dies ist kein Netzwerktrace oder Sandbox-Nachweis.

| Option | L: installierte Hilfe | Konsequenz für P |
| --- | --- | --- |
| run | Nichtinteraktiver Nachrichtenbefehl | Nur nach OS-Abnahme überhaupt zulassen |
| --format json | Auswahl default/json | Eigenen Wire-Decoder benötigen |
| --model | provider/model#variant | Provider, Modell und optionale Variante getrennt pinnen; kein Default |
| --session | Fortsetzen oder bei Nichtexistenz neu erstellen | Flag allein ist kein sicheres Resume |
| --continue/--fork | Letzte Session/Fork | Kein automatischer Einsatz bei unbekanntem Versuch |
| --standalone | Privater Server statt Hintergrunddienst | Gesamte Kindprozessstruktur isolieren |
| --server | Verbindung zu anderem Server | Freie Browser-/Plan-URL verbieten; im Zielprofil ausgeschlossen |
| --auto | Nicht explizit verbotene Permissions automatisch genehmigen | Kein Sicherheitsmechanismus; im vorgesehenen Profil ausgeschlossen |

Die lokale v2-Hilfe ist maßgeblich für diese Optionsnamen; die allgemeine
[CLI-Webdokumentation](https://docs.opencode.ai/docs/cli/) ist kein vollständiger
v2.2.0-Wirevertrag.

### Statisch geprüfter v2.2.0-Quellstand

Der öffentliche Release-Tag wurde lesend auf Commit
`1097e2668b1e08ad63bdf0b1c4860b9bc01e420c` aufgelöst. Für sechs untersuchte Dateien
stimmen die heruntergeladenen Tag-Bytes mit diesem unveränderlichen Commit
überein. Keine dieser Dateien wurde ausgeführt. Das ist eine **Quellprüfung D**,
keine Binär-/Live-Protokollverifikation.

- [run.ts](https://github.com/anomalyco/opencode/blob/1097e2668b1e08ad63bdf0b1c4860b9bc01e420c/packages/cli/src/run/run.ts):
  Nachricht kann aus Argumenten und stdin zusammengesetzt werden; Dateien können
  Inhalt hinzufügen. Argumentformatierung kann Quotes einfügen. P: Gemeinsamen
  Prompt im tatsächlich übermittelten Payload prüfen, nicht nur Ausgangsdateihash;
  keine ungeprüften --file-/Argument-/stdin-Kombinationen. Vorabfehler können ein
  error-JSON mit leerer sessionID und Exitcode 1 erzeugen.
- [server-connection.ts](https://github.com/anomalyco/opencode/blob/1097e2668b1e08ad63bdf0b1c4860b9bc01e420c/packages/cli/src/services/server-connection.ts):
  Ohne Standalone wird ein Hintergrundserver gesucht/bereitgestellt; im normalen
  Pfad kann Versionsabweichung toleriert werden. P: Keine Übernahme vorhandener
  Server, kein tolerierter Versionswechsel. --standalone und --server schließen
  einander aus.
- [standalone.ts](https://github.com/anomalyco/opencode/blob/1097e2668b1e08ad63bdf0b1c4860b9bc01e420c/packages/cli/src/services/standalone.ts):
  Privater Kindprozess für serve, stdio-Lease, eigener kurzlebiger Zugang und
  Beendigungsbehandlung. Dies ist keine garantierte Nachkommenkontrolle; nicht
  mit einem rein prozessinternen Server verwechseln.
- [session-target.ts](https://github.com/anomalyco/opencode/blob/1097e2668b1e08ad63bdf0b1c4860b9bc01e420c/packages/cli/src/session-target.ts):
  Sessionwahl/-neuanlage ist eigene Serverlogik. P: Nur persistierte, eindeutig
  gebundene Sessions übernehmen; fehlen sie, bleibt der Versuch gesperrt.
- [global.ts](https://github.com/anomalyco/opencode/blob/1097e2668b1e08ad63bdf0b1c4860b9bc01e420c/packages/util/src/global.ts):
  Getrennte Daten-/Config-/State-/Cache-/Log-/Tempbereiche; Anlage von Verzeichnissen.
  P: Jeder Versuch erhält eigene beschreibbare Zustandsbereiche, ohne Host-Home.

### Konfiguration und Provider – D, nicht aus Hostkonfiguration gelesen

Die offizielle [Config-Dokumentation](https://docs.opencode.ai/docs/config/)
beschreibt zusammengeführte Remote-, globale, benutzerdefinierte, Projekt- und
Inline-Konfigurationen sowie Erweiterungsverzeichnisse. Ein eigener Configpfad
ersetzt diese Quellen nicht automatisch. [v2-CLI-Configcode](https://github.com/anomalyco/opencode/blob/1097e2668b1e08ad63bdf0b1c4860b9bc01e420c/packages/cli/src/config/config.ts)
verwendet zusätzlich cli.json und OPENCODE_CLI_CONFIG_CONTENT für CLI-Einstellungen;
das ist nicht der vollständige Server-/Providervertrag. Effektive serverseitige
Konfiguration bleibt O, sie wurde nicht durch Start eines Servers inspiziert.

P: Geschlossene Startumgebung, private Home-/XDG-/Tempbereiche, gepinnte Config,
nur der genehmigte Provider und feste Modelle, keine übernommenen Authdateien,
Plugins/MCP/Skills/LSP-Downloads oder automatischen Installationen/Updates.
Wettbewerbsinputs dürfen keine verdeckten OpenCode-/Agenten-Konfigurationsquellen
aktivieren. Toolfähigkeiten und wirksame Instruktionen werden privat archiviert.
Die genaue v2.2.0-Wirkung aller Abschaltoptionen muss getestet werden; kein Flag
wird aus seinem Namen allein als vollständige Sperre akzeptiert.

[Permissions](https://docs.opencode.ai/docs/permissions/) sind Anwendungsregeln,
keine OS-Sandbox. Ausgangspunkt ist deny, mit ausdrücklich freigegebenen Tools;
--auto und versteckte Freigabe-Aliasse werden nicht zugelassen. P: Geprüfte
Providerkonfiguration und Gateway erzwingen Modellidentität; kein automatisches
Login, Credential-Fallback oder Cloudprovider bei fehlender lokaler Konfiguration.
Der tatsächliche Modell-Digest ist im CLI-Ereignisstrom noch nicht nachgewiesen.

## 3. S6-A-Kompatibilitätsmatrix

Die Wire-Befunde D beruhen auf
[noninteractive.ts](https://github.com/anomalyco/opencode/blob/1097e2668b1e08ad63bdf0b1c4860b9bc01e420c/packages/cli/src/run/noninteractive.ts).
Keine aufgezeichnete reale Antwort liegt vor.

| S6-A-Annahme | OpenCode v2.2.0: Eigenschaft | Status | Offener Test |
| --- | --- | --- | --- |
| Eigenes profile/sequence/session_id/data | Ausgabehülle type/timestamp/sessionID plus part oder error | D; nicht wire-kompatibel | Bytefixtures, Framing, Reihenfolge, Trunkierung |
| started mit Provider/Digest/Bindinghash | step_start markiert einen Schritt, nicht denselben Bindungsnachweis | D; Digest/Executorbeleg unbekannt | Kontrollkanal und Modellbeleg separat prüfen |
| text | text mit verschachteltem part; reasoning ist eigener Typ | D | Unicode, große Inhalte, Teil-/Doppelevents |
| tool als symbolischer Wunsch | tool_use berichtet Werkzeugzustände; reale Servertools arbeiten unabhängig vom Decoder | D | Effektive Verbote vor Toolausführung beweisen |
| completed als Terminalmarker | step_finish kann mehrfach auftreten; Session-Erfolg wird intern verarbeitet, kein entsprechendes allgemeines completed-JSON zugesichert | D | Mehrschrittverlauf und finalen Sessionzustand prüfen |
| error nur begrenzter Code | error kann strukturierte Typen/Freitext tragen; sessionID vor Sessionanlage leer | D | Whitelistprojektion, Geheimnisfilter, Vorstart-/Laufzeitfehler |
| Keine Floats im S1-Parser | step_finish enthält cost/tokens; zulässige Zahlenformen noch gesondert abzubilden | D/O | Strikter externer Decoder mit begrenzten Dezimalzahlen, S1/S2 nicht lockern |
| Regex-Session plus Fixture-Bindung | --session kann fehlende Sitzung neu anlegen | L/D | Keine Wiederholung bei fehlendem Kontrollbeleg |
| FakeEnd stopped/Exitcode | CLI-Erfolg/SIGINT sind keine Baum-/Cgroup-Endbelege | D/O | Server, Tools und Hintergrundkinder kontrollieren |
| Feste Fake-Profilversion | Binary nennt v2.2.0; kein eigener Wire-Handshake belegt | L/O | Binary-/Server-/Schema-/Configpin gemeinsam prüfen |
| Gleicher Prompt/Inputhash | CLI kann Argumente/stdin/Dateien kombinieren | D/O | Tatsächliche Nutzlastgleichheit für alle Teilnehmer |
| Idempotente Fake-Projektion | Server-/IPC-Verlust ist kein bestätigtes Ende | O | Crash-/Resume-Matrix samt externer Arbeit |

D: Der Code behandelt bestimmte Fehler mit Exit 1 und SIGINT mit Exit 130;
ein weiteres SIGINT kann sofort beenden. Interrupt-RPC-Fehler können unbeachtet
bleiben. Das ist keine vollständige getestete Exitcodetabelle und kein SIGTERM-
oder Cgroup-Vertrag. JSON allein und Exitcode allein genügen jeweils nicht.

P: Vollständiger Erfolg benötigt passend gebundenen Session-Erfolg, validierte
vollständige Ausgabe ohne Fehler, akzeptierten Exitstatus, unabhängiges lokales
Baumende, geklärte Providerrequests und geprüfte Artefakte. Zeitstempel/Tokenwerte
aus CLI-JSON sind keine verifizierten Ollama-Timings; der Quellcode projiziert
Millisekunden, während der S2-Messvertrag Nanosekunden vorsieht. Einheiten und
Zeitbasis müssen getrennt abgebildet werden; Unbekanntes bleibt null.
Keine echte Ausgabe direkt an den S6-A-Fixturedecoder übergeben. Versionierter
Wire-Decoder/Coding-Planvertrag bleiben eigene spätere Implementierungsschritte.

## 4. systemd 255: grundsätzliche und lokale Fähigkeiten

Dokumentation A: [exec](https://www.freedesktop.org/software/systemd/man/255/systemd.exec.html),
[resource-control](https://www.freedesktop.org/software/systemd/man/255/systemd.resource-control.html),
[service](https://www.freedesktop.org/software/systemd/man/255/systemd.service.html),
[kill](https://www.freedesktop.org/software/systemd/man/255/systemd.kill.html).
Zusätzlich wurden die installierten Handbücher geprüft; keine fremde Unit-
Konfiguration wurde gelesen. **Keine Zeile der folgenden Tabelle ist ein C-Nachweis.**

| Direktive / Grenze | A: unterstützt | B: lokal lesend | C: zwingend später |
| --- | --- | --- | --- |
| User / eigene Identität | Ja | Aktuelle EUID ist nicht root | Neue Executor-/Workeridentität, kein UID-/Gruppenkonflikt |
| Eigene Cgroup | Ja | Unified hierarchy und Scope vorhanden | CLI/Server/Tools vollständig zugeordnet, kein Escape |
| MemoryMax | Ja | Memorycontroller vorhanden | OOM- und Nachkommenlimit |
| CPUQuota | Ja | CPUcontroller/Bandwidth vorhanden | Tatsächliche Drosselung; Quote ist kein CPU-Gesamtzeitbudget |
| TasksMax | Ja | PIDs-Controller vorhanden | Begrenzter Fork-Test, keine Escape-Kinder |
| RuntimeMaxSec | Ja | Direktive im installierten Handbuch | Ablauf und vollständige Stopkette |
| KillMode=control-group | Ja | Dokumentiert, noch keine Probe | Gesamter Baum weg, nicht nur Parent |
| PrivateTmp | Ja | Mount-Namespaces im Kernel | Keine Host-Temp-/Socketfreigabe |
| ProtectSystem=strict | Ja | Direktive vorhanden | Schreibsperre; versteckt lesbare Hostdateien nicht allein |
| ProtectHome | Ja | Direktive vorhanden | Host-Homes nicht sichtbar; kein pauschales Aufweichen |
| ReadWritePaths | Ja | Mount-Funktionen vorhanden | Ausschließlich private schreibbare Bereiche; kein Rechtegrant an sich |
| InaccessiblePaths | Ja | Direktive vorhanden | Sperren tatsächlich erreichbar/nicht umgehbar |
| NoNewPrivileges | Ja | Kernelgrundlage, aktuell im Prüfprozess 0 | Workerwert 1, Setuid/Capability-Eskalation abgewiesen |
| RestrictAddressFamilies | Ja | +SECCOMP | Familienbegrenzung ohne geerbte Socket-FDs als Umweg |
| SystemCallFilter | Ja | +SECCOMP und Kernel-Filter | Bun/Tools lauffähig, verbotene Syscalls gesperrt |
| PrivateDevices | Ja | Direktive vorhanden | Nur notwendige Pseudogeräte, keine GPU-/Hostgeräte |
| CapabilityBoundingSet | Ja | Prüfer hat keine effektiven Caps | Worker mit leerer Bounding-/Ambientmenge |
| RestrictNamespaces | Ja | Kernel-Namespaces vorhanden | Worker kann keine zusätzlichen Namespaces öffnen |
| PrivateNetwork | Ja | Net-Namespace im Kernel | Nur eigener Loopback; kein Host-/Provider-Egress |
| IPAddressAllow/Deny | Ja, voraussetzungsabhängig | Cgroup-BPF im Kernel, Build meldet -BPF_FRAMEWORK | Programm geladen und tatsächliche IPv4/IPv6-Sperre |

P: System-Service statt User-Scope verwenden. Mount-/Benutzergrenzen und
Ressourcenrechte nicht aus einer vorhandenen Benutzergruppe oder aus systemd-run
ableiten. RestrictNamespaces für den Worker verhindert nicht, dass der Manager
vorher dessen genehmigte Isolation einrichtet; konkrete Kombination testen.

P: Zusätzlich minimale RootDirectory/RootImage, unsichtbare fremde /proc-Einträge
(ProtectProc/ProcSubset mit getrennten UIDs), geschützte Kernel-/Cgroupansichten,
begrenzte private temporäre Dateisysteme, keine Delegation an den Agenten und kein
automatischer Neustart. systemd 255 wird hier **keine PrivatePIDs-Direktive**
zugeschrieben; ein eigener PID-Namespace ist durch diese Prüfung nicht belegt.

## 5. Dateisystem und S3-Handoff

L: S3 erzwingt Storewurzeln **innerhalb des Engine-Projekts**, privaten Besitz
der Engine-EUID, getrennte workspaces/artifacts/journals und No-Follow-/Single-
Link-/Same-Device-Prüfungen. active ist gesperrt. Das sind wertvolle Speicher-
invarianten, aber keine Agenten-Sandbox. Die aktuelle Implementierung akzeptiert
nicht einfach einen außerhalb des Projekts liegenden produktiven S3-Root.

Ein direkter Bind-Mount des vollständigen Stores ist ungeeignet: private
Zugriffsrechte passen nicht zu einer anderen Worker-UID; dieselbe UID könnte
eigene Schutzmodi ändern. Fremde Mounts im S3-Baum kollidieren zudem mit dessen
Dateisystem-/Inventarvertrag. ProtectSystem macht Hostdateien nicht unsichtbar.

**P: Staging statt Freigabe des Engine-Projekts.** Beispielnamen, keine heute
angelegten Pfade oder bereits validierte Config-Keys:

```text
Engine/S3 (unverändert privat, nur Engine-Identität)
  -> kontrollierte normale Inputkopien und gepinnter Auftrag
Executor-Spool außerhalb Home/Webroot: /var/lib/llm-casting-executor/...
  -> je Versuch minimale Root + private Identität + Unit
     /work/reference   unveränderliche Inputkopien, read-only
     /work/output      eigener beschreibbarer Output
     /work/state       eigene OpenCode-DB/Config-/Cache-/Logzustände
     private Tempbereiche mit eigenen Größenlimits
  -> nach Stillstand neue geprüfte Dateikopien zurück in Engine-Outputs
Engine/S3 prüft und archiviert unabhängig
```

Private State-/Tempbereiche gehören zum eigenen Versuchsarbeitsbereich; sie
werden nicht als Wettbewerbsoutput blind übernommen. Nur /work/output ist das
zulässige Outputinventar. Input-/Output-/State-/Imagepfade werden aus geprüften
IDs und Operator-Konfiguration abgeleitet, niemals aus Browserpfaden/Modelltext.

P: Eigenständiges, geschützt bereitgestelltes minimales Root-Image, nicht der
Hostroot mit nur einigen Schreibsperren. Darin keine Host-SSH-Dateien,
dicomat-refactor, Enginequellen/.git, S3-Journale/Archive, anderen Workspaces,
/etc/dicomat oder privaten Anwendungskonfigurationen. Keine breiten /home-, /run-,
/etc- oder Host-/proc-Freigaben, keine D-Bus-/Container-Admin-Sockets, keine
geerbten Kontroll-/Netzwerk-FDs. Eigene synthetische Systemdateien statt Hostsecrets.

Neue kontrollierte Stagingbereiche brauchen passende Besitz-/Mountregeln für die
Workeridentität. Bevorzugt separate Dienstidentität für den Executor und eigene
Workeridentität je Versuch, z.B. geprüfte DynamicUser-/Systemdirectory-Verwendung.
Besitzübergang, UID-Wiederverwendung und Rücknahme müssen getestet werden; ein
read-only Mount allein macht ein Engine-eigenes 0700-Verzeichnis nicht lesbar.
Keine rekursive chmod/chown/ACL-Freigabe von Home oder S3.

Collection nur nach bewiesener lokaler Arbeitsruhe: neues privates Engine-
Output, begrenztes explizites Inventar, normale Einzel-Link-Dateien, dirfd-gebundene
Prüfung, stabile Inodes/Hashes vor und nach dem Kopieren. Keine Bewertung von
Agenten-Behauptungen oder Collection im noch beschreibbaren Live-Workspace.
Bewertungsregeln/-programme bleiben außerhalb der Agentensicht und werden durch
S5 separat geprüft. Derzeit gibt es diesen UID-/Mount-/Kopier-Handoff noch nicht.

## 6. Netzarchitektur und gezieltes Ollama

A: PrivateNetwork erzeugt einen privaten Netzwerkraum; Host-Loopback und ein
entfernter Ollama-Server sind daraus nicht automatisch erreichbar. Ein Host-
Ollama auf 127.0.0.1 wird nicht zum Loopback des Agenten. IPAddressAllow/Deny
begrenzen IPs, nicht allein den gewünschten HTTP-Dienst/Port und nicht AF_UNIX.
DNS und IPv6 können zusätzliche Wege schaffen; geerbte Socket-FDs ebenso.

Das installierte Handbuch warnt vor wirkungslosen IP-Listen bei fehlenden
Voraussetzungen. -BPF_FRAMEWORK ist weder ein erfolgreicher Filtertest noch der
Beweis, dass jedes IPAddress-Feature fehlt: der
[v255-Firewallcode](https://github.com/systemd/systemd/blob/v255/src/core/bpf-firewall.c)
enthält eigene BPF-Programmlogik. Kerneloptionen/bpftool im PATH ersetzen keinen
erfolgreichen Attach-/Negativtest. Kein BPF-Probeprogramm wurde geladen.

**P: Bevorzugter Weg ohne direkten Host-Egress des Agenten:**

```text
OpenCode-CLI + privater Server + Tools (PrivateNetwork)
  -> HTTP nur am privaten Loopback
  -> fest begrenzte Bridge zu genau einem sichtbaren AF_UNIX-Socket
  -> vertrauenswürdiges Provider-Gateway außerhalb der Agentengrenze
  -> genau konfiguriertes Ollama-Ziel
```

Bridge/Gateway sind neue, noch nicht implementierte Komponenten. Ein nativer
OpenCode-Unix-Socket-Provider wird nicht behauptet. Die Loopback-Bridge erlaubt
das HTTP-Providerprotokoll und den privaten OpenCode-Server trotz Netzsperre.
RestrictAddressFamilies könnte dafür AF_UNIX/AF_INET/AF_INET6 erlauben; wirkliche
Egresssperre liefert der isolierte Netzwerkraum, nicht die bloße Familienliste.
Nur der eigene Provider-Socket wird ins minimale Dateisystem eingebunden; keine
Host-Unix-Sockets. Abstract-Sockets/FD-Vererbung gesondert negativ testen.

Gatewaykonfiguration kommt nur vom Betreiber: feste Origin/IP/Port/Modellmenge,
keine freien Ziel-URLs, Redirects, Proxy-Umgebungen, CONNECT, Plugins oder Cloud-
Fallbacks. Nur benötigte, versioniert geprüfte Generierungs-/Metadatenoperationen
zulassen; Modellinstallation/-löschung/-verwaltung verbieten. Bodies, Antworten,
Streaming, Zeit/Tokenbudget und gleichzeitige Requests begrenzen. Modellbindung
und notwendige Digestbelege separat prüfen. DNS bleibt, falls nötig, außerhalb
der Sandbox kontrolliert; Adressänderungen benötigen erneute Freigabe. IPv4 und
IPv6 werden gleichermaßen berücksichtigt, ohne internes Ziel im Dokument zu nennen.

Lokales Host-Ollama oder ein genehmigtes entferntes Ollama sind damit dieselbe
fest konfigurierte Gateway-Aufgabe. IP-Filter des Gateway-Dienstes sind mögliche
zusätzliche Härtung, nach Wirksamkeitsprüfung; keine alleinige Sicherheitsgrenze.
Alternativ wäre ein separater Netzwerkraum mit festem Routing/Firewall nötig:
höherer Betreiberaufwand und ausdrücklich keine jetzige Empfehlung zur Änderung
der Hostfirewall. Eine reine IP-Allowlist ohne Port-/Protokollgrenze genügt nicht.

**Wichtig:** Ende der lokalen Cgroup beweist kein Ende einer entfernten Inferenz.
Gateway muss eigene Provider-Intents und Abschlüsse zuordnen. Bei Verlust einer
Antwort bleibt externe Arbeit unbekannt; keine automatische neue Anfrage oder
neuer Versuch. /api/ps ist weiterhin kein ausreichender Ruhebeleg.

## 7. Prozess-, Abbruch- und Resume-Entwurf

P: Genau eine auflösbare Zuordnung aus run_id, participant_id, repetition,
attempt_id, plan_sha256 und Startnonce. Der Executor prüft eine feste versionierte
Auftragshülle und einen authentisierten lokalen Kontrollkanal; keine Shellstrings,
frei wählbaren Executables, Unit-Properties, Umgebungen oder Hostpfade.

| Phase | Geplanter Beleg / Verhalten |
| --- | --- |
| Prepare | Engine validiert Definitionen/Prompt/Inputs, erstellt S3-Workspace; Executor prüft unveränderliche Stagingkopien/Image/Config |
| Intent | Engine persistiert Startabsicht vor Auftrag; Executor bestätigt idempotente Identität vor Unitstart |
| Start | Kontrollierter System-Service, Type=exec als Ausgangspunkt; CLI --standalone und alle Nachkommen in derselben Cgroup |
| Identify | Boot-ID, Unitname, InvocationID, Cgrouppfad, Startnonce und Binary-/Config-/Imagehashes an Versuch binden; PID allein reicht nicht |
| Observe | Autorisierte Manager-/Executorereignisse getrennt von untrusted stdout; begrenztes JSON-Framing und monotone Budgetüberwachung |
| Timeout/Cancel | Abbruchwunsch persistieren; SIGINT/Stop nur für eigene Identität, begrenzte Schonfrist, gesamte Cgroup beenden |
| Confirm | Terminale Unitdaten/Exitursache sichern, keine offenen Jobs/Neustarts, Cgroup-Unterbaum leer (populated=0), Lease/IPC beendet, keine unbekannte Providerarbeit |
| Collect | Keine Schreiber; Inventar unabhängig prüfen und als normale Dateien übernehmen |
| Commit | Engine veröffentlicht Resultat mit Belegen atomar/no-replace über bestehende Speichergrundlage; keine Erfolgsmeldung vor Commit |

KillMode=control-group, SendSIGKILL und begrenzte TimeoutStopSec sind geplante
Bestandteile, Restart=no ist zwingend. RuntimeMaxSec ist eine äußere Sicherung,
kein Ersatz für persistierte Zeitlimits. CPUQuota drosselt, begrenzt aber keine
kumulierte CPU-Arbeit; dafür Verbrauch über die ganze Cgroup überwachen und bei
Budgetende kontrolliert stoppen. Speicher/PIDs/Dateisystem-/Ausgabelimits gelten
auch für Kinder und OpenCode-State. Kein unbounded stdout, Core-Dump oder Tempfile.

P: Swap explizit begrenzen (MemorySwapMax nach Abnahme), private tmpfs-Bereiche
mit Größen-/Inodebudget oder ein gleichwertig begrenztes Dateisystem verwenden.
Auch persistenter Spool und Kontrollbelege brauchen Kapazitätsgrenzen. Ein bloßes
ReadWritePaths oder nachträgliches S3-Dateilimit verhindert keine volle Hostdisk
während der Ausführung. Logs über einen begrenzten Kontrollkanal übernehmen,
statt unbegrenzt in das Hostjournal oder eine Engine-Datei zu schreiben.

Die mögliche Kombination mit ExitType=cgroup und das Aufbewahren terminaler
Unitbelege ist C-Testgegenstand, keine schon bewiesene Direktivenrezeptur.
Keine frühe --collect-/GC-Nutzung, bevor Identität und Abschluss dauerhaft
gesichert sind. Entfernte/garbage-collected Units bedeuten ohne Abschlussbeleg
**nicht** "nie gestartet". Bei nicht eindeutigem Baumstatus: uncertain.

Ein Executor-Neustart rekonstruiert eigene Handles und übernimmt nur exakt
identische laufende Units; niemals wiederholtes start/run für dieselbe unklare
Slot-ID. Fehlende Startantwort, IPC-Abbruch, Reboot, falsche InvocationID oder
unvollständiger Commit führen zu Sperre, nicht --continue/--session-Neuanlage.
Bestätigte Belege sind erneut lesbar und zählen nicht doppelt. Abbruch-Request-Ack
ist kein Endbeleg. S2/S3-Zustände werden nicht durch neue Fantasiestatus ersetzt.

Executor hält nur nötige idempotente Start-/Endreceipts; er plant keine
Wettbewerbe, bewertet nichts und startet keine Retries. Maßgeblicher Laufplan,
Resultat und Runjournal bleiben bei der Engine. S3 active sowie Coding-/S2-
Profile müssen vor Umsetzung versioniert erweitert/geprüft werden; keine
Umgehung der heutigen Sperre und kein paralleles zweites Runjournal.

systemd-run kann eine Unit anlegen/auf sie warten, bietet allein aber weder
Plan-/Promptbindung, sichere Auftragsautorisierung, langlebige Receipts noch
Crash-/Provider-Reconciliation. Scope-Modus übernimmt zudem die Aufrufumgebung;
Default-Type=simple bestätigt noch keinen exec-Erfolg. Für dauerhafte Integration
bevorzugt das feste Dienstprotokoll statt freier Kommandozeilenprivilegien.
Quellen: [systemd-run 255](https://www.freedesktop.org/software/systemd/man/255/systemd-run.html),
[Manager-API 255](https://www.freedesktop.org/software/systemd/man/255/org.freedesktop.systemd1.html),
[Cgroup v2](https://docs.kernel.org/admin-guide/cgroup-v2.html).

## 8. Bedrohungsmodell

| Gefahr | Geplante Kontrolle | Restgrenze / Abnahmetest |
| --- | --- | --- |
| Modelltext/Prompt-Injection | Alles untrusted; feste Policy, keine Autorität aus Antworttext | Fachliche Manipulation bleibt möglich; deterministische Tests zuerst |
| Shell-/Toolmissbrauch | Minimales Image, Tool-Allowlist, keine freien Startkommandos/Installationen | Freigegebene Tools führen untrusted Code aus; OS-Grenze praktisch testen |
| Fremddateien/Hostsecrets | Minimale Sicht, private Identität, keine Hostmounts/Config/SSH/FDs | Bind-/proc-/Unix-Socketfehler und Kernelbugs bleiben Risiken |
| Secret-Exfiltration | Keine Secrets in Sandbox; PrivateNetwork und feste Gateway-Operationen | Freigegebene Inputs erreichen den genehmigten Provider; Datenfreigabe erforderlich |
| Ausbruch aus Workspace | Read-only Inputs, begrenzte schreibbare Mounts, keine Caps/Namespaceerzeugung | Image-/Mount-/Symlink-Negativtests; kein Versprechen gegen Kernel-Exploits |
| Links/TOCTOU/Artefaktmanipulation | Stillstand, unabhängige Kopien, S3-dirfd-/Single-Link-/Inventarprüfungen | Übergabe zwischen UIDs/Dateisystemen ist neu zu prüfen |
| Hintergrundprozesse/Fork-Bomben | Cgroupzuordnung, TasksMax, KillMode, kein Restart/Delegation | Parentende allein reicht nicht; Doppel-Fork/setsid im späteren Test |
| CPU/RAM/Disk/Log-Erschöpfung | Quota/MemoryMax/TasksMax, CPU-Zähler, Deadline, begrenztes tmp/state/output | CPUQuota ist keine Gesamtdauer; Speicherdruck/Stopfehler testen |
| Prozess-/IPC-Verlust | Persistente IDs/Nonce/InvocationID/Boot-ID, externe Endprüfung | Unbekannt bleibt uncertain; kein automatischer Neuversuch |
| Resume-Races/Mehrfachstart | Exklusive Identitätsannahme und bestehender S3-Lock | Crash vor/nach Start und parallele Requests testen |
| Bewertungsmanipulation | Rubrics/Jury/Testprogramme außerhalb Agentenbereich, unveränderliche Rohbelege | Keine Selbstevaluation als Ergebnis; S5-Produktivfreigabe fehlt |
| Lieferkette/Executorfehler | Geschützte Installation, gepinnte Versionen, minimaler privilegierter Teil | Hash allein autorisiert nichts; gemeinsame Kernel-/Adminvertrauensgrenze bleibt |

systemd kann diese Grenzen konfigurieren und überwachen, beweist sie aber nicht
allein durch Unittext. Bei erhöhtem Risiko durch absichtlich feindlichen Code
ist eine separate VM/MicroVM als stärkere Kernelgrenze neu zu bewerten.

## 9. Vergleich und Entscheidung

Alle Varianten benötigen denselben nachgewiesenen Provider-, Identitäts-,
Artefakt- und Resume-Vertrag. Stand heute ist **keine** betriebsbereit abgenommen.

| Kriterium | A: Transient-Unit + eigener User | B: kontrollierter Executor-Dienst | C: bubblewrap + systemd | D: Rootless Podman |
| --- | --- | --- | --- | --- |
| Sicherheitsgrenze | Nur mit vollständigem Unitprofil/Root/UID-Trennung | Festes auditiertes Profil und getrennte Kontrolle; bevorzugt | Explizite Mount-/PID-/Net-Namespaces; Tool allein keine Policy | OCI-/Usernamespace-/Imagegrenze; Hostkernel bleibt gemeinsam |
| Ressourcen/Baum | systemd-Cgroup; zusätzliche sichere Steuerung nötig | systemd-Cgroup plus Receipts/Resume- und Endbelege | systemd ergänzend zwingend | Cgroupdelegation/Runtime/Containerbaum praktisch prüfen |
| Netzwerk | PrivateNetwork plus Gateway oder geprüfter Filter | PrivateNetwork plus festes Provider-Gateway | Net-Namespace plus dasselbe Gateway | network=none plus kontrollierter Providerpfad; Defaults ungeeignet |
| Betrieb | Einfacher Prototyp, hohe Gefahr freier Properties/CLI-Flags | Höherer einmaliger Protokoll-/Brokeraufwand, klare Betreibergrenze | Weiteres Werkzeug/AppArmor-Profil; zwei Ebenen pflegen | Runtime/Image-/Mapping-/Netzwerk-/Speicherpflege |
| Installation | systemd vorhanden; Identität/Image fehlen | systemd vorhanden; Dienst/geschütztes OpenCode/Image/Gateway fehlen | bwrap nicht gefunden; Installation und Usernsfreigabe prüfen | podman nicht gefunden; Runtime/UID-Maps/Rootlessvoraussetzungen prüfen |
| Ubuntu 24.04 | Grundfunktionen vorhanden, kein Unitnachweis | Geeignete vorhandene Grundfunktionen, Abnahme offen | AppArmor-Usernsbeschränkung relevant | AppArmor/Userns und Delegation relevant |
| Nachweisbarkeit | Jede Aufrufvariante neu zu kontrollieren | Ein versioniertes festes Profil mit standardisierten Receipts | Flags + Unit + AppArmor gemeinsam testen | OCI-Konfiguration/Image/Containerzustand dokumentieren |
| Engineintegration | Freie CLI ungeeignet als endgültige Grenze | Kleiner identitätsgebundener Adapter; keine duplizierte Engine | Weiterhin Executorprotokoll nötig | Weiterhin Executorprotokoll nötig, größte zusätzliche Plattform |

C ist eine mögliche spätere Ergänzung von B, falls ein eigener PID-Namespace oder
feinere Mountkontrolle erforderlich wird. D eignet sich bei bewusst gewünschtem
OCI-Imagebetrieb; ist auf diesem Host keine bereits verfügbare Alternative.
[bubblewrap](https://github.com/containers/bubblewrap) liefert Mechanismen,
keine fertige Sicherheitsrichtlinie. [Podman](https://docs.podman.io/en/latest/markdown/podman.1.html)
und [podman run](https://docs.podman.io/en/latest/markdown/podman-run.1.html)
benötigen kontrollierte Images/Rootless-Cgroups; automatische Pulls/Hostmounts und
Defaultnetze wären hier unzulässig. Für C/D Ubuntu-/AppArmorregeln eng freigeben,
nicht globale Usernamespace-Sicherheitsprüfungen deaktivieren.

**Begründung für B:** Vorhandene systemd-/Cgroup-/Kernelmechanismen sind eine
plausible Grundlage ohne zunächst eine weitere Containerplattform einzuführen.
Der fehlende dauerhafte Kontroll-/Autorisierungsvertrag wird explizit ergänzt.
PrivateNetwork mit Gateway vermeidet, die unbekannte IP-Filterwirksamkeit als
Voraussetzung für direkte Agentenverbindungen auszugeben. Dies ist ein konkreter
Zielentwurf, keine Aussage, dass die zusätzliche Implementierung bereits sicher ist.

## 10. Betreibermaßnahmen und notwendige Bereitstellung – nicht ausgeführt

1. Engen TST-Testauftrag und Ressourcen-/Datenfreigabe beschließen, vorhandene
   OpenCode-Nutzung durch Betreiber zuordnen; keine fremden Services übernehmen.
2. Geschütztes, nach Herkunft geprüftes OpenCode-Release und minimales versioniertes
   Root-Image mit festem Toolbestand bereitstellen. Derzeitige Home-Binary nicht
   als privilegierten Launcher oder veränderbare Paketquelle verwenden.
3. Eigene Executor-Dienstidentität und getrennte Worker-/Spoolregeln festlegen;
   Verwaltungsrechte nur für den fest geprüften Unittyp erlauben. Ein eventuell
   privilegierter kleiner Launcher ist separat zu auditieren. Kein freies sudo,
   kein beliebiges StartTransientUnit/ExecStart/Unit-Property-API für die Engine.
4. Außerhalb Home/Webroot neue Staging-/Receipt-/Gatewaybereiche einrichten,
   ohne Rechte vorhandener Homes, Enginearchive oder dicomat-Pfade zu ändern.
5. Gateway/Loopback-Bridge implementieren und separat abnehmen; erlaubtes Ollama-
   Ziel, Modell, Methoden, Budgets und optionaler DNS-/TLS-Vertrag durch Betreiber.
6. Geschütztes Unitprofil und Kontrollprotokoll installieren; Managerrechte für
   UID-/Mount-/Net-/Cgroupaufbau sind Betreiber-/Systemmanageraufgabe. Keine
   administrative Fähigkeit an Modellprozesse weiterreichen.
7. Nur falls gewählt: bubblewrap bzw. Podman samt konkret geprüften Abhängigkeiten/
   Profilen installieren. Für die bevorzugte Variante B ist keine dieser beiden
   Installationen vorab notwendig; erforderliche Image-/OpenCode-Abhängigkeiten
   sind noch zu inventarisieren. Vorhandenes Node ersetzt diese Prüfung nicht.

Keine dieser Aktionen ist durch diese Machbarkeitsprüfung freigegeben. Keine
Paket-, Benutzer-, Rechte-, Firewall-, AppArmor-, systemd- oder Deploymentänderung
wurde vorgenommen. Keine produktive Standortauswirkung wird behauptet.

## 11. Späterer konkreter Testplan und Stopppunkte

Nur nach gesonderter Freigabe, mit synthetischen Daten/Canaries und eng begrenzten
harmlosen Fixtures; keine realen Hostsecrets als Testeingabe. Zunächst ohne
OpenCode und ohne Provider, danach getrennte Freigaben für weitere Stufen.

| Stufe | Test / Prüfbeleg | Abbruchbedingung |
| --- | --- | --- |
| T0 Herkunft/Prerequisites | Vertrauenswürdige Binary-/Imagebelege, Profilhashes, UID-/Mount-/Cgroup-/Gatewaykonfiguration | Beschreibbare Installationsquelle, unbekannte Version oder Profilabweichung |
| T1 Einzel-Unit | Feste harmlose Fixture; EUID/Caps/NoNewPrivileges, Namespaces, Mounts, Cgroup- und InvocationID kontrollieren | Kontrollrecht zu breit oder fehlende Identität/Isolation |
| T2 Dateisystem | Canaries außerhalb Mounts, fremde Arbeitsräume, Dummy-Home/.ssh/.git/Journal-/Configpfade; Inputs nicht änderbar, Output nur privat | Lesen fremder Daten oder Schreiben außerhalb eigener Bereiche |
| T3 Links/Collection | Symlink/Hardlink/Spezialdateien, Dateiaustausch, große/zu viele Outputs, Wechsel während Übergabe | Annahme fremder/instabiler Dateien oder Collection bei laufenden Schreibern |
| T4 Netz ohne Provider | IPv4/IPv6/DNS/Hostloopback/Unix-/Abstract-Socket/FD-Umwege negativ; erlaubte Fake-Gatewaystrecke positiv | Irgendein ungewollter Egress, frei wählbare Origin/Port/Methoden |
| T5 Limits | Begrenzte CPU-/RAM-/PIDs-/Disk-/Logfixture; Drosselung, OOM, Deadline, Kosten aller Kinder messen | Unbegrenzter Verbrauch, Hoststörung, verwaiste Kinder |
| T6 Abbruch | Child/Grandchild, setsid, Parent-Exit 0, verzögertes Ende; vollständige Stopkette und populated=0 | Parentende als einziger Beleg, Cgroupescape oder fehlender Endnachweis |
| T7 Crash/Resume | Crash vor/nach Intent/Startantwort/Endbeleg/Archivcommit, IPC-Verlust, Unit-GC, Dienst-/Hostneustart und doppelte Startrequests | Neue Ausführung eines unklaren Slots oder verlorene Identitätszuordnung |
| T8 v2-Protokoll offline | Gepinnte Quellen/Fixtures für Events, Floats, Kosten/Tokenfelder, Sessions, Exit 1/130, Trunkierung, Mehrschrittverlauf | Unbekannte Varianten stillschweigend als Erfolg behandelt |
| T9 isolierter OpenCode-Test | Erst gesondert: privater Server und Fake-Provider, keine echte Modellverbindung; Payload-/Input-/Tool-/Sessionbindung und Kindprozesse messen | Zugriff auf Hostconfig/Altserver, Promptdrift, Auto-Fallback |
| T10 reales lokales Modell | Nochmals gesondert: ausdrückliche Provider-/Daten-/Budgetfreigabe; Modellidentität und externe Arbeitsruhe prüfen | Unbekannter Digest, Cloudfallback oder verlorener Providerabschluss |
| T11 Bewertung/Regression | S1–S6-Regression, unveränderte Altarchive, separate isolierte Testausführung und produktive Rubricfreigabe | Ergebnis-/Bewertungsmanipulation oder fehlende Belege |

Belege müssen auch bei Misserfolg erhalten bleiben. Bei Fehlern keine spontane
Abschwächung von ProtectHome/ProtectSystem/AppArmor/Netzregeln und kein Force-
Resume. Ein gescheiterter Isolationstest blockiert alle späteren Stufen.

## 12. Prüfung dieses Dokumentationskandidaten

`python3 -m unittest discover -s tests -q`: **456/456 erfolgreich, keine Skips**
(109.494 s). Bestehende Suite, keine neuen Test-/Runtime-/Schemaänderungen.
Hashbaseline, Git-Diff-/Whitespace-/Link-/Konsistenzprüfung sichern den Bestand;
lokale Prüfbelege bleiben ignoriert. Git-Dateisatz ist ausschließlich dieses
Dokument plus der S6-B-Verweis in ROADMAP.md. Kein Commit/Push/Deployment.

Offene Blocker: praktischer OS-Nachweis, geschütztes Binary/Image, enges
Executor-/Gatewayprotokoll, S3-Staging und versionierte Coding-/Wire-Verträge,
Modell-/Provideridentität, lokale und externe Endbelege sowie S5-Produktivfreigabe.
Die historische S6-A-Bestandsaufnahme bleibt unverändert; die jetzt vorhandene
Binary und Hilfe beseitigen keine ihrer Ausführungssperren. Unabhängige MCP-Prüfung
folgt; daraus ergibt sich keine automatische Installations-/Ausführungsfreigabe.
