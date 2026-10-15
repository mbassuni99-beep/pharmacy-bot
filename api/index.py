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
        archive_and_reset_month, set_base_carryover, edit_or_delete_day, factory_reset
    )
    from logic import calculate_metrics, generate_excel_report, fmt, progress_bar, get_pharmacist_title
except ImportError:
    from .db import (
        load_data, save_data, register_chat, verify_admin_pin, set_admin_pin,
        archive_and_reset_month, set_base_carryover, edit_or_delete_day, factory_reset
    )
    from .logic import calculate_metrics, generate_excel_report, fmt, progress_bar, get_pharmacist_title

TOKEN = os.environ.get("TELEGRAM_TOKEN") or "8926788986:AAG4ZzgJif82hUl-BZATgV6Sbc9aDbcpO_w"
bot = telebot.TeleBot(TOKEN, threaded=False)
app = Flask(__name__)

# Temporary in-memory state tracking
user_states = {}

def get_main_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    btn_record = types.KeyboardButton("📝 تسجيل مبيعات اليوم")
    btn_drawer = types.KeyboardButton("💵 جرد عهدة الدرج والكاش")
    btn_dash = types.KeyboardButton("📊 لوحة التحكم (Dashboard)")
    btn_target = types.KeyboardButton("🎯 أهداف الشهر والحوافز")
    btn_excel = types.KeyboardButton("📥 تحميل تقرير الإكسل")
    btn_admin = types.KeyboardButton("⚙️ إدارة النظام (Admin)")
    markup.add(btn_record, btn_drawer)
    markup.add(btn_dash, btn_target)
    markup.add(btn_excel, btn_admin)
    return markup

# -------------------------------------------------------------
# Handlers: Start & Menu
# -------------------------------------------------------------
@bot.message_handler(commands=['start', 'menu'])
def handle_start(message):
    register_chat(message.chat.id)
    user_states.pop(message.chat.id, None)
    welcome_text = (
        "👋 **مرحباً بك في نظام إدارة ومتابعة مبيعات صيدلية زهرة الروضة 103 💊 (Vercel Serverless 24/7)**\n\n"
        "✨ **المميزات المتكاملة:**\n"
        "• 📝 **تسجيل المبيعات السريع:** أرسل 3 أرقام (`مبيعات كاش وصفتي`)\n"
        "• 💵 **جرد عهدة الدرج:** تتبع فواتير المشتريات، الكاش الفعلي، وحساب العجز أو الزيادة تلقائياً.\n"
        "• 🎯 **تتبع التارجت وحوافز الـ 85% والـ 100%:** حساب المطلوب يومياً بدقة.\n"
        "• ⚙️ **لوحة تحكم إدارية برمز سري:** تصفير شهر جديد، إدخال التراكمي السابق، وتعديل أي يوم.\n"
        "• ⏰ **منبه آلي يومي للشفت** عند الساعة 11:30 PM.\n\n"
        "👇 **اختر الإجراء المطلوب من القائمة أدناه:**"
    )
    bot.send_message(message.chat.id, welcome_text, reply_markup=get_main_keyboard(), parse_mode="Markdown")

# -------------------------------------------------------------
# Dashboard View
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

    # Last recorded info & drawer
    last_log_str = str(day_num)
    last_info = ""
    if last_log_str in data.get("history", {}):
        h = data["history"][last_log_str]
        drawer_txt = f" | عهدة: `{h.get('drawer_status', 'مطابق')}`" if h.get("drawer_status") else ""
        last_info = f"✅ **آخر تسجيل اليوم:** `{fmt(h.get('daily', 0))} SAR` بواسطة {h.get('pharmacist', 'Dr. Staff')} ({h.get('time', '')}){drawer_txt}\n"

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
    )

    markup = types.InlineKeyboardMarkup()
    btn_send = types.InlineKeyboardButton("📝 تسجيل مبيعات اليوم", callback_data="start_record")
    btn_drawer = types.InlineKeyboardButton("💵 جرد عهدة الدرج", callback_data="start_drawer")
    btn_ref = types.InlineKeyboardButton("🔄 تحديث البيانات", callback_data="refresh_dash")
    markup.add(btn_send, btn_drawer)
    markup.add(btn_ref)

    bot.send_message(message.chat.id, txt, reply_markup=markup, parse_mode="Markdown")

# -------------------------------------------------------------
# Drawer Reconciliation Guide
# -------------------------------------------------------------
@bot.message_handler(func=lambda m: bool(m.text and ("جرد عهدة" in m.text or "الدرج" in m.text)))
def guide_drawer(message):
    register_chat(message.chat.id)
    txt = (
        "💵 **جرد عهدة الدرج والمبيعات بالتفصيل 📋**\n\n"
        "يمكنك إرسال 5 أرقام مفصولة بمسافة في رسالة واحدة كالتالي:\n"
        "`مبيعات_اليوم الكاش وصفتي فواتير_الدرج الكاش_الفعلي`\n\n"
        "🔹 **مثال توضيحي:**\n"
        "`5420 2150 1200 150 2000`\n\n"
        "**تفسير الأرقام في المثال أعلاه:**\n"
        "• 5420 = إجمالي مبيعات اليوم\n"
        "• 2150 = مبيعات الكاش\n"
        "• 1200 = مبيعات وصفتي\n"
        "• 150 = فواتير مشتريات ومصروفات مدفوعة من الدرج\n"
        "• 2000 = الكاش الفعلي المعدود في الدرج عند التسليم\n\n"
        "👈 وسيقوم البوت تلقائياً بحساب:\n"
        "(الكاش المفترض توفره = 2150 - 150 = 2000)\n"
        "ومطابقة الكاش الفعلي لإظهار العجز أو الزيادة فوراً في تقرير الواتساب!"
    )
    bot.send_message(message.chat.id, txt, parse_mode="Markdown")

# -------------------------------------------------------------
# Admin Control Panel (Protected by PIN)
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

    txt = (
        "⚙️ **لوحة التحكم الإدارية — صيدلية زهرة الروضة 103** 💊\n\n"
        f"• عدد الأيام المسجلة بالشهر الحالي: **{days_count} يوم**\n"
        f"• التراكمي السابق (Base Carryover): `{fmt(base_tot)} SAR` (وصفتي: `{fmt(base_nw)}`)\n"
        f"• تارجت التوتال: `{fmt(t_tot)} SAR` | غير وصفتي: `{fmt(t_nw)} SAR`\n\n"
        "👇 **اختر الإجراء الإداري المطلوب:**"
    )
    markup = types.InlineKeyboardMarkup(row_width=1)
    btn_carry = types.InlineKeyboardButton("📥 إدخال التراكمي السابق (Base Carryover)", callback_data="adm_carryover")
    btn_edit = types.InlineKeyboardButton("✏️ تعديل أو حذف مبيعات يوم محدد", callback_data="adm_edit_day")
    btn_new_month = types.InlineKeyboardButton("🔄 بداية شهر جديد وأرشفة الشهر المنتهي", callback_data="adm_new_month")
    btn_clear = types.InlineKeyboardButton("🗑️ مسح وتصفير بيانات الشهر الحالي", callback_data="adm_reset_req")
    btn_pin = types.InlineKeyboardButton("🔐 تغيير الرقم السري (PIN)", callback_data="adm_change_pin")
    markup.add(btn_carry, btn_edit, btn_new_month, btn_clear, btn_pin)

    bot.send_message(chat_id, txt, reply_markup=markup, parse_mode="Markdown")

# -------------------------------------------------------------
# Targets & Settings
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
    caption = f"📊 **تقرير مبيعات وجرد عهدة شهر {now.strftime('%B %Y')} — صيدلية زهرة الروضة 103** 💊"
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

