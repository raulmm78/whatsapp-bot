from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse, JSONResponse
import os
import json
import requests
import dateparser
from datetime import datetime, timedelta, timezone

from openai import OpenAI

from google.oauth2 import service_account
from googleapiclient.discovery import build

# -----------------------------------------------------
# FASTAPI APP
# -----------------------------------------------------
app = FastAPI()

# -----------------------------------------------------
# ENV VARIABLES
# -----------------------------------------------------
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

GOOGLE_CALENDAR_ID = os.getenv("GOOGLE_CALENDAR_ID")
GOOGLE_CREDENTIALS_JSON = os.getenv("GOOGLE_CREDENTIALS_JSON")

WHATSAPP_URL = f"https://graph.facebook.com/v20.0/{WHATSAPP_PHONE_NUMBER_ID}/messages"

# Zona horaria (ajusta si hace falta)
TZ = timezone(timedelta(hours=1))  # Europa/Madrid aproximado

# OpenAI client
client = OpenAI(api_key=OPENAI_API_KEY)


# -----------------------------------------------------
# GOOGLE CALENDAR: SERVICE
# -----------------------------------------------------
def get_calendar_service():
    """Devuelve el cliente de Google Calendar o None si falta configuración."""
    try:
        if not GOOGLE_CREDENTIALS_JSON or not GOOGLE_CALENDAR_ID:
            print("Google Calendar no configurado (faltan env vars).")
            return None

        creds_info = json.loads(GOOGLE_CREDENTIALS_JSON)
        creds = service_account.Credentials.from_service_account_info(
            creds_info,
            scopes=["https://www.googleapis.com/auth/calendar"]
        )
        service = build("calendar", "v3", credentials=creds, cache_discovery=False)
        return service
    except Exception as e:
        print("Error creando servicio de Calendar:", e)
        return None


# -----------------------------------------------------
# GOOGLE CALENDAR: CREAR CITA
# -----------------------------------------------------
def create_calendar_event(name: str, phone: str, when_dt: datetime):
    """
    Crea una cita de 30 minutos en el calendario.
    Devuelve un texto amigable con la info de la cita o mensaje de error.
    """
    service = get_calendar_service()
    if service is None:
        return "He intentado crear la cita, pero el calendario no está bien configurado todavía."

    # Normalizar a timezone
    if when_dt.tzinfo is None:
        when_dt = when_dt.replace(tzinfo=TZ)

    end_dt = when_dt + timedelta(minutes=30)

    event_body = {
        "summary": f"Cita dental - {name}",
        "description": f"Cita creada por WhatsApp. Teléfono: {phone}",
        "start": {
            "dateTime": when_dt.isoformat(),
            "timeZone": "Europe/Madrid",
        },
        "end": {
            "dateTime": end_dt.isoformat(),
            "timeZone": "Europe/Madrid",
        }
    }

    try:
        event = service.events().insert(
            calendarId=GOOGLE_CALENDAR_ID,
            body=event_body
        ).execute()

        start_str = when_dt.strftime("%d/%m/%Y a las %H:%M")
        return f"Cita creada para *{start_str}* ✅\nSi quieres cambiarla, escríbenos de nuevo."
    except Exception as e:
        print("Error creando evento:", e)
        return "He intentado crear la cita pero ha habido un problema con el calendario."


# -----------------------------------------------------
# GOOGLE CALENDAR: CITAS PENDIENTES POR TELÉFONO
# -----------------------------------------------------
def get_user_appointments(phone: str):
    """
    Busca citas futuras en el calendario que contengan el teléfono en la descripción.
    Devuelve un texto en formato lista.
    """
    service = get_calendar_service()
    if service is None:
        return "Ahora mismo no puedo consultar el calendario, pero puedo ayudarte igualmente con tus dudas."

    now = datetime.now(TZ).isoformat()

    try:
        events_result = service.events().list(
            calendarId=GOOGLE_CALENDAR_ID,
            timeMin=now,
            q=phone,
            singleEvents=True,
            orderBy="startTime"
        ).execute()

        events = events_result.get("items", [])

        if not events:
            return "No veo ninguna cita futura a tu nombre/tu número en el calendario."

        lines = ["Estas son tus próximas citas que veo en el sistema:"]
        for ev in events:
            start = ev["start"].get("dateTime") or ev["start"].get("date")
            start_dt = dateparser.parse(start)
            start_str = start_dt.strftime("%d/%m/%Y a las %H:%M") if start_dt else start
            lines.append(f"• {ev.get('summary', 'Cita')} – {start_str}")

        return "\n".join(lines)

    except Exception as e:
        print("Error consultando citas:", e)
        return "Ha habido un problema al consultar tus citas. Intenta de nuevo más tarde."


