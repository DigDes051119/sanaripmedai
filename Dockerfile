FROM python:3.10-slim

WORKDIR /app

# Copy app files
COPY . .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

EXPOSE 7860

# Используем entrypoint.sh для запуска health-check сервера и Telegram бота
RUN chmod +x entrypoint.sh
CMD ["bash", "entrypoint.sh"]
