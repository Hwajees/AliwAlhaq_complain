import json
import os
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram import asyncio

# تحميل المتغيرات من البيئة
BOT_TOKEN = os.getenv("BOT_TOKEN")
MAIN_GROUP_ID = int(os.getenv("MAIN_GROUP_ID"))
ADMIN_GROUP_ID = int(os.getenv("ADMIN_GROUP_ID"))
ADMIN_GROUP_TOPIC_ID = int(os.getenv("ADMIN_GROUP_TOPIC_ID"))

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

BLOCK_FILE = "blocked_users.json"


# ---------------------- وظائف مساعدة ----------------------

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
    if str(user_id) in data:
        expire = datetime.fromisoformat(data[str(user_id)])
        if datetime.now() < expire:
            return True
        else:
            del data[str(user_id)]
            save_blocked(data)
    return False

def block_user(user_id, days=7):
    data = load_blocked()
    data[str(user_id)] = (datetime.now() + timedelta(days=days)).isoformat()
    save_blocked(data)

def unblock_user(user_id):
    data = load_blocked()
    if str(user_id) in data:
        del data[str(user_id)]
        save_blocked(data)


# ---------------------- أوامر المستخدم ----------------------

@dp.message(CommandStart())
async def start(message: types.Message):
    member = await bot.get_chat_member(MAIN_GROUP_ID, message.from_user.id)
    if member.status in ["left", "kicked"]:
        await message.answer("🚫 يجب أن تكون عضوًا في المجموعة العامة لاستخدام هذا البوت.")
        return

    if is_blocked(message.from_user.id):
        await message.answer("⏸️ تم إيقافك مؤقتًا من إرسال الشكاوى لمدة 7 أيام.")
        return

    await message.answer("مرحبًا 👋\nأرسل الآن الشكوى أو الاقتراح الذي ترغب في تقديمه.")


@dp.message(F.text)
async def receive_complaint(message: types.Message):
    if is_blocked(message.from_user.id):
        await message.answer("⏸️ لا يمكنك إرسال شكاوى حاليًا. انتظر انتهاء مدة الإيقاف.")
        return

    user = message.from_user
    text = message.text.strip()

    complaint_msg = (
        f"📬 **شكوى جديدة**\n"
        f"👤 الاسم: {user.full_name}\n"
        f"🆔 ID: `{user.id}`\n"
        f"🗣️ المستخدم: @{user.username if user.username else 'بدون'}\n"
        f"🕓 التاريخ: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"💬 **النص:** {text}"
    )

    # إنشاء أزرار التحكم للإدارة
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ قبول", callback_data=f"accept:{user.id}"),
         InlineKeyboardButton(text="❌ رفض", callback_data=f"reject:{user.id}")],
        [InlineKeyboardButton(text="💬 رد", callback_data=f"reply:{user.id}"),
         InlineKeyboardButton(text="⏸️ إيقاف 7 أيام", callback_data=f"block:{user.id}"),
         InlineKeyboardButton(text="🔓 رفع الإيقاف", callback_data=f"unblock:{user.id}")]
    ])

    # إرسال الشكوى إلى التوبيك الإداري
    await bot.send_message(
        chat_id=ADMIN_GROUP_ID,
        text=complaint_msg,
        parse_mode="Markdown",
        message_thread_id=ADMIN_GROUP_TOPIC_ID,
        reply_markup=keyboard
    )

    await message.answer("✅ تم إرسال شكواك إلى الإدارة. سيتم التواصل معك عند الرد.")


# ---------------------- تفاعل الإدارة ----------------------

@dp.callback_query(F.data.startswith(("accept", "reject", "reply", "block", "unblock")))
async def admin_actions(callback: types.CallbackQuery):
    action, user_id = callback.data.split(":")
    user_id = int(user_id)

    if action == "accept":
        await bot.send_message(user_id, "✅ تم قبول شكواك. شكرًا لتعاونك!")
        await callback.message.edit_text(callback.message.text + "\n\n📢 تم القبول ✅")

    elif action == "reject":
        await bot.send_message(user_id, "❌ تم رفض الشكوى بعد المراجعة.")
        await callback.message.edit_text(callback.message.text + "\n\n📢 تم الرفض ❌")

    elif action == "block":
        block_user(user_id)
        await bot.send_message(user_id, "🚫 تم إيقافك من إرسال الشكاوى لمدة 7 أيام.")
        await callback.message.edit_text(callback.message.text + "\n\n⏸️ العضو موقوف 7 أيام")

    elif action == "unblock":
        unblock_user(user_id)
        await bot.send_message(user_id, "✅ تم رفع الإيقاف عنك ويمكنك الآن إرسال الشكاوى مجددًا.")
        await callback.message.edit_text(callback.message.text + "\n\n🔓 تم رفع الإيقاف")

    elif action == "reply":
        await callback.message.answer("💬 أرسل الرد الآن ليتم توجيهه للعضو:")

        @dp.message(F.text)
        async def reply_msg(msg: types.Message):
            await bot.send_message(user_id, f"📩 رد من الإدارة:\n{msg.text}")
            await msg.answer("✅ تم إرسال الرد.")
            dp.message.handlers.unregister(reply_msg)

    await callback.answer()

# ---------------------- تشغيل البوت ----------------------

if __name__ == "__main__":
    import asyncio
    print("🚀 Bot is running...")
    asyncio.run(dp.start_polling(bot))
