from fastapi import FastAPI, Request, Query
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

@app.get("/devices", response_class=HTMLResponse)
def devices_page(request: Request):
  with get_conn() as conn, conn.cursor() as cur:
    cur.execute(
      "select * from geräte"
    )
    devices = list(cur.fetchall())

  return templates.TemplateResponse(
    "geräte/index.html",
    {"request": request, "title": "Geräte", "geräte": devices},
  )

@app.post("/devices", response_class=HTMLResponse)
def create_device(
  request: Request,
  geraet_id: str = Form(...),
  geraetetyp: str = Form(...),
  nachname: str = Form(...),
  programme: str = Form(...),
  semester: int = Form(...),
  return_to: str | None = Form(None),
):
  data = DeviceCreate(
    geraet_id=geraet_id,
    geraetetyp=geraetetyp,
    hersteller=hersteller,
    modell=modell,
    geraetename=geraetename,
    netto_preis=netto_preis,
    seriennummer=seriennummer,
    status=status,
  )
  with get_conn() as conn, conn.cursor() as cur:
    cur.execute(
      """
      insert into device (matrikel, vorname, nachname, programme, semester)
      values (%s, %s, %s, %s, %s)
      on conflict (matrikel) do nothing
      """,
      (data.matrikel, data.vorname, data.nachname, data.programme, data.semester),
    )
  if return_to:
    return RedirectResponse(return_to, status_code=303)
  return grades_page(request)


@app.get("/inventory", response_class=HTMLResponse)
async def inventory_page(request: Request):
    return templates.TemplateResponse("inventory.html", {"request": request, "title": "Inventar Starter"})

@app.post("/mqtt/publish")
async def mqtt_publish(topic: str = Query(...), payload: str = Query(...)):
    c = mqtt_client()
    c.publish(topic, payload, qos=0, retain=False)
    c.disconnect()
    return {"ok": True, "topic": topic, "payload": payload}
