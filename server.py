#!/usr/bin/env python3
"""Minimal HTTP server using only stdlib — no Flask, no dependencies."""
import http.server, os, sys

class Handler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"<h1>Sanarip Med AI</h1><p>Works!</p>")
    def log_message(self, fmt, *args):
        sys.stderr.write("[HTTP] %s - %s\n" % (self.address_string(), fmt % args))
        sys.stderr.flush()

port = int(os.environ.get("PORT", 7860))
sys.stderr.write("[STARTUP] Minimal server on 0.0.0.0:%d\n" % port)
sys.stderr.flush()
http.server.HTTPServer(("0.0.0.0", port), Handler).serve_forever()
