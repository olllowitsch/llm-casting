# Wettbewerbslauf – JSON-Vertrag v1 (Ziel v0.3+)

Verbindlicher Entwurf, noch kein neuer Runner. [Architektur](ARCHITECTURE.md),
[Wettbewerb](COMPETITION_CONTRACT.md), [Ergebnis](RESULT_CONTRACT.md),
[Roadmap](../ROADMAP.md). Hash-/JSON-Regeln gelten wie im Wettbewerbsvertrag.

## Unveränderlicher Plan

Ein Lauf besitzt eine UUID `run_id`. Sein Plan (`kind: run_plan`,
`schema_version: 1`) bindet `competition_id`, `definition_revision`,
`definition_sha256`, `prompt_version`, `prompt_sha256` und die Rubricreferenz.
Zusätzlich werden die vollständige Definition, Rubric und Eingabedateien im
privaten Archiv fixiert. Namen und aktuelle Dateipfade sind kein Ersatz dafür.

| Feld | Bedeutung |
| --- | --- |
| `engine` | Version und source_sha256 des vollständigen Engine-/Adapter-/Testadapter-Buildmanifests; vor Ausführung vollständig aufgelöst |
| `participants` | Nichtleere Liste eindeutiger Teilnehmer-UUIDs und vollständig aufgelöster Konfigurationen |
| `limits` | Positive ganze `request_timeout_seconds`, `attempt_deadline_seconds`, `run_deadline_seconds`; keine widersprüchlichen Budgets |
| `repetitions` | Positive ganze Zahl gemessener Versuche je Teilnehmer |
| `preparation` | `unload_before`, `preload`, nichtnegative `warmup_count`; Adapterfähigkeit prüfen |
| `policy` | Fixierte Limits `max_asset_bytes`, `max_artifact_bytes`, `max_files`, Boolean `network_allowed`; registriertes `isolation_profile` |

Jeder Teilnehmer enthält `participant_id`, `execution_adapter`,
`adapter_version`, `provider`, `model`, `parameters` und `hardware`.
`model` enthält `name` und einen unveränderlichen `revision_digest`. Ein Adapter
muss seine Modellidentität nachweisen; ohne nachweisbaren Digest/Snapshot bleibt
Planung möglich, Ausführung/Resume und bestätigte Vergleichbarkeit werden
verweigert. Adapterversionen werden vor Ausführung konkret aufgelöst.
`parameters` enthält wirksame, typisierte Werte statt impliziter Defaults;
Dezimalparameter als Dezimalstrings. Adapter bildet sie nachvollziehbar auf sein
Transportformat ab. Nicht unterstützte Optionen werden nicht still ignoriert.

`hardware` enthält die dokumentierte Zielhardware als `profile_id`,
`profile_revision` und `verified`. Bei unbekannter Hardware sind ID/Revision null
und verified=false; keine Ableitung aus Runner-Hostname oder Modellgeschwindigkeit.
Ein verifiziertes Profil benötigt einen archivierten, geprüften Inventarsnapshot
mit Inhaltshash. Lokale Hostpfade und Endpoints sind separate private Operator-
Konfiguration, keine portablen Planparameter. Mehrere Hardware-/Parameter-
konfigurationen desselben Modells sind getrennte Teilnehmer.

Ausführung bleibt zunächst sequenziell; keine neue Parallelitätszusage für v0.3.
network_allowed betrifft die Agenten-/Testumgebung. Der separat konfigurierte
Inferenztransport darf ausschließlich den explizit freigegebenen Providerendpunkt
ansprechen; daraus folgt keine freie Netzwerkberechtigung für Modellwerkzeuge.
Warmup/Vorladen werden getrennt von Messversuchen dokumentiert und nicht in die
Leistungsstatistik gemischt. Zeitbudgets schließen Vorbereitung ein, sofern das
jeweilige Gesamtbudget gilt; der Versuch darf das verbleibende Laufbudget nicht
überschreiten. Ein Requesttimeout ist keine bestätigte Prozessbeendigung.

