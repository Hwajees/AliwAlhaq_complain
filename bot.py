# bot.py
import os
import json
import threading
from datetime import datetime, timedelta
from pathlib import Path

from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils import executor
from aiohttp import web

# ---------- إعداد المتغيرات من بيئة التشغيل ----------
BOT_TOKEN = os.getenv("BOT_TOKEN")  # ضع التوكن في إعدادات Render (Env)
MAIN_GROUP_ID = int(os.getenv("MAIN_GROUP_ID", "0"))      # مثال: -4949122709
ADMIN_GROUP_ID = int(os.getenv("ADMIN_GROUP_ID", "0"))    # مثال: -1003131818226
# ADMIN_THREAD_ID اختياري: اتركه فارغًا إذا لم تعرفه
ADMIN_THREAD_ID = os.getenv("ADMIN_THREAD_ID") or None
if ADMIN_THREAD_ID:
    try:
        ADMIN_THREAD_ID = int(ADMIN_THREAD_ID)
    except:
        ADMIN_THREAD_ID = None

# المسار الدائم لحفظ ملف الإيقافات (اجعل هذا mount path على Render إذا أردت الاستمرارية)
PERSISTENT_PATH = os.getenv("PERSISTENT_PATH", "/tmp")  # إذا ربطت Persistent Disk استخدم مساره هنا
SUSPENSIONS_FILE = os.path.join(PERSISTENT_PATH, "suspensions.json")

# ---------- تهيئة البوت ----------
bot = Bot(token=BOT_TOKEN, parse_mode="HTML")
dp = Dispatcher(bot)

# ---------- إعداد ملف الإيقافات ----------
Path(PERSISTENT_PATH).mkdir(parents=True, exist_ok=True)
if not os.path.exists(SUSPENSIONS_FILE):
    with open(SUSPENSIONS_FILE, "w", encoding="utf-8") as f:
        json.dump({}, f)

def load_suspensions():
    with open(SUSPENSIONS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_suspensions(data):
    with open(SUSPENSIONS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def is_suspended(user_id):
    data = load_suspensions()
    s = data.get(str(user_id))
    if not s:
        return False
    expiry = datetime.fromisoformat(s["until"])
    if datetime.utcnow() >= expiry:
        data.pop(str(user_id), None)
        save_suspensions(data)
        return False
    return True

def suspend_user(user_id, days=7, by_admin=None):
    data = load_suspensions()
    until = datetime.utcnow() + timedelta(days=days)
    data[str(user_id)] = {"until": until.isoformat(), "by": by_admin, "reason": "spam"}
    save_suspensions(data)

def lift_suspension(user_id):
    data = load_suspensions()
    if str(user_id) in data:
        data.pop(str(user_id), None)
        save_suspensions(data)
        return True
    return False

# ---------- أزرار الإدارة ----------
def admin_buttons(user_id):
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("✅ قبول", callback_data=f"accept:{user_id}"),
        InlineKeyboardButton("❌ رفض", callback_data=f"reject:{user_id}")
    )
    kb.add(
        InlineKeyboardButton("💬 رد للعضو", callback_data=f"reply:{user_id}"),
        InlineKeyboardButton("⏸️ إيقاف 7 أيام", callback_data=f"suspend:{user_id}")
    )
    kb.add(InlineKeyboardButton("🔓 رفع الإيقاف", callback_data=f"lift:{user_id}"))
    return kb

# ---------- /start ----------
@dp.message_handler(commands=["start"])
async def cmd_start(message: types.Message):
    user = message.from_user
    # تحقق العضوية في المجموعة الرئيسية
    try:
        member = await bot.get_chat_member(chat_id=MAIN_GROUP_ID, user_id=user.id)
        if member.status not in ("creator", "administrator", "member"):
            await message.answer("🚫 عذرًا، يجب أن تكون عضوًا في المجموعة العامة لاستخدام هذا البوت.")
            return
    except Exception:
        await message.answer("❗ حدث خطأ أثناء التحقق من عضويتك. تأكد أنك عضو بالمجموعة وتواصل مع الإدارة.")
        return

    if is_suspended(user.id):
        data = load_suspensions()
        until = data.get(str(user.id))["until"]
        await message.answer(f"🚫 تم ايقافك عن إرسال شكاوى حتى {until} (UTC).")
        return

    await message.answer("مرحبًا 👋\nأرسل الآن نص الشكوى أو الاقتراح. سيتلقى فريق الإدارة الرسالة داخل التوبيك المخصص.")

    # مؤقت: تسجيل استقبال الرسالة التالية من نفس المستخدم
    @dp.message_handler(lambda m: m.from_user.id == user.id, content_types=types.ContentTypes.TEXT, state=None)
    async def receive_complaint(m: types.Message):
        text = m.text.strip()
        if not text:
            await m.answer("✍️ الرجاء كتابة نص الشكوى أو الاقتراح.")
            return

        info = (
            f"📬 <b>شكوى / اقتراح جديد</b>\n\n"
            f"👤 الاسم: {user.full_name}\n"
            f"🆔 ID: <code>{user.id}</code>\n"
            f"🗣️ المعرف: @{user.username if user.username else 'لا يوجد'}\n"
            f"🕓 الوقت (UTC): {datetime.utcnow().isoformat(sep=' ', timespec='seconds')}\n\n"
            f"✉️ النص:\n{text}"
        )
        try:
            await bot.send_message(chat_id=ADMIN_GROUP_ID, text=info, reply_markup=admin_buttons(user.id),
                                   message_thread_id=ADMIN_THREAD_ID if ADMIN_THREAD_ID else None)
            await m.answer("✅ تم إرسال شكواك للإدارة. شكرًا لك.")
        except Exception:
            await m.answer("❗ حدث خطأ أثناء إرسال الشكوى للإدارة. حاول لاحقًا.")
        # إلغاء الهاندلر المسجّل مؤقتًا
        dp.message_handlers.unregister(receive_complaint)

# ---------- تعامل مع أزرار الإدارة ----------
@dp.callback_query_handler(lambda c: c.data and c.data.split(":")[0] in ("accept","reject","reply","suspend","lift"))
async def admin_action(cb: types.CallbackQuery):
    action, user_id_str = cb.data.split(":")
    user_id = int(user_id_str)
    admin = cb.from_user

    if action == "accept":
        await cb.message.edit_reply_markup(reply_markup=None)
        await cb.answer("✅ تم قبول الشكوى.")
        try:
            await bot.send_message(user_id, "✅ تم قبول شكواك، سيتم اتخاذ الإجراء اللازم. شكراً لتعاونك.")
        except:
            await cb.answer("⚠️ لم أتمكن من إرسال رسالة خاصة للعضو.", show_alert=True)

    elif action == "reject":
        await cb.message.edit_reply_markup(reply_markup=None)
        await cb.answer("❌ تم رفض الشكوى.")
        try:
            await bot.send_message(user_id, "❌ تم رفض شكواك بعد المراجعة.")
        except:
            await cb.answer("⚠️ لم أتمكن من إرسال رسالة خاصة للعضو.", show_alert=True)

    elif action == "reply":
        await cb.answer("اكتب ردّك هنا في الخاص — سأرسله للعضو عندما تكتبه.")
        if not hasattr(bot, "pending_replies"):
            bot.pending_replies = {}
        bot.pending_replies[admin.id] = user_id

    elif action == "suspend":
        suspend_user(user_id, days=7, by_admin=admin.id)
        await cb.answer("⏸️ تم إيقاف استلام الشكاوى من هذا العضو لمدة 7 أيام.")
        try:
            await bot.send_message(user_id, f"🚫 تم إيقافك مؤقتًا عن إرسال شكاوى لمدة 7 أيام بواسطة الإدارة.")
        except:
            pass
        await cb.message.edit_reply_markup(reply_markup=None)

    elif action == "lift":
        ok = lift_suspension(user_id)
        if ok:
            await cb.answer("🔓 تم رفع الإيقاف عن هذا العضو.")
            try:
                await bot.send_message(user_id, "🔓 تم رفع الإيقاف عنك، يمكنك الآن إرسال الشكاوى مجددًا.")
            except:
                pass
            await cb.message.edit_reply_markup(reply_markup=None)
        else:
            await cb.answer("ℹ️ العضو ليس موقوفًا أصلاً.", show_alert=True)

# ---------- التقاط رد المشرف بعد الضغط reply ----------
@dp.message_handler(lambda m: hasattr(bot, "pending_replies") and m.from_user.id in getattr(bot, "pending_replies", {}), content_types=types.ContentTypes.TEXT)
async def handle_admin_reply(m: types.Message):
    admin = m.from_user
    target_user_id = bot.pending_replies.pop(admin.id)
    text = m.text.strip()
    try:
        await bot.send_message(target_user_id, f"💬 رد من الإدارة:\n\n{text}")
        await m.answer("✅ تم إرسال ردّك للعضو.")
    except Exception:
        await m.answer("⚠️ فشل إرسال الرد للعضو — ربما خاصية الرسائل مغلقة لدى العضو.")

# ---------- بدء البوت (long polling) في خيط منفصل، ثم تشغيل سيرفر ويب بسيط ----------
def start_polling_in_thread():
    executor.start_polling(dp, skip_updates=True)

def run_webserver():
    async def handle(request):
        return web.Response(text="OK")
    app = web.Application()
    app.router.add_get("/", handle)
    port = int(os.getenv("PORT", "8000"))
    web.run_app(app, port=port)

if __name__ == "__main__":
    # تشغيل polling في خيط منفصل
    t = threading.Thread(target=start_polling_in_thread, daemon=True)
    t.start()
    # تشغيل سيرفر ويب (يمسك الـ $PORT ليتقبل Render)
    run_webserver()