# -----------------------------------------------------
# GOOGLE CALENDAR: HORAS LIBRES PARA UN DÍA
# -----------------------------------------------------
def get_free_slots_for_day(day: datetime):
    """
    Da una lista de horas libres en texto para un día concreto, usando FreeBusy.
    Ventana simple: 10:00–14:00 cada 30 minutos.
    """
    service = get_calendar_service()
    if service is None:
        return None  # sin calendario

    # Normalizar fecha
    day = day.astimezone(TZ).replace(hour=0, minute=0, second=0, microsecond=0)
    start_of_day = day
    end_of_day = day + timedelta(days=1)

    body = {
        "timeMin": start_of_day.isoformat(),
        "timeMax": end_of_day.isoformat(),
        "items": [{"id": GOOGLE_CALENDAR_ID}]
    }

    try:
        fb = service.freebusy().query(body=body).execute()
        busy = fb["calendars"][GOOGLE_CALENDAR_ID]["busy"]

        # Ventana por defecto 10:00–14:00
        current = day.replace(hour=10, minute=0)
        end_window = day.replace(hour=14, minute=0)

        free_slots = []
        while current < end_window:
            slot_end = current + timedelta(minutes=30)

            overlap = False
            for b in busy:
                b_start = dateparser.parse(b["start"])
                b_end = dateparser.parse(b["end"])
                # Hay solapamiento si empieza antes del fin y termina después del inicio
                if b_start < slot_end and b_end > current:
                    overlap = True
                    break

            if not overlap:
                free_slots.append(current.strftime("%H:%M"))

            current = slot_end

        if not free_slots:
            return "Ese día parece estar completo en la franja 10:00–14:00 😕."

        slots_text = "\n".join(f"🕒 {h}" for h in free_slots)
        return (
            "Disponibilidad aproximada para ese día (10:00–14:00):\n"
            f"{slots_text}\n\n"
            "Responde con la hora que prefieras, por ejemplo: *11:30*."
        )

    except Exception as e:
        print("Error consultando FreeBusy:", e)
        return None


# -----------------------------------------------------
# WEBHOOK VERIFICATION (GET)
# -----------------------------------------------------
@app.get("/webhook")
async def verify(hub_mode: str = None, hub_challenge: str = None, hub_verify_token: str = None):
    if hub_mode == "subscribe" and hub_verify_token == VERIFY_TOKEN:
        return PlainTextResponse(content=hub_challenge, status_code=200)
    return PlainTextResponse(content="Invalid verify token", status_code=403)


# -----------------------------------------------------
# ENVIAR MENSAJE A WHATSAPP
# -----------------------------------------------------
def send_whatsapp_message(to_number: str, message: str):
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }

    payload = {
        "messaging_product": "whatsapp",
        "to": to_number,
        "text": {"body": message}
    }

    print("Sending message:", json.dumps(payload, indent=2, ensure_ascii=False))
    r = requests.post(WHATSAPP_URL, headers=headers, json=payload)
    print("WhatsApp response:", r.status_code, r.text)
    return r.status_code, r.text


# -----------------------------------------------------
# RESPUESTA GENERAL CON OPENAI
# -----------------------------------------------------
def answer_with_openai(user_msg: str) -> str:
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Eres un asistente amable de una clínica dental. "
                        "Respondes siempre de forma cercana, clara y profesional. "
                        "Si la pregunta es sobre citas, horarios o reservas, "
                        "explica la información general y deja claro que las citas "
                        "se gestionan a través del sistema de agenda integrado."
                    )
                },
                {"role": "user", "content": user_msg}
            ]
        )

        return response.choices[0].message.content

    except Exception as e:
        print("Error OpenAI:", e)
        return "Parece que hay un problema técnico con el sistema 😔. Puedes intentarlo de nuevo más tarde."


