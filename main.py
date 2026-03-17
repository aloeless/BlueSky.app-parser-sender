# -*- coding: utf-8 -*-
import asyncio
import logging
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, F, Router
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, Update, ReplyKeyboardMarkup, KeyboardButton, FSInputFile
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

from config import BOT_TOKEN, ADMINS, SUBSCRIPTION_PLANS, REFERRAL_BONUS, MIN_DEPOSIT, LANGUAGES
from database import (
    init_db, create_user, get_user, update_balance, add_subscription,
    has_active_subscription, increment_search_count, get_user_stats,
    add_referral_bonus, get_referral_stats, load_blacklist, add_trial_subscription,
    add_to_blacklist, clear_blacklist, get_db,
    # Новые функции для раздельных подписок
    add_parser_subscription, add_sender_subscription, add_combo_subscription,
    has_parser_subscription, has_sender_subscription,
    # Функции для сендера
    save_bluesky_account, get_bluesky_account
)
from crypto_payment import create_crypto_invoice, check_invoices_task, check_single_invoice
from bluesky_parser import run_parser_for_user, cancel_parser_for_user, shutdown_parsers
from bluesky_sender import run_sender, cancel_sender_for_user, shutdown_senders, parse_profile_links

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
router = Router()
dp.include_router(router)

# Глобальная переменная для username бота (заполняется при старте)
bot_username = "bot"

class AdminStates(StatesGroup):
    waiting_balance_amount = State()
    waiting_sub_days = State()
    waiting_sub_user_id = State()
    waiting_balance_user_id = State()
    waiting_blacklist_handle = State()
    waiting_broadcast_message = State()
    waiting_broadcast_confirm = State()

class SearchStates(StatesGroup):
    waiting_keyword = State()
    waiting_amount = State()
    waiting_followers_count = State()
    waiting_profile_count = State()
    waiting_search_lang = State()

class SenderStates(StatesGroup):
    waiting_handle = State()
    waiting_password = State()
    waiting_file = State()
    waiting_message = State()

# Настройка парсера и сендера для использования бота
import bluesky_parser
import bluesky_sender
bluesky_parser.bot = bot
bluesky_parser.admins = set(ADMINS)
bluesky_sender.bot = bot

async def is_admin(user_id: int) -> bool:
    return user_id in ADMINS

def get_main_keyboard():
    keyboard = ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📋 Задачи"), KeyboardButton(text="💎 Подписка")],
        [KeyboardButton(text="💰 Пополнить баланс"), KeyboardButton(text="👤 Профиль")]
    ], resize_keyboard=True)
    return keyboard

def get_admin_keyboard():
    keyboard = ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📋 Задачи"), KeyboardButton(text="💎 Подписка")],
        [KeyboardButton(text="💰 Пополнить баланс"), KeyboardButton(text="👤 Профиль")],
        [KeyboardButton(text="⚙️ Админ")]
    ], resize_keyboard=True)
    return keyboard

@router.message(CommandStart())
async def start(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username or "unknown"
    first_name = message.from_user.first_name or "User"
    create_user(user_id, username, first_name)

    # ИСПРАВЛЕНО: Админы получают бесконечные подписки на парсер и сендер
    if await is_admin(user_id):
        with get_db() as conn:
            infinite_date = (datetime.now() + timedelta(days=36500)).isoformat()
            conn.execute(
                "UPDATE users SET parser_until = ?, sender_until = ? WHERE user_id = ?",
                (infinite_date, infinite_date, user_id)
            )
            logger.info(f"[ADMIN] Infinite subscriptions granted to admin {user_id}")

    try:
        photo = FSInputFile("banner.jpg")
        await message.answer_photo(
            photo=photo,
            caption=(
                "🤖 <b>Bluesky Profile Parser Bot</b>\n\n"
                "👋 Добро пожаловать!\n\n"
                "Бот для поиска профилей в Bluesky по различным параметрам.\n\n"
                "<b>Возможности:</b>\n"
                "🔍 Поиск профилей\n"
                "💎 Подписки на функции\n"
                "💰 Пополнение баланса\n"
                "👤 Просмотр профиля"
            ),
            parse_mode="HTML",
            reply_markup=get_admin_keyboard() if await is_admin(user_id) else get_main_keyboard()
        )
    except:
        text = (
            "🤖 <b>Bluesky Profile Parser Bot</b>\n\n"
            "👋 Добро пожаловать!\n\n"
            "Бот для поиска профилей в Bluesky по различным параметрам.\n\n"
            "<b>Возможности:</b>\n"
            "🔍 Поиск профилей\n"
            "💎 Подписки на функции\n"
            "💰 Пополнение баланса\n"
            "👤 Просмотр профиля"
        )
        await message.answer(text, parse_mode="HTML", reply_markup=get_admin_keyboard() if await is_admin(user_id) else get_main_keyboard())

@router.message(F.text == "👤 Профиль")
async def profile_view(message: Message):
    user_id = message.from_user.id
    user = get_user(user_id)
    if not user:
        await message.answer("❌ Пользователь не найден")
        return

    # Проверка раздельных подписок
    parser_active = has_parser_subscription(user_id)
    sender_active = has_sender_subscription(user_id)
    parser_status = "✅ Активна" if parser_active else "❌ Нет"
    sender_status = "✅ Активна" if sender_active else "❌ Нет"

    ref_stats = get_referral_stats(user_id)
    ref_link = f"https://t.me/{bot_username}?start={user_id}"

    text = (
        f"👤 <b>Ваш профиль</b>\n\n"
        f"🆔 ID: <code>{user_id}</code>\n"
        f"👤 Имя: {user['first_name']}\n\n"
        f"📊 <b>Подписки:</b>\n"
        f"🔍 Парсер: {parser_status}\n"
        f"📤 Сендер: {sender_status}\n\n"
        f"💰 Баланс: ${user['balance']:.2f}\n"
        f"🔍 Поисков: {user['searches_count']}\n\n"
        f"🎁 Рефералов: {ref_stats['count']}\n"
        f"💵 Заработано: ${ref_stats['total_bonus']:.2f}\n\n"
        f"🔗 Реф. ссылка:\n<code>{ref_link}</code>"
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 Пополнить баланс", callback_data="deposit_menu")],
        [InlineKeyboardButton(text="🏠 Главная", callback_data="go_start")]
    ])

    await message.answer(text, parse_mode="HTML", reply_markup=keyboard)

