from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse
import os
import requests

app = FastAPI()

VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
WHATSAPP_API_URL = "https://graph.facebook.com/v20.0/"  # versión estable
WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID")


# ========== VERIFY WEBHOOK (GET) ==========
@app.get("/webhook")
async def verify_webhook(hub_mode: str = None, hub_challenge: str = None, hub_verify_token: str = None):
    if hub_mode == "subscribe" and hub_verify_token == VERIFY_TOKEN:
        return PlainTextResponse(content=hub_challenge, status_code=200)
    return PlainTextResponse(content="Invalid verify token", status_code=403)


# ========== RECEIVE MESSAGES (POST) ==========
@app.post("/webhook")
async def webhook_handler(request: Request):
    data = await request.json()

    # Debug
    print("Incoming:", data)

    # Comprobar estructura del webhook
    try:
        entry = data["entry"][0]
        changes = entry["changes"][0]
        value = changes["value"]
        messages = value.get("messages")

        if messages:
            phone_number_id = value["metadata"]["phone_number_id"]
            msg = messages[0]
            from_number = msg["from"]
            text = msg["text"]["body"]

            # Respuesta básica del bot (sin OpenAI)
            reply_text = f"Bot activo 👍\nRecibí tu mensaje: {text}"

            send_whatsapp_message(from_number, reply_text)

    except Exception as e:
        print("Error parsing message:", e)

    return {"status": "ok"}


# ========== SEND MESSAGE TO WHATSAPP ==========
def send_whatsapp_message(to, message):
    url = f"{WHATSAPP_API_URL}{WHATSAPP_PHONE_NUMBER_ID}/messages"
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
    return r.text


# ROOT 404
@app.get("/")
async def root():
    return {"status": "ok", "message": "WhatsApp bot is running"}