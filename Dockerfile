FROM python:3.10-slim

# Install required system packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    redis-server \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements and install Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the project
COPY . .

# Make sure entrypoint is executable (but we might not use it)
RUN chmod +x entrypoint.sh

EXPOSE 7860

# Use server.py with CMD — clean and simple
CMD ["python", "-u", "server.py"]