@router.message(F.text == "📋 Задачи")
async def tasks_menu(message: Message):
    user_id = message.from_user.id

    text = "📋 <b>Выберите задачу:</b>\n\n"
    text += "🔍 <b>Парсер</b> - поиск профилей по ключевым словам\n"
    text += "📤 <b>Сендер</b> - массовая отправка DM сообщений\n\n"

    # Проверка подписок
    has_parser = has_parser_subscription(user_id)
    has_sender = has_sender_subscription(user_id)

    buttons = []

    if has_parser:
        buttons.append([InlineKeyboardButton(text="🔍 Парсер", callback_data="task_parser")])
    else:
        buttons.append([InlineKeyboardButton(text="🔍 Парсер (❌ Нет подписки)", callback_data="no_parser_sub")])

    if has_sender:
        buttons.append([InlineKeyboardButton(text="📤 Сендер", callback_data="task_sender")])
    else:
        buttons.append([InlineKeyboardButton(text="📤 Сендер (❌ Нет подписки)", callback_data="no_sender_sub")])

    buttons.append([InlineKeyboardButton(text="🏠 Главная", callback_data="go_start")])

    await message.answer(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

@router.callback_query(F.data == "task_parser")
async def start_parser_task(callback: CallbackQuery):
    user_id = callback.from_user.id
    if not has_parser_subscription(user_id):
        await callback.answer("❌ Требуется подписка на Парсер")
        return

    text = "🌍 <b>Выберите язык для парсинга:</b>"
    buttons = []
    for lang_code, lang_name in LANGUAGES.items():
        buttons.append([InlineKeyboardButton(text=lang_name, callback_data=f"search_lang_{lang_code}")])

    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()

@router.callback_query(F.data == "no_parser_sub")
async def no_parser_subscription(callback: CallbackQuery):
    await callback.answer("❌ У вас нет подписки на Парсер. Купите подписку в разделе 💎 Подписка", show_alert=True)

@router.callback_query(F.data == "no_sender_sub")
async def no_sender_subscription(callback: CallbackQuery):
    await callback.answer("❌ У вас нет подписки на Сендер. Купите подписку в разделе 💎 Подписка", show_alert=True)

@router.callback_query(F.data.startswith("search_lang_"))
async def select_search_lang(callback: CallbackQuery, state: FSMContext):
    lang = callback.data.split("_")[2]
    await state.update_data(search_lang=lang)
    await callback.message.edit_text("🔍 Введите ключевое слово для поиска:")
    await state.set_state(SearchStates.waiting_keyword)
    await callback.answer()

@router.message(SearchStates.waiting_keyword)
async def process_keyword(message: Message, state: FSMContext):
    await state.update_data(keyword=message.text.strip())
    await message.answer("👥 Сколько максимальное количество подписчиков?\n\nПример: 1000")
    await state.set_state(SearchStates.waiting_followers_count)

@router.message(SearchStates.waiting_followers_count)
async def process_followers_count(message: Message, state: FSMContext):
    try:
        max_followers = int(message.text.strip())
        await state.update_data(max_followers=max_followers)
        await message.answer("📊 Сколько профилей найти?\n\nПример: 20")
        await state.set_state(SearchStates.waiting_profile_count)
    except ValueError:
        await message.answer("❌ Введите корректное число")

@router.message(SearchStates.waiting_profile_count)
async def process_profile_count(message: Message, state: FSMContext):
    try:
        profile_count = int(message.text.strip())
        data = await state.get_data()
        keyword = data.get('keyword', '')
        max_followers = data.get('max_followers', 1000)
        lang = data.get('search_lang', 'all')

        user_id = message.from_user.id

        if not has_parser_subscription(user_id):
            await message.answer("❌ Требуется подписка на Парсер")
            await state.clear()
            return

        blacklist = load_blacklist()
        await message.answer(
            f"🚀 Поиск запущен!\n"
            f"Ключевое слово: {keyword}\n"
            f"Макс подписчиков: {max_followers}\n"
            f"Искать профилей: {profile_count}\n"
            f"Язык: {lang}\n"
            f"Черный список: {len(blacklist)} профилей"
        )

        started = await run_parser_for_user(user_id, keyword, max_followers, profile_count)
        if not started:
            await message.answer("⚠️ Парсинг уже выполняется для вас")
        else:
            increment_search_count(user_id)

        await state.clear()
    except ValueError:
        await message.answer("❌ Введите корректное число")

# ========== СЕНДЕР ОБРАБОТЧИКИ ==========

@router.callback_query(F.data == "task_sender")
async def start_sender_task(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    if not has_sender_subscription(user_id):
        await callback.answer("❌ Требуется подписка на Сендер")
        return

    # Проверяем есть ли сохраненный аккаунт
    account = get_bluesky_account(user_id)

    if account:
        text = (
            f"📤 <b>Bluesky Сендер</b>\n\n"
            f"Сохраненный аккаунт: <code>{account['handle']}</code>\n\n"
            f"Используем этот аккаунт или введете новый?"
        )
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Использовать", callback_data="sender_use_saved")],
            [InlineKeyboardButton(text="🔄 Новый аккаунт", callback_data="sender_new_account")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="go_start")]
        ])
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)
    else:
        await callback.message.edit_text(
            "📤 <b>Bluesky Сендер</b>\n\n"
            "Введите handle (логин) вашего Bluesky аккаунта:\n\n"
            "Пример: <code>username.bsky.social</code>",
            parse_mode="HTML"
        )
        await state.set_state(SenderStates.waiting_handle)

    await callback.answer()

@router.callback_query(F.data == "sender_use_saved")
async def sender_use_saved_account(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    account = get_bluesky_account(user_id)

    if not account:
        await callback.answer("❌ Аккаунт не найден")
        return

    await state.update_data(sender_handle=account['handle'], sender_password=account['app_password'])
    await callback.message.edit_text(
        "📄 <b>Загрузите TXT файл</b> со ссылками на профили\n\n"
        "Файл должен содержать ссылки вида:\n"
        "<code>https://bsky.app/profile/username.bsky.social</code>\n\n"
        "Каждая ссылка с новой строки"
    )
    await state.set_state(SenderStates.waiting_file)
    await callback.answer()

@router.callback_query(F.data == "sender_new_account")
async def sender_new_account(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "📤 <b>Новый аккаунт</b>\n\n"
        "Введите handle (логин) вашего Bluesky аккаунта:\n\n"
        "Пример: <code>username.bsky.social</code>",
        parse_mode="HTML"
    )
    await state.set_state(SenderStates.waiting_handle)
    await callback.answer()

@router.message(SenderStates.waiting_handle)
async def process_sender_handle(message: Message, state: FSMContext):
    handle = message.text.strip()
    await state.update_data(sender_handle=handle)
    await message.answer(
        "🔑 <b>Введите App Password</b>\n\n"
        "Получить можно в настройках Bluesky:\n"
        "Settings → App Passwords → Add App Password\n\n"
        "Введите сгенерированный пароль:",
        parse_mode="HTML"
    )
    await state.set_state(SenderStates.waiting_password)

@router.message(SenderStates.waiting_password)
async def process_sender_password(message: Message, state: FSMContext):
    password = message.text.strip()
    data = await state.get_data()
    handle = data.get('sender_handle')

    await state.update_data(sender_password=password)

    # Сохраняем аккаунт в БД
    save_bluesky_account(message.from_user.id, handle, password)

    await message.answer(
        "✅ Аккаунт сохранен!\n\n"
        "📄 <b>Загрузите TXT файл</b> со ссылками на профили\n\n"
        "Файл должен содержать ссылки вида:\n"
        "<code>https://bsky.app/profile/username.bsky.social</code>\n\n"
        "Каждая ссылка с новой строки",
        parse_mode="HTML"
    )
    await state.set_state(SenderStates.waiting_file)

@router.message(SenderStates.waiting_file)
async def process_sender_file(message: Message, state: FSMContext):
    # Проверяем что это документ
    if not message.document:
        await message.answer("❌ Пожалуйста, отправьте TXT файл")
        return

    # Проверяем что это текстовый файл
    if not message.document.file_name.endswith('.txt'):
        await message.answer("❌ Файл должен быть в формате .txt")
        return

    try:
        # Скачиваем файл
        file = await bot.download(message.document)
        file_content = file.read().decode('utf-8')

        # Парсим ссылки
        target_handles = parse_profile_links(file_content)

        if not target_handles:
            await message.answer("❌ В файле не найдено ни одной ссылки на профиль")
            return

        await state.update_data(sender_targets=target_handles)
        await message.answer(
            f"✅ Загружено {len(target_handles)} профилей\n\n"
            f"💬 <b>Введите текст сообщения</b>, которое будет отправлено всем:\n\n"
            f"(Максимум 1000 символов)",
            parse_mode="HTML"
        )
        await state.set_state(SenderStates.waiting_message)

    except Exception as e:
        logger.error(f"Error processing file: {e}")
        await message.answer(f"❌ Ошибка обработки файла: {str(e)[:100]}")

@router.message(SenderStates.waiting_message)
async def process_sender_message(message: Message, state: FSMContext):
    message_text = message.text.strip()

    if len(message_text) > 1000:
        await message.answer("❌ Сообщение слишком длинное (макс 1000 символов)")
        return

    if len(message_text) < 1:
        await message.answer("❌ Сообщение не может быть пустым")
        return

    data = await state.get_data()
    handle = data.get('sender_handle')
    password = data.get('sender_password')
    targets = data.get('sender_targets', [])

    await message.answer(
        f"🚀 <b>Подтверждение отправки</b>\n\n"
        f"📤 Аккаунт: <code>{handle}</code>\n"
        f"👥 Получателей: <b>{len(targets)}</b>\n"
        f"💬 Сообщение:\n<i>{message_text[:200]}{'...' if len(message_text) > 200 else ''}</i>\n\n"
        f"Начать отправку?",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Начать", callback_data="sender_confirm")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="go_start")]
        ])
    )

    await state.update_data(sender_message=message_text)

@router.callback_query(F.data == "sender_confirm")
async def confirm_sender(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    handle = data.get('sender_handle')
    password = data.get('sender_password')
    targets = data.get('sender_targets', [])
    message_text = data.get('sender_message')

    user_id = callback.from_user.id

    # Запускаем сендер
    started = await run_sender(user_id, handle, password, targets, message_text)

    if started:
        await callback.message.edit_text("🚀 Отправка запущена! Ожидайте...")
    else:
        await callback.message.edit_text("⚠️ Не удалось запустить отправку")

    await state.clear()
    await callback.answer()

@router.message(F.text == "💎 Подписка")
async def subscription_menu(message: Message):
    user_id = message.from_user.id
    user = get_user(user_id)

    min_price = min(p['price'] for p in SUBSCRIPTION_PLANS.values())
    if user['balance'] < min_price:
        text = (
            f"❌ <b>Недостаточно средств</b>\n\n"
            f"Требуется минимум ${min_price:.2f}\n\n"
            f"Пополните баланс для активации подписки."
        )
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💰 Пополнить", callback_data="deposit_menu")],
            [InlineKeyboardButton(text="🏠 Главная", callback_data="go_start")]
        ])
        await message.answer(text, parse_mode="HTML", reply_markup=keyboard)
        return

    # Группируем подписки по типам
    text = "💎 <b>Выберите тип подписки:</b>\n\n"
    text += "🔍 <b>Парсер</b> - поиск профилей\n"
    text += "📤 <b>Сендер</b> - массовая отправка DM\n"
    text += "💎 <b>Комбо</b> - парсер + сендер (выгоднее!)\n\n"

    buttons = []

    # Парсер
    parser_plans = {k: v for k, v in SUBSCRIPTION_PLANS.items() if v['type'] == 'parser'}
    if parser_plans:
        for k, p in parser_plans.items():
            buttons.append([InlineKeyboardButton(text=f"🔍 {p['name']} - ${p['price']:.2f}", callback_data=f"sub_{k}")])

    # Сендер
    sender_plans = {k: v for k, v in SUBSCRIPTION_PLANS.items() if v['type'] == 'sender'}
    if sender_plans:
        for k, p in sender_plans.items():
            buttons.append([InlineKeyboardButton(text=f"📤 {p['name']} - ${p['price']:.2f}", callback_data=f"sub_{k}")])

    # Комбо
    combo_plans = {k: v for k, v in SUBSCRIPTION_PLANS.items() if v['type'] == 'combo'}
    if combo_plans:
        for k, p in combo_plans.items():
            buttons.append([InlineKeyboardButton(text=f"{p['emoji']} {p['name']} - ${p['price']:.2f}", callback_data=f"sub_{k}")])

    buttons.append([InlineKeyboardButton(text="🏠 Главная", callback_data="go_start")])

    await message.answer(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

@router.callback_query(F.data.startswith("sub_"))
async def buy_subscription(callback: CallbackQuery):
    # ИСПРАВЛЕНО: правильный парсинг для sub_parser_day и т.д.
    plan_id = callback.data.replace("sub_", "")
    if plan_id not in SUBSCRIPTION_PLANS:
        await callback.answer(f"❌ Неверный план: {plan_id}")
        logger.error(f"Unknown plan_id: {plan_id}, available: {list(SUBSCRIPTION_PLANS.keys())}")
        return

    plan = SUBSCRIPTION_PLANS[plan_id]
    user_id = callback.from_user.id
    user = get_user(user_id)

    if user['balance'] < plan['price']:
        await callback.answer("❌ Недостаточно средств")
        return

    update_balance(user_id, -plan['price'])

    # Активируем подписку в зависимости от типа
    sub_type = plan['type']
    days = plan.get('days', 0)
    hours = plan.get('hours', 0)

    if sub_type == 'parser':
        add_parser_subscription(user_id, days=days, hours=hours)
    elif sub_type == 'sender':
        add_sender_subscription(user_id, days=days, hours=hours)
    elif sub_type == 'combo':
        add_combo_subscription(user_id, days=days, hours=hours)

    text = (
        f"✅ <b>Подписка активирована!</b>\n\n"
        f"{plan['emoji']} {plan['name']}\n"
        f"💰 Списано: ${plan['price']:.2f}"
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Задачи", callback_data="task_menu_callback")],
        [InlineKeyboardButton(text="🏠 Главная", callback_data="go_start")]
    ])

    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)
    await callback.answer("✅ Подписка успешно активирована!")

@router.callback_query(F.data == "task_menu_callback")
async def task_menu_callback(callback: CallbackQuery):
    user_id = callback.from_user.id

    text = "📋 <b>Выберите задачу:</b>\n\n"
    text += "🔍 <b>Парсер</b> - поиск профилей по ключевым словам\n"
    text += "📤 <b>Сендер</b> - массовая отправка DM сообщений\n\n"

    # Проверка подписок
    has_parser = has_parser_subscription(user_id)
    has_sender = has_sender_subscription(user_id)

    buttons = []

    if has_parser:
        buttons.append([InlineKeyboardButton(text="🔍 Парсер", callback_data="task_parser")])
    else:
        buttons.append([InlineKeyboardButton(text="🔍 Парсер (❌ Нет подписки)", callback_data="no_parser_sub")])

    if has_sender:
        buttons.append([InlineKeyboardButton(text="📤 Сендер", callback_data="task_sender")])
    else:
        buttons.append([InlineKeyboardButton(text="📤 Сендер (❌ Нет подписки)", callback_data="no_sender_sub")])

    buttons.append([InlineKeyboardButton(text="🏠 Главная", callback_data="go_start")])

    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()

@router.message(F.text == "💰 Пополнить баланс")
async def deposit_menu(message: Message):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Создать счет", callback_data="create_invoice")],
        [InlineKeyboardButton(text="🏠 Главная", callback_data="go_start")]
    ])

    text = f"💰 <b>Пополнение баланса</b>\n\n"
    text += f"Минимальная сумма: ${MIN_DEPOSIT}\n\n"
    text += "<b>Доступные планы подписки:</b>\n"
    for k, p in SUBSCRIPTION_PLANS.items():
        text += f"{p['emoji']} {p['name']} - ${p['price']:.2f}\n"

    await message.answer(text, parse_mode="HTML", reply_markup=keyboard)

@router.callback_query(F.data == "deposit_menu")
async def deposit_menu_callback(callback: CallbackQuery):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Создать счет", callback_data="create_invoice")],
        [InlineKeyboardButton(text="🏠 Главная", callback_data="go_start")]
    ])

    text = f"💰 <b>Пополнение баланса</b>\n\n"
    text += f"Минимальная сумма: ${MIN_DEPOSIT}\n\n"
    text += "<b>Доступные планы подписки:</b>\n"
    for k, p in SUBSCRIPTION_PLANS.items():
        text += f"{p['emoji']} {p['name']} - ${p['price']:.2f}\n"

    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)
    await callback.answer()

@router.callback_query(F.data == "create_invoice")
async def create_invoice_start(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(f"💳 Введите сумму для пополнения (минимум ${MIN_DEPOSIT}):\n\nПример: 10")
    await state.set_state(SearchStates.waiting_amount)
    await callback.answer()

@router.message(SearchStates.waiting_amount)
async def process_invoice(message: Message, state: FSMContext):
    user_id = message.from_user.id
    try:
        amount = float(message.text.strip())
        if amount < MIN_DEPOSIT:
            await message.answer(f"❌ Сумма должна быть не менее ${MIN_DEPOSIT}")
            return

        loading_msg = await message.answer("⏳ Создаем счет на оплату...")

        # ИСПРАВЛЕНО: сначала отправляем сообщение, затем создаем инвойс с message_id
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⏳ Ожидание...", callback_data="waiting")]
        ])
        text = f"⏳ <b>Создание счета...</b>\n\n💰 Сумма: ${amount:.2f}"
        invoice_msg = await message.answer(text, parse_mode="HTML", reply_markup=keyboard)

        # Удаляем loading сообщение
        await loading_msg.delete()

        # Создаем инвойс с message_id
        pay_url = await create_crypto_invoice(user_id, amount, invoice_msg.message_id, message.chat.id)

        if pay_url:
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="💳 Оплатить", url=pay_url)],
                [InlineKeyboardButton(text="🏠 Главная", callback_data="go_start")]
            ])
            text = f"✅ <b>Счет создан!</b>\n\n💰 Сумма: ${amount:.2f}\n\nНажмите кнопку для оплаты."
            await invoice_msg.edit_text(text, parse_mode="HTML", reply_markup=keyboard)

            # Запускаем фоновую проверку этого конкретного инвойса для быстрого зачисления
            # Получаем invoice_id из БД
            with get_db() as conn:
                last_invoice = conn.execute(
                    "SELECT invoice_id FROM invoices WHERE user_id = ? AND status = 'pending' ORDER BY created_at DESC LIMIT 1",
                    (user_id,)
                ).fetchone()
                if last_invoice:
                    asyncio.create_task(check_single_invoice(last_invoice['invoice_id'], bot))
                    logger.info(f"[CRYPTO] Started instant checker for invoice {last_invoice['invoice_id']}")
        else:
            await invoice_msg.edit_text("❌ Ошибка создания счета. Попробуйте позже.")
    except ValueError:
        await message.answer("❌ Введите корректную сумму (число).")
    finally:
        await state.clear()

@router.message(F.text == "⚙️ Админ")
async def admin_panel(message: Message):
    if not await is_admin(message.from_user.id):
        await message.answer("❌ Нет доступа")
        return

    stats = get_user_stats()
    text = (
        f"⚙️ <b>Админ-панель</b>\n\n"
        f"👥 Всего пользователей: {stats['total_users']}\n"
        f"🔍 Парсер подписок: {stats['active_parser']}\n"
        f"📤 Сендер подписок: {stats['active_sender']}\n"
        f"💰 Общий баланс: ${stats['total_balance']:.2f}"
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton(text="💰 Выдать баланс", callback_data="admin_give_balance_select")],
        [InlineKeyboardButton(text="💎 Выдать подписку", callback_data="admin_give_sub_select")],
        [InlineKeyboardButton(text="👥 Пользователи", callback_data="admin_users_0")],
        [InlineKeyboardButton(text="🚫 Черный список", callback_data="admin_blacklist")],
        [InlineKeyboardButton(text="📢 Рассылка", callback_data="admin_broadcast")],
        [InlineKeyboardButton(text="🏠 Главная", callback_data="go_start")]
    ])

    await message.answer(text, parse_mode="HTML", reply_markup=keyboard)

@router.callback_query(F.data == "admin_give_balance_select")
async def admin_give_balance_select(callback: CallbackQuery, state: FSMContext):
    if not await is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа")
        return

    await callback.message.edit_text("💰 Введите ID пользователя для выдачи баланса:")
    await state.set_state(AdminStates.waiting_balance_user_id)
    await callback.answer()

@router.message(AdminStates.waiting_balance_user_id)
async def process_balance_user_id(message: Message, state: FSMContext):
    try:
        user_id = int(message.text.strip())
        user = get_user(user_id)
        if not user:
            await message.answer("❌ Пользователь не найден")
            return
        await state.update_data(target_user_id=user_id)
        await message.answer(f"💰 Введите сумму баланса для выдачи пользователю {user_id}:")
        await state.set_state(AdminStates.waiting_balance_amount)
    except ValueError:
        await message.answer("❌ Введите корректный ID")

@router.message(AdminStates.waiting_balance_amount)
async def process_give_balance(message: Message, state: FSMContext):
    try:
        amount = float(message.text.strip())
        data = await state.get_data()
        target_user_id = data.get('target_user_id')

        update_balance(target_user_id, amount)
        await message.answer(f"✅ Выдано ${amount:.2f} пользователю {target_user_id}")
        await state.clear()
    except ValueError:
        await message.answer("❌ Введите корректное число")

@router.callback_query(F.data == "admin_give_sub_select")
async def admin_give_sub_select(callback: CallbackQuery, state: FSMContext):
    if not await is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа")
        return

    await callback.message.edit_text("💎 Введите ID пользователя для выдачи подписки:")
    await state.set_state(AdminStates.waiting_sub_user_id)
    await callback.answer()

@router.message(AdminStates.waiting_sub_user_id)
async def process_sub_user_id(message: Message, state: FSMContext):
    try:
        user_id = int(message.text.strip())
        user = get_user(user_id)
        if not user:
            await message.answer("❌ Пользователь не найден")
            return
        await state.update_data(target_user_id=user_id)

        text = "💎 <b>Выберите тип подписки:</b>\n\n"
        buttons = []

        # Выбор типа подписки
        buttons.append([InlineKeyboardButton(text="🔍 Парсер", callback_data=f"admin_sub_type_parser_{user_id}")])
        buttons.append([InlineKeyboardButton(text="📤 Сендер", callback_data=f"admin_sub_type_sender_{user_id}")])
        buttons.append([InlineKeyboardButton(text="💎 Комбо (оба)", callback_data=f"admin_sub_type_combo_{user_id}")])
        buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")])

        await message.answer(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
        await state.clear()
    except ValueError:
        await message.answer("❌ Введите корректный ID")

@router.callback_query(F.data.startswith("admin_sub_type_"))
async def admin_select_sub_type(callback: CallbackQuery):
    if not await is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа")
        return

    parts = callback.data.split("_")
    sub_type = parts[3]  # parser, sender или combo
    user_id = int(parts[4])

    text = f"💎 <b>Выберите период для {sub_type}:</b>\n\n"
    buttons = []
    for days in [1, 7, 30, 365]:
        buttons.append([InlineKeyboardButton(text=f"📅 {days} дней", callback_data=f"admin_sub_grant_{sub_type}_{days}_{user_id}")])

    buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")])
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()

@router.callback_query(F.data.startswith("admin_sub_grant_"))
async def admin_grant_subscription(callback: CallbackQuery):
    if not await is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа")
        return

    parts = callback.data.split("_")
    sub_type = parts[3]  # parser, sender или combo
    days = int(parts[4])
    user_id = int(parts[5])

    # Выдаем подписку в зависимости от типа
    if sub_type == 'parser':
        add_parser_subscription(user_id, days)
        type_name = "Парсер"
    elif sub_type == 'sender':
        add_sender_subscription(user_id, days)
        type_name = "Сендер"
    elif sub_type == 'combo':
        add_combo_subscription(user_id, days)
        type_name = "Комбо"

    await callback.answer(f"✅ Выдана подписка {type_name} на {days} дней")
    await callback.message.edit_text(f"✅ Подписка {type_name} выдана пользователю {user_id} на {days} дней")

@router.callback_query(F.data == "admin_stats")
async def admin_stats(callback: CallbackQuery):
    if not await is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа")
        return

    stats = get_user_stats()
    text = (
        f"📊 <b>Статистика</b>\n\n"
        f"👥 Всего пользователей: <code>{stats['total_users']}</code>\n"
        f"🔍 Парсер подписок: <code>{stats['active_parser']}</code>\n"
        f"📤 Сендер подписок: <code>{stats['active_sender']}</code>\n"
        f"💰 Общий баланс: <code>${stats['total_balance']:.2f}</code>"
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")]
    ])

    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)
    await callback.answer()

@router.callback_query(F.data.startswith("admin_users_"))
async def admin_users(callback: CallbackQuery):
    if not await is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа")
        return

    page = int(callback.data.split("_")[2])
    items_per_page = 3

    with get_db() as conn:
        users = conn.execute(
            "SELECT * FROM users LIMIT ? OFFSET ?", 
            (items_per_page, page * items_per_page)
        ).fetchall()
        total = conn.execute("SELECT COUNT(*) as cnt FROM users").fetchone()['cnt']

    total_pages = (total + items_per_page - 1) // items_per_page

    text = f"👥 <b>Управление пользователями (Страница {page + 1}/{total_pages})</b>\n\n"
    buttons = []

    for u in users:
        sub = "✅" if has_active_subscription(u['user_id']) else "❌"
        text += f"━━━━━━━━━━━━━━━━━\n"
        text += f"ID: <code>{u['user_id']}</code>\n"
        text += f"Имя: {u['first_name']}\n"
        text += f"Баланс: ${u['balance']:.2f}\n"
        text += f"Подписка: {sub}\n"
        text += f"Поисков: {u['searches_count']}\n\n"

        buttons.append([
            InlineKeyboardButton(text="🚫 Забанить", callback_data=f"admin_ban_{u['user_id']}")
        ])

    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton(text="◀️", callback_data=f"admin_users_{page - 1}"))
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton(text="▶️", callback_data=f"admin_users_{page + 1}"))

    if nav_buttons:
        buttons.append(nav_buttons)

    buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")])

    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()

@router.callback_query(F.data.startswith("admin_ban_"))
async def admin_ban_user(callback: CallbackQuery):
    if not await is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа")
        return

    user_id = int(callback.data.split("_")[2])
    with get_db() as conn:
        conn.execute("DELETE FROM users WHERE user_id = ?", (user_id,))

    await callback.answer(f"✅ Пользователь {user_id} забанен")
    await callback.message.edit_text(f"✅ Пользователь {user_id} удален из системы")

@router.callback_query(F.data == "admin_blacklist")
async def admin_blacklist(callback: CallbackQuery):
    if not await is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа")
        return

    blacklist = load_blacklist()
    if not blacklist:
        text = "🚫 <b>Черный список пуст</b>"
    else:
        text = "🚫 <b>Черный список:</b>\n\n" + "\n".join(list(blacklist)[:20])

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить", callback_data="admin_add_blacklist")],
        [InlineKeyboardButton(text="🗑️ Очистить", callback_data="admin_clear_blacklist")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")]
    ])

    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)
    await callback.answer()

@router.callback_query(F.data == "admin_add_blacklist")
async def admin_add_blacklist(callback: CallbackQuery, state: FSMContext):
    if not await is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа")
        return

    await callback.message.edit_text("Введите хэндл для добавления в черный список:")
    await state.set_state(AdminStates.waiting_blacklist_handle)
    await callback.answer()

@router.message(AdminStates.waiting_blacklist_handle)
async def process_add_blacklist(message: Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        await message.answer("❌ Нет доступа")
        await state.clear()
        return

    handle = message.text.strip()
    if add_to_blacklist(handle, message.from_user.id):
        await message.answer(f"✅ Добавлен в черный список: {handle}")
    else:
        await message.answer(f"⚠️ Уже в черном списке: {handle}")

    await state.clear()

@router.callback_query(F.data == "admin_clear_blacklist")
async def admin_clear_blacklist_confirm(callback: CallbackQuery):
    if not await is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа")
        return

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да", callback_data="admin_clear_blacklist_yes"),
         InlineKeyboardButton(text="❌ Нет", callback_data="admin_blacklist")]
    ])

    await callback.message.edit_text("Очистить весь черный список?", reply_markup=keyboard)
    await callback.answer()

@router.callback_query(F.data == "admin_clear_blacklist_yes")
async def admin_clear_blacklist_yes(callback: CallbackQuery):
    if not await is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа")
        return

    clear_blacklist()
    await callback.message.edit_text("✅ Черный список очищен!")
    await callback.answer()

@router.callback_query(F.data == "admin_broadcast")
async def admin_broadcast_start(callback: CallbackQuery, state: FSMContext):
    if not await is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа")
        return

    stats = get_user_stats()
    await callback.message.edit_text(
        f"📢 <b>Рассылка сообщений</b>\n\n"
        f"👥 Всего пользователей: {stats['total_users']}\n\n"
        f"Введите текст сообщения для рассылки:\n"
        f"(Поддерживается HTML форматирование)",
        parse_mode="HTML"
    )
    await state.set_state(AdminStates.waiting_broadcast_message)
    await callback.answer()

@router.message(AdminStates.waiting_broadcast_message)
async def process_broadcast_message(message: Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        await message.answer("❌ Нет доступа")
        await state.clear()
        return

    broadcast_text = message.text or message.caption
    if not broadcast_text:
        await message.answer("❌ Сообщение не может быть пустым")
        return

    # Сохраняем сообщение в состояние
    await state.update_data(broadcast_text=broadcast_text, has_photo=bool(message.photo))
    if message.photo:
        await state.update_data(photo_file_id=message.photo[-1].file_id)

    # Получаем статистику
    stats = get_user_stats()

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Начать рассылку", callback_data="broadcast_confirm")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_back")]
    ])

    preview = broadcast_text[:200] + "..." if len(broadcast_text) > 200 else broadcast_text

    await message.answer(
        f"📢 <b>Подтверждение рассылки</b>\n\n"
        f"👥 Получателей: <b>{stats['total_users']}</b>\n\n"
        f"📝 Предпросмотр:\n"
        f"<i>{preview}</i>\n\n"
        f"Начать рассылку?",
        parse_mode="HTML",
        reply_markup=keyboard
    )

