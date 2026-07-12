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

# Use CMD instead of ENTRYPOINT — run a pure-Python HTTP server from stdlib
# This completely eliminates any shell script issues
CMD python -u -c "
import http.server, os, sys, threading, time

class H(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/health':
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'OK')
        else:
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(b'<h1>Sanarip Med AI</h1><p>Pure stdlib HTTP server works!</p>')
    
    def log_message(self, format, *args):
        sys.stderr.write('[HTTP] %s - %s\n' % (self.address_string(), format % args))
        sys.stderr.flush()

port = int(os.environ.get('PORT', 7860))
sys.stderr.write('[STARTUP] Pure stdlib HTTP server starting on 0.0.0.0:%d\n' % port)
sys.stderr.flush()

server = http.server.HTTPServer(('0.0.0.0', port), H)
sys.stderr.write('[STARTUP] Server started successfully!\n')
sys.stderr.flush()
server.serve_forever()
" 2>&1
