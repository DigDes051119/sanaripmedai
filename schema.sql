-- SQL-скрипт миграции для создания необходимых таблиц в Supabase (PostgreSQL)

-- 1. Таблица пользователей (анонимизированные настройки, лимиты оффтопика и блокировки)
CREATE TABLE IF NOT EXISTS users (
    chat_id BIGINT PRIMARY KEY,
    accepted_disclaimer BOOLEAN DEFAULT FALSE,
    offtopic_count INT DEFAULT 0,
    blocked BOOLEAN DEFAULT FALSE,
    last_activity DOUBLE PRECISION DEFAULT 0.0,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 2. Таблица состояний диалогов (хранение текущего шага в диалоге бота)
CREATE TABLE IF NOT EXISTS user_states (
    chat_id BIGINT PRIMARY KEY,
    state_data JSONB,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 3. Таблица записей к врачам и в лаборатории
CREATE TABLE IF NOT EXISTS appointments (
    id SERIAL PRIMARY KEY,
    chat_id BIGINT,
    data JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 4. Таблица экстренных обращений (для скорой помощи)
CREATE TABLE IF NOT EXISTS emergency_requests (
    id SERIAL PRIMARY KEY,
    chat_id BIGINT,
    data JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 5. Таблица истории переписок (для контекста общения с ИИ)
CREATE TABLE IF NOT EXISTS chat_histories (
    chat_id BIGINT PRIMARY KEY,
    history JSONB,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
