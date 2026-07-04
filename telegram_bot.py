import os
import json
import base64
import math
import requests
import telebot
from telebot import types
from dotenv import load_dotenv
from rag_updater import SimpleTFIDFIndex, start_background_updater

# Загружаем переменные окружения
load_dotenv()

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

# Проверка токена при запуске
token_missing = not TELEGRAM_BOT_TOKEN or TELEGRAM_BOT_TOKEN == "your_telegram_bot_token_here" or ":" not in TELEGRAM_BOT_TOKEN

if token_missing:
    print("\n[!] ОШИБКА: TELEGRAM_BOT_TOKEN не настроен.")
    if __name__ == "__main__":
        import sys
        sys.exit(1)
    else:
        # Для работы в Flask / Vercel не валим весь сервер при импорте, а создаем заглушку
        bot = telebot.TeleBot("123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ", threaded=False)
else:
    # Инициализируем бота
    bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN, threaded=False)

# URLs для API
DEEPSEEK_URL = "https://api.deepseek.com/v1/chat/completions"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

# Конфигурация моделей
DEEPSEEK_MODEL = "deepseek-chat"
GROQ_VISION_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"

# Хранилище контекста диалогов (история сообщений для каждого пользователя)
# Структура: { chat_id: [{"role": "user/assistant", "content": "..."}] }
USER_SESSIONS = {}

# Состояния заполнения формы скорой помощи
# Структура: { chat_id: {"state": "...", "name": "...", "region": "...", "location": "...", "symptoms": "..."} }
USER_STATES = {}

# Глобальный словарь соответствия симптомов специальностям врачей
SPECIALTY_KEYWORDS = {
    "педиатр": ["ребенок", "детский", "дети", "малыш", "педиатр", "ребенка"],
    "кардиолог": ["сердце", "грудь", "инфаркт", "кардиолог", "давление", "стенокардия"],
    "офтальмолог": ["глаз", "зрение", "окулист", "катаракта", "офтальмолог", "глаза"],
    "стоматолог": ["зуб", "десна", "кариес", "стоматолог", "зубы", "зубная"],
    "травматолог": ["сломал", "перелом", "вывих", "ушиб", "травма", "травматолог", "гипс", "растяжение"],
    "гинеколог": ["беременность", "роды", "гинеколог", "женский", "яичники"]
}

# Загрузка локальных баз данных
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CLINICS_PATH = os.path.join(BASE_DIR, "data", "clinics.json")
FIRST_AID_PATH = os.path.join(BASE_DIR, "data", "first_aid.json")
DISEASES_INDEX_PATH = os.path.join(BASE_DIR, "data", "diseases_index.json")

CLINICS_DB = []
FIRST_AID_DB = []

try:
    with open(CLINICS_PATH, "r", encoding="utf-8") as f:
        CLINICS_DB = json.load(f).get("clinics", [])
    print(f"Успешно загружено клиник: {len(CLINICS_DB)}")
except Exception as e:
    print(f"Ошибка загрузки базы клиник: {e}")

try:
    with open(FIRST_AID_PATH, "r", encoding="utf-8") as f:
        FIRST_AID_DB = json.load(f).get("conditions", [])
    print(f"Успешно загружено инструкций первой помощи: {len(FIRST_AID_DB)}")
except Exception as e:
    print(f"Ошибка загрузки базы первой помощи: {e}")

# Инициализация и запуск локальной RAG базы знаний
DISEASES_INDEX = None
try:
    if os.path.exists(DISEASES_INDEX_PATH):
        DISEASES_INDEX = SimpleTFIDFIndex.load(DISEASES_INDEX_PATH)
        print("RAG база знаний успешно загружена.")
    else:
        print("Внимание: RAG база знаний не найдена.")
except Exception as e:
    print(f"Ошибка загрузки RAG базы знаний: {e}")

# Запускаем фоновый апдейтер только если мы НЕ на Vercel и НЕ на PythonAnywhere
if "VERCEL" not in os.environ and "PYTHONANYWHERE_DOMAIN" not in os.environ:
    try:
        start_background_updater()
    except Exception as e:
        print(f"Ошибка фоновой службы обновлений RAG: {e}")


