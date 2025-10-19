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

# ------ ملفات البيانات ------
BLOCK_FILE = "blocked_users.json"
DAILY_LIMIT_FILE = "daily_limit.json"

MAX_CHARS = 200  # الحد الأقصى للأحرف لكل رسالة

def load_json(file_path):
    if os.path.exists(file_path):
        with open(file_path, "r") as f:
            return json.load(f)
    return {}

def save_json(file_path, data):
    with open(file_path, "w") as f:
        json.dump(data, f)

# ------ وظائف الإيقاف ------
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

# ------ وظائف الحد اليومي ------
def can_send_today(user_id):
    data = load_json(DAILY_LIMIT_FILE)
    today = datetime.now().date().isoformat()
    if str(user_id) in data and data[str(user_id)] == today:
        return False
    return True

def mark_sent_today(user_id):
    data = load_json(DAILY_LIMIT_FILE)
    today = datetime.now().date().isoformat()
    data[str(user_id)] = today
    save_json(DAILY_LIMIT_FILE, data)

# ------ إنشاء تطبيق البوت ------
application = Application.builder().token(BOT_TOKEN).build()

# ------ قاموس الردود المؤقتة لكل مشرف ------
reply_targets = {}  # admin_id -> target_user_id

# ------ نصوص الرسائل ------
welcome_text = (
    f"👋 مرحبًا بك في بوت الشكاوى والمقترحات!\n\n"
    f"📢 هذا البوت مخصص لاستقبال شكاوى ومقترحات أعضاء **غرفة علي مع الحق والحق مع علي**.\n"
    f"📝 جميع الشكاوى والمقترحات سيتم عرضها مباشرة على إدارة الغرفة لمراجعتها.\n\n"
    f"💬 ملاحظة:\n"
    f"- الحد اليومي لكل عضو: رسالة واحدة فقط.\n"
    f"- الحد الأقصى للأحرف لكل رسالة: {MAX_CHARS} حرف.\n\n"
    f"🔗 للرجوع إلى الغرفة: [غرفة علي مع الحق](https://t.me/AliwAlhaq)"
)

accept_text = (
    "✅ تم قبول شكواك بنجاح!\n\n"
    "📌 شكركم على تواصلكم معنا، سيتم التعامل مع شكواك وفق الإجراءات المعتمدة.\n"
    "💡 نسعى دائمًا لتحسين تجربة الأعضاء في الغرفة."
)

reject_text = (
    "❌ تم رفض شكواك بعد المراجعة.\n\n"
    "📌 نعتذر عن أي إزعاج، وإذا كان لديك أي استفسار أو توضيح، يمكنك التواصل معنا مرة أخرى.\n"
    "💡 هدفنا دائمًا هو تحسين جودة النقاش والخدمة للأعضاء."
)

# ------ Handlers المستخدم ------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(welcome_text, parse_mode="Markdown")

async def handle_private(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    text = update.message.text.strip()

    # تحقق من الحد اليومي
    if not can_send_today(user.id):
        await update.message.reply_text("⚠️ يمكنك إرسال رسالة واحدة فقط يوميًا. حاول مرة أخرى غدًا.")
        return

    # تحقق من الحد الأقصى للأحرف
    if len(text) > MAX_CHARS:
        await update.message.reply_text(
            f"⚠️ لا يمكن إرسال أكثر من {MAX_CHARS} حرفًا. رسالتك الحالية تحتوي على {len(text)} حرفًا."
        )
        return

    # تحقق من الإيقاف
    if is_blocked(user.id):
        await update.message.reply_text("⏸️ تم إيقافك مؤقتًا من إرسال الشكاوى لمدة 7 أيام.")
        return

    # بعد التحقق، سجل إرسال الرسالة اليوم
    mark_sent_today(user.id)

    # إرسال الشكوى للإدارة
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

    await update.message.reply_text(
        "✅ تم إرسال شكواك إلى الإدارة. سيتم التواصل معك عند الرد."
    )

# ------ Handler أزرار الإدارة ------
async def handle_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    action, target_user_id = query.data.split(":")
    target_user_id = int(target_user_id)
    admin_id = query.from_user.id

    if action == "accept":
        await context.bot.send_message(target_user_id, accept_text, parse_mode="Markdown")
        await query.message.edit_text(query.message.text + "\n\n📢 تم القبول ✅", reply_markup=None)

    elif action == "reject":
        await context.bot.send_message(target_user_id, reject_text, parse_mode="Markdown")
        await query.message.edit_text(query.message.text + "\n\n📢 تم الرفض ❌", reply_markup=None)

    elif action == "block":
        block_user(target_user_id)
        await context.bot.send_message(target_user_id, "🚫 تم إيقافك من إرسال الشكاوى لمدة 7 أيام.")
        await query.message.edit_text(query.message.text + "\n\n⏸️ العضو موقوف 7 أيام", reply_markup=None)

    elif action == "reply":
        reply_targets[admin_id] = target_user_id
        await query.message.edit_text(
            query.message.text + "\n\n💬 أرسل الرد الآن في الخاص ليتم توجيهه للعضو.",
            reply_markup=None
        )

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
