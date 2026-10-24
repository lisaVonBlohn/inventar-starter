import os
from decimal import Decimal

from fastapi import FastAPI, Request, HTTPException, Form, status
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse

from .db import get_conn
from .models import DeviceCreate, AssignmentCreate, AssignmentReturn
from .mqtt import (
    start_mqtt_listener,
    publish_device_issued,
    publish_device_returned,
    get_mqtt_client,
)

app = FastAPI(title="Inventar Starter", version="0.1.0")
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "templates"))


@app.on_event("startup")
def on_startup():
    start_mqtt_listener()


@app.get("/health")
async def health():
    db_state = "ok"
    mqtt_state = "ok"
    try:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
    except Exception as ex:
        db_state = f"error:{type(ex).__name__}"

    try:
        c = get_mqtt_client()
        c.disconnect()
    except Exception as ex:
        mqtt_state = f"degraded:{type(ex).__name__}"

    return {"status": "ok" if db_state == "ok" else "degraded", "db": db_state, "mqtt": mqtt_state}


@app.get("/", response_class=HTMLResponse)
async def index():
    return RedirectResponse(url="/inventory", status_code=303)


# =====================================================================
# HTML-VIEW: /inventory (F.1, F.2, F.3)
# =====================================================================
@app.get("/inventory", response_class=HTMLResponse)
async def inventory_page(request: Request):
    with get_conn() as conn, conn.cursor() as cur:
        # Dropdown: Gerätetypen
        cur.execute("SELECT geraetetyp_id, geraete_typ_bezeichnung FROM geraete_typ ORDER BY geraetetyp_id;")
        device_types = [{"geraetetyp_id": r[0], "geraete_typ_bezeichnung": r[1]} for r in cur.fetchall()]

        # Tabelle: Alle Geräte
        cur.execute("""
            SELECT g.geraete_id, g.geraete_name, gt.geraete_typ_bezeichnung,
                   g.hersteller, g.modell, g.seriennummer, g.standort, g.netto_preis, g.status
            FROM geraete g
            LEFT JOIN geraete_typ gt ON g.geraete_typ = gt.geraetetyp_id
            ORDER BY g.geraete_id;
        """)
        devices = [
            {
                "geraete_id": r[0],
                "geraete_name": r[1],
                "geraete_typ_bezeichnung": r[2],
                "hersteller": r[3],
                "modell": r[4],
                "seriennummer": r[5],
                "standort": r[6],
                "netto_preis": float(r[7]),
                "status": r[8],
            }
            for r in cur.fetchall()
        ]

        # Dropdown: Aktive Mitarbeiter
        cur.execute("SELECT personalnummer, vorname, nachname FROM mitarbeiter WHERE aktiv = TRUE ORDER BY nachname;")
        employees = [{"personalnummer": r[0], "vorname": r[1], "nachname": r[2]} for r in cur.fetchall()]

        # Dropdown: Freie Geräte
        cur.execute("SELECT geraete_id, geraete_name, seriennummer FROM geraete WHERE status = 'frei' ORDER BY geraete_name;")
        available_devices = [{"geraete_id": r[0], "geraete_name": r[1], "seriennummer": r[2]} for r in cur.fetchall()]

        # Tabelle: Aktive Ausleihen
        cur.execute("""
            SELECT a.ausleih_id, g.geraete_name, g.seriennummer, m.vorname, m.nachname, a.ausgabe_datum
            FROM ausleihe a
            JOIN geraete g ON a.geraete_id = g.geraete_id
            JOIN mitarbeiter m ON a.mitarbeiter_id = m.personalnummer
            WHERE a.rueckgabe_datum IS NULL
            ORDER BY a.ausgabe_datum DESC;
        """)
        active_assignments = [
            {
                "ausleih_id": r[0],
                "geraete_name": r[1],
                "seriennummer": r[2],
                "vorname": r[3],
                "nachname": r[4],
                "ausgabe_datum": str(r[5]),
            }
            for r in cur.fetchall()
        ]

    return templates.TemplateResponse(
        "inventory.html",
        {
            "request": request,
            "title": "Inventarverwaltung",
            "device_types": device_types,
            "devices": devices,
            "employees": employees,
            "available_devices": available_devices,
            "active_assignments": active_assignments,
        },
    )


# =====================================================================
# GERÄTE (Abschnitt E.1)
# =====================================================================
@app.get("/devices")
def get_devices():
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT * FROM geraete ORDER BY geraete_id;")
        columns = [col[0] for col in cur.description]
        return [dict(zip(columns, row)) for row in cur.fetchall()]


# 1. Pydantic-Route für /docs und JSON
@app.post("/devices", status_code=status.HTTP_201_CREATED)
def create_device_json(device: DeviceCreate):
    try:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("""
                INSERT INTO geraete (
                    geraete_typ, hersteller, modell, geraete_name, netto_preis, seriennummer, standort, status
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING geraete_id;
            """, (
                device.device_type_id,
                device.manufacturer,
                device.model,
                device.device_name,
                Decimal(str(device.net_price)),
                device.serial_number,
                getattr(device, "location", "Gebäude E"),
                device.status
            ))
            new_id = cur.fetchone()[0]
            conn.commit()
            return {"geraete_id": new_id}

    except Exception as exc:
        if getattr(exc, "sqlstate", None) == "23505" or getattr(exc, "pgcode", None) == "23505":
            raise HTTPException(status_code=409, detail="Diese Seriennummer existiert bereits.")
        raise


