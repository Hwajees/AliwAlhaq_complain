# bot.py
import os
import json
import logging
import asyncio
import threading
from flask import Flask, request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, ContextTypes, filters, CallbackQueryHandler
)

# ------ إعداد السجلات ------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("complaint-bot")

# ------ إعداد Flask ------
app = Flask(__name__)

# ------ متغيرات البيئة ------
BOT_TOKEN = os.getenv("BOT_TOKEN")
MAIN_GROUP_ID = int(os.getenv("MAIN_GROUP_ID"))
ADMIN_GROUP_ID = int(os.getenv("ADMIN_GROUP_ID"))
ADMIN_GROUP_TOPIC_ID = int(os.getenv("ADMIN_GROUP_TOPIC_ID", "0"))
PORT = int(os.getenv("PORT", "10000"))
WEBHOOK_PATH = f"/{BOT_TOKEN}"
WEBHOOK_URL = f"https://{os.getenv('RENDER_EXTERNAL_HOSTNAME')}{WEBHOOK_PATH}"

if not BOT_TOKEN:
    raise RuntimeError("❌ BOT_TOKEN غير موجود في متغيرات البيئة.")

# ------ ملف الموقوفين ------
BLOCK_FILE = "blocked_users.json"

def load_blocked():
    if os.path.exists(BLOCK_FILE):
        with open(BLOCK_FILE, "r") as f:
            return json.load(f)
    return {}

def save_blocked(data):
    with open(BLOCK_FILE, "w") as f:
        json.dump(data, f)

def is_blocked(user_id):
    data = load_blocked()
    from datetime import datetime
    if str(user_id) in data:
        expire = datetime.fromisoformat(data[str(user_id)])
        if datetime.now() < expire:
            return True
        else:
            del data[str(user_id)]
        save_blocked(data)
    return False

def block_user(user_id, days=7):
    from datetime import datetime, timedelta
    data = load_blocked()
    data[str(user_id)] = (datetime.now() + timedelta(days=days)).isoformat()
    save_blocked(data)

# ------ إنشاء تطبيق البوت ------
application = Application.builder().token(BOT_TOKEN).build()

# ------ قاموس لتخزين الردود المؤقتة لكل مشرف ------
reply_targets = {}    # admin_id -> target_user_id

# ------ Handlers المستخدم ------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if is_blocked(user_id):
        await update.message.reply_text("⏸️ تم إيقافك مؤقتًا من إرسال الشكاوى لمدة 7 أيام.")
        return
    await update.message.reply_text("👋 مرحبًا! أرسل شكواك أو اقتراحك هنا.")

async def handle_private(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    text = update.message.text.strip()

    # إذا كان المرسل مشرف ينتظر الرد
    if user.id in reply_targets:
        target_user_id = reply_targets[user.id]
        await context.bot.send_message(
            chat_id=target_user_id,
            text=f"📩 رد من الإدارة:\n{text}"
        )
        await update.message.reply_text("✅ تم إرسال الرد بنجاح.")
        del reply_targets[user.id]  # إزالة بعد الإرسال
        return

    # إذا كان العضو عادي
    if is_blocked(user.id):
        await update.message.reply_text("⏸️ لا يمكنك إرسال شكاوى حاليًا. انتظر انتهاء مدة الإيقاف.")
        return

    complaint_msg = (
        f"📬 **شكوى جديدة**\n"
        f"👤 الاسم: {user.full_name}\n"
        f"🆔 ID: `{user.id}`\n"
        f"🗣️ المستخدم: @{user.username if user.username else 'بدون'}\n"
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
        text=complaint_msg,
        parse_mode="Markdown",
        reply_markup=keyboard,
        message_thread_id=ADMIN_GROUP_TOPIC_ID if ADMIN_GROUP_TOPIC_ID != 0 else None
    )

    await update.message.reply_text("✅ تم إرسال شكواك إلى الإدارة. سيتم التواصل معك عند الرد.")

# ------ Handler أزرار الإدارة ------
async def handle_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    action, target_user_id = query.data.split(":")
    target_user_id = int(target_user_id)
    admin_id = query.from_user.id

    if action == "accept":
        await context.bot.send_message(target_user_id, "✅ تم قبول شكواك. شكرًا لتعاونك!")
        await query.message.edit_text(query.message.text + "\n\n📢 تم القبول ✅", reply_markup=None)

    elif action == "reject":
        await context.bot.send_message(target_user_id, "❌ تم رفض الشكوى بعد المراجعة.")
        await query.message.edit_text(query.message.text + "\n\n📢 تم الرفض ❌", reply_markup=None)

    elif action == "block":
        block_user(target_user_id)
        await context.bot.send_message(target_user_id, "🚫 تم إيقافك من إرسال الشكاوى لمدة 7 أيام.")
        await query.message.edit_text(query.message.text + "\n\n⏸️ العضو موقوف 7 أيام", reply_markup=None)

    elif action == "reply":
        reply_targets[admin_id] = target_user_id
        await query.message.edit_text(query.message.text + "\n\n💬 أرسل الرد الآن في الخاص ليتم توجيهه للعضو.", reply_markup=None)

# ------ إضافة Handlers ------
application.add_handler(CommandHandler("start", start))
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_private))
application.add_handler(CallbackQueryHandler(handle_buttons))

# ------ تشغيل Webhook في Thread منفصل ------
async_loop = None

def run_async_loop():
    global async_loop
    async_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(async_loop)

    async def init_app():
        await application.initialize()
        try:
            await application.bot.set_webhook(WEBHOOK_URL)
            logger.info(f"✅ تم ضبط webhook -> {WEBHOOK_URL}")
        except Exception as ex:
            logger.warning(f"⚠️ لم أتمكن من ضبط webhook تلقائيًا: {ex}")
    async_loop.run_until_complete(init_app())
    async_loop.run_forever()

threading.Thread(target=run_async_loop, daemon=True).start()

# ------ مسار Webhook للـ Flask ------
@app.route(WEBHOOK_PATH, methods=["POST"])
def telegram_webhook():
    try:
        data = request.get_json(force=True)
        if not data:
            return "No data", 400
        update = Update.de_json(data, application.bot)
        if async_loop is None:
            logger.error("❌ الحلقة غير جاهزة بعد")
            return "Service not ready", 503
        asyncio.run_coroutine_threadsafe(application.process_update(update), async_loop)
        return "OK", 200
    except Exception as e:
        logger.exception(f"❌ خطأ في استلام webhook: {e}")
        return "Error", 500

# ------ بدء Flask ------
if __name__ == "__main__":
    logger.info("🚀 بدأ تشغيل Flask - الخادم سيستمع للطلبات")
    app.run(host="0.0.0.0", port=PORT)