# Системные промпты с профессиональным, успокаивающим тоном и строгими ограничениями
SYSTEM_PROMPT = (
    "Ты — Санарип, высококвалифицированный, хладнокровный и надежный медицинский координатор. "
    "Твоя главная миссия — спасти жизнь человека при любых обстоятельствах, предотвратить ухудшение его состояния и направить к нужному специалисту.\n\n"
    "СТРОГИЕ КЛИНИЧЕСКИЕ ПРАВИЛА (ЖИЗНЕННО ВАЖНО):\n"
    "1. ДВУХЭТАПНЫЙ ОПРОС ПАЦИЕНТА (ОБЯЗАТЕЛЬНО):\n"
    "   - ЭТАП 1: Когда пациент впервые сообщает о жалобе или новом симптоме (например: 'я обжегся', 'болит живот'), ты НЕ должен сразу выдавать полный диагноз или рекомендации первой помощи. Вместо этого ты должен СНАЧАЛА задать один (максимум два) коротких и точечных уточняющих вопроса, чтобы сузить круг симптомов, и обязательно предложить в конце кнопки с вариантами ответов.\n"
    "   - ЭТАП 2: Только после того, как пациент выберет кнопку или ответит на твой уточняющий вопрос (это будет видно в истории диалога), ты переходишь к подробному анализу симптомов, выдаешь пошаговые рекомендации первой помощи на основе RAG-справки и предлагаешь кнопку записи к врачу.\n"
    "2. МГНОВЕННОЕ РАСПОЗНАВАНИЕ УГРОЗЫ ЖИЗНИ: При любых намеках на критическое состояние (боль за грудиной, одышка, удушье, потеря сознания, анафилактический шок, обильное артериальное кровотечение, признаки инсульта FAST) твоей ПЕРВОЙ фразой должно быть требование СРОЧНО вызвать скорую помощь по номеру 103 и предложить кнопку:\n"
    "[Кнопки: Вызвать скорую помощь]\n"
    "3. ПРИНЦИП 'НЕ НАВРЕДИ': Строго запрещено рекомендовать рецептурные медикаменты. Предотвращай опасные действия (например, запрещай греть живот при болях, накладывать жгут без артериального кровотечения, мазать ожоги маслом).\n"
    "4. СОПРОВОЖДЕНИЕ ПАЦИЕНТА: Если ситуация средней тяжести, подробно объясни правила безопасности и пошаговые рекомендации до осмотра врача, основываясь на RAG-информации. Только после этого предлагай записаться:\n"
    "[Кнопки: Записаться на врача поблизости]\n\n"
    "ПРАВИЛА ОФОРМЛЕНИЯ И ЧИТАЕМОСТИ (КРИТИЧЕСКИ ВАЖНО):\n"
    "- Будь лаконичным. Пиши максимально кратко, убирай лишние рассуждения, пустые вежливые фразы и 'воду'. Текст должен быть легко читаемым в одно мгновение.\n"
    "- Разделяй смысловые блоки горизонтальными линиями из символов: `────────────────`.\n"
    "- Разнообразь текст тематическими иконками-эмодзи перед пунктами или важными предупреждениями (например: 🩹, ⚠️, 🌡️, 💊, ❌, ✅, ℹ️, 🚨, 🚑).\n"
    "- В конце сообщения добавляй кнопки строго в формате: [Кнопки: Вариант 1 | Вариант 2]"
)

VISION_PROMPT = (
    "Ты — Санарип, квалифицированный медицинский координатор визуальной диагностики.\n\n"
    "СТРОГИЕ ПРАВИЛА АНАЛИЗА ИЗОБРАЖЕНИЙ (ДВУХЭТАПНЫЙ ПРОЦЕСС):\n"
    "1. ЭТАП 1: Когда пациент только отправляет фотографию симптома/травмы, ты НЕ должен писать полный отчет, диагноз или рекомендации первой помощи. "
    "Вместо этого ты должен СНАЧАЛА кратко (в 1 предложении) описать, что видишь на снимке, и сразу задать 1 главный уточняющий вопрос, чтобы определить происхождение или тяжесть симптома, обязательно прикрепив в самом конце варианты ответов в виде кнопок.\n"
    "Пример ответа на первом этапе:\n"
    "Вижу на фотографии покраснение кожи на руке. Подскажите, пожалуйста, чем именно был вызван этот ожог?\n"
    "[Кнопки: Горячая вода или пар | Горячий предмет | Открытый огонь | Химическое вещество]\n\n"
    "2. ЭТАП 2: Только после того, как пациент выберет вариант (это будет видно в истории диалога как ответ на твой уточняющий вопрос), ты проводишь полный клинический анализ и выдаешь структурированную информацию, разделяя разделы линиями и используя иконки:\n"
    "   ℹ️ Визуальные признаки: (кратко)\n"
    "   ────────────────\n"
    "   ⚠️ Вероятные симптомы: (кратко)\n"
    "   ────────────────\n"
    "   🩹 Примерный диагноз: (предварительно, сноска о том, что точный диагноз ставит врач)\n"
    "   ────────────────\n"
    "   💊 Первая помощь: (пошаговая инструкция до визита к врачу)\n"
    "   ────────────────\n"
    "   И добавляешь кнопку записи к врачу: `[Кнопки: Записаться на врача поблизости]`\n\n"
    "ПРАВИЛА ОФОРМЛЕНИЯ:\n"
    "- Пиши кратко, емко, без лишних пояснений.\n"
    "- Разделяй смысловые блоки линиями `────────────────`."
)


# --- Клавиатуры быстрого выбора (Keyboards) ---

def get_main_keyboard():
    """Создает постоянную клавиатуру под полем ввода"""
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    btn_first_aid = types.KeyboardButton("📚 Первая помощь")
    btn_clinics = types.KeyboardButton("🏥 Клиники Бишкека")
    btn_emergency = types.KeyboardButton("🚑 Экстренный случай (103)")
    markup.row(btn_first_aid, btn_clinics)
    markup.row(btn_emergency)
    return markup

