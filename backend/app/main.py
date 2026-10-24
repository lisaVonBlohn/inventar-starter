from fastapi import FastAPI, Request, Query
from fastapi import HTTPException
from .models import DeviceCreate, AssignmentCreate, AssignmentReturn
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
import os
from .db import get_conn
import paho.mqtt.client as mqtt

app = FastAPI(title="Inventar Starter", version="0.1.0")
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "templates"))

MQTT_HOST = os.getenv("MQTT_HOST", "mqtt")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))

def mqtt_client() -> mqtt.Client:
    c = mqtt.Client()
    c.connect(MQTT_HOST, MQTT_PORT, keepalive=30)
    return c

@app.get("/health")
async def health():
    db_state = "ok"
    mqtt_state = "ok"
    try:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("select 1")
            cur.fetchone()
    except Exception as ex:
        db_state = f"error:{type(ex).__name__}"

    try:
        c = mqtt_client()
        c.disconnect()
    except Exception as ex:
        mqtt_state = f"degraded:{type(ex).__name__}"

    return {"status": "ok" if db_state == "ok" else "degraded", "db": db_state, "mqtt": mqtt_state}

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request, "title": "Inventar Starter"})

@app.get("/devices")
def get_devices():
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT *
            FROM geraete
            ORDER BY geraete_id
        """)

        columns = [col[0] for col in cur.description]
        return [
            dict(zip(columns, row))
            for row in cur.fetchall()
        ]

@app.get("/assignments/active")
def get_active_assignments():
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT
                a.ausleih_id,
                a.mitarbeiter_id,
                a.geraete_id,
                a.ausgabe_datum,
                a.rueckgabe_datum
            FROM ausleihe AS a
            WHERE a.rueckgabe_datum IS NULL
            ORDER BY a.ausleih_id
        """)

        columns = [col[0] for col in cur.description]
        return [
            dict(zip(columns, row))
            for row in cur.fetchall()
        ]

@app.post("/assignments", status_code=201)
def create_assignment(assignment: AssignmentCreate):
    try:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("""
                SELECT aktiv
                FROM mitarbeiter
                WHERE personalnummer = %s
            """, (assignment.person_id,))

            person = cur.fetchone()

            if person is None or not person[0]:
                raise HTTPException(
                    status_code=400,
                    detail="Mitarbeiter fehlt oder ist inaktiv."
                )

            cur.execute("""
                SELECT status
                FROM geraete
                WHERE geraete_id = %s
                FOR UPDATE
            """, (assignment.device_id,))

            device = cur.fetchone()

            if device is None:
                raise HTTPException(
                    status_code=404,
                    detail="Gerät nicht gefunden."
                )

            if device[0].lower() != "frei":
                raise HTTPException(
                    status_code=409,
                    detail="Gerät ist nicht verfügbar."
                )

            cur.execute("""
                INSERT INTO ausleihe (
                    mitarbeiter_id,
                    geraete_id,
                    ausgabe_datum
                )
                VALUES (%s, %s, COALESCE(%s, CURRENT_DATE))
                RETURNING ausleih_id
            """, (
                assignment.person_id,
                assignment.device_id,
                assignment.issued_at
            ))

            assignment_id = cur.fetchone()[0]

            cur.execute("""
                UPDATE geraete
                SET status = 'ausgeliehen'
                WHERE geraete_id = %s
            """, (assignment.device_id,))

            return {"ausleih_id": assignment_id}

    except Exception as exc:
        if (
            getattr(exc, "sqlstate", None) == "23505"
            or getattr(exc, "pgcode", None) == "23505"
        ):
            raise HTTPException(
                status_code=409,
                detail="Gerät hat bereits eine aktive Ausleihe."
            )
        raise
        
@app.post("/assignments/{id}/return")
def return_assignment(
    assignment_id: int,
    returned: AssignmentReturn
):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT geraete_id
                FROM ausleihe
                WHERE ausleih_id = %s
                  AND rueckgabe_datum IS NULL
                FOR UPDATE
            """, (assignment_id,))

            assignment = cur.fetchone()

            if assignment is None:
                raise HTTPException(
                    status_code=404,
                    detail="Aktive Ausleihe nicht gefunden."
                )

            device_id = assignment[0]

            cur.execute("""
                UPDATE ausleihe
                SET rueckgabe_datum = COALESCE(%s, CURRENT_DATE)
                WHERE ausleih_id = %s
            """, (returned.returned_at, assignment_id))

            cur.execute("""
                UPDATE geraete
                SET status = 'frei'
                WHERE geraete_id = %s
            """, (device_id,))

            return {"message": "Gerät erfolgreich zurückgegeben."}

@app.post("/devices", status_code=201)
def create_device(device: DeviceCreate):
    try:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("""
                INSERT INTO geraete (
                    geraete_typ,
                    hersteller,
                    modell,
                    geraete_name,
                    netto_preis,
                    seriennummer,
                    status
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING geraete_id
            """, (
                device.device_type_id,
                device.manufacturer,
                device.model,
                device.device_name,
                device.net_price,
                device.serial_number,
                device.status
            ))

            return {"geraete_id": cur.fetchone()[0]}

    except Exception as exc:
        if (
            getattr(exc, "sqlstate", None) == "23505"
            or getattr(exc, "pgcode", None) == "23505"
        ):
            raise HTTPException(
                status_code=409,
                detail="Diese Seriennummer existiert bereits."
            )
        raise


@app.get("/inventory", response_class=HTMLResponse)
async def inventory_page(request: Request):
    return templates.TemplateResponse("inventory.html", {"request": request, "title": "Inventar Starter"})

@app.post("/mqtt/publish")
async def mqtt_publish(topic: str = Query(...), payload: str = Query(...)):
    c = mqtt_client()
    c.publish(topic, payload, qos=0, retain=False)
    c.disconnect()
    return {"ok": True, "topic": topic, "payload": payload}
