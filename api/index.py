import os
import sys
import datetime
import calendar
import urllib.parse
import re
from flask import Flask, request, jsonify
import telebot
from telebot import types

# Add parent directory to path so db and logic can be imported
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from db import load_data, save_data, register_chat
from logic import calculate_metrics, generate_excel_report, fmt, progress_bar, get_pharmacist_title

TOKEN = os.environ.get("TELEGRAM_TOKEN") or "8926788986:AAG4ZzgJif82hUl-BZATgV6Sbc9aDbcpO_w"
bot = telebot.TeleBot(TOKEN, threaded=False)
app = Flask(__name__)

def get_main_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    btn_record = types.KeyboardButton("📝 تسجيل مبيعات اليوم")
    btn_dash = types.KeyboardButton("📊 لوحة التحكم (Dashboard)")
    btn_target = types.KeyboardButton("🎯 أهداف الشهر والحوافز")
    btn_excel = types.KeyboardButton("📥 تحميل تقرير الإكسل")
    markup.add(btn_record, btn_dash)
    markup.add(btn_target, btn_excel)
    return markup

# -------------------------------------------------------------
# Handlers
# -------------------------------------------------------------
@bot.message_handler(commands=['start', 'menu'])
def handle_start(message):
    register_chat(message.chat.id)
    welcome_text = (
        "👋 **مرحباً بك في نظام إدارة ومتابعة مبيعات صيدلية زهرة الروضة 103 💊 (سحابي 24/7)**\n\n"
        "✨ **المميزات المفعلة سحابياً:**\n"
        "• ⏰ **منبه تلقائي للشفت** يعمل عبر Vercel Cron في 11:30 PM.\n"
        "• 👨‍⚕️ **توثيق الصيدلي المسؤول** وتوقيت الإرسال بدقة في كل تقرير.\n"
        "• 📈 **حساب نسبة النمو اليومية** مقارنة بمبيعات أمس تلقائياً.\n"
        "• 🎯 **تتبع ذكي لحوافز الـ 85%** لغير وصفتي والتوتال.\n\n"
        "👇 **اختر الإجراء المطلوب من القائمة أدناه أو أرسل 3 أرقام مفصولة بمسافة:**\n"
        "`مبيعات_اليوم الكاش وصفتي` (مثال: `5500 2000 1200`)"
    )
    bot.send_message(message.chat.id, welcome_text, reply_markup=get_main_keyboard(), parse_mode="Markdown")

