FROM python:3.10-slim

# Установка необходимых системных пакетов, включая Redis
RUN apt-get update && apt-get install -y --no-install-recommends \
    redis-server \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Копируем requirements.txt и устанавливаем зависимости
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем весь проект в контейнер
COPY . .

# Скрипт entrypoint.sh для запуска Redis и Flask приложения
RUN chmod +x entrypoint.sh

EXPOSE 7860

ENTRYPOINT ["./entrypoint.sh"]
