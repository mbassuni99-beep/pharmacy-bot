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
    "fixed_custody": 2000.0,
    "current_custody": {
        "purchases_invoices": 0.0,
        "insurance_amounts": 0.0,
        "actual_cash": 2000.0,
        "last_audit_date": "",
        "last_audit_pharmacist": "",
        "status": "مطابق",
        "notes": ""
    },
    "custody_history": [],
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

def ensure_defaults(data):
    if not isinstance(data, dict):
        data = dict(DEFAULT_DATA)
    data.setdefault("admin_pin", "1234")
    data.setdefault("target_total", 314803.0)
    data.setdefault("target_non_wasfaty", 276252.0)
    data.setdefault("base_total_cum", 0.0)
    data.setdefault("base_wasfaty_cum", 0.0)
    data.setdefault("base_days_count", 0)
    data.setdefault("fixed_custody", 2000.0)
    data.setdefault("current_custody", {
        "purchases_invoices": 0.0,
        "insurance_amounts": 0.0,
        "actual_cash": float(data.get("fixed_custody", 2000.0)),
        "last_audit_date": "",
        "last_audit_pharmacist": "",
        "status": "مطابق",
        "notes": ""
    })
    data.setdefault("custody_history", [])
    data.setdefault("registered_chats", [])
    data.setdefault("archives", {})
    data.setdefault("history", {})
    return data

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
                    return ensure_defaults(data)
        except Exception as e:
            print("Error loading from KV:", e)

    if REDIS_URL:
        try:
            import redis
            r = redis.from_url(REDIS_URL)
            val = r.get("pharmacy_data")
            if val:
                data = json.loads(val)
                return ensure_defaults(data)
        except Exception as e:
            print("Error loading from REDIS_URL:", e)

    # Local fallback
    if os.path.exists(TEMP_FILE):
        try:
            with open(TEMP_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return ensure_defaults(data)
        except Exception:
            pass

    return ensure_defaults(dict(DEFAULT_DATA))

def save_data(data):
    data = ensure_defaults(data)
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

# -------------------------------------------------------------
# Custody (Petty Cash Float) Management
# -------------------------------------------------------------
def get_custody_info():
    data = load_data()
    fixed = float(data.get("fixed_custody", 2000.0))
    curr = data.get("current_custody", {})
    invoices = float(curr.get("purchases_invoices", 0.0))
    insurance = float(curr.get("insurance_amounts", 0.0))
    actual = float(curr.get("actual_cash", fixed))

    total_docs = invoices + insurance
    expected = max(0.0, fixed - total_docs)
    diff = actual - expected

    if abs(diff) < 0.01:
        status = "مطابق"
        diff_str = "0.00"
    elif diff < 0:
        status = f"عجز: {abs(diff):,.2f} SAR"
        diff_str = f"-{abs(diff):,.2f}"
    else:
        status = f"زيادة: +{diff:,.2f} SAR"
        diff_str = f"+{diff:,.2f}"

    return {
        "fixed_custody": fixed,
        "purchases_invoices": invoices,
        "insurance_amounts": insurance,
        "total_documents": total_docs,
        "expected_cash": expected,
        "actual_cash": actual,
        "diff": diff,
        "diff_str": diff_str,
        "status": status,
        "last_audit_date": curr.get("last_audit_date", ""),
        "last_audit_pharmacist": curr.get("last_audit_pharmacist", ""),
        "notes": curr.get("notes", "")
    }

def save_custody_audit(purchases_invoices, insurance_amounts, actual_cash, pharmacist_name, notes=""):
    data = load_data()
    fixed = float(data.get("fixed_custody", 2000.0))
    invoices = float(purchases_invoices or 0.0)
    insurance = float(insurance_amounts or 0.0)
    actual = float(actual_cash or 0.0)

    total_docs = invoices + insurance
    expected = max(0.0, fixed - total_docs)
    diff = actual - expected

    if abs(diff) < 0.01:
        status = "مطابق"
    elif diff < 0:
        status = f"عجز: {abs(diff):,.2f} SAR"
    else:
        status = f"زيادة: +{diff:,.2f} SAR"

    now_str = datetime.datetime.now().strftime("%Y-%m-%d %I:%M %p")

    record = {
        "date": now_str,
        "fixed": fixed,
        "invoices": invoices,
        "insurance": insurance,
        "total_docs": total_docs,
        "expected": expected,
        "actual": actual,
        "diff": diff,
        "status": status,
        "pharmacist": pharmacist_name,
        "notes": notes
    }

    data["current_custody"] = {
        "purchases_invoices": invoices,
        "insurance_amounts": insurance,
        "actual_cash": actual,
        "last_audit_date": now_str,
        "last_audit_pharmacist": pharmacist_name,
        "status": status,
        "notes": notes
    }

    if "custody_history" not in data:
        data["custody_history"] = []
    data["custody_history"].append(record)

    # Keep last 50 audit entries
    if len(data["custody_history"]) > 50:
        data["custody_history"] = data["custody_history"][-50:]

    save_data(data)
    return record

def set_fixed_custody_amount(new_amount):
    data = load_data()
    data["fixed_custody"] = float(new_amount)
    save_data(data)
    return True

def replenish_custody(pharmacist_name="Admin"):
    """
    تسوية / تعويض العهدة من الإدارة:
    يتم تصفير فواتير المشتريات ومبالغ التأمين وإعادة الكاش للعهدة الثابتة
    """
    data = load_data()
    fixed = float(data.get("fixed_custody", 2000.0))
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %I:%M %p")

    rep_record = {
        "date": now_str,
        "type": "replenishment",
        "fixed": fixed,
        "invoices": 0.0,
        "insurance": 0.0,
        "actual": fixed,
        "diff": 0.0,
        "status": "تم تعويض العهدة بالكامل ✅",
        "pharmacist": pharmacist_name,
        "notes": "استلام كاش التعويض وتصفير الفواتير السابقة"
    }

    data["current_custody"] = {
        "purchases_invoices": 0.0,
        "insurance_amounts": 0.0,
        "actual_cash": fixed,
        "last_audit_date": now_str,
        "last_audit_pharmacist": pharmacist_name,
        "status": "تم تعويض العهدة - مطابقة ✅",
        "notes": "تم التعويض"
    }

    if "custody_history" not in data:
        data["custody_history"] = []
    data["custody_history"].append(rep_record)
    save_data(data)
    return rep_record

# -------------------------------------------------------------
# Month & Day Admin Operations
# -------------------------------------------------------------
def archive_and_reset_month(month_name=None, new_target_tot=None, new_target_nw=None):
    data = load_data()
    now = datetime.datetime.now()
    if not month_name:
        month_name = now.strftime("%Y_%m")

    if "archives" not in data:
        data["archives"] = {}

    data["archives"][month_name] = {
        "history": data.get("history", {}),
        "target_total": data.get("target_total", 0),
        "target_non_wasfaty": data.get("target_non_wasfaty", 0),
        "archived_at": now.strftime("%Y-%m-%d %H:%M")
    }

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
        if d_str in data["history"]:
            del data["history"][d_str]
            save_data(data)
            return True, "تم مسح بيانات اليوم بنجاح."
        return False, "اليوم غير موجود في السجل."
    else:
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
