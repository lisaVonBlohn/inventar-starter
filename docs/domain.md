```mermaid
erDiagram

    Mitarbeiter ||--o{ Ausleihen : hat
    Gerät  ||--o{ Ausleihen : wird_ausgeliehen     
    Mitarbeiter {
        int mitarbeiter_id PK
        string personalnummer UK
        string vorname
        string nachname
        string email 
        boolean aktiv
    }

    Gerät {
        int geraet_id PK
        string inventarnummer UK
        string geraetetyp
        string hersteller
        string modell
        string geraetename
        decimal netto_preis
        string seriennummer UK
        string status
    }

    Ausleihen {
        int ausleihe_id PK
        int mitarbeiter_id FK
        int geraet_id FK
        datetime ausleihdatum
        datetime rueckgabedatum
        string zustand_bei_ausgabe
        string zustand_bei_rueckgabe
        string bemerkung
    }
```
R1 – Höchstens eine aktive Ausleihe pro Gerät
Ein Gerät darf zu einem Zeitpunkt höchstens einer aktiven Ausleihe zugeordnet sein.

R2 – Keine Ausleihe nicht verfügbarer Geräte
Defekte oder ausgemusterte Geräte dürfen nicht neu ausgeliehen werden.

R3 – Nur ausleihberechtigte Mitarbeitende
Neue Ausleihen dürfen nur für aktive Mitarbeitende angelegt werden.

R4 – Plausible Zeitangaben
Das Ausleihdatum muss gesetzt sein. Falls ein Rückgabedatum vorhanden ist, darf es nicht vor dem Ausleihdatum liegen.

R5 – Historie erhalten
Abgeschlossene Ausleihen müssen für die Nachvollziehbarkeit erhalten bleiben. Eine erneute Ausleihe erzeugt einen neuen Datensatz.

R6 – Keine doppelte Inventarnummer
Jedes Gerät muss anhand seiner Inventarnummer eindeutig identifizierbar sein.

R7 – Stammdaten nicht unnötig duplizieren
Geräte- und Mitarbeiterinformationen werden in ihren Stammdatentabellen gepflegt und nicht bei jeder Ausleihe erneut gespeichert. Zustandsangaben, die sich auf einen konkreten Ausleihvorgang beziehen, gehören dagegen in die Ausleihe.