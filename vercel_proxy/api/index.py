from flask import Flask, request, Response
import requests

app = Flask(__name__)

@app.route("/", defaults={"path": ""}, methods=["GET", "POST", "PUT", "DELETE"])
@app.route("/<path:path>", methods=["GET", "POST", "PUT", "DELETE"])
def proxy(path):
    # Перенаправляем запрос на официальный API Telegram
    target_url = f"https://api.telegram.org/{path}"
    
    # Копируем заголовки запроса, исключая Host
    headers = {k: v for k, v in request.headers if k.lower() != 'host'}
    
    try:
        # Выполняем прокси-запрос
        resp = requests.request(
            method=request.method,
            url=target_url,
            headers=headers,
            data=request.get_data(),
            params=request.args,
            cookies=request.cookies,
            allow_redirects=False,
            timeout=30
        )
        
        # Передаем ответ обратно клиенту
        response = Response(resp.content, resp.status_code)
        for k, v in resp.headers.items():
            # Исключаем заголовки передачи контента, которые пересчитываются Flask автоматически
            if k.lower() not in ['content-encoding', 'content-length', 'transfer-encoding', 'connection']:
                response.headers[k] = v
        return response
    except Exception as e:
        return f"Proxy Error: {e}", 500