def get_first_aid_inline_keyboard():
    """Создает инлайн-кнопки для выбора темы первой помощи"""
    markup = types.InlineKeyboardMarkup(row_width=2)
    buttons = [
        types.InlineKeyboardButton("🔥 Термический ожог", callback_data="aid_burn"),
        types.InlineKeyboardButton("🦴 Переломы и вывихи", callback_data="aid_fracture"),
        types.InlineKeyboardButton("🕷️ Укусы (собаки, клещи, змеи)", callback_data="aid_bite"),
        types.InlineKeyboardButton("🤢 Пищевое отравление", callback_data="aid_poison"),
        types.InlineKeyboardButton("🫀 Боль в сердце (инфаркт)", callback_data="aid_heart"),
        types.InlineKeyboardButton("🌡️ Высокая температура", callback_data="aid_temp"),
    ]
    markup.add(*buttons)
    return markup

def get_clinics_inline_keyboard():
    """Создает инлайн-кнопки со списком клиник Бишкека"""
    markup = types.InlineKeyboardMarkup(row_width=1)
    for i, clinic in enumerate(CLINICS_DB):
        btn_text = f"🏥 {clinic.get('name')}"
        markup.add(types.InlineKeyboardButton(btn_text, callback_data=f"clinic_{i}"))
    return markup


# --- Логика контекстного поиска ---

def get_relevant_context(user_text: str) -> tuple:
    """Ищет подходящие инструкции и клиники по ключевым словам. Возвращает (context_text, detected_types)"""
    text_lower = user_text.lower()
    context_parts = []
    detected_types = []

    # 1. Поиск первой помощи
    matched_conditions = []
    for cond in FIRST_AID_DB:
        for kw in cond.get("keywords", []):
            if kw in text_lower:
                matched_conditions.append(cond)
                detected_types.append("first_aid")
                break
    
    if matched_conditions:
        context_parts.append("=== ИНСТРУКЦИИ ПЕРВОЙ ПОМОЖИ ===")
        for cond in matched_conditions:
            do_list = "\n".join([f"- {item}" for item in cond.get("do", [])])
            dont_list = "\n".join([f"- {item}" for item in cond.get("dont", [])])
            context_parts.append(
                f"Травма: {cond.get('title')}\n"
                f"Что нужно делать:\n{do_list}\n"
                f"Чего делать НЕЛЬЗЯ:\n{dont_list}\n"
            )

    # 2. Поиск клиник по специализации
    detected_specialties = []
    for specialty, keywords in SPECIALTY_KEYWORDS.items():
        for kw in keywords:
            if kw in text_lower:
                detected_specialties.append(specialty)
                detected_types.append("clinic")
                break

    matched_clinics = []
    if detected_specialties:
        for clinic in CLINICS_DB:
            if any(spec in clinic.get("specializations", []) for spec in detected_specialties):
                matched_clinics.append(clinic)

    if matched_clinics:
        context_parts.append("=== ДОСТУПНЫЕ КЛИНИКИ В БИШКЕКЕ ===")
        for clinic in matched_clinics:
            doctors_list = ", ".join([f"{doc['name']} ({doc['specialty']})" for doc in clinic.get("doctors", [])])
            context_parts.append(
                f"Клиника: {clinic.get('name')}\n"
                f"Адрес: {clinic.get('address')}\n"
                f"Телефон: {clinic.get('phone')}\n"
                f"Направления: {', '.join(clinic.get('specializations', []))}\n"
                f"Врачи: {doctors_list}\n"
            )
            
    return "\n\n".join(context_parts), list(set(detected_types))


def ask_deepseek_with_history(chat_id: int, user_message: str, context: str = "") -> tuple:
    """Запрос к DeepSeek с учетом истории диалога и контекста. Возвращает (clean_text, reply_markup)"""
    if not DEEPSEEK_API_KEY or DEEPSEEK_API_KEY == "your_deepseek_api_key_here":
        return "Ошибка конфигурации: отсутствует ключ DEEPSEEK_API_KEY.", None

    # Инициализируем историю сообщений, если сессии нет
    if chat_id not in USER_SESSIONS:
        USER_SESSIONS[chat_id] = []

    # Добавляем сообщение пользователя в историю
    USER_SESSIONS[chat_id].append({"role": "user", "content": user_message})
    save_chat_history(chat_id)

    # Ограничиваем историю последними 10 сообщениями
    USER_SESSIONS[chat_id] = USER_SESSIONS[chat_id][-10:]

    # Проводим RAG поиск по локальной базе заболеваний
    rag_context = ""
    if DISEASES_INDEX:
        try:
            # Объединяем последние 3 сообщения пользователя для сохранения медицинского контекста
            history = USER_SESSIONS.get(chat_id, [])
            user_msgs = [m["content"] for m in history if m["role"] == "user"]
            search_query = " ".join(user_msgs[-3:]) if user_msgs else user_message
            
            results = DISEASES_INDEX.search(search_query, top_k=2)
            matching_docs = []
            for doc, score in results:
                if score > 0.05:
                    matching_docs.append(
                        f"Документ: {doc['title']}\n"
                        f"Ссылка: {doc['url']}\n"
                        f"Содержание:\n{doc['content'][:2500]}"
                    )
            if matching_docs:
                rag_context = "=== ЛОКАЛЬНЫЕ КЛИНИЧЕСКИЕ ПРОТОКОЛЫ (RAG) ===\n\n" + "\n\n---\n\n".join(matching_docs)
        except Exception as e:
            print(f"Ошибка RAG поиска: {e}")
            
    # Объединяем контекст ключевых слов и RAG
    full_context = ""
    if context:
        full_context += context + "\n\n"
    if rag_context:
        full_context += rag_context

    # Собираем payload для API
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json"
    }
    
    # Формируем сообщения с системным промптом на первом месте
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    # Если есть контекст из базы знаний, добавляем его перед историей
    if full_context:
        messages.append({
            "role": "system", 
            "content": f"Справочная информация из базы знаний:\n\n{full_context}\n\nКратко используй эти факты в ответе, если применимо."
        })

    # Добавляем саму историю диалога
    messages.extend(USER_SESSIONS[chat_id])

    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": messages,
        "temperature": 0.6,
    }
    
    try:
        resp = requests.post(DEEPSEEK_URL, json=payload, headers=headers, timeout=25)
        if resp.status_code != 200:
            return "Не удалось получить ответ от ИИ-ассистента. Пожалуйста, попробуйте еще раз.", None
        
        data = resp.json()
        raw_reply = data["choices"][0]["message"]["content"]

        # Добавляем ответ ассистента в историю диалога
        USER_SESSIONS[chat_id].append({"role": "assistant", "content": raw_reply})
        save_chat_history(chat_id)

        # Парсинг кнопок из ответа ИИ
        clean_text, markup = parse_dynamic_buttons(raw_reply)
        return clean_text, markup

    except Exception as e:
        print(f"Ошибка DeepSeek API: {e}")
        return "Техническая задержка на стороне ИИ-модели. Пожалуйста, повторите запрос.", None


