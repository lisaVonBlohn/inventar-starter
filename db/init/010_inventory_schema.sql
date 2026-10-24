-- TODO: Inventar-Schema für Tag 3
--
-- Legt hier euer Datenmodell für die Inventar-App an.
-- Vorschlag für die Reihenfolge:
--   1. Stammdaten-Tabellen (department, person, device_type, location)
--   2. device
--   3. assignment
--
-- Ergänzt anschließend kleine Seed-Daten, damit ihr eure Flows testen könnt.

CREATE TABLE IF NOT EXISTS abteilung (
    abteilungs_id SERIAL PRIMARY KEY,
    bezeichnung TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS geraete_typ (
    geraetetyp_id SERIAL PRIMARY KEY,
    geraete_typ_bezeichnung TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS mitarbeiter (
    personalnummer SERIAL PRIMARY KEY,
    vorname TEXT NOT NULL,
    nachname TEXT NOT NULL,
    abteilung_id INT NOT NULL REFERENCES abteilung(abteilungs_id) ON DELETE CASCADE,
    email TEXT NOT NULL UNIQUE,
    standort TEXT NOT NULL,
    aktiv BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS geraete (
    geraete_id SERIAL PRIMARY KEY,
    geraete_typ INT NOT NULL REFERENCES geraete_typ(geraetetyp_id),
    hersteller TEXT NOT NULL,
    modell TEXT NOT NULL,
    geraete_name TEXT NOT NULL,
    netto_preis NUMERIC(10, 2) NOT NULL, 
    seriennummer TEXT UNIQUE NOT NULL,   
    status TEXT NOT NULL                
);

CREATE TABLE IF NOT EXISTS ausleihe (
    ausleih_id SERIAL PRIMARY KEY,
    mitarbeiter_id INT NOT NULL REFERENCES mitarbeiter(personalnummer) ON DELETE CASCADE,
    geraete_id INT NOT NULL REFERENCES geraete(geraete_id) ON DELETE CASCADE,
    ausgabe_datum DATE NOT NULL DEFAULT CURRENT_DATE,
    rueckgabe_datum DATE,
    CONSTRAINT chk_rueckgabe_nach_ausgabe CHECK (rueckgabe_datum IS NULL OR rueckgabe_datum >= ausgabe_datum)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_eine_aktive_ausleihe_pro_geraet 
ON ausleihe (geraete_id) 
WHERE rueckgabe_datum IS NULL;

INSERT INTO geraete_typ (geraetetyp_id, geraete_typ_bezeichnung) VALUES
    (1, 'Laptop'),
    (2, 'Monitor'),
    (3, 'Handscanner')
ON CONFLICT (geraete_typ_bezeichnung) DO NOTHING;

INSERT INTO abteilung (abteilungs_id, bezeichnung) VALUES
    (1, 'IT-Support'),
    (2, 'Logistik'),
    (3, 'Entwicklung')
ON CONFLICT (abteilungs_id) DO NOTHING;

INSERT INTO mitarbeiter (personalnummer, vorname, nachname, abteilung_id, email, standort, aktiv) VALUES
    (1001, 'Max', 'Mustermann', 1, 'max.mustermann@example.com', 'Gebäude E', TRUE),
    (1002, 'Erika', 'Musterfrau', 2, 'erika.musterfrau@example.com', 'Gebäude F', TRUE),
    (1003, 'Lukas', 'Schmidt', 3, 'lukas.schmidt@example.com', 'Gebäude H', TRUE),
    (1004, 'Anna', 'Meier', 1, 'anna.meier@example.com', 'Gebäude E', FALSE)
ON CONFLICT (personalnummer) DO NOTHING;

INSERT INTO geraete (geraete_id, geraete_typ, hersteller, modell, geraete_name, netto_preis, seriennummer, standort, status) VALUES
    (1, 1, 'Lenovo', 'ThinkPad T14 Gen 4', 'NB-IT-01', 1250.00, 'SN-LNV-001', 'Gebäude E', 'ausgeliehen'),
    (2, 1, 'Apple', 'MacBook Pro 14 M3', 'NB-DEV-01', 1999.00, 'SN-APL-002', 'Gebäude H', 'frei'),
    (3, 2, 'Dell', 'UltraSharp U2723QE', 'MON-01', 520.50, 'SN-DEL-101', 'Gebäude E', 'frei'),
    (4, 3, 'Zebra', 'DS2208 2D-Scanner', 'SCN-LOG-01', 189.90, 'SN-ZEB-501', 'Gebäude F', 'ausgeliehen')
ON CONFLICT (geraete_id) DO NOTHING;

INSERT INTO ausleihe (ausleih_id, mitarbeiter_id, geraete_id, ausgabe_datum, rueckgabe_datum) VALUES
    (1, 1001, 2, '2026-03-01', '2026-03-15'),
    (2, 1001, 1, '2026-04-01', NULL),
    (3, 1002, 4, '2026-04-10', NULL)
ON CONFLICT (ausleih_id) DO NOTHING;

SELECT setval(pg_get_serial_sequence('abteilung', 'abteilungs_id'), coalesce(max(abteilungs_id), 1)) FROM abteilung;
SELECT setval(pg_get_serial_sequence('geraete_typ', 'geraetetyp_id'), coalesce(max(geraetetyp_id), 1)) FROM geraete_typ;
SELECT setval(pg_get_serial_sequence('mitarbeiter', 'personalnummer'), coalesce(max(personalnummer), 1)) FROM mitarbeiter;
SELECT setval(pg_get_serial_sequence('geraete', 'geraete_id'), coalesce(max(geraete_id), 1)) FROM geraete;
SELECT setval(pg_get_serial_sequence('ausleihe', 'ausleih_id'), coalesce(max(ausleih_id), 1)) FROM ausleihe;
