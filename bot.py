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
    Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
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

# ------ ملفات الحظر والحد اليومي ------
BLOCK_FILE = "blocked_users.json"
DAILY_FILE = "daily_users.json"
MAX_CHAR = 200  # حد الأحرف للعضو والمشرف

def load_json(file_path):
    if os.path.exists(file_path):
        with open(file_path, "r") as f:
            return json.load(f)
    return {}

def save_json(file_path, data):
    with open(file_path, "w") as f:
        json.dump(data, f)

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

# ------ إنشاء تطبيق البوت ------
application = Application.builder().token(BOT_TOKEN).build()

# ------ قاموس لتخزين الردود المؤقتة لكل مشرف ------
reply_targets = {}  # admin_id -> target_user_id

# ------ دالة /start ------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return  # تجاهل أي استخدام للأمر داخل المجموعات

    user_id = update.message.from_user.id
    if is_blocked(user_id):
        await update.message.reply_text("⏸️ تم إيقافك مؤقتًا من إرسال الشكاوى لمدة 7 أيام.")
        return

    msg = (
        "👋 مرحبًا بك!\n\n"
        "📮 هذا البوت مخصص لاستقبال **الشكاوى والمقترحات** من أعضاء غرفة *علي مع الحق والحق مع علي*.\n\n"
        f"📝 يمكنك إرسال **رسالة واحدة يوميًا** بحد أقصى **{MAX_CHAR} حرفًا**.\n"
        "📂 سيتم عرض رسالتك في *موضوع الشكاوى والمقترحات* داخل مجموعة الإدارة.\n\n"
        "🔗 لمتابعة الغرفة الرئيسية: @AliwAlhaq"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

# ------ معالجة الرسائل الخاصة فقط ------
async def handle_private(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # تجاهل أي رسالة من المجموعات
    if update.effective_chat.type != "private":
        return

    user = update.message.from_user
    text = update.message.text.strip()

    if len(text) > MAX_CHAR:
        await update.message.reply_text(f"⚠️ الحد الأقصى لعدد الأحرف هو {MAX_CHAR}.")
        return

    # تحقق إن كان هذا المشرف في وضع الرد
    if user.id in reply_targets:
        target_user_id = reply_targets[user.id]
        try:
            await context.bot.send_message(
                chat_id=target_user_id,
                text=f"📩 رد من الإدارة:\n{text}"
            )
            await update.message.reply_text("✅ تم إرسال الرد بنجاح إلى العضو.")
        except Exception as e:
            await update.message.reply_text(f"⚠️ لم أتمكن من إرسال الرد: {e}")
        finally:
            del reply_targets[user.id]
        return

    # عضو عادي يرسل شكوى
    if is_blocked(user.id):
        await update.message.reply_text("🚫 لا يمكنك إرسال شكاوى حاليًا. انتظر انتهاء مدة الإيقاف.")
        return

    if not can_send_today(user.id):
        await update.message.reply_text("⚠️ يمكنك إرسال رسالة واحدة فقط يوميًا. حاول غدًا.")
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

# ------ معالجة الأزرار ------
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
application.add_handler(MessageHandler(filters.TEXT & filters.ChatType.PRIVATE, handle_private))
application.add_handler(CallbackQueryHandler(handle_buttons))

# ------ تشغيل Webhook ------
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

# ------ Flask Webhook Route ------
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

# ------ تشغيل Flask ------
if __name__ == "__main__":
    logger.info("🚀 بدأ تشغيل Flask - الخادم سيستمع للطلبات")
    app.run(host="0.0.0.0", port=PORT)
