# bot.py
import os
import json
import logging
import asyncio
import threading
from datetime import datetime, timedelta
from flask import Flask, request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, ContextTypes, filters, CallbackQueryHandler
)

# إعداد السجلات
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("complaint-bot")

# إعداد Flask
app = Flask(__name__)

# متغيرات البيئة
BOT_TOKEN = os.getenv("BOT_TOKEN")
MAIN_GROUP_ID = int(os.getenv("MAIN_GROUP_ID", "0"))
ADMIN_GROUP_ID = int(os.getenv("ADMIN_GROUP_ID", "0"))
ADMIN_GROUP_TOPIC_ID = int(os.getenv("ADMIN_GROUP_TOPIC_ID", "0"))
PORT = int(os.getenv("PORT", "10000"))
WEBHOOK_PATH = f"/{BOT_TOKEN}"
WEBHOOK_URL = f"https://{os.getenv('RENDER_EXTERNAL_HOSTNAME')}{WEBHOOK_PATH}"

if not BOT_TOKEN:
    raise RuntimeError("❌ BOT_TOKEN غير موجود في متغيرات البيئة.")

# ملفات البيانات
BLOCK_FILE = "blocked_users.json"
DAILY_FILE = "daily_limit.json"
REPLY_FILE = "reply_targets.json"
MAX_CHARS = 200

# دوال المساعدة
def load_json(path):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)

def is_blocked(uid):
    data = load_json(BLOCK_FILE)
    if str(uid) in data:
        expire = datetime.fromisoformat(data[str(uid)])
        if datetime.now() < expire:
            return True
        del data[str(uid)]
        save_json(BLOCK_FILE, data)
    return False

def block_user(uid, days=7):
    data = load_json(BLOCK_FILE)
    data[str(uid)] = (datetime.now() + timedelta(days=days)).isoformat()
    save_json(BLOCK_FILE, data)

def can_send_today(uid):
    data = load_json(DAILY_FILE)
    today = datetime.now().date().isoformat()
    if data.get(str(uid)) == today:
        return False
    data[str(uid)] = today
    save_json(DAILY_FILE, data)
    return True

def save_reply(admin_id, user_id):
    data = load_json(REPLY_FILE)
    data[str(admin_id)] = user_id
    save_json(REPLY_FILE, data)

def pop_reply(admin_id):
    data = load_json(REPLY_FILE)
    if str(admin_id) in data:
        user_id = data[str(admin_id)]
        del data[str(admin_id)]
        save_json(REPLY_FILE, data)
        return user_id
    return None

# إنشاء التطبيق
application = Application.builder().token(BOT_TOKEN).build()

welcome_text = (
    f"👋 مرحبًا بك في بوت الشكاوى والمقترحات!\n\n"
    f"📢 هذا البوت مخصص لاستقبال شكاوى ومقترحات أعضاء **غرفة علي مع الحق والحق مع علي**.\n\n"
    f"💬 ملاحظات:\n"
    f"- الحد اليومي: رسالة واحدة.\n"
    f"- الحد الأقصى للأحرف: {MAX_CHARS}.\n\n"
    f"🔗 [الانضمام إلى الغرفة](https://t.me/AliwAlhaq)"
)

accept_text = "✅ تم قبول شكواك. شكرًا لتعاونك!"
reject_text = "❌ تم رفض الشكوى بعد المراجعة."

# Handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return
    uid = update.message.from_user.id
    if is_blocked(uid):
        await update.message.reply_text("⏸️ تم إيقافك مؤقتًا من إرسال الشكاوى لمدة 7 أيام.")
        return
    await update.message.reply_text(welcome_text, parse_mode="Markdown")