# -----------------------------------------------------
# WEBHOOK POST (MENSAJES ENTRANTES)
# -----------------------------------------------------
@app.post("/webhook")
async def webhook_handler(request: Request):
    data = await request.json()
    print("\n\nIncoming webhook:")
    print(json.dumps(data, indent=2, ensure_ascii=False))

    try:
        entry = data["entry"][0]
        changes = entry["changes"][0]
        value = changes["value"]
        messages = value.get("messages")

        if not messages:
            return JSONResponse({"status": "ignored"})

        msg = messages[0]
        from_number = msg["from"]
        text = msg.get("text", {}).get("body", "").strip()
        lower = text.lower()

        # -------------------------------------------------
        # 1) PETICIÓN: VER MIS CITAS
        # -------------------------------------------------
        check_words = ["mis citas", "tengo cita", "citas pendientes", "próxima cita", "proxima cita"]
        if any(w in lower for w in check_words):
            reply = get_user_appointments(from_number)
            send_whatsapp_message(from_number, reply)
            return {"status": "appointments"}

        # -------------------------------------------------
        # 2) INTENCIÓN DE RESERVA
        # -------------------------------------------------
        intent_words = ["cita", "agendar", "agenda", "hora", "reserva", "limpieza"]
        is_booking_intent = any(w in lower for w in intent_words)

        # EXTRAER POSIBLE NOMBRE
        possible_name = None

        if "," in text:
            possible_name = text.split(",")[0].strip()

        if "mi nombre es" in lower:
            possible_name = text.lower().replace("mi nombre es", "").strip().title()

        if lower.startswith("soy "):
            possible_name = text[4:].strip().title()

        # EXTRAER FECHA/HORA
        parsed_dt = dateparser.parse(text, languages=["es"])
        iso_date = None
        if parsed_dt:
            parsed_dt = parsed_dt.replace(tzinfo=TZ)
            iso_date = parsed_dt.date()

        if is_booking_intent:
            # 2.1 Tenemos nombre y fecha/hora -> intentamos crear cita
            if possible_name and iso_date:
                # Si parsed_dt no tiene hora, ponemos 10:00
                if parsed_dt.hour == 0 and parsed_dt.minute == 0:
                    parsed_dt = datetime(
                        year=parsed_dt.year,
                        month=parsed_dt.month,
                        day=parsed_dt.day,
                        hour=10,
                        minute=0,
                        tzinfo=TZ
                    )

                # Mostrar disponibilidad de ese día de forma "visual"
                slots_text = get_free_slots_for_day(parsed_dt)
                if slots_text:
                    send_whatsapp_message(
                        from_number,
                        f"Genial {possible_name} 😄\n"
                        f"He detectado el día *{parsed_dt.strftime('%d/%m/%Y')}*.\n\n"
                        f"{slots_text}"
                    )
                    # Nota: para versión simple todavía no usamos la hora elegida
                    # El usuario probablemente responderá con algo tipo "11:30 mañana"
                    # y volvemos a entrar por este mismo flujo con fecha+hora.
                else:
                    # Directamente intentamos crear cita
                    result = create_calendar_event(possible_name, from_number, parsed_dt)
                    send_whatsapp_message(from_number, result)

                return {"status": "booking_with_name_and_date"}

            # 2.2 Falta nombre
            if iso_date and not possible_name:
                send_whatsapp_message(
                    from_number,
                    "Genial 😊 Ya tengo el día. Ahora dime tu *nombre completo*, por favor."
                )
                return {"status": "need_name"}

            # 2.3 Falta fecha
            if possible_name and not iso_date:
                send_whatsapp_message(
                    from_number,
                    f"Gracias {possible_name}. Ahora dime el *día exacto* en el que quieres venir."
                )
                return {"status": "need_date"}

            # 2.4 Falta todo
            send_whatsapp_message(
                from_number,
                "Será un placer ayudarte a agendar una cita 🦷\n"
                "Dime por favor tu *nombre* y el *día* que te gustaría venir.\n"
                "Ejemplo: *Carolina Rodríguez, mañana a las 18h*"
            )
            return {"status": "need_info"}

        # -------------------------------------------------
        # 3) RESPUESTA GENERAL CON IA
        # -------------------------------------------------
        ai_reply = answer_with_openai(text)
        send_whatsapp_message(from_number, ai_reply)

        return {"status": "ai_response"}

    except Exception as e:
        print("Webhook error:", e)
        return JSONResponse({"error": str(e)}, status_code=500)


# -----------------------------------------------------
# ROOT
# -----------------------------------------------------
@app.get("/")
def root():
    return {"status": "running", "message": "WhatsApp bot online 🚀"}