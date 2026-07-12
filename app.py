import os
import sys
from flask import Flask, request, abort
import telebot

# Добавляем текущую директорию в path, чтобы корректно импортировать telegram_bot
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from telegram_bot import bot, token_missing

app = Flask(__name__)

@app.route("/")
@app.route("/health")
def health():
    return "<h1>Sanarip Med AI</h1><p>Status: Running</p>", 200

@app.route("/webhook", methods=["POST"])
def webhook():
    if request.headers.get("content-type") == "application/json":
        json_string = request.get_data().decode("utf-8")
        update = telebot.types.Update.de_json(json_string)
        
        # Передаем обновление в bot для обработки диспетчерами
        bot.process_new_updates([update])
        return "OK", 200
    else:
        abort(403)

def init_webhook():
    """Настройка вебхука Telegram бота в фоновом режиме"""
    import threading
    
    def run_setup():
        if token_missing:
            print("[Webhook] WARNING: Токен отсутствует или является заглушкой. Пропускаем регистрацию вебхука.")
            return
            
        webhook_url = os.getenv("WEBHOOK_URL")
        
        # Автоматическое определение URL на Hugging Face Spaces
        if not webhook_url and os.getenv("SPACE_ID"):
            space_id = os.getenv("SPACE_ID") # e.g. "username/space-name"
            subdomain = space_id.replace("/", "-").lower().replace("_", "-")
            webhook_url = f"https://{subdomain}.hf.space"
            print(f"[Webhook] Auto-detected Hugging Face Space URL: {webhook_url}")
            
        if webhook_url:
            full_webhook_url = f"{webhook_url.rstrip('/')}/webhook"
            print(f"[Webhook] Setting Telegram webhook to: {full_webhook_url} ...")
            try:
                bot.remove_webhook()
                # Устанавливаем вебхук с увеличенным тайм-аутом
                success = bot.set_webhook(url=full_webhook_url, timeout=30)
                if success:
                    print("[Webhook] Webhook successfully set.")
                else:
                    print("[Webhook] ERROR: Failed to set webhook.")
            except Exception as e:
                print(f"[Webhook] Error configuring webhook: {e}")
        else:
            print("[Webhook] WARNING: WEBHOOK_URL is not set. Bot webhook not configured.")

    # Запускаем в фоновом потоке, чтобы сетевые задержки Telegram не тормозили старт Flask
    threading.Thread(target=run_setup, daemon=True).start()

# Вызываем настройку вебхука при старте
init_webhook()


if __name__ == "__main__":
    from waitress import serve
    port = int(os.environ.get("PORT", 7860))
    print(f"[STARTUP] Starting waitress production WSGI server on port {port}...")
    serve(app, host="0.0.0.0", port=port, threads=8)

