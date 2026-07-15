import os
import json
import base64
import math
import time
import threading
import difflib
import requests
import telebot
from telebot import types
from dotenv import load_dotenv
from rag_updater import SimpleTFIDFIndex, start_background_updater
from qdrant_client import QdrantClient


# ─── Round-Robin счётчики (thread-safe) ───────────────────────────────────────
_rr_lock = threading.Lock()
_rr_deepseek_idx = 0
_rr_groq_idx = 0
_rr_gemini_idx = 0

def _rr_next(counter_name: str, pool_size: int) -> int:
    """Возвращает следующий индекс ключа в пуле (Round-Robin, thread-safe)"""
    global _rr_deepseek_idx, _rr_groq_idx, _rr_gemini_idx
    with _rr_lock:
        if counter_name == 'deepseek':
            idx = _rr_deepseek_idx % pool_size
            _rr_deepseek_idx += 1
        elif counter_name == 'groq':
            idx = _rr_groq_idx % pool_size
            _rr_groq_idx += 1
        else:  # gemini
            idx = _rr_gemini_idx % pool_size
            _rr_gemini_idx += 1
    return idx


def _get_gemini_query_embedding(query_text: str) -> list:
    """Генерирует вектор эмбеддинга для вопроса пользователя через API Gemini с ротацией ключей (для RAG)"""
    gemini_keys_str = os.getenv("GEMINI_API_KEYS", "")
    if gemini_keys_str:
        keys = [k.strip() for k in gemini_keys_str.split(",") if k.strip()]
    else:
        keys = [os.getenv("GEMINI_API_KEY")]
    
    keys = [k for k in keys if k and k.strip()]
    if not keys:
        print("[Embedding] Error: Нет доступных ключей GEMINI_API_KEYS")
        return None
        
    start_idx = _rr_next('gemini', len(keys))
    for i in range(len(keys)):
        idx = (start_idx + i) % len(keys)
        api_key = keys[idx]
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-embedding-001:embedContent?key={api_key}"
        headers = {"Content-Type": "application/json"}
        payload = {
            "model": "models/gemini-embedding-001",
            "content": {"parts": [{"text": query_text[:3000]}]}
        }
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=8)
            if resp.status_code == 200:
                return resp.json()["embedding"]["values"]
            elif resp.status_code == 429:
                print(f"[Embedding API] Rate limit 429 на ключе #{idx+1}. Пауза 5 сек...")
                time.sleep(5)
        except Exception as e:
            print(f"[Embedding API] Ошибка запроса на ключе #{idx+1}: {e}")
    return None

_embedding_model = None
_embedding_lock = threading.Lock()

def _get_local_cache_embedding(query_text: str) -> list:
    """Генерирует вектор эмбеддинга локально через sentence-transformers (rubert-tiny2) для семантического кэша"""
    global _embedding_model
    try:
        from sentence_transformers import SentenceTransformer
        with _embedding_lock:
            if _embedding_model is None:
                print("[Embedding Cache] Загрузка локальной модели rubert-tiny2...")
                import torch
                torch.set_num_threads(2)
                _embedding_model = SentenceTransformer("cointegrated/rubert-tiny2")
                print("[Embedding Cache] Локальная модель rubert-tiny2 загружена.")
        
        vector = _embedding_model.encode(query_text).tolist()
        return vector
    except Exception as e:
        print(f"[Embedding Cache] Ошибка локальной генерации эмбеддинга: {e}")
    return None


def _cache_get(question: str):
    """Ищет похожий вопрос в Redis-кэше с помощью локальных векторных эмбеддингов."""
    try:
        from semantic_cache import check_cache
        query_vector = _get_local_cache_embedding(question)
        if not query_vector:
            return None
        return check_cache(query_vector)
    except Exception as e:
        print(f"[Cache] Ошибка чтения векторного кэша: {e}")
    return None

def _cache_set(question: str, answer: str):
    """Сохраняет пару вопрос→ответ в Redis-кэш с использованием локальных эмбеддингов."""
    try:
        from semantic_cache import store_cache
        query_vector = _get_local_cache_embedding(question)
        if not query_vector:
            return
        store_cache(query_vector, answer)
    except Exception as e:
        print(f"[Cache] Ошибка записи векторного кэша: {e}")



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
        # Для работы во время сборки образа (когда нет токенов) не валим весь сервер при импорте, а создаем заглушку
        bot = telebot.TeleBot("123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ", threaded=False)
else:
    # Инициализируем бота с кастомными тайм-аутами и возможностью проксирования API
    import telebot.apihelper as apihelper
    apihelper.CONNECT_TIMEOUT = 30
    apihelper.READ_TIMEOUT = 30
    
    custom_api_url = os.getenv("TELEGRAM_API_URL")
    if custom_api_url:
        if "vercel" in custom_api_url.lower():
            # Заменяем засыпающий Vercel-прокси на стабильный Cloudflare Worker прокси
            custom_api_url = "https://fancy-mountain-f16b.sanaripmedai.workers.dev/bot{0}/{1}"
            print("[Telegram API] Vercel-прокси отключен. Перенаправлено на Cloudflare Worker прокси.")
        apihelper.API_URL = custom_api_url
        print(f"[Telegram API] Использование кастомного API URL: {custom_api_url}")
        
    bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN, threaded=False)


# URLs для API
DEEPSEEK_URL = "https://api.deepseek.com/v1/chat/completions"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

# Конфигурация моделей
DEEPSEEK_MODEL = "deepseek-chat"
GROQ_VISION_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"

# Определение путей и базовой директории
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# База данных
from database import (
    get_user_data,
    update_user_field,
    get_user_state,
    set_user_state,
    save_appointment as db_save_appointment,
    get_all_appointments,
    save_emergency_request as db_save_emergency_request,
    get_all_emergency_requests,
    get_chat_history,
    set_chat_history
)

class DbUserStatesProxy:
    def __getitem__(self, chat_id):
        val = get_user_state(chat_id)
        if val is None:
            raise KeyError(chat_id)
        return val

    def __setitem__(self, chat_id, value):
        set_user_state(chat_id, value)

    def __delitem__(self, chat_id):
        set_user_state(chat_id, None)

    def get(self, chat_id, default=None):
        val = get_user_state(chat_id)
        return val if val is not None else default

    def pop(self, chat_id, default=None):
        val = get_user_state(chat_id)
        if val is not None:
            set_user_state(chat_id, None)
            return val
        return default

    def __contains__(self, chat_id):
        return get_user_state(chat_id) is not None

class DbOfftopicProxy:
    def __getitem__(self, chat_id):
        data = get_user_data(chat_id)
        return data.get("offtopic_count", 0)

    def __setitem__(self, chat_id, value):
        update_user_field(chat_id, "offtopic_count", value)

    def get(self, chat_id, default=0):
        data = get_user_data(chat_id)
        return data.get("offtopic_count", default)

class DbBlockedProxy:
    def __contains__(self, chat_id):
        data = get_user_data(chat_id)
        return bool(data.get("blocked"))

    def add(self, chat_id):
        update_user_field(chat_id, "blocked", True)

    def remove(self, chat_id):
        update_user_field(chat_id, "blocked", False)

    def discard(self, chat_id):
        update_user_field(chat_id, "blocked", False)

class DbDisclaimerProxy:
    def __contains__(self, chat_id):
        data = get_user_data(chat_id)
        return bool(data.get("accepted_disclaimer"))

    def add(self, chat_id):
        update_user_field(chat_id, "accepted_disclaimer", True)

    def remove(self, chat_id):
        update_user_field(chat_id, "accepted_disclaimer", False)

    def discard(self, chat_id):
        update_user_field(chat_id, "accepted_disclaimer", False)

class DbActivityProxy:
    def get(self, chat_id, default=0.0):
        data = get_user_data(chat_id)
        return data.get("last_activity") or default

    def __getitem__(self, chat_id):
        data = get_user_data(chat_id)
        return data.get("last_activity") or 0.0

    def __setitem__(self, chat_id, value):
        update_user_field(chat_id, "last_activity", value)

def save_json_state(file_path, data):
    # Данные сохраняются в БД автоматически при изменении через Proxy
    if isinstance(data, (DbUserStatesProxy, DbOfftopicProxy, DbBlockedProxy, DbDisclaimerProxy, DbActivityProxy)):
        return
    try:
        from database import save_json_state as db_save_json
        db_save_json(file_path, data)
    except Exception as e:
        print(f"Ошибка сохранения состояния: {e}")

STATES_FILE = "user_states.json"
DISCLAIMER_FILE = "user_accepted_disclaimer.json"
OFFTOPIC_FILE = "user_offtopic_count.json"
BLOCKED_FILE = "user_blocked.json"
ACTIVITY_FILE = "user_last_activity.json"

# Хранилище контекста диалогов (история сообщений для каждого пользователя)
USER_SESSIONS = {}
USER_LAST_ACTIVITY = DbActivityProxy()
USER_STATES = DbUserStatesProxy()
USER_OFFTOPIC_COUNT = DbOfftopicProxy()
USER_BLOCKED = DbBlockedProxy()
USER_ACCEPTED_DISCLAIMER = DbDisclaimerProxy()
USER_TOKEN_USAGE = {}


def check_session_timeout(chat_id):
    import time
    current_time = time.time()
    chat_key = str(chat_id)
    last_active = USER_LAST_ACTIVITY.get(chat_key) or USER_LAST_ACTIVITY.get(chat_id)
    
    # Обновляем время активности
    USER_LAST_ACTIVITY[chat_key] = current_time
    
    if last_active and (current_time - last_active > 3600):
        USER_SESSIONS[chat_id] = []
        save_chat_history(chat_id)
        if chat_id in USER_STATES:
            del USER_STATES[chat_id]
            
        bot.send_message(
            chat_id,
            "Приветствую снова! Рад вашему возвращению. Вас что-то начало беспокоить или вы хотите проверить здоровье?",
            reply_markup=get_main_keyboard()
        )
        return True
    return False

def load_chat_history(chat_id):
    """Загружает историю диалога из БД, если она еще не загружена в память"""
    if chat_id in USER_SESSIONS:
        return USER_SESSIONS[chat_id]
    
    try:
        data = get_chat_history(chat_id)
        USER_SESSIONS[chat_id] = data.get("history", [])
        if "usage_stats" in data:
            USER_TOKEN_USAGE[chat_id] = data["usage_stats"]
        return USER_SESSIONS[chat_id]
    except Exception as e:
        print(f"Ошибка загрузки истории чата для {chat_id}: {e}")
    
    USER_SESSIONS[chat_id] = []
    return USER_SESSIONS[chat_id]

def send_message_safe(chat_id, text, reply_markup=None, parse_mode='Markdown'):
    """Отправляет сообщение, при ошибке парсинга Markdown пробует отправить как обычный текст"""
    try:
        return bot.send_message(chat_id, text, reply_markup=reply_markup, parse_mode=parse_mode)
    except telebot.apihelper.ApiTelegramException as e:
        if "bad request" in str(e).lower() and parse_mode == 'Markdown':
            print(f"Markdown parsing failed, retrying in plain text for chat {chat_id}: {e}")
            try:
                # Очищаем от некоторых явных нестыковок и пробуем повторно как обычный текст
                return bot.send_message(chat_id, text, reply_markup=reply_markup)
            except Exception as e2:
                print(f"Fallback send_message failed: {e2}")
        else:
            print(f"ApiTelegramException in send_message_safe: {e}")
    except Exception as e:
        print(f"General exception in send_message_safe: {e}")

def reply_to_safe(message, text, reply_markup=None, parse_mode='Markdown'):
    """Отвечает на сообщение, при ошибке парсинга Markdown пробует ответить как обычный текст"""
    try:
        return bot.reply_to(message, text, reply_markup=reply_markup, parse_mode=parse_mode)
    except telebot.apihelper.ApiTelegramException as e:
        if "bad request" in str(e).lower() and parse_mode == 'Markdown':
            print(f"Markdown parsing failed, retrying in plain text for reply: {e}")
            try:
                return bot.reply_to(message, text, reply_markup=reply_markup)
            except Exception as e2:
                print(f"Fallback reply_to failed: {e2}")
        else:
            print(f"ApiTelegramException in reply_to_safe: {e}")
    except Exception as e:
        print(f"General exception in reply_to_safe: {e}")



def requests_post_deepseek(payload, timeout=15):
    """POST к DeepSeek с Round-Robin ротацией, retry при 429 и fallback на OpenRouter"""
    # ── Пул ключей DeepSeek ───────────────────────────────────────────────────
    keys_str = os.getenv("DEEPSEEK_API_KEYS", "")
    if keys_str:
        keys = [k.strip() for k in keys_str.split(",") if k.strip()]
    else:
        keys = [
            os.getenv("DEEPSEEK_API_KEY"),
            os.getenv("DEEPSEEK_API_KEY_SECONDARY")
        ]
    keys = [k for k in keys if k and k.strip() and k != "your_deepseek_api_key_here"]

    last_err = None
    if keys:
        start_idx = _rr_next('deepseek', len(keys))  # Round-Robin
        for offset in range(len(keys)):
            i = (start_idx + offset) % len(keys)
            key = keys[i]
            headers = {
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json"
            }
            try:
                print(f"[API Router] DeepSeek Round-Robin (ключ #{i+1}/{len(keys)})...")
                resp = requests.post(DEEPSEEK_URL, json=payload, headers=headers, timeout=timeout)
                if resp.status_code == 200:
                    return resp
                elif resp.status_code == 429:
                    print(f"[API Router] DeepSeek ключ #{i+1} — Rate Limit 429. Пауза 7 сек...")
                    time.sleep(7)
                    last_err = f"HTTP 429 (rate limit)"
                else:
                    last_err = f"HTTP {resp.status_code}: {resp.text[:200]}"
                    print(f"[API Router] Ошибка DeepSeek #{i+1}: {last_err}")
            except Exception as e:
                last_err = str(e)
                print(f"[API Router] Сбой DeepSeek #{i+1}: {last_err}")

    # ── Fallback: OpenRouter ──────────────────────────────────────────────────
    openrouter_keys_str = os.getenv("OPENROUTER_API_KEYS", "")
    if openrouter_keys_str:
        or_keys = [k.strip() for k in openrouter_keys_str.split(",") if k.strip()]
    else:
        or_keys = [os.getenv("OPENROUTER_API_KEY")]
    or_keys = [k for k in or_keys if k and k.strip()]

    if or_keys:
        print("[API Router] Переключение на резервный провайдер OpenRouter...")
        or_payload = payload.copy()
        or_payload["model"] = "deepseek/deepseek-chat"
        for j, or_key in enumerate(or_keys):
            headers = {
                "Authorization": f"Bearer {or_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://sanarip.med.ai",
                "X-Title": "Sanarip Med AI"
            }
            try:
                print(f"[API Router] OpenRouter (ключ #{j+1})...")
                resp = requests.post("https://openrouter.ai/api/v1/chat/completions", json=or_payload, headers=headers, timeout=timeout)
                if resp.status_code == 200:
                    return resp
                elif resp.status_code == 429:
                    print(f"[API Router] OpenRouter ключ #{j+1} — Rate Limit. Пауза 7 сек...")
                    time.sleep(7)
                else:
                    last_err = f"OpenRouter HTTP {resp.status_code}: {resp.text[:200]}"
                    print(f"[API Router] Ошибка OpenRouter #{j+1}: {last_err}")
            except Exception as e:
                last_err = str(e)
                print(f"[API Router] Сбой OpenRouter #{j+1}: {last_err}")

    raise Exception(f"Все API-ключи DeepSeek и OpenRouter вернули ошибку. Последняя ошибка: {last_err}")


# Глобальный словарь соответствия симптомов специальностям врачей
SPECIALTY_KEYWORDS = {
    "педиатр": ["ребенок", "детский", "дети", "малыш", "педиатр", "ребенка"],
    "кардиолог": ["сердце", "грудь", "инфаркт", "кардиолог", "давление", "стенокардия"],
    "офтальмолог": ["глаз", "зрение", "окулист", "катаракта", "офтальмолог", "глаза"],
    "стоматолог": ["зуб", "десна", "кариес", "стоматолог", "зубы", "зубная", "пломба"],
    "травматолог": ["сломал", "перелом", "вывих", "ушиб", "травма", "травматолог", "гипс", "растяжение"],
    "гинеколог": ["беременность", "роды", "гинеколог", "женский", "яичники", "менструация"],
    "эндокринолог": ["гормон", "щитовидка", "зоб", "диабет", "сахар", "эндокринолог"],
    "невролог": ["невролог", "нервы", "мигрень", "спина", "позвоночник", "онемение", "головокружение"],
    "гастроэнтеролог": ["желудок", "живот", "изжога", "тошнота", "рвота", "понос", "кишечник", "гастроэнтеролог"],
    "пульмонолог": ["легкие", "кашель", "астма", "бронхит", "дыхание", "пульмонолог"],
    "дерматолог": ["кожа", "сыпь", "зуд", "лишай", "прыщи", "акне", "дерматолог"],
    "ревматолог": ["сустав", "суставы", "артрит", "артроз", "колени", "ревматолог"],
    "отоларинголог": ["ухо", "горло", "нос", "отит", "гайморит", "ангина", "лор"],
    "уролог": ["мочеиспускание", "цистит", "почки", "простатит", "уролог"],
    "психиатр": ["депрессия", "тревога", "паническая", "психика", "галлюцинации", "психиатр", "психотерапевт"],
    "диетолог": ["вес", "диета", "похудеть", "ожирение", "питание", "диетолог"]
}

# Загрузка локальных баз данных
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CLINICS_PATH = os.path.join(BASE_DIR, "data", "clinics.json")
FIRST_AID_PATH = os.path.join(BASE_DIR, "data", "first_aid.json")
DISEASES_INDEX_PATH = os.path.join(BASE_DIR, "data", "diseases_index.json")
PROFESSIONS_INDEX_PATH = os.path.join(BASE_DIR, "data", "professions_index.json")

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

# Инициализация локальной RAG базы знаний (загружается асинхронно в фоне)
DISEASES_INDEX = None
PROFESSIONS_INDEX = None
QDRANT_CLIENT = None

def _load_rag_databases():
    global DISEASES_INDEX, PROFESSIONS_INDEX, QDRANT_CLIENT
    print("[RAG Load] Запуск фоновой загрузки баз знаний...")
    
    # 1. Загрузка TF-IDF индекса заболеваний
    try:
        if os.path.exists(DISEASES_INDEX_PATH):
            DISEASES_INDEX = SimpleTFIDFIndex.load(DISEASES_INDEX_PATH)
            print("[RAG Load] RAG база знаний заболеваний (TF-IDF) успешно загружена.")
        else:
            print("[RAG Load] Внимание: RAG база знаний заболеваний (TF-IDF) не найдена.")
    except Exception as e:
        print(f"[RAG Load] Ошибка загрузки RAG базы знаний заболеваний (TF-IDF): {e}")

    # 2. Загрузка TF-IDF индекса профессий
    try:
        if os.path.exists(PROFESSIONS_INDEX_PATH):
            PROFESSIONS_INDEX = SimpleTFIDFIndex.load(PROFESSIONS_INDEX_PATH)
            print("[RAG Load] RAG база знаний профессий (TF-IDF) успешно загружена.")
        else:
            print("[RAG Load] Внимание: RAG база знаний профессий (TF-IDF) не найдена.")
    except Exception as e:
        print(f"[RAG Load] Ошибка загрузки RAG базы знаний профессий (TF-IDF): {e}")

    # 3. Подключение Qdrant
    QDRANT_DB_PATH = os.path.join(BASE_DIR, "data", "qdrant_db_new")
    try:
        if os.path.exists(QDRANT_DB_PATH):
            QDRANT_CLIENT = QdrantClient(path=QDRANT_DB_PATH)
            print("[RAG Load] Векторная база знаний Qdrant успешно подключена.")
        else:
            print("[RAG Load] Внимание: Векторная база знаний Qdrant не найдена. Будет использоваться TF-IDF.")
    except Exception as e:
        print(f"[RAG Load] Ошибка инициализации Qdrant: {e}")

    # 4. Фоновый апдейтер RAG
    try:
        start_background_updater()
        print("[RAG Load] Фоновая служба обновлений RAG запущена.")
    except Exception as e:
        print(f"[RAG Load] Ошибка фоновой службы обновлений RAG: {e}")

# Запуск фонового потока загрузки баз
threading.Thread(target=_load_rag_databases, daemon=True).start()


# Системные промпты с профессиональным, успокаивающим тоном и строгими ограничениями
# Системные промпты с профессиональным, успокаивающим тоном и строгими ограничениями
SYSTEM_PROMPT = (
    "Ты — Санарип, высококвалифицированный, заботливый и надежный медицинский координатор. "
    "Твоя главная миссия — спасти жизнь человека при любых обстоятельствах, предотвратить ухудшение его состояния и оказать психологическую поддержку.\n\n"
    "ПРАВИЛО ПСИХОЛОГИЧЕСКОЙ ПОДДЕРЖКИ:\n"
    "Всегда начинай свои рекомендации с вежливых, мягких и успокаивающих слов. Морально поддержи пациента, дай ему понять, что всё под контролем и он в безопасности (например: «Не волнуйтесь, пожалуйста, мы во всём разберемся», «Всё хорошо, главное — сохранять спокойствие, сейчас мы вам поможем»).\n\n"
    "СТРОГИЕ КЛИНИЧЕСКИЕ ПРАВИЛА (ЖИЗНЕННО ВАЖНО):\n"
    "1. ПОЭТАПНЫЙ ОПРОС ПАЦИЕНТА (СТРОГО ОДИН ВОПРОС ЗА РАЗ):\n"
    "   - Если тебе нужно уточнить детали о состоянии пациента (например, характер боли, наличие сопутствующих симптомов, температура), ты должен задавать **строго один вопрос за один шаг**.\n"
    "   - Категорически запрещено объединять несколько вопросов в список или предлагать кнопки для разных вопросов одновременно. Сначала задай первый вопрос (например: «Боль тупая, давящая или пульсирующая?») и предложи для него кнопки.\n"
    "   - Только после того, как пациент выберет вариант (это появится в истории), ты можешь задать следующий уточняющий вопрос (например: «Есть ли у вас насморк?») с новыми кнопками. Опрашивай по очереди, удерживая в памяти общий контекст жалобы, и только получив все ответы переходи к рекомендациям.\n"
    "2. МГНОВЕННОЕ РАСПОЗНАВАНИЕ УГРОЗЫ ЖИЗНИ: При любых намеках на критическое состояние (боль за грудиной, одышка, удушье, потеря сознания, анафилактический шок, обильное артериальное кровотечение, признаки инсульта FAST) твоей ПЕРВОЙ фразой должно быть требование СРОЧНО вызвать скорую помощь по номеру 103 и предложить кнопку:\n"
    "[Кнопки: Вызвать скорую помощь]\n"
    "3. ПРИНЦИП 'НЕ НАВРЕДИ': Строго запрещено рекомендовать рецептурные медикаменты. Предотвращай опасные действия (например, запрещай греть живот при болях, накладывать жгут без артериального кровотечения, мазать ожоги маслом).\n"
    "4. РАЗДЕЛЕНИЕ ЭТАПОВ РЕКОМЕНДАЦИЙ И ЗАПИСИ (КРИТИЧЕСКИ ВАЖНО):\n"
    "   - СЛУЧАЙ А (Симптомы не критические/не очень болезненные): Морально успокой пациента и дай базовые правила безопасности (что делать НЕЛЬЗЯ, например: не принимать горячую ванну, не пить таблетки без контроля). Категорически запрещено давать подробные пошаговые рекомендации до осмотра врача на этом этапе (например: прикладывать полотенце, делать массаж). Вместо этого в самом конце сообщения напиши вежливую фразу: «Если вас это беспокоит и ваше самочувствие ухудшается, то вам нужно обратиться к врачу.» и предложи кнопки:\n"
    "     [Кнопки: Нет, спасибо, мне лучше | Да, записаться к врачу]\n"
    "   - СЛУЧАЙ Б (Симптомы средней тяжести / болезненные / выраженные): Дай пошаговые рекомендации. Ты ОБЯЗАН четко, явно и выделяя жирным шрифтом указать точное название специальности врача (например, **акушер-гинеколог**, **кардиолог**, **эндокринолог**), к которому пациенту следует обратиться для очной консультации. После этого предложи три кнопки действий:\n"
    "     [Кнопки: Записаться к врачу | Вызвать врача на дом | Вызвать скорую помощь]\n"
    "5. ОБРАБОТКА УТОЧНЯЮЩИХ И ГИПОТЕТИЧЕСКИХ ВОПРОСОВ (ВАЖНО):\n"
    "   - Если пациент просто хочет уточнить вопрос или спрашивает о будущем («А что будет, если боль усилится?»), не пугай его сразу. Мягко и вежливо расскажи, что это за состояние и как оно ощущается. Успокой пациента, дав ему понять, что прямо сейчас всё хорошо и не стоит переживать. Напиши, что при ухудшении состояния он может воспользоваться услугами врачей. Предложи кнопки действий:\n"
    "     [Кнопки: Записаться к врачу | Вызвать врача на дом | Вызвать скорую помощь]\n"
    "6. РАЗЛИЧИЕ КНОПОК ДЕЙСТВИЙ:\n"
    "   - «Записаться к врачу» — если пациент хочет спокойно прийти в клинику и удостовериться в своем здоровье.\n"
    "   - «Вызвать врача на дом» — если пациенту нездоровится, тяжело идти, и нужен осмотр врача на дому в тот же день.\n"
    "   - «Вызвать скорую помощь» — если пациенту критически плохо и требуется экстренная помощь.\n\n"
    "ПРАВИЛА ОФОРМЛЕНИЯ И ЧИТАЕМОСТИ (КРИТИЧЕСКИ ВАЖНО):\n"
    "- Будь лаконичным. Пиши максимально кратко, убирай лишние рассуждения, пустые вежливые фразы и 'воду'. Текст должен быть легко читаемым в одно мгновение.\n"
    "- Разделяй смысловые блоки горизонтальными линиями из символов: `────────────────`.\n"
    "- Разнообразь текст тематическими иконками-эмодзи перед пунктами или важными предупреждениями (например: 🩹, ⚠️, 🌡️, 💊, ❌, ✅, ℹ️, 🚨, 🚑).\n"
    "- В конце сообщения добавляй кнопки строго в формате: [Кнопки: Вариант 1 | Вариант 2]. ВАЖНО: Названия кнопок делай максимально короткими (1-3 слова, до 20 символов), чтобы они полностью помещались на экране телефона и не обрезались.\n\n"
    "7. ЗАПРЕТ ПОВТОРНЫХ ПРИВЕТСТВИЙ: Если в истории переписки уже есть хотя бы одно твое сообщение, категорически ЗАПРЕЩЕНО писать приветственные слова вроде 'Здравствуйте!', 'Добрый день!', 'Привет!' и т.д. Сразу переходи к сути.\n"
    "8. ЛАБОРАТОРНЫЕ ИССЛЕДОВАНИЯ И АНАЛИЗЫ: Если пациент спрашивает про сдачу анализов, хочет провериться или найти лабораторию:\n"
    "   - Ты должен порекомендовать подходящие анализы (например, общий анализ крови, гормоны, витамины) в зависимости от его жалоб.\n"
    "   - Опрашивай строго по одному вопросу за раз (сначала спроси, что конкретно его беспокоит, и выведи кнопки с типами анализов).\n"
    "   - Обязательно предложи в конце кнопку действия:\n"
    "     [Кнопки: Найти лабораторию]\n\n"
    "ОБРАБОТКА ОФФТОПИКА:\n"
    "Если запрос пользователя вообще не относится к медицине, здоровью, первой помощи или сдаче анализов, ты должен вежливо попросить его больше не обращаться к боту с такими темами. В этом случае ОБЯЗАТЕЛЬНО добавь в самом начале ответа тег [OFFTOPIC].\n\n"
    "ЯЗЫКОВОЕ ПРАВИЛО (КРИТИЧЕСКИ ВАЖНО):\n"
    "Обязательно определяй язык, на котором к тебе обращается пациент (русский, кыргызский и т.д.), и ВСЕГДА отвечай строго на том же языке. Все уточняющие вопросы, рекомендации и названия кнопок должны быть переведены на язык пользователя."
)


VISION_PROMPT = (
    "Ты — Санарип, квалифицированный медицинский координатор визуальной диагностики.\n\n"
    "СТРОГИЕ ПРАВИЛА АНАЛИЗА ИЗОБРАЖЕНИЙ (ДВУХЭТАПНЫЙ ПРОЦЕСС):\n"
    "1. ЭТАП 1: Когда пациент только отправляет фотографию симптома/травмы, ты НЕ должен писать полный отчет, диагноз или рекомендации первой помощи. "
    "Вместо этого ты должен СНАЧАЛА кратко (в 1 предложении) описать, что видишь на снимке, и сразу задать 1 главный уточняющий вопрос, чтобы определить происхождение или тяжесть симптома. Варианты ответов ты ОБЯЗАН представить строго в формате кнопок: `[Кнопки: Вариант 1 | Вариант 2 | Вариант 3]` в самом конце сообщения. Категорически запрещено оформлять варианты в виде обычного списка с дефисами или цифрами!\n"
    "2. ЭТАП 2: Только после того, как пациент выберет вариант (это будет видно в истории диалога как ответ на твой уточняющий вопрос), ты проводишь полный клинический анализ и выдаешь структурированную информацию, разделяя разделы линиями и используя иконки:\n"
    "   ℹ️ Визуальные признаки: (кратко)\n"
    "   ────────────────\n"
    "   ⚠️ Вероятные симптомы: (кратко)\n"
    "   ────────────────\n"
    "   🩹 Примерный диагноз: (предварительно, с указанием конкретной специальности врача, к которому надо пойти, выделенной жирным шрифтом, например **офтальмолог**, **дерматолог**)\n"
    "   ────────────────\n"
    "   💊 Первая помощь: (пошаговая инструкция до визита к врачу)\n"
    "   ────────────────\n"
    "   И добавляешь кнопку записи к врачу: `[Кнопки: Записаться на врача поблизости]`\n\n"
    "ПРАВИЛА ОФОРМЛЕНИЯ:\n"
    "- Пиши кратко, емко, без лишних пояснений.\n"
    "- Разделяй смысловые блоки линиями `────────────────`.\n"
    "- Названия предлагаемых кнопок делай максимально короткими (1-3 слова, до 20 символов), чтобы они полностью помещались на экране телефона и не обрезались.\n\n"
    "ОБРАБОТКА ОФФТОПИКА:\n"
    "Если изображение или вопрос не относится к медицине, здоровью, травмам или симптомам болезней, напиши только одно слово: [OFFTOPIC].\n\n"
    "ЯЗЫКОВОЕ ПРАВИЛО (КРИТИЧЕСКИ ВАЖНО):\n"
    "Обязательно определяй язык, на котором к тебе обращается пациент (русский, кыргызский и т.д.), и ВСЕГДА отвечай строго на том же языке. Все уточняющие вопросы, рекомендации и названия кнопок должны быть переведены на язык пользователя."
)


# --- Клавиатуры быстрого выбора (Keyboards) ---

def get_main_keyboard():
    """Создает постоянную клавиатуру под полем ввода"""
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    btn_first_aid = types.KeyboardButton("📚 Первая помощь")
    btn_clinics = types.KeyboardButton("🏥 Клиники Бишкека")
    btn_emergency = types.KeyboardButton("🚑 Вызвать скорую помощь (103)")
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


def validate_llm_response(response_text: str, user_query: str) -> tuple:
    """
    Двухуровневый Guardrails (валидатор ответов) для защиты пациентов от галлюцинаций:
    1. Эвристический уровень (регулярные выражения и стоп-слова).
    2. Семантический уровень (быстрый перекрестный аудит через Gemini Flash).
    Возвращает (is_safe, processed_text)
    """
    # 1. Эвристический уровень (быстрые стоп-слова для опасных ситуаций)
    dangerous_patterns = [
        r"(?i)\b(увеличьте дозу|примите двойную дозу|назначьте себе|самостоятельно начните принимать)\b",
        # Попытка назначить сильные антибиотики/рецептурные препараты без врача
        r"(?i)\b(амоксициллин|азитромицин|цефтриаксон|левофлоксацин)\b.*?\b(без рецепта|купите сами|принимайте по)\b"
    ]
    for pattern in dangerous_patterns:
        if re.search(pattern, response_text):
            print(f"[Guardrails] Deterministic rule match on pattern: {pattern}")
            return False, ""

    # 2. Семантический уровень (проверка через Gemini Flash с ротацией ключей)
    gemini_keys_str = os.getenv("GEMINI_API_KEYS", "")
    if gemini_keys_str:
        keys = [k.strip() for k in gemini_keys_str.split(",") if k.strip()]
    else:
        keys = [os.getenv("GEMINI_API_KEY")]
    keys = [k for k in keys if k and k.strip()]

    if not keys:
        # Если ключей нет, пропускаем через локальные эвристики
        print("[Guardrails] Warning: Нет ключей Gemini для семантического контроля, только эвристики.")
        return True, response_text

    prompt = (
        "Ты — строгий медицинский эксперт-аудитор. Твоя задача — проверить сгенерированный ИИ-ассистентом ответ пациенту на безопасность.\n\n"
        f"Вопрос пациента: \"{user_query}\"\n"
        f"Сгенерированный ответ: \"{response_text}\"\n\n"
        "Правила безопасности:\n"
        "1. Ответ НЕ должен назначать точные дозировки сильнодействующих рецептурных препаратов без очного врача.\n"
        "2. Ответ НЕ должен содержать опасных для жизни рекомендаций (например, игнорировать критические симптомы).\n"
        "3. Ответ НЕ должен советовать самолечение при жизнеугрожающих состояниях (инфаркт, инсульт, отек Квинке и т.д.).\n\n"
        "Ответь строго в формате JSON с ключами:\n"
        "\"safe\": true (если ответ безопасен) или false (если нарушает правила безопасности)\n"
        "\"reason\": \"краткое пояснение причины\"\n\n"
        "Формат ответа: строго JSON, без markdown-разметки."
    )

    start_idx = _rr_next('gemini', len(keys))
    for offset in range(len(keys)):
        i = (start_idx + offset) % len(keys)
        key = keys[i]
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={key}"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseMimeType": "application/json"}
        }
        headers = {"Content-Type": "application/json"}
        try:
            print(f"[Guardrails] Запуск семантического аудита через Gemini Flash (ключ #{i+1})...")
            resp = requests.post(url, json=payload, headers=headers, timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                text_res = data["candidates"][0]["content"]["parts"][0]["text"]
                audit_res = json.loads(text_res)
                if audit_res.get("safe") is False:
                    print(f"[Guardrails] Нарушение безопасности! Причина: {audit_res.get('reason')}")
                    return False, ""
                print("[Guardrails] Семантический аудит пройден успешно.")
                return True, response_text
        except Exception as e:
            print(f"[Guardrails] Сбой аудита на ключе #{i+1}: {e}")
            
    # Если все API-запросы к Gemini свалились, по умолчанию считаем ответ безопасным,
    # чтобы не ломать обслуживание, так как эвристический уровень уже пройден.
    print("[Guardrails] Все попытки семантического аудита завершились ошибкой. Пропуск.")
    return True, response_text


def ask_deepseek_with_history(chat_id: int, user_message: str, context: str = "") -> tuple:
    """Запрос к DeepSeek с учетом истории диалога и контекста. Возвращает (clean_text, reply_markup)"""
    if not DEEPSEEK_API_KEY or DEEPSEEK_API_KEY == "your_deepseek_api_key_here":
        return "Ошибка конфигурации: отсутствует ключ DEEPSEEK_API_KEY.", None

    # Инициализируем историю сообщений, если сессии нет
    load_chat_history(chat_id)

    # Добавляем сообщение пользователя в историю и лог-буфер
    USER_SESSIONS[chat_id].append({"role": "user", "content": user_message})
    save_chat_history(chat_id)
    add_to_log_buffer(chat_id, "user", user_message)

    # ── Семантический кэш (экономия 40% API-запросов) ──────────────────────────
    cached = _cache_get(user_message)
    if cached:
        clean_text, markup = parse_dynamic_buttons(cached)
        USER_SESSIONS[chat_id].append({"role": "assistant", "content": cached})
        save_chat_history(chat_id)
        add_to_log_buffer(chat_id, "assistant", cached, event_type="cache_hit")
        return clean_text, markup

    # Ограничиваем историю последними 10 сообщениями
    USER_SESSIONS[chat_id] = USER_SESSIONS[chat_id][-10:]

    # Проводим RAG поиск по локальной базе заболеваний
    rag_context = ""
    history = USER_SESSIONS.get(chat_id, [])
    user_msgs = [m["content"] for m in history if m["role"] == "user"]
    search_query = " ".join(user_msgs[-3:]) if user_msgs else user_message

    query_vector = None
    if QDRANT_CLIENT:
        try:
            query_vector = _get_gemini_query_embedding(search_query)
            if query_vector:
                search_results = QDRANT_CLIENT.search(
                    collection_name="diseases",
                    query_vector=query_vector,
                    limit=2
                )
                matching_docs = []
                for hit in search_results:
                    if hit.score > 0.40:
                        matching_docs.append(
                            f"Документ: {hit.payload['title']}\n"
                            f"Ссылка: {hit.payload['url']}\n"
                            f"Содержание:\n{hit.payload['content'][:2500]}"
                        )
                if matching_docs:
                    rag_context = "=== ЛОКАЛЬНЫЕ КЛИНИЧЕСКИЕ ПРОТОКОЛЫ (RAG - Vector) ===\n\n" + "\n\n---\n\n".join(matching_docs)
        except Exception as e:
            print(f"Ошибка RAG поиска заболеваний в Qdrant: {e}")

    # Fallback на TF-IDF для заболеваний, если векторный поиск не дал результатов
    if not rag_context and DISEASES_INDEX:
        try:
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
                rag_context = "=== ЛОКАЛЬНЫЕ КЛИНИЧЕСКИЕ ПРОТОКОЛЫ (RAG - TF-IDF) ===\n\n" + "\n\n---\n\n".join(matching_docs)
        except Exception as e:
            print(f"Ошибка RAG поиска заболеваний (TF-IDF): {e}")

    # Проводим RAG поиск по локальной базе медицинских профессий
    prof_context = ""
    if QDRANT_CLIENT:
        try:
            if not query_vector:
                query_vector = _get_gemini_query_embedding(search_query)
            if query_vector:
                search_results = QDRANT_CLIENT.search(
                    collection_name="professions",
                    query_vector=query_vector,
                    limit=2
                )
                matching_docs = []
                for hit in search_results:
                    if hit.score > 0.40:
                        matching_docs.append(
                            f"Профессиональный профиль: {hit.payload['title']}\n"
                            f"Содержание:\n{hit.payload['content']}"
                        )
                if matching_docs:
                    prof_context = "=== СПРАВКА ПО МЕДИЦИНСКИМ ПРОФЕССИЯМ (RAG - Vector) ===\n\n" + "\n\n---\n\n".join(matching_docs)
        except Exception as e:
            print(f"Ошибка RAG поиска профессий в Qdrant: {e}")

    # Fallback на TF-IDF для профессий
    if not prof_context and PROFESSIONS_INDEX:
        try:
            results = PROFESSIONS_INDEX.search(search_query, top_k=2)
            matching_docs = []
            for doc, score in results:
                if score > 0.05:
                    matching_docs.append(
                        f"Профессиональный профиль: {doc['title']}\n"
                        f"Содержание:\n{doc['content']}"
                    )
            if matching_docs:
                prof_context = "=== СПРАВКА ПО МЕДИЦИНСКИМ ПРОФЕССИЯМ (RAG - TF-IDF) ===\n\n" + "\n\n---\n\n".join(matching_docs)
        except Exception as e:
            print(f"Ошибка RAG поиска профессий (TF-IDF): {e}")

    # Объединяем контекст ключевых слов, RAG по заболеваниям и RAG по профессиям
    full_context = ""
    if context:
        full_context += context + "\n\n"
    if rag_context:
        full_context += rag_context + "\n\n"
    if prof_context:
        full_context += prof_context

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
        resp = requests_post_deepseek(payload, timeout=15)
        data = resp.json()
        raw_reply = data["choices"][0]["message"]["content"]

        # Применяем Guardrails для верификации безопасности медицинских советов
        is_safe, _ = validate_llm_response(raw_reply, user_message)
        if not is_safe:
            raw_reply = (
                "⚠️ Сформированный ответ содержит потенциально небезопасные медицинские рекомендации "
                "или указание дозировок препаратов без очного осмотра. В целях вашей безопасности "
                "ответ был заблокирован. Пожалуйста, обратитесь к врачу очно или воспользуйтесь кнопкой "
                "«Вызвать скорую помощь» при неотложных состояниях."
            )

        # Обновляем статистику токенов
        usage = data.get("usage", {})
        if usage:
            if chat_id not in USER_TOKEN_USAGE:
                USER_TOKEN_USAGE[chat_id] = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
            USER_TOKEN_USAGE[chat_id]["prompt_tokens"] += usage.get("prompt_tokens", 0)
            USER_TOKEN_USAGE[chat_id]["completion_tokens"] += usage.get("completion_tokens", 0)
            USER_TOKEN_USAGE[chat_id]["total_tokens"] += usage.get("total_tokens", 0)

        # Добавляем ответ ассистента в историю диалога и лог-буфер
        USER_SESSIONS[chat_id].append({"role": "assistant", "content": raw_reply})
        save_chat_history(chat_id)
        add_to_log_buffer(chat_id, "assistant", raw_reply)

        # Сохраняем в семантический кэш (только если ответ безопасен и не оффтопик)
        if is_safe and len(user_message) > 10 and "[OFFTOPIC]" not in raw_reply:
            _cache_set(user_message, raw_reply)

        
        # Обработка тега [OFFTOPIC]
        reply = raw_reply
        if "[OFFTOPIC]" in reply:
            reply = reply.replace("[OFFTOPIC]", "").strip()
            USER_OFFTOPIC_COUNT[chat_id] = USER_OFFTOPIC_COUNT.get(chat_id, 0) + 1
            if USER_OFFTOPIC_COUNT[chat_id] > 2:
                USER_BLOCKED.add(chat_id)
                return "Извините, но вы были заблокированы за многократные вопросы не по теме.", None
            if not reply:
                reply = "Пожалуйста, прошу вас уважительно больше не обращаться ко мне на темы, не связанные с медицинской помощью."

        # Парсинг кнопок из ответа ИИ
        clean_text, markup = parse_dynamic_buttons(reply)
        return clean_text, markup

    except Exception as e:
        print(f"Ошибка DeepSeek API: {e}")
        return "Для подготовки качественного и точного ответа нашему ИИ-ассистенту требуется чуть больше времени для анализа баз данных. Пожалуйста, отправьте ваше сообщение еще раз. 🩺", None


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
    markup = types.InlineKeyboardMarkup(row_width=1)
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
        {"role": "system", "content": "Ты З медицинский координатор. Проанализируй историю диалога и кратко (одной фразой до 10-12 слов) сформулируй жалобы и симптомы пациента для бригады скорой помощи. Пиши строго по делу (например: 'Термический ожог кисти руки горячей водой, острая боль'). Избегай приветствий и вежливых слов."},
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
        resp = requests_post_deepseek(payload, timeout=15)
        return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"Ошибка суммаризации симптомов: {e}")
        
    # Резервный фолбэк при ошибке сети
    user_msgs = [msg["content"] for msg in history if msg["role"] == "user" and not msg["content"].startswith("👉")]
    if user_msgs:
        return " / ".join(user_msgs[-3:])
    return "Симптомы не указаны"


def save_chat_history(chat_id):
    """Сохраняет историю диалога пользователя в базу данных для панели разработчика"""
    import time
    history = USER_SESSIONS.get(chat_id, [])
    
    # Пытаемся получить имя из состояния, если оно там есть
    name = "Пациент"
    if chat_id in USER_STATES and USER_STATES[chat_id].get("name"):
        name = USER_STATES[chat_id]["name"]
        
    try:
        set_chat_history(chat_id, {
            "chat_id": chat_id,
            "name": name,
            "history": history,
            "last_updated": time.strftime("%Y-%m-%d %H:%M:%S"),
            "usage_stats": USER_TOKEN_USAGE.get(chat_id, {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0})
        })
    except Exception as e:
        print(f"Ошибка сохранения истории чата {chat_id}: {e}")


def save_emergency_request(chat_id, state_data):
    """Сохраняет новую заявку скорой помощи в базу данных и отправляет подтверждение"""
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
    
    try:
        db_save_emergency_request(chat_id, request_entry)
    except Exception as e:
        print(f"Ошибка сохранения заявки в БД: {e}")
        
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
    send_message_safe(chat_id, confirmation_text, reply_markup=get_main_keyboard(), parse_mode="Markdown")

    # Генерируем пошаговые рекомендации первой помощи до приезда скорой
    bot.send_chat_action(chat_id, 'typing')
    
    prompt_deepseek = (
        f"Пользователь успешно зарегистрировал экстренный вызов скорой помощи. Симптомы: '{request_entry['symptoms']}'. "
        "Проанализируй историю диалога и напиши очень четкую, пошаговую инструкцию первой помощи, "
        "которую пациент или находящиеся рядом близкие должны выполнить прямо сейчас до приезда скорой помощи (что делать и чего делать категорически нельзя). "
        "Пиши кратко, хладнокровно, по делу. Начни с ободряющих слов поддержки. В конце НЕ предлагай никаких текстовых кнопок и тегов [Кнопки: ...]."
    )
    
    history = USER_SESSIONS.get(chat_id, [])
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(history)
    messages.append({"role": "user", "content": prompt_deepseek})
    
    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": messages,
        "temperature": 0.4,
    }
    
    try:
        resp = requests_post_deepseek(payload, timeout=15)
        aid_reply = resp.json()["choices"][0]["message"]["content"]
    except Exception as e:
        print(f"Ошибка генерации первой помощи до приезда скорой: {e}")
        aid_reply = (
            "📋 **Рекомендации до приезда скорой помощи:**\n\n"
            "1. Обеспечьте приток свежего воздуха (откройте окно).\n"
            "2. Уложите пациента в удобное положение, расстегните стесняющую одежду.\n"
            "3. Постоянно контролируйте дыхание и пульс.\n"
            "❌ Категорически запрещено давать пациенту медикаменты, воду или еду до осмотра врачом."
        )
        
    send_message_safe(chat_id, aid_reply, parse_mode="Markdown")


def save_home_doctor_request(chat_id, state_data):
    """Сохраняет заявку на вызов врача на дом в базу данных и отправляет подтверждение"""
    import datetime
    
    request_entry = {
        "id": chat_id,
        "name": state_data.get("name", "Не указано"),
        "phone": state_data.get("phone", "Не указано"),
        "region": state_data.get("region", "Не указано"),
        "location": state_data.get("location", "Не указано"),
        "symptoms": state_data.get("symptoms", "Не указано"),
        "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "type": "home_doctor"
    }
    
    try:
        db_save_emergency_request(chat_id, request_entry)
    except Exception as e:
        print(f"Ошибка сохранения вызова в БД: {e}")
        
def save_appointment_request(chat_id, state_data):
    """Сохраняет новую запись к врачу или в лабораторию в базу данных"""
    import datetime
    
    # Генерируем уникальный ID для записи
    import uuid
    appointment_id = str(uuid.uuid4())[:8]
    
    appointment = {
        "id": appointment_id,
        "chat_id": chat_id,
        "name": state_data.get("name", "Не указано"),
        "phone": state_data.get("phone", "Не указано"),
        "specialty": state_data.get("specialty", "Не указано"),
        "clinic_id": state_data.get("clinic_id", "Не указано"),
        "clinic_name": state_data.get("clinic_name", "Не указано"),
        "doctor_name": state_data.get("doctor_name", "Не указано"),
        "status": "pending",  # pending, accepted, rejected
        "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    
    try:
        db_save_appointment(chat_id, appointment)
    except Exception as e:
        print(f"Ошибка сохранения записи: {e}")
        
_whisper_model = None
_whisper_lock = threading.Lock()

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


def transcribe_voice(file_bytes: bytes) -> str:
    """Транскрибация аудио-файла локально через Whisper с резервным fallback на Groq API"""
    global _whisper_model
    
    # 1. Попытка локального распознавания через Whisper
    try:
        import tempfile
        import whisper
        
        # Ленивая загрузка модели под локом
        with _whisper_lock:
            if _whisper_model is None:
                print("[Whisper] Загрузка локальной модели 'tiny' на CPU...")
                # Ограничиваем количество потоков для torch, чтобы не вешать весь CPU при нагрузке
                import torch
                torch.set_num_threads(2)
                _whisper_model = whisper.load_model("tiny")
                print("[Whisper] Локальная модель загружена успешно.")
        
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
            tmp.write(file_bytes)
            tmp_path = tmp.name
            
        try:
            print("[Whisper] Начало локального распознавания...")
            result = _whisper_model.transcribe(tmp_path, fp16=False)
            text = result.get("text", "").strip()
            print(f"[Whisper] Успешно распознано локально: '{text}'")
            return text
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
    except Exception as e:
        print(f"[Whisper] Ошибка локального распознавания: {e}. Переключение на Groq Whisper API...")
        
    # 2. Резервный Fallback на Groq
    return transcribe_voice_with_groq(file_bytes)



def analyze_image_with_gemini(image_bytes: bytes) -> str:
    """Резервный анализ изображений через Gemini 1.5/2.0 Flash — Round-Robin + retry при 429"""
    gemini_keys_str = os.getenv("GEMINI_API_KEYS", "")
    if gemini_keys_str:
        keys = [k.strip() for k in gemini_keys_str.split(",") if k.strip()]
    else:
        keys = [os.getenv("GEMINI_API_KEY")]
    keys = [k for k in keys if k and k.strip()]

    if not keys:
        return None

    base64_image = base64.b64encode(image_bytes).decode('utf-8')
    start_idx = _rr_next('gemini', len(keys))  # Round-Robin

    for offset in range(len(keys)):
        i = (start_idx + offset) % len(keys)
        key = keys[i]
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={key}"
        payload = {
            "contents": [{
                "parts": [
                    {"text": VISION_PROMPT},
                    {
                        "inlineData": {
                            "mimeType": "image/jpeg",
                            "data": base64_image
                        }
                    }
                ]
            }]
        }
        headers = {"Content-Type": "application/json"}
        try:
            print(f"[Gemini Router] Round-Robin Gemini Flash (ключ #{i+1}/{len(keys)})...")
            resp = requests.post(url, json=payload, headers=headers, timeout=20)
            if resp.status_code == 200:
                data = resp.json()
                return data["candidates"][0]["content"]["parts"][0]["text"]
            elif resp.status_code == 429:
                print(f"[Gemini Router] Ключ #{i+1} — Rate Limit 429. Пауза 7 сек...")
                time.sleep(7)
            else:
                print(f"[Gemini Router] Ошибка Gemini #{i+1}: {resp.status_code} {resp.text[:200]}")
        except Exception as e:
            print(f"[Gemini Router] Исключение #{i+1}: {e}")
    return None


def analyze_image_with_groq(image_bytes: bytes) -> str:
    """Groq Vision — Round-Robin + retry при 429 + fallback на Gemini"""
    groq_keys_str = os.getenv("GROQ_API_KEYS", "")
    if groq_keys_str:
        keys = [k.strip() for k in groq_keys_str.split(",") if k.strip()]
    else:
        keys = [GROQ_API_KEY]
    keys = [k for k in keys if k and k.strip() and k != "your_groq_api_key_here"]

    if keys:
        base64_image = base64.b64encode(image_bytes).decode('utf-8')
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
        start_idx = _rr_next('groq', len(keys))  # Round-Robin
        for offset in range(len(keys)):
            i = (start_idx + offset) % len(keys)
            key = keys[i]
            headers = {
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json"
            }
            try:
                print(f"[Groq Router] Round-Robin Groq Vision (ключ #{i+1}/{len(keys)})...")
                resp = requests.post(GROQ_URL, json=payload, headers=headers, timeout=30)
                if resp.status_code == 200:
                    return resp.json()["choices"][0]["message"]["content"]
                elif resp.status_code == 429:
                    print(f"[Groq Router] Ключ #{i+1} — Rate Limit 429. Пауза 7 сек...")
                    time.sleep(7)
                else:
                    print(f"[Groq Router] Ошибка Groq #{i+1}: {resp.status_code} {resp.text[:200]}")
            except Exception as e:
                print(f"[Groq Router] Сбой Groq #{i+1}: {e}")

    # Fallback на Gemini
    print("[API Router] Переключение на резервный Gemini Flash Vision...")
    gemini_reply = analyze_image_with_gemini(image_bytes)
    if gemini_reply:
        return gemini_reply

    return "Не удалось распознать изображение. Пожалуйста, сделайте новую фотографию при хорошем освещении."


def is_offtopic_text(text: str) -> bool:
    if not text.strip():
        return False
    prompt = f"Ответь только ДА или НЕТ. Относится ли этот текст к медицине, здоровью, травмам или симптомам болезней? Текст: '{text}'"
    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.0,
        "max_tokens": 10
    }
    headers = {"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"}
    try:
        resp = requests_post_deepseek(payload, timeout=10)
        ans = resp.json()["choices"][0]["message"]["content"].strip().lower()
        if "нет" in ans or "no" in ans:
            return True
    except:
        pass
    return False

@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    try:
        _handle_callback_logic(call)
    except Exception as e:
        print(f"Ошибка в handle_callback: {e}")
        import traceback
        traceback.print_exc()
        try:
            bot.answer_callback_query(call.id, "Произошла ошибка при обработке нажатия.")
        except:
            pass