async def handle_private(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return

    user = update.message.from_user
    text = update.message.text.strip()

    # تحقق من أن هذا المشرف يرد على عضو
    target_id = pop_reply(user.id)
    if target_id:
        try:
            # التأكد من أن العضو يمكن التواصل معه فعليًا
            chat_info = await context.bot.get_chat(target_id)
            await context.bot.send_message(
                chat_id=target_id,
                text=f"📩 رد من الإدارة:\n\n{text}"
            )
            await update.message.reply_text("✅ تم إرسال الرد بنجاح إلى العضو.")
        except Exception as e:
            logger.error(f"❌ خطأ أثناء إرسال الرد: {e}")
            # إبلاغ المشرف بالسبب الحقيقي
            await update.message.reply_text(
                "⚠️ لم أتمكن من إرسال الرد للعضو.\n"
                "🚫 السبب المحتمل:\n"
                "- العضو غادر المحادثة مع البوت.\n"
                "- أو فعّل إعداد الخصوصية ضد الرسائل من البوتات.\n\n"
                "✅ في هذه الحالة يمكن التواصل معه يدويًا."
            )
        return

    # عضو عادي يرسل شكوى
    if is_blocked(user.id):
        await update.message.reply_text("🚫 تم إيقافك مؤقتًا من إرسال الشكاوى.")
        return

    if not can_send_today(user.id):
        await update.message.reply_text("⚠️ يمكنك إرسال رسالة واحدة فقط يوميًا.")
        return

    if len(text) > MAX_CHARS:
        await update.message.reply_text(f"⚠️ الحد الأقصى {MAX_CHARS} حرف.")
        return

    complaint = (
        f"📬 **شكوى جديدة**\n"
        f"👤 الاسم: {user.full_name}\n"
        f"🆔 ID: `{user.id}`\n"
        f"🗣️ المستخدم: @{user.username or 'بدون'}\n"
        f"💬 **النص:** {text}"
    )

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ قبول", callback_data=f"accept:{user.id}"),
            InlineKeyboardButton("❌ رفض", callback_data=f"reject:{user.id}")
        ],
        [
            InlineKeyboardButton("💬 رد", callback_data=f"reply:{user.id}"),
            InlineKeyboardButton("⏸️ إيقاف 7 أيام", callback_data=f"block:{user.id}")
        ]
    ])

    await context.bot.send_message(
        chat_id=ADMIN_GROUP_ID,
        text=complaint,
        parse_mode="Markdown",
        reply_markup=keyboard,
        message_thread_id=ADMIN_GROUP_TOPIC_ID if ADMIN_GROUP_TOPIC_ID else None
    )

    await update.message.reply_text("✅ تم إرسال شكواك إلى الإدارة. سيتم التواصل معك عند الرد.")

async def handle_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    action, uid = query.data.split(":")
    uid = int(uid)
    admin_id = query.from_user.id

    if action == "accept":
        await context.bot.send_message(uid, accept_text)
        await query.message.edit_text(query.message.text + "\n\n📢 تم القبول ✅", reply_markup=None)

    elif action == "reject":
        await context.bot.send_message(uid, reject_text)
        await query.message.edit_text(query.message.text + "\n\n📢 تم الرفض ❌", reply_markup=None)

    elif action == "block":
        block_user(uid)
        await context.bot.send_message(uid, "🚫 تم إيقافك من إرسال الشكاوى لمدة 7 أيام.")
        await query.message.edit_text(query.message.text + "\n\n⏸️ العضو موقوف 7 أيام", reply_markup=None)

    elif action == "reply":
        save_reply(admin_id, uid)
        await query.message.edit_text(
            query.message.text + "\n\n💬 أرسل الرد الآن في الخاص ليتم توجيهه للعضو.",
            reply_markup=None
        )

# Handlers
application.add_handler(CommandHandler("start", start))
application.add_handler(MessageHandler(filters.TEXT & filters.ChatType.PRIVATE, handle_private))
application.add_handler(CallbackQueryHandler(handle_buttons))

# Webhook setup
async_loop = None

def run_async_loop():
    global async_loop
    async_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(async_loop)

    async def init_app():
        await application.initialize()
        try:
            await application.bot.set_webhook(WEBHOOK_URL)
            logger.info(f"✅ تم ضبط Webhook -> {WEBHOOK_URL}")
        except Exception as ex:
            logger.warning(f"⚠️ تعذر ضبط Webhook: {ex}")
    async_loop.run_until_complete(init_app())
    async_loop.run_forever()

threading.Thread(target=run_async_loop, daemon=True).start()

@app.route(WEBHOOK_PATH, methods=["POST"])
def telegram_webhook():
    try:
        data = request.get_json(force=True)
        update = Update.de_json(data, application.bot)
        asyncio.run_coroutine_threadsafe(application.process_update(update), async_loop)
        return "ok", 200
    except Exception as e:
        logger.exception(f"Webhook Error: {e}")
        return "error", 500

if __name__ == "__main__":
    logger.info("🚀 بدأ تشغيل البوت - Webhook جاهز")
    app.run(host="0.0.0.0", port=PORT)
