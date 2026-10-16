import os
import sys
import datetime
import calendar
import urllib.parse
import re
from flask import Flask, request, jsonify
import telebot
from telebot import types

# Ensure current directory is in sys.path
CUR_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(CUR_DIR)
for p in [CUR_DIR, PARENT_DIR]:
    if p not in sys.path:
        sys.path.insert(0, p)

try:
    from db import (
        load_data, save_data, register_chat, verify_admin_pin, set_admin_pin,
        get_custody_info, save_custody_audit, set_fixed_custody_amount, replenish_custody,
        archive_and_reset_month, set_base_carryover, edit_or_delete_day, factory_reset
    )
    from logic import (
        calculate_sales_metrics, calculate_custody_audit, generate_excel_report,
        fmt, progress_bar, get_pharmacist_title
    )
except ImportError:
    from .db import (
        load_data, save_data, register_chat, verify_admin_pin, set_admin_pin,
        get_custody_info, save_custody_audit, set_fixed_custody_amount, replenish_custody,
        archive_and_reset_month, set_base_carryover, edit_or_delete_day, factory_reset
    )
    from .logic import (
        calculate_sales_metrics, calculate_custody_audit, generate_excel_report,
        fmt, progress_bar, get_pharmacist_title
    )

TOKEN = os.environ.get("TELEGRAM_TOKEN") or "8926788986:AAG4ZzgJif82hUl-BZATgV6Sbc9aDbcpO_w"
bot = telebot.TeleBot(TOKEN, threaded=False)
app = Flask(__name__)

# Temporary in-memory state tracking
user_states = {}

def get_main_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    btn_record = types.KeyboardButton("📝 تسجيل مبيعات اليوم")
    btn_custody = types.KeyboardButton("💼 جرد عهدة الصيدلية")
    btn_dash = types.KeyboardButton("📊 لوحة التحكم (Dashboard)")
    btn_target = types.KeyboardButton("🎯 أهداف الشهر والحوافز")
    btn_excel = types.KeyboardButton("📥 تحميل تقرير الإكسل")
    btn_admin = types.KeyboardButton("⚙️ إدارة النظام (Admin)")
    markup.add(btn_record, btn_custody)
    markup.add(btn_dash, btn_target)
    markup.add(btn_excel, btn_admin)
    return markup

# -------------------------------------------------------------
# Handlers: Start & Main Menu
# -------------------------------------------------------------
@bot.message_handler(commands=['start', 'menu'])
def handle_start(message):
    register_chat(message.chat.id)
    user_states.pop(message.chat.id, None)
    welcome_text = (
        "👋 **مرحباً بك في نظام إدارة ومتابعة مبيعات وعهدة صيدلية زهرة الروضة 103 💊 (Vercel Serverless 24/7)**\n\n"
        "✨ **الخدمات الرئيسية المنفصلة:**\n"
        "• 📝 **تسجيل المبيعات اليومية:** أرسل 3 أرقام (`مبيعات كاش وصفتي`)\n"
        "• 💼 **جرد عهدة الصيدلية (Petty Cash Float):** متابعة العهدة الثابتة (2,000 ريال)، فواتير المشتريات، التأمين، والكاش الفعلي المتبقي.\n"
        "• 🎯 **تتبع التارجت وحوافز الـ 85% والـ 100%:** حساب المطلوب يومياً للإغلاق.\n"
        "• ⚙️ **لوحة تحكم إدارية برمز أمان:** تصفير شهر جديد، إدخال التراكمي السابق، وتعديل أي يوم.\n\n"
        "👇 **اختر الإجراء المطلوب من القائمة أدناه:**"
    )
    bot.send_message(message.chat.id, welcome_text, reply_markup=get_main_keyboard(), parse_mode="Markdown")

# -------------------------------------------------------------
# 1. Dashboard View
# -------------------------------------------------------------
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

    # 100% Target Run-rate
    rem100_tot = max(0.0, t_tot - cum_total)
    req100_tot = rem100_tot / rem_days

    # 85% Incentives
    t85_tot = t_tot * 0.85
    rem85_tot = max(0.0, t85_tot - cum_total)
    req85_tot = rem85_tot / rem_days

    t85_nw = t_nw * 0.85
    rem85_nw = max(0.0, t85_nw - cum_nw)
    req85_nw = rem85_nw / rem_days

    # Last recorded sales info
    last_log_str = str(day_num)
    last_info = ""
    if last_log_str in data.get("history", {}):
        h = data["history"][last_log_str]
        last_info = f"✅ **آخر مبيعات مسجلة اليوم:** `{fmt(h.get('daily', 0))} SAR` بواسطة {h.get('pharmacist', 'Dr. Staff')} ({h.get('time', '')})\n"

    # Custody quick status
    c_info = get_custody_info()
    cust_status_badge = "🟢" if "مطابق" in c_info["status"] else ("🔴" if "عجز" in c_info["status"] else "🟡")

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
        f"  `{progress_bar(tot_ach)}`\n"
        f"  👈 مطلوب للـ 100%: `{fmt(rem100_tot)}` ({fmt(req100_tot)}/يوم)\n\n"
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
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💼 **حالة عهدة الفرع الثابتة (Petty Cash):**\n"
        f"• العهدة الأساسية: `{fmt(c_info['fixed_custody'])} SAR`\n"
        f"• فواتير + تأمين: `{fmt(c_info['total_documents'])} SAR`\n"
        f"• كاش فعلي متبقي: `{fmt(c_info['actual_cash'])} SAR`\n"
        f"• حالة المطابقة: {cust_status_badge} `{c_info['status']}`\n"
    )

    markup = types.InlineKeyboardMarkup()
    btn_send = types.InlineKeyboardButton("📝 تسجيل مبيعات اليوم", callback_data="start_record")
    btn_cust = types.InlineKeyboardButton("💼 جرد العهدة", callback_data="open_custody_menu")
    btn_ref = types.InlineKeyboardButton("🔄 تحديث البيانات", callback_data="refresh_dash")
    markup.add(btn_send, btn_cust)
    markup.add(btn_ref)

    bot.send_message(message.chat.id, txt, reply_markup=markup, parse_mode="Markdown")

