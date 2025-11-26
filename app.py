from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse, JSONResponse
import os
import json
import requests
from openai import OpenAI
from google.oauth2 import service_account
from googleapiclient.discovery import build

app = FastAPI()

# ========= CONFIG =========
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")

WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID")
WHATSAPP_API_URL = "https://graph.facebook.com/v20.0"

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GCAL_SERVICE_ACCOUNT = os.getenv("GCAL_SERVICE_ACCOUNT")
GOOGLE_CALENDAR_ID = os.getenv("GOOGLE_CALENDAR_ID", "www.raulmartinez.es@gmail.com")

openai_client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

# ========= "PDF" EMBEBIDO (resumen clínica) =========
CLINIC_KNOWLEDGE = """
Clínica Dental Martínez es una clínica dental familiar ubicada en Madrid.
Ofrece: limpiezas, revisiones, ortodoncia, implantes, estética dental, urgencias.
Horario orientativo: L-V 9:30–14:00 y 16:00–20:00.
Contacto: teléfono y WhatsApp en el número de la propia clínica.
Tono: cercano, tranquilo, profesional; explica las cosas en lenguaje sencillo.
No inventes precios concretos, solo puedes decir que dependerán del caso y que se le hará presupuesto en la clínica.
Nunca des recomendaciones médicas tajantes, invita a revisión presencial si hay dolor, inflamación o urgencia.
"""

# ========= ENVIAR MENSAJE WHATSAPP =========
def send_whatsapp_message(to: str, message: str):
    url = f"{WHATSAPP_API_URL}/{WHATSAPP_PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "text": {"body": message}
    }

    print("Sending:", payload)

    r = requests.post(url, headers=headers, json=payload)
    print("WhatsApp response:", r.status_code, r.text)
    return r.status_code, r.text

# ========= GOOGLE CALENDAR =========
def create_calendar_event(name: str, day: str):
    """
    Crea una cita básica en Google Calendar:
    name: nombre del paciente
    day: 'AAAA-MM-DD'
    """
    if not GCAL_SERVICE_ACCOUNT:
        print("GCAL_SERVICE_ACCOUNT no configurado")
        return False, None, "Falta GCAL_SERVICE_ACCOUNT"

    try:
        service_json = json.loads(GCAL_SERVICE_ACCOUNT)

        credentials = service_account.Credentials.from_service_account_info(
            service_json,
            scopes=["https://www.googleapis.com/auth/calendar"]
        )

        service = build("calendar", "v3", credentials=credentials, cache_discovery=False)

        event = {
            "summary": f"Cita dental – {name}",
            "description": "Reserva automatizada desde WhatsApp",
            "start": {
                "dateTime": f"{day}T10:00:00",
                "timeZone": "Europe/Madrid",
            },
            "end": {
                "dateTime": f"{day}T10:30:00",
                "timeZone": "Europe/Madrid",
            },
        }

        event_result = service.events().insert(
            calendarId=GOOGLE_CALENDAR_ID,
            body=event
        ).execute()

        link = event_result.get("htmlLink")
        print("Evento creado:", link)
        return True, link, None

    except Exception as e:
        print("Error creando evento:", e)
        return False, None, str(e)

# ========= OPENAI / ASISTENTE CLÍNICA =========
def answer_with_openai(user_text: str) -> str:
    if not openai_client:
        return (
            "Soy el asistente de la Clínica Dental Martínez 🦷\n"
            "Ahora mismo no tengo conexión con el motor de IA, pero puedes escribirnos o llamarnos para más detalle."
        )

    system_prompt = (
        "Eres el asistente virtual de una clínica dental llamada 'Clínica Dental Martínez'. "
        "Respondes de forma cercana, clara y profesional. Usa SOLO la información de la siguiente base de conocimiento. "
        "Si algo no está en la base, dilo y recomienda contactar con la clínica.\n\n"
        f"BASE DE CONOCIMIENTO:\n{CLINIC_KNOWLEDGE}\n"
    )

    try:
        resp = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_text}
            ],
            temperature=0.4,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        print("Error OpenAI:", e)
        return (
            "He tenido un problema al generar la respuesta 🤖.\n"
            "Por favor, vuelve a intentarlo en unos minutos o contacta directamente con la clínica."
        )

# ========= WEBHOOK VERIFY (GET) =========
@app.get("/webhook")
async def verify_webhook(
    hub_mode: str = None,
    hub_challenge: str = None,
    hub_verify_token: str = None,
):
    print("VERIFY:", hub_mode, hub_challenge, hub_verify_token)
    if hub_mode == "subscribe" and hub_verify_token == VERIFY_TOKEN:
        return PlainTextResponse(content=hub_challenge, status_code=200)
    return PlainTextResponse(content="Invalid verify token", status_code=403)

# ========= WEBHOOK MENSAJES (POST) =========
@app.post("/webhook")
async def webhook_handler(request: Request):
    data = await request.json()
    print("Incoming:", json.dumps(data, indent=2, ensure_ascii=False))

    try:
        entry = data["entry"][0]
        changes = entry["changes"][0]
        value = changes["value"]
        messages = value.get("messages")

        if not messages:
            return JSONResponse({"status": "no_message"})

        msg = messages[0]
        from_number = msg["from"]
        text = msg.get("text", {}).get("body", "").strip()

        if not text:
            return JSONResponse({"status": "no_text"})

        lower = text.lower()

        # 1) PRIMER PASO: INTENTO DE CITA
        if any(word in lower for word in ["cita", "hora", "visita", "limpieza", "revisión"]):
            send_whatsapp_message(
                from_number,
                "Perfecto 🦷\n"
                "Para reservar, dime tu *nombre* y *día en formato AAAA-MM-DD*.\n"
                "Ejemplo: Raúl, 2025-11-30"
            )
            return JSONResponse({"status": "asking_for_name_and_date"})

        # 2) SEGUNDO PASO: MENSAJE TIPO 'Nombre, 2025-11-30'
        if "," in text:
            try:
                name, day = text.split(",", 1)
                name = name.strip()
                day = day.strip()

                ok, link, err = create_calendar_event(name, day)

                if ok:
                    send_whatsapp_message(
                        from_number,
                        f"¡Cita creada! 📅\n{name}, te esperamos el {day}.\n\n"
                        f"Te dejo el enlace de confirmación:\n{link}"
                    )
                else:
                    send_whatsapp_message(
                        from_number,
                        "He intentado crear la cita pero ha ocurrido un error 😓.\n"
                        "Por favor, inténtalo más tarde o contacta directamente con la clínica."
                    )

                return JSONResponse({"status": "calendar_attempt"})

            except Exception as e:
                print("Error parseando nombre/fecha:", e)
                # Si falla, seguimos al flujo normal de IA

        # 3) IA PARA PREGUNTAS GENERALES
        answer = answer_with_openai(text)
        send_whatsapp_message(from_number, answer)
        return JSONResponse({"status": "answered_with_ai"})

    except Exception as e:
        print("Error parsing webhook:", e)
        return JSONResponse({"status": "error", "details": str(e)})

# ========= ROOT =========
@app.get("/")
async def root():
    return {"status": "ok", "message": "WhatsApp bot + OpenAI + Google Calendar funcionando"}