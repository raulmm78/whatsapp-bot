from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware
import os
import requests
from openai import OpenAI
import json

app = FastAPI()

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ENV VARS
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

WHATSAPP_URL = f"https://graph.facebook.com/v20.0/{WHATSAPP_PHONE_NUMBER_ID}/messages"
client = OpenAI(api_key=OPENAI_API_KEY)

# ========== LOAD PDF INTO CONTEXT ==========
with open("dental_info.pdf", "rb") as f:
    dental_pdf = f.read()

pdf_text = """
CLÍNICA DENTAL SONRISA — INFORMACIÓN GENERAL

Tratamientos y precios:
- Limpieza dental: 45€
- Ortodoncia invisible: desde 65€/mes
- Blanqueamiento dental: 150€
- Implantes: 950€
- Empaste: 60€

Horarios:
Lunes a Viernes: 09:00–14:00 / 16:00–20:00
Sábados: 10:00–14:00

Teléfono:
General: +34 900 000 000
Urgencias: +34 611 222 333

Ubicación:
Calle Falsa 123, Madrid

Preguntas frecuentes:
¿Duele un implante? No, hay anestesia.
¿Hacéis financiación? Sí, hasta 24 meses.
¿Aceptáis seguros? Sí, Adeslas, Sanitas, Mapfre.
"""

# ========== WHATSAPP SEND ==========
def send_whatsapp_message(to, message):
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "text": {"body": message}
    }
    requests.post(WHATSAPP_URL, headers=headers, json=payload)


# ========== MENÚ PRINCIPAL ==========
def main_menu():
    return (
        "👋 *Clínica Dental Sonrisa*\n"
        "Soy tu asistente virtual. Elige una opción:\n\n"
        "1️⃣ Tratamientos\n"
        "2️⃣ Precios\n"
        "3️⃣ Horario\n"
        "4️⃣ Ubicación\n"
        "5️⃣ Pedir cita\n"
        "6️⃣ Preguntas frecuentes\n"
        "0️⃣ Hablar con un humano"
    )


# ========== IA RESPONSE (RAG SIMPLE) ==========
def ai_answer(user_message):
    system_prompt = f"""
Eres el asistente virtual de una clínica dental.
Debes responder SOLO con la información del PDF:

{pdf_text}

Si el usuario pide precios, horarios, tratamientos, etc, respóndelo exactamente.
No inventes nada que no esté arriba.
"""

    completion = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message}
        ]
    )

    return completion.choices[0].message["content"]


# ========== VERIFY WEBHOOK ==========
@app.get("/webhook")
async def verify_webhook(hub_mode: str = None, hub_challenge: str = None, hub_verify_token: str = None):
    if hub_mode == "subscribe" and hub_verify_token == VERIFY_TOKEN:
        return PlainTextResponse(hub_challenge)
    return PlainTextResponse("Invalid token", 403)


# ========== HANDLE MESSAGES ==========
@app.post("/webhook")
async def webhook_handler(request: Request):
    data = await request.json()
    print("Incoming:", json.dumps(data, indent=2))

    try:
        entry = data["entry"][0]
        change = entry["changes"][0]["value"]

        if "messages" in change:
            msg = change["messages"][0]
            from_number = msg["from"]
            text = msg["text"]["body"].strip().lower()

            # ───────────────────────────
            #           MENÚS
            # ───────────────────────────
            if text in ["hola", "menu", "inicio", "start"]:
                send_whatsapp_message(from_number, main_menu())
                return {"status": "ok"}

            if text == "1":
                send_whatsapp_message(from_number, "Tratamientos disponibles:\n- Limpieza\n- Ortodoncia\n- Implantes\n- Blanqueamiento\n\n¿Sobre cuál quieres más info?")
                return {"status": "ok"}

            if text == "2":
                send_whatsapp_message(from_number, "💰 *Precios*\n- Limpieza: 45€\n- Ortodoncia: desde 65€/mes\n- Blanqueamiento: 150€\n- Empaste: 60€")
                return {"status": "ok"}

            if text == "3":
                send_whatsapp_message(from_number, "🕒 Horario:\nL-V 09–14 / 16–20\nSábados 10–14")
                return {"status": "ok"}

            if text == "4":
                send_whatsapp_message(from_number, "📍 Ubicación:\nCalle Falsa 123, Madrid")
                return {"status": "ok"}

            if text == "5":
                send_whatsapp_message(from_number, "Para pedir cita envía tu nombre + día deseado. Un humano te confirmará.")
                return {"status": "ok"}

            if text == "6":
                answer = ai_answer(text)
                send_whatsapp_message(from_number, answer)
                return {"status": "ok"}

            if text == "0":
                send_whatsapp_message(from_number, "📞 Derivando a un humano…")
                return {"status": "ok"}

            # ───────────────────────────
            #     IA GENERAL (fallback)
            # ───────────────────────────
            answer = ai_answer(text)
            send_whatsapp_message(from_number, answer)

    except Exception as e:
        print("Error:", e)

    return {"status": "ok"}


@app.get("/")
async def root():
    return {"status": "running"}