## Planungsbeispiel

```json
{
  "kind": "run_plan",
  "schema_version": 1,
  "run_id": "22222222-2222-4222-8222-222222222222",
  "competition": {
    "competition_id": "11111111-1111-4111-8111-111111111111",
    "definition_revision": 1,
    "definition_sha256": "0038e746a42218336e3294860f2d3efff277465b1dc27987a07c2ff6986af030",
    "prompt_version": 1,
    "prompt_sha256": "7df1c900720fdbdecd6bde9c91460763f4900e2fb2991c4b83e9438ef24f84a6"
  },
  "rubric": {
    "rubric_id": "66666666-6666-4666-8666-666666666666",
    "revision": 1,
    "sha256": "1fa2b8558aa62edcb5466c85e5681f4753bd6ea72e69862e5699564e635f2f74"
  },
  "participants": [
    {
      "participant_id": "33333333-3333-4333-8333-333333333333",
      "execution_adapter": "ollama",
      "adapter_version": "planned-v1",
      "provider": "ollama",
      "model": {
        "name": "example-model",
        "revision_digest": null
      },
      "parameters": {
        "threads": 4,
        "gpu_mode": "cpu_only",
        "num_ctx": 16384,
        "think": false,
        "num_predict": 64,
        "seed": 42,
        "temperature": "0"
      },
      "hardware": {
        "profile_id": null,
        "profile_revision": null,
        "verified": false
      }
    }
  ],
  "limits": {
    "request_timeout_seconds": 300,
    "attempt_deadline_seconds": 600,
    "run_deadline_seconds": 1200
  },
  "repetitions": 1,
  "preparation": {
    "unload_before": true,
    "preload": true,
    "warmup_count": 1
  },
  "policy": {
    "max_asset_bytes": 10485760,
    "max_artifact_bytes": 104857600,
    "max_files": 1000,
    "network_allowed": false,
    "isolation_profile": "inference_only"
  },
  "engine": {
    "version": "planned-v0.3",
    "source_sha256": null
  }
}
```

Das Beispiel ist ein nicht ausführbarer Entwurf: Modell-Digest und Engine-Build
sind noch null. Die finale, vollständig gebundene Fassung erhält eine neue
run_id; bereits publizierte Laufpläne werden nicht in-place ergänzt. Engine-
source_sha256 bindet ein archiviertes vollständiges Quell-/Buildinventar mit
Dateihashes. Externe Werkzeugversionen und Executable-Hashes werden zusätzlich
in provenance gebunden und beim Resume geprüft.

Unbekannte Hardware im Beispiel ist ausdrücklich keine verifizierte Hardware-
vergleichsgruppe. Die Adapterversion bezeichnet das geplante Vertragsprofil,
keine Behauptung eines bereits verfügbaren Adapterpakets.

## Lauf, Versuche und Zustände

Der Plan wird nicht verändert. Ein separates Journal enthält `run_id`,
`plan_sha256`, fortlaufende Ereignisnummern und UTC-Zeitpunkte. Stabile Versuch-
Schlüssel sind `(participant_id, repetition)`; vor jedem realen Anlauf wird eine
neue UUID `attempt_id` mit Verweis auf diesen Schlüssel persistiert. Keine
Überschreibung alter Versuche bei einem ausdrücklich erlaubten neuen Anlauf.

Laufstatus: `planned` → `running` → `completed`; von running auch
`cancel_requested` → `cancelled` oder `interrupted`. `failed` bezeichnet einen
fatalen Lauf-/Archivfehler. `completed` bedeutet alle geplanten Messplätze terminal,
nicht alle erfolgreich. Einzeleingaben tragen `planned`, `running`, `succeeded`,
`failed`, `timed_out`, `cancelled` oder `uncertain`. Ein Fehler ist niemals Erfolg.
Ein Lauf mit offenen unklaren Operationen ist interrupted und nicht completed.

