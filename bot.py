import logging
import datetime
from telegram import (
    Update, InlineKeyboardMarkup, InlineKeyboardButton
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    ContextTypes, CallbackQueryHandler, filters
)

# ---------------- إعدادات عامة ----------------
TOKEN = "ضع_توكن_البوت_هنا"

# معرّف مجموعة الإدارة (خاصة)
ADMIN_GROUP_ID = -1001234567890
# رقم موضوع الشكاوى داخل مجموعة الإدارة (ضع 0 إذا لا يوجد مواضيع)
ADMIN_GROUP_TOPIC_ID = 0
# معرّف المجموعة العامة (البوت لا يرد فيها)
PUBLIC_GROUP_ID = -1009876543210

# الحدود
MAX_CHAR = 200
MAX_MESSAGES_PER_DAY = 1

# ---------------- سجلات وتشغيل ----------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# تخزين حالات الرد
reply_targets = {}
user_daily_messages = {}
blocked_users = {}

# ---------------- دوال مساعدة ----------------
def can_send_today(user_id):
    today = datetime.date.today()
    if user_id not in user_daily_messages:
        user_daily_messages[user_id] = [today, 0]
    last_date, count = user_daily_messages[user_id]
    if last_date != today:
        user_daily_messages[user_id] = [today, 0]
        return True
    return count < MAX_MESSAGES_PER_DAY

def increment_message_count(user_id):
    today = datetime.date.today()
    if user_id not in user_daily_messages:
        user_daily_messages[user_id] = [today, 1]
    else:
        last_date, count = user_daily_messages[user_id]
        if last_date == today:
            user_daily_messages[user_id][1] += 1
        else:
            user_daily_messages[user_id] = [today, 1]

def is_blocked(user_id):
    return user_id in blocked_users and blocked_users[user_id] > datetime.datetime.now()

def block_user(user_id, days=7):
    blocked_users[user_id] = datetime.datetime.now() + datetime.timedelta(days=days)

# ---------------- أوامر البوت ----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 مرحبًا بك في *بوت الشكاوى الخاص بغرفة علي مع الحق*\n\n"
        "📝 يمكنك إرسال شكوى أو اقتراح عبر كتابة رسالتك هنا مباشرة.\n\n"
        f"⚠️ *الحد الأقصى:* {MAX_CHAR} حرف.\n"
        f"📅 *عدد الرسائل المسموح بها:* {MAX_MESSAGES_PER_DAY} رسالة يوميًا.\n"
        "💬 سيتم إرسال شكواك إلى الإدارة، وسيتم الرد عليك في حال الحاجة.\n\n"
        "📍 يمكن للإدارة مراجعة الشكاوى داخل موضوع (الشكاوى والمقترحات) في مجموعة الإدارة.\n"
        "⚖️ الحد الأقصى لرد المشرف أيضًا هو 200 حرف.",
        parse_mode="Markdown"
    )

# ---------------- استقبال رسائل المستخدم ----------------
async def handle_private(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    text = update.message.text.strip()

    # تحقق من عدد الأحرف
    if len(text) > MAX_CHAR:
        await update.message.reply_text(f"⚠️ الحد الأقصى لعدد الأحرف هو {MAX_CHAR}.")
        return

    # تحقق من إن كان المشرف في وضع الرد
    if user.id in reply_targets:
        target_user_id = reply_targets[user.id]
        try:
            await context.bot.send_message(
                chat_id=target_user_id,
                text=f"📩 *رد من الإدارة:*\n{text}",
                parse_mode="Markdown"
            )
            await update.message.reply_text("✅ تم إرسال الرد بنجاح إلى العضو.")
            await context.bot.send_message(
                chat_id=ADMIN_GROUP_ID,
                text=(
                    f"💬 تم إرسال رد من المشرف [{user.full_name}](tg://user?id={user.id}) "
                    f"إلى العضو `{target_user_id}`:\n\n{text}"
                ),
                parse_mode="Markdown"
            )
        except Exception as e:
            if "Forbidden" in str(e):
                await context.bot.send_message(
                    chat_id=ADMIN_GROUP_ID,
                    text=(
                        f"⚠️ لا يمكن إرسال الرد للعضو `{target_user_id}` "
                        f"لأنه لم يبدأ المحادثة مع البوت.\n\n"
                        f"🔗 أرسل له هذا الرابط لبدء المحادثة:\n"
                        f"https://t.me/{(await context.bot.get_me()).username}"
                    ),
                    parse_mode="Markdown"
                )
                await update.message.reply_text("⚠️ لم أتمكن من إرسال الرد، لأن العضو لم يبدأ المحادثة مع البوت.")
            else:
                logger.error(f"❌ خطأ أثناء إرسال الرد إلى {target_user_id}: {e}")
                await update.message.reply_text("⚠️ حدث خطأ غير متوقع أثناء إرسال الرد.")
        finally:
            del reply_targets[user.id]
        return

    # تحقق من الحظر أو الحد اليومي
    if is_blocked(user.id):
        await update.message.reply_text("⏸️ لا يمكنك إرسال شكاوى حاليًا. انتظر انتهاء مدة الإيقاف.")
        return
    if not can_send_today(user.id):
        await update.message.reply_text("⚠️ يمكنك إرسال رسالة واحدة فقط يوميًا. حاول غدًا.")
        return

    increment_message_count(user.id)

    # إنشاء نص الشكوى
    complaint_msg = (
        f"📬 *شكوى جديدة*\n"
        f"👤 الاسم: {user.full_name}\n"
        f"🆔 ID: `{user.id}`\n"
        f"🗣️ المستخدم: @{user.username if user.username else 'بدون'}\n"
        f"💬 النص: {text}"
    )

    # أزرار التحكم
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

    # إرسالها إلى مجموعة الإدارة
    await context.bot.send_message(
        chat_id=ADMIN_GROUP_ID,
        text=complaint_msg,
        parse_mode="Markdown",
        reply_markup=keyboard,
        message_thread_id=ADMIN_GROUP_TOPIC_ID if ADMIN_GROUP_TOPIC_ID != 0 else None
    )

    await update.message.reply_text("✅ تم إرسال شكواك إلى الإدارة. سيتم التواصل معك عند الرد.")

# ---------------- معالجة الأزرار ----------------
async def handle_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    action, target_user_id = query.data.split(":")
    target_user_id = int(target_user_id)
    admin_id = query.from_user.id

    async def edit_message_status(status):
        try:
            await query.message.edit_text(
                query.message.text + f"\n\n📢 {status}",
                reply_markup=None
            )
        except:
            pass

    try:
        if action == "accept":
            await context.bot.send_message(target_user_id, "✅ تم قبول شكواك. شكرًا لتعاونك!")
            await edit_message_status("تم القبول ✅")

        elif action == "reject":
            await context.bot.send_message(target_user_id, "❌ تم رفض الشكوى بعد المراجعة.")
            await edit_message_status("تم الرفض ❌")

        elif action == "block":
            block_user(target_user_id)
            await context.bot.send_message(target_user_id, "🚫 تم إيقافك من إرسال الشكاوى لمدة 7 أيام.")
            await edit_message_status("العضو موقوف 7 أيام ⏸️")

        elif action == "reply":
            reply_targets[admin_id] = target_user_id
            await edit_message_status("💬 أرسل الرد الآن في الخاص ليتم توجيهه للعضو.")
            await context.bot.send_message(
                chat_id=admin_id,
                text="📩 أرسل الآن الرد في الخاص ليتم توجيهه إلى العضو."
            )

    except Exception as e:
        if "Forbidden" in str(e):
            await context.bot.send_message(
                chat_id=ADMIN_GROUP_ID,
                text=(
                    f"⚠️ لا يمكن إرسال الرسالة إلى العضو `{target_user_id}`، "
                    f"ربما غادر أو حظر البوت.\n"
                    f"🔗 رابط البوت: https://t.me/{(await context.bot.get_me()).username}"
                ),
                parse_mode="Markdown"
            )
        else:
            logger.error(f"❌ خطأ في handle_buttons: {e}")

# ---------------- تجاهل رسائل المجموعات ----------------
async def ignore_groups(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return  # لا يقوم بأي شيء في المجموعات

# ---------------- تشغيل التطبيق ----------------
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(handle_buttons))
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.TEXT, handle_private))
    app.add_handler(MessageHandler(filters.ChatType.GROUPS, ignore_groups))

    logger.info("✅ البوت يعمل الآن...")
    app.run_polling()

if __name__ == "__main__":
    main()
