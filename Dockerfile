FROM python:3.10-slim

WORKDIR /app

# Install system dependencies (ffmpeg for whisper)
RUN apt-get update && apt-get install -y \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Install PyTorch CPU-only first to keep image lightweight and prevent CUDA download
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

# Copy only requirements to cache dependencies install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code
COPY . .

EXPOSE 7860

# Используем entrypoint.sh для запуска Flask-сервера и фоновых задач
RUN chmod +x entrypoint.sh
CMD ["bash", "entrypoint.sh"]

