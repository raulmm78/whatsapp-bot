import os
import requests
from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware
from openai import OpenAI

# =========================
# CONFIG
# =========================

# Variables de entorno (las pondrás en Render)
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")              # tu access token de Meta
WHATSAPP_PHONE_ID = os.getenv("WHATSAPP_PHONE_ID")        # Phone number ID
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "mi_verify_token")  # el que tú elijas
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

client = OpenAI(api_key=OPENAI_API_KEY)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =========================
# RUTA DE VERIFICACIÓN WEBHOOK (GET)
# =========================

@app.get("/webhook", response_class=PlainTextResponse)
async def verify(
    hub_mode: str = "",
    hub_challenge: str = "",
    hub_verify_token: str = "",
):
    """
    Meta llama aquí cuando configuras el webhook.
    Si el VERIFY_TOKEN coincide, devolvemos el challenge.
    """
    if hub_mode == "subscribe" and hub_verify_token == VERIFY_TOKEN:
        return hub_challenge
    return "Error de verificación"


# =========================
# RUTA DE MENSAJES (POST)
# =========================

@app.post("/webhook")
async def webhook_whatsapp(request: Request):
    """
    Meta enviará los mensajes entrantes aquí.
    Leemos el texto, llamamos a OpenAI y respondemos por WhatsApp.
    """
    data = await request.json()
    # print(data)  # para debug

    # Comprobamos que hay un mensaje
    try:
        entry = data["entry"][0]
        changes = entry["changes"][0]
        value = changes["value"]
        messages = value.get("messages", [])

        if not messages:
            return {"status": "no_messages"}

        message = messages[0]
        from_number = message["from"]  # número del usuario
        message_type = message["type"]

        if message_type == "text":
            user_text = message["text"]["body"]
        else:
            # si no es texto, respondemos algo genérico
            user_text = "Solo puedo responder a mensajes de texto por ahora 😊"
    except Exception:
        # Si la estructura no es la esperada, simplemente devolvemos ok
        return {"status": "ignored"}

    # =========================
    # LÓGICA DEL BOT (IA)
    # =========================

    # Si el mensaje contiene "cita", "reservar", etc. hacemos un comportamiento especial
    lower_text = user_text.lower()
    if any(pal in lower_text for pal in ["cita", "reservar", "reserva", "appointment"]):
        system_prompt = (
            "Eres un asistente de reservas para un negocio. "
            "Pregunta al usuario por día y hora que le vienen bien, "
            "y confirma la cita de forma amable. "
            "NO inventes calendario real, solo propón que se confirmará por mensaje."
        )
    else:
        system_prompt = (
            "Eres un asistente de un negocio que responde dudas de forma clara, "
            "corta y amable. Da respuestas prácticas."
        )

    completion = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_text},
        ],
        temperature=0.5,
    )

    reply_text = completion.choices[0].message.content.strip()

    # =========================
    # ENVIAR RESPUESTA POR WHATSAPP
    # =========================

    wa_url = f"https://graph.facebook.com/v20.0/{WHATSAPP_PHONE_ID}/messages"

    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json",
    }

    payload = {
        "messaging_product": "whatsapp",
        "to": from_number,
        "type": "text",
        "text": {"body": reply_text},
    }

    r = requests.post(wa_url, headers=headers, json=payload)
    # print(r.status_code, r.text)  # debug si algo falla

    return {"status": "ok"}