# -------------------------------------------------------------
# 2. Petty Cash Custody Menu & Actions
# -------------------------------------------------------------
@bot.message_handler(func=lambda m: bool(m.text and ("جرد عهدة" in m.text or "العهدة" in m.text or "عهدة" in m.text)))
def show_custody_menu(message):
    register_chat(message.chat.id)
    render_custody_view(message.chat.id)

def render_custody_view(chat_id):
    c = get_custody_info()
    status_badge = "🟢" if "مطابق" in c["status"] else ("🔴" if "عجز" in c["status"] else "🟡")
    
    last_text = ""
    if c["last_audit_date"]:
        last_text = f"🕒 **آخر جرد:** {c['last_audit_date']} بواسطة {c['last_audit_pharmacist']}\n\n"

    txt = (
        f"💼 **إدارة ومطابقة عهدة الفرع المستديمة — صيدلية زهرة الروضة 103** 💊\n\n"
        f"{last_text}"
        f"💵 **مبلغ العهدة الأساسي الثابت:** `{fmt(c['fixed_custody'])} SAR`\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"🧾 **فواتير المشتريات والمصروفات:** `{fmt(c['purchases_invoices'])} SAR`\n"
        f"📋 **مبالغ التأمين / الاسترداد:** `{fmt(c['insurance_amounts'])} SAR`\n"
        f"📊 **إجمالي المستندات:** `{fmt(c['total_documents'])} SAR`\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"💰 **الكاش المفترض توفره بالدرج:** `{fmt(c['expected_cash'])} SAR`\n"
        f"💵 **الكاش الفعلي المعدود:** `{fmt(c['actual_cash'])} SAR`\n"
        f"⚖️ **حالة المطابقة:** {status_badge} **`{c['status']}`**\n\n"
        "💡 **كيفية تسجيل جرد جديد؟**\n"
        "اضغط على زر **(📝 تسجيل جرد عهدة جديد)** أو أرسل 3 أرقام مفصولة بمسافة:\n"
        "`فواتير_المشتريات مبالغ_التأمين الكاش_الفعلي_المتبقي`\n"
        "🔹 **مثال:** `450 150 1400`"
    )

    markup = types.InlineKeyboardMarkup(row_width=1)
    b_new = types.InlineKeyboardButton("📝 تسجيل جرد عهدة جديد", callback_data="cust_new_audit")
    b_wa = types.InlineKeyboardButton("📲 إرسال تقرير العهدة للواتساب", callback_data="cust_send_wa")
    b_rep = types.InlineKeyboardButton("🔄 تسوية وتعويض العهدة (Replenish)", callback_data="cust_replenish")
    markup.add(b_new, b_wa, b_rep)

    bot.send_message(chat_id, txt, reply_markup=markup, parse_mode="Markdown")

# -------------------------------------------------------------
# 3. Admin Control Panel (Protected by PIN)
# -------------------------------------------------------------
@bot.message_handler(func=lambda m: bool(m.text and ("إدارة النظام" in m.text or "Admin" in m.text or "ادارة" in m.text)))
def prompt_admin(message):
    register_chat(message.chat.id)
    user_states[message.chat.id] = "awaiting_admin_pin"
    bot.send_message(
        message.chat.id,
        "🔒 **منطقة الإدارة محمية برمز أمان**\n\n"
        "الرجاء إرسال الرمز السري للإدارة للدخول:\n"
        "*(الرمز الافتراضي: `1234`)*",
        parse_mode="Markdown"
    )

