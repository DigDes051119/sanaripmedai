import os
import re
import sys
import json
import math
import time
import requests
import urllib.parse
import threading
import schedule
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor, as_completed

load_dotenv()

BASE_URL = "https://diseases.medelement.com"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "X-Requested-With": "XMLHttpRequest"
}

def tokenize(text):
    """Очищает текст и разбивает на токены"""
    text = text.lower()
    words = re.findall(r'[a-zA-Zа-яА-ЯёЁ0-9]+', text)
    return words

class SimpleTFIDFIndex:
    def __init__(self):
        self.doc_count = 0
        self.documents = []
        self.vocab = {}
        self.df = {}
        self.tf = []
        self.doc_lens = []

    def add_document(self, doc_id, title, content, url):
        self.doc_count += 1
        tokens = tokenize(title + " " + content)
        doc_tf = {}
        for t in tokens:
            if t not in self.vocab:
                self.vocab[t] = len(self.vocab)
            t_id = self.vocab[t]
            doc_tf[t_id] = doc_tf.get(t_id, 0) + 1
            
        for t_id in doc_tf.keys():
            self.df[t_id] = self.df.get(t_id, 0) + 1
            
        self.documents.append({
            "id": doc_id,
            "title": title,
            "content": content,
            "url": url
        })
        self.tf.append(doc_tf)

    def build_index(self):
        self.doc_lens = []
        for doc_idx in range(self.doc_count):
            doc_tf = self.tf[doc_idx]
            squared_sum = 0.0
            for t_id, count in doc_tf.items():
                idf = math.log((self.doc_count + 1) / (self.df.get(t_id, 0) + 1)) + 1
                squared_sum += (count * idf) ** 2
            self.doc_lens.append(math.sqrt(squared_sum))

    def save(self, filepath):
        data = {
            "doc_count": self.doc_count,
            "documents": self.documents,
            "vocab": self.vocab,
            "df": self.df,
            "tf": self.tf,
            "doc_lens": self.doc_lens
        }
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"[RAG] Векторный индекс успешно сохранен в: {filepath}")

    @classmethod
    def load(cls, filepath):
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        index = cls()
        index.doc_count = data["doc_count"]
        index.documents = data["documents"]
        index.vocab = data["vocab"]
        index.df = {int(k): v for k, v in data["df"].items()}
        index.tf = [{int(k): v for k, v in doc.items()} for doc in data["tf"]]
        index.doc_lens = data["doc_lens"]
        return index

    def search(self, query, top_k=3):
        tokens = tokenize(query)
        query_tf = {}
        for t in tokens:
            if t in self.vocab:
                t_id = self.vocab[t]
                query_tf[t_id] = query_tf.get(t_id, 0) + 1
                
        if not query_tf or self.doc_count == 0:
            return []
            
        query_len = 0.0
        query_tfidf = {}
        for t_id, count in query_tf.items():
            idf = math.log((self.doc_count + 1) / (self.df.get(t_id, 0) + 1)) + 1
            tfidf = count * idf
            query_tfidf[t_id] = tfidf
            query_len += tfidf ** 2
        query_norm = math.sqrt(query_len)
        
        scores = []
        for doc_idx in range(self.doc_count):
            doc_tf = self.tf[doc_idx]
            dot_product = 0.0
            for t_id, q_val in query_tfidf.items():
                if t_id in doc_tf:
                    idf = math.log((self.doc_count + 1) / (self.df.get(t_id, 0) + 1)) + 1
                    dot_product += q_val * (doc_tf[t_id] * idf)
            
            doc_norm = self.doc_lens[doc_idx]
            if query_norm > 0 and doc_norm > 0:
                cosine_sim = dot_product / (query_norm * doc_norm)
            else:
                cosine_sim = 0.0
            scores.append((self.documents[doc_idx], cosine_sim))
            
        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:top_k]

