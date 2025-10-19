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

# ---------------- إعداد السجلات ----------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("complaint-bot")

# ---------------- إعداد Flask ----------------
app = Flask(__name__)

# ---------------- قراءة متغيرات البيئة ----------------
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("❌ BOT_TOKEN غير موجود في متغيرات البيئة.")

# المتغيرات التي كنت تستخدمها سابقًا — تأكد أن تضبطها في Render
MAIN_GROUP_ID = int(os.getenv("MAIN_GROUP_ID", "0"))           # قد تكون 0 إن لم تستخدمها
ADMIN_GROUP_ID = int(os.getenv("ADMIN_GROUP_ID"))              # مطلوب
ADMIN_GROUP_TOPIC_ID = int(os.getenv("ADMIN_GROUP_TOPIC_ID", "0"))  # 0 إذا لا توجد topic
PORT = int(os.getenv("PORT", "10000"))
WEBHOOK_PATH = f"/{BOT_TOKEN}"
HOSTNAME = os.getenv("RENDER_EXTERNAL_HOSTNAME", None)
if HOSTNAME:
    WEBHOOK_URL = f"https://{HOSTNAME}{WEBHOOK_PATH}"
else:
    WEBHOOK_URL = os.getenv("WEBHOOK_URL", "")  # fallback إذا أردت تجربة محليًا

# ---------------- إعداد ملفات التخزين والحدود ----------------
BLOCK_FILE = "blocked_users.json"    # موقوفين (iso timestamps)
DAILY_FILE = "daily_users.json"      # تتبع من أرسل اليوم
MAX_CHAR = int(os.getenv("MAX_CHAR", "200"))  # يمكن تغييره من env

# ---------------- دوال مساعدة بسيطة للـ JSON ----------------
def load_json(path):
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        logger.warning(f"load_json error {path}: {e}")
    return {}

def save_json(path, data):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    except Exception as e:
        logger.error(f"save_json error {path}: {e}")

# ---------------- حالة الحظر ----------------
def is_blocked(user_id):
    data = load_json(BLOCK_FILE)
    if str(user_id) in data:
        try:
            expire = datetime.fromisoformat(data[str(user_id)])
            if datetime.now() < expire:
                return True
            else:
                # انتهاء الحظر -> حذف
                del data[str(user_id)]
                save_json(BLOCK_FILE, data)
        except Exception:
            # لو شكل التاريخ تالف نحذفه
            del data[str(user_id)]
            save_json(BLOCK_FILE, data)
    return False

def block_user(user_id, days=7):
    data = load_json(BLOCK_FILE)
    data[str(user_id)] = (datetime.now() + timedelta(days=days)).isoformat()
    save_json(BLOCK_FILE, data)

# ---------------- حد رسالة يومي ----------------
def can_send_today(user_id):
    data = load_json(DAILY_FILE)
    today = datetime.now().date().isoformat()
    if str(user_id) in data and data[str(user_id)] == today:
        return False
    data[str(user_id)] = today
    save_json(DAILY_FILE, data)
    return True

# ---------------- إنشاء التطبيق ----------------
application = Application.builder().token(BOT_TOKEN).build()

# ---------------- قاموس الردود المؤقتة لكل مشرف ----------------
# عند ضغط المشرف زر "رد" نضع: reply_targets[admin_id] = target_user_id
reply_targets = {}

# ---------------- Handlers ----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # /start يشتغل في الخاص فقط — حماية إضافية
    if update.effective_chat.type != "private":
        return
    user_id = update.effective_user.id
    if is_blocked(user_id):
        await update.message.reply_text("⏸️ تم إيقافك مؤقتًا من إرسال الشكاوى لمدة 7 أيام.")
        return

    welcome = (
        "👋 مرحبًا! هذا البوت مخصص لاستقبال شكاوى ومقترحات أعضاء غرفة علي مع الحق.\n\n"
        f"📌 يمكنك إرسال رسالة واحدة يوميًا.\n"
        f"✍️ الحد الأقصى للأحرف: {MAX_CHAR}\n"
        "📂 ستُعرض الشكاوى في موضوع 'الشكاوي والمقترحات' داخل مجموعة الإدارة.\n\n"
        "📩 **مهم:** لتضمن استلام الردود من الإدارة، اضغط /start وابقَ المحادثة مع البوت مفتوحة.\n"
        "🔗 الغرفة الرئيسية: @AliwAlhaq"
    )
    await update.message.reply_text(welcome)

async def handle_private(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # نتعامل فقط مع الخاص
    if update.effective_chat.type != "private":
        return

    user = update.effective_user
    text = (update.message.text or "").strip()
    if not text:
        return

    # حماية: طول الرسالة
    if len(text) > MAX_CHAR:
        await update.message.reply_text(f"⚠️ الحد الأقصى لعدد الأحرف هو {MAX_CHAR}.")
        return

    # 1) هل هذا المشرف في وضع الرد (كتب زر رد قبل قليل)؟
    if user.id in reply_targets:
        target_user_id = reply_targets[user.id]
        try:
            # نحاول إرسال الرد مباشرة للعضو المستهدف
            await context.bot.send_message(chat_id=target_user_id, text=f"📩 رد من الإدارة:\n\n{text}")
            await update.message.reply_text("✅ تم إرسال الرد بنجاح إلى العضو.")
            # نخبر الإدارة في المجموعة بنجاح الإرسال
            try:
                await context.bot.send_message(
                    chat_id=ADMIN_GROUP_ID,
                    text=f"💬 تم إرسال رد من المشرف [{user.full_name}](tg://user?id={user.id}) إلى العضو `{target_user_id}`:\n\n{text}",
                    parse_mode="Markdown"
                )
            except Exception:
                # إذا فشل إعلام الإدارة فلا نكسر التدفق
                pass
        except Exception as e:
            logger.exception(f"فشل إرسال الرد إلى {target_user_id}: {e}")
            # تعامل ذكي مع Forbidden
            err_str = str(e)
            if "Forbidden" in err_str or "bot can't initiate conversation" in err_str:
                await update.message.reply_text(
                    "⚠️ لم أتمكن من إرسال الرد — يبدو أن العضو لم يسمح للبوت بمراسلات خاصة أو حظرك البوت."
                )
                # إرسال رسالة للإدارة تحتوي رابط البوت لبدء المحادثة
                try:
                    me = await context.bot.get_me()
                    bot_username = me.username
                except Exception:
                    bot_username = None

                note = (
                    f"⚠️ تعذّر إرسال الرد إلى العضو `{target_user_id}`؛ قد يكون لم يبدأ محادثة مع البوت أو حظره.\n"
                )
                if bot_username:
                    note += f"🔗 أرسِل له هذا الرابط ليبدأ المحادثة: https://t.me/{bot_username}"
                try:
                    await context.bot.send_message(chat_id=ADMIN_GROUP_ID, text=note, parse_mode="Markdown")
                except Exception:
                    pass
            else:
                await update.message.reply_text("⚠️ حدث خطأ أثناء محاولة إرسال الرد. راجع السجلات.")
        finally:
            # إزالة الحالة للمشرف بعد المحاولة (نجحت أو فشلت)
            reply_targets.pop(user.id, None)
        return

    # 2) حالة إرسال شكوى عادية من مستخدم
    if is_blocked(user.id):
        await update.message.reply_text("⏸️ لا يمكنك إرسال شكاوى حاليًا. انتهت فترة الإيقاف لاحقًا.")
        return

    if not can_send_today(user.id):
        await update.message.reply_text("⚠️ يمكنك إرسال رسالة واحدة يوميًا فقط. حاول غدًا.")
        return

    # بناء رسالة الشكوى للإدارة
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

    # إرسال الشكوى لمجموعة الإدارة (وفي Topic إن معرفه موجود)
    try:
        await context.bot.send_message(
            chat_id=ADMIN_GROUP_ID,
            text=complaint_msg,
            parse_mode="Markdown",
            reply_markup=keyboard,
            message_thread_id=ADMIN_GROUP_TOPIC_ID if ADMIN_GROUP_TOPIC_ID != 0 else None
        )
    except Exception as e:
        logger.exception(f"فشل إرسال الشكوى لمجموعة الإدارة: {e}")
        await update.message.reply_text("⚠️ حدث خطأ أثناء إرسال الشكوى إلى الإدارة. حاول لاحقًا.")
        return

    await update.message.reply_text("✅ تم إرسال شكواك إلى الإدارة. سيتم التواصل معك عند الرد.")

async def handle_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data or ""
    if ":" not in data:
        await query.message.edit_text(query.message.text + "\n\n⚠️ بيانات الزر غير مفهومة", reply_markup=None)
        return

    action, target_user_id = data.split(":", 1)
    try:
        target_user_id = int(target_user_id)
    except:
        await query.message.edit_text(query.message.text + "\n\n⚠️ ID غير صالح", reply_markup=None)
        return

    admin_id = query.from_user.id

    async def edit_status(text):
        try:
            await query.message.edit_text(query.message.text + f"\n\n📢 {text}", reply_markup=None)
        except Exception:
            pass

    try:
        if action == "accept":
            try:
                await context.bot.send_message(chat_id=target_user_id, text="✅ تم قبول شكواك. شكرًا لتعاونك!")
            except Exception as e:
                logger.warning(f"فشل إرسال قبول إلى {target_user_id}: {e}")
            await edit_status("تم القبول ✅")

        elif action == "reject":
            try:
                await context.bot.send_message(chat_id=target_user_id, text="❌ تم رفض الشكوى بعد المراجعة.")
            except Exception as e:
                logger.warning(f"فشل إرسال رفض إلى {target_user_id}: {e}")
            await edit_status("تم الرفض ❌")

        elif action == "block":
            block_user(target_user_id)
            try:
                await context.bot.send_message(chat_id=target_user_id, text="🚫 تم إيقافك من إرسال الشكاوى لمدة 7 أيام.")
            except Exception as e:
                logger.warning(f"فشل إخطار العضو بالإيقاف: {e}")
            await edit_status("العضو موقوف 7 أيام ⏸️")

        elif action == "reply":
            # تحفظ أن المشرف (admin_id) سيدخل الرد في الخاص وسيتم توجيهه للـ target_user_id
            reply_targets[admin_id] = target_user_id
            await edit_status("💬 أرسل الرد الآن في الخاص ليتم توجيهه للعضو.")
            # نرسل تعليمات للمشرف في الخاص (حتى لو كانت الرسالة في مجموعة عامة)
            try:
                await context.bot.send_message(chat_id=admin_id, text="📩 أرسل الآن الرد في الخاص ليتم توجيهه إلى العضو.")
            except Exception:
                pass

    except Exception as e:
        logger.exception(f"خطأ في handle_buttons: {e}")
        try:
            await context.bot.send_message(chat_id=ADMIN_GROUP_ID, text=f"❌ حدث خطأ: {e}")
        except Exception:
            pass

# ---------------- Webhook route (Flask) ----------------
@app.route(WEBHOOK_PATH, methods=["POST"])
def telegram_webhook():
    try:
        data = request.get_json(force=True)
        if not data:
            return "no data", 400
        update = Update.de_json(data, application.bot)
        if async_loop is None:
            logger.error("❌ الحلقة غير جاهزة بعد")
            return "service not ready", 503
        asyncio.run_coroutine_threadsafe(application.process_update(update), async_loop)
        return "ok", 200
    except Exception as e:
        logger.exception(f"خطأ في استلام webhook: {e}")
        return "error", 500

# ---------------- تشغيل حلقة التطبيق وضبط webhook ----------------
async_loop = None
def run_async_loop():
    global async_loop
    async_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(async_loop)

    async def init_app():
        await application.initialize()
        # ضبط webhook إذا كان لدينا URL صالح
        if WEBHOOK_URL:
            try:
                await application.bot.set_webhook(WEBHOOK_URL)
                logger.info(f"✅ تم ضبط webhook -> {WEBHOOK_URL}")
            except Exception as ex:
                logger.exception(f"⚠️ فشل ضبط webhook: {ex}")
        else:
            logger.warning("⚠️ WEBHOOK_URL غير مضبوطة، لن يتم ضبط webhook تلقائيًا.")
    async_loop.run_until_complete(init_app())
    async_loop.run_forever()

threading.Thread(target=run_async_loop, daemon=True).start()

# ---------------- تسجيل الـ Handlers ----------------
application.add_handler(CommandHandler("start", start))
application.add_handler(MessageHandler(filters.TEXT & filters.ChatType.PRIVATE, handle_private))
application.add_handler(CallbackQueryHandler(handle_buttons))

# ---------------- بدء Flask ----------------
if __name__ == "__main__":
    logger.info("🚀 بدأ الخادم - البوت يعمل عبر webhook (Flask)")
    app.run(host="0.0.0.0", port=PORT)
