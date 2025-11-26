from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse
import os
import requests
from openai import OpenAI

app = FastAPI()

# ====== ENV VARS ======
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")  # META access token
PHONE_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID")
OPENAI_KEY = os.getenv("OPENAI_API_KEY")

client = OpenAI(api_key=OPENAI_KEY)

WHATSAPP_URL = f"https://graph.facebook.com/v20.0/{PHONE_ID}/messages"

# ====== RAG: BASE DE CONOCIMIENTO ======
PDF_TEXT = """
CLÍNICA DENTAL MARTÍNEZ – INFORMACIÓN COMPLETA
=================================================

Somos una clínica dental situada en Madrid, especializada en tratamientos modernos con un trato cercano, humano y profesional.

FILOSOFÍA
---------
En Clínica Dental Martínez buscamos que cada paciente se sienta en casa:
- Trato cercano y amable.
- Atención personalizada.
- Diagnósticos claros y sin tecnicismos.
- Comodidad y cero dolor gracias a técnicas modernas y anestesia eficaz.

TRATAMIENTOS PRINCIPALES
------------------------
1. Implantes dentales
   - Reemplazo fijo y duradero del diente.
   - Técnica guiada mínimamente invasiva.
   - No duele gracias a anestesia local.

2. Ortodoncia invisible
   - Alineadores transparentes.
   - Cómodos, discretos y removibles.
   - Ideal para adultos.

3. Limpieza dental / Profilaxis
   - Eliminación de sarro y manchas.
   - Se recomienda cada 6 meses.

4. Endodoncia
   - Tratamiento del nervio del diente.
   - Se realiza sin dolor.

5. Estética dental
   - Carillas.
   - Blanqueamientos.
   - Remodelación estética.

PREGUNTAS FRECUENTES (FAQ)
--------------------------
¿Duele un implante?
→ No duele. Se realiza con anestesia local y técnicas guiadas.

¿Ofrecen financiación?
→ Sí, financiamos la mayoría de tratamientos entre 3 y 24 meses.

¿Puedo pedir cita por WhatsApp?
→ Sí, solo necesitamos nombre + día deseado.

¿Atendéis urgencias?
→ Sí, de lunes a sábado dentro del horario disponible.

¿Trabajáis con niños?
→ Sí, ofrecemos odontopediatría básica.

PRECIOS ORIENTATIVOS
---------------------
- Limpieza dental: desde 45€
- Blanqueamiento dental: 150€
- Ortodoncia invisible: desde 65€/mes
- Implante dental completo: desde 900€
- Empaste dental: 60€

HORARIO
-------
Lunes a Viernes: 10:00 – 14:00 / 17:00 – 21:00  
Sábados: 10:00 – 14:00  
Domingos: cerrado

CONTACTO
--------
Teléfono: 900 000 000  
WhatsApp: este mismo número  
Email: info@clinicadentalmartinez.es  
Dirección: Calle Martínez, Madrid  

CÓMO TRABAJAMOS
----------------
1. Revisión inicial gratuita.
2. Diagnóstico y explicación del tratamiento.
3. Plan económico y financiación si se necesita.
4. Tratamiento moderno y sin dolor.
5. Revisión y seguimiento personalizado.
"""

# ====== MENÚ PRINCIPAL ======
MENU_TEXT = """
¡Hola! 👋 Soy el asistente virtual de **Clínica Dental Martínez**.
¿En qué puedo ayudarte hoy?

1️⃣ Información sobre tratamientos  
2️⃣ Precios aproximados  
3️⃣ Pedir cita  
4️⃣ Urgencias dentales  
5️⃣ Horarios y dirección  

Escribe solo el número o tu pregunta directamente.
"""


# ====== VERIFICACIÓN DEL WEBHOOK ======
@app.get("/webhook")
async def verify_webhook(hub_mode: str = None, hub_challenge: str = None, hub_verify_token: str = None):
    if hub_mode == "subscribe" and hub_verify_token == VERIFY_TOKEN:
        return PlainTextResponse(content=hub_challenge, status_code=200)
    return PlainTextResponse(content="Invalid verify token", status_code=403)


# ====== PROCESADO DE MENSAJES ======
@app.post("/webhook")
async def whatsapp_webhook(request: Request):
    data = await request.json()
    print("Incoming:", data)

    try:
        entry = data["entry"][0]
        changes = entry["changes"][0]
        value = changes["value"]

        if "messages" in value:
            message = value["messages"][0]
            from_number = message["from"]
            text = message["text"]["body"].strip().lower()

            # MENÚ RÁPIDO
            if text in ["menu", "hola", "hi", "buenas"]:
                send_whatsapp(from_number, MENU_TEXT)
                return {"status": "menu"}

            # OPCIONES DE MENÚ
            if text == "1":
                reply = "Estos son los tratamientos principales:\n- Implantes\n- Ortodoncia invisible\n- Limpiezas\n- Estética dental\n\nPregunta por cualquiera."
                send_whatsapp(from_number, reply)
                return {"status": "ok"}

            if text == "2":
                reply = "Precios aproximados:\n- Limpieza: 45€\n- Blanqueamiento: 150€\n- Ortodoncia invisible: desde 65€/mes\n- Implante: desde 900€"
                send_whatsapp(from_number, reply)
                return {"status": "ok"}

            if text == "3":
                send_whatsapp(from_number, "Perfecto 🦷\nPara pedir cita dime:\n👉 *Tu nombre*\n👉 *Día y hora deseada*")
                return {"status": "ok"}

            if text == "4":
                send_whatsapp(from_number, "Atendemos urgencias de Lunes a Sábado.\nEnvíame tu problema y te doy una solución rápida.")
                return {"status": "ok"}

            if text == "5":
                send_whatsapp(from_number, "📍 Calle Martínez, Madrid\n🕒 L-V 10-14 / 17-21\nSábados 10-14")
                return {"status": "ok"}

            # ====== PREGUNTAS LIBRES CON RAG ======
            full_prompt = f"""
Eres el asistente virtual de una clínica dental. Responde de forma amable y cercana.
Usa SOLO la información del siguiente documento y NUNCA inventes nada:

DOCUMENTO:
{PDF_TEXT}

PREGUNTA DEL PACIENTE:
{text}

RESPUESTA:
"""

            completion = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": full_prompt}],
                max_tokens=300
            )

            answer = completion.choices[0].message.content
            send_whatsapp(from_number, answer)

    except Exception as e:
        print("Error:", e)

    return {"status": "ok"}


# ====== ENVÍO DE MENSAJES ======
def send_whatsapp(to, message):
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json",
    }

    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "text": {"body": message},
    }

    print("Sending:", payload)

    r = requests.post(WHATSAPP_URL, headers=headers, json=payload)
    print("WhatsApp response:", r.status_code, r.text)


# ====== ROOT ======
@app.get("/")
async def root():
    return {"status": "ok", "message": "WhatsApp bot with RAG running"}