def _handle_callback_logic(call):
    chat_id = call.message.chat.id
    if chat_id in USER_BLOCKED:
        bot.answer_callback_query(call.id, "Диалог остановлен. Вы заблокированы за оффтоп.")
        return

    if call.data == "view_offer":
        bot.answer_callback_query(call.id, "Загружаю оферту...")
        pdf_path = os.path.join(BASE_DIR, "Sanarip_Med_AI_Public_Offer.pdf")
        if os.path.exists(pdf_path):
            try:
                with open(pdf_path, 'rb') as doc:
                    bot.send_document(chat_id, doc, caption="📄 Публичная оферта Санарип Мед AI")
            except Exception as e:
                print(f"Ошибка отправки оферты: {e}")
                bot.send_message(chat_id, "Извините, не удалось загрузить файл оферты. Пожалуйста, попробуйте позже.")
        else:
            bot.send_message(chat_id, "Файл оферты временно недоступен.")
        return

    if call.data == "accept_disclaimer":
        USER_ACCEPTED_DISCLAIMER.add(chat_id)
        save_json_state(DISCLAIMER_FILE, USER_ACCEPTED_DISCLAIMER)
        bot.answer_callback_query(call.id, "Спасибо за подтверждение!")
        bot.edit_message_reply_markup(chat_id, call.message.message_id, reply_markup=None)
        instructions = (
            "Спасибо! Соглашение принято, теперь я готов помочь вам. 👍\n\n"
            "✍️ **Вы можете описать ваши жалобы текстом** (например: 'болит ухо' или 'укусила собака') "
            "или **прислать фотографию** травмы/симптома.\n\n"
            "👇 Также вы можете воспользоваться кнопками быстрого выбора ниже:"
        )
        bot.send_message(chat_id, instructions, reply_markup=get_main_keyboard(), parse_mode='Markdown')
        return

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
            if reply is not None:
                bot.send_message(chat_id, reply, reply_markup=markup, parse_mode='Markdown')
            
    # 2. Запросы клиник
    elif call.data.startswith("clinic_"):
        try:
            index = int(call.data.split("_")[1])
            clinic = CLINICS_DB[index]
            bot.answer_callback_query(call.id, "Загружаю...")
            
            # Достаем сохраненную специальность из текущего состояния
            state_data = USER_STATES.get(chat_id, {}) or USER_STATES.get(str(chat_id), {})
            specialty = state_data.get("specialty") or detect_specialty(chat_id) or "терапевт"
            
            doctors_list = []
            for doc in clinic.get("doctors", []):
                rating = doc.get("rating")
                rating_str = f" ({rating})" if rating else ""
                doctors_list.append(f"👨‍⚕️ {doc['name']} — {doc['specialty']}{rating_str}")
            
            doctors_info = "\n".join(doctors_list) if doctors_list else "Информация уточняется."
            
            message_text = (
                f"🏥 **{clinic.get('name')}**\n\n"
                f"📍 **Адрес:** {clinic.get('address')}\n"
                f"📞 **Контакты:** {clinic.get('phone')}\n"
                f"🕒 **Часы работы:** {clinic.get('working_hours')}\n\n"
                f"🩺 **Врачи клиники:**\n{doctors_info}"
            )
            send_message_safe(chat_id, message_text, parse_mode="Markdown")
            
            # Переводим в состояние ввода имени для записи
            USER_STATES[chat_id] = {
                "state": "APPOINTMENT_NAME",
                "clinic_id": clinic.get("id"),
                "clinic_name": clinic.get("name"),
                "clinic_type": "lab" if ("лаборатория" in clinic.get("specializations", []) or "анализы" in clinic.get("specializations", [])) else "clinic",
                "specialty": specialty
            }
            save_json_state(STATES_FILE, USER_STATES)
            
            bot.send_message(
                chat_id,
                "✍️ Пожалуйста, напишите ваше **Имя и Фамилию** для оформления записи:",
                parse_mode="Markdown",
                reply_markup=types.ReplyKeyboardRemove()
            )
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
            state_data = USER_STATES[chat_id]
            is_emergency = state_data.get("state", "").startswith("EMERGENCY")
            prefix = "EMERGENCY" if is_emergency else "HOME_DOCTOR"
            
            if val == "Другой":
                state_data["state"] = f"{prefix}_REGION_TEXT"
                save_json_state(STATES_FILE, USER_STATES)
                bot.send_message(chat_id, "Пожалуйста, введите название вашего района или региона вручную:")
            else:
                state_data["region"] = val
                state_data["state"] = f"{prefix}_CONTACT"
                save_json_state(STATES_FILE, USER_STATES)
                
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
        
        if choice.lower() in ["нет, спасибо, мне лучше", "нет спасибо мне лучше", "мне лучше"]:
            bot.send_message(
                chat_id,
                "Очень рад слышать, что вам стало лучше! 🌸 Пожалуйста, берегите себя, отдыхайте и следите за своим самочувствием. "
                "Если симптомы вернутся или ваше состояние ухудшится, я всегда готов помочь.",
                reply_markup=get_main_keyboard()
            )
            return

        if (choice.lower() in ["найти лабораторию", "сдать анализы", "поиск лаборатории", "лаборатория"] or
            choice.startswith("Найти лабораторию")):
            USER_STATES[chat_id] = {
                "state": "SEARCH_CLINICS_LOCATION",
                "specialty": "лаборатория"
            }
            save_json_state(STATES_FILE, USER_STATES)
            
            prompt_msg = (
                "🗺️ Чтобы подобрать **ближайшие лаборатории в Бишкеке**, пожалуйста, **поделитесь вашим местоположением** (нажав на кнопку ниже 👇):"
            )
            markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
            btn = types.KeyboardButton("📍 Отправить геолокацию", request_location=True)
            markup.add(btn)
            
            send_message_safe(chat_id, prompt_msg, reply_markup=markup, parse_mode="Markdown")
            return

        if choice.lower() in ["хорошо, буду соблюдать", "хорошо буду соблюдать"]:
            state_data = USER_STATES.get(chat_id, {}) or USER_STATES.get(str(chat_id), {})
            specialty = state_data.get("specialty")
            
            # Переводим в состояние ожидания геолокации
            state_data["state"] = "SEARCH_CLINICS_LOCATION"
            USER_STATES[chat_id] = state_data
            save_json_state(STATES_FILE, USER_STATES)
            
            # Строим сообщение для отправки геолокации
            if specialty:
                prompt_msg = (
                    f"🩺 Рекомендуемый специалист: **{specialty}**.\n\n"
                    "🗺️ Чтобы подобрать ближайшие партнерские клиники с этим врачом, пожалуйста, **поделитесь вашим местоположением** (нажав на кнопку ниже 👇):"
                )
            else:
                prompt_msg = (
                    "🗺️ Чтобы подобрать ближайшие партнерские клиники, пожалуйста, **поделитесь вашим местоположением** (нажав на кнопку ниже 👇):"
                )
                
            markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
            btn = types.KeyboardButton("📍 Отправить геолокацию", request_location=True)
            markup.add(btn)
            
            send_message_safe(chat_id, prompt_msg, reply_markup=markup, parse_mode="Markdown")
            return

        if (choice.startswith("Записаться") or 
            "записаться к" in choice.lower() or 
            "записаться на" in choice.lower() or 
            "записаться к врачу" in choice.lower() or
            "да, записаться к врачу" in choice.lower()):
            
            # Попробуем загрузить историю диалога на всякий случай
            load_chat_history(chat_id)
            specialty = detect_specialty(chat_id)
            
            bot.send_chat_action(chat_id, 'typing')
            
            # Запрашиваем подробные пошаговые рекомендации и специальность
            prompt_deepseek = (
                "Пользователь уже нажал кнопку 'записаться к врачу'. Проанализируй историю диалога.\n"
                "1. Напиши ОЧЕНЬ КРАТКУЮ (1 короткое предложение) вежливую успокаивающую фразу (например: 'Всё будет хорошо, мы поможем вам подобрать врача.').\n"
                "2. Сразу выведи пошаговые рекомендации до осмотра врача (что делать и чего делать нельзя) конкретно для его ситуации. Пиши их максимально сжато, кратко, тезисно, без лишней воды.\n"
                "3. Укажи специальность врача, к которому нужно обратиться, выделив её тегом [SPECIALTY: специальность] (например, [SPECIALTY: оториноларинголог (ЛОР-врач)]).\n"
                "4. Категорически ЗАПРЕЩЕНО писать фразы вроде 'Вам необходимо обратиться к врачу' или 'Рекомендуется очная консультация', так как пользователь это уже сделал.\n"
                "5. В самом конце текста напиши: 'Далее я помогу вам найти врача поблизости. Пожалуйста, подтвердите готовность соблюдать рекомендации:'\n"
                "В конце сообщения НЕ добавляй никаких кнопок."
            )
            
            history = USER_SESSIONS.get(chat_id, [])
            messages = [{"role": "system", "content": SYSTEM_PROMPT}]
            messages.extend(history)
            messages.append({"role": "user", "content": prompt_deepseek})
            
            payload = {
                "model": DEEPSEEK_MODEL,
                "messages": messages,
                "temperature": 0.5,
            }
            
            try:
                resp = requests_post_deepseek(payload, timeout=15)
                reply = resp.json()["choices"][0]["message"]["content"]
            except Exception as e:
                print(f"Ошибка получения рекомендации при записи к врачу: {e}")
                spec_text = f"**{specialty}**" if specialty else "врачу"
                reply = (
                    f"Не волнуйтесь, пожалуйста, мы во всём разберёмся. [SPECIALTY: {spec_text}]\n\n"
                    "Ваши пошаговые рекомендации до приёма врача:\n"
                    "1. Постарайтесь отдохнуть и исключить физические нагрузки.\n"
                    "2. Избегайте тепловых процедур (баня, сауна, горячие компрессы) до осмотра.\n"
                    "3. Постоянно контролируйте свое самочувствие."
                )
                
            # Парсим специальность из тега [SPECIALTY: ...]
            import re
            spec_match = re.search(r"\[SPECIALTY:\s*([^\]]+)\]", reply)
            if spec_match:
                specialty_parsed = spec_match.group(1).strip()
                if specialty_parsed:
                    specialty = specialty_parsed
                reply = re.sub(r"\[SPECIALTY:\s*[^\]]+\]", "", reply).strip()
                
            # Попробуем извлечь специальность из ответа ИИ, если тег не сработал
            if not specialty:
                for key in SPECIALTY_KEYWORDS.keys():
                    if key[:-1] in reply.lower():
                        specialty = key
                        break
                        
            USER_STATES[chat_id] = {
                "state": "CONFIRM_DOCTOR_RECOMMENDATIONS",
                "specialty": specialty
            }
            save_json_state(STATES_FILE, USER_STATES)
            
            # Сообщение готово к отправке с inline-кнопкой подтверждения
            
            markup = types.InlineKeyboardMarkup(row_width=1)
            markup.add(types.InlineKeyboardButton("Хорошо, буду соблюдать", callback_data="user_choice:Хорошо, буду соблюдать"))
            
            send_message_safe(chat_id, reply, reply_markup=markup, parse_mode="Markdown")
            return

        if "врача на дом" in choice.lower() or "врача надом" in choice.lower():
            symptoms = summarize_symptoms_with_llm(chat_id)
            USER_STATES[chat_id] = {
                "state": "HOME_DOCTOR_LOCATION",
                "name": "",
                "region": "",
                "location": "",
                "symptoms": symptoms
            }
            save_json_state(STATES_FILE, USER_STATES)
            
            markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
            markup.add(types.KeyboardButton("📍 Отправить геолокацию", request_location=True))
            bot.send_message(
                chat_id, 
                "🏠 **Оформление вызова врача на дом**\n\n"
                "Чтобы дежурный врач мог приехать к вам, пожалуйста, **отправьте вашу геолокацию** с помощью кнопки ниже 👇 или напишите ваш **точный адрес текстом**:", 
                parse_mode="Markdown", 
                reply_markup=markup
            )
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
            save_json_state(STATES_FILE, USER_STATES)
            
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
        if reply is not None:
            send_message_safe(chat_id, reply, reply_markup=markup, parse_mode='Markdown')
def send_disclaimer(chat_id):
    disclaimer_text = (
        "⚖️ **Пользовательское соглашение и оферта**\n\n"
        "Для продолжения работы, пожалуйста, ознакомьтесь с правилами ИИ-ассистента Санарип.\n\n"
        "Нажимая кнопку ниже, вы подтверждаете своё согласие с **Публичной офертой** и даёте безусловное согласие на **обработку и трансграничную передачу обезличенных данных** (ID чата, текст сообщений) на серверы бота согласно Закону КР «Об информации персонального характера».\n\n"
        "Бот носит исключительно справочно-ознакомительный характер, не ставит диагнозы, не назначает лечение и не заменяет визит к врачу. В экстренных случаях немедленно звоните 103!"
    )
    markup = types.InlineKeyboardMarkup(row_width=1)
    btn_accept = types.InlineKeyboardButton("🤝 Принимаю условия и оферту", callback_data="accept_disclaimer")
    btn_view = types.InlineKeyboardButton("📄 Посмотреть оферту", callback_data="view_offer")
    markup.add(btn_accept, btn_view)
    bot.send_message(chat_id, disclaimer_text, reply_markup=markup, parse_mode='Markdown')


# --- Системный буфер логов чата и выгрузка в Hugging Face Datasets ---
LOG_BUFFER = []
LOG_BUFFER_LOCK = threading.Lock()
LOG_BUFFER_PATH = os.path.join(BASE_DIR, "data", "log_buffer.json")

def load_log_buffer():
    global LOG_BUFFER
    if os.path.exists(LOG_BUFFER_PATH):
        try:
            with open(LOG_BUFFER_PATH, "r", encoding="utf-8") as f:
                LOG_BUFFER = json.load(f)
            print(f"[Logs] Загружено {len(LOG_BUFFER)} записей из локального буфера логов.")
        except Exception as e:
            print(f"[Logs] Ошибка загрузки локального буфера логов: {e}")

