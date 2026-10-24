import os
import json
from decimal import Decimal
from typing import Optional

from fastapi import FastAPI, Request, HTTPException, Form, Query
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

@app.get("/inventory", response_class=HTMLResponse)
async def inventory_page(request: Request):
    with get_conn() as conn, conn.cursor() as cur:
        # Gerätetypen für Dropdown
        cur.execute("SELECT geraetetyp_id, geraete_typ_bezeichnung FROM geraete_typ ORDER BY geraetetyp_id;")
        device_types = [{"geraetetyp_id": r[0], "geraete_typ_bezeichnung": r[1]} for r in cur.fetchall()]

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

        # Aktive Mitarbeiter für Dropdown
        cur.execute("SELECT personalnummer, vorname, nachname FROM mitarbeiter WHERE aktiv = TRUE ORDER BY nachname;")
        employees = [{"personalnummer": r[0], "vorname": r[1], "nachname": r[2]} for r in cur.fetchall()]

        # Nur freie Geräte für Ausgabe-Dropdown
        cur.execute("SELECT geraete_id, geraete_name, seriennummer FROM geraete WHERE status = 'frei' ORDER BY geraete_name;")
        available_devices = [{"geraete_id": r[0], "geraete_name": r[1], "seriennummer": r[2]} for r in cur.fetchall()]

        # Aktive Ausleihen auflisten
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

@app.get("/devices")
def get_devices():
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT * FROM geraete ORDER BY geraete_id;")
        columns = [col[0] for col in cur.description]
        return [dict(zip(columns, row)) for row in cur.fetchall()]


@app.post("/devices", status_code=201)
def create_device(
    request: Request,
    geraete_typ: Optional[int] = Form(None),
    geraete_name: Optional[str] = Form(None),
    hersteller: Optional[str] = Form(None),
    modell: Optional[str] = Form(None),
    seriennummer: Optional[str] = Form(None),
    netto_preis: Optional[float] = Form(None),
    standort: Optional[str] = Form(None),
    status: Optional[str] = Form("frei"),
    return_to: Optional[str] = Form(None),
    json_device: Optional[DeviceCreate] = None,
):
    typ = geraete_typ if json_device is None else json_device.device_type_id
    name = geraete_name if json_device is None else json_device.device_name
    herst = hersteller if json_device is None else json_device.manufacturer
    mod = modell if json_device is None else json_device.model
    sn = seriennummer if json_device is None else json_device.serial_number
    preis = netto_preis if json_device is None else json_device.net_price
    std = standort if json_device is None else getattr(json_device, "location", "Gebäude E")
    stat = status if json_device is None else json_device.status

    try:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("""
                INSERT INTO geraete (
                    geraete_typ, hersteller, modell, geraete_name, netto_preis, seriennummer, standort, status
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING geraete_id;
            """, (typ, herst, mod, name, Decimal(str(preis)), sn, std, stat))
            new_id = cur.fetchone()[0]
            conn.commit()

        if return_to:
            return RedirectResponse(return_to, status_code=303)
        return {"geraete_id": new_id}

    except Exception as exc:
        if getattr(exc, "sqlstate", None) == "23505" or getattr(exc, "pgcode", None) == "23505":
            raise HTTPException(status_code=409, detail="Diese Seriennummer existiert bereits.")
        raise

@app.get("/assignments/active")
def get_active_assignments():
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT a.ausleih_id, a.mitarbeiter_id, a.geraete_id, a.ausgabe_datum, a.rueckgabe_datum
            FROM ausleihe AS a
            WHERE a.rueckgabe_datum IS NULL
            ORDER BY a.ausleih_id;
        """)
        columns = [col[0] for col in cur.description]
        return [dict(zip(columns, row)) for row in cur.fetchall()]


@app.post("/assignments", status_code=201)
def create_assignment(
    mitarbeiter_id: Optional[int] = Form(None),
    geraete_id: Optional[int] = Form(None),
    return_to: Optional[str] = Form(None),
    json_assignment: Optional[AssignmentCreate] = None,
):
    person_id = mitarbeiter_id if json_assignment is None else json_assignment.person_id
    dev_id = geraete_id if json_assignment is None else json_assignment.device_id
    issued_at = None if json_assignment is None else json_assignment.issued_at

    try:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT aktiv FROM mitarbeiter WHERE personalnummer = %s;", (person_id,))
            person = cur.fetchone()
            if person is None or not person[0]:
                raise HTTPException(status_code=400, detail="Mitarbeiter fehlt oder ist inaktiv.")

            cur.execute("SELECT status FROM geraete WHERE geraete_id = %s FOR UPDATE;", (dev_id,))
            device = cur.fetchone()
            if device is None:
                raise HTTPException(status_code=404, detail="Gerät nicht gefunden.")
            if device[0].lower() != "frei":
                raise HTTPException(status_code=409, detail="Gerät ist nicht verfügbar.")

            cur.execute("""
                INSERT INTO ausleihe (mitarbeiter_id, geraete_id, ausgabe_datum)
                VALUES (%s, %s, COALESCE(%s, CURRENT_DATE))
                RETURNING ausleih_id;
            """, (person_id, dev_id, issued_at))
            assignment_id = cur.fetchone()[0]

            cur.execute("UPDATE geraete SET status = 'ausgeliehen' WHERE geraete_id = %s;", (dev_id,))
            conn.commit()

        publish_device_issued(assignment_id, person_id, dev_id)

        if return_to:
            return RedirectResponse(return_to, status_code=303)
        return {"ausleih_id": assignment_id}

    except HTTPException:
        raise
    except Exception as exc:
        if getattr(exc, "sqlstate", None) == "23505" or getattr(exc, "pgcode", None) == "23505":
            raise HTTPException(status_code=409, detail="Gerät hat bereits eine aktive Ausleihe.")
        raise


@app.post("/assignments/{assignment_id}/return")
def return_assignment(
    assignment_id: int,
    return_to: Optional[str] = Form(None),
    returned: Optional[AssignmentReturn] = None,
):
    ret_date = None if returned is None else returned.returned_at

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT geraete_id, ausgabe_datum
            FROM ausleihe
            WHERE ausleih_id = %s AND rueckgabe_datum IS NULL
            FOR UPDATE;
        """, (assignment_id,))
        assignment = cur.fetchone()

        if assignment is None:
            raise HTTPException(status_code=404, detail="Aktive Ausleihe nicht gefunden.")

        dev_id = assignment[0]

        cur.execute("""
            UPDATE ausleihe
            SET rueckgabe_datum = COALESCE(%s, CURRENT_DATE)
            WHERE ausleih_id = %s;
        """, (ret_date, assignment_id))

        cur.execute("UPDATE geraete SET status = 'frei' WHERE geraete_id = %s;", (dev_id,))
        conn.commit()

    publish_device_returned(assignment_id)

    if return_to:
        return RedirectResponse(return_to, status_code=303)
    return {"message": "Gerät erfolgreich zurückgegeben."}


@app.post("/mqtt/publish")
async def mqtt_publish(topic: str = Query(...), payload: str = Query(...)):
    c = get_mqtt_client()
    c.publish(topic, payload, qos=0, retain=False)
    c.disconnect()
    return {"ok": True, "topic": topic, "payload": payload}
