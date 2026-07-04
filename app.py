import os
import requests
from flask import Flask, request, jsonify, render_template_string
from dotenv import load_dotenv

# Загружаем переменные окружения
load_dotenv()

# Импортируем бота для работы через вебхуки на Vercel
import telebot
from telegram_bot import bot

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
WHATSAPP_VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN")
WHATSAPP_ACCESS_TOKEN = os.getenv("WHATSAPP_ACCESS_TOKEN")

if not DEEPSEEK_API_KEY:
    print("WARNING: Отсутствует DEEPSEEK_API_KEY в переменных окружения.")

app = Flask(__name__)

DEEPSEEK_URL = "https://api.deepseek.com/v1/chat/completions"
MODEL_NAME = "deepseek-chat"  # DeepSeek V3/V4 chat model name

SYSTEM_PROMPT = (
    "Ты — дружелюбный и очень casual медицинский ассистент по имени Санарип. "
    "Общайся на русском языке, используй разговорный стиль, как будто переписываешься с другом. "
    "Не используй официальный тон, будь расслабленным и приветливым. "
    "Помни: твоя задача — первичный триаж. Если ситуация выглядит серьезной, рекомендуй обратиться в 103 "
    "или клиники Бишкека."
)

def ask_deepseek(prompt: str) -> str:
    """Отправляет запрос к DeepSeek API"""
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

def send_whatsapp_message(to_phone: str, text: str, phone_number_id: str):
    """Отправляет сообщение пользователю в WhatsApp через Cloud API"""
    url = f"https://graph.facebook.com/v18.0/{phone_number_id}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to_phone,
        "type": "text",
        "text": {
            "body": text
        }
    }
    resp = requests.post(url, json=payload, headers=headers, timeout=15)
    if resp.status_code not in [200, 201]:
        print(f"Ошибка отправки WhatsApp: {resp.status_code} {resp.text}")
    else:
        print(f"Ответ успешно отправлен на номер: {to_phone}")

@app.route("/", methods=["GET"])
def home():
    return """
    <h1>Sanarip Med AI Webhook Server is running!</h1>
    <ul>
        <li><a href="/dashboard">🚑 Dashboard (Заявки скорой помощи)</a></li>
        <li><a href="/developer">🛠️ Developer Panel (Диалоги с ИИ)</a></li>
    </ul>
    """

