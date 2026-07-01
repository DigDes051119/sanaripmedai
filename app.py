import os
import requests
from dotenv import load_dotenv

load_dotenv()

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
if not DEEPSEEK_API_KEY:
    raise RuntimeError("Отсутствует DEEPSEEK_API_KEY в переменных окружения.")

DEEPSEEK_URL = "https://api.deepseek.com/v1/chat/completions"
MODEL_NAME = "deepseek-v4-flash"

SYSTEM_PROMPT = (
    "Ты — дружелюбный и очень casual медицинский ассистент по имени Санарип. "
    "Общайся на русском языке, используй разговорный стиль, как будто переписываешься с другом. "
    "Не используй официальный тон, будь расслабленным и приветливым."
)

def ask_deepseek(prompt: str) -> str:
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

if __name__ == "__main__":
    print(ask_deepseek("Привет, что такое мигрень?"))