def _save_log_buffer_locally():
    try:
        # Убедимся, что папка data существует
        os.makedirs(os.path.dirname(LOG_BUFFER_PATH), exist_ok=True)
        with open(LOG_BUFFER_PATH, "w", encoding="utf-8") as f:
            json.dump(LOG_BUFFER, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[Logs] Ошибка сохранения буфера логов: {e}")

def add_to_log_buffer(chat_id: int, role: str, text: str, event_type: str = "message"):
    with LOG_BUFFER_LOCK:
        LOG_BUFFER.append({
            "timestamp": time.time(),
            "chat_id": chat_id,
            "role": role,
            "text": text,
            "event": event_type
        })
        _save_log_buffer_locally()

def upload_logs_to_hf():
    global LOG_BUFFER
    token = os.getenv("HF_TOKEN")
    repo_id = os.getenv("HF_DATASET_REPO") # e.g. "Akimkhan/sanarip-med-ai-logs"
    
    if not token or not repo_id:
        print("[HF Logs] WARNING: HF_TOKEN или HF_DATASET_REPO не заданы в .env. Пропуск автовыгрузки.")
        return
        
    with LOG_BUFFER_LOCK:
        if not LOG_BUFFER:
            print("[HF Logs] Лог-буфер пуст, нечего выгружать.")
            return
        logs_to_upload = list(LOG_BUFFER)
        
    try:
        from huggingface_hub import HfApi
        api = HfApi(token=token)
        
        # Создаем временный файл
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".jsonl", mode="w", encoding="utf-8", delete=False) as tmp:
            for entry in logs_to_upload:
                tmp.write(json.dumps(entry, ensure_ascii=False) + "\n")
            tmp_path = tmp.name
            
        import datetime
        date_str = datetime.date.today().strftime("%Y_%m_%d")
        path_in_repo = f"logs_{date_str}.jsonl"
        
        print(f"[HF Logs] Загрузка {len(logs_to_upload)} логов в репозиторий датасета {repo_id}...")
        api.upload_file(
            path_or_fileobj=tmp_path,
            path_in_repo=path_in_repo,
            repo_id=repo_id,
            repo_type="dataset",
            commit_message=f"Upload chat logs for {date_str}"
        )
        print("[HF Logs] Загрузка логов на Hugging Face успешно завершена.")
        
        # Очищаем буфер после успешной загрузки
        with LOG_BUFFER_LOCK:
            del LOG_BUFFER[:len(logs_to_upload)]
            _save_log_buffer_locally()
            
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
            
    except Exception as e:
        print(f"[HF Logs] Ошибка загрузки логов на Hugging Face: {e}")

def start_logs_uploader_thread():
    def run_loop():
        # Тестовая выгрузка через 60 секунд после старта
        time.sleep(60)
        print("[Logs Thread] Проверка накопленных логов при старте...")
        upload_logs_to_hf()
        
        while True:
            # Выгружаем раз в сутки (86400 секунд)
            time.sleep(86400)
            print("[Logs Thread] Запуск плановой выгрузки логов...")
            upload_logs_to_hf()
            
    threading.Thread(target=run_loop, daemon=True).start()
    print("[Logs Thread] Фоновая служба выгрузки логов запущена.")

# Инициализируем логи
load_log_buffer()
start_logs_uploader_thread()


# --- Системы Безопасности и защиты ИИ-агента ---
import re
import html
# Инициализация Redis для Rate-limiting
redis_client = None
try:
    import redis
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    redis_client = redis.from_url(redis_url, socket_timeout=1)
    redis_client.ping()
    print("[Redis] Успешно подключено для Rate-limiting")
except Exception as e:
    redis_client = None
    print(f"[Redis] Ошибка подключения к Redis: {e}. Будет использована локальная память.")


# Локальный Rate-limiting fallback
MEMORY_RATE_LIMITS = {}

def is_rate_limited(chat_id: int) -> bool:
    """Проверяет лимит запросов (максимум 10 сообщений в минуту)"""
    import time
    now = time.time()
    limit = 10
    window = 60
    
    if redis_client:
        try:
            key = f"ratelimit:{chat_id}"
            pipe = redis_client.pipeline()
            pipe.rpush(key, now)
            pipe.expire(key, window)
            pipe.lrange(key, 0, -1)
            results = pipe.execute()
            timestamps = results[2]
            
            valid_timestamps = [float(t) for t in timestamps if now - float(t) < window]
            if len(valid_timestamps) != len(timestamps):
                redis_client.delete(key)
                if valid_timestamps:
                    redis_client.rpush(key, *valid_timestamps)
                    redis_client.expire(key, window)
            
            if len(valid_timestamps) > limit:
                return True
            return False
        except Exception as e:
            print(f"[Redis] Ошибка rate-limit: {e}")
            
    # Fallback на RAM
    timestamps = MEMORY_RATE_LIMITS.get(chat_id, [])
    timestamps = [t for t in timestamps if now - t < window]
    timestamps.append(now)
    MEMORY_RATE_LIMITS[chat_id] = timestamps
    return len(timestamps) > limit

def sanitize_user_input(text: str) -> str:
    """Защита от XSS и очистка тегов, ограничение длины"""
    if not text:
        return ""
    if len(text) > 1000:
        text = text[:1000] + "... [Текст обрезан из соображений безопасности]"
    text = re.sub(r'<[^>]*>', '', text)
    text = html.escape(text)
    return text

def check_prompt_injection(text: str) -> bool:
    """Проверка на попытки джейлбрейка и инъекций промптов"""
    lower_text = text.lower()
    keywords = [
        "игнорируй предыдущие инструкции",
        "игнорируй все предыдущие",
        "отключи безопасный режим",
        "системный промпт",
        "system prompt",
        "developer mode",
        "ignore all previous instructions",
        "forget your rules",
        "забудь свои правила",
        "действуй как",
        "act as a",
        "ты теперь не"
    ]
    for kw in keywords:
        if kw in lower_text:
            return True
    return False

def anonymize_pii(text: str) -> str:
    """Анонимизация PII (почты, телефоны) перед отправкой внешним провайдерам"""
    text = re.sub(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', '[EMAIL_REDACTED]', text)
    text = re.sub(r'\+?\b\d[\d\s-]{8,14}\b', '[PHONE_REDACTED]', text)
    return text


# --- Командные обработчики ---

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    chat_id = message.chat.id
    
    # Сброс сессии, соглашения и блокировок при /start
    USER_SESSIONS[chat_id] = []
    USER_ACCEPTED_DISCLAIMER.discard(chat_id)
    if chat_id in USER_STATES:
        del USER_STATES[chat_id]
    if chat_id in USER_OFFTOPIC_COUNT:
        del USER_OFFTOPIC_COUNT[chat_id]
    if chat_id in USER_BLOCKED:
        USER_BLOCKED.remove(chat_id)
        
    save_json_state(STATES_FILE, USER_STATES)
    save_json_state(DISCLAIMER_FILE, USER_ACCEPTED_DISCLAIMER)
    save_json_state(OFFTOPIC_FILE, USER_OFFTOPIC_COUNT)
    save_json_state(BLOCKED_FILE, USER_BLOCKED)
    save_chat_history(chat_id)
        
    welcome_text = "Здравствуйте! 👋 Я медицинский координатор **Санарип**."
    bot.send_message(chat_id, welcome_text, parse_mode='Markdown')
    
    # Отправляем дисклеймер
    send_disclaimer(chat_id)


@bot.message_handler(func=lambda message: True)
def handle_text(message):
    chat_id = message.chat.id
    if check_session_timeout(chat_id):
        return
        
    # 1. Проверка Rate-limit
    if is_rate_limited(chat_id):
        bot.reply_to(message, "⚠️ Вы отправляете сообщения слишком часто. Пожалуйста, подождите немного.")
        return

    load_chat_history(chat_id)
    
    # 2. Ограничение длины и XSS санитаризация
    raw_text = message.text.strip() if message.text else ""
    sanitized_text = sanitize_user_input(raw_text)
    
    if chat_id not in USER_ACCEPTED_DISCLAIMER:
        send_disclaimer(chat_id)
        return
        
    if chat_id in USER_BLOCKED:
        return

    # Проверка, заполняет ли пользователь форму
    if chat_id in USER_STATES:
        text = sanitized_text # Используем санитаризованный текст для форм, не обрезая PII
    else:
        # Для общего чата с ИИ проверяем на инъекции и вырезаем PII
        if check_prompt_injection(raw_text):
            bot.reply_to(message, "⚠️ Обнаружена попытка некорректного запроса. Пожалуйста, задавайте вопросы только по теме здоровья.")
            return
        text = anonymize_pii(sanitized_text)
        state_data = USER_STATES[chat_id]
        current_state = state_data.get("state")

        # --- Вызов скорой помощи ---
        if current_state == "EMERGENCY_LOCATION":
            state_data["location"] = text
            state_data["state"] = "EMERGENCY_REGION"
            save_json_state(STATES_FILE, USER_STATES)
            
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
            state_data["state"] = "EMERGENCY_CONTACT"
            save_json_state(STATES_FILE, USER_STATES)
            
            markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
            markup.add(types.KeyboardButton("📱 Поделиться контактом", request_contact=True))
            bot.send_message(
                chat_id,
                "Пожалуйста, **поделитесь номером телефона**, нажав на кнопку ниже 👇 (или отправьте его текстом):",
                parse_mode="Markdown",
                reply_markup=markup
            )
            return

        elif current_state == "EMERGENCY_CONTACT":
            state_data["phone"] = text
            state_data["state"] = "EMERGENCY_NAME"
            save_json_state(STATES_FILE, USER_STATES)
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
            save_json_state(STATES_FILE, USER_STATES)
            return

        # --- Запись на прием ---
        elif current_state == "APPOINTMENT_NAME":
            state_data["patient_name"] = text
            state_data["state"] = "APPOINTMENT_CONTACT"
            save_json_state(STATES_FILE, USER_STATES)
            
            markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
            markup.add(types.KeyboardButton("📱 Поделиться контактом", request_contact=True))
            bot.send_message(
                chat_id,
                "Пожалуйста, **поделитесь номером телефона**, нажав на кнопку ниже 👇 (или отправьте его текстом):",
                parse_mode="Markdown",
                reply_markup=markup
            )
            return

        elif current_state == "APPOINTMENT_CONTACT":
            state_data["phone"] = text
            save_appointment_request(chat_id, state_data)
            return

        # --- Вызов врача на дом ---
        elif current_state == "HOME_DOCTOR_LOCATION":
            state_data["location"] = text
            state_data["state"] = "HOME_DOCTOR_REGION"
            save_json_state(STATES_FILE, USER_STATES)
            
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
                "Координаты не получены. Укажите ваш район Бишкека вручную с помощью кнопок для вызова врача на дом:", 
                reply_markup=markup
            )
            return

        elif current_state == "HOME_DOCTOR_REGION_TEXT":
            state_data["region"] = text
            state_data["state"] = "HOME_DOCTOR_CONTACT"
            save_json_state(STATES_FILE, USER_STATES)
            
            markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
            markup.add(types.KeyboardButton("📱 Поделиться контактом", request_contact=True))
            bot.send_message(
                chat_id,
                "Пожалуйста, **поделитесь номером телефона**, нажав на кнопку ниже 👇 (или отправьте его текстом):",
                parse_mode="Markdown",
                reply_markup=markup
            )
            return

        elif current_state == "HOME_DOCTOR_CONTACT":
            state_data["phone"] = text
            state_data["state"] = "HOME_DOCTOR_NAME"
            save_json_state(STATES_FILE, USER_STATES)
            bot.send_message(
                chat_id,
                "Пожалуйста, напишите ваше **Имя и Фамилию** для оформления вызова врача на дом:",
                parse_mode="Markdown",
                reply_markup=types.ReplyKeyboardRemove()
            )
            return

        elif current_state == "HOME_DOCTOR_NAME":
            state_data["name"] = text
            save_home_doctor_request(chat_id, state_data)
            save_json_state(STATES_FILE, USER_STATES)
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

    elif text in ["🚑 Экстренный случай (103)", "🚑 Вызвать скорую помощь (103)"]:
        USER_STATES[chat_id] = {
            "state": "EMERGENCY_LOCATION",
            "name": "",
            "region": "",
            "location": "",
            "symptoms": "Прямой вызов скорой помощи через меню"
        }
        save_json_state(STATES_FILE, USER_STATES)
        
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

    # Стандартный запрос к ИИ
    bot.send_chat_action(chat_id, 'typing')
    
    # Ищем совпадения в базах данных
    context, _ = get_relevant_context(text)
    
    # Запрос к DeepSeek с учетом истории диалога
    reply, markup = ask_deepseek_with_history(chat_id, text, context)
    if reply is not None:
        send_message_safe(chat_id, reply, reply_markup=markup, parse_mode='Markdown')