@router.callback_query(F.data == "broadcast_confirm")
async def broadcast_confirm(callback: CallbackQuery, state: FSMContext):
    if not await is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа")
        return

    data = await state.get_data()
    broadcast_text = data.get('broadcast_text')
    has_photo = data.get('has_photo', False)
    photo_file_id = data.get('photo_file_id')

    await callback.message.edit_text("📢 Начинаю рассылку...")

    # Получаем всех пользователей
    with get_db() as conn:
        users = conn.execute("SELECT user_id FROM users").fetchall()

    total = len(users)
    success = 0
    failed = 0

    # Отправляем сообщения
    for user in users:
        try:
            user_id = user['user_id']
            if has_photo and photo_file_id:
                await bot.send_photo(
                    user_id,
                    photo=photo_file_id,
                    caption=broadcast_text,
                    parse_mode="HTML"
                )
            else:
                await bot.send_message(
                    user_id,
                    broadcast_text,
                    parse_mode="HTML"
                )
            success += 1
        except Exception as e:
            logger.error(f"Failed to send broadcast to {user_id}: {e}")
            failed += 1

        # Небольшая задержка чтобы не словить rate limit
        await asyncio.sleep(0.05)

    # Итоговый отчет
    await bot.send_message(
        callback.from_user.id,
        f"✅ <b>Рассылка завершена!</b>\n\n"
        f"📊 Статистика:\n"
        f"👥 Всего пользователей: {total}\n"
        f"✅ Успешно: {success}\n"
        f"❌ Ошибок: {failed}",
        parse_mode="HTML"
    )

    await state.clear()
    await callback.answer()

@router.callback_query(F.data == "admin_back")
async def admin_back(callback: CallbackQuery):
    if not await is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа")
        return

    stats = get_user_stats()
    text = (
        f"⚙️ <b>Админ-панель</b>\n\n"
        f"👥 Всего пользователей: {stats['total_users']}\n"
        f"🔍 Парсер подписок: {stats['active_parser']}\n"
        f"📤 Сендер подписок: {stats['active_sender']}\n"
        f"💰 Общий баланс: ${stats['total_balance']:.2f}"
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton(text="💰 Выдать баланс", callback_data="admin_give_balance_select")],
        [InlineKeyboardButton(text="💎 Выдать подписку", callback_data="admin_give_sub_select")],
        [InlineKeyboardButton(text="👥 Пользователи", callback_data="admin_users_0")],
        [InlineKeyboardButton(text="🚫 Черный список", callback_data="admin_blacklist")],
        [InlineKeyboardButton(text="📢 Рассылка", callback_data="admin_broadcast")],
        [InlineKeyboardButton(text="🏠 Главная", callback_data="go_start")]
    ])

    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)
    await callback.answer()

@router.callback_query(F.data == "go_start")
async def go_start(callback: CallbackQuery):
    user_id = callback.from_user.id
    await callback.message.delete()

    try:
        photo = FSInputFile("banner.jpg")
        await bot.send_photo(
            user_id,
            photo=photo,
            caption=(
                "🤖 <b>Bluesky Profile Parser Bot</b>\n\n"
                "👋 Добро пожаловать!\n\n"
                "Бот для поиска профилей в Bluesky по различным параметрам.\n\n"
                "<b>Возможности:</b>\n"
                "🔍 Поиск профилей\n"
                "💎 Подписки на функции\n"
                "💰 Пополнение баланса\n"
                "👤 Просмотр профиля"
            ),
            parse_mode="HTML",
            reply_markup=get_admin_keyboard() if await is_admin(user_id) else get_main_keyboard()
        )
    except:
        text = (
            "🤖 <b>Bluesky Profile Parser Bot</b>\n\n"
            "👋 Добро пожаловать!\n\n"
            "Бот для поиска профилей в Bluesky по различным параметрам.\n\n"
            "<b>Возможности:</b>\n"
            "🔍 Поиск профилей\n"
            "💎 Подписки на функции\n"
            "💰 Пополнение баланса\n"
            "👤 Просмотр профиля"
        )
        await bot.send_message(user_id, text, parse_mode="HTML", reply_markup=get_admin_keyboard() if await is_admin(user_id) else get_main_keyboard())

    await callback.answer()

@router.message(Command("cancel"))
async def cancel(message: Message):
    user_id = message.from_user.id
    cancelled = await cancel_parser_for_user(user_id)
    if cancelled:
        await message.answer("🛑 Парсинг отменен")
    else:
        await message.answer("⚠️ Нет активного парсинга")

@router.callback_query(F.data.startswith("stop_parser_"))
async def stop_parser_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    cancelled = await cancel_parser_for_user(user_id)
    if cancelled:
        await callback.message.edit_text("🛑 Парсинг остановлен пользователем")
        await callback.answer("✅ Парсинг остановлен")
    else:
        await callback.answer("⚠️ Нет активного парсинга", show_alert=True)

@router.callback_query(F.data.startswith("stop_sender_"))
async def stop_sender_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    cancelled = await cancel_sender_for_user(user_id)
    if cancelled:
        await callback.message.edit_text("🛑 Отправка остановлена пользователем")
        await callback.answer("✅ Отправка остановлена")
    else:
        await callback.answer("⚠️ Нет активной отправки", show_alert=True)

@router.error()
async def error_handler(update: Update, exception: Exception):
    logger.error(f"Error: {exception}", exc_info=True)

async def main():
    global bot_username
    init_db()

    # Получаем информацию о боте для динамической реферальной ссылки
    try:
        bot_info = await bot.get_me()
        bot_username = bot_info.username
        logger.info(f"Bot username: @{bot_username}")
    except Exception as e:
        logger.error(f"Failed to get bot info: {e}")
        bot_username = "bot"  # fallback

    asyncio.create_task(check_invoices_task(bot))
    load_blacklist()
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped")
    finally:
        asyncio.run(shutdown_parsers())
        asyncio.run(shutdown_senders())