def render_admin_panel(chat_id):
    data = load_data()
    days_count = len(data.get("history", {}))
    t_tot = data.get("target_total", 0)
    t_nw = data.get("target_non_wasfaty", 0)
    base_tot = data.get("base_total_cum", 0)
    base_nw = data.get("base_wasfaty_cum", 0)
    fixed_cust = data.get("fixed_custody", 2000.0)

    txt = (
        "⚙️ **لوحة التحكم الإدارية — صيدلية زهرة الروضة 103** 💊\n\n"
        f"• أيام المبيعات المسجلة بالشهر: **{days_count} يوم**\n"
        f"• التراكمي السابق (Carryover): `{fmt(base_tot)} SAR` (وصفتي: `{fmt(base_nw)}`)\n"
        f"• مبلغ العهدة الثابتة للفرع: `{fmt(fixed_cust)} SAR`\n"
        f"• تارجت التوتال: `{fmt(t_tot)} SAR` | غير وصفتي: `{fmt(t_nw)} SAR`\n\n"
        "👇 **اختر الإجراء الإداري المطلوب:**"
    )
    markup = types.InlineKeyboardMarkup(row_width=1)
    btn_carry = types.InlineKeyboardButton("📥 إدخال التراكمي السابق (Base Carryover)", callback_data="adm_carryover")
    btn_set_cust = types.InlineKeyboardButton("💵 تعديل مبلغ العهدة الثابتة للفرع", callback_data="adm_set_fixed_cust")
    btn_edit = types.InlineKeyboardButton("✏️ تعديل أو حذف مبيعات يوم محدد", callback_data="adm_edit_day")
    btn_new_month = types.InlineKeyboardButton("🔄 بداية شهر جديد وأرشفة الشهر المنتهي", callback_data="adm_new_month")
    btn_clear = types.InlineKeyboardButton("🗑️ مسح وتصفير مبيعات الشهر الحالي", callback_data="adm_reset_req")
    btn_pin = types.InlineKeyboardButton("🔐 تغيير الرقم السري (PIN)", callback_data="adm_change_pin")
    markup.add(btn_carry, btn_set_cust, btn_edit, btn_new_month, btn_clear, btn_pin)

    bot.send_message(chat_id, txt, reply_markup=markup, parse_mode="Markdown")

# -------------------------------------------------------------
# 4. Targets & Settings
# -------------------------------------------------------------
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
        "💡 **لتعديل الأهداف أرسل:**\n"
        "`تارجت التوتال 300000` أو `تارجت غير وصفتي 250000`"
    )
    markup = types.InlineKeyboardMarkup()
    btn1 = types.InlineKeyboardButton("✏️ تعديل تارجت التوتال", callback_data="set_target_total")
    btn2 = types.InlineKeyboardButton("✏️ تعديل تارجت غير وصفتي", callback_data="set_target_nw")
    markup.add(btn1, btn2)
    bot.send_message(message.chat.id, txt, reply_markup=markup, parse_mode="Markdown")

@bot.message_handler(func=lambda m: bool(m.text and ("تحميل تقرير" in m.text or "إكسل" in m.text or "Excel" in m.text)))
def send_excel(message):
    register_chat(message.chat.id)
    bot.send_chat_action(message.chat.id, "upload_document")
    path = generate_excel_report()
    now = datetime.datetime.now()
    caption = f"📊 **تقرير مبيعات وجرد عهدة شهر {now.strftime('%B %Y')} — صيدلية زهرة الروضة 103** 💊\n*(يحتوي على شيت المبيعات اليومية + شيت جرد العهدة)*"
    with open(path, "rb") as doc:
        bot.send_document(message.chat.id, doc, caption=caption, parse_mode="Markdown")

@bot.message_handler(func=lambda m: bool(m.text and ("تسجيل مبيعات" in m.text)))
def guide_record(message):
    register_chat(message.chat.id)
    txt = (
        "📝 **تسجيل مبيعات اليوم:**\n\n"
        "⚡ **الطريقة السريعة (موصى بها):**\n"
        "أرسل الأرقام الثلاثة في رسالة واحدة مفصولة بمسافة:\n"
        "`مبيعات_اليوم الكاش وصفتي`\n\n"
        "🔹 **مثال:** `5420 2150 1200`\n\n"
        "💬 **أو اضغط على الزر أدناه للتسجيل خطوة بخطوة:**"
    )
    markup = types.InlineKeyboardMarkup()
    btn_wiz = types.InlineKeyboardButton("💬 تسجيل تفاعلي خطوة بخطوة", callback_data="start_sales_wizard")
    markup.add(btn_wiz)
    bot.send_message(message.chat.id, txt, reply_markup=markup, parse_mode="Markdown")