def parse_dynamic_buttons(text: str) -> tuple:
    """Ищет [Кнопки: Вариант 1 | Вариант 2] в тексте, вырезает их и строит InlineKeyboardMarkup"""
    import re
    pattern = r"\[Кнопки:\s*([^\]]+)\]"
    match = re.search(pattern, text)
    
    if not match:
        return text, None
    
    # Извлекаем варианты кнопок
    options_str = match.group(1)
    options = [opt.strip() for opt in options_str.split("|") if opt.strip()]
    
    # Очищаем текст от разметки кнопок
    clean_text = re.sub(pattern, "", text).strip()
    
    # Строим клавиатуру
    markup = types.InlineKeyboardMarkup(row_width=2)
    inline_buttons = []
    for opt in options:
        # В Telegram callback_data ограничена 64 байтами.
        # Поскольку кириллица занимает 2 байта на символ, обрезаем по байтовой длине.
        opt_bytes = opt.encode("utf-8")[:48]
        opt_short = opt_bytes.decode("utf-8", errors="ignore")
        cb_data = f"user_choice:{opt_short}"
        inline_buttons.append(types.InlineKeyboardButton(opt, callback_data=cb_data))
    
    markup.add(*inline_buttons)
    return clean_text, markup


def calculate_distance(lat1, lon1, lat2, lon2):
    """Вычисление расстояния по формуле гаверсинусов (в км)"""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


def get_bishkek_district_by_coords(lat, lon):
    """Определение района Бишкека по географическим координатам"""
    # Границы Бишкека
    if not (42.80 <= lat <= 42.93 and 74.45 <= lon <= 74.72):
        return "Другой"
        
    # Ленинский район - запад (lon < 74.58)
    if lon < 74.58:
        return "Ленинский"
    # Южная часть - Октябрьский (lat < 42.855)
    elif lat < 42.855:
        if lon >= 74.58:
            return "Октябрьский"
        else:
            return "Ленинский"
    # Северная часть - Свердловский (восток) и Первомайский (центр/запад)
    else:
        if lon >= 74.615:
            return "Свердловский"
        else:
            return "Первомайский"


def detect_specialty(chat_id):
    """Анализирует историю диалога пользователя для выявления нужной специализации врача"""
    history = USER_SESSIONS.get(chat_id, [])
    for msg in reversed(history):
        if msg.get("role") == "user":
            text = msg.get("content", "").lower()
            for specialty, keywords in SPECIALTY_KEYWORDS.items():
                for kw in keywords:
                    if kw in text:
                        return specialty
    return None


def summarize_symptoms_with_llm(chat_id) -> str:
    """Просит DeepSeek обобщить жалобы и симптомы пациента на основе истории переписки"""
    history = USER_SESSIONS.get(chat_id, [])
    if not history:
        return "Симптомы не описаны"
        
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json"
    }
    
    messages = [
        {"role": "system", "content": "Ты — медицинский координатор. Проанализируй историю диалога и кратко (одной фразой до 10-12 слов) сформулируй жалобы и симптомы пациента для бригады скорой помощи. Пиши строго по делу (например: 'Термический ожог кисти руки горячей водой, острая боль'). Избегай приветствий и вежливых слов."},
    ]
    # Фильтруем сообщения, исключая технические сообщения о выборе кнопок
    filtered_history = [
        msg for msg in history 
        if not (msg.get("content", "").startswith("👉") or msg.get("content", "").startswith("📍") or "вызов успешно зарегистрирован" in msg.get("content", "").lower())
    ]
    messages.extend(filtered_history[-6:]) # Берем последние 6 сообщений
    messages.append({"role": "user", "content": "Напиши краткое и точное описание симптомов пациента на основе диалога:"})
    
    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": messages,
        "temperature": 0.3,
        "max_tokens": 100
    }
    
    try:
        resp = requests.post(DEEPSEEK_URL, json=payload, headers=headers, timeout=15)
        if resp.status_code == 200:
            return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"Ошибка суммаризации симптомов: {e}")
        
    # Резервный фолбэк при ошибке сети
    user_msgs = [msg["content"] for msg in history if msg["role"] == "user" and not msg["content"].startswith("👉")]
    if user_msgs:
        return " / ".join(user_msgs[-3:])
    return "Симптомы не указаны"


