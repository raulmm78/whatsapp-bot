from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse
import os
import httpx
import openai


# -------------------------
# CONFIG
# -------------------------

VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

openai.api_key = OPENAI_API_KEY

app = FastAPI()


# -------------------------
# WEBHOOK VERIFICATION
# -------------------------
@app.get("/webhook", response_class=PlainTextResponse)
async def verify(request: Request):
    """
    Meta envía GET con:
    hub.mode
    hub.verify_token
    hub.challenge
    """
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        return challenge  # Meta requiere texto plano

    return PlainTextResponse("Error: invalid token", status_code=403)


# -------------------------
# RECEPCIÓN DE MENSAJES
# -------------------------
@app.post("/webhook")
async def webhook_handler(request: Request):
    data = await request.json()

    # Meta envía mensajes así:
    # data["entry"][0]["changes"][0]["value"]["messages"][0]
    try:
        entry = data.get("entry", [])[0]
        changes = entry.get("changes", [])[0]
        value = changes.get("value", {})
        messages = value.get("messages")

        if messages:
            message = messages[0]
            phone = message["from"]
            text = message["text"]["body"]

            # Respuesta con OpenAI
            reply = await generate_reply(text)

            # Enviar mensaje por WhatsApp
            await send_whatsapp_message(phone, reply)

    except Exception as e:
        print("Error procesando mensaje:", e)

    return {"status": "ok"}


# -------------------------
# OPENAI: GENERAR RESPUESTA
# -------------------------
async def generate_reply(user_text: str) -> str:
    try:
        response = openai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system",
                 "content": "Eres un chatbot amable y útil del negocio. Responde de forma clara y breve."},
                {"role": "user", "content": user_text}
            ]
        )
        return response.choices[0].message.content

    except Exception as e:
        print("Error con OpenAI:", e)
        return "Lo siento, ahora mismo no puedo responder."


# -------------------------
# ENVIAR MENSAJE A WHATSAPP
# -------------------------
async def send_whatsapp_message(to_number: str, text: str):
    url = f"https://graph.facebook.com/v17.0/{WHATSAPP_PHONE_NUMBER_ID}/messages"

    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }

    payload = {
        "messaging_product": "whatsapp",
        "to": to_number,
        "type": "text",
        "text": {"body": text}
    }

    async with httpx.AsyncClient() as client:
        r = await client.post(url, headers=headers, json=payload)
        print("WhatsApp SEND status:", r.status_code, r.text)