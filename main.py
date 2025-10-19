import os
import json
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiohttp import web

# ------------------------
# المتغيرات من بيئة Render
# ------------------------
BOT_TOKEN = os.getenv("BOT_TOKEN")
MAIN_GROUP_ID = int(os.getenv("Main_Group_ID"))
ADMIN_GROUP_ID = int(os.getenv("Admin_Group_ID"))
ADMIN_TOPIC_ID = int(os.getenv("Admin_Group_topic_ID", "2"))  # يمكن تعديله لاحقاً

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

BLOCK_FILE = "blocked.json"

# ------------------------
# إدارة ملف الموقوفين
# ------------------------
def load_blocked():
    if os.path.exists(BLOCK_FILE):
        with open(BLOCK_FILE, "r") as f:
            return json.load(f)
    return {}

def save_blocked(data):
    with open(BLOCK_FILE, "w") as f:
        json.dump(data, f)

blocked_users = load_blocked()

def is_blocked(user_id):
    now = datetime.now()
    if str(user_id) in blocked_users:
        until = datetime.fromisoformat(blocked_users[str(user_id)])
        if now < until:
            return True
        else:
            del blocked_users[str(user_id)]
            save_blocked(blocked_users)
    return False

# ------------------------
# الأوامر الأساسية
# ------------------------
@dp.message(Command("start"))
async def start(message: types.Message):
    member = await bot.get_chat_member(MAIN_GROUP_ID, message.from_user.id)
    if member.status not in ["member", "administrator", "creator"]:
        await message.answer("🚫 يجب أن تكون عضوًا في المجموعة العامة لاستخدام هذا البوت.")
        return

    if is_blocked(message.from_user.id):
        await message.answer("🚫 تم إيقافك مؤقتًا من إرسال الشكاوى لمدة 7 أيام.")
        return

    await message.answer("👋 مرحبًا! أرسل الآن شكواك أو اقتراحك:")

@dp.message()
async def handle_complaint(message: types.Message):
    if message.chat.type != "private":
        return

    if is_blocked(message.from_user.id):
        await message.answer("🚫 تم إيقافك مؤقتًا من إرسال الشكاوى لمدة 7 أيام.")
        return

    member = await bot.get_chat_member(MAIN_GROUP_ID, message.from_user.id)
    if member.status not in ["member", "administrator", "creator"]:
        await message.answer("🚫 يجب أن تكون عضوًا في المجموعة العامة لاستخدام هذا البوت.")
        return

    user = message.from_user
    text = (
        f"📬 **شكوى/اقتراح جديد**\n"
        f"👤 الاسم: {user.full_name}\n"
        f"🆔 ID: `{user.id}`\n"
        f"🗣️ المستخدم: @{user.username if user.username else '—'}\n"
        f"🕓 الوقت: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        f"📝 **النص:**\n{message.text}"
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ قبول", callback_data=f"accept_{user.id}"),
            InlineKeyboardButton(text="❌ رفض", callback_data=f"reject_{user.id}")
        ],
        [
            InlineKeyboardButton(text="💬 رد", callback_data=f"reply_{user.id}"),
            InlineKeyboardButton(text="⏸️ إيقاف 7 أيام", callback_data=f"block_{user.id}"),
            InlineKeyboardButton(text="🔓 رفع الإيقاف", callback_data=f"unblock_{user.id}")
        ]
    ])

    await bot.send_message(
        chat_id=ADMIN_GROUP_ID,
        text=text,
        parse_mode="Markdown",
        reply_markup=keyboard,
        message_thread_id=ADMIN_TOPIC_ID
    )

    await message.answer("✅ تم إرسال شكواك للإدارة، شكرًا لتواصلك.")

# ------------------------
# ردود الإدارة على الأزرار
# ------------------------
@dp.callback_query()
async def handle_callback(callback: types.CallbackQuery):
    data = callback.data.split("_")
    action = data[0]
    user_id = int(data[1])

    if action == "accept":
        await bot.send_message(user_id, "✅ تم قبول شكواك، سيتم اتخاذ الإجراء اللازم.")
        await callback.message.edit_text(callback.message.text + "\n\n✅ تم قبول الشكوى.")

    elif action == "reject":
        await bot.send_message(user_id, "❌ تم رفض الشكوى بعد المراجعة.")
        await callback.message.edit_text(callback.message.text + "\n\n❌ تم رفض الشكوى.")

    elif action == "reply":
        await callback.message.reply("💬 أرسل الرد الذي تريد إرساله للعضو:")

        @dp.message()
        async def get_reply(message: types.Message):
            await bot.send_message(user_id, f"📩 رد من الإدارة:\n{message.text}")
            await message.answer("✅ تم إرسال الرد.")
            dp.message.handlers.unregister(get_reply)

    elif action == "block":
        until = datetime.now() + timedelta(days=7)
        blocked_users[str(user_id)] = until.isoformat()
        save_blocked(blocked_users)
        await bot.send_message(user_id, "🚫 تم إيقافك عن إرسال الشكاوى لمدة 7 أيام.")
        await callback.message.reply("⏸️ تم إيقاف العضو 7 أيام.")

    elif action == "unblock":
        if str(user_id) in blocked_users:
            del blocked_users[str(user_id)]
            save_blocked(blocked_users)
            await bot.send_message(user_id, "✅ تم رفع الإيقاف عنك، يمكنك إرسال شكوى مجددًا.")
            await callback.message.reply("🔓 تم رفع الإيقاف عن العضو.")
        else:
            await callback.message.reply("ℹ️ العضو غير موقوف حاليًا.")

    await callback.answer()

# ------------------------
# إعداد webhook لـ Render
# ------------------------
async def handle_webhook(request):
    update = await request.json()
    await dp.feed_webhook_update(bot, update)
    return web.Response()

app = web.Application()
app.router.add_post(f"/{BOT_TOKEN}", handle_webhook)

async def on_startup(app):
    webhook_url = f"https://{os.getenv('RENDER_EXTERNAL_HOSTNAME')}/{BOT_TOKEN}"
    await bot.set_webhook(webhook_url)

app.on_startup.append(on_startup)

if __name__ == "__main__":
    web.run_app(app, host="0.0.0.0", port=int(os.getenv("PORT", 10000)))
