# S6 – gesperrter OpenCode-Adapter und lokales Simulationsprofil

Status: **Teilumfang, keine produktive S6-Abnahme**. S5 und S6 bleiben insgesamt
offen. Keine Agenten, Coding-Tests, Provideranfragen oder Sandbox-Prozesse werden
gestartet. Nur Python-Standardbibliothek; kein zweiter Scheduler oder Journal.
Bestehende CLIs, normative S1/S2-Schemas, Golden-Fixtures und Archive bleiben erhalten.

## Bestand und lokale Verifikation

Basis: main, `62671c8`, zuvor 388 Tests. Analysiert: ROADMAP, ARCHITECTURE,
RUN_CONTRACT, RESULT_CONTRACT, S3_WORKSPACES, S4_OLLAMA_ADAPTER, S5_ASSESSMENT,
definitions.py, planning.py, workspaces.py, ollama_adapter.py und assessment.py.

Die passive PATH-Prüfung am 2026-11-02 fand weder opencode noch bwrap; systemd-run
ist vorhanden. Kein Programm davon wurde gestartet, nichts installiert. Das
belegt keine nutzbare Sandbox. S3 bestätigt weiterhin keine OS-Isolation.

**Vertragsblocker:** S1-Standardregistry und S2-v1-Teilnehmer unterstützen nur
performance/ollama; coding ist reserviert. Hier wird OpenCode weder als Ollama
ausgegeben noch der normative Validator erweitert. Das private S6-Profil nutzt
ausdrücklich synthetische Performance-Referenzpläne zum Prüfen der vorhandenen
Status-/Persistenzregeln. Es erstellt keinen produktiv gültigen Coding-Plan.
Eine versionierte Coding-/OpenCode-Planerweiterung muss separat geprüft werden.

## Dokumentierte OpenCode-Schnittstellen

Offizielle Dokumentation gelesen am 2026-11-02; ihre Onlinefassung ist veränderlich.
Die Recherche ist keine Prüfung eines installierten Binaries:

| Thema | Dokumentierter Stand | Grenze |
| --- | --- | --- |
| CLI | run nichtinteraktiv; --model verwendet provider/model; --format json liefert rohe JSON-Ereignisse | Kein CLI-Start, keine belegte Binaryversion |
| Sitzung | --session/--continue referenzieren Sitzungen | Session-ID ist kein Prozesskontrollbeleg |
| JSON | JSON-Ausgabe beschrieben | CLI-Seite spezifiziert kein vollständiges stabiles Eventschema mit Versionshandshake |
| Exit/Abbruch | CLI-/Sitzungsoptionen beschrieben | Keine daraus ableitbare vollständige Exitcodetabelle oder Garantie über Kindprozessende |