def save_chat_history(chat_id):
    """Сохраняет историю диалога пользователя на диск для панели разработчика"""
    import time
    os.makedirs(os.path.join(BASE_DIR, "data", "chat_histories"), exist_ok=True)
    file_path = os.path.join(BASE_DIR, "data", "chat_histories", f"{chat_id}.json")
    history = USER_SESSIONS.get(chat_id, [])
    
    # Пытаемся получить имя из состояния, если оно там есть
    name = "Пациент"
    if chat_id in USER_STATES and USER_STATES[chat_id].get("name"):
        name = USER_STATES[chat_id]["name"]
        
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump({
                "chat_id": chat_id,
                "name": name,
                "history": history,
                "last_updated": time.strftime("%Y-%m-%d %H:%M:%S")
            }, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Ошибка сохранения истории чата {chat_id}: {e}")


def save_emergency_request(chat_id, state_data):
    """Сохраняет новую заявку скорой помощи в JSON файл и отправляет подтверждение"""
    import datetime
    
    request_entry = {
        "id": chat_id,
        "name": state_data.get("name", "Не указано"),
        "phone": state_data.get("phone", "Не указано"),
        "region": state_data.get("region", "Не указано"),
        "location": state_data.get("location", "Не указано"),
        "symptoms": state_data.get("symptoms", "Не указано"),
        "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    
    file_path = os.path.join(BASE_DIR, "data", "emergency_requests.json")
    data = {"requests": []}
    if os.path.exists(file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            print(f"Ошибка чтения заявок: {e}")
            
    data.setdefault("requests", []).append(request_entry)
    
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Ошибка сохранения заявки: {e}")
        
    USER_STATES.pop(chat_id, None)
    
    confirmation_text = (
        "🚨 **Ваш экстренный вызов успешно зарегистрирован!**\n\n"
        "Мы передали следующую информацию бригаде скорой помощи:\n"
        f"👤 **Пациент:** {request_entry['name']}\n"
        f"📞 **Телефон:** {request_entry['phone']}\n"
        f"🏙️ **Район:** {request_entry['region']}\n"
        f"📍 **Адрес:** {request_entry['location']}\n"
        f"🩺 **Описанные симптомы:** {request_entry['symptoms']}\n\n"
        "🚑 Бригада скорой помощи формируется. Пожалуйста, оставайтесь на связи по этому номеру телефона. Если ситуация ухудшится, немедленно звоните по номеру **103**."
    )
    bot.send_message(chat_id, confirmation_text, parse_mode="Markdown", reply_markup=get_main_keyboard())


def transcribe_voice_with_groq(file_bytes: bytes) -> str:
    """Транскрибация аудио-файла голоса через Groq Whisper API (поддерживает кыргызский, русский и английский)"""
    if not GROQ_API_KEY or GROQ_API_KEY == "your_groq_api_key_here":
        return "Ошибка конфигурации: отсутствует ключ GROQ_API_KEY."

    url = "https://api.groq.com/openai/v1/audio/transcriptions"
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}"
    }
    
    files = {
        "file": ("voice.ogg", file_bytes, "audio/ogg")
    }
    data = {
        "model": "whisper-large-v3",
        "response_format": "json"
    }
    
    try:
        resp = requests.post(url, headers=headers, files=files, data=data, timeout=30)
        if resp.status_code != 200:
            print(f"Ошибка Groq Audio API: {resp.status_code} {resp.text}")
            return ""
        return resp.json().get("text", "")
    except Exception as e:
        print(f"Ошибка Groq Whisper: {e}")
        return ""


def analyze_image_with_groq(image_bytes: bytes) -> str:
    """Отправка изображения в Groq Cloud Vision API (Llama-3.2 Vision)"""
    if not GROQ_API_KEY or GROQ_API_KEY == "your_groq_api_key_here":
        return "Ошибка конфигурации: отсутствует ключ GROQ_API_KEY."

    base64_image = base64.b64encode(image_bytes).decode('utf-8')
    
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": GROQ_VISION_MODEL,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": VISION_PROMPT},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{base64_image}"
                        }
                    }
                ]
            }
        ],
        "temperature": 0.5,
        "max_tokens": 1024
    }
    
    try:
        resp = requests.post(GROQ_URL, json=payload, headers=headers, timeout=30)
        if resp.status_code != 200:
            print(f"Ошибка от Groq API: {resp.status_code} {resp.text}")
            return "Не удалось распознать изображение. Пожалуйста, попробуйте еще раз."
        data = resp.json()
        return data["choices"][0]["message"]["content"]
    except Exception as e:
        print(f"Ошибка Groq Vision: {e}")
        return "Произошла ошибка при анализе изображения."


# --- Обработчики Callback-запросов (Inline кнопки) ---