# 2. Formular-Route für das HTML-Template
@app.post("/devices/form")
def create_device_form(
    geraete_typ: int = Form(...),
    geraete_name: str = Form(...),
    hersteller: str = Form(...),
    modell: str = Form(...),
    seriennummer: str = Form(...),
    netto_preis: float = Form(...),
    standort: str = Form(...),
    status: str = Form("frei"),
    return_to: str = Form("/inventory"),
):
    try:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("""
                INSERT INTO geraete (
                    geraete_typ, hersteller, modell, geraete_name, netto_preis, seriennummer, standort, status
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s);
            """, (geraete_typ, hersteller, modell, geraete_name, Decimal(str(netto_preis)), seriennummer, standort, status))
            conn.commit()
        return RedirectResponse(return_to, status_code=303)
    except Exception as exc:
        if getattr(exc, "sqlstate", None) == "23505" or getattr(exc, "pgcode", None) == "23505":
            raise HTTPException(status_code=409, detail="Diese Seriennummer existiert bereits.")
        raise


# =====================================================================
# ASSIGNMENTS (Abschnitt E.2 & G)
# =====================================================================
@app.get("/assignments/active")
def get_active_assignments():
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT ausleih_id, mitarbeiter_id, geraete_id, ausgabe_datum, rueckgabe_datum
            FROM ausleihe
            WHERE rueckgabe_datum IS NULL
            ORDER BY ausleih_id;
        """)
        columns = [col[0] for col in cur.description]
        return [dict(zip(columns, row)) for row in cur.fetchall()]


# 1. Pydantic-Route für /docs
@app.post("/assignments", status_code=status.HTTP_201_CREATED)
def create_assignment_json(assignment: AssignmentCreate):
    return _process_create_assignment(assignment.person_id, assignment.device_id, assignment.issued_at)


# 2. Formular-Route für das HTML-Template
@app.post("/assignments/form")
def create_assignment_form(
    mitarbeiter_id: int = Form(...),
    geraete_id: int = Form(...),
    return_to: str = Form("/inventory"),
):
    _process_create_assignment(mitarbeiter_id, geraete_id, None)
    return RedirectResponse(return_to, status_code=303)


def _process_create_assignment(person_id: int, dev_id: int, issued_at):
    with get_conn() as conn, conn.cursor() as cur:
        # Prüfe Person
        cur.execute("SELECT aktiv FROM mitarbeiter WHERE personalnummer = %s;", (person_id,))
        person = cur.fetchone()
        if person is None or not person[0]:
            raise HTTPException(status_code=400, detail="Mitarbeiter fehlt oder ist inaktiv.")

        # Prüfe Gerät (IR-02)
        cur.execute("SELECT status FROM geraete WHERE geraete_id = %s FOR UPDATE;", (dev_id,))
        device = cur.fetchone()
        if device is None:
            raise HTTPException(status_code=404, detail="Gerät nicht gefunden.")
        if device[0].lower() != "frei":
            raise HTTPException(status_code=409, detail="Gerät ist nicht verfügbar.")

        # Ausleihe anlegen
        cur.execute("""
            INSERT INTO ausleihe (mitarbeiter_id, geraete_id, ausgabe_datum)
            VALUES (%s, %s, COALESCE(%s, CURRENT_DATE))
            RETURNING ausleih_id;
        """, (person_id, dev_id, issued_at))
        assignment_id = cur.fetchone()[0]

        # Status aktualisieren
        cur.execute("UPDATE geraete SET status = 'ausgeliehen' WHERE geraete_id = %s;", (dev_id,))
        conn.commit()

    # MQTT senden (G.2)
    publish_device_issued(assignment_id, person_id, dev_id)
    return {"ausleih_id": assignment_id}


# 1. Pydantic-Route für /docs
@app.post("/assignments/{id}/return")
def return_assignment_json(id: int, returned: AssignmentReturn):
    return _process_return_assignment(id, returned.returned_at)


# 2. Formular-Route für das HTML-Template
@app.post("/assignments/{id}/return-form")
def return_assignment_form(id: int, return_to: str = Form("/inventory")):
    _process_return_assignment(id, None)
    return RedirectResponse(return_to, status_code=303)


def _process_return_assignment(assignment_id: int, returned_at):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT geraete_id
            FROM ausleihe
            WHERE ausleih_id = %s AND rueckgabe_datum IS NULL
            FOR UPDATE;
        """, (assignment_id,))
        row = cur.fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Aktive Ausleihe nicht gefunden.")

        dev_id = row[0]

        cur.execute("""
            UPDATE ausleihe
            SET rueckgabe_datum = COALESCE(%s, CURRENT_DATE)
            WHERE ausleih_id = %s;
        """, (returned_at, assignment_id))

        cur.execute("UPDATE geraete SET status = 'frei' WHERE geraete_id = %s;", (dev_id,))
        conn.commit()

    # MQTT senden (G.2)
    publish_device_returned(assignment_id)
    return {"message": "Gerät erfolgreich zurückgegeben."}