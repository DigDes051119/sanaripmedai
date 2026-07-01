import os
from flask import Flask, request, jsonify
import requests
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

# --- переменные окружения ---
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_WHATSAPP_NUMBER = os.getenv("TWILIO_WHATSAPP_NUMBER")  # например "whatsapp:+14155238886"

if not DEEPSEEK_API_KEY:
    raise RuntimeError("Отсутствует DEEPSEEK_API_KEY в переменных окружения.")

# --- настройки DeepSeek ---
DEEPSEEK_URL = "https://api.deepseek.com/v1/chat/completions"
MODEL_NAME = "deepseek-v4-flash"

SYSTEM_PROMPT = (
    "Ты — дружелюбный и очень casual медицинский ассистент по имени Санарип. "
    "Общайся на русском языке, используй разговорный стиль, как будто переписываешься с другом. "
    "Не используй официальный тон, будь расслабленным и приветливым."
)

def ask_deepseek(prompt: str) -> str:
    """Отправляет сообщение в DeepSeek и возвращает текстовый ответ."""
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": MODEL_NAME,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.8,
    }
    resp = requests.post(DEEPSEEK_URL, json=payload, headers=headers, timeout=30)
    if resp.status_code != 200:
        raise Exception(f"Ошибка DeepSeek API: {resp.status_code} {resp.text}")

    data = resp.json()
    if "choices" in data and len(data["choices"]) > 0:
        return data["choices"][0]["message"]["content"]
    else:
        raise Exception("Ответ от модели отсутствует.")

# --- вебхук для WhatsApp (Twilio) ---
@app.route("/webhook", methods=["GET"])
def verify():
    """Пустой GET‑ответ для проверки вебхука (Twilio не использует, но оставим)."""
    return "Webhook ready", 200

@app.route("/webhook", methods=["POST"])
def whatsapp_webhook():
    """Принимает входящие сообщения WhatsApp через Twilio, обрабатывает и отвечает."""
    incoming_msg = request.form.get("Body")
    sender = request.form.get("From")

    if not incoming_msg:
        return "OK", 200

    # Получаем ответ от ИИ‑ассистента
    try:
        ai_response = ask_deepseek(incoming_msg)
    except Exception as e:
        ai_response = "Блин, что-то пошло не так. Попробуй позже. 😕"
        print("DeepSeek error:", e)

    # Отправляем ответ обратно через Twilio API
    twilio_url = (
        f"https://api.twilio.com/2010-04-01/Accounts/{TWILIO_ACCOUNT_SID}/Messages.json"
    )
    reply_payload = {
        "From": TWILIO_WHATSAPP_NUMBER,
        "To": sender,
        "Body": ai_response,
    }
    try:
        reply_resp = requests.post(
            twilio_url,
            data=reply_payload,
            auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN),
            timeout=30,
        )
        if reply_resp.status_code != 201:
            print("Не удалось отправить ответ:", reply_resp.text)
    except Exception as e:
        print("Ошибка отправки через Twilio:", e)

    return "OK", 200

if __name__ == "__main__":
    print("Хей! Санарип AI Medical Assistant готов к работе. 🩺")
    app.run(debug=True, port=5000)
