import os
import sys
import json
import time
import requests
import threading
from dotenv import load_dotenv
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct
from concurrent.futures import ThreadPoolExecutor, as_completed

load_dotenv()

# Загружаем ключи Gemini
GEMINI_KEYS = os.getenv("GEMINI_API_KEYS", "").split(",")
GEMINI_KEYS = [k.strip() for k in GEMINI_KEYS if k.strip()]
if not GEMINI_KEYS:
    single_key = os.getenv("GEMINI_API_KEY")
    if single_key:
        GEMINI_KEYS = [single_key]

if not GEMINI_KEYS:
    print("[Error] Нет ключей GEMINI_API_KEYS в .env!")
    sys.exit(1)

print(f"Загружено ключей Gemini для генерации эмбеддингов: {len(GEMINI_KEYS)}")

key_idx = 0
key_lock = threading.Lock()

def get_next_key():
    global key_idx
    with key_lock:
        key_idx = (key_idx + 1) % len(GEMINI_KEYS)
        return GEMINI_KEYS[key_idx]

def get_gemini_embeddings_batch(texts: list, retries=5) -> list:
    """Генерирует эмбеддинги для списка текстов (батчем до 100 шт) через batchEmbedContents с обработкой 429."""
    # Подготавливаем payload
    requests_payload = []
    for text in texts:
        text_chunk = text[:3000] # Ограничиваем длину каждого текста
        requests_payload.append({
            "model": "models/gemini-embedding-001",
            "content": {"parts": [{"text": text_chunk}]}
        })
        
    for attempt in range(retries):
        api_key = get_next_key()
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-embedding-001:batchEmbedContents?key={api_key}"
        headers = {"Content-Type": "application/json"}
        payload = {"requests": requests_payload}
        
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=30)
            if resp.status_code == 200:
                embeddings_data = resp.json().get("embeddings", [])
                return [emb["values"] for emb in embeddings_data]
            elif resp.status_code == 429:
                print(f"[Embedding Batch API] Rate limit 429. Ждем 6 секунд перед повтором...")
                time.sleep(6)
            else:
                print(f"[Embedding Batch API] Ошибка {resp.status_code}: {resp.text}")
        except Exception as e:
            print(f"[Embedding Batch API] Исключение: {e}")
            
        time.sleep(2)
        
    raise Exception(f"Не удалось получить батч эмбеддингов после {retries} попыток")

def build_vector_db():
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    diseases_path = os.path.join(BASE_DIR, "data", "diseases_index.json")
    professions_path = os.path.join(BASE_DIR, "data", "professions_index.json")
    
    qdrant_db_path = os.path.join(BASE_DIR, "data", "qdrant_db_new")
    
    print(f"Инициализация базы Qdrant по пути: {qdrant_db_path}")
    client = QdrantClient(path=qdrant_db_path)
    
    # --- 1. Обработка заболеваний ---
    if os.path.exists(diseases_path):
        print(f"Загрузка заболеваний из {diseases_path}...")
        with open(diseases_path, "r", encoding="utf-8") as f:
            diseases_data = json.load(f)
        docs = diseases_data.get("documents", [])
        print(f"Всего документов заболеваний: {len(docs)}")
        
        client.recreate_collection(
            collection_name="diseases",
            vectors_config=VectorParams(size=3072, distance=Distance.COSINE)
        )
        
        print("Генерация векторов батчами по 30 документов...")
        points = []
        batch_size = 30
        
        for i in range(0, len(docs), batch_size):
            batch_docs = docs[i:i+batch_size]
            texts = []
            for doc in batch_docs:
                title = doc.get("title", "")
                content = doc.get("content", "")
                texts.append(f"Заболевание: {title}\n{content[:1500]}")
                
            try:
                vectors = get_gemini_embeddings_batch(texts)
                for idx, doc in enumerate(batch_docs):
                    global_idx = i + idx
                    points.append(
                        PointStruct(
                            id=global_idx,
                            vector=vectors[idx],
                            payload={
                                "id": doc.get("id", f"disease_{global_idx}"),
                                "title": doc.get("title", ""),
                                "content": doc.get("content", ""),
                                "url": doc.get("url", "")
                            }
                        )
                    )
                print(f"Обработано заболеваний: {len(points)}/{len(docs)}")
                # Небольшая пауза для обхода лимитов
                time.sleep(3)
            except Exception as e:
                print(f"Критическая ошибка на батче заболеваний {i}-{i+batch_size}: {e}")
                # Делаем паузу и пробуем продолжить
                time.sleep(10)
                
        print(f"Сохранение {len(points)} точек в Qdrant коллекцию 'diseases'...")
        for chunk_idx in range(0, len(points), 100):
            client.upsert(
                collection_name="diseases",
                points=points[chunk_idx:chunk_idx+100]
            )
        print("Коллекция 'diseases' успешно создана!")
        
    # --- 2. Обработка профессий ---
    if os.path.exists(professions_path):
        print(f"Загрузка профессий из {professions_path}...")
        with open(professions_path, "r", encoding="utf-8") as f:
            professions_data = json.load(f)
        docs = professions_data.get("documents", [])
        print(f"Всего документов профессий: {len(docs)}")
        
        client.recreate_collection(
            collection_name="professions",
            vectors_config=VectorParams(size=3072, distance=Distance.COSINE)
        )
        
        texts = []
        for doc in docs:
            title = doc.get("title", "")
            content = doc.get("content", "")
            texts.append(f"Специализация врача: {title}\nОписание работы: {content}")
            
        try:
            vectors = get_gemini_embeddings_batch(texts)
            points = []
            for idx, doc in enumerate(docs):
                points.append(
                    PointStruct(
                        id=idx,
                        vector=vectors[idx],
                        payload={
                            "id": doc.get("id", f"prof_{idx}"),
                            "title": doc.get("title", ""),
                            "content": doc.get("content", ""),
                            "url": doc.get("url", "")
                        }
                    )
                )
            print(f"Сохранение {len(points)} точек в Qdrant коллекцию 'professions'...")
            client.upsert(collection_name="professions", points=points)
            print("Коллекция 'professions' успешно создана!")
        except Exception as e:
            print(f"Ошибка на батче профессий: {e}")

if __name__ == "__main__":
    build_vector_db()
