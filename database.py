import os
import json
import time
import psycopg2
from psycopg2.extras import RealDictCursor
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
    """Дешифрует все ПДн-поля после чтения из БД."""
    result = {}
    for k, v in data.items():
        if k.lower() in _PII_FIELDS and isinstance(v, str):
            result[k] = decrypt_pii(v)
        else:
            result[k] = v
    return result

# Загружаем переменные окружения из .env
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

# Папка для локального хранения
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)

# Локальные пути (для fallback)
STATES_FILE = os.path.join(DATA_DIR, "user_states.json")
DISCLAIMER_FILE = os.path.join(DATA_DIR, "user_accepted_disclaimer.json")
OFFTOPIC_FILE = os.path.join(DATA_DIR, "user_offtopic_count.json")
BLOCKED_FILE = os.path.join(DATA_DIR, "user_blocked.json")
ACTIVITY_FILE = os.path.join(DATA_DIR, "user_last_activity.json")
APPOINTMENTS_FILE = os.path.join(DATA_DIR, "appointments.json")
EMERGENCY_FILE = os.path.join(DATA_DIR, "emergency_requests.json")

def get_connection():
    if not DATABASE_URL:
        return None
    retry_delay = 5
    max_retries = 10
    for attempt in range(1, max_retries + 1):
        try:
            conn = psycopg2.connect(DATABASE_URL)
            print(f"[DB] Connected to PostgreSQL (attempt {attempt}).")
            return conn
        except Exception as e:
            print(f"[DB] Connection error (attempt {attempt}/{max_retries}): {e}")
            if attempt < max_retries:
                print(f"[DB] Retrying in {retry_delay} sec...")
                time.sleep(retry_delay)
    print("[DB] All connection attempts exhausted. Falling back to JSON mode.")
    return None