# -------------------------------------------------------------
# 5. Inline Callbacks Handler
# -------------------------------------------------------------
@bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(call):
    chat_id = call.message.chat.id
    register_chat(chat_id)

    if call.data == "refresh_dash":
        show_dashboard(call.message)
        bot.answer_callback_query(call.id, "تم تحديث البيانات! ✅")
    elif call.data == "start_record":
        guide_record(call.message)
        bot.answer_callback_query(call.id)
    elif call.data == "start_sales_wizard":
        user_states[chat_id] = "sales_wiz_step1"
        bot.send_message(chat_id, "1️⃣ **الخطوة الأولى:** كم إجمالي مبيعات اليوم بالريال؟ (أرسل الرقم فقط، مثال: `5420`):", parse_mode="Markdown")
        bot.answer_callback_query(call.id)
    elif call.data == "cust_wiz":
        user_states[chat_id] = "cust_wiz_step1"
        bot.send_message(chat_id, "1️⃣ **الخطوة الأولى:** كم إجمالي فواتير ومصروفات المشتريات من العهدة؟ (أرسل 0 إذا لم يوجد):", parse_mode="Markdown")
        bot.answer_callback_query(call.id)
    elif call.data == "open_custody_menu":
        render_custody_view(chat_id)
        bot.answer_callback_query(call.id)
    elif call.data == "cust_new_audit":
        user_states[chat_id] = "awaiting_custody_audit"
        bot.send_message(
            chat_id,
            "💼 **تسجيل جرد عهدة جديد:**\n\n"
            "أرسل الأرقام الثلاثة التالية مفصولة بمسافة:\n"
            "`فواتير_المشتريات مبالغ_التأمين الكاش_الفعلي_المتبقي`\n\n"
            "🔹 **مثال:**\n"
            "`450 150 1400`\n\n"
            "*(ملاحظة: إذا لم توجد مبالغ تأمين اكتب 0 مكانها)*",
            parse_mode="Markdown"
        )
        bot.answer_callback_query(call.id)
    elif call.data == "cust_send_wa":
        c = get_custody_info()
        pharm_name = get_pharmacist_title(call.from_user)
        audit_res = calculate_custody_audit(
            c["purchases_invoices"], c["insurance_amounts"], c["actual_cash"],
            pharmacist_name=pharm_name, notes=c.get("notes", "")
        )
        wa_enc = urllib.parse.quote(audit_res["whatsapp_msg"])
        wa_url = f"https://api.whatsapp.com/send?text={wa_enc}"

        markup = types.InlineKeyboardMarkup()
        btn = types.InlineKeyboardButton("📲 إرسال التقرير لجروب الواتساب الآن", url=wa_url)
        markup.add(btn)

        msg_preview = (
            f"📋 **معاينة تقرير عهدة الفرع للواتساب:**\n\n"
            f"```text\n{audit_res['whatsapp_msg']}\n```"
        )
        bot.send_message(chat_id, msg_preview, reply_markup=markup, parse_mode="Markdown")
        bot.answer_callback_query(call.id)
    elif call.data == "cust_replenish":
        pharm_name = get_pharmacist_title(call.from_user)
        rep = replenish_custody(pharmacist_name=pharm_name)
        bot.send_message(
            chat_id,
            f"🎉 **تمت تسوية وتعويض العهدة بنجاح!**\n\n"
            f"• تم تصفير الفواتير ومبالغ التأمين السابقة.\n"
            f"• الكاش الفعلي الآن بالدرج: `{fmt(rep['actual'])} SAR` (مطابق للعهدة الثابتة).\n"
            f"• المسؤول: {rep['pharmacist']}",
            parse_mode="Markdown"
        )
        render_custody_view(chat_id)
        bot.answer_callback_query(call.id)
    elif call.data == "set_target_total":
        bot.send_message(chat_id, "✏️ أرسل تارجت التوتال الجديد كالتالي:\n`تارجت التوتال 300000`", parse_mode="Markdown")
        bot.answer_callback_query(call.id)
    elif call.data == "set_target_nw":
        bot.send_message(chat_id, "✏️ أرسل تارجت غير وصفتي الجديد كالتالي:\n`تارجت غير وصفتي 250000`", parse_mode="Markdown")
        bot.answer_callback_query(call.id)
    elif call.data == "adm_carryover":
        user_states[chat_id] = "awaiting_carryover"
        bot.send_message(
            chat_id,
            "📥 **إدخال التراكمي السابق للأيام الفائتة:**\n\n"
            "أرسل رقمين مفصولين بمسافة كالتالي:\n"
            "`تراكمي_إجمالي_المبيعات تراكمي_وصفتي`\n\n"
            "🔹 **مثال:** لو مبيعات الأيام السابقة 45000 منها 12000 وصفتي:\n"
            "`45000 12000`",
            parse_mode="Markdown"
        )
        bot.answer_callback_query(call.id)
    elif call.data == "adm_set_fixed_cust":
        user_states[chat_id] = "awaiting_fixed_cust_val"
        bot.send_message(
            chat_id,
            "💵 **تعديل مبلغ العهدة الثابتة للفرع:**\n\n"
            "أرسل مبلغ العهدة الثابتة الجديد بالريال (مثال: `2500` أو `2000`):",
            parse_mode="Markdown"
        )
        bot.answer_callback_query(call.id)
    elif call.data == "adm_edit_day":
        user_states[chat_id] = "awaiting_edit_day_num"
        bot.send_message(
            chat_id,
            "✏️ **تعديل أو حذف مبيعات يوم محدد:**\n\n"
            "أرسل رقم اليوم المطلوب (مثال: `14`):",
            parse_mode="Markdown"
        )
        bot.answer_callback_query(call.id)
    elif call.data == "adm_new_month":
        markup = types.InlineKeyboardMarkup()
        b_yes = types.InlineKeyboardButton("✅ نعم، ابدأ شهراً جديداً الآن", callback_data="adm_new_month_yes")
        b_no = types.InlineKeyboardButton("❌ تراجع", callback_data="adm_cancel")
        markup.add(b_yes, b_no)
        bot.send_message(
            chat_id,
            "⚠️ **تأكيد بداية شهر جديد:**\n\n"
            "سيقوم البوت بحفظ أرشيف كامل لمبيعات الشهر المنتهي، وتصفير عداد الأيام للشهر الجديد.\n"
            "هل أنت متأكد من البدء؟",
            reply_markup=markup,
            parse_mode="Markdown"
        )
        bot.answer_callback_query(call.id)
    elif call.data == "adm_new_month_yes":
        archive_and_reset_month()
        bot.send_message(chat_id, "🎉 **تمت أرشفة الشهر المنتهي وبدء شهر جديد بنجاح!** العداد الآن 0 وجاهز لاستقبال مبيعات اليوم الأول.", parse_mode="Markdown")
        render_admin_panel(chat_id)
        bot.answer_callback_query(call.id)
    elif call.data == "adm_reset_req":
        markup = types.InlineKeyboardMarkup()
        b_yes = types.InlineKeyboardButton("🚨 نعم، امسح مبيعات الشهر", callback_data="adm_reset_yes")
        b_no = types.InlineKeyboardButton("❌ تراجع", callback_data="adm_cancel")
        markup.add(b_yes, b_no)
        bot.send_message(
            chat_id,
            "⚠️ **تحذير أمان عالي:**\n\n"
            "هل أنت متأكد من مسح جميع مبيعات الشهر الحالي وتصفيرها بالكامل؟",
            reply_markup=markup,
            parse_mode="Markdown"
        )
        bot.answer_callback_query(call.id)
    elif call.data == "adm_reset_yes":
        factory_reset()
        bot.send_message(chat_id, "🗑️ **تم مسح وتصفير جميع مبيعات الشهر الحالي بنجاح!**", parse_mode="Markdown")
        render_admin_panel(chat_id)
        bot.answer_callback_query(call.id)
    elif call.data == "adm_change_pin":
        user_states[chat_id] = "awaiting_new_pin"
        bot.send_message(chat_id, "🔐 أرسل الرقم السري الجديد للإدارة (مثال: `5566`):", parse_mode="Markdown")
        bot.answer_callback_query(call.id)
    elif call.data == "adm_cancel":
        bot.send_message(chat_id, "تم الإلغاء. العودة للقائمة الرئيسية.", reply_markup=get_main_keyboard())
        bot.answer_callback_query(call.id)

# -------------------------------------------------------------
# 6. Free Text Processor (PIN, Inputs, Numbers)
# -------------------------------------------------------------
@bot.message_handler(func=lambda m: True)
def process_text_input(message):
    chat_id = message.chat.id
    register_chat(chat_id)
    text = message.text.strip()
    state = user_states.get(chat_id)

    # 1. Admin PIN verification
    if state == "awaiting_admin_pin":
        if verify_admin_pin(text):
            user_states.pop(chat_id, None)
            bot.send_message(chat_id, "🔓 **تم تأكيد رمز الأمان بنجاح!**", parse_mode="Markdown")
            render_admin_panel(chat_id)
            return
        else:
            bot.send_message(chat_id, "❌ **رمز الأمان غير صحيح!** حاول مرة أخرى أو اكتب /menu للعودة.")
            return

    # Interactive Sales Wizard Steps
    if state == "sales_wiz_step1":
        nums = re.findall(r"[\d\.]+", text.replace(",", ""))
        if nums:
            user_states[chat_id] = f"sales_wiz_step2_{float(nums[0])}"
            bot.send_message(chat_id, "2️⃣ **الخطوة الثانية:** كم مبيعات الكاش؟ (أرسل الرقم فقط، مثال: `2150`):", parse_mode="Markdown")
            return
        else:
            bot.send_message(chat_id, "⚠️ يرجى إرسال رقم مبيعات صحيح (مثال: `5420`).")
            return

    if state and state.startswith("sales_wiz_step2_"):
        wiz_daily = float(state.split("_")[-1])
        nums = re.findall(r"[\d\.]+", text.replace(",", ""))
        if nums:
            wiz_cash = float(nums[0])
            user_states[chat_id] = f"sales_wiz_step3_{wiz_daily}_{wiz_cash}"
            bot.send_message(chat_id, "3️⃣ **الخطوة الثالثة:** كم مبيعات وصفتي حتى اليوم؟ (مثال: `1200`):", parse_mode="Markdown")
            return
        else:
            bot.send_message(chat_id, "⚠️ يرجى إرسال رقم كاش صحيح (مثال: `2150`).")
            return

    if state and state.startswith("sales_wiz_step3_"):
        parts = state.split("_")
        wiz_daily = float(parts[3])
        wiz_cash = float(parts[4])
        nums = re.findall(r"[\d\.]+", text.replace(",", ""))
        if nums:
            wiz_wasfaty = float(nums[0])
            user_states.pop(chat_id, None)
            pharm_name = get_pharmacist_title(message.from_user)
            metrics = calculate_sales_metrics(wiz_daily, wiz_cash, wiz_wasfaty, pharm_name)

            d = load_data()
            today_day = str(datetime.date.today().day)
            d["history"][today_day] = {
                "daily": wiz_daily,
                "cash": wiz_cash,
                "wasfaty": wiz_wasfaty,
                "pharmacist": pharm_name,
                "time": metrics["submit_time"],
                "date": datetime.date.today().strftime("%Y-%m-%d")
            }
            save_data(d)

            wa_enc = urllib.parse.quote(metrics["whatsapp_msg"])
            wa_url = f"https://api.whatsapp.com/send?text={wa_enc}"
            markup = types.InlineKeyboardMarkup()
            btn_wa = types.InlineKeyboardButton("📲 إرسال التقرير لجروب الواتساب الآن", url=wa_url)
            btn_dash = types.InlineKeyboardButton("📊 عرض لوحة التحكم", callback_data="refresh_dash")
            markup.add(btn_wa, btn_dash)

            resp = (
                f"✅ **تم تسجيل تقرير المبيعات بنجاح عبر المساعد التفاعلي!**\n\n"
                f"```text\n{metrics['whatsapp_msg']}\n```\n\n"
                f"👇 **اضغط أدناه لإرسال التقرير مباشرة إلى جروب الواتساب:**"
            )
            bot.send_message(chat_id, resp, reply_markup=markup, parse_mode="Markdown")
            return

    # Interactive Custody Wizard Steps
    if state == "cust_wiz_step1":
        nums = re.findall(r"[\d\.]+", text.replace(",", ""))
        if nums:
            user_states[chat_id] = f"cust_wiz_step2_{float(nums[0])}"
            bot.send_message(chat_id, "2️⃣ **الخطوة الثانية:** كم إجمالي مبالغ التأمين / الاسترداد؟ (أرسل 0 إذا لم يوجد):", parse_mode="Markdown")
            return
        else:
            bot.send_message(chat_id, "⚠️ يرجى إرسال رقم صحيح (أو 0).")
            return

    if state and state.startswith("cust_wiz_step2_"):
        wiz_inv = float(state.split("_")[-1])
        nums = re.findall(r"[\d\.]+", text.replace(",", ""))
        if nums:
            wiz_ins = float(nums[0])
            user_states[chat_id] = f"cust_wiz_step3_{wiz_inv}_{wiz_ins}"
            bot.send_message(chat_id, "3️⃣ **الخطوة الثالثة:** كم الكاش الفعلي المعدود في درج العهدة الآن؟ (مثال: `1400`):", parse_mode="Markdown")
            return
        else:
            bot.send_message(chat_id, "⚠️ يرجى إرسال رقم صحيح.")
            return

    if state and state.startswith("cust_wiz_step3_"):
        parts = state.split("_")
        wiz_inv = float(parts[3])
        wiz_ins = float(parts[4])
        nums = re.findall(r"[\d\.]+", text.replace(",", ""))
        if nums:
            wiz_act = float(nums[0])
            user_states.pop(chat_id, None)
            pharm_name = get_pharmacist_title(message.from_user)

            save_custody_audit(wiz_inv, wiz_ins, wiz_act, pharm_name)
            audit_res = calculate_custody_audit(wiz_inv, wiz_ins, wiz_act, pharm_name)

            wa_enc = urllib.parse.quote(audit_res["whatsapp_msg"])
            wa_url = f"https://api.whatsapp.com/send?text={wa_enc}"
            markup = types.InlineKeyboardMarkup()
            btn = types.InlineKeyboardButton("📲 إرسال تقرير العهدة للواتساب الآن", url=wa_url)
            btn_menu = types.InlineKeyboardButton("💼 فتح قائمة العهدة", callback_data="open_custody_menu")
            markup.add(btn, btn_menu)

            resp = (
                f"✅ **تم تسجيل وتدقيق عهدة الفرع بنجاح!**\n\n"
                f"```text\n{audit_res['whatsapp_msg']}\n```\n\n"
                f"👇 **اضغط أدناه لإرسال تقرير العهدة مباشرة إلى جروب الواتساب:**"
            )
            bot.send_message(chat_id, resp, reply_markup=markup, parse_mode="Markdown")
            return

    # 2. Awaiting Fixed Custody Amount
    if state == "awaiting_fixed_cust_val":
        nums = re.findall(r"[\d\.]+", text.replace(",", ""))
        if nums:
            new_val = float(nums[0])
            set_fixed_custody_amount(new_val)
            user_states.pop(chat_id, None)
            bot.send_message(chat_id, f"✅ **تم تحديث مبلغ العهدة الأساسي للفرع إلى:** `{fmt(new_val)} SAR`", parse_mode="Markdown")
            render_admin_panel(chat_id)
            return
        else:
            bot.send_message(chat_id, "⚠️ يرجى إرسال مبلغ صحيح بالأرقام.")
            return

    # 3. Awaiting Custody Audit Inputs (invoices insurance actual)
    if state == "awaiting_custody_audit":
        nums = re.findall(r"[\d\.]+", text.replace(",", ""))
        if len(nums) >= 3:
            invoices = float(nums[0])
            insurance = float(nums[1])
            actual = float(nums[2])
            pharm_name = get_pharmacist_title(message.from_user)

            save_custody_audit(invoices, insurance, actual, pharm_name)
            audit_res = calculate_custody_audit(invoices, insurance, actual, pharm_name)
            user_states.pop(chat_id, None)

            wa_enc = urllib.parse.quote(audit_res["whatsapp_msg"])
            wa_url = f"https://api.whatsapp.com/send?text={wa_enc}"

            markup = types.InlineKeyboardMarkup()
            btn = types.InlineKeyboardButton("📲 إرسال تقرير العهدة للواتساب الآن", url=wa_url)
            btn_menu = types.InlineKeyboardButton("💼 فتح قائمة العهدة", callback_data="open_custody_menu")
            markup.add(btn)
            markup.add(btn_menu)

            resp = (
                f"✅ **تم تسجيل وتدقيق عهدة الفرع بنجاح!**\n\n"
                f"```text\n{audit_res['whatsapp_msg']}\n```\n\n"
                f"👇 **اضغط أدناه لإرسال تقرير العهدة مباشرة إلى جروب الواتساب:**"
            )
            bot.send_message(chat_id, resp, reply_markup=markup, parse_mode="Markdown")
            return
        else:
            bot.send_message(chat_id, "💡 يرجى إرسال 3 أرقام مفصولة بمسافة:\n`فواتير_المشتريات مبالغ_التأمين الكاش_الفعلي_المتبقي`\n🔹 **مثال:** `450 150 1400`")
            return

    # 4. Awaiting Carryover (Base cum)
    if state == "awaiting_carryover":
        nums = re.findall(r"[\d\.]+", text.replace(",", ""))
        if len(nums) >= 2:
            base_tot = float(nums[0])
            base_w = float(nums[1])
            set_base_carryover(base_tot, base_w)
            user_states.pop(chat_id, None)
            bot.send_message(
                chat_id,
                f"✅ **تم تسجيل التراكمي السابق بنجاح!**\n"
                f"• إجمالي المبيعات السابقة: `{fmt(base_tot)} SAR`\n"
                f"• وصفتي السابقة: `{fmt(base_w)} SAR`\n\n"
                f"سيتم احتساب هذا التراكمي في كل حسابات الشهر تلقائياً.",
                parse_mode="Markdown"
            )
            render_admin_panel(chat_id)
            return
        else:
            bot.send_message(chat_id, "💡 يرجى إرسال رقمين مفصولين بمسافة: `تراكمي_المبيعات تراكمي_وصفتي`")
            return

    # 5. Awaiting New PIN
    if state == "awaiting_new_pin":
        new_pin = text.strip()
        if len(new_pin) >= 4:
            set_admin_pin(new_pin)
            user_states.pop(chat_id, None)
            bot.send_message(chat_id, f"✅ **تم تغيير رمز الأمان بنجاح إلى:** `{new_pin}`", parse_mode="Markdown")
            render_admin_panel(chat_id)
            return
        else:
            bot.send_message(chat_id, "⚠️ يجب أن يتكون الرمز السري من 4 أرقام على الأقل. أرسل رمزاً جديداً:")
            return

    # 6. Awaiting Edit Day Number
    if state == "awaiting_edit_day_num":
        nums = re.findall(r"\d+", text)
        if nums:
            target_day = int(nums[0])
            user_states[chat_id] = f"editing_day_{target_day}"
            data = load_data()
            d_str = str(target_day)
            existing = data.get("history", {}).get(d_str)
            cur_txt = ""
            if existing:
                cur_txt = f"البيانات الحالية ليوم {target_day}:\nمبيعات: `{fmt(existing.get('daily'))}` | كاش: `{fmt(existing.get('cash'))}` | وصفتي: `{fmt(existing.get('wasfaty'))}`\n\n"

            bot.send_message(
                chat_id,
                f"📅 **تعديل مبيعات يوم {target_day}:**\n\n"
                f"{cur_txt}"
                f"• لتعديل الأرقام: أرسل الأرقام الجديدة:\n`مبيعات كاش وصفتي`\n"
                f"• لحذف يوم {target_day} تماماً: اكتب كلمة `حذف`",
                parse_mode="Markdown"
            )
            return

    # 7. Handling Day Update or Delete
    if state and state.startswith("editing_day_"):
        target_day = int(state.split("_")[-1])
        if text == "حذف":
            edit_or_delete_day(target_day, None)
            user_states.pop(chat_id, None)
            bot.send_message(chat_id, f"✅ **تم حذف مبيعات يوم {target_day} بالكامل.**", parse_mode="Markdown")
            render_admin_panel(chat_id)
            return
        else:
            nums = re.findall(r"[\d\.]+", text.replace(",", ""))
            if len(nums) >= 3:
                daily = float(nums[0])
                cash = float(nums[1])
                wasfaty = float(nums[2])

                pharmacist_name = get_pharmacist_title(message.from_user)
                metrics = calculate_sales_metrics(daily, cash, wasfaty, pharmacist_name, day_num=target_day)

                new_rec = {
                    "daily": daily,
                    "cash": cash,
                    "wasfaty": wasfaty,
                    "pharmacist": pharmacist_name,
                    "time": metrics["submit_time"],
                    "date": datetime.date.today().strftime("%Y-%m-%d")
                }
                edit_or_delete_day(target_day, new_rec)
                user_states.pop(chat_id, None)
                bot.send_message(chat_id, f"✅ **تم تحديث بيانات يوم {target_day} بنجاح!**", parse_mode="Markdown")
                render_admin_panel(chat_id)
                return

    # 8. Target updates via text
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

    # 9. Daily Sales Recording (3 numbers)
    raw_numbers = re.findall(r"[\d\.]+", text.replace(",", ""))
    if len(raw_numbers) >= 3:
        try:
            daily = float(raw_numbers[0])
            cash = float(raw_numbers[1])
            wasfaty = float(raw_numbers[2])

            pharmacist_name = get_pharmacist_title(message.from_user)
            metrics = calculate_sales_metrics(daily, cash, wasfaty, pharmacist_name)

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
                f"✅ **تم تسجيل تقرير مبيعات اليوم بنجاح وحفظه سحابياً!**\n\n"
                f"```text\n{metrics['whatsapp_msg']}\n```\n\n"
                f"👇 **اضغط على الزر أدناه لإرسال التقرير مباشرة إلى جروب الواتساب:**"
            )
            bot.send_message(chat_id, resp, reply_markup=markup, parse_mode="Markdown")
            return
        except Exception as e:
            bot.reply_to(message, f"❌ حدث خطأ أثناء المعالجة: {str(e)}")
            return

    # Fallback instructions
    bot.reply_to(
        message,
        "💡 استخدم القائمة أدناه أو أرسل:\n"
        "• للمبيعات: `مبيعات كاش وصفتي` (مثال: `5200 2000 1200`)\n"
        "• لجرد العهدة: اضغط على زر **(💼 جرد عهدة الصيدلية)**",
        reply_markup=get_main_keyboard(),
        parse_mode="Markdown"
    )