def fetch_disease_detail(url):
    """Скачивает детальную информацию по конкретному заболеванию с локальным кэшированием"""
    doc_id = urllib.parse.urlparse(url).path.strip("/").replace("/", "_")
    local_path = f"data/diseases_kb/{doc_id}.json"
    
    # Если файл уже скачан локально, используем его
    if os.path.exists(local_path):
        try:
            with open(local_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass

    try:
        r = requests.get(url, headers={"User-Agent": HEADERS["User-Agent"]}, timeout=15)
        if r.status_code != 200:
            return None
        soup = BeautifulSoup(r.text, "html.parser")
        
        title = soup.find("h1")
        title_text = title.text.strip() if title else "Медицинский протокол"
        
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
            
        content_div = soup.find("div", class_="article") or soup.find("section", id="layout-content") or soup.find("body")
        content_text = content_div.get_text(separator="\n", strip=True) if content_div else soup.get_text(separator="\n", strip=True)
        
        doc = {
            "id": doc_id,
            "title": title_text,
            "content": content_text[:15000],
            "url": url
        }
        
        with open(local_path, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=2)
            
        return doc
    except Exception as e:
        print(f"[RAG Scraper] Ошибка скачивания детальной страницы {url}: {e}")
        return None

def run_scraper(limit=None):
    """Сбор заболеваний и терминов и обновление локальной базы RAG с защитой от бесконечных циклов"""
    print("[RAG] Начало скачивания справочников с MedElement...")
    os.makedirs("data/diseases_kb", exist_ok=True)
    
    scraped_docs = []
    
    # === 1. СКАЧИВАНИЕ РАЗДЕЛА «ЗАБОЛЕВАНИЯ» ===
    print("[RAG] Сбор списка заболеваний...")
    disease_urls = []
    skip = 0
    consecutive_failures = 0
    
    while True:
        if limit and len(disease_urls) >= limit:
            break
            
        url = f"{BASE_URL}/search/load_data?searched_data=diseases&q=&diseases_filter_type=list&diseases_content_type=1&section_medicine=0&category_mkb=0&parent_category_mkb=0&skip={skip}"
        try:
            r = requests.get(url, headers=HEADERS, timeout=15)
            if r.status_code != 200:
                consecutive_failures += 1
                if consecutive_failures > 3:
                    break
                time.sleep(1)
                continue
                
            consecutive_failures = 0
            res = r.json()
            html_data = res.get("data", "")
            if not html_data.strip():
                break 
                
            soup = BeautifulSoup(html_data, "html.parser")
            links = soup.find_all("a", class_="results-item__title-link")
            if not links:
                break
                
            new_links_added = 0
            for a in links:
                href = a.get("href")
                if href:
                    full_url = urllib.parse.urljoin(BASE_URL, href)
                    if full_url not in disease_urls:
                        disease_urls.append(full_url)
                        new_links_added += 1
                        
            # Если на странице нет новых ссылок, значит мы начали ходить по кругу
            if new_links_added == 0:
                print("[RAG] Все доступные ссылки заболеваний собраны.")
                break
                
            if skip % 100 == 0:
                print(f"[RAG] Собрано {len(disease_urls)} ссылок на заболевания...")
            skip += 10
            time.sleep(0.05)
        except Exception as e:
            print(f"[RAG ERROR] Ошибка парсинга списка на skip={skip}: {e}")
            break
            
    if limit:
        disease_urls = disease_urls[:limit]
        
    print(f"[RAG] Скачивание детальных страниц заболеваний (Всего: {len(disease_urls)})...")
    with ThreadPoolExecutor(max_workers=20) as executor:
        futures = {executor.submit(fetch_disease_detail, url): url for url in disease_urls}
        completed_count = 0
        for future in as_completed(futures):
            doc = future.result()
            if doc:
                scraped_docs.append(doc)
            completed_count += 1
            if completed_count % 100 == 0 or completed_count == len(disease_urls):
                print(f"[RAG] Загружено {completed_count}/{len(disease_urls)} заболеваний...")
                
    # === 2. СКАЧИВАНИЕ РАЗДЕЛА «ТЕРМИНЫ» ===
    print("[RAG] Сбор и обработка медицинских терминов...")
    terms_count = 0
    skip = 0
    consecutive_failures = 0
    processed_terms = set()
    
    while True:
        if limit and terms_count >= limit:
            break
            
        url = f"{BASE_URL}/search/load_data?searched_data=terms&q=&terms_filter_type=list&skip={skip}"
        try:
            r = requests.get(url, headers=HEADERS, timeout=15)
            if r.status_code != 200:
                consecutive_failures += 1
                if consecutive_failures > 3:
                    break
                time.sleep(1)
                continue
                
            consecutive_failures = 0
            res = r.json()
            html_data = res.get("data", "")
            if not html_data.strip():
                break
                
            soup = BeautifulSoup(html_data, "html.parser")
            items = soup.find_all("div", class_="results-item")
            if not items:
                break
                
            new_terms_added = 0
            for item in items:
                title_el = item.find("a", class_="results-item__title-link")
                if not title_el:
                    continue
                term_name = title_el.text.strip()
                
                doc_id = f"term_{term_name.replace(' ', '_').replace('/', '_')}"
                if doc_id in processed_terms:
                    continue
                    
                val_divs = item.find_all("div", class_="results-item__value")
                desc_text = "\n".join([div.get_text(separator=" ", strip=True) for div in val_divs])
                doc_url = urllib.parse.urljoin(BASE_URL, title_el.get("href", ""))
                
                doc = {
                    "id": doc_id,
                    "title": f"Термин: {term_name}",
                    "content": desc_text,
                    "url": doc_url
                }
                
                scraped_docs.append(doc)
                processed_terms.add(doc_id)
                new_terms_added += 1
                
                with open(f"data/diseases_kb/{doc_id}.json", "w", encoding="utf-8") as f:
                    json.dump(doc, f, ensure_ascii=False, indent=2)
                    
                terms_count += 1
                
            if new_terms_added == 0:
                print("[RAG] Все доступные медицинские термины собраны.")
                break
                
            if terms_count % 100 == 0 or len(items) < 10:
                print(f"[RAG] Обработано {terms_count} терминов...")
                
            skip += 10
            time.sleep(0.05)
        except Exception as e:
            print(f"[RAG ERROR] Ошибка парсинга терминов на skip={skip}: {e}")
            break
            
    # Добавляем любые файлы, которые уже есть локально, но не были заново запрошены
    local_files = os.listdir("data/diseases_kb")
    scraped_ids = {doc["id"] for doc in scraped_docs}
    loaded_from_disk = 0
    
    for filename in local_files:
        if filename.endswith(".json"):
            doc_id = filename[:-5]
            if doc_id not in scraped_ids:
                try:
                    with open(f"data/diseases_kb/{filename}", "r", encoding="utf-8") as f:
                        doc = json.load(f)
                        scraped_docs.append(doc)
                        loaded_from_disk += 1
                except Exception:
                    pass
                    
    print(f"[RAG] Загружено с диска ранее скачанных статей: {loaded_from_disk}")
    print(f"[RAG] Всего документов для RAG индекса: {len(scraped_docs)}")
    
    # === 3. ПОСТРОЕНИЕ ВЕКТОРНОГО ИНДЕКСА ===
    print("[RAG] Построение нового локального TF-IDF индекса...")
    index = SimpleTFIDFIndex()
    for doc in scraped_docs:
        index.add_document(doc["id"], doc["title"], doc["content"], doc["url"])
        
    index.build_index()
    index.save("data/diseases_index.json")
    print("[RAG] Локальная база RAG успешно обновлена!")

def run_scheduler_loop():
    """Фоновая служба планировщика"""
    print("[RAG Scheduler] Запуск планировщика обновлений...")
    schedule.every(30).days.do(run_scraper)
    
    while True:
        schedule.run_pending()
        time.sleep(60)

def start_background_updater():
    """Запускает фоновое обновление базы знаний RAG"""
    if not os.path.exists("data/diseases_index.json"):
        t1 = threading.Thread(target=lambda: run_scraper(), daemon=True)
        t1.start()
        
    t2 = threading.Thread(target=run_scheduler_loop, daemon=True)
    t2.start()

if __name__ == "__main__":
    limit_val = None
    if len(sys.argv) > 1:
        for arg in sys.argv:
            if arg.startswith("--limit="):
                limit_val = int(arg.split("=")[1])
    run_scraper(limit=limit_val)
