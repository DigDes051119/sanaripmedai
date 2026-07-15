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
        
        # Передаем обновление в bot для обработки диспетчерами в фоновом потоке,
        # чтобы избежать таймаутов ответа Telegram (Read timeout expired) при долгой генерации ИИ.
        import threading
        threading.Thread(target=bot.process_new_updates, args=([update],), daemon=True).start()
        return "OK", 200
    else:
        abort(403)

@app.route("/test_telegram")
def test_telegram():
    import requests
    results = {}
    
    # 1. Тест прямого Telegram API (таймаут 15 сек)
    try:
        r = requests.get("https://api.telegram.org", timeout=15)
        results["direct_api"] = f"Success (Status: {r.status_code})"
    except Exception as e:
        results["direct_api"] = f"Failed: {e}"
        
    # 2. Тест Cloudflare Worker Proxy с разными заголовками и SSL-настройками
    # Тест А: Обычный запрос (без User-Agent)
    try:
        r = requests.get("https://fancy-mountain-f16b.sanaripmedai.workers.dev", timeout=10)
        results["worker_default"] = f"Success (Status: {r.status_code})"
    except Exception as e:
        results["worker_default"] = f"Failed: {e}"
        
    # Тест Б: С браузерным User-Agent (обход блокировок роботов на Cloudflare)
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
        r = requests.get("https://fancy-mountain-f16b.sanaripmedai.workers.dev", headers=headers, timeout=10)
        results["worker_with_user_agent"] = f"Success (Status: {r.status_code})"
    except Exception as e:
        results["worker_with_user_agent"] = f"Failed: {e}"
        
    # Тест В: Форсирование TLS 1.2 (для устранения несовместимости OpenSSL и Cloudflare TLS 1.3)
    try:
        import ssl
        class TLS12Adapter(requests.adapters.HTTPAdapter):
            def init_poolmanager(self, *args, **kwargs):
                context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
                context.minimum_version = ssl.TLSVersion.TLSv1_2
                context.maximum_version = ssl.TLSVersion.TLSv1_2
                kwargs['ssl_context'] = context
                return super().init_poolmanager(*args, **kwargs)
                
        session = requests.Session()
        session.mount("https://", TLS12Adapter())
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
        r = session.get("https://fancy-mountain-f16b.sanaripmedai.workers.dev", headers=headers, timeout=10)
        results["worker_tls12_with_ua"] = f"Success (Status: {r.status_code})"
    except Exception as e:
        results["worker_tls12_with_ua"] = f"Failed: {e}"


        
    # 3. Тест Google.com (для проверки общего интернета)
    try:
        r = requests.get("https://www.google.com", timeout=10)
        results["google_com"] = f"Success (Status: {r.status_code})"
    except Exception as e:
        results["google_com"] = f"Failed: {e}"
        
    # 4. Проверка внешнего IP контейнера
    try:
        r = requests.get("https://httpbin.org/ip", timeout=10)
        results["container_ip"] = f"Success (IP: {r.json().get('origin')})"
    except Exception as e:
        results["container_ip"] = f"Failed: {e}"
        
    # Форматируем красивый вывод
    html_output = "<h1>Диагностика сети Telegram API (Расширенная)</h1>"
    for name, res in results.items():
        html_output += f"<p><b>{name}:</b> {res}</p>"
    return html_output, 200



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

# ─── Keep-alive: предотвращение засыпания HF Space ─────────────────────────────
def start_keep_alive():
    """Фоновый поток, который пингует свой /health каждые 25 минут,
    чтобы Hugging Face Space не уходил в sleep из-за неактивности."""
    import threading
    import time
    import requests as req

    def ping_loop():
        # Даём серверу время полностью стартовать
        time.sleep(60)
        port = int(os.environ.get("PORT", 7860))
        health_url = f"http://localhost:{port}/health"
        print(f"[Keep-Alive] Started. Pinging {health_url} every 25 minutes.")
        while True:
            try:
                r = req.get(health_url, timeout=10)
                print(f"[Keep-Alive] Ping OK (status={r.status_code})")
            except Exception as e:
                print(f"[Keep-Alive] Ping failed: {e}")
            time.sleep(25 * 60)  # 25 минут

    threading.Thread(target=ping_loop, daemon=True).start()


# Вызываем настройку вебхука и keep-alive при старте
init_webhook()
start_keep_alive()


if __name__ == "__main__":
    from waitress import serve
    port = int(os.environ.get("PORT", 7860))
    print(f"[STARTUP] Starting waitress production WSGI server on port {port}...")
    serve(app, host="0.0.0.0", port=port, threads=8)

