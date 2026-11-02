# Synthetische Fixtures

profile.example.json ist ein Vertragsbeispiel, kein freigegebenes Startprofil.
Host-Mount-Namespace null lässt das aktive Gate geschlossen. Beispiel-UID/GID
sind keine Aussage über vorhandene Benutzer. Bei jedem Operatorlauf neue UUID,
passende echte IDs und aktuellen Namespace-/Zeitbeleg verwenden.

Der Betreiber stellt einen neuen, ausschließlich synthetischen Root bereit:

```text
marker.json           kind, profile_version=1, test_id, profile_sha256
profile.json          operatorgepinntes Testprofil
reference/canary.txt  llm-casting-isolation-canary:reference:TEST-UUID + LF
outside/canary.txt    llm-casting-isolation-canary:outside:TEST-UUID + LF
other/canary.txt      llm-casting-isolation-canary:other:TEST-UUID + LF
output/              eigener begrenzter Testausgabebereich
rootfs/              separat geprüftes minimales Python-Root-Dateisystem
```

Root/Marker/Profil und Referenz-/Negativcanaries gehören dem Betreiber/root;
nur output gehört der dedizierten Testidentität. Keine Kopien realer
Konfigurations-, Patienten-, SSH- oder Archivdaten. Keine Hard-/Symlinks in
Canary- und Profildaten. Testwerkzeuge erzeugen weder Benutzer noch Rootfs.

child.py führt nur dieselben Live-Gate-/Rootprüfungen durch, meldet PID/PPID/
Cgroup und schläft acht Sekunden. Kein Fork, Socket, Shellbefehl oder größerer
Speicherverbrauch. Es darf nur vom festen probe.py-Pfad in der Test-Unit
gestartet werden; eine direkte Ausführung außerhalb scheitert am Live-Gate.
