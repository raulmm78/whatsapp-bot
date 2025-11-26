from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse
import os
import requests
import json
from datetime import datetime, timedelta

from google.oauth2 import service_account
from googleapiclient.discovery import build
from openai import OpenAI

app = FastAPI()

# =========================
# ENV VARS
# =========================
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID")
GOOGLE_SERVICE_ACCOUNT_JSON = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

client = OpenAI(api_key=OPENAI_API_KEY)

# =========================
# RAG: TEXTO DE LA CLÍNICA
# =========================
CLINIC_KNOWLEDGE = """
Clínica Dental Martínez

Dirección: Calle Ejemplo 123, Madrid.
Servicios: Odontología general, implantes, ortodoncia, estética dental.
Teléfono: 900 000 000
Horario habitual: Lunes a Viernes, 10:00–14:00 y 16:00–20:00.
Las citas se reservan siempre bajo disponibilidad mediante el calendario.
Procura que el tono sea cálido, cercano y profesional.
"""

# =========================
# GOOGLE CALENDAR
# =========================
def get_calendar_service():
    if not GOOGLE_SERVICE_ACCOUNT_JSON:
        raise RuntimeError("Falta GOOGLE_SERVICE_ACCOUNT_JSON en las variables de entorno")

    data = json.loads(GOOGLE_SERVICE_ACCOUNT_JSON)
    creds = service_account.Credentials.from_service_account_info(
        data,
        scopes=["https://www.googleapis.com/auth/calendar"]
    )
    service = build("calendar", "v3", credentials=creds)
    return service


def is_slot_free(date_iso: str, time_24: str, duration_minutes: int = 60) -> bool:
    """
    date_iso: '2025-11-27'
    time_24: '11:00'
    """
    service = get_calendar_service()
    calendar_id = "primary"

    start_dt = datetime.fromisoformat(f"{date_iso}T{time_24}:00")
    end_dt = start_dt + timedelta(minutes=duration_minutes)

    events = service.events().list(
        calendarId=calendar_id,
        timeMin=start_dt.isoformat() + "Z",
        timeMax=end_dt.isoformat() + "Z",
        singleEvents=True,
        orderBy="startTime"
    ).execute()

    return len(events.get("items", [])) == 0


def create_appointment(name: str, date_iso: str, time_24: str):
    service = get_calendar_service()
    calendar_id = "primary"

    start_dt = datetime.fromisoformat(f"{date_iso}T{time_24}:00")
    end_dt = start_dt + timedelta(minutes=60)

    event = {
        "summary": f"Cita dental – {name}",
        "description": "Cita reservada automáticamente por el bot de WhatsApp.",
        "start": {
            "dateTime": start_dt.isoformat(),
            "timeZone": "Europe/Madrid",
        },
        "end": {
            "dateTime": end_dt.isoformat(),
            "timeZone": "Europe/Madrid",
        },
    }

    created = service.events().insert(calendarId=calendar_id, body=event).execute()
    return created


def list_free_slots(date_iso: str):
    """
    Devuelve huecos libres tipo ['10:00', '11:00', '16:00'] según horario estándar.
    """
    possible_hours = ["10:00", "11:00", "12:00", "13:00",
                      "16:00", "17:00", "18:00", "19:00"]
    free = []
    for h in possible_hours:
        if is_slot_free(date_iso, h):
            free.append(h)
    return free


def get_upcoming_appointments(limit: int = 5):
    service = get_calendar_service()
    calendar_id = "primary"
    now = datetime.utcnow().isoformat() + "Z"

    events_result = service.events().list(
        calendarId=calendar_id,
        timeMin=now,
        maxResults=limit,
        singleEvents=True,
        orderBy="startTime",
    ).execute()

    events = events_result.get("items", [])
    return events

# =========================
# WHATSAPP
# =========================
def send_whatsapp_message(to: str, message: str):
    url = f"https://graph.facebook.com/v20.0/{WHATSAPP_PHONE_NUMBER_ID}/messages"

    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json",
    }

    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "text": {"body": message},
    }

    r = requests.post(url, headers=headers, json=payload)
    print("WhatsApp response:", r.status_code, r.text)
    return r.text