@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    """Обрабатывает нажатия на inline кнопки"""
    chat_id = call.message.chat.id

    # 1. Запросы первой помощи
    if call.data.startswith("aid_"):
        condition_map = {
            "aid_burn": "ожог",
            "aid_fracture": "перелом",
            "aid_bite": "укус",
            "aid_poison": "отравление",
            "aid_heart": "сердце",
            "aid_temp": "температура"
        }
        key = condition_map.get(call.data)
        if key:
            bot.answer_callback_query(call.id, "Загружаю...")
            context, _ = get_relevant_context(key)
            reply, markup = ask_deepseek_with_history(chat_id, f"Напиши инструкцию первой помощи при теме: '{key}'", context)
            bot.send_message(chat_id, reply, reply_markup=markup, parse_mode='Markdown')
            
    # 2. Запросы клиник
    elif call.data.startswith("clinic_"):
        try:
            index = int(call.data.split("_")[1])
            clinic = CLINICS_DB[index]
            bot.answer_callback_query(call.id, "Загружаю...")
            
            doctors_info = "\n".join([f"👨‍⚕️ {doc['name']} — {doc['specialty']} ({doc['rating']})" for doc in clinic.get("doctors", [])])
            
            message_text = (
                f"🏥 {clinic.get('name')}\n\n"
                f"📍 Адрес: {clinic.get('address')}\n"
                f"📞 Контакты: {clinic.get('phone')}\n"
                f"🕒 Часы работы: {clinic.get('working_hours')}\n\n"
                f"🩺 Врачи клиники:\n{doctors_info}"
            )
            bot.send_message(chat_id, message_text)
        except Exception as e:
            print(f"Ошибка клиники по кнопке: {e}")

    # 4. Выбор района для скорой помощи
    elif call.data.startswith("region_"):
        bot.answer_callback_query(call.id)
        region_map = {
            "region_lenin": "Ленинский",
            "region_okt": "Октябрьский",
            "region_perv": "Первомайский",
            "region_sverd": "Свердловский",
            "region_other": "Другой"
        }
        val = region_map.get(call.data)
        
        if chat_id in USER_STATES:
            if val == "Другой":
                USER_STATES[chat_id]["state"] = "EMERGENCY_REGION_TEXT"
                bot.send_message(chat_id, "Пожалуйста, введите название вашего района или региона вручную:")
            else:
                USER_STATES[chat_id]["region"] = val
                USER_STATES[chat_id]["state"] = "EMERGENCY_CONTACT"
                
                markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
                markup.add(types.KeyboardButton("📱 Поделиться контактом", request_contact=True))
                bot.send_message(
                    chat_id,
                    f"Выбран район: **{val}**.\n\nПожалуйста, **поделитесь номером телефона**, нажав на кнопку ниже 👇 (или отправьте его текстом):",
                    parse_mode="Markdown",
                    reply_markup=markup
                )

    elif call.data.startswith("user_choice:"):
        choice = call.data.split("user_choice:")[1]
        bot.answer_callback_query(call.id)
        
        # Симулируем отправку сообщения пользователем в чат, отображая его выбор
        bot.send_message(chat_id, f"👉 Выбрано: {choice}")
        
        if choice.startswith("Записаться на врача поблизости"):
            markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
            btn = types.KeyboardButton("📍 Поделиться геолокацией", request_location=True)
            markup.add(btn)
            bot.send_message(chat_id, "Пожалуйста, поделитесь вашим местоположением (нажав на кнопку ниже), чтобы я мог подобрать ближайших врачей для вашей ситуации: 👇", reply_markup=markup)
            return

        if choice.startswith("Вызвать скорую помощь"):
            # Вызываем LLM-суммаризатор симптомов на основе истории диалога
            symptoms = summarize_symptoms_with_llm(chat_id)
            
            USER_STATES[chat_id] = {
                "state": "EMERGENCY_LOCATION",
                "name": "",
                "region": "",
                "location": "",
                "symptoms": symptoms
            }
            
            markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
            markup.add(types.KeyboardButton("📍 Отправить геолокацию", request_location=True))
            bot.send_message(
                chat_id, 
                "🚨 **Регистрация экстренного вызова**\n\n"
                "Для быстрого реагирования нам нужны ваши координаты. Пожалуйста, **отправьте вашу геолокацию** с помощью кнопки ниже 👇 или напишите ваш **точный адрес текстом**:", 
                parse_mode="Markdown", 
                reply_markup=markup
            )
            return
            
        # Запускаем обработку текста с этим значением
        bot.send_chat_action(chat_id, 'typing')
        context, _ = get_relevant_context(choice)
        reply, markup = ask_deepseek_with_history(chat_id, choice, context)
        bot.send_message(chat_id, reply, reply_markup=markup, parse_mode='Markdown')
# --- Командные обработчики ---

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    chat_id = message.chat.id
    # Очищаем историю сессии при старте/сбросе
    USER_SESSIONS[chat_id] = []
    
    welcome_text = (
        "Здравствуйте! 👋 Я медицинский координатор **Санарип**.\n\n"
        "Я помогу вам провести первичную оценку симптомов, дам рекомендации по первой помощи "
        "и подскажу контакты клиник в Бишкеке.\n\n"
        "✍️ **Вы можете описать ваши жалобы текстом** (например: 'болит ухо' или 'укусила собака') "
        "или **прислать фотографию** травмы/симптома.\n\n"
        "👇 Также вы можете воспользоваться кнопками быстрого выбора ниже:"
    )
    bot.reply_to(message, welcome_text, reply_markup=get_main_keyboard(), parse_mode='Markdown')