@app.route("/dashboard", methods=["GET"])
def dashboard():
    import json
    import os
    
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    file_path = os.path.join(BASE_DIR, "data", "emergency_requests.json")
    requests_list = []
    if os.path.exists(file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                requests_list = json.load(f).get("requests", [])
        except Exception as e:
            print(f"Error reading requests: {e}")
            
    districts = {
        "Ленинский": [],
        "Октябрьский": [],
        "Первомайский": [],
        "Свердловский": [],
        "Другие регионы": []
    }
    
    for req in requests_list:
        reg = req.get("region", "Другие регионы")
        # Match keys accurately
        matched = False
        for key in districts.keys():
            if key.lower() in reg.lower():
                districts[key].append(req)
                matched = True
                break
        if not matched:
            districts["Другие регионы"].append(req)
            
    total_count = len(requests_list)
    
    template = """
    <!DOCTYPE html>
    <html lang="ru">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            :root {
                --bg-light: #f3f4f6;
                --card-bg: #ffffff;
                --card-border: #e5e7eb;
                --text-primary: #1f2937;
                --text-secondary: #4b5563;
                --accent-red: #dc2626;
            }
            
            * {
                box-sizing: border-box;
                margin: 0;
                padding: 0;
            }
            
            body {
                font-family: 'Segoe UI', -apple-system, BlinkMacSystemFont, Roboto, sans-serif;
                background-color: var(--bg-light);
                color: var(--text-primary);
                min-height: 100vh;
                padding: 3.5rem;
                overflow-x: hidden;
                letter-spacing: -0.01em;
            }
            
            .container {
                max-width: 1600px;
                margin: 0 auto;
            }
            
            header {
                display: flex;
                justify-content: space-between;
                align-items: center;
                margin-bottom: 4rem;
                border-bottom: 1px solid #d1d5db;
                padding-bottom: 2rem;
            }
            
            h1 {
                font-size: 1.8rem;
                font-weight: 600;
                color: #111827;
                display: flex;
                align-items: center;
                gap: 0.75rem;
            }
            
            .stats-badge {
                background: #fee2e2;
                border: 1px solid #fca5a5;
                padding: 0.6rem 1.4rem;
                border-radius: 4px;
                font-weight: 600;
                color: #dc2626;
                font-size: 0.9rem;
            }
            
            .dashboard-grid {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
                gap: 2.5rem;
                align-items: start;
            }
            
            .district-column {
                background: #ffffff;
                border: 1px solid var(--card-border);
                border-radius: 8px;
                padding: 2.25rem;
                display: flex;
                flex-direction: column;
                gap: 2rem;
                box-shadow: 0 1px 3px rgba(0, 0, 0, 0.02), 0 1px 2px rgba(0, 0, 0, 0.04);
            }
            
            .district-header {
                display: flex;
                justify-content: space-between;
                align-items: center;
                border-bottom: 2px solid var(--bg-light);
                padding-bottom: 1.25rem;
            }
            
            .district-title {
                font-size: 1.15rem;
                font-weight: 600;
                color: #111827;
                display: flex;
                align-items: center;
                gap: 0.5rem;
            }
            
            .district-count {
                background: var(--bg-light);
                padding: 0.25rem 0.75rem;
                border-radius: 4px;
                font-size: 0.85rem;
                font-weight: 600;
                color: var(--text-secondary);
            }
            
            .request-card {
                background: #ffffff;
                border: 1px solid var(--card-border);
                border-radius: 6px;
                padding: 1.75rem;
                display: flex;
                flex-direction: column;
                gap: 1.25rem;
                position: relative;
                overflow: hidden;
                box-shadow: 0 1px 2px rgba(0, 0, 0, 0.01);
                transition: all 0.2s ease;
            }
            
            .request-card:hover {
                background: #fafafa;
                border-color: #fca5a5;
                box-shadow: 0 4px 12px rgba(0, 0, 0, 0.05);
            }
            
            .request-card::before {
                content: '';
                position: absolute;
                left: 0;
                top: 0;
                bottom: 0;
                width: 4px;
                background: var(--accent-red);
            }
            
            .request-header {
                display: flex;
                justify-content: space-between;
                align-items: flex-start;
                margin-bottom: 0.25rem;
            }
            
            .patient-name {
                font-weight: 600;
                font-size: 1.15rem;
                color: #111827;
            }
            
            .timestamp {
                font-size: 0.75rem;
                color: var(--text-secondary);
            }
            
            .info-item {
                display: flex;
                flex-direction: column;
                gap: 0.5rem;
                font-size: 0.9rem;
            }
            
            .info-label {
                color: var(--text-secondary);
                font-size: 0.8rem;
                text-transform: uppercase;
                letter-spacing: 0.08em;
                font-weight: 600;
            }
            
            .info-val {
                color: var(--text-primary);
                line-height: 1.6;
            }
            
            .no-requests {
                color: var(--text-secondary);
                font-style: italic;
                font-size: 0.9rem;
                text-align: center;
                padding: 3rem 0;
            }
            
            .lucide {
                width: 18px;
                height: 18px;
                vertical-align: middle;
                display: inline-block;
                stroke-width: 2px;
            }
            
            h1 .lucide {
                width: 28px;
                height: 28px;
                color: var(--accent-red);
                margin-right: 0.5rem;
            }
            
            .district-title .lucide {
                color: var(--text-secondary);
                margin-right: 0.25rem;
            }
            
            .info-label .lucide {
                width: 14px;
                height: 14px;
                margin-right: 0.35rem;
                vertical-align: -2px;
            }
        </style>
        <script src="https://unpkg.com/lucide@latest"></script>
        <script>
            setInterval(() => {
                window.location.reload();
            }, 5000);
        </script>
    </head>
    <body>
        <div class="container">
            <header>
                <h1><i data-lucide="alert-triangle"></i> Панель Заявок Скорой Помощи</h1>
                <div class="stats-badge">Активных вызовов: {{ total_count }}</div>
            </header>
            
            <div class="dashboard-grid">
                {% for name, reqs in districts.items() %}
                <div class="district-column">
                    <div class="district-header">
                        <span class="district-title"><i data-lucide="map-pin"></i> {{ name }} район</span>
                        <span class="district-count">{{ reqs|length }}</span>
                    </div>
                    
                    {% if reqs|length == 0 %}
                        <div class="no-requests">Активные вызовы отсутствуют</div>
                    {% else %}
                        {% for r in reqs %}
                        <div class="request-card">
                            <div class="request-header">
                                <span class="patient-name">{{ r.name }}</span>
                                <span class="timestamp">{{ r.timestamp }}</span>
                            </div>
                            
                            {% if r.phone %}
                            <div class="info-item" style="margin-top: -0.25rem;">
                                <span class="info-label"><i data-lucide="phone"></i> Телефон:</span>
                                <span class="info-val" style="color: #10b981; font-weight: 600;">{{ r.phone }}</span>
                            </div>
                            {% endif %}
                            
                            <div class="info-item">
                                <span class="info-label"><i data-lucide="map"></i> Адрес / Локация:</span>
                                <span class="info-val" style="color: #2563eb;">{{ r.location }}</span>
                            </div>
                            
                            <div class="info-item">
                                <span class="info-label"><i data-lucide="activity"></i> Симптомы и состояние:</span>
                                <span class="info-val" style="color: #dc2626; font-weight: 500;">{{ r.symptoms }}</span>
                            </div>
                        </div>
                        {% endfor %}
                    {% endif %}
                </div>
                {% endfor %}
            </div>
        </div>
        <script>
            lucide.createIcons();
        </script>
    </body>
    </html>
    """
    return render_template_string(template, districts=districts, total_count=total_count)

@app.route("/developer", methods=["GET"])
def developer_panel():
    import json
    import os
    import glob
    
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    histories_dir = os.path.join(BASE_DIR, "data", "chat_histories")
    chats = []
    
    if os.path.exists(histories_dir):
        files = glob.glob(os.path.join(histories_dir, "*.json"))
        for file in files:
            try:
                with open(file, "r", encoding="utf-8") as f:
                    chat_data = json.load(f)
                    chats.append(chat_data)
            except Exception as e:
                print(f"Error reading chat file {file}: {e}")
                
    # Сортируем чаты по последнему обновлению
    chats.sort(key=lambda x: x.get("last_updated", ""), reverse=True)
    
    selected_chat_id = request.args.get("chat_id")
    selected_chat = None
    if selected_chat_id:
        for c in chats:
            if str(c.get("chat_id")) == str(selected_chat_id):
                selected_chat = c
                break
                
    template = """
    <!DOCTYPE html>
    <html lang="ru">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            :root {
                --bg-light: #f3f4f6;
                --sidebar-bg: #ffffff;
                --chat-bg: #fafafa;
                --text-primary: #1f2937;
                --text-secondary: #4b5563;
                --border-color: #d1d5db;
                --accent-blue: #2563eb;
                --bubble-user: #eff6ff;
                --bubble-bot: #ffffff;
            }
            
            * {
                box-sizing: border-box;
                margin: 0;
                padding: 0;
            }
            
            body {
                font-family: 'Segoe UI', -apple-system, BlinkMacSystemFont, Roboto, sans-serif;
                background-color: var(--bg-light);
                color: var(--text-primary);
                height: 100vh;
                display: flex;
                flex-direction: column;
                overflow: hidden;
                letter-spacing: -0.01em;
            }
            
            header {
                background: #ffffff;
                border-bottom: 1px solid var(--border-color);
                padding: 1.5rem 3rem;
                display: flex;
                justify-content: space-between;
                align-items: center;
                height: 80px;
                flex-shrink: 0;
            }
            
            header h1 {
                font-size: 1.4rem;
                font-weight: 600;
                color: #111827;
                display: flex;
                align-items: center;
                gap: 0.5rem;
            }
            
            .nav-btn {
                background: #f3f4f6;
                color: var(--text-secondary);
                text-decoration: none;
                padding: 0.6rem 1.2rem;
                border-radius: 4px;
                font-size: 0.875rem;
                font-weight: 600;
                border: 1px solid #d1d5db;
                transition: all 0.2s;
            }
            
            .nav-btn:hover {
                background: #e5e7eb;
                color: var(--text-primary);
            }
            
            .main-container {
                display: flex;
                flex: 1;
                overflow: hidden;
            }
            
            .sidebar {
                width: 380px;
                background: var(--sidebar-bg);
                border-right: 1px solid var(--border-color);
                display: flex;
                flex-direction: column;
                overflow-y: auto;
                flex-shrink: 0;
            }
            
            .sidebar-title {
                padding: 1.25rem;
                font-size: 0.85rem;
                text-transform: uppercase;
                color: var(--text-secondary);
                border-bottom: 1px solid var(--border-color);
                letter-spacing: 0.08em;
                font-weight: 600;
            }
            
            .chat-list-item {
                display: block;
                padding: 1.25rem;
                border-bottom: 1px solid var(--border-color);
                text-decoration: none;
                color: inherit;
                transition: background 0.2s;
            }
            
            .chat-list-item:hover {
                background: #f9fafb;
            }
            
            .chat-list-item.active {
                background: #eff6ff;
                border-left: 4px solid var(--accent-blue);
            }
            
            .chat-item-header {
                display: flex;
                justify-content: space-between;
                margin-bottom: 0.35rem;
            }
            
            .chat-item-name {
                font-weight: 600;
                font-size: 0.95rem;
            }
            
            .chat-item-time {
                font-size: 0.75rem;
                color: var(--text-secondary);
            }
            
            .chat-item-id {
                font-size: 0.8rem;
                color: var(--text-secondary);
            }
            
            .chat-window {
                flex: 1;
                display: flex;
                flex-direction: column;
                background: var(--chat-bg);
                overflow: hidden;
            }
            
            .chat-header-info {
                padding: 1.5rem 3rem;
                background: #ffffff;
                border-bottom: 1px solid var(--border-color);
                flex-shrink: 0;
            }
            
            .chat-header-name {
                font-weight: 600;
                font-size: 1.2rem;
                color: #111827;
            }
            
            .chat-header-meta {
                font-size: 0.85rem;
                color: var(--text-secondary);
                margin-top: 0.35rem;
            }
            
            .messages-container {
                flex: 1;
                padding: 3rem;
                overflow-y: auto;
                display: flex;
                flex-direction: column;
                gap: 2rem;
            }
            
            .message-bubble {
                max-width: 65%;
                padding: 1.25rem 1.5rem;
                border-radius: 4px;
                line-height: 1.6;
                font-size: 0.95rem;
                position: relative;
                box-shadow: 0 1px 3px rgba(0,0,0,0.02);
            }
            
            .message-bubble.user {
                background: var(--bubble-user);
                align-self: flex-end;
                border: 1px solid #bfe0ff;
            }
            
            .message-bubble.assistant {
                background: var(--bubble-bot);
                align-self: flex-start;
                border: 1px solid var(--border-color);
            }
            
            .bubble-meta {
                font-size: 0.75rem;
                color: var(--text-secondary);
                margin-bottom: 0.5rem;
                font-weight: 600;
                text-transform: uppercase;
                letter-spacing: 0.05em;
            }
            
            .no-chat-selected {
                flex: 1;
                display: flex;
                flex-direction: column;
                align-items: center;
                justify-content: center;
                color: var(--text-secondary);
                font-size: 1rem;
            }
            
            .no-chat-icon {
                font-size: 3rem;
                margin-bottom: 1rem;
                color: var(--text-secondary);
            }
            
            .lucide {
                width: 18px;
                height: 18px;
                vertical-align: middle;
                display: inline-block;
                stroke-width: 2px;
            }
            
            header h1 .lucide {
                width: 24px;
                height: 24px;
                margin-right: 0.5rem;
                color: var(--accent-blue);
            }
            
            .nav-btn .lucide {
                width: 16px;
                height: 16px;
                margin-right: 0.35rem;
                vertical-align: -2px;
            }
            
            .bubble-meta .lucide {
                width: 14px;
                height: 14px;
                margin-right: 0.25rem;
                vertical-align: -2px;
            }
        </style>
        <script src="https://unpkg.com/lucide@latest"></script>
        <script>
            setInterval(() => {
                const urlParams = new URLSearchParams(window.location.search);
                const chatId = urlParams.get('chat_id');
                let refreshUrl = '/developer';
                if (chatId) {
                    refreshUrl += '?chat_id=' + chatId;
                }
                window.location.href = refreshUrl;
            }, 5000);
        </script>
    </head>
    <body>
        <header>
            <h1><i data-lucide="terminal"></i> Панель разработчика: Диалоги пациентов</h1>
            <a href="/dashboard" class="nav-btn"><i data-lucide="activity"></i> К заявкам скорой помощи</a>
        </header>
        
        <div class="main-container">
            <div class="sidebar">
                <div class="sidebar-title">Активные сессии ({{ chats|length }})</div>
                {% if chats|length == 0 %}
                    <div style="padding: 2rem; text-align: center; color: var(--text-secondary);">Чаты не найдены</div>
                {% else %}
                    {% for c in chats %}
                    <a href="/developer?chat_id={{ c.chat_id }}" class="chat-list-item {% if selected_chat and selected_chat.chat_id == c.chat_id %}active{% endif %}">
                        <div class="chat-item-header">
                            <span class="chat-item-name">{{ c.name or 'Пациент' }}</span>
                            <span class="chat-item-time">{{ c.last_updated.split(' ')[1] }}</span>
                        </div>
                        <div class="chat-item-id">ID: {{ c.chat_id }}</div>
                    </a>
                    {% endfor %}
                {% endif %}
            </div>
            
            <div class="chat-window">
                {% if selected_chat %}
                    <div class="chat-header-info">
                        <div class="chat-header-name">{{ selected_chat.name or 'Пациент' }}</div>
                        <div class="chat-header-meta">Chat ID: {{ selected_chat.chat_id }} | Обновлено: {{ selected_chat.last_updated }}</div>
                    </div>
                    
                    <div class="messages-container">
                        {% for msg in selected_chat.history %}
                        <div class="message-bubble {{ msg.role }}">
                            <div class="bubble-meta">
                                {% if msg.role == 'user' %}
                                    <i data-lucide="user"></i> Пациент
                                {% else %}
                                    <i data-lucide="cpu"></i> Санарип ИИ
                                {% endif %}
                            </div>
                            <div class="bubble-content" style="white-space: pre-wrap;">{{ msg.content }}</div>
                        </div>
                        {% endfor %}
                    </div>
                {% else %}
                    <div class="no-chat-selected">
                        <div class="no-chat-icon"><i data-lucide="message-square" style="width: 48px; height: 48px;"></i></div>
                        <div>Выберите сессию в левом меню для просмотра переписки с ИИ-ассистентом</div>
                    </div>
                {% endif %}
            </div>
        </div>
        <script>
            lucide.createIcons();
        </script>
    </body>
    </html>
    """
    return render_template_string(template, chats=chats, selected_chat=selected_chat)

@app.route("/webhook", methods=["GET"])
def verify_webhook():
    """Проверка вебхука со стороны Meta (GET запрос)"""
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    if mode == "subscribe" and token == WHATSAPP_VERIFY_TOKEN:
        print("Вебхук успешно верифицирован Meta!")
        return challenge, 200
    else:
        print("Ошибка верификации: неверный Verify Token.")
        return "Forbidden", 403

@app.route("/webhook", methods=["POST"])
def receive_webhook():
    """Прием сообщений от Meta (POST запрос)"""
    data = request.json
    print(f"Получено событие от WhatsApp: {data}")

    # Проверяем, есть ли сообщения в запросе
    if not data or "entry" not in data:
        return jsonify({"status": "ignored"}), 200

    for entry in data.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            if "messages" in value:
                for message in value.get("messages", []):
                    # Проверяем, что сообщение текстовое
                    if message.get("type") == "text":
                        sender_phone = message.get("from")
                        message_body = message.get("text", {}).get("body")
                        phone_number_id = value.get("metadata", {}).get("phone_number_id")

                        print(f"Новое сообщение от {sender_phone}: {message_body}")

                        if message_body and phone_number_id:
                            try:
                                # Запрос к ИИ
                                response_text = ask_deepseek(message_body)
                                # Отправка ответа в WhatsApp
                                send_whatsapp_message(sender_phone, response_text, phone_number_id)
                            except Exception as e:
                                print(f"Ошибка при обработке сообщения: {e}")
                                # Можно отправить шаблонное сообщение об ошибке
                                send_whatsapp_message(
                                    sender_phone, 
                                    "Извините, возникла техническая ошибка при обработке вашего запроса. Пожалуйста, попробуйте позже.", 
                                    phone_number_id
                                )

    return jsonify({"status": "ok"}), 200

@app.route("/webhook/telegram", methods=["POST"])
def telegram_webhook():
    """Прием обновлений от Telegram через вебхук"""
    import sys
    print("LOG: Received webhook request", file=sys.stderr)
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        print(f"LOG: Webhook payload: {json_string}", file=sys.stderr)
        try:
            update = telebot.types.Update.de_json(json_string)
            print(f"LOG: Parsed update: {update}", file=sys.stderr)
            bot.process_new_updates([update])
            print("LOG: Updates processed successfully", file=sys.stderr)
        except Exception as e:
            print(f"LOG ERROR: Exception in processing updates: {e}", file=sys.stderr)
        return '', 200
    else:
        print("LOG: Unsupported Media Type", file=sys.stderr)
        return 'Unsupported Media Type', 403

@app.route("/set_webhook", methods=["GET"])
def set_webhook():
    """Автоматическая настройка вебхука Telegram на текущий хост"""
    webhook_url = f"{request.host_url}webhook/telegram"
    success = bot.set_webhook(url=webhook_url)
    if success:
        return f"Webhook successfully set to: {webhook_url}", 200
    else:
        return f"Failed to set webhook to: {webhook_url}", 500

if __name__ == "__main__":
    # Запуск сервера
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
