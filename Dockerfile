FROM python:3.10-slim

WORKDIR /app

# Copy app files
COPY . .

EXPOSE 7860

# Используем entrypoint.sh для запуска health-check сервера и Telegram бота
RUN chmod +x entrypoint.sh
CMD ["bash", "entrypoint.sh"]
