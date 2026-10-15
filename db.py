import os
import json
import requests

KV_URL = os.environ.get("KV_REST_API_URL") or os.environ.get("UPSTASH_REDIS_REST_URL")
KV_TOKEN = os.environ.get("KV_REST_API_TOKEN") or os.environ.get("UPSTASH_REDIS_REST_TOKEN")
TEMP_FILE = "/tmp/pharmacy_bot_data.json"

DEFAULT_DATA = {
    "target_total": 314803.0,
    "target_non_wasfaty": 276252.0,
    "base_total_cum": 0.0,
    "base_wasfaty_cum": 0.0,
    "registered_chats": [],
    "history": {
        "6": {
            "daily": 5200.0,
            "cash": 1850.0,
            "wasfaty": 2100.0,
            "date": "2026-10-14"
        },
        "14": {
            "daily": 5800.0,
            "cash": 1950.0,
            "wasfaty": 3500.0,
            "total_cum": 11000.0,
            "wasfaty_cum": 5600.0,
            "date": "2026-10-14"
        }
    }
}

def load_data():
    if KV_URL and KV_TOKEN:
        try:
            url = f"{KV_URL.rstrip('/')}/get/pharmacy_data"
            headers = {"Authorization": f"Bearer {KV_TOKEN}"}
            res = requests.get(url, headers=headers, timeout=5)
            if res.status_code == 200:
                result = res.json().get("result")
                if result:
                    if isinstance(result, str):
                        return json.loads(result)
                    elif isinstance(result, dict):
                        return result
        except Exception as e:
            print("Error loading from KV:", e)

    # Local fallback
    if os.path.exists(TEMP_FILE):
        try:
            with open(TEMP_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass

    return dict(DEFAULT_DATA)

def save_data(data):
    if KV_URL and KV_TOKEN:
        try:
            url = f"{KV_URL.rstrip('/')}/set/pharmacy_data"
            headers = {"Authorization": f"Bearer {KV_TOKEN}"}
            payload = json.dumps(data)
            res = requests.post(url, headers=headers, data=payload, timeout=5)
            if res.status_code == 200:
                return True
        except Exception as e:
            print("Error saving to KV:", e)

    # Local fallback
    try:
        with open(TEMP_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
    return True

def register_chat(chat_id):
    data = load_data()
    if "registered_chats" not in data:
        data["registered_chats"] = []
    if chat_id not in data["registered_chats"]:
        data["registered_chats"].append(chat_id)
        save_data(data)