@bot.message_handler(func=lambda m: bool(m.text and ("لوحة التحكم" in m.text or "Dashboard" in m.text or "داشبورد" in m.text)))
def show_dashboard(message):
    register_chat(message.chat.id)
    data = load_data()
    today = datetime.date.today()
    day_num = today.day
    _, last_day = calendar.monthrange(today.year, today.month)
    days_in_month = last_day
    rem_days = max(1, days_in_month - day_num)

    t_tot = data.get("target_total", 150000.0)
    t_nw = data.get("target_non_wasfaty", 100000.0)

    # Cumulatives
    cum_total = data.get("base_total_cum", 0.0)
    cum_wasfaty = data.get("base_wasfaty_cum", 0.0)

    for d in range(1, day_num + 1):
        d_str = str(d)
        if d_str in data.get("history", {}):
            cum_total += data["history"][d_str].get("daily", 0.0)
            cum_wasfaty += data["history"][d_str].get("wasfaty", 0.0)

    cum_nw = max(0.0, cum_total - cum_wasfaty)

    # Run-rate Expectations
    exp_tot = (cum_total / day_num) * days_in_month if day_num > 0 else 0.0
    exp_nw = (cum_nw / day_num) * days_in_month if day_num > 0 else 0.0

    tot_ach = (exp_tot / t_tot) * 100 if t_tot > 0 else 0.0
    nw_ach = (exp_nw / t_nw) * 100 if t_nw > 0 else 0.0

    emoji_tot = "🟢" if tot_ach >= 100 else ("🟡" if tot_ach >= 85 else "🔴")
    emoji_nw = "🟢" if nw_ach >= 100 else ("🟡" if nw_ach >= 85 else "🔴")

    mtd_tot_pct = (cum_total / t_tot) * 100 if t_tot > 0 else 0.0
    mtd_nw_pct = (cum_nw / t_nw) * 100 if t_nw > 0 else 0.0

    # 85% Incentives
    t85_tot = t_tot * 0.85
    rem85_tot = max(0.0, t85_tot - cum_total)
    req85_tot = rem85_tot / rem_days

    t85_nw = t_nw * 0.85
    rem85_nw = max(0.0, t85_nw - cum_nw)
    req85_nw = rem85_nw / rem_days

    # Last recorded info
    last_log_str = str(day_num)
    last_info = ""
    if last_log_str in data.get("history", {}):
        h = data["history"][last_log_str]
        last_info = f"✅ **آخر تسجيل اليوم:** `{fmt(h.get('daily', 0))} SAR` بواسطة {h.get('pharmacist', 'Dr. Staff')} ({h.get('time', '')})\n"

    txt = (
        f"📊 **لوحة التحكم المباشرة — صيدلية زهرة الروضة 103 💊**\n"
        f"📅 **اليوم:** {day_num} من {days_in_month} (المتبقي: {rem_days} يوم)\n"
        f"{last_info}"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🎯 **مستهدف المبيعات الإجمالي (Total Target):**\n"
        f"• المستهدف: `{fmt(t_tot)} SAR`\n"
        f"• التراكمي الفعلي: `{fmt(cum_total)} SAR` ({mtd_tot_pct:.1f}%)\n"
        f"• المتوقع لنهاية الشهر: `{fmt(exp_tot)} SAR`\n"
        f"• نسبة الإنجاز المتوقعة: **{tot_ach:.1f}%** {emoji_tot}\n"
        f"  `{progress_bar(tot_ach)}`\n\n"
        f"💊 **مستهدف غير وصفتي (Non-Wasfaty Target):**\n"
        f"• المستهدف: `{fmt(t_nw)} SAR`\n"
        f"• التراكمي الفعلي: `{fmt(cum_nw)} SAR` ({mtd_nw_pct:.1f}%)\n"
        f"• المتوقع لنهاية الشهر: `{fmt(exp_nw)} SAR`\n"
        f"• نسبة الإنجاز المتوقعة: **{nw_ach:.1f}%** {emoji_nw}\n"
        f"  `{progress_bar(nw_ach)}`\n\n"
        f"📋 **تراكمي مبيعات وصفتي حتى اليوم:** `{fmt(cum_wasfaty)} SAR`\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🎁 **تتبع حافز الـ 85% (Incentive Track):**\n"
        f"• تارجت 85% غير وصفتي: `{fmt(t85_nw)}`\n"
        f"  👈 المتبقي: `{fmt(rem85_nw)}` (مطلوب: `{fmt(req85_nw)}/يوم`)\n"
        f"• تارجت 85% التوتال: `{fmt(t85_tot)}`\n"
        f"  👈 المتبقي: `{fmt(rem85_tot)}` (مطلوب: `{fmt(req85_tot)}/يوم`)\n"
    )

    markup = types.InlineKeyboardMarkup()
    btn_send = types.InlineKeyboardButton("📝 تسجيل مبيعات اليوم", callback_data="start_record")
    btn_ref = types.InlineKeyboardButton("🔄 تحديث البيانات", callback_data="refresh_dash")
    markup.add(btn_send, btn_ref)

    bot.send_message(message.chat.id, txt, reply_markup=markup, parse_mode="Markdown")

@bot.message_handler(func=lambda m: bool(m.text and ("أهداف الشهر" in m.text or "الحوافز" in m.text or "Target" in m.text)))
def show_targets(message):
    register_chat(message.chat.id)
    data = load_data()
    t_tot = data.get("target_total", 150000.0)
    t_nw = data.get("target_non_wasfaty", 100000.0)

    txt = (
        "🎯 **إعدادات مستهدفات الشهر لصيدلية زهرة الروضة 103 💊**\n\n"
        f"• مستهدف إجمالي المبيعات (Total Target): `{fmt(t_tot)} SAR`\n"
        f"• مستهدف غير وصفتي (Non-Wasfaty Target): `{fmt(t_nw)} SAR`\n"
        f"• حد استحقاق الحافز 85% غير وصفتي: `{fmt(t_nw * 0.85)} SAR`\n"
        f"• حد استحقاق الحافز 85% التوتال: `{fmt(t_tot * 0.85)} SAR`\n\n"
        "💡 **لتعديل الأهداف:** اضغط على الأزرار أدناه:"
    )
    markup = types.InlineKeyboardMarkup()
    btn1 = types.InlineKeyboardButton("✏️ تعديل تارجت التوتال", callback_data="set_target_total")
    btn2 = types.InlineKeyboardButton("✏️ تعديل تارجت غير وصفتي", callback_data="set_target_nw")
    markup.add(btn1)
    markup.add(btn2)
    bot.send_message(message.chat.id, txt, reply_markup=markup, parse_mode="Markdown")

