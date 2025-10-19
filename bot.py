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

app = Flask(__name__)

# المتغيرات
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("❌ BOT_TOKEN غير موجود.")

ADMIN_GROUP_ID = int(os.getenv("ADMIN_GROUP_ID"))
ADMIN_GROUP_TOPIC_ID = int(os.getenv("ADMIN_GROUP_TOPIC_ID", "0"))
PORT = int(os.getenv("PORT", "10000"))
HOSTNAME = os.getenv("RENDER_EXTERNAL_HOSTNAME")
WEBHOOK_PATH = f"/{BOT_TOKEN}"
WEBHOOK_URL = f"https://{HOSTNAME}{WEBHOOK_PATH}" if HOSTNAME else None
MAX_CHAR = 200

# ملفات البيانات
BLOCK_FILE = "blocked_users.json"
DAILY_FILE = "daily_users.json"
REPLY_FILE = "reply_targets.json"  # الملف الجديد لتخزين الردود

# دوال مساعدة
def load_json(path):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)

def is_blocked(user_id):
    data = load_json(BLOCK_FILE)
    if str(user_id) in data:
        expire = datetime.fromisoformat(data[str(user_id)])
        if datetime.now() < expire:
            return True
        else:
            del data[str(user_id)]
            save_json(BLOCK_FILE, data)
    return False

def block_user(user_id, days=7):
    data = load_json(BLOCK_FILE)
    data[str(user_id)] = (datetime.now() + timedelta(days=days)).isoformat()
    save_json(BLOCK_FILE, data)

def can_send_today(user_id):
    data = load_json(DAILY_FILE)
    today = datetime.now().date().isoformat()
    if str(user_id) in data and data[str(user_id)] == today:
        return False
    data[str(user_id)] = today
    save_json(DAILY_FILE, data)
    return True

def get_reply_targets():
    return load_json(REPLY_FILE)

def set_reply_target(admin_id, user_id):
    data = load_json(REPLY_FILE)
    data[str(admin_id)] = user_id
    save_json(REPLY_FILE, data)

def pop_reply_target(admin_id):
    data = load_json(REPLY_FILE)
    target = data.pop(str(admin_id), None)
    save_json(REPLY_FILE, data)
    return target

# إنشاء التطبيق
application = Application.builder().token(BOT_TOKEN).build()

# أوامر البداية
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return
    welcome = (
        "👋 مرحبًا! هذا البوت لاستقبال شكاوى ومقترحات أعضاء غرفة علي مع الحق.\n\n"
        "📩 يمكنك إرسال شكوى واحدة يوميًا.\n"
        "✍️ الحد الأقصى للأحرف: 200\n"
        "📂 يمكن للإدارة مراجعة الشكاوى في موضوع (الشكاوي والمقترحات).\n"
        "🔗 الغرفة: @AliwAlhaq"
    )
    await update.message.reply_text(welcome)

# استقبال الشكوى
async def handle_private(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return
    user = update.effective_user
    text = (update.message.text or "").strip()
    if not text:
        return

    # تحقق هل هذا رد من مشرف
    reply_targets = get_reply_targets()
    if str(user.id) in reply_targets:
        target_id = reply_targets[str(user.id)]
        pop_reply_target(user.id)
        try:
            await context.bot.send_message(chat_id=target_id, text=f"📩 رد من الإدارة:\n\n{text}")
            await update.message.reply_text("✅ تم إرسال الرد إلى العضو.")
        except Exception as e:
            await update.message.reply_text("⚠️ لم أستطع إرسال الرد، ربما العضو لم يبدأ محادثة مع البوت.")
            logger.warning(f"رد فشل إلى {target_id}: {e}")
        return

    # تحقق من الحظر والحد اليومي
    if is_blocked(user.id):
        await update.message.reply_text("⏸️ تم إيقافك من إرسال الشكاوى مؤقتًا.")
        return
    if not can_send_today(user.id):
        await update.message.reply_text("⚠️ يمكنك إرسال رسالة واحدة يوميًا فقط.")
        return
    if len(text) > MAX_CHAR:
        await update.message.reply_text(f"⚠️ الحد الأقصى هو {MAX_CHAR} حرفًا.")
        return

    msg = (
        f"📬 **شكوى جديدة**\n"
        f"👤 الاسم: {user.full_name}\n"
        f"🆔 `{user.id}`\n"
        f"🗣️ المستخدم: @{user.username if user.username else 'بدون'}\n"
        f"💬 النص:\n{text}"
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
        text=msg,
        parse_mode="Markdown",
        reply_markup=keyboard,
        message_thread_id=ADMIN_GROUP_TOPIC_ID if ADMIN_GROUP_TOPIC_ID else None
    )
    await update.message.reply_text("✅ تم إرسال شكواك إلى الإدارة.")

# التعامل مع الأزرار
async def handle_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    action, user_id = query.data.split(":")
    user_id = int(user_id)

    if action == "reply":
        set_reply_target(query.from_user.id, user_id)
        await query.edit_message_text(query.message.text + "\n\n💬 أرسل الرد الآن في الخاص ليصل للعضو.")
        try:
            await context.bot.send_message(chat_id=query.from_user.id, text="📩 أرسل الرد هنا ليُرسل للعضو.")
        except:
            pass
        return

    elif action == "block":
        block_user(user_id)
        await query.edit_message_text(query.message.text + "\n\n🚫 تم إيقاف العضو 7 أيام.")
        return

    elif action == "accept":
        await context.bot.send_message(chat_id=user_id, text="✅ تم قبول شكواك. شكرًا لتعاونك.")
        await query.edit_message_text(query.message.text + "\n\n✅ تم القبول.")
        return

    elif action == "reject":
        await context.bot.send_message(chat_id=user_id, text="❌ تم رفض الشكوى بعد المراجعة.")
        await query.edit_message_text(query.message.text + "\n\n❌ تم الرفض.")
        return

# Flask Webhook
@app.route(WEBHOOK_PATH, methods=["POST"])
def webhook():
    update = Update.de_json(request.get_json(force=True), application.bot)
    asyncio.run_coroutine_threadsafe(application.process_update(update), loop)
    return "ok"

# تشغيل التطبيق
loop = None
def start_bot():
    global loop
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    async def init():
        await application.initialize()
        if WEBHOOK_URL:
            await application.bot.set_webhook(WEBHOOK_URL)
            logger.info(f"✅ Webhook set to {WEBHOOK_URL}")
    loop.run_until_complete(init())
    loop.run_forever()

threading.Thread(target=start_bot, daemon=True).start()

application.add_handler(CommandHandler("start", start))
application.add_handler(MessageHandler(filters.TEXT & filters.ChatType.PRIVATE, handle_private))
application.add_handler(CallbackQueryHandler(handle_buttons))

if __name__ == "__main__":
    logger.info("🚀 البوت يعمل الآن (Webhook mode)")
    app.run(host="0.0.0.0", port=PORT)
