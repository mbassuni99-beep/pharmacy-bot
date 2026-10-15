from http.server import BaseHTTPRequestHandler
import json
import os
import sys
import datetime
import telebot
from telebot import types

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from db import load_data

TOKEN = os.environ.get("TELEGRAM_TOKEN") or "8926788986:AAG4ZzgJif82hUl-BZATgV6Sbc9aDbcpO_w"
bot = telebot.TeleBot(TOKEN, threaded=False)

def run_reminder_check():
    data = load_data()
    now = datetime.datetime.now()
    today_day = str(now.day)

    # Check if report has NOT been submitted for today
    if today_day not in data.get("history", {}):
        registered = data.get("registered_chats", [])
        if not registered:
            return "No registered chats."

        reminder_text = (
            "⏰ **تنبيه إغلاق الشفت اليومي — صيدلية زهرة الروضة 103 💊**\n\n"
            "دكتور، لم يتم تسجيل مبيعات اليوم حتى الآن!\n"
            "يرجى فتح البوت وتسجيل الأرقام وإرسال التقرير لجروب الواتساب قبل إغلاق الشفت 📝"
        )
        markup = types.InlineKeyboardMarkup()
        b_rec = types.InlineKeyboardButton("📝 تسجيل مبيعات اليوم", callback_data="start_record")
        markup.add(b_rec)

        sent_count = 0
        for chat_id in registered:
            try:
                bot.send_message(chat_id, reminder_text, reply_markup=markup, parse_mode="Markdown")
                sent_count += 1
            except Exception as e:
                print(f"Failed to send reminder to {chat_id}: {e}")

        return f"Reminder sent to {sent_count} chats."
    return "Sales already reported today. No reminder needed."

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        result = run_reminder_check()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps({"status": "success", "result": result}).encode('utf-8'))