@bot.message_handler(func=lambda m: bool(m.text and ("تحميل تقرير" in m.text or "إكسل" in m.text or "Excel" in m.text)))
def send_excel(message):
    register_chat(message.chat.id)
    bot.send_chat_action(message.chat.id, "upload_document")
    path = generate_excel_report()
    now = datetime.datetime.now()
    caption = f"📊 **تقرير مبيعات شهر {now.strftime('%B %Y')} — صيدلية زهرة الروضة 103** 💊"
    with open(path, "rb") as doc:
        bot.send_document(message.chat.id, doc, caption=caption, parse_mode="Markdown")

@bot.message_handler(func=lambda m: bool(m.text and ("تسجيل مبيعات" in m.text)))
def guide_record(message):
    register_chat(message.chat.id)
    txt = (
        "📝 **تسجيل مبيعات اليوم السريع:**\n\n"
        "أرسل الأرقام الثلاثة في رسالة واحدة مفصولة بمسافة:\n"
        "`مبيعات_اليوم الكاش وصفتي`\n\n"
        "🔹 **مثال:**\n"
        "`5420 2150 1200`\n\n"
        "👈 وسيقوم البوت بحساب التقرير وتجهيز زر الإرسال المباشر للواتساب فوراً!"
    )
    bot.send_message(message.chat.id, txt, parse_mode="Markdown")

# Inline Callbacks
@bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(call):
    register_chat(call.message.chat.id)
    if call.data == "refresh_dash":
        show_dashboard(call.message)
        bot.answer_callback_query(call.id, "تم تحديث البيانات! ✅")
    elif call.data == "start_record":
        guide_record(call.message)
        bot.answer_callback_query(call.id)
    elif call.data == "set_target_total":
        bot.send_message(call.message.chat.id, "✏️ أرسل تارجت التوتال الجديد كالتالي:\n`تارجت التوتال 300000`", parse_mode="Markdown")
        bot.answer_callback_query(call.id)
    elif call.data == "set_target_nw":
        bot.send_message(call.message.chat.id, "✏️ أرسل تارجت غير وصفتي الجديد كالتالي:\n`تارجت غير وصفتي 250000`", parse_mode="Markdown")
        bot.answer_callback_query(call.id)

# Free text processor (3 numbers or target update)
@bot.message_handler(func=lambda m: True)
def process_text_input(message):
    register_chat(message.chat.id)
    text = message.text.strip()

    # Target updates via text
    if text.startswith("تارجت التوتال"):
        nums = re.findall(r"[\d\.]+", text)
        if nums:
            val = float(nums[0])
            d = load_data()
            d["target_total"] = val
            save_data(d)
            bot.reply_to(message, f"✅ تم تحديث مستهدف المبيعات الإجمالي إلى: `{fmt(val)} SAR`", parse_mode="Markdown")
            return

    if text.startswith("تارجت غير وصفتي"):
        nums = re.findall(r"[\d\.]+", text)
        if nums:
            val = float(nums[0])
            d = load_data()
            d["target_non_wasfaty"] = val
            save_data(d)
            bot.reply_to(message, f"✅ تم تحديث مستهدف غير وصفتي إلى: `{fmt(val)} SAR`", parse_mode="Markdown")
            return

    # 3 numbers entry: daily cash wasfaty
    raw_numbers = re.findall(r"[\d\.]+", text.replace(",", ""))
    if len(raw_numbers) >= 3:
        try:
            daily = float(raw_numbers[0])
            cash = float(raw_numbers[1])
            wasfaty = float(raw_numbers[2])

            pharmacist_name = get_pharmacist_title(message.from_user)
            metrics = calculate_metrics(daily, cash, wasfaty, pharmacist_name)

            # Persist to database
            d = load_data()
            today_day = str(datetime.date.today().day)
            if "history" not in d:
                d["history"] = {}
            d["history"][today_day] = {
                "daily": daily,
                "cash": cash,
                "wasfaty": wasfaty,
                "pharmacist": pharmacist_name,
                "time": metrics["submit_time"],
                "date": datetime.date.today().strftime("%Y-%m-%d")
            }
            save_data(d)

            # Build WhatsApp direct dispatch URL
            wa_encoded = urllib.parse.quote(metrics["whatsapp_msg"])
            wa_url = f"https://api.whatsapp.com/send?text={wa_encoded}"

            markup = types.InlineKeyboardMarkup()
            btn_wa = types.InlineKeyboardButton("📲 إرسال التقرير لجروب الواتساب الآن", url=wa_url)
            btn_dash = types.InlineKeyboardButton("📊 عرض لوحة التحكم", callback_data="refresh_dash")
            markup.add(btn_wa)
            markup.add(btn_dash)

            resp = (
                f"✅ **تم تسجيل تقرير اليوم بنجاح وحفظه سحابياً!**\n\n"
                f"```text\n{metrics['whatsapp_msg']}\n```\n\n"
                f"👇 **اضغط على الزر أدناه لإرسال التقرير مباشرة إلى جروب الواتساب:**"
            )
            bot.send_message(message.chat.id, resp, reply_markup=markup, parse_mode="Markdown")
            return
        except Exception as e:
            bot.reply_to(message, f"❌ حدث خطأ أثناء المعالجة: {str(e)}")
            return

    # Fallback instructions
    bot.reply_to(
        message,
        "💡 استخدم القائمة أدناه أو أرسل 3 أرقام مفصولة بمسافة:\n`مبيعات_اليوم الكاش وصفتي`\n(مثال: `5200 2000 1200`)",
        reply_markup=get_main_keyboard(),
        parse_mode="Markdown"
    )

