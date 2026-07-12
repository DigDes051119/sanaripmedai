import os
from flask import Flask

app = Flask(__name__)

@app.route("/")
def index():
    return "<h1>Sanarip Med AI</h1><p>Status: OK</p>", 200

@app.route("/health")
def health():
    return "OK", 200

print("[STARTUP] Minimal Flask app loaded, starting server...")
port = int(os.environ.get("PORT", 7860))
print(f"[STARTUP] Binding to 0.0.0.0:{port}")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=port, debug=False)
