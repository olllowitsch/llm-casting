# S2 Golden-Fixtures – nur synthetische Vertragsdaten

Keine Datei enthält echte Modellantworten oder gemessene Benchmarkwerte.
config.json erzeugt run-plan.json aus den S1-Fixtures und ihren echten Inputhashes.
initial-result.json ist ein leerer geplanter Stand. resolved-plan.json hat eine
andere Run-ID; a-/b-Hexwerte sind ausdrücklich synthetische Modell-/Buildpins.
synthetic-completed-result.json ist ein manuell konstruierter, strukturell gültiger
Beleg mit unbekannten Metriken, keine Behauptung einer tatsächlich erfolgten Inferenz.

Jede in vectors.json genannte Datei besitzt eine .canonical.json-Fassung mit
exakten UTF-8-Bytes ohne letzten Zeilenumbruch. Ihre Hashes müssen mit den Funktionen
in definitions.py übereinstimmen. unicode-vector.json prüft Codepoint-Sortierung
und fehlende Normalisierung; integer-vector.json schützt Werte oberhalb von 2^53.
Spätere TypeScript-/dicomat-Implementierungen müssen diese Bytes verlustfrei
reproduzieren, nicht nur ungefähr gleiche Number-Werte oder Objektschlüssel.
