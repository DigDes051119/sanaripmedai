from http.server import HTTPServer, BaseHTTPRequestHandler
import os

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write(b'OK, Sanarip Med AI is running!\n')
    def log_message(self, format, *args):
        print(f'{self.client_address[0]} - {format % args}')

port = int(os.environ.get('PORT', 7860))
print(f'Starting server on port {port}...')
server = HTTPServer(('0.0.0.0', port), HealthHandler)
server.serve_forever()
