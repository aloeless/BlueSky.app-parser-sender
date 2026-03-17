# 🤖 Bluesky Profile Parser & Sender Bot

[Русский](#русский) | [English](#english)

---

## Русский

Telegram-бот для автоматизации работы с социальной сетью Bluesky. Решение "все в одном" для поиска целевой аудитории и взаимодействия с ней.

### 🚀 Основные возможности
- **🔍 Умный Парсер**: Поиск профилей по ключевым словам в постах с фильтрацией по количеству подписчиков и проверкой открытых DM.
- **📤 Массовый Сендер**: Рассылка сообщений по списку профилей. Поддерживает кликабельные ссылки.
- **💳 Прием платежей**: Интеграция с CryptoPay (CryptoBot) для автоматической продажи подписок.
- **👥 Реферальная система**: Система бонусов за привлечение новых пользователей.
- **⚙️ Админ-панель**: Управление пользователями, статистика, рассылки по базе бота и управление черным списком.

### 🛠 Установка

1. **Клонируйте репозиторий:**
   ```bash
   git clone https://github.com/ВАШ_ЛОГИН/BlueSky.app-parser-sender.git
   cd BlueSky.app-parser-sender
   ```

2. **Создайте виртуальное окружение и установите зависимости:**
   ```bash
   python -m venv venv
   source venv/bin/activate  # Для Windows: venv\Scripts\activate
   pip install aiogram aiohttp
   ```

3. **Настройте `config.py`**:
   Откройте файл и впишите свои данные:
   - `BOT_TOKEN`: Получите у @BotFather.
   - `BLUESKY_HANDLE` & `BLUESKY_APP_PASSWORD`: Ваш аккаунт Bluesky (используйте App Password из настроек Bluesky).
   - `CRYPTO_BOT_TOKEN`: Получите у @CryptoBot.
   - `ADMINS`: Ваш Telegram ID.

4. **Запуск:**
   ```bash
   python main.py
   ```

### 📖 Инструкция по использованию

#### Как пользоваться Парсером:
1. В меню бота выберите **📋 Задачи** -> **🔍 Парсер**.
2. Выберите язык поиска и введите ключевое слово.
3. Укажите максимальное кол-во подписчиков (чтобы найти "живых" людей, а не селебрити).
4. Бот пришлет вам профили и сформирует **TXT файл**, который можно сразу использовать в Сендере.

#### Как пользоваться Сендером:
1. Выберите **📋 Задачи** -> **📤 Сендер**.
2. Введите свои данные Bluesky (Handle и App Password). Бот использует ваш аккаунт для отправки.
3. Загрузите TXT файл со ссылками (каждая ссылка с новой строки).
4. Введите текст сообщения и подтвердите запуск. Бот будет отправлять сообщения с задержкой, чтобы избежать блокировок.

---

## English

Telegram bot for automating operations within the Bluesky social network. An all-in-one solution for finding and engaging with your target audience.

### 🚀 Key Features
- **🔍 Smart Parser**: Find profiles by keywords in posts, filtered by follower count and open DM status.
- **📤 Bulk Sender**: Send direct messages to a list of profiles. Supports clickable links.
- **💳 Crypto Payments**: Integrated with CryptoPay (CryptoBot) for automated subscription sales.
- **👥 Referral System**: Bonus system for inviting new users.
- **⚙️ Admin Panel**: User management, statistics, global broadcasts, and blacklist management.

### 🛠 Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/YOUR_USERNAME/BlueSky.app-parser-sender.git
   cd BlueSky.app-parser-sender
   ```

2. **Create virtual environment and install dependencies:**
   ```bash
   python -m venv venv
   source venv/bin/activate  # For Windows: venv\Scripts\activate
   pip install aiogram aiohttp
   ```

3. **Configure `config.py`**:
   Fill in your credentials:
   - `BOT_TOKEN`: From @BotFather.
   - `BLUESKY_HANDLE` & `BLUESKY_APP_PASSWORD`: Your Bluesky technical account (use App Password from Bluesky settings).
   - `CRYPTO_BOT_TOKEN`: From @CryptoBot.
   - `ADMINS`: Your Telegram ID.

4. **Run:**
   ```bash
   python main.py
   ```

### 📖 Usage Guide

#### Using the Parser:
1. Go to **📋 Tasks** -> **🔍 Parser**.
2. Select search language and enter a keyword.
3. Set the maximum follower count (to target regular users).
4. The bot will send you profiles and generate a **TXT file** ready for the Sender.

#### Using the Sender:
1. Go to **📋 Tasks** -> **📤 Sender**.
2. Enter your Bluesky credentials (Handle and App Password). The bot uses your account to send messages.
3. Upload a TXT file with profile links (one link per line).
4. Enter your message and confirm. The bot sends messages with delays to prevent rate limiting.

---

## ⚖️ Disclaimer / Отказ от ответственности

**RU:** Этот софт создан исключительно для образовательных и ознакомительных целей. Автор не несет ответственности за использование данного инструмента в целях спама, фишинга или нарушения правил Bluesky. Используйте на свой страх и риск.

**EN:** This software is created for educational and research purposes only. The author is not responsible for any misuse, including spam, phishing, or violation of Bluesky's Terms of Service. Use at your own risk.

## 📄 License
This project is licensed under the terms of the repository license.
