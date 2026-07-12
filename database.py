import os
import json
import time
from dotenv import load_dotenv

# ─── Шифрование ПДн (Fernet / AES-128) ─────────────────────────────────────────────
try:
    from cryptography.fernet import Fernet
    _pii_key_raw = os.getenv("PII_ENCRYPTION_KEY", "")
    if _pii_key_raw:
        _fernet = Fernet(_pii_key_raw.encode())
        print("[DB/Crypto] Шифрование ПДн (Fernet) активировано.")
    else:
        _fernet = None
        print("[DB/Crypto] PII_ENCRYPTION_KEY не задан — персональные данные хранятся без шифрования.")
except ImportError:
    _fernet = None
    print("[DB/Crypto] cryptography не установлен — шифрование работает в режиме passthrough.")

_PII_FIELDS = {"name", "phone", "phone_number", "location", "address", "full_name", "имя", "телефон"}

def encrypt_pii(value: str) -> str:
    """Шифрует строку Fernet (если ключ задан)."""
    if _fernet and isinstance(value, str):
        return _fernet.encrypt(value.encode()).decode()
    return value

def decrypt_pii(value: str) -> str:
    """Дешифрует строку Fernet (если ключ задан)."""
    if _fernet and isinstance(value, str):
        try:
            return _fernet.decrypt(value.encode()).decode()
        except Exception:
            return value  # уже было открыто или не зашифровано
    return value

def _encrypt_dict_pii(data: dict) -> dict:
    """Шифрует все ПДн-поля в словаре перед записью."""
    result = {}
    for k, v in data.items():
        if k.lower() in _PII_FIELDS and isinstance(v, str):
            result[k] = encrypt_pii(v)
        else:
            result[k] = v
    return result

def _decrypt_dict_pii(data: dict) -> dict:
    """Дешифрует все ПДн-поля после чтения."""
    result = {}
    for k, v in data.items():
        if k.lower() in _PII_FIELDS and isinstance(v, str):
            result[k] = decrypt_pii(v)
        else:
            result[k] = v
    return result

# Загружаем переменные окружения из .env
load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)

# Локальные пути
STATES_FILE = os.path.join(DATA_DIR, "user_states.json")
DISCLAIMER_FILE = os.path.join(DATA_DIR, "user_accepted_disclaimer.json")
OFFTOPIC_FILE = os.path.join(DATA_DIR, "user_offtopic_count.json")
BLOCKED_FILE = os.path.join(DATA_DIR, "user_blocked.json")
ACTIVITY_FILE = os.path.join(DATA_DIR, "user_last_activity.json")
APPOINTMENTS_FILE = os.path.join(DATA_DIR, "appointments.json")
EMERGENCY_FILE = os.path.join(DATA_DIR, "emergency_requests.json")

def init_db():
    print("[DB] Режим работы: локальные JSON-файлы (база данных Supabase отключена).")
    # Создаем папку chat_histories
    os.makedirs(os.path.join(DATA_DIR, "chat_histories"), exist_ok=True)

# Вызываем при импорте
init_db()

# --- ФУНКЦИИ РАБОТЫ С JSON ---
def load_json_state(file_path, default):
    if os.path.exists(file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"Ошибка загрузки из {file_path}: {e}")
    return default

def save_json_state(file_path, data):
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Ошибка сохранения в {file_path}: {e}")

# --- ИНТЕРФЕЙС РАБОТЫ С ДАННЫМИ ---

# 1. User Settings (Disclaimer, Offtopic, Blocked, Last Activity)
def get_user_data(chat_id):
    disclaimers = load_json_state(DISCLAIMER_FILE, [])
    offtopics = load_json_state(OFFTOPIC_FILE, {})
    blocked = load_json_state(BLOCKED_FILE, [])
    activities = load_json_state(ACTIVITY_FILE, {})
    
    return {
        "chat_id": chat_id,
        "accepted_disclaimer": chat_id in disclaimers or str(chat_id) in disclaimers,
        "offtopic_count": offtopics.get(str(chat_id)) or offtopics.get(chat_id) or 0,
        "blocked": chat_id in blocked or str(chat_id) in blocked,
        "last_activity": activities.get(str(chat_id)) or activities.get(chat_id) or 0.0
    }

def update_user_field(chat_id, field, value):
    if field == "accepted_disclaimer":
        disclaimers = set(load_json_state(DISCLAIMER_FILE, []))
        if value:
            disclaimers.add(chat_id)
        else:
            disclaimers.discard(chat_id)
        save_json_state(DISCLAIMER_FILE, list(disclaimers))
    elif field == "offtopic_count":
        offtopics = load_json_state(OFFTOPIC_FILE, {})
        offtopics[str(chat_id)] = value
        save_json_state(OFFTOPIC_FILE, offtopics)
    elif field == "blocked":
        blocked = set(load_json_state(BLOCKED_FILE, []))
        if value:
            blocked.add(chat_id)
        else:
            blocked.discard(chat_id)
        save_json_state(BLOCKED_FILE, list(blocked))
    elif field == "last_activity":
        activities = load_json_state(ACTIVITY_FILE, {})
        activities[str(chat_id)] = value
        save_json_state(ACTIVITY_FILE, activities)

# 2. User State
def get_user_state(chat_id):
    states = load_json_state(STATES_FILE, {})
    return states.get(str(chat_id)) or states.get(chat_id)

def set_user_state(chat_id, state_data):
    states = load_json_state(STATES_FILE, {})
    if state_data is None:
        states.pop(str(chat_id), None)
        states.pop(chat_id, None)
    else:
        states[str(chat_id)] = state_data
    save_json_state(STATES_FILE, states)

# 3. Appointments
def save_appointment(chat_id, appointment_data):
    encrypted_data = _encrypt_dict_pii(appointment_data)
    appointments = load_json_state(APPOINTMENTS_FILE, [])
    appointments.append(encrypted_data)
    save_json_state(APPOINTMENTS_FILE, appointments)

def get_all_appointments():
    apps = load_json_state(APPOINTMENTS_FILE, [])
    return [_decrypt_dict_pii(a) for a in apps]

# 4. Emergency Requests
def save_emergency_request(chat_id, request_data):
    encrypted_data = _encrypt_dict_pii(request_data)
    requests_list = load_json_state(EMERGENCY_FILE, [])
    requests_list.append(encrypted_data)
    save_json_state(EMERGENCY_FILE, requests_list)

def get_all_emergency_requests():
    reqs = load_json_state(EMERGENCY_FILE, [])
    return [_decrypt_dict_pii(r) for r in reqs]

# 5. Chat History
def get_chat_history(chat_id):
    file_path = os.path.join(DATA_DIR, "chat_histories", f"{chat_id}.json")
    if os.path.exists(file_path):
        return load_json_state(file_path, {"history": []})
    return {"history": []}

def set_chat_history(chat_id, history_data):
    history_dir = os.path.join(DATA_DIR, "chat_histories")
    os.makedirs(history_dir, exist_ok=True)
    file_path = os.path.join(history_dir, f"{chat_id}.json")
    save_json_state(file_path, history_data)

def update_appointment_status(appointment_id, status, doctor_fio, appointment_time):
    appointments = load_json_state(APPOINTMENTS_FILE, [])
    for appt in appointments:
        if appt.get("id") == appointment_id:
            appt["status"] = status
            appt["doctor_fio"] = doctor_fio
            appt["appointment_time"] = appointment_time
            break
    save_json_state(APPOINTMENTS_FILE, appointments)