Quelle: [CLI](https://docs.opencode.ai/docs/cli/). Automatische Permission-
Freigaben wie --auto sind für den späteren kontrollierten Start nicht vorgesehen.
Exit 0 und Session-Ende gelten in der Engine nicht als vollständiger Endbeleg.

Konfigurationen werden aus mehreren Quellen zusammengeführt; ein eigener
Configpfad allein schließt globale/Projektwerte nicht aus. Provider-Allow-/
Denylists und Variablensubstitution sind dokumentiert. Später muss die effektive
Konfiguration samt Umgebung/Plugins kontrolliert werden.
Quelle: [Config](https://docs.opencode.ai/docs/config/).

Permissions unterscheiden allow/ask/deny, besitzen permissive Defaults und können
durch Agentenregeln überlagert werden. Diese Anwendungsregeln ersetzen keine
OS-Isolation. Vorgesehen: deny als Ausgangspunkt, explizite Toolfreigaben;
interaktive Nachfragen niemals automatisch als Zustimmung behandeln.
Quelle: [Permissions](https://docs.opencode.ai/docs/permissions/).

Lokales Ollama ist als expliziter Provider mit OpenAI-kompatiblem Endpunkt und
benannten Modellen dokumentiert. Credentials/Providerkonfiguration sind weitere
Quellen; der Modellname allein beweist weder lokalen Provider noch Modelldigest.
Hier gibt es keine Anmeldung oder Credential-Verwaltung.
Quelle: [Providers](https://docs.opencode.ai/docs/providers/).

## Protokoll-/Versionsvertrag dieses Teilumfangs

`casting-opencode-simulation-v1` ist ein **eigenes normalisiertes Fixture-Profil**,
keine OpenCode-Version und kein verifiziertes OpenCode-Wire-Schema. decode_events
nimmt abgegrenzte UTF-8-JSON-Frames als tuple[bytes] entgegen, keinen Prozessstream.
Ein echter Wire-Decoder und seine Übersetzung sind noch nicht implementiert.

Ein Frame enthält ausschließlich:

```json
{
  "profile": "casting-opencode-simulation-v1",
  "sequence": 2,
  "type": "completed",
  "session_id": "ses_fixture",
  "data": {}
}
```

Sequenzen beginnen bei 1, die Session bleibt versuchsgebunden konstant. started
ist das erste Event mit provider, model, model_digest und binding_sha256. Weitere
Typen: text mit text; tool mit capability/area/path; completed mit leerem data;
error mit begrenztem Code. Nach completed/error folgen keine weiteren Events.
Toolereignisse sind symbolische Anforderungen und führen niemals Tools aus.

Limits: 64 KiB je Frame, 128 Frames, 512 KiB Rohframes insgesamt plus bestehende
S1-Limits für Tiefe/Knoten/Strings/Integer. Doppelte Schlüssel, ungültiges UTF-8,
BOM, Floats, NaN, unbekannte Felder/Typen/Versionen und Reihenfolgefehler werden
abgewiesen. Kosten-/Leistungsfloats eines späteren Wireformats benötigen eine
gesonderte geprüfte Abbildung. Verworfene Streams begründen keinen Erfolg.

Spätere Freigabe benötigt konkrete OpenCode-Version, vertrauenswürdigen
Installationsbeleg/Executablehash, aufgezeichnete Fixtures dieser Version,
vollständige Event-/Fehler-/Exit-Abbildung, begrenztes Streamframing und bewiesene
Session-/Abbruchsemantik. Inkompatible Änderungen erhalten neue Profilversionen.
upstream_binary_version bleibt hier null; keine Versionskompatibilität behaupten.

## Öffentliche Python-API

| opencode_adapter.py | Wirkung |
| --- | --- |
| safety_gate() | Nur Lesedaten; executable=false, Isolation/Binaryversion/Coding-Pläne nicht akzeptiert |
| execute(...), request_cancel(...) | Immer DefinitionError(opencode_execution_disabled), auch mit force/unsafe/enable/isolation_verified |
| build_manifest() | Hashinventar von Adapter/S1/S2/S3; kein Installations-/Isolationsbeleg |
| bind(reference_plan, identity, config) | Gepinnter, nicht ausführbarer Simulationsauftrag |
| decode_events(frames, binding) | Strikte normalisierte Ereignisprüfung ohne Tools/I/O |
| FakeEnd, FakeTransport | Lokale Testdaten; keine Callbacks, Executables oder Liveverbindungen |
| OpenCodeAdapter(store, reference_plan) | Ein Versuch auf vorhandenem S3-Store, kein Scheduler |
| prepare(identity, config, asset_root=..., rubric_asset_root=...) | S1/S2-Bindung, S3-Inputkopien und private binding.json |
| simulate(identity, config, transport) | Persistierte Absicht, Fake-Auswertung, S3-Archiv und S2-Statusprojektion |
| project(expected_head=None) | Lesende Rekonstruktion mit simulation_only-Wrapper und optionalem externen Journalpin |

Kein neuer Ausführungs-CLI-Schalter, keine Integration in casting.py. Live-
Transporte und FakeTransport-Unterklassen werden abgewiesen. Die Fake-Klassen
sind ein Testvertrag, keine Autorisierungsgrenze gegen bereits vertrauenswürdigen
Python-Code mit denselben Benutzerrechten im Engine-Prozess.

### Referenzplan, Provider, Policy und Fairness

create_run_plan erstellt unverändert den synthetischen S2-Referenzplan. Er muss
engine.version=s6-simulation-only, source_sha256 des aktuellen build_manifest,
bei allen Teilnehmern adapter_version=s6-reference-only und einen expliziten
**Fixture**-Modelldigest besitzen. Das sind keine vermessenen Providerbelege.
Andere Pläne werden vor jeder Simulation zurückgewiesen. Das vollständige
engine_build-Inventar wird im Binding archiviert; model_selector enthält die
explizite provider/model-Angabe, ohne daraus einen Prozessbefehl zu erzeugen.

Private config enthält exakt profile, provider, model, model_digest, endpoint,
tools, network, resources. Nur provider=ollama, planidentischer Modellname/Digest
und expliziter HTTP-Loopback-IP-Endpunkt mit Port und /v1 sind zugelassen
(Beispiel http://127.0.0.1:11434/v1). Keine URL-Credentials, Query/Fragment,
DNS-Namen oder Cloud-Fallbacks. Der Endpunkt wird nicht kontaktiert. Keine
Environment-Defaults, Auth- oder Konfigurationsdateien werden gelesen.
Das Eventecho bestätigt nur die Fake-Bindung, keine reale Provideridentität.

network muss deny sein. tools ist eine explizite Teilmenge von read_reference und
write_output: eigene Simulationsbegriffe, keine Zusage gleichnamiger OpenCode-
Tools. Pfade sind nur symbolische relative Input-/Outputnamen. Hostbereiche,
Traversal, versteckte Dateien, SSH-/Config-/Secret-/Journalbereiche und unbekannte
Inputs sind verboten. Eventpfade werden nie geöffnet, Shell-/Netzwerktools nie
ausgeführt. Ein Workspace ist keine Freigabe an einen Agenten.

resources enthält positive Integer cpu_seconds, memory_bytes, wall_seconds.
wall_seconds ist zusätzlich durch Versuch-/Laufdeadline begrenzt. Übrige Limits
und Modellparameter sind über plan_sha256 gebunden. OS-Durchsetzung dieser Werte
ist ausdrücklich nicht implementiert und später zwingend abzunehmen.

Wettbewerb, Disziplin, Definitionsrevision, Promptversion/-hash, gemeinsamer Prompt
und Assetinventar sind gepinnt; S3 prüft die tatsächlichen Eingabebytes. Teilnehmer
und Wiederholungen besitzen getrennte S3-Identitäten/Arbeitsbereiche. Abweichende
technische Parameter und Toolfähigkeiten bleiben in der privaten Binding-
Provenienz sichtbar. Keine Promptumschreibung oder zusätzliche Teilnehmerhilfe.

## Persistenz, Status und Wiederanlauf

Vorhandene S3-Workspaces und exklusiver Store-Lock bleiben zuständig. Im privaten
outputs-Bereich des synthetischen Versuchs entstehen ausschließlich binding.json,
start-intent.json und observation.json. Verwendet werden S3-dirfd-/No-Follow-/
Single-Link-/No-Replace-/fsync-Primitiven, Collectionmanifest und unverändertes
hashverkettetes Journal. Kein zweites Journal und keine Ergebnisüberschreibung.

| Fachlicher Zustand | Vorhandener Vertrag / Beleg |
| --- | --- |
| geplant/vorbereitet | S3 planned → prepared; S2-Versuch planned |
| Startabsicht | start-intent.json vor Fake-Auswertung dauerhaft publiziert |
| Start bestätigt/laufend | started im Fake-Trace; kein echtes S3 active oder Startrecht |
| Ende bestätigt | Separate FakeEnd-Testvorgabe: gesamter Baum stopped, Exitcode vorhanden; passendes Terminalevent für Erfolg |
| unbekannt | S2 uncertain, Lauf interrupted, keine finished_at-Zeit; keine neue Ausführung |
| Artefakte übernommen | S3 collecting → archived; archived ist kein Ausführungserfolg |
| abgeschlossen | S2 succeeded/failed/timed_out/cancelled; completed nur bei terminalen Slots |

Bei uncertain bezeichnet started_at konservativ den Zeitpunkt der Startabsicht,
also den frühestmöglichen Beginn, keinen bestätigten Start. Ein belegter Fehler
vor Start wird cancelled mit Fehlerbeleg und ohne started_at projiziert, da S2
failed einen Start verlangt. Das zählt niemals als erfolgreiche Messung.
Alle neun Messwerte bleiben null; keine erfundenen Tokens/s.

Timeout/Abbruchwunsch ohne Baumende bleiben uncertain. Ebenso Parent-Exit 0 mit
verbleibenden Kindern, unbekannter Baum, Kontaktverlust, Fehler nach Startabsicht
oder verlorene Abschlussbestätigung. Session-ID ist kein Kontrollbeleg. Erneute
Projektion eines validierten Archivs verbraucht keinen Transport und zählt nicht
doppelt. Ungewisse Slots starten nicht neu; auch schon vorbereitete andere Slots
bleiben bei ungeklärter Arbeit gesperrt.

Nach Abbruch zwischen Absicht und vollständig validierter Archivierung gibt es
keine automatische Fortsetzung oder Neuausführung. Ein vollständiger, nach
Neustart verifizierter S3-Commit kann gelesen werden. Halbe Collection, temporäre
Dateien, fehlende Bindings oder beschädigte Belege bleiben gesperrt oder ergeben
Validierungsfehler. Keine automatische Bereinigung.

Die Projektion enthält zwingend profile, simulation_only=true, executable=false
und einen S2-validierten result; journal_head_sha256 kann außerhalb des Stores
als Vertrauenspin aufbewahrt und beim Lesen mit expected_head geprüft werden.
Sie ist **kein produktives OpenCode-Ergebnis**
und darf nicht als Benchmark/Agentenleistung benotet/importiert werden. Der innere
Referenzplan ist ein Performance-Fixture, kein falsch deklarierter Coding-Plan.
S4/S5 akzeptieren diesen Build-/Adaptervertrag nicht als reale S4-Quelle.

Binding, Intent, geprüfte Events, Fehler, Fake-Endvorgabe und S3-Manifest sind
persistente private Provenienz. Fehlerhafte Rohframes werden nicht als gültige
Events gespeichert, ihr Ausgang bleibt uncertain. Hashes sind lokale
Integritätsbindungen, keine Signaturen gegen einen Store-Schreibberechtigten.
Prompt, Endpoint und Modelltext gehören nicht in öffentliche Reports.

## Künftiger Executorvertrag – Entwurf, nicht implementiert

Der Kontrollkanal muss authentisiert und vom nicht vertrauenswürdigen stdout
getrennt sein. Keine frei wählbaren Kommandos oder ungeprüften Hostpfade:

1. **accept/start:** Auftrags-, Plan-, Binding-, Inputhashes, Executorprofil,
   Binary-/Configbelege, neue Sandboxidentität und Budget binden; Intent vor Start.
2. **inspect:** Handle nach Neustart eindeutig zuordnen. PID allein genügt wegen
   Wiederverwendung nicht; Session und Sandbox-/Cgroupidentität müssen passen.
3. **cancel:** Identitätsgebundene Anforderung; graceful, anschließend budgetierter
   kompletter Baumabbruch. Request-Ack bleibt cancel_requested bis zum Endbeleg.
4. **attest_end:** Prozess-/Cgroupstillstand einschließlich Kinder, Exitursache,
   Budgetverbrauch und Kontrollkanalintegrität nachweisen. Unklar bleibt uncertain.
5. **collect:** Erst nach bewiesenem Ende begrenztes privates Outputinventar mit
   S3 übernehmen; keine Links/Spezialdateien/fremden Dateien/nachträglichen Schreiber.
   Originaljournale, Inputs und Archive bleiben unverändert.

Abzunehmende Eigenschaften:

| Grenze | Erforderlicher Nachweis |
| --- | --- |
| Identität | Getrennte effektive Prozessidentität/Namespaces, keine Eskalation oder geerbten Kontroll-FDs |
| Dateisystem | Minimale Sicht, private schreibbare Outputs, unveränderliche Inputs; keine Host-SSH-/Config-/Secrets, fremden Workspaces, Engine-Journale oder Originalarchive |
| Netzwerk | Standardmäßig gesperrt; nur separat genehmigter Providerpfad, keine Credential-/Cloud-/DNS-/Proxy-Fallbacks oder Tool-Egress |
| Ressourcen | Harte CPU-/RAM-/Prozesszahl-/Zeitgrenzen einschließlich Nachkommen, unabhängig von CLI-Angaben |
| Tools/Config | Effektive Allowlist; private Home-/Config-/Cachebereiche, keine Hostplugins/MCP/LSP-Downloads/Projekt-Skripte/automatischen Installationen |
| Abbruch/Resume | Vollständige Baum-/Cgroupkontrolle und nachweisbare Arbeitsruhe, konservativ bei verlorenem Kontrollkanal |

Kandidaten sind eine geprüfte Namespace-/Sandboxlösung (z.B. bubblewrap mit
ergänzender Ressourcen-/Cgroupkontrolle), restriktive systemd-Unit oder isolierter
Container/VM. Keiner ist hier ausgewählt oder als verfügbar/ausreichend abgenommen.
Verzeichnisrechte, Python-Prozessgruppe, UID-Gleichheit, vorhandenes systemd-run
und Booleans belegen keine Isolation. execute bleibt auch dann gesperrt, wenn ein
Aufrufer deren Erfüllung behauptet. Freigabe benötigt geprüften Code und Auftrag.

## Tests und offene Betriebsabnahme

```bash
python3 -m unittest discover -s tests -p test_opencode_adapter.py -v
python3 -m unittest discover -s tests -v
```

Alle S6-Tests sperren HTTP-/Socketfunktionen, Popen, Fork/Spawn/Exec und os.system.
FakeTransport ist speicherbasiert; keine Hilfsprozesse notwendig. Geprüft werden
Protokoll-/Provider-/Prompt-/Input-/Planbindung, Grenzen, Host-/Toolablehnung,
getrennte Workspaces, Kinder, Timeout/Cancel/Kontaktverlust, Persistenzabbrüche,
konservatives Resume, Artefaktintegrität und idempotente S2-Projektion.

**Fake-Nachweis:** lokale Daten-/Status-/Persistenzlogik. **Vertragsprüfung:**
S1/S2/S3 plus privates Profil. **Reale Betriebsabnahme:** keine.
Offen: Coding-Planprofil, Wire-Decoder mit gepinntem Binary, Provider-/Modellbelege,
isolierter Executor mit harten Limits, Baumende/Recovery, sichere reale Artefakte,
produktive Rubrics/Testpakete. Keine Modell-, Agenten-, Cloud-, systemd- oder
Deploymentoperation ist Teil dieser Tests. Unabhängige MCP-Prüfung vor Freigabe.

Lokaler Kandidatennachweis: 68 S6-Tests plus 388 bestehende Tests, **456/456
erfolgreich, keine Skips**. Syntaxprüfung aller 19 Python-Quell-/Testdateien und
Whitespace-/Konflikt-/Secretprüfung erfolgreich. Der Hashvergleich mit dem
Arbeitsbeginn bestätigt unveränderten Bestands-Laufzeitcode, bisherige Tests,
Schemas, Golden-Fixtures und vorhandene Archive. Dies ersetzt keine Betriebsabnahme.