# --- Текстовые сообщения ---

@bot.message_handler(func=lambda message: True)
def handle_text(message):
    chat_id = message.chat.id
    text = message.text

    # Проверка, заполняет ли пользователь форму скорой помощи
    if chat_id in USER_STATES:
        state_data = USER_STATES[chat_id]
        current_state = state_data.get("state")

        if current_state == "EMERGENCY_LOCATION":
            state_data["location"] = text
            state_data["state"] = "EMERGENCY_REGION"
            
            markup = types.InlineKeyboardMarkup(row_width=2)
            markup.add(
                types.InlineKeyboardButton("Ленинский", callback_data="region_lenin"),
                types.InlineKeyboardButton("Октябрьский", callback_data="region_okt"),
                types.InlineKeyboardButton("Первомайский", callback_data="region_perv"),
                types.InlineKeyboardButton("Свердловский", callback_data="region_sverd"),
                types.InlineKeyboardButton("Другой район / Регион", callback_data="region_other")
            )
            bot.send_message(
                chat_id, 
                "Координаты не получены. Укажите ваш район Бишкека вручную с помощью кнопок:", 
                reply_markup=markup
            )
            return

        elif current_state == "EMERGENCY_REGION_TEXT":
            state_data["region"] = text
            state_data["state"] = "EMERGENCY_NAME"
            bot.send_message(
                chat_id,
                "Пожалуйста, напишите ваше **Имя и Фамилию** для завершения вызова:",
                parse_mode="Markdown",
                reply_markup=types.ReplyKeyboardRemove()
            )
            return

        elif current_state == "EMERGENCY_NAME":
            state_data["name"] = text
            save_emergency_request(chat_id, state_data)
            return

    # Обработка кнопок быстрого меню
    if text == "📚 Первая помощь":
        bot.send_message(
            chat_id, 
            "Выберите интересующую тему для просмотра пошаговой инструкции:", 
            reply_markup=get_first_aid_inline_keyboard()
        )
        return

    elif text == "🏥 Клиники Бишкека":
        bot.send_message(
            chat_id, 
            "Ниже представлен список партнерских клиник Бишкека. Выберите клинику для просмотра контактов:", 
            reply_markup=get_clinics_inline_keyboard()
        )
        return

    elif text == "🚑 Экстренный случай (103)":
        emergency_text = (
            "🚨 **Экстренная служба скорой помощи: 103**\n\n"
            "Пожалуйста, звоните по номеру 103 немедленно при следующих симптомах:\n"
            "- Потеря сознания или затрудненное дыхание\n"
            "- Сильная непрекращающаяся боль в груди\n"
            "- Обильное кровотечение, которое не останавливается\n"
            "- Подозрение на серьезный перелом позвоночника или черепно-мозговую травму"
        )
        bot.send_message(chat_id, emergency_text, parse_mode='Markdown')
        return

    # Стандартный запрос к ИИ
    bot.send_chat_action(chat_id, 'typing')
    
    # Ищем совпадения в базах данных
    context, _ = get_relevant_context(text)
    
    # Запрос к DeepSeek с учетом истории диалога
    reply, markup = ask_deepseek_with_history(chat_id, text, context)
            
    bot.reply_to(message, reply, reply_markup=markup, parse_mode='Markdown')


# --- Геолокация ---