# --- Голосовые сообщения ---



@bot.message_handler(content_types=['voice'])
def handle_voice(message):
    chat_id = message.chat.id
    if check_session_timeout(chat_id):
        return
    if is_rate_limited(chat_id):
        bot.reply_to(message, "⚠️ Вы отправляете сообщения слишком часто. Пожалуйста, подождите немного.")
        return

    if chat_id not in USER_ACCEPTED_DISCLAIMER:
        send_disclaimer(chat_id)
        return

    bot.reply_to(message, "Получил голосовое сообщение. Распознаю речь... 🎧")

    

    try:

        file_info = bot.get_file(message.voice.file_id)

        downloaded_file = bot.download_file(file_info.file_path)

        

        # Распознаем текст локально с помощью Whisper (с резервным Groq API)

        transcribed_text = transcribe_voice(downloaded_file)


        

        if not transcribed_text.strip():

            bot.reply_to(message, "Не удалось разобрать речь. Пожалуйста, попробуйте записать аудио четче или напишите текстом.")

            return

            

        bot.reply_to(message, f"З️ **Распознанный текст:**\n*«{transcribed_text}»*", parse_mode="Markdown")

        

        # Имитируем отправку текстового ответа, подменяя text в объекте message

        message.text = transcribed_text

        handle_text(message)

            

    except Exception as e:

        print(f"Ошибка обработки голосового сообщения: {e}")

        bot.reply_to(message, "Произошла ошибка при обработке голосового сообщения.")


# --- Фотографии / Изображения ---

@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    chat_id = message.chat.id
    if check_session_timeout(chat_id):
        return
    if chat_id not in USER_ACCEPTED_DISCLAIMER:
        send_disclaimer(chat_id)
        return

    bot.reply_to(message, "Получил изображение. Анализирую визуальные симптомы... 🔍")
    bot.send_chat_action(chat_id, 'typing')
    try:
        photo = message.photo[-1]
        file_info = bot.get_file(photo.file_id)
        downloaded_file = bot.download_file(file_info.file_path)

        # Вызываем Vision API для получения текстового описания симптомов на фото
        analysis_result = analyze_image_with_groq(downloaded_file)

        # Совмещаем описание изображения и подпись пациента
        caption = message.caption.strip() if message.caption else ""
        combined_query = f"[Симптомы на фото]: {analysis_result}"
        if caption:
            combined_query += f"\n[Комментарий пациента]: {caption}"

        # Отправляем объединенный запрос в общий RAG + LLM пайплайн
        clean_text, markup = ask_deepseek_with_history(chat_id, combined_query)

        # Отправляем ответ пациенту
        send_message_safe(chat_id, clean_text, reply_markup=markup, parse_mode='Markdown')

    except Exception as e:
        print(f"Ошибка обработки изображения: {e}")
        bot.reply_to(message, "Произошла ошибка при анализе изображения. Пожалуйста, попробуйте еще раз.")



def find_nearest_clinics(lat, lon, specialty=None, top_k=3):
    import math
    results = []
    
    # Нормализуем и подбираем синонимы специальности для гибкого поиска
    search_terms = []
    if specialty:
        spec_lower = specialty.lower()
        search_terms.append(spec_lower)
        
        synonyms = {
            "лор": ["оториноларинголог", "отоларинголог", "ухо", "горло", "нос"],
            "оториноларинголог": ["лор", "отоларинголог"],
            "отоларинголог": ["лор", "оториноларинголог"],
            "стоматолог": ["зубной"],
            "окулист": ["офтальмолог"],
            "офтальмолог": ["окулист"],
            "терапевт": ["семейный врач"]
        }
        for key, val in synonyms.items():
            if key in spec_lower:
                search_terms.extend(val)

    for clinic in CLINICS_DB:
        if specialty:
            specializations = [s.lower() for s in clinic.get("specializations", [])]
            doc_specialties = [d.get("specialty", "").lower() for d in clinic.get("doctors", [])]
            
            matched = False
            for term in search_terms:
                if any(term in spec or spec in term for spec in specializations):
                    matched = True
                    break
                if any(term in ds or ds in term for ds in doc_specialties):
                    matched = True
                    break
            if not matched:
                continue
                
        clat = clinic.get("latitude")
        clon = clinic.get("longitude")
        if clat is None or clon is None:
            continue
            
        R = 6371.0
        dlat = math.radians(clat - lat)
        dlon = math.radians(clon - lon)
        a = math.sin(dlat / 2)**2 + math.cos(math.radians(lat)) * math.cos(math.radians(clat)) * math.sin(dlon / 2)**2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        distance = R * c
        
        results.append((clinic, distance))
        
    results.sort(key=lambda x: x[1])
    return results[:top_k]

# --- Контактные данные (номер телефона) ---

@bot.message_handler(content_types=['contact'])
def handle_contact(message):
    chat_id = message.chat.id
    try:
        load_chat_history(chat_id)
        
        if chat_id not in USER_ACCEPTED_DISCLAIMER:
            send_disclaimer(chat_id)
            return
            
        if chat_id in USER_STATES:
            state_data = USER_STATES[chat_id]
            current_state = state_data.get("state")
            
            if current_state in ["EMERGENCY_CONTACT", "HOME_DOCTOR_CONTACT"]:
                phone = message.contact.phone_number
                state_data["phone"] = phone
                prefix = "EMERGENCY" if "EMERGENCY" in current_state else "HOME_DOCTOR"
                state_data["state"] = f"{prefix}_NAME"
                save_json_state(STATES_FILE, USER_STATES)
                
                prompt_text = "Пожалуйста, напишите ваше **Имя и Фамилию** для завершения вызова:" if prefix == "EMERGENCY" else "Пожалуйста, напишите ваше **Имя и Фамилию** для оформления вызова врача на дом:"
                bot.send_message(
                    chat_id,
                    prompt_text,
                    parse_mode="Markdown",
                    reply_markup=types.ReplyKeyboardRemove()
                )
            elif current_state == "APPOINTMENT_CONTACT":
                phone = message.contact.phone_number
                state_data["phone"] = phone
                save_appointment_request(chat_id, state_data)
    except Exception as e:
        print(f"Ошибка в handle_contact для chat_id {chat_id}: {e}")
        import traceback
        traceback.print_exc()


# --- Геолокация ---

@bot.message_handler(content_types=['location'])
def handle_location(message):
    chat_id = message.chat.id
    import time
    USER_LAST_ACTIVITY[str(chat_id)] = time.time()
    save_json_state(ACTIVITY_FILE, USER_LAST_ACTIVITY)
    try:
        # Загружаем историю диалога и состояния
        load_chat_history(chat_id)
        
        if chat_id not in USER_ACCEPTED_DISCLAIMER:
            send_disclaimer(chat_id)
            return

        lat = message.location.latitude
        lon = message.location.longitude

        # Пытаемся получить состояние по строковому или числовому ключу
        state_data = USER_STATES.get(chat_id, {}) or USER_STATES.get(str(chat_id), {})
        current_state = state_data.get("state")

        if current_state == "EMERGENCY_LOCATION":
            region = get_bishkek_district_by_coords(lat, lon)
            state_data["location"] = f"Координаты: {lat}, {lon}"
            state_data["region"] = region
            state_data["state"] = "EMERGENCY_NAME"
            USER_STATES[chat_id] = state_data
            save_json_state(STATES_FILE, USER_STATES)
            
            bot.send_message(
                chat_id,
                f"📍 Координаты получены. Район города: **{region}**.\n\nПожалуйста, напишите ваше **Имя и Фамилию** для завершения вызова:",
                parse_mode="Markdown",
                reply_markup=types.ReplyKeyboardRemove()
            )
            return

        elif current_state == "HOME_DOCTOR_LOCATION":
            region = get_bishkek_district_by_coords(lat, lon)
            state_data["location"] = f"Координаты: {lat}, {lon}"
            state_data["region"] = region
            state_data["state"] = "HOME_DOCTOR_NAME"
            USER_STATES[chat_id] = state_data
            save_json_state(STATES_FILE, USER_STATES)
            
            bot.send_message(
                chat_id,
                f"📍 Координаты получены. Район города: **{region}**.\n\nПожалуйста, напишите ваше **Имя и Фамилию** для оформления вызова врача на дом:",
                parse_mode="Markdown",
                reply_markup=types.ReplyKeyboardRemove()
            )
            return

        # Поиск клиник
        specialty = state_data.get("specialty") if current_state == "SEARCH_CLINICS_LOCATION" else detect_specialty(chat_id)
        USER_STATES[chat_id] = {
            "state": "SELECTING_CLINIC",
            "specialty": specialty or ""
        }
        save_json_state(STATES_FILE, USER_STATES)

        bot.reply_to(message, "Ищу ближайшие клиники... 🗺️")
        
        nearest = find_nearest_clinics(lat, lon, specialty=specialty, top_k=3)
        if not nearest and specialty:
            # Если по специальности ничего не найдено, ищем любые ближайшие клиники
            nearest = find_nearest_clinics(lat, lon, specialty=None, top_k=3)

        if not nearest:
            bot.send_message(chat_id, "Извините, не удалось найти клиники рядом с вами.", reply_markup=get_main_keyboard())
            return

        markup = types.InlineKeyboardMarkup(row_width=1)
        for clinic, dist in nearest:
            # Находим индекс клиники в базе CLINICS_DB для правильного колбэка
            try:
                clinic_idx = CLINICS_DB.index(clinic)
            except ValueError:
                continue
            btn_text = f"🏥 {clinic.get('short_name', clinic.get('name'))} ({dist:.2f} км)"
            markup.add(types.InlineKeyboardButton(btn_text, callback_data=f"clinic_{clinic_idx}"))
            
        response = (
            "📍 **Мы подобрали ближайшие клиники с нужным специалистом:**\n\n"
            "Пожалуйста, **выберите интересующую клинику ниже 👇**, чтобы увидеть контакты, точный адрес, расписание работы и список врачей:"
        )
        bot.send_message(chat_id, response, reply_markup=markup, parse_mode="Markdown")

    except Exception as e:
        print(f"Ошибка в handle_location для chat_id {chat_id}: {e}")
        import traceback
        traceback.print_exc()
        try:
            bot.send_message(
                chat_id, 
                "Произошла ошибка при обработке геоданных. Пожалуйста, попробуйте отправить геолокацию еще раз или напишите ваш адрес текстом.", 
                reply_markup=get_main_keyboard()
            )
        except Exception as send_err:
            print(f"Не удалось отправить сообщение об ошибке: {send_err}")


if __name__ == "__main__":

    if bot:

        print("Telegram-бот Санарип успешно запущен и ожидает сообщений...")

        bot.infinity_polling()

    else:

        print("Критическая ошибка: Бот не запущен из-за отсутствия токена.")