`interrupted` kann erst nach erneuter Verträglichkeits- und Stillstandsprüfung zu
running wechseln. Ein cancelled/completed/failed Lauf wird nicht automatisch
wieder geöffnet; eine ausdrückliche neue Serie verweist auf den Ursprung.
Definitiv fehlgeschlagene terminale Versuche werden beim Resume nicht wiederholt.
Die Zahl terminaler Messplätze wird von der Zahl gestarteter Anläufe getrennt.

## Workspace und sicherer Abbruch

Logische Struktur des neuen Archivs, noch keine existierenden Verzeichnisse:

```text
RUN_ID/
  plan.json, competition.json, rubric.json, journal.json, result.json
  inputs/...
  workspaces/PARTICIPANT_ID/ATTEMPT_ID/...
  artifacts/PARTICIPANT_ID/ATTEMPT_ID/...
  assessments/ASSESSMENT_ID.json
```

Workspaces werden frisch aus demselben geprüften Inputsnapshot erzeugt, niemals
zwischen Teilnehmern geteilt. Abgeleitete Pfade ausschließlich aus validierten
IDs und festen Segmenten; Browserpfade werden nicht akzeptiert. Artefakte werden
unter Größen-/Anzahllimits als normale Dateien übernommen; Traversal, Links,
Spezialdateien und Zugriffe außerhalb des erlaubten Roots werden abgewiesen.
Workspaces sind privat und keine Veröffentlichung. Kein automatisches rekursives
Löschen unbekannter Verzeichnisse. Archivierung folgt dem sicheren Ergebnisvertrag.

Abbruch persistiert die Absicht, sperrt neue Starts und fordert den Adapter zum
geordneten Ende auf. Prozessbaum-/Serverstillstand muss bestätigt werden.
Ist dies nicht möglich, bleibt der Versuch uncertain; spätere Teilnehmer werden
nicht unter womöglich weiterlaufender Fremdlast gestartet. Ein Sockettimeout
allein gibt keinen neuen Versuch frei. Gleiches gilt nach hartem Prozessverlust.

## Resume und Abgrenzung zum bestehenden Runner

Nur ein kooperierender Writer pro Lauf, nichtblockierender Lock, atomare
Publikation mit fsync und integritätsgeprüfte Originalbelege. Fortschritt aus
dauerhaften Versuchsdaten rekonstruieren, keine Doppelzählung durch alte Summen.
Vor Wiederaufnahme Plan-/Definitions-/Prompt-/Asset-/Rubric-Hashes, Engine- und
Adapterversionen, Modellidentität, Parameter und relevante private Zielbindung
prüfen. Der erste neue Vertrag verlangt exakte Version-/Inhaltsübereinstimmung;
spätere Migrationen müssen ausdrücklich versioniert sein.

Unklare Anläufe werden nicht als Erfolg rekonstruiert und nicht automatisch
wiederholt. Adapter muss ein vorhandenes Ergebnis idempotent identifizieren oder
den Stillstand bestätigen; danach ist ein explizit protokollierter neuer Anlauf
mit neuer attempt_id möglich. Ohne solche Evidenz bleibt Resume blockiert.

Das ist eine neue, strengere Agentenregel. Der heutige `benchmark.py` kann offene
Ollama-Intents erneut anfragen und verlangt vorherige serverseitige Ruhe vom
Betreiber. Diese bestehende Semantik wird in diesem Dokumentationsauftrag weder
geändert noch als hinreichende Coding-Agent-Resume-Garantie ausgegeben.

Pflichttests: Abbruch an jeder Persistenzgrenze, doppelte Resume-/Startanforderung,
wechselnder Digest/Plan/Prompt, beschädigte Belege, verbliebene Prozesse,
Antwort nach Timeout, neue Anlauf-ID ohne doppelte Messplatzwertung, keine
Wiederholung terminaler Fehler und keine Übernahme fremder Workspace-Dateien.