# -------------------------------------------------------------
# 7. Flask Web Routes (Vercel Serverless)
# -------------------------------------------------------------
def get_home_html():
    data = load_data()
    t_tot = data.get("target_total", 0)
    t_nw = data.get("target_non_wasfaty", 0)
    days_recorded = len(data.get("history", {}))
    c = get_custody_info()
    return f"""<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
  <meta charset="utf-8">
  <title>صيدلية زهرة الروضة 103</title>
  <style>
    body {{ font-family: system-ui, -apple-system, sans-serif; background: #0f172a; color: #f8fafc; text-align: center; padding: 40px 20px; }}
    .card {{ background: #1e293b; max-width: 520px; margin: 0 auto; padding: 30px; border-radius: 16px; box-shadow: 0 10px 25px rgba(0,0,0,0.3); border: 1px solid #334155; }}
    h1 {{ color: #38bdf8; margin-bottom: 8px; font-size: 22px; }}
    .badge {{ display: inline-block; background: #059669; color: white; padding: 6px 14px; border-radius: 20px; font-weight: bold; font-size: 13px; margin: 15px 0; }}
    .stats {{ background: #0f172a; padding: 15px; border-radius: 10px; margin: 20px 0; text-align: right; font-size: 14px; }}
    .stats p {{ margin: 8px 0; }}
    a.btn {{ display: inline-block; background: #0284c7; color: white; padding: 10px 20px; border-radius: 8px; text-decoration: none; font-weight: bold; margin: 5px; }}
  </style>
</head>
<body>
  <div class="card">
    <h1>💊 صيدلية زهرة الروضة 103</h1>
    <p>نظام تقارير المبيعات وجرد عهدة الفرع السحابي (Vercel Serverless 24/7)</p>
    <div class="badge">🟢 البوت نشط ويعمل 24/7</div>
    <div class="stats">
      <p>🎯 <b>تارجت التوتال:</b> {t_tot:,.2f} SAR</p>
      <p>💊 <b>تارجت غير وصفتي:</b> {t_nw:,.2f} SAR</p>
      <p>📅 <b>أيام المبيعات المسجلة:</b> {days_recorded} يوم</p>
      <p>💼 <b>العهدة الثابتة للفرع:</b> {c['fixed_custody']:,.2f} SAR ({c['status']})</p>
      <p>🔒 <b>قفل الإدارة برقم سري:</b> مفعّل</p>
    </div>
    <a class="btn" href="https://t.me/MyPharmaSalesBot" target="_blank">📲 فتح البوت في تليجرام (@MyPharmaSalesBot)</a>
  </div>
</body>
</html>"""

def handle_webhook_logic():
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

def handle_reminder_logic():
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
        b_cst = types.InlineKeyboardButton("💼 جرد عهدة الصيدلية", callback_data="open_custody_menu")
        markup.add(b_rec, b_cst)

        sent_count = 0
        for chat_id in registered:
            try:
                bot.send_message(chat_id, reminder_text, reply_markup=markup, parse_mode="Markdown")
                sent_count += 1
            except Exception as e:
                print(f"Failed to send to {chat_id}: {e}")

        return jsonify({"status": "sent", "count": sent_count}), 200

    return jsonify({"status": "already_submitted"}), 200

@app.route("/", defaults={"path": ""}, methods=["GET", "POST"])
@app.route("/<path:path>", methods=["GET", "POST"])
def master_router(path):
    if request.method == "POST":
        return handle_webhook_logic()

    req_url = request.url.lower()
    req_path = path.lower()
    if "reminder" in req_url or "reminder" in req_path:
        return handle_reminder_logic()

    return get_home_html()