# -------------------------------------------------------------
# Inline Callbacks Handler
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
    elif call.data == "start_drawer":
        guide_drawer(call.message)
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
        user_states[chat_id] = "awaiting_new_month_confirm"
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
        b_yes = types.InlineKeyboardButton("🚨 نعم، امسح كل بيانات الشهر", callback_data="adm_reset_yes")
        b_no = types.InlineKeyboardButton("❌ تراجع", callback_data="adm_cancel")
        markup.add(b_yes, b_no)
        bot.send_message(
            chat_id,
            "⚠️ **تحذير أمان عالي:**\n\n"
            "هل أنت متأكد من مسح جميع بيانات ومبيعات الشهر الحالي وتصفيرها بالكامل؟",
            reply_markup=markup,
            parse_mode="Markdown"
        )
        bot.answer_callback_query(call.id)
    elif call.data == "adm_reset_yes":
        factory_reset()
        bot.send_message(chat_id, "🗑️ **تم مسح وتصفير جميع بيانات الشهر الحالي بنجاح!**", parse_mode="Markdown")
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
# Free Text Processor (PIN, Inputs, Numbers)
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

    # 2. Awaiting Carryover (Base cum)
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
                f"سيتم احتساب هذا التراكمي في كل التقارير تلقائياً.",
                parse_mode="Markdown"
            )
            render_admin_panel(chat_id)
            return
        else:
            bot.send_message(chat_id, "💡 يرجى إرسال رقمين مفصولين بمسافة: `تراكمي_المبيعات تراكمي_وصفتي`")
            return

    # 3. Awaiting New PIN
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

    # 4. Awaiting Edit Day Number
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
                f"📅 **تعديل يوم {target_day}:**\n\n"
                f"{cur_txt}"
                f"• لتعديل الأرقام: أرسل الأرقام الجديدة:\n`مبيعات كاش وصفتي` أو `مبيعات كاش وصفتي مصاريف كاش_فعلي`\n"
                f"• لحذف يوم {target_day} تماماً: اكتب كلمة `حذف`",
                parse_mode="Markdown"
            )
            return

    # 5. Handling Day Update or Delete
    if state and state.startswith("editing_day_"):
        target_day = int(state.split("_")[-1])
        if text == "حذف":
            edit_or_delete_day(target_day, None)
            user_states.pop(chat_id, None)
            bot.send_message(chat_id, f"✅ **تم حذف بيانات يوم {target_day} بالكامل.**", parse_mode="Markdown")
            render_admin_panel(chat_id)
            return
        else:
            nums = re.findall(r"[\d\.]+", text.replace(",", ""))
            if len(nums) >= 3:
                daily = float(nums[0])
                cash = float(nums[1])
                wasfaty = float(nums[2])
                expenses = float(nums[3]) if len(nums) >= 4 else 0.0
                actual_cash = float(nums[4]) if len(nums) >= 5 else None

                pharmacist_name = get_pharmacist_title(message.from_user)
                metrics = calculate_metrics(daily, cash, wasfaty, pharmacist_name, day_num=target_day, expenses=expenses, actual_cash=actual_cash)
                
                new_rec = {
                    "daily": daily,
                    "cash": cash,
                    "wasfaty": wasfaty,
                    "expenses": expenses,
                    "actual_cash": metrics["actual_cash"],
                    "drawer_status": metrics["drawer_status"],
                    "pharmacist": pharmacist_name,
                    "time": metrics["submit_time"],
                    "date": datetime.date.today().strftime("%Y-%m-%d")
                }
                edit_or_delete_day(target_day, new_rec)
                user_states.pop(chat_id, None)
                bot.send_message(chat_id, f"✅ **تم تحديث بيانات يوم {target_day} بنجاح!**", parse_mode="Markdown")
                render_admin_panel(chat_id)
                return

    # 6. Target updates via text
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

    # 7. Sales & Cash Drawer Recording (3 or 5 numbers)
    raw_numbers = re.findall(r"[\d\.]+", text.replace(",", ""))
    if len(raw_numbers) >= 3:
        try:
            daily = float(raw_numbers[0])
            cash = float(raw_numbers[1])
            wasfaty = float(raw_numbers[2])
            expenses = float(raw_numbers[3]) if len(raw_numbers) >= 4 else 0.0
            actual_cash = float(raw_numbers[4]) if len(raw_numbers) >= 5 else None

            # Sanity Warning for extreme outliers
            if daily > 50000.0 or daily < 50.0:
                pass  # accepted, but could be flagged if needed

            pharmacist_name = get_pharmacist_title(message.from_user)
            metrics = calculate_metrics(daily, cash, wasfaty, pharmacist_name, expenses=expenses, actual_cash=actual_cash)

            # Persist to database
            d = load_data()
            today_day = str(datetime.date.today().day)
            if "history" not in d:
                d["history"] = {}
            d["history"][today_day] = {
                "daily": daily,
                "cash": cash,
                "wasfaty": wasfaty,
                "expenses": expenses,
                "actual_cash": metrics["actual_cash"],
                "drawer_status": metrics["drawer_status"],
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
                f"✅ **تم تسجيل تقرير اليوم وعُهدة الدرج بنجاح!**\n\n"
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
        "• للمبيعات السريعة: `مبيعات كاش وصفتي` (مثال: `5200 2000 1200`)\n"
        "• لجرد الدرج بالتفصيل: `مبيعات كاش وصفتي مصاريف كاش_فعلي` (مثال: `5200 2000 1200 150 1850`)",
        reply_markup=get_main_keyboard(),
        parse_mode="Markdown"
    )

# -------------------------------------------------------------
# Flask Web Routes
# -------------------------------------------------------------
def get_home_html():
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
    .card {{ background: #1e293b; max-width: 520px; margin: 0 auto; padding: 30px; border-radius: 16px; box-shadow: 0 10px 25px rgba(0,0,0,0.3); border: 1px solid #334155; }}
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
    <p>نظام تقارير المبيعات وجرد عهدة الدرج السحابي (Vercel Serverless 24/7)</p>
    <div class="badge">🟢 البوت نشط ويعمل 24/7</div>
    <div class="stats">
      <p>🎯 <b>تارجت التوتال:</b> {t_tot:,.2f} SAR</p>
      <p>💊 <b>تارجت غير وصفتي:</b> {t_nw:,.2f} SAR</p>
      <p>📅 <b>الأيام المسجلة:</b> {days_recorded} يوم</p>
      <p>🔒 <b>الرقم السري للإدارة:</b> مفعّل</p>
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
            "دكتور، لم يتم تسجيل مبيعات اليوم وجرد الدرج حتى الآن!\n"
            "يرجى فتح البوت وتسجيل الأرقام وإرسال التقرير لجروب الواتساب قبل إغلاق الشفت 📝"
        )
        markup = types.InlineKeyboardMarkup()
        b_rec = types.InlineKeyboardButton("📝 تسجيل مبيعات اليوم", callback_data="start_record")
        b_drw = types.InlineKeyboardButton("💵 جرد عهدة الدرج", callback_data="start_drawer")
        markup.add(b_rec, b_drw)

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
