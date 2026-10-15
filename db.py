import os
import json
import requests
import datetime

KV_URL = os.environ.get("KV_REST_API_URL") or os.environ.get("UPSTASH_REDIS_REST_URL")
KV_TOKEN = os.environ.get("KV_REST_API_TOKEN") or os.environ.get("UPSTASH_REDIS_REST_TOKEN")
REDIS_URL = os.environ.get("REDIS_URL")
TEMP_FILE = "/tmp/pharmacy_bot_data.json"

DEFAULT_DATA = {
    "admin_pin": "1234",
    "target_total": 314803.0,
    "target_non_wasfaty": 276252.0,
    "base_total_cum": 0.0,
    "base_wasfaty_cum": 0.0,
    "base_days_count": 0,
    "registered_chats": [],
    "archives": {},
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
                        data = json.loads(result)
                    elif isinstance(result, dict):
                        data = result
                    else:
                        data = dict(DEFAULT_DATA)
                    if "admin_pin" not in data:
                        data["admin_pin"] = "1234"
                    if "archives" not in data:
                        data["archives"] = {}
                    return data
        except Exception as e:
            print("Error loading from KV:", e)

    if REDIS_URL:
        try:
            import redis
            r = redis.from_url(REDIS_URL)
            val = r.get("pharmacy_data")
            if val:
                data = json.loads(val)
                if "admin_pin" not in data:
                    data["admin_pin"] = "1234"
                if "archives" not in data:
                    data["archives"] = {}
                return data
        except Exception as e:
            print("Error loading from REDIS_URL:", e)

    # Local fallback
    if os.path.exists(TEMP_FILE):
        try:
            with open(TEMP_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if "admin_pin" not in data:
                    data["admin_pin"] = "1234"
                if "archives" not in data:
                    data["archives"] = {}
                return data
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

    if REDIS_URL:
        try:
            import redis
            r = redis.from_url(REDIS_URL)
            r.set("pharmacy_data", json.dumps(data))
            return True
        except Exception as e:
            print("Error saving to REDIS_URL:", e)

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

def verify_admin_pin(pin):
    data = load_data()
    current_pin = str(data.get("admin_pin", "1234")).strip()
    return str(pin).strip() == current_pin

def set_admin_pin(new_pin):
    data = load_data()
    data["admin_pin"] = str(new_pin).strip()
    save_data(data)
    return True

def archive_and_reset_month(month_name=None, new_target_tot=None, new_target_nw=None):
    data = load_data()
    now = datetime.datetime.now()
    if not month_name:
        month_name = now.strftime("%Y_%m")

    if "archives" not in data:
        data["archives"] = {}

    # Save snapshot of previous month
    data["archives"][month_name] = {
        "history": data.get("history", {}),
        "target_total": data.get("target_total", 0),
        "target_non_wasfaty": data.get("target_non_wasfaty", 0),
        "archived_at": now.strftime("%Y-%m-%d %H:%M")
    }

    # Reset current month
    data["history"] = {}
    data["base_total_cum"] = 0.0
    data["base_wasfaty_cum"] = 0.0
    data["base_days_count"] = 0

    if new_target_tot is not None and new_target_tot > 0:
        data["target_total"] = float(new_target_tot)
    if new_target_nw is not None and new_target_nw > 0:
        data["target_non_wasfaty"] = float(new_target_nw)

    save_data(data)
    return True

def set_base_carryover(base_total, base_wasfaty, base_days=0):
    data = load_data()
    data["base_total_cum"] = float(base_total)
    data["base_wasfaty_cum"] = float(base_wasfaty)
    data["base_days_count"] = int(base_days)
    save_data(data)
    return True

def edit_or_delete_day(day_num, new_data=None):
    data = load_data()
    d_str = str(int(day_num))
    if "history" not in data:
        data["history"] = {}

    if new_data is None:
        # Delete day
        if d_str in data["history"]:
            del data["history"][d_str]
            save_data(data)
            return True, "تم مسح بيانات اليوم بنجاح."
        return False, "اليوم غير موجود في السجل."
    else:
        # Update day
        data["history"][d_str] = new_data
        save_data(data)
        return True, "تم تعديل بيانات اليوم بنجاح."

def factory_reset():
    data = load_data()
    data["history"] = {}
    data["base_total_cum"] = 0.0
    data["base_wasfaty_cum"] = 0.0
    data["base_days_count"] = 0
    save_data(data)
    return True
