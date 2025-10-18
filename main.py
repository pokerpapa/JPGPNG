import os
import asyncio
import uuid
import glob
import subprocess
import logging
import sqlite3
import platform

from datetime import datetime
from collections import defaultdict
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import (
    Message, CallbackQuery, FSInputFile, ChatMember,
    InlineKeyboardMarkup, InlineKeyboardButton
)
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter, TelegramBadRequest
from aiogram.client.default import DefaultBotProperties

from PIL import Image
from pillow_heif import register_heif_opener
from watermark_utils import add_pdf_watermark, add_docx_text_watermark

# ─────────────────────────── Pillow HEIF support ─────────────────────────── #
register_heif_opener()

# ─────────────────────────── ENV + LOGGING ───────────────────────────────── #
load_dotenv()
BOT_TOKEN       = os.getenv("TELEGRAM_API_TOKEN")
ADMIN_USER_ID   = os.getenv("ADMIN_USER_ID", "6139103896")
REQUIRED_CHANNEL = os.getenv("REQUIRED_CHANNEL", "@cryptomanevry")

promo_kb = InlineKeyboardMarkup(inline_keyboard=[[
    InlineKeyboardButton(
        text="ВСЕ ФИЛЬМЫ БЕСПЛАТНО ТУТ🍿",
        url=f"https://t.me/Bestleonfilm_bot"
    )
]])

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    filename="bot.log",
    filemode="a"
)
logger = logging.getLogger(__name__)

# ─────────────────────────── DIRECTORIES ──────────────────────────────────── #
DOWNLOAD_DIR = "downloads"
OUTPUT_DIR   = "converted"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

# ─────────────────────────── IMAGE CONVERSION CONSTS ─────────────────────── #
MAX_IMG_BYTES = 40 * 1024 * 1024      # 40 MB
MAX_PIXELS    = 64_000_000            # ~8000×8000 pixels

CANON = {
    "jpeg": "jpg", "jpg": "jpg",
    "png":  "png",
    "gif":  "gif",
    "heif": "heic", "heic": "heic",
}
def norm(ext: str) -> str:
    return CANON.get(ext.lower(), ext.lower())

IN_IMG_FORMATS  = set(CANON) | {"photo"}
OUT_IMG_FORMATS = ("jpg", "png", "gif", "heic")
PENDING_IMG: dict[str, dict] = {}

# ─────────────────────────── USER DB ──────────────────────────────────────── #
class UserDatabase:
    """Работа с базой пользователей и статистикой конвертаций."""
    def __init__(self, db_path="bot_users.db"):
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.cursor = self.conn.cursor()
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY
            )
        ''')
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS download_stats (
                user_id INTEGER,
                format TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        self.conn.commit()
        self.users_cache = self._load_users()

    def _load_users(self):
        self.cursor.execute('SELECT user_id FROM users')
        return {row[0] for row in self.cursor.fetchall()}

    def add_user(self, user_id: int):
        if user_id not in self.users_cache:
            self.cursor.execute(
                'INSERT OR IGNORE INTO users (user_id) VALUES (?)',
                (user_id,)
            )
            self.conn.commit()
            self.users_cache.add(user_id)

    def get_all_users(self):
        return self.users_cache

    def add_download(self, user_id: int, file_format: str):
        self.cursor.execute(
            'INSERT INTO download_stats (user_id, format) VALUES (?, ?)',
            (user_id, file_format)
        )
        self.conn.commit()

    def get_stats(self):
        self.cursor.execute('''
            SELECT format, COUNT(*) AS count
            FROM download_stats
            GROUP BY format
            ORDER BY count DESC
        ''')
        stats = self.cursor.fetchall()
        self.cursor.execute('SELECT COUNT(*) FROM download_stats')
        total = self.cursor.fetchone()[0]
        return stats, total

db = UserDatabase()

# ─────────────────────────── BOT INIT ─────────────────────────────────────── #
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp  = Dispatcher()

# ─────────────────────────── SUBSCRIPTION MIDDLEWARE ──────────────────────── #
class SubscriptionMiddleware:
    async def __call__(self, handler, event, data):
        uid = None
        if hasattr(event, "message") and event.message:
            uid = event.message.from_user.id
        elif hasattr(event, "callback_query") and event.callback_query:
            uid = event.callback_query.from_user.id

        if uid is None or str(uid) == ADMIN_USER_ID:
            return await handler(event, data)

        try:
            member: ChatMember = await bot.get_chat_member(REQUIRED_CHANNEL, uid)
            if member.status in ("left", "kicked"):
                text = (
                    "🚀 <b>Всего одна подписка (и всего на один канал!) — и бот ваш!</b>\n\n"
                    "Чтобы продолжить, присоединяйтесь к нашему каналу <b>@projkino</b> — это займет 10 секунд!\n\n"
                    "✅ Никаких скрытых условий — только доступ к крутым возможностям.\n"
                    "❤️ Для нас это важно — так мы видим, что вы часть команды!\n\n"
                    "👉 https://t.me/projkino\n\n"
                    "🔄 После подписки нажмите <b>/start</b>, чтобы активировать бота!"
                )
                kb = InlineKeyboardMarkup(inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="Присоединиться ▶️",
                            url=f"https://t.me/{REQUIRED_CHANNEL.strip('@')}"
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            text="Проверить подписку 🔄",
                            callback_data="check_sub"
                        )
                    ]
                ])
                target = event.message or event.callback_query.message
                await target.answer(text, reply_markup=kb)
                return
        except TelegramBadRequest:
            await bot.send_message(
                uid,
                "⚠️ Не могу проверить подписку — дайте боту права администратора."
            )
            return

        return await handler(event, data)


dp.update.middleware(SubscriptionMiddleware())

@dp.callback_query(F.data == "check_sub")
async def check_sub_handler(call: CallbackQuery):
    await call.answer()
    await call.message.edit_reply_markup(None)
    db.add_user(call.from_user.id)
    await call.message.answer(
        "👋 Привет! Я ваш универсальный бот‑конвертер.\n\n"
        "📄 Документы:\n"
        "  • Отправьте мне .docx — и я верну PDF.\n"
        "  • Отправьте мне .pdf — и я верну DOCX.\n\n"
        "🖼️ Изображения:\n"
        "  • Пришлите JPG/PNG/GIF/HEIC или просто фотографию —\n"
        "    я предложу нужные форматы для конвертации.\n\n"
        "❗️ Максимальный размер файла: <b>40 MB</b>.\n"
        "🔄 Всего пару кликов — и готовый файл у вас!"
    )


# ─────────────────────────── DOC ↔ PDF ────────────────────────────────────── #
def convert_docx_to_pdf(input_path: str, output_dir: str):
    cmd = "soffice" if platform.system()=="Windows" else "libreoffice"
    subprocess.run([
        cmd, "--headless", "--convert-to", "pdf",
        "--outdir", output_dir, input_path
    ], check=True)

def convert_pdf_to_docx(input_path: str, output_path: str):
    from pdf2docx import Converter
    cv = Converter(input_path)
    cv.convert(output_path)
    cv.close()

pending_watermarks: dict[int, tuple[str, str]] = {}

# ─────────────────────────── IMAGE CONVERSION UTILS ──────────────────────── #
def img_kb(uid: str, cur_ext: str) -> InlineKeyboardMarkup:
    btns = [
        InlineKeyboardButton(
            text=f.upper(),
            callback_data=f"imgconv:{uid}:{f}"
        )
        for f in OUT_IMG_FORMATS
        if not (cur_ext != "photo" and f == cur_ext)
    ]
    btns.append(InlineKeyboardButton(text="Отмена", callback_data=f"imgcancel:{uid}"))
    # разбить на строки по 3 кнопки
    rows = [btns[i:i+3] for i in range(0, len(btns)-1, 3)]
    rows.append([btns[-1]])
    return InlineKeyboardMarkup(inline_keyboard=rows)

async def download_img_and_ask(
    m: Message,
    file_id: str,
    ext: str,
    name: str,
    size: int
):
    if size > MAX_IMG_BYTES:
        return await m.answer(f"❌ Файл слишком большой. Макс {MAX_IMG_BYTES//1024//1024} MB.")
    uid = uuid.uuid4().hex
    in_path = os.path.join(DOWNLOAD_DIR, f"{uid}_{name}")
    await m.answer("📥 Загружаю изображение…")
    try:
        await bot.download(file_id, destination=in_path)
    except Exception as e:
        logger.error("Ошибка загрузки: %s", e)
        return await m.answer("❌ Не удалось скачать файл.")
    PENDING_IMG[uid] = {"input": in_path, "ext": ext, "user": m.from_user.id}
    await m.answer("📂 Выберите формат конвертации:", reply_markup=img_kb(uid, ext))

# ─────────────────────────── HANDLERS: IMAGES ────────────────────────────── #
@dp.message(lambda m: m.photo is not None)
async def on_photo(m: Message):
    ph = m.photo[-1]
    await download_img_and_ask(
        m, ph.file_id, "photo",
        f"{uuid.uuid4().hex}.jpg", ph.file_size or 0
    )

@dp.message(lambda m: m.document is not None and norm((m.document.file_name or "").split('.')[-1]) in IN_IMG_FORMATS)
async def on_image_doc(m: Message):
    doc = m.document
    ext_raw = (doc.file_name or "").split('.')[-1]
    ext = norm(ext_raw)
    await download_img_and_ask(m, doc.file_id, ext, doc.file_name, doc.file_size or 0)

@dp.callback_query(lambda c: c.data and c.data.startswith("imgconv:"))
async def do_img_convert(c: CallbackQuery):
    _, uid, to_ext = c.data.split(":")
    task = PENDING_IMG.pop(uid, None)
    if not task:
        return await c.answer("⏳ Время выбора истекло.", show_alert=True)

    src, from_ext, user_id = task["input"], task["ext"], task["user"]
    # Проверка разрешения
    try:
        with Image.open(src) as img:
            w,h = img.size
    except:
        os.remove(src)
        return await c.answer("❌ Не изображение.", show_alert=True)
    if w*h > MAX_PIXELS:
        os.remove(src)
        return await c.answer(
            f"❌ Слишком высокое разрешение (> {MAX_PIXELS:,} пикселей).",
            show_alert=True
        )

    dst = os.path.join(OUTPUT_DIR, f"{uid}.{to_ext}")
    await c.answer("⏳ Конвертирую…")
    loop = asyncio.get_running_loop()
    try:
        def _conv():
            img = Image.open(src)
            if to_ext == "jpg":
                img = img.convert("RGB")
                img.save(dst, "JPEG")
            elif to_ext == "png":
                img.save(dst, "PNG")
            elif to_ext == "gif":
                img.save(dst, "GIF")
            elif to_ext == "heic":
                img.save(dst, "HEIF", quality=80)
        await loop.run_in_executor(None, _conv)
        db.add_download(user_id, f"{from_ext}→{to_ext}")
        await bot.send_document(
            user_id,
            FSInputFile(dst),
            caption="✅ Ваш файл готов!",
            reply_markup=promo_kb
        )
        logger.info("Image converted %s → %s", src, dst)
    except Exception as e:
        logger.error("Ошибка конвертации изображения: %s", e)
        await bot.send_message(user_id, f"⚠️ Ошибка: {e}")
    finally:
        for p in (src, dst):
            if os.path.exists(p):
                os.remove(p)
        try:
            await c.message.delete()
        except:
            pass

@dp.callback_query(lambda c: c.data and c.data.startswith("imgcancel:"))
async def do_img_cancel(c: CallbackQuery):
    _, uid = c.data.split(":")
    task = PENDING_IMG.pop(uid, None)
    if task and os.path.exists(task["input"]):
        os.remove(task["input"])
    await c.answer("❌ Отменено.", show_alert=False)
    await c.message.delete()

# ─────────────────────────── HANDLERS: /start ────────────────────────────── #
@dp.message(Command(commands=["start"]))
async def start_command(message: Message):
    db.add_user(message.from_user.id)
    await message.answer(
        "👋 Привет! Я ваш универсальный бот‑конвертер.\n\n"
        "📄 <b>Документы:</b>\n"
        "  • Отправьте мне <b>.docx</b> — и я верну PDF.\n"
        "  • Отправьте мне <b>.pdf</b> — и я верну DOCX.\n\n"
        "🖼️ <b>Изображения:</b>\n"
        "  • Пришлите JPG/PNG/GIF/HEIC или просто фотографию —\n"
        "    я предложу нужные форматы для конвертации.\n\n"
        "❗️ Максимальный размер файла: <b>40 MB</b>.\n"
        "🔄 Всего пару кликов — и готовый файл у вас!"
    )


@dp.message(lambda m: m.document is not None and not pending_watermarks.get(m.from_user.id))
async def handle_document(message: Message):
    doc = message.document
    file_name = doc.file_name or ""
    ext = file_name.split('.')[-1].lower()

    if ext not in ("docx", "pdf"):
        # это обработает image-doc выше
        return

    file_id = str(uuid.uuid4())
    input_path = os.path.join(DOWNLOAD_DIR, f"{file_id}_{file_name}")
    try:
        await message.answer("📥 Загружаю файл...")
        await bot.download(doc.file_id, destination=input_path)
    except Exception as e:
        logger.error("Ошибка скачивания: %s", e)
        return await message.answer("❌ Ошибка скачивания. Попробуйте позже.")

    loop = asyncio.get_running_loop()
    try:
        await message.answer("⏳ Идёт конвертация, подождите до 120 сек...")
        if ext == "docx":
            await loop.run_in_executor(None, convert_docx_to_pdf, input_path, OUTPUT_DIR)
            db.add_download(message.from_user.id, "docx→pdf")
            pattern = os.path.join(OUTPUT_DIR, f"{file_id}_*.pdf")
            files = glob.glob(pattern)
            if not files:
                raise Exception("PDF не найден")
            output_path = files[0]
        else:
            output_path = os.path.join(OUTPUT_DIR, f"{file_id}.docx")
            await loop.run_in_executor(None, convert_pdf_to_docx, input_path, output_path)
            db.add_download(message.from_user.id, "pdf→docx")

        pending_watermarks[message.from_user.id] = (output_path, ext)
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Добавить водяной знак", callback_data="wm_yes")],
            [InlineKeyboardButton(text="❌ Без водяного знака", callback_data="wm_no")],
        ])
        await message.answer("✅ Файл готов. Добавить водяной знак?", reply_markup=kb)

    except Exception as e:
        logger.error("Ошибка конвертации документа: %s", e)
        await message.answer(f"⚠️ Ошибка: {e}")
    finally:
        if os.path.exists(input_path):
            os.remove(input_path)

@dp.callback_query(F.data == "wm_yes")
async def wm_yes_handler(call: CallbackQuery):
    user = call.from_user.id
    info = pending_watermarks.pop(user, None)
    if not info:
        return await call.answer("Сессия устарела", show_alert=True)
    path, ext = info

    # создаём водяной знак
    wm_path = os.path.join(OUTPUT_DIR, f"wm_{os.path.basename(path)}")
    if ext == "docx":
        add_pdf_watermark(path, wm_path, watermark_text="https://t.me/cryptomanevry")
    else:
        add_docx_text_watermark(path, wm_path, text="https://t.me/cryptomanevry")

    # отправляем уже с promo_kb
    await bot.send_document(user, FSInputFile(wm_path), reply_markup=promo_kb)

    # убираем кнопки у предыдущего сообщения
    await call.message.edit_reply_markup(None)

    # чистим файлы
    os.remove(path)
    os.remove(wm_path)

@dp.callback_query(F.data == "wm_no")
async def wm_no_handler(call: CallbackQuery):
    user = call.from_user.id
    info = pending_watermarks.pop(user, None)
    if not info:
        return await call.answer("Сессия устарела", show_alert=True)
    path, _ = info

    # просто отправляем без водяного знака, но с promo_kb
    await bot.send_document(user, FSInputFile(path), reply_markup=promo_kb)

    await call.message.edit_reply_markup(None)
    os.remove(path)

# ─────────────────────────── BROADCAST ───────────────────────────────────── #
pending_broadcasts: dict[int, types.Message] = {}

@dp.message(Command(commands=["broadcast"]))
async def broadcast_command(message: Message):
    if str(message.from_user.id) != ADMIN_USER_ID:
        return await message.answer("⛔ Нет доступа.")
    pending_broadcasts[message.from_user.id] = True
    await message.answer("📩 Пришлите сообщение для рассылки.")

@dp.message(lambda m: pending_broadcasts.get(m.from_user.id))
async def handle_broadcast_message(message: Message):
    admin_id = message.from_user.id
    pending_broadcasts[admin_id] = message
    markup = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Подтвердить", callback_data="confirm_broadcast"),
        InlineKeyboardButton(text="❌ Отменить", callback_data="cancel_broadcast"),
    ]])
    await message.answer("🔎 Подтвердите отправку:", reply_markup=markup)

@dp.callback_query(F.data.in_(["confirm_broadcast", "cancel_broadcast"]))
async def handle_broadcast_confirmation(call: CallbackQuery):
    if str(call.from_user.id) != ADMIN_USER_ID:
        return await call.message.answer("⛔ Нет доступа.")
    if call.data == "cancel_broadcast":
        pending_broadcasts.pop(call.from_user.id, None)
        return await call.message.answer("❌ Рассылка отменена.")
    await call.message.answer("📤 Начинаю рассылку...")
    original = pending_broadcasts.pop(call.from_user.id, None)
    users = db.get_all_users()
    success, failed = 0, []
    for u in users:
        try:
            if original.text:
                await bot.send_message(u, original.text)
            elif original.photo:
                await bot.send_photo(u, original.photo[-1].file_id, caption=original.caption or "")
            elif original.video:
                await bot.send_video(u, original.video.file_id, caption=original.caption or "")
            elif original.audio:
                await bot.send_audio(u, original.audio.file_id, caption=original.caption or "")
            elif original.document:
                await bot.send_document(u, original.document.file_id, caption=original.caption or "")
            success += 1
        except TelegramForbiddenError:
            failed.append(u)
        except TelegramRetryAfter as e:
            await asyncio.sleep(e.retry_after + 1)
        except Exception:
            failed.append(u)
        await asyncio.sleep(0.05)
    await bot.send_message(call.message.chat.id,
        f"✅ Рассылка завершена: {success} пользователей. Не доставлено: {len(failed)}."
    )

# ─────────────────────────── ADMIN COMMANDS ───────────────────────────────── #
@dp.message(Command(commands=["stats"]))
async def cmd_stats(message: Message):
    if str(message.from_user.id) != ADMIN_USER_ID:
        return await message.answer("⛔ Нет доступа.")
    stats, total = db.get_stats()
    if not stats:
        return await message.answer("📊 Нет данных.")
    txt = "<b>📊 Статистика конвертаций</b>\n\n"
    for fmt, cnt in stats:
        txt += f"• <b>{fmt}</b>: {cnt} раз\n"
    txt += f"\nВсего: <b>{total}</b>"
    await message.answer(txt)

@dp.message(Command(commands=["users"]))
async def list_users(message: Message):
    if str(message.from_user.id) != ADMIN_USER_ID:
        return await message.answer("⛔ Нет доступа.")
    await message.answer(f"👥 Всего пользователей: <b>{len(db.get_all_users())}</b>")

# ─────────────────────────── RUN BOT ──────────────────────────────────────── #
async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
