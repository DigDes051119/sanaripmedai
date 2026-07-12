FROM python:3.10-slim

WORKDIR /app

# Copy app files
COPY . .

EXPOSE 7860

# Use Python's built-in HTTP server — no deps needed
CMD ["python", "-u", "server.py"]