def init_db():
    if not DATABASE_URL:
        print("[DB] Режим работы: локальные JSON-файлы (DATABASE_URL не настроен).")
        return
    
    conn = get_connection()
    if not conn:
        return

    
    try:
        with conn.cursor() as cur:
            # Таблица пользователей
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    chat_id BIGINT PRIMARY KEY,
                    accepted_disclaimer BOOLEAN DEFAULT FALSE,
                    offtopic_count INT DEFAULT 0,
                    blocked BOOLEAN DEFAULT FALSE,
                    last_activity DOUBLE PRECISION DEFAULT 0.0,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            # Таблица состояний диалогов
            cur.execute("""
                CREATE TABLE IF NOT EXISTS user_states (
                    chat_id BIGINT PRIMARY KEY,
                    state_data JSONB,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            # Таблица записей к врачу
            cur.execute("""
                CREATE TABLE IF NOT EXISTS appointments (
                    id SERIAL PRIMARY KEY,
                    chat_id BIGINT,
                    data JSONB,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            # Таблица экстренных вызовов
            cur.execute("""
                CREATE TABLE IF NOT EXISTS emergency_requests (
                    id SERIAL PRIMARY KEY,
                    chat_id BIGINT,
                    data JSONB,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            # Таблица историй переписок
            cur.execute("""
                CREATE TABLE IF NOT EXISTS chat_histories (
                    chat_id BIGINT PRIMARY KEY,
                    history JSONB,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            conn.commit()
            print("[DB] Таблицы базы данных успешно проверены/созданы.")
    except Exception as e:
        print(f"[DB] Ошибка инициализации таблиц: {e}")
        conn.rollback()
    finally:
        conn.close()

# Вызываем инициализацию при импорте
init_db()

# --- ФУНКЦИИ FALLBACK (JSON) ---
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
    conn = get_connection()
    if conn:
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT * FROM users WHERE chat_id = %s", (chat_id,))
                res = cur.fetchone()
                if res:
                    return res
                else:
                    # Инициализируем пустую запись
                    cur.execute(
                        "INSERT INTO users (chat_id) VALUES (%s) RETURNING *", 
                        (chat_id,)
                    )
                    conn.commit()
                    return cur.fetchone()
        except Exception as e:
            print(f"[DB] Ошибка get_user_data: {e}")
            conn.rollback()
        finally:
            conn.close()
            
    # Fallback
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
    conn = get_connection()
    if conn:
        try:
            with conn.cursor() as cur:
                cur.execute(f"""
                    INSERT INTO users (chat_id, {field}, updated_at)
                    VALUES (%s, %s, CURRENT_TIMESTAMP)
                    ON CONFLICT (chat_id) DO UPDATE
                    SET {field} = EXCLUDED.{field}, updated_at = CURRENT_TIMESTAMP
                """, (chat_id, value))
                conn.commit()
                return
        except Exception as e:
            print(f"[DB] Ошибка update_user_field {field}: {e}")
            conn.rollback()
        finally:
            conn.close()
            
    # Fallback
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
    conn = get_connection()
    if conn:
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT state_data FROM user_states WHERE chat_id = %s", (chat_id,))
                res = cur.fetchone()
                return res[0] if res else None
        except Exception as e:
            print(f"[DB] Ошибка get_user_state: {e}")
        finally:
            conn.close()
            
    # Fallback
    states = load_json_state(STATES_FILE, {})
    return states.get(str(chat_id)) or states.get(chat_id)

def set_user_state(chat_id, state_data):
    conn = get_connection()
    if conn:
        try:
            with conn.cursor() as cur:
                if state_data is None:
                    cur.execute("DELETE FROM user_states WHERE chat_id = %s", (chat_id,))
                else:
                    cur.execute("""
                        INSERT INTO user_states (chat_id, state_data, updated_at)
                        VALUES (%s, %s, CURRENT_TIMESTAMP)
                        ON CONFLICT (chat_id) DO UPDATE
                        SET state_data = EXCLUDED.state_data, updated_at = CURRENT_TIMESTAMP
                    """, (chat_id, json.dumps(state_data)))
                conn.commit()
                return
        except Exception as e:
            print(f"[DB] Ошибка set_user_state: {e}")
            conn.rollback()
        finally:
            conn.close()
            
    # Fallback
    states = load_json_state(STATES_FILE, {})
    if state_data is None:
        states.pop(str(chat_id), None)
        states.pop(chat_id, None)
    else:
        states[str(chat_id)] = state_data
    save_json_state(STATES_FILE, states)

# 3. Appointments
def save_appointment(chat_id, appointment_data):
    # Шифруем ПДн-поля перед записью в БД
    encrypted_data = _encrypt_dict_pii(appointment_data)
    conn = get_connection()
    if conn:
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO appointments (chat_id, data) VALUES (%s, %s)",
                    (chat_id, json.dumps(encrypted_data))
                )
                conn.commit()
                return
        except Exception as e:
            print(f"[DB] Ошибка save_appointment: {e}")
            conn.rollback()
        finally:
            conn.close()

    # Fallback
    appointments = load_json_state(APPOINTMENTS_FILE, [])
    appointments.append(encrypted_data)
    save_json_state(APPOINTMENTS_FILE, appointments)

def get_all_appointments():
    conn = get_connection()
    if conn:
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT id, chat_id, data FROM appointments ORDER BY created_at DESC")
                rows = cur.fetchall()
                # Возвращаем список данных
                appointments = []
                for row in rows:
                    item = row["data"]
                    if isinstance(item, str):
                        item = json.loads(item)
                    item = _decrypt_dict_pii(item)
                    item["id"] = row["id"]
                    item["chat_id"] = row["chat_id"]
                    appointments.append(item)
                return appointments
        except Exception as e:
            print(f"[DB] Ошибка get_all_appointments: {e}")
        finally:
            conn.close()
            
    # Fallback
    return load_json_state(APPOINTMENTS_FILE, [])

# 4. Emergency Requests
def save_emergency_request(chat_id, request_data):
    # Шифруем ПДн-поля перед записью
    encrypted_data = _encrypt_dict_pii(request_data)
    conn = get_connection()
    if conn:
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO emergency_requests (chat_id, data) VALUES (%s, %s)",
                    (chat_id, json.dumps(encrypted_data))
                )
                conn.commit()
                return
        except Exception as e:
            print(f"[DB] Ошибка save_emergency_request: {e}")
            conn.rollback()
        finally:
            conn.close()

    # Fallback
    requests_list = load_json_state(EMERGENCY_FILE, [])
    requests_list.append(encrypted_data)
    save_json_state(EMERGENCY_FILE, requests_list)

def get_all_emergency_requests():
    conn = get_connection()
    if conn:
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT id, chat_id, data FROM emergency_requests ORDER BY created_at DESC")
                rows = cur.fetchall()
                requests_list = []
                for row in rows:
                    item = row["data"]
                    if isinstance(item, str):
                        item = json.loads(item)
                    item = _decrypt_dict_pii(item)
                    item["id"] = row["id"]
                    item["chat_id"] = row["chat_id"]
                    requests_list.append(item)
                return requests_list
        except Exception as e:
            print(f"[DB] Ошибка get_all_emergency_requests: {e}")
        finally:
            conn.close()
            
    # Fallback
    return load_json_state(EMERGENCY_FILE, [])

# 5. Chat History
def get_chat_history(chat_id):
    conn = get_connection()
    if conn:
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT history FROM chat_histories WHERE chat_id = %s", (chat_id,))
                res = cur.fetchone()
                if res:
                    val = res[0]
                    return val if isinstance(val, dict) else json.loads(val)
                return {"history": []}
        except Exception as e:
            print(f"[DB] Ошибка get_chat_history: {e}")
        finally:
            conn.close()
            
    # Fallback
    file_path = os.path.join(DATA_DIR, "chat_histories", f"{chat_id}.json")
    if os.path.exists(file_path):
        return load_json_state(file_path, {"history": []})
    return {"history": []}

def set_chat_history(chat_id, history_data):
    conn = get_connection()
    if conn:
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO chat_histories (chat_id, history, updated_at)
                    VALUES (%s, %s, CURRENT_TIMESTAMP)
                    ON CONFLICT (chat_id) DO UPDATE
                    SET history = EXCLUDED.history, updated_at = CURRENT_TIMESTAMP
                """, (chat_id, json.dumps(history_data)))
                conn.commit()
                return
        except Exception as e:
            print(f"[DB] Ошибка set_chat_history: {e}")
            conn.rollback()
        finally:
            conn.close()
            
    # Fallback
    history_dir = os.path.join(DATA_DIR, "chat_histories")
    os.makedirs(history_dir, exist_ok=True)
    file_path = os.path.join(history_dir, f"{chat_id}.json")
    save_json_state(file_path, history_data)


def update_appointment_status(appointment_id, status, doctor_fio, appointment_time):
    conn = get_connection()
    if conn:
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE appointments
                    SET data = jsonb_set(
                        jsonb_set(
                            jsonb_set(data, '{status}', %s::jsonb),
                            '{doctor_fio}', %s::jsonb
                        ),
                        '{appointment_time}', %s::jsonb
                    )
                    WHERE data->>'id' = %s
                """, (json.dumps(status), json.dumps(doctor_fio), json.dumps(appointment_time), appointment_id))
                conn.commit()
                return
        except Exception as e:
            print(f"[DB] Ошибка update_appointment_status: {e}")
            conn.rollback()
        finally:
            conn.close()
            
    # Fallback
    appointments = load_json_state(APPOINTMENTS_FILE, [])
    for appt in appointments:
        if appt.get("id") == appointment_id:
            appt["status"] = status
            appt["doctor_fio"] = doctor_fio
            appt["appointment_time"] = appointment_time
            break
    save_json_state(APPOINTMENTS_FILE, appointments)