@bot.message_handler(content_types=['location'])
def handle_location(message):
    chat_id = message.chat.id
    if not message.location:
        return
    
    lat = message.location.latitude
    lon = message.location.longitude

    # Проверка на режим регистрации вызова скорой
    if chat_id in USER_STATES:
        state_data = USER_STATES[chat_id]
        if state_data.get("state") == "EMERGENCY_LOCATION":
            state_data["location"] = f"Координаты: {lat:.6f}, {lon:.6f}"
            
            # Определяем район Бишкека автоматически по координатам
            detected_district = get_bishkek_district_by_coords(lat, lon)
            state_data["region"] = detected_district
            state_data["state"] = "EMERGENCY_CONTACT"
            
            markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
            markup.add(types.KeyboardButton("📱 Поделиться контактом", request_contact=True))
            bot.send_message(
                chat_id,
                f"📍 Район определен автоматически: **{detected_district}**\n\nПожалуйста, **поделитесь номером телефона**, нажав на кнопку ниже 👇 (или отправьте его текстом):",
                parse_mode="Markdown",
                reply_markup=markup
            )
            return
    
    # 1. Определяем специализацию по истории диалога
    specialty = detect_specialty(chat_id)
    
    # 2. Фильтруем и вычисляем расстояния
    matched_clinics = []
    for clinic in CLINICS_DB:
        # Проверяем, есть ли нужная специализация (если удалось определить)
        if specialty:
            if specialty not in clinic.get("specializations", []):
                continue
                
        c_lat = clinic.get("latitude")
        c_lon = clinic.get("longitude")
        if c_lat is not None and c_lon is not None:
            dist = calculate_distance(lat, lon, c_lat, c_lon)
            matched_clinics.append((clinic, dist))
        else:
            matched_clinics.append((clinic, 999999.0))
            
    # Сортируем по возрастанию расстояния
    matched_clinics.sort(key=lambda x: x[1])
    
    if not matched_clinics:
        bot.send_message(
            chat_id, 
            "К сожалению, в нашей базе нет клиник с подходящими врачами.", 
            reply_markup=get_main_keyboard()
        )
        return
        
    response_lines = []
    if specialty:
        response_lines.append(f"🔍 Найдено ближайших врачей по специализации **{specialty}**:\n")
    else:
        response_lines.append("🔍 Вот ближайшие клиники к вам:\n")
        
    # Показываем топ-3 ближайших клиник
    for clinic, dist in matched_clinics[:3]:
        # Выбираем врачей нужной специализации
        matching_docs = []
        for doc in clinic.get("doctors", []):
            if not specialty or specialty in doc.get("specialty", "").lower():
                matching_docs.append(doc)
                
        docs_str = "\n".join([f"  👨‍⚕️ {doc['name']} ({doc['specialty']}) — {doc.get('rating', '')}" for doc in matching_docs])
        if not docs_str:
            docs_str = "  (Нет свободных врачей по выбранному направлению)"
            
        dist_str = f"{dist:.2f} км" if dist < 999999.0 else "расстояние неизвестно"
        
        response_lines.append(
            f"🏥 **{clinic['name']}** (~{dist_str})\n"
            f"📍 Адрес: {clinic['address']}\n"
            f"📞 Тел: {clinic['phone']}\n"
            f"🕒 Время работы: {clinic.get('working_hours', 'Не указано')}\n"
            f"🩺 Врачи:\n{docs_str}\n"
        )
        
    bot.send_message(chat_id, "\n".join(response_lines), parse_mode="Markdown", reply_markup=get_main_keyboard())


# --- Фотографии ---

@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    chat_id = message.chat.id
    bot.reply_to(message, "Фотография получена. Провожу анализ изображения, пожалуйста, подождите... ⏳")
    
    try:
        photo_index = -2 if len(message.photo) > 1 else -1
        file_info = bot.get_file(message.photo[photo_index].file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        
        analysis_result = analyze_image_with_groq(downloaded_file)
        
        # Парсим динамические кнопки из ответа модели
        clean_text, markup = parse_dynamic_buttons(analysis_result)
        
        # Записываем событие отправки фото и его анализ в историю диалога
        if chat_id not in USER_SESSIONS:
            USER_SESSIONS[chat_id] = []
        USER_SESSIONS[chat_id].append({"role": "user", "content": "[Отправлена фотография для анализа]"})
        USER_SESSIONS[chat_id].append({"role": "assistant", "content": clean_text})
        save_chat_history(chat_id)
        
        bot.reply_to(message, clean_text, reply_markup=markup, parse_mode='Markdown')
        
    except Exception as e:
        print(f"Ошибка анализа фото: {e}")
        bot.reply_to(message, "Произошла непредвиденная ошибка при разборе фотографии. Пожалуйста, попробуйте отправить изображение еще раз.")


# --- Контакты ---

@bot.message_handler(content_types=['contact'])
def handle_contact(message):
    chat_id = message.chat.id
    if not message.contact:
        return
        
    if chat_id in USER_STATES:
        state_data = USER_STATES[chat_id]
        if state_data.get("state") == "EMERGENCY_CONTACT":
            phone = message.contact.phone_number
            state_data["phone"] = phone
            state_data["state"] = "EMERGENCY_NAME"
            
            bot.send_message(
                chat_id,
                "Спасибо! Пожалуйста, напишите ваше **Имя и Фамилию** для завершения вызова:",
                parse_mode="Markdown",
                reply_markup=types.ReplyKeyboardRemove()
            )


# --- Голосовые сообщения ---

@bot.message_handler(content_types=['voice'])
def handle_voice(message):
    chat_id = message.chat.id
    bot.reply_to(message, "Получил голосовое сообщение. Распознаю речь... 🎧")
    
    try:
        file_info = bot.get_file(message.voice.file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        
        # Распознаем текст с помощью Groq Whisper (поддерживает кыргызский, русский и английский)
        transcribed_text = transcribe_voice_with_groq(downloaded_file)
        
        if not transcribed_text.strip():
            bot.reply_to(message, "Не удалось разобрать речь. Пожалуйста, попробуйте записать аудио четче или напишите текстом.")
            return
            
        bot.reply_to(message, f"🗣️ **Распознанный текст:**\n*«{transcribed_text}»*", parse_mode="Markdown")
        
        # Имитируем отправку текстового ответа, подменяя text в объекте message
        message.text = transcribed_text
        handle_text(message)
            
    except Exception as e:
        print(f"Ошибка обработки голосового сообщения: {e}")
        bot.reply_to(message, "Произошла ошибка при обработке голосового сообщения.")


if __name__ == "__main__":
    if bot:
        print("Telegram-бот Санарип успешно запущен и ожидает сообщений...")
        bot.infinity_polling()
    else:
        print("Критическая ошибка: Бот не запущен из-за отсутствия токена.")
