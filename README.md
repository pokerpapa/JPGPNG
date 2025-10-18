# JPGPNG — Telegram-бот для конвертации изображений и документов + водяные знаки

> Универсальный конвертер на основе **aiogram v3**, **Pillow**, **pillow-heif**, **LibreOffice/soffice**, **pdf2docx**, **python-docx**, **PyPDF2**, **reportlab**.  
> Умеет:
> - JPG/PNG/GIF/HEIC/фото → в нужный формат (кнопки в Telegram)
> - DOCX → PDF и PDF → DOCX
> - Водяной знак (PDF: каждую страницу, DOCX: текст/футер)
> - Статистика и рассылка для админа

---

## ✨ Возможности

- 📥 Принимает **фото** и **документы**
- 🖼 Конвертация изображений в: **JPG**, **PNG**, **GIF**, **HEIC**
- 📄 Конвертация документов: **DOCX ⇄ PDF**
- 🏷 Водяной знак:
  - PDF: поверх каждой страницы
  - DOCX: текст в футере
- 👥 Хранит пользователей, считает загрузки по форматам
- 📊 Команды админа: `/stats`, `/users`, `/broadcast`
- 🔒 Опциональная проверка подписки на канал перед использованием

---

## 🗂 Структура проекта

```text
JPGPNG/
├─ main.py                 # Основная логика бота
├─ watermark_utils.py      # Утилиты наложения водяных знаков (PDF/DOCX)
├─ downloads/              # Временные входные файлы (runtime)
├─ converted/              # Готовые файлы для выдачи (runtime)
├─ bot_users.db            # SQLite база пользователей/статистики (runtime)
├─ .env                    # Секреты/настройки (НЕ коммитить)
└─ .venv/                  # Виртуальное окружение (локально)


🔧 Требования

Python 3.10+

LibreOffice (Windows: soffice) или на Linux libreoffice в PATH — для DOCX→PDF

Git

Telegram Bot Token

Рекомендуемые Python-зависимости (см. requirements.txt ниже):

aiogram>=3

pillow, pillow-heif

python-dotenv

pdf2docx

python-docx

PyPDF2

reportlab

⚙️ Установка и запуск
git clone https://github.com/pokerpapa/JPGPNG.git
cd JPGPNG

python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/Mac:
# source .venv/bin/activate

pip install -r requirements.txt


Создайте .env в корне (минимум):

TELEGRAM_API_TOKEN=xxxxxxxxxxxxxxxxxxxxxxxxxxxx
ADMIN_USER_ID=6139103896
REQUIRED_CHANNEL=@projkino         # или отключите проверку в коде


Запуск:

python main.py

💬 Команды/поведение

/start — приветствие и подсказки

Отправьте изображение (фото/документ JPG/PNG/GIF/HEIC) — бот предложит целевой формат

Отправьте DOCX — вернёт PDF (с вопросом о водяном знаке)

Отправьте PDF — вернёт DOCX (с вопросом о водяном знаке)

/stats (админ) — статистика конвертаций

/users (админ) — количество пользователей

/broadcast (админ) — рассылка: отправьте сообщение → подтвердите

Ограничения по умолчанию:

Макс размер изображения: 40 MB

Макс площадь: 64 000 000 пикселей (≈ 8000×8000)

🧱 Технологии

aiogram v3 — Telegram-бот

Pillow / pillow-heif — работа с изображениями и HEIC/HEIF

LibreOffice/soffice — DOCX → PDF

pdf2docx — PDF → DOCX

python-docx — водяной знак в DOCX

PyPDF2 + reportlab — водяной знак в PDF

SQLite — пользователи и статистика

python-dotenv — конфигурация через .env

🛡 Безопасность и эксплуатация

Не коммитьте: .env, bot_users.db, директории downloads/, converted/

Рекомендуется запускать в изолированном окружении (venv, Docker)

Следите за размером/количеством временных файлов (они удаляются, но проверяйте)

🧪 Requirements (пример)

Создайте requirements.txt:

aiogram>=3.4
pillow>=10
pillow-heif>=0.15
python-dotenv>=1.0
pdf2docx>=0.5
python-docx>=1.1
PyPDF2>=3.0
reportlab>=4.0


Установка:

pip install -r requirements.txt