# =========================
# OPENAI: PLAN EN JSON
# =========================
def plan_from_ai(user_message: str) -> dict:
    """
    Le pedimos a OpenAI que nos devuelva SOLO un JSON con:
    - intent: 'book' | 'check' | 'info'
    - name: str | null
    - date_iso: 'YYYY-MM-DD' | null
    - time_24: 'HH:MM' | null
    - extra: texto para ayudar a responder
    """
    system_msg = f"""
Eres el asistente de la Clínica Dental Martínez.
Conocimiento de la clínica:
{CLINIC_KNOWLEDGE}

Tu misión: interpretar lo que pide el usuario y devolver SOLO un JSON válido.
NO expliques nada, no añadas texto fuera del JSON.
"""

    user_msg = f"""
Usuario dice: "{user_message}"

Devuelve un JSON con esta forma:

{{
  "intent": "book" | "check" | "info",
  "name": "Nombre de la persona o null",
  "date_iso": "YYYY-MM-DD o null",
  "time_24": "HH:MM o null",
  "extra": "texto breve en español para contexto interno"
}}

Reglas:
- "book" si quiere reservar/modificar una cita.
- "check" si quiere ver próximas citas o saber si tiene algo pendiente.
- "info" si solo pregunta por servicios, horarios, etc.
- Convierte expresiones como "mañana", "hoy", "el jueves", "28 de noviembre" a date_iso.
- Convierte horas como "a las 11", "11 de la mañana", "6 de la tarde" a formato 24h HH:MM.
"""

    completion = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg},
        ],
        temperature=0.1,
    )

    content = completion.choices[0].message.content
    print("AI raw plan:", content)

    # Intentamos parsear el JSON
    try:
        plan = json.loads(content)
    except Exception as e:
        print("Error parseando JSON del plan:", e)
        plan = {
            "intent": "info",
            "name": None,
            "date_iso": None,
            "time_24": None,
            "extra": "No he podido interpretar el JSON, actúa solo como informativo.",
        }
    return plan


def build_reply_from_plan(plan: dict) -> str:
    intent = plan.get("intent")
    name = plan.get("name")
    date_iso = plan.get("date_iso")
    time_24 = plan.get("time_24")

    # Sólo información, sin tocar calendario
    if intent == "info" or (not date_iso and not time_24):
        msg = plan.get("extra") or ""
        return (
            "Hola 👋, soy el asistente de la Clínica Dental Martínez.\n\n"
            f"{msg}\n\nSi quieres reservar una cita, dime tu nombre, el día y la hora que prefieres."
        )

    # Consultar próximas citas
    if intent == "check":
        events = get_upcoming_appointments()
        if not events:
            return "No veo citas próximas en el calendario. Si quieres, puedo ayudarte a reservar una 😊"

        lines = ["Estas son tus próximas citas en la clínica:"]
        for ev in events:
            start = ev["start"].get("dateTime", ev["start"].get("date"))
            start_dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
            local = start_dt.astimezone()  # usa zona local del servidor
            lines.append(f"• {local.strftime('%d/%m/%Y %H:%M')} – {ev.get('summary', 'Cita')}")
        return "\n".join(lines)

    # Reserva de cita
    if intent == "book" and date_iso and time_24 and name:
        if is_slot_free(date_iso, time_24):
            event = create_appointment(name, date_iso, time_24)
            start = event["start"]["dateTime"]
            start_dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
            local = start_dt.astimezone()
            fecha_str = local.strftime("%d/%m/%Y")
            hora_str = local.strftime("%H:%M")

            return (
                f"¡Perfecto, {name}! 🎉\n\n"
                f"He reservado tu cita para el día {fecha_str} a las {hora_str} en la Clínica Dental Martínez.\n"
                "Si necesitas cambiarla o tienes alguna duda, escríbeme por aquí."
            )
        else:
            free = list_free_slots(date_iso)
            if not free:
                return (
                    "Ese horario ya está ocupado y hoy no tengo huecos libres 😔.\n"
                    "Si quieres, dime otro día u otra hora aproximada y miro de nuevo."
                )
            else:
                slots_str = ", ".join(free)
                return (
                    "Ese horario ya está ocupado, pero tengo disponibles estos huecos:\n"
                    f"{slots_str}\n\n"
                    "Dime cuál te viene mejor y la reservamos 😊"
                )

    # Caso raro / fallback
    return (
        "He entendido que quieres hacer algo con tu cita, pero me falta algún dato "
        "(nombre, día u hora). Por favor, dime algo como:\n\n"
        "«Quiero una cita para el martes 3 de diciembre a las 11, mi nombre es Ana Pérez»."
    )

# =========================
# WEBHOOK VERIFY (GET)
# =========================
@app.get("/webhook")
async def verify_webhook(hub_mode: str = None, hub_challenge: str = None, hub_verify_token: str = None):
    if hub_mode == "subscribe" and hub_verify_token == VERIFY_TOKEN:
        return PlainTextResponse(content=hub_challenge, status_code=200)
    return PlainTextResponse(content="Invalid verify token", status_code=403)

# =========================
# WEBHOOK (POST)
# =========================
@app.post("/webhook")
async def webhook_handler(request: Request):
    data = await request.json()
    print("Incoming:", json.dumps(data, indent=2, ensure_ascii=False))

    try:
        entry = data["entry"][0]
        changes = entry["changes"][0]["value"]
        messages = changes.get("messages")

        if messages:
            msg = messages[0]
            from_number = msg["from"]
            text = msg["text"]["body"]

            plan = plan_from_ai(text)
            reply = build_reply_from_plan(plan)
            send_whatsapp_message(from_number, reply)

    except Exception as e:
        print("Error manejando webhook:", e)

    return {"status": "ok"}

# =========================
# ROOT
# =========================
@app.get("/")
def home():
    return {"status": "running", "bot": "whatsapp-calendar-rag"}