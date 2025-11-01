import os
import re
import asyncio
import json
import requests
from bs4 import BeautifulSoup
from fake_useragent import UserAgent
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)

# === КОНФИГ ===
BOT_TOKEN = "8056909873:AAEOdLrPNRBGSmqpZ7o-jCnsbJWpmya-cGg"
ADMIN_ID = 847094720
USERS_FILE = "users.json"

# === КЛЮЧИ ===
DEPSEARCH_TOKEN = "NP1aOH6jeB0H9Mvx81cznexVixq7V2tB"
HLR_API_KEY = "ezfF7P9wcUHcmMz7Kc25kPFbwHaHHuSQ"

# === Состояния ===
WAITING_PHONE = "phone"
WAITING_VK = "vk"
WAITING_SHERLOCK = "sherlock"
WAITING_HLR = "hlr"
WAITING_EMAIL = "email"

# === ГЛОБАЛЬНЫЕ ===
ua = UserAgent()
user_active_msg = {}  # {user_id: message_id}

# === БАЗА ===
def load_users():
    if os.path.exists(USERS_FILE):
        with open(USERS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if "paid" in data:
                for uid in data["paid"]:
                    if str(uid) not in data.get("users", {}):
                        data["users"][str(uid)] = {}
                del data["paid"]
            return data
    return {"users": {}, "admins": [ADMIN_ID]}

def save_users():
    with open(USERS_FILE, 'w', encoding='utf-8') as f:
        json.dump(users_db, f, ensure_ascii=False, indent=2)

users_db = load_users()

# === ПОМОЩНИКИ ===
def has_access(user_id): return True
def is_admin(user_id): return user_id in users_db["admins"]
def input_phone(text):
    if re.match(r"^\d{11}$", text) and text.startswith("7"):
        return f"+{text}"
    return None

def input_email(text):
    if re.match(r"^[\w.-]+@[\w.-]+\.\w+$", text):
        return text
    return None

# === РАЗБИВКА ТЕКСТА ===
def split_message(text, max_len=4096):
    lines = text.split('\n')
    parts = []
    current = ""
    for line in lines:
        if len(current) + len(line) + 1 > max_len:
            if current:
                parts.append(current)
            current = line
        else:
            if current:
                current += "\n" + line
            else:
                current = line
    if current:
        parts.append(current)
    return parts

# === ПОИСКОВЫЕ ФУНКЦИИ ===
def search_phone(full_number):
    url = f"https://api.depsearch.digital/quest={full_number}?token={DEPSEARCH_TOKEN}"
    try:
        r = requests.get(url, timeout=15)
        if r.status_code == 200:
            data = r.json()
            results = data.get("results", [])
            number_clean = full_number[1:]
            lines = [
                f"Номер: +7 ({number_clean[1:4]}) {number_clean[4:7]}-{number_clean[7:9]}-{number_clean[9:]}",
                f"Найдено: {len(results)} записей", ""
            ]
            for res in results[:20]:
                for k, v in res.items():
                    if not v: continue
                    icon = {
                        'fio': 'ФИО', 'name': 'Имя', 'phone': 'Телефон', 'region': 'Регион',
                        'address': 'Адрес', 'birthdate': 'Дата рождения', 'bdate': 'ДР',
                        'snils': 'СНИЛС', 'inn': 'ИНН', 'email': 'Почта',
                        'city': 'Город', 'source': 'Источник', 'login': 'Логин', 'password': 'Пароль',
                        'record_date': 'Дата записи'
                    }.get(k, k.title())
                    lines.append(f"• {icon}: {v}")
                lines.append("")
            return "\n".join(lines)
        return "Не найдено"
    except Exception as e:
        print(f"[DEPSEARCH] Ошибка: {e}")
        return "Нет связи"

def search_vk(query):
    id_match = re.search(r'id(\d+)', query)
    if id_match: return parse_vk_profile(id_match.group(1))
    elif 'vk.com/' in query:
        shortname = query.split('vk.com/')[-1].split('?')[0].split('#')[0]
        if shortname and shortname != 'id':
            return parse_vk_by_shortname(shortname)
    return search_vk_by_name(query)

def parse_vk_profile(user_id):
    try:
        url = f"https://vk.com/id{user_id}"
        r = requests.get(url, headers={'User-Agent': ua.random}, timeout=15)
        if 'login' in r.url.lower() or r.status_code in [302, 403]:
            return f"ВК ID: {user_id}\nНик: [приватный]\nСсылка: {url}"
        soup = BeautifulSoup(r.text, 'html.parser')
        name = None
        tag = soup.find('h1', class_='page_name')
        if tag and tag.text.strip() and tag.text.strip() not in ['DELETED', 'Удалён']:
            name = tag.text.strip()
        if not name:
            tag = soup.find('meta', property='og:title')
            if tag and tag.get('content'):
                title = tag['content'].strip()
                if ' | ВКонтакте' in title:
                    name = title.replace(' | ВКонтакте', '').strip()
        if not name or name in ['DELETED', 'Удалён']:
            name = search_vk_name_from_yandex(user_id) or "[скрыт]"
        return f"ВК ID: {user_id}\nНик: {name}\nСсылка: {url}"
    except Exception as e:
        print(f"[VK] Ошибка: {e}")
        return "Ошибка ВК"

def parse_vk_by_shortname(shortname):
    try:
        url = f"https://vk.com/{shortname}"
        r = requests.get(url, headers={'User-Agent': ua.random}, timeout=15)
        if r.url != url:
            user_id = r.url.split('id')[-1]
            return parse_vk_profile(user_id)
        soup = BeautifulSoup(r.text, 'html.parser')
        name = soup.find('h1', class_='page_name')
        name = name.text.strip() if name and name.text.strip() else shortname
        return f"ВК: @{shortname}\nНик: {name}\nСсылка: {url}"
    except Exception as e:
        return "Профиль не найден"

def search_vk_by_name(query):
    try:
        dork = f"{query} site:vk.com/id"
        search_url = f"https://yandex.ru/search/?text={dork.replace(' ', '+')}"
        r = requests.get(search_url, headers={'User-Agent': ua.random}, timeout=15)
        soup = BeautifulSoup(r.text, 'html.parser')
        profiles = []
        for a in soup.find_all('a', href=re.compile(r'vk.com/id\d+'))[:10]:
            href = a['href']
            text = a.get_text(strip=True)
            id_match = re.search(r'id(\d+)', href)
            if id_match:
                profiles.append({'name': text or '—', 'id': id_match.group(1)})
        if profiles:
            lines = ["Профили ВК:"]
            for p in profiles:
                lines.append(f"• {p['name']}\n ID: {p['id']}\n vk.com/id{p['id']}\n")
            return "\n".join(lines)
        return "Ничего не найдено"
    except Exception as e:
        return "Dorks: ошибка"

def search_vk_name_from_yandex(user_id):
    try:
        dork = f"site:vk.com/id{user_id}"
        search_url = f"https://yandex.ru/search/?text={dork}"
        r = requests.get(search_url, headers={'User-Agent': ua.random}, timeout=15)
        soup = BeautifulSoup(r.text, 'html.parser')
        for a in soup.find_all('a', href=re.compile(rf'vk.com/id{user_id}')):
            text = a.get_text(strip=True)
            name_match = re.search(r'([А-ЯЁ][а-яё]+ [А-ЯЁ][а-яё]+)', text)
            if name_match:
                return name_match.group(1)
        return None
    except:
        return None

def search_sherlock(username):
    platforms = [
        {"name": "ВКонтакте", "url": f"https://vk.com/{username}"},
        {"name": "TikTok", "url": f"https://www.tiktok.com/@{username}"},
        {"name": "Telegram", "url": f"https://t.me/{username}"},
        {"name": "YouTube", "url": f"https://www.youtube.com/@{username}"},
        {"name": "Instagram", "url": f"https://www.instagram.com/{username}/"},
        {"name": "Twitter", "url": f"https://twitter.com/{username}"},
    ]
    results = []
    for p in platforms:
        try:
            r = requests.get(p["url"], headers={'User-Agent': ua.random}, timeout=10)
            if r.status_code == 200:
                soup = BeautifulSoup(r.text, 'html.parser')
                title = soup.find('title').text if soup.find('title') else ''
                status = "Найден" if any(x in title.lower() for x in [p["name"].lower(), username.lower(), "@" + username.lower()]) else "Не найден"
                results.append(f"• {p['name']}: {p['url']} — {status}")
            else:
                results.append(f"• {p['name']}: {p['url']} — Не найден")
        except:
            results.append(f"• {p['name']}: {p['url']} — Ошибка")
    return "\n".join(results) or "Ничего не найдено"

def hlr_check(full_number):
    url = "https://api.apilayer.com/number_verification/validate"
    headers = {"apikey": HLR_API_KEY}
    try:
        r = requests.get(url, headers=headers, params={"number": full_number}, timeout=10)
        data = r.json()
        if data.get("valid"):
            return f"Активен\n• Номер: {data.get('international_format')}\n• Оператор: {data.get('carrier')}\n• Страна: {data.get('country_name')}\n• Тип: {data.get('line_type')}"
        return "Неактивен"
    except Exception as e:
        print(f"[HLR] Ошибка: {e}")
        return "HLR: Ошибка"

def search_email(email):
    url = f"https://api.depsearch.digital/quest={email}?token={DEPSEARCH_TOKEN}"
    try:
        r = requests.get(url, timeout=15)
        if r.status_code == 200:
            data = r.json()
            results = data.get("results", [])
            lines = [f"Email: {email}", f"Найдено: {len(results)} записей", ""]
            for res in results[:20]:
                for k, v in res.items():
                    if not v: continue
                    icon = {
                        'fio': 'ФИО', 'name': 'Имя', 'phone': 'Телефон', 'region': 'Регион',
                        'address': 'Адрес', 'birthdate': 'Дата рождения', 'bdate': 'ДР',
                        'snils': 'СНИЛС', 'inn': 'ИНН', 'email': 'Почта',
                        'city': 'Город', 'source': 'Источник', 'login': 'Логин', 'password': 'Пароль',
                        'record_date': 'Дата записи'
                    }.get(k, k.title())
                    lines.append(f"• {icon}: {v}")
                lines.append("")
            return "\n".join(lines)
        return "Ошибка сервера"
    except:
        return "Нет связи"

# === КЛАВИАТУРЫ ===
def get_main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Поиск по телефону", callback_data="phone")],
        [InlineKeyboardButton("Поиск по VK", callback_data="vk")],
        [InlineKeyboardButton("OSINT Sherlock", callback_data="sherlock")],
        [InlineKeyboardButton("HLR-проверка", callback_data="hlr")],
        [InlineKeyboardButton("Поиск по email", callback_data="email")],
    ])

def get_back_menu():
    return InlineKeyboardMarkup([[InlineKeyboardButton("Вернуться в меню", callback_data="back_to_menu")]])

# === СТАРТ ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if str(user_id) not in users_db["users"]:
        users_db["users"][str(user_id)] = {}
        save_users()
    caption = "Psycho Bot\nВыберите функцию:"
    photo_path = "icon.png" if os.path.exists("icon.png") else None
    if photo_path:
        with open(photo_path, "rb") as photo:
            msg = await update.message.reply_photo(photo, caption=caption, reply_markup=get_main_menu())
    else:
        msg = await update.message.reply_text(caption, reply_markup=get_main_menu())
    user_active_msg[user_id] = msg.message_id

# === КНОПКИ ===
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    chat_id = query.message.chat_id
    msg_id = query.message.message_id
    if query.data == "back_to_menu":
        caption = "Psycho Bot\nВыберите функцию:"
        photo_path = "icon.png" if os.path.exists("icon.png") else None
        try:
            if photo_path:
                with open(photo_path, "rb") as photo:
                    await context.bot.edit_message_media(
                        chat_id=chat_id,
                        message_id=msg_id,
                        media=InputMediaPhoto(photo, caption=caption),
                        reply_markup=get_main_menu()
                    )
            else:
                await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=msg_id,
                    text=caption,
                    reply_markup=get_main_menu()
                )
        except Exception as e:
            print(f"[BACK EDIT ERROR] {e}")
            if photo_path:
                with open(photo_path, "rb") as photo:
                    msg = await context.bot.send_photo(chat_id, photo, caption=caption, reply_markup=get_main_menu())
            else:
                msg = await context.bot.send_message(chat_id, caption, reply_markup=get_main_menu())
            user_active_msg[user_id] = msg.message_id
        return
    prompts = {
        "phone": "Введите номер без + (11 цифр, начиная с 7):",
        "vk": "Введите VK ID, ссылку или ФИО:",
        "sherlock": "Введите ник (без @):",
        "hlr": "Введите номер без + для HLR:",
        "email": "Введите email:",
    }
    prompt_text = prompts.get(query.data, "Неизвестная команда")
    photo_path = "icon.png" if os.path.exists("icon.png") else None
    try:
        if photo_path:
            with open(photo_path, "rb") as photo:
                await context.bot.edit_message_media(
                    chat_id=chat_id,
                    message_id=msg_id,
                    media=InputMediaPhoto(photo, caption=prompt_text),
                    reply_markup=None
                )
        else:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=msg_id,
                text=prompt_text
            )
    except Exception as e:
        print(f"[PROMPT EDIT ERROR] {e}")
        if photo_path:
            with open(photo_path, "rb") as photo:
                msg = await context.bot.send_photo(chat_id, photo, caption=prompt_text)
        else:
            msg = await context.bot.send_message(chat_id, prompt_text)
        user_active_msg[user_id] = msg.message_id
    context.user_data.setdefault(user_id, {})["state"] = query.data

# === ОТПРАВКА РЕЗУЛЬТАТА С search.png ===
async def send_result(context, chat_id, user_id, result_text):
    msg_id = user_active_msg.get(user_id)
    search_photo_path = "search.png" if os.path.exists("search.png") else ("icon.png" if os.path.exists("icon.png") else None)
    parts = split_message(result_text)
    for i, part in enumerate(parts):
        is_last = i == len(parts) - 1
        markup = get_back_menu() if is_last else None
        try:
            if search_photo_path and i == 0 and len(part) <= 1024:
                with open(search_photo_path, "rb") as photo:
                    if msg_id:
                        await context.bot.edit_message_media(
                            chat_id=chat_id,
                            message_id=msg_id,
                            media=InputMediaPhoto(photo, caption=part),
                            reply_markup=markup
                        )
                    else:
                        msg = await context.bot.send_photo(chat_id, photo, caption=part, reply_markup=markup)
                        user_active_msg[user_id] = msg.message_id
            else:
                if msg_id and i == 0:
                    await context.bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=msg_id,
                        text=part,
                        reply_markup=markup
                    )
                else:
                    msg = await context.bot.send_message(chat_id, part, reply_markup=markup)
                    if is_last:
                        user_active_msg[user_id] = msg.message_id
        except Exception as e:
            print(f"[RESULT ERROR] {e}")
            msg = await context.bot.send_message(chat_id, part, reply_markup=markup)
            if is_last:
                user_active_msg[user_id] = msg.message_id

# === ВВОД (УДАЛЕНИЕ СООБЩЕНИЯ ПОЛЬЗОВАТЕЛЯ) ===
async def handle_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    user_message = update.message
    text = user_message.text.strip()
    state = context.user_data.get(user_id, {}).get("state")
    if not state:
        return
    result = ""
    if state == WAITING_PHONE:
        full = input_phone(text)
        result = search_phone(full) if full else "Ошибка: 11 цифр, начиная с 7"
    elif state == WAITING_VK:
        result = search_vk(text)
    elif state == WAITING_SHERLOCK:
        result = search_sherlock(text)
    elif state == WAITING_HLR:
        full = input_phone(text)
        result = hlr_check(full) if full else "Ошибка: 11 цифр, начиная с 7"
    elif state == WAITING_EMAIL:
        valid_email = input_email(text)
        result = search_email(valid_email) if valid_email else "Неверный email"
    context.user_data[user_id].pop("state", None)
    # Удаление сообщения пользователя
    try:
        await user_message.delete()
    except Exception as e:
        print(f"[DELETE USER MSG] {e}")
    # Отправка результата
    await send_result(context, update.message.chat_id, user_id, result)

# === АДМИНКА ===
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    await update.message.reply_text("Админка:\n/stats — статистика\n/broadcast — рассылка")

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    await update.message.reply_text(f"Пользователей: {len(users_db['users'])}")

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("Использование: /broadcast <текст>")
        return
    text = " ".join(context.args)
    users = list(users_db["users"].keys())
    keyboard = [
        [InlineKeyboardButton("Отправить", callback_data="confirm_broadcast")],
        [InlineKeyboardButton("Отмена", callback_data="cancel_broadcast")]
    ]
    context.user_data[update.effective_user.id]["broadcast_text"] = text
    context.user_data[update.effective_user.id]["broadcast_users"] = users
    await update.message.reply_text(f"Кому: {len(users)}\n\n{text}", reply_markup=InlineKeyboardMarkup(keyboard))

async def confirm_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    if not is_admin(user_id):
        return
    text = context.user_data[user_id].get("broadcast_text")
    users = context.user_data[user_id].get("broadcast_users", [])
    sent = 0
    for uid in users:
        try:
            await context.bot.send_message(int(uid), text)
            sent += 1
            await asyncio.sleep(0.03)
        except:
            pass
    await query.message.reply_text(f"Отправлено: {sent}")
    context.user_data[user_id].pop("broadcast_text", None)
    context.user_data[user_id].pop("broadcast_users", None)

async def cancel_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    context.user_data[user_id].pop("broadcast_text", None)
    context.user_data[user_id].pop("broadcast_users", None)
    await query.edit_message_text("Рассылка отменена")

# === ЗАПУСК ===
def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("broadcast", broadcast))
    app.add_handler(CallbackQueryHandler(button_handler, pattern="^(phone|vk|sherlock|hlr|email|back_to_menu)$"))
    app.add_handler(CallbackQueryHandler(confirm_broadcast, pattern="^confirm_broadcast$"))
    app.add_handler(CallbackQueryHandler(cancel_broadcast, pattern="^cancel_broadcast$"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_input))
    print("Psycho Bot — ЗАПУЩЕН! (Полный код + админка + удаление сообщений)")
    app.run_polling()

if __name__ == "__main__":
    main()
