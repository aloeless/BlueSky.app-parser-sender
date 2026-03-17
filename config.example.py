# -*- coding: utf-8 -*-

# --- ТЕЛЕГРАМ НАСТРОЙКИ ---
BOT_TOKEN = "ВАШ_ТЕЛЕГРАМ_ТОКЕН"

# --- BLUESKY НАСТРОЙКИ (ТЕХНИЧЕСКИЙ АККАУНТ ДЛЯ ПАРСЕРА) ---
# Рекомендуется создать отдельный аккаунт для парсинга
BLUESKY_HANDLE = "your_handle.bsky.social"
BLUESKY_APP_PASSWORD = "your_app_password"

# --- АДМИНИСТРАТОРЫ ---
# ID пользователей Telegram, которые будут иметь доступ к админ-панели
ADMINS = [12345678, 87654321]

# --- КРИПТО ОПЛАТА (CRYPTO BOT) ---
CRYPTO_BOT_TOKEN = "ВАШ_CRYPTO_BOT_TOKEN"
CRYPTO_BOT_API = "https://pay.crypt.bot/api"

# --- СИСТЕМА ТАРИФОВ ---
# Вы можете изменять цены и длительность подписок здесь
SUBSCRIPTION_PLANS = {
    # ПАРСЕР
    "parser_1h": {"name": "Парсер 1 час", "price": 1.00, "hours": 1, "emoji": "🔍", "type": "parser"},
    "parser_day": {"name": "Парсер 1 день", "price": 2.00, "days": 1, "emoji": "🔍", "type": "parser"},
    "parser_week": {"name": "Парсер 1 неделя", "price": 8.00, "days": 7, "emoji": "🔍", "type": "parser"},
    "parser_month": {"name": "Парсер 1 месяц", "price": 35.00, "days": 30, "emoji": "🔍", "type": "parser"},

    # СЕНДЕР
    "sender_1h": {"name": "Сендер 1 час", "price": 2.00, "hours": 1, "emoji": "📤", "type": "sender"},
    "sender_day": {"name": "Сендер 1 день", "price": 5.00, "days": 1, "emoji": "📤", "type": "sender"},
    "sender_week": {"name": "Сендер 1 неделя", "price": 18.00, "days": 7, "emoji": "📤", "type": "sender"},
    "sender_month": {"name": "Сендер 1 месяц", "price": 50.00, "days": 30, "emoji": "📤", "type": "sender"},

    # КОМБО (ПАРСЕР + СЕНДЕР)
    "combo_1h": {"name": "Комбо 1 час", "price": 5.00, "hours": 1, "emoji": "💎", "type": "combo"},
    "combo_day": {"name": "Комбо 1 день", "price": 10.00, "days": 1, "emoji": "💎", "type": "combo"},
    "combo_week": {"name": "Комбо 1 неделя", "price": 30.00, "days": 7, "emoji": "💎", "type": "combo"},
    "combo_month": {"name": "Комбо 1 месяц", "price": 100.00, "days": 30, "emoji": "💎", "type": "combo"},
}

REFERRAL_BONUS = 0.30  # Бонус в долларах за приглашение
MIN_DEPOSIT = 1.00     # Минимальный депозит для пополнения

LANGUAGES = {
    "en": "🇬🇧 English", "ru": "🇷🇺 Русский", "es": "🇪🇸 Español",
    "fr": "🇫🇷 Français", "de": "🇩🇪 Deutsch", "ja": "🇯🇵 日本語",
    "ko": "🇰🇷 한국어", "pt": "🇵🇹 Português", "all": "🌍 Все языки"
}