# -------------------------------------------------------------
# Flask Web Routes
# -------------------------------------------------------------
@app.route("/", methods=["GET"])
def home():
    data = load_data()
    t_tot = data.get("target_total", 0)
    t_nw = data.get("target_non_wasfaty", 0)
    days_recorded = len(data.get("history", {}))
    return f"""<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
  <meta charset="utf-8">
  <title>صيدلية زهرة الروضة 103</title>
  <style>
    body {{ font-family: system-ui, -apple-system, sans-serif; background: #0f172a; color: #f8fafc; text-align: center; padding: 40px 20px; }}
    .card {{ background: #1e293b; max-width: 500px; margin: 0 auto; padding: 30px; border-radius: 16px; box-shadow: 0 10px 25px rgba(0,0,0,0.3); border: 1px solid #334155; }}
    h1 {{ color: #38bdf8; margin-bottom: 8px; font-size: 22px; }}
    .badge {{ display: inline-block; background: #059669; color: white; padding: 6px 14px; border-radius: 20px; font-weight: bold; font-size: 13px; margin: 15px 0; }}
    .stats {{ background: #0f172a; padding: 15px; border-radius: 10px; margin: 20px 0; text-align: right; font-size: 14px; }}
    .stats p {{ margin: 8px 0; }}
    a.btn {{ display: inline-block; background: #0284c7; color: white; padding: 10px 20px; border-radius: 8px; text-decoration: none; font-weight: bold; }}
  </style>
</head>
<body>
  <div class="card">
    <h1>💊 صيدلية زهرة الروضة 103</h1>
    <p>نظام تقارير المبيعات السحابي الآلي (Vercel Serverless 24/7)</p>
    <div class="badge">🟢 البوت نشط ويعمل 24/7</div>
    <div class="stats">
      <p>🎯 <b>تارجت التوتال:</b> {t_tot:,.2f} SAR</p>
      <p>💊 <b>تارجت غير وصفتي:</b> {t_nw:,.2f} SAR</p>
      <p>📅 <b>الأيام المسجلة:</b> {days_recorded} يوم</p>
    </div>
    <a class="btn" href="https://t.me/MyPharmaSalesBot" target="_blank">📲 فتح البوت في تليجرام (@MyPharmaSalesBot)</a>
  </div>
</body>
</html>"""

@app.route("/api/webhook", methods=["GET", "POST"])
def webhook():
    if request.method == "POST":
        try:
            json_str = request.get_data().decode("utf-8")
            update = types.Update.de_json(json_str)
            if update:
                bot.process_new_updates([update])
        except Exception as e:
            print("Webhook update processing error:", e)
        return "OK", 200
    return "<h3>Zahrat Alrawda 103 Webhook Endpoint is Active!</h3>", 200

@app.route("/api/reminder", methods=["GET"])
def reminder():
    data = load_data()
    now = datetime.datetime.now()
    today_day = str(now.day)

    if today_day not in data.get("history", {}):
        registered = data.get("registered_chats", [])
        if not registered:
            return jsonify({"status": "no_chats"}), 200

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
                print(f"Failed to send to {chat_id}: {e}")

        return jsonify({"status": "sent", "count": sent_count}), 200

    return jsonify({"status": "already_submitted"}), 200
