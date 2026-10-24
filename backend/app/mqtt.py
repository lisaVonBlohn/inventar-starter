import os
import json
import threading
import time

import paho.mqtt.client as mqtt

from .db import get_conn

MQTT_HOST = os.getenv("MQTT_HOST", "mqtt")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))

TOPIC_ISSUED = "inventory/assignments/issued"
TOPIC_RETURNED = "inventory/assignments/returned"

def get_mqtt_client() -> mqtt.Client:
    """Erstellt und verbindet einen MQTT-Client (wird auch von /health genutzt)."""
    client = mqtt.Client()
    client.connect(MQTT_HOST, MQTT_PORT, keepalive=30)
    return client

def _publish_event(topic: str, payload_dict: dict):
    """Hilfsfunktion: Sendet eine Nachricht an das angegebene Topic."""
    try:
        client = mqtt.Client()
        client.connect(MQTT_HOST, MQTT_PORT, keepalive=10)
        client.publish(topic, json.dumps(payload_dict), qos=0)
        client.disconnect()
        print(f"[MQTT] Event gesendet auf '{topic}': {payload_dict}")
    except Exception as exc:
        print(f"[MQTT] Fehler beim Senden auf '{topic}':", exc)

def publish_device_issued(ausleih_id: int, mitarbeiter_id: int, geraete_id: int):
    """Wird nach erfolgreicher Ausgabe aufgerufen."""
    payload = {
        "event": "device_issued",
        "ausleih_id": ausleih_id,
        "mitarbeiter_id": mitarbeiter_id,
        "geraete_id": geraete_id
    }
    _publish_event(TOPIC_ISSUED, payload)


def publish_device_returned(ausleih_id: int):
    """Wird nach erfolgreicher Rückgabe aufgerufen."""
    payload = {
        "event": "device_returned",
        "ausleih_id": ausleih_id
    }
    _publish_event(TOPIC_RETURNED, payload)

def _on_message(client: mqtt.Client, userdata, msg: mqtt.MQTTMessage):
  try:
    payload = msg.payload.decode("utf-8")
    data = json.loads(payload)
    mitarbeiter_id = int(data["mitarbeiter_id"])
    geraete_id = int(data["geraete_id"])
  except Exception as exc:
    print("[MQTT] Ungültiges Payload, wird ignoriert:", exc)
    return

  try:
    with get_conn() as conn, conn.cursor() as cur:
      cur.execute(
        """
        INSERT INTO ausleihe (mitarbeiter_id, geraete_id, ausgabe_datum)
        VALUES (%s, %s, CURRENT_DATE)
        RETURNING ausleih_id;
        """,
        (mitarbeiter_id, geraete_id),
      )
    ausleih_id = cur.fetchone()[0]
    cur.execute(
                """
                UPDATE geraete
                SET status = 'ausgeliehen'
                WHERE geraete_id = %s;
                """,
                (geraete_id,),
            )
    conn.commit()

    print(f"[MQTT] Neue Ausleihe via MQTT angelegt: id={ausleih_id}, mitarbeiter={mitarbeiter_id}, geraet={geraete_id}")
        
    publish_device_issued(ausleih_id, mitarbeiter_id, geraete_id)
  except Exception as exc:
    print("[MQTT] Fehler beim Eintragen der Ausleihe:", exc)


def _mqtt_loop():
  """Verbindet sich mit dem Broker, abonniert das Topic und läuft in einer Endlosschleife."""
  while True:
    try:
      client = mqtt.Client()
      client.on_message = _on_message
      client.connect(MQTT_HOST, MQTT_PORT, keepalive=30)
      client.subscribe("inventory/assignments/new", qos=0)
      print(f"[MQTT] Verbunden mit {MQTT_HOST}:{MQTT_PORT}, Topic 'inventory/assignments/new' abonniert.")
      client.loop_forever()
    except Exception as exc:
      print("[MQTT] Verbindungsfehler, neuer Versuch in 5s:", exc)
      time.sleep(5)


def start_mqtt_listener():
  """Startet den MQTT-Listener in einem Hintergrundthread."""
  t = threading.Thread(target=_mqtt_loop, daemon=True)
  t.start()
