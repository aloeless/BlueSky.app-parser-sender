# database.py
# -*- coding: utf-8 -*-
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
import json
import logging

logger = logging.getLogger(__name__)

DATABASE = "bluesky_bot.db"
blacklist_cache = set()
global_shown_profiles_cache = set()

@contextmanager
def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()

def init_db():
    """Инициализация БД с ИСПРАВЛЕННОЙ схемой invoices и миграциями"""
    with get_db() as conn:
        # Таблица пользователей (ОБНОВЛЕНО: раздельные подписки)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            balance REAL DEFAULT 0.0,
            searches_count INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            referred_by INTEGER,
            subscription_until TIMESTAMP,
            parser_until TIMESTAMP,
            sender_until TIMESTAMP
        )
        """)

        # Таблица рефералов
        conn.execute("""
        CREATE TABLE IF NOT EXISTS referrals (
            referrer_id INTEGER,
            referred_id INTEGER,
            bonus REAL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)

        # Таблица черного списка (админский)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS blacklist (
            handle TEXT PRIMARY KEY,
            added_by INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)

        # Таблица глобального черного списка (автоматический)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS global_shown_profiles (
            handle TEXT PRIMARY KEY,
            seen_count INTEGER DEFAULT 1,
            last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)

        # Таблица истории поисков
        conn.execute("""
        CREATE TABLE IF NOT EXISTS search_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            keyword TEXT,
            profiles_found JSON,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        )
        """)

        # Таблица показанных профилей (локальная, per-user)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS shown_profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            handle TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(user_id),
            UNIQUE(user_id, handle)
        )
        """)

        # ИСПРАВЛЕННАЯ таблица счетов/инвойсов с status и message_id
        conn.execute("""
        CREATE TABLE IF NOT EXISTS invoices (
            invoice_id TEXT PRIMARY KEY,
            user_id INTEGER,
            amount REAL,
            status TEXT DEFAULT 'pending',
            message_id INTEGER,
            chat_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            paid_at TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        )
        """)

        # Таблица Bluesky аккаунтов для сендера
        conn.execute("""
        CREATE TABLE IF NOT EXISTS bluesky_accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            handle TEXT,
            app_password TEXT,
            is_active BOOLEAN DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_used TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(user_id),
            UNIQUE(user_id, handle)
        )
        """)

        # Таблица истории отправки сообщений
        conn.execute("""
        CREATE TABLE IF NOT EXISTS sender_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            account_id INTEGER,
            total_targets INTEGER,
            sent_count INTEGER,
            failed_count INTEGER,
            message_text TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            completed_at TIMESTAMP,
            status TEXT DEFAULT 'running',
            FOREIGN KEY (user_id) REFERENCES users(user_id),
            FOREIGN KEY (account_id) REFERENCES bluesky_accounts(id)
        )
        """)

        # МИГРАЦИИ: Добавление новых полей
        try:
            # Проверяем наличие колонок в invoices
            cursor = conn.execute("PRAGMA table_info(invoices)")
            columns = [row[1] for row in cursor.fetchall()]

            if 'message_id' not in columns:
                conn.execute("ALTER TABLE invoices ADD COLUMN message_id INTEGER")
                logger.info("[DATABASE MIGRATION] Added message_id column to invoices")

            if 'chat_id' not in columns:
                conn.execute("ALTER TABLE invoices ADD COLUMN chat_id INTEGER")
                logger.info("[DATABASE MIGRATION] Added chat_id column to invoices")

            # Проверяем наличие колонок в users для раздельных подписок
            cursor = conn.execute("PRAGMA table_info(users)")
            user_columns = [row[1] for row in cursor.fetchall()]

            if 'parser_until' not in user_columns:
                conn.execute("ALTER TABLE users ADD COLUMN parser_until TIMESTAMP")
                logger.info("[DATABASE MIGRATION] Added parser_until column to users")

            if 'sender_until' not in user_columns:
                conn.execute("ALTER TABLE users ADD COLUMN sender_until TIMESTAMP")
                logger.info("[DATABASE MIGRATION] Added sender_until column to users")

        except Exception as e:
            logger.warning(f"[DATABASE MIGRATION] Migration check error (may be normal): {e}")

        logger.info("[DATABASE] Initialized successfully with all tables")

def create_user(user_id, username, first_name, referred_by=None):
    """Создать пользователя"""
    with get_db() as conn:
        conn.execute("""
        INSERT OR IGNORE INTO users (user_id, username, first_name, referred_by)
        VALUES (?, ?, ?, ?)
        """, (user_id, username, first_name, referred_by))
        logger.info(f"[DB] User created/updated: {user_id}")

def get_user(user_id):
    """Получить информацию пользователя"""
    with get_db() as conn:
        user = conn.execute("""
        SELECT * FROM users WHERE user_id = ?
        """, (user_id,)).fetchone()
        if user:
            return dict(user)
    return None

def update_balance(user_id, amount):
    """Обновить баланс пользователя"""
    with get_db() as conn:
        conn.execute("""
        UPDATE users SET balance = balance + ? WHERE user_id = ?
        """, (amount, user_id))
        logger.info(f"[DB] Balance updated for user {user_id}: +{amount}")

def add_subscription(user_id, days):
    """Добавить подписку на N дней"""
    with get_db() as conn:
        user = conn.execute("SELECT subscription_until FROM users WHERE user_id = ?", (user_id,)).fetchone()
        if user and user['subscription_until']:
            sub_until = datetime.fromisoformat(user['subscription_until']) + timedelta(days=days)
        else:
            sub_until = datetime.now() + timedelta(days=days)
        conn.execute("""
        UPDATE users SET subscription_until = ? WHERE user_id = ?
        """, (sub_until.isoformat(), user_id))
        logger.info(f"[DB] Subscription added for user {user_id}: +{days} days")

def add_trial_subscription(user_id, hours=1):
    """Добавить пробную подписку"""
    with get_db() as conn:
        sub_until = datetime.now() + timedelta(hours=hours)
        conn.execute("""
        UPDATE users SET subscription_until = ? WHERE user_id = ?
        """, (sub_until.isoformat(), user_id))
        logger.info(f"[DB] Trial subscription added for user {user_id}: {hours} hours")

def has_active_subscription(user_id):
    """Проверить наличие активной подписки"""
    with get_db() as conn:
        user = conn.execute("SELECT subscription_until FROM users WHERE user_id = ?", (user_id,)).fetchone()
        if user and user['subscription_until']:
            is_active = datetime.fromisoformat(user['subscription_until']) > datetime.now()
            return is_active
    return False

def increment_search_count(user_id):
    """Увеличить счетчик поисков"""
    with get_db() as conn:
        conn.execute("""
        UPDATE users SET searches_count = searches_count + 1 WHERE user_id = ?
        """, (user_id,))

def get_user_stats():
    """Получить общую статистику с раздельными подписками"""
    with get_db() as conn:
        stats = conn.execute("""
        SELECT
            COUNT(*) as total_users,
            SUM(CASE WHEN parser_until > datetime('now') THEN 1 ELSE 0 END) as active_parser,
            SUM(CASE WHEN sender_until > datetime('now') THEN 1 ELSE 0 END) as active_sender,
            SUM(balance) as total_balance
        FROM users
        """).fetchone()
    return dict(stats) if stats else {'total_users': 0, 'active_parser': 0, 'active_sender': 0, 'total_balance': 0.0}

def add_referral_bonus(referrer_id, referred_id, bonus):
    """Добавить бонус за реферала"""
    with get_db() as conn:
        conn.execute("""
        INSERT INTO referrals (referrer_id, referred_id, bonus)
        VALUES (?, ?, ?)
        """, (referrer_id, referred_id, bonus))
        conn.execute("""
        UPDATE users SET balance = balance + ? WHERE user_id = ?
        """, (bonus, referrer_id))
        logger.info(f"[DB] Referral bonus: {referrer_id} +{bonus} (referred {referred_id})")

def get_referral_stats(user_id):
    """Получить статистику рефералов"""
    with get_db() as conn:
        stats = conn.execute("""
        SELECT COUNT(*) as count, SUM(bonus) as total_bonus
        FROM referrals WHERE referrer_id = ?
        """, (user_id,)).fetchone()
    if stats:
        return {'count': stats['count'] or 0, 'total_bonus': stats['total_bonus'] or 0.0}
    return {'count': 0, 'total_bonus': 0.0}

# ========== АДМИНСКИЙ ЧЕРНЫЙ СПИСОК ==========

def add_to_blacklist(handle, added_by):
    """Добавить хэндл в админский черный список"""
    handle_lower = handle.lower()
    global blacklist_cache

    with get_db() as conn:
        try:
            conn.execute("""
            INSERT INTO blacklist (handle, added_by)
            VALUES (?, ?)
            """, (handle_lower, added_by))
            logger.info(f"[ADMIN BLACKLIST] Added {handle_lower}")
            blacklist_cache.add(handle_lower)
            return True
        except sqlite3.IntegrityError:
            logger.warning(f"[ADMIN BLACKLIST] Already in blacklist: {handle_lower}")
            return False

def load_blacklist():
    """Загрузить админский черный список"""
    global blacklist_cache
    with get_db() as conn:
        handles = conn.execute("SELECT handle FROM blacklist").fetchall()
        blacklist_cache = {h['handle'].lower() for h in handles}
    logger.info(f"[ADMIN BLACKLIST] Loaded: {len(blacklist_cache)} items")
    return blacklist_cache

def is_handle_blacklisted(handle):
    """Проверить если ли хэндл в админском черном списке"""
    result = handle.lower() in blacklist_cache
    if result:
        logger.info(f"[CHECK] {handle} - in admin blacklist")
    return result

def clear_blacklist():
    """Очистить администраторский черный список"""
    global blacklist_cache
    with get_db() as conn:
        conn.execute("DELETE FROM blacklist")
    blacklist_cache.clear()
    logger.info("[ADMIN BLACKLIST] Cleared")

# ========== ГЛОБАЛЬНЫЙ ЧЕРНЫЙ СПИСОК ==========

def add_to_global_shown(handle):
    """Добавить профиль в глобальный черный список"""
    handle_lower = handle.lower()
    global global_shown_profiles_cache

    with get_db() as conn:
        try:
            conn.execute("""
            INSERT INTO global_shown_profiles (handle, seen_count, last_seen)
            VALUES (?, 1, ?)
            """, (handle_lower, datetime.now().isoformat()))
            logger.info(f"[GLOBAL BLACKLIST] Added {handle_lower} (count: 1)")
        except sqlite3.IntegrityError:
            conn.execute("""
            UPDATE global_shown_profiles SET seen_count = seen_count + 1, last_seen = ?
            WHERE handle = ?
            """, (datetime.now().isoformat(), handle_lower))
            count = conn.execute("""
            SELECT seen_count FROM global_shown_profiles WHERE handle = ?
            """, (handle_lower,)).fetchone()['seen_count']
            logger.info(f"[GLOBAL BLACKLIST] Updated {handle_lower} (count: {count})")

    global_shown_profiles_cache.add(handle_lower)

def was_profile_shown_globally(handle):
    """Проверить был ли профиль показан ЛЮБОМУ пользователю"""
    result = handle.lower() in global_shown_profiles_cache
    if result:
        logger.info(f"[CHECK] {handle} - in global blacklist (shown before)")
    return result

def load_global_shown_profiles():
    """Загрузить глобальный черный список"""
    global global_shown_profiles_cache
    with get_db() as conn:
        handles = conn.execute("SELECT handle FROM global_shown_profiles").fetchall()
        global_shown_profiles_cache = {h['handle'].lower() for h in handles}
    logger.info(f"[GLOBAL BLACKLIST] Loaded: {len(global_shown_profiles_cache)} items")
    return global_shown_profiles_cache

def get_global_shown_stats():
    """Получить статистику глобального черного списка"""
    with get_db() as conn:
        stats = conn.execute("""
        SELECT COUNT(*) as total, SUM(seen_count) as total_seen
        FROM global_shown_profiles
        """).fetchone()
    return {
        'unique_profiles': stats['total'] or 0,
        'total_shown': stats['total_seen'] or 0
    }

# ========== ЛОКАЛЬНЫЙ ЧЕРНЫЙ СПИСОК ==========

def add_shown_profile(user_id, handle):
    """Добавить профиль в локальный черный список пользователя"""
    with get_db() as conn:
        try:
            conn.execute("""
            INSERT INTO shown_profiles (user_id, handle)
            VALUES (?, ?)
            """, (user_id, handle.lower()))
            return True
        except sqlite3.IntegrityError:
            return False

def was_profile_shown(user_id, handle):
    """Проверить был ли профиль показан этому пользователю"""
    with get_db() as conn:
        result = conn.execute("""
        SELECT id FROM shown_profiles WHERE user_id = ? AND handle = ?
        """, (user_id, handle.lower())).fetchone()
    return result is not None

def clear_shown_profiles(user_id):
    """Очистить историю показанных профилей для пользователя"""
    with get_db() as conn:
        conn.execute("DELETE FROM shown_profiles WHERE user_id = ?", (user_id,))
    logger.info(f"[USER BLACKLIST] Cleared for user {user_id}")

def clear_all_shown_profiles():
    """Очистить всю историю показанных профилей"""
    with get_db() as conn:
        conn.execute("DELETE FROM shown_profiles")
    logger.info("[USER BLACKLIST] Cleared all")

def save_search_history(user_id, keyword, profiles):
    """Сохранить историю поиска"""
    with get_db() as conn:
        profiles_json = json.dumps(profiles)
        conn.execute("""
        INSERT INTO search_history (user_id, keyword, profiles_found)
        VALUES (?, ?, ?)
        """, (user_id, keyword, profiles_json))
        logger.info(f"[DB] Search history saved for user {user_id}")

# ========== ПЛАТЕЖИ / INVOICES ==========

def get_invoice(invoice_id):
    """Получить информацию о счете"""
    with get_db() as conn:
        invoice = conn.execute("""
        SELECT * FROM invoices WHERE invoice_id = ?
        """, (invoice_id,)).fetchone()
    return dict(invoice) if invoice else None

def get_pending_invoices():
    """Получить все ожидающие счета"""
    with get_db() as conn:
        invoices = conn.execute("""
        SELECT * FROM invoices WHERE status = 'pending'
        """).fetchall()
    return [dict(inv) for inv in invoices]

def update_invoice_status(invoice_id, status, paid_at=None):
    """Обновить статус счета"""
    with get_db() as conn:
        if paid_at:
            conn.execute("""
            UPDATE invoices SET status = ?, paid_at = ? WHERE invoice_id = ?
            """, (status, paid_at, invoice_id))
        else:
            conn.execute("""
            UPDATE invoices SET status = ? WHERE invoice_id = ?
            """, (status, invoice_id))
        logger.info(f"[INVOICE] Status updated: {invoice_id} -> {status}")

def update_user_balance_from_invoice(invoice_id):
    """Обновить баланс пользователя после оплаты счета"""
    with get_db() as conn:
        invoice = conn.execute("""
        SELECT * FROM invoices WHERE invoice_id = ? AND status = 'paid'
        """, (invoice_id,)).fetchone()

        if invoice:
            conn.execute("""
            UPDATE users SET balance = balance + ? WHERE user_id = ?
            """, (invoice['amount'], invoice['user_id']))
            logger.info(f"[INVOICE] Balance updated: user {invoice['user_id']} +${invoice['amount']}")
            return True
    return False

# ========== УТИЛИТЫ ==========

def export_stats():
    """Экспортировать статистику БД"""
    with get_db() as conn:
        users_count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        balance_total = conn.execute("SELECT SUM(balance) FROM users").fetchone()[0] or 0
        invoices_paid = conn.execute("SELECT SUM(amount) FROM invoices WHERE status='paid'").fetchone()[0] or 0
        profiles_shown = conn.execute("SELECT SUM(seen_count) FROM global_shown_profiles").fetchone()[0] or 0

    return {
        'users_count': users_count,
        'total_balance': balance_total,
        'total_paid': invoices_paid,
        'profiles_shown': profiles_shown
    }

def cleanup_old_data(days=30):
    """Очистить старые данные (опционально)"""
    with get_db() as conn:
        conn.execute("""
        DELETE FROM search_history
        WHERE created_at < datetime('now', '-' || ? || ' days')
        """, (days,))
        logger.info(f"[DB] Cleaned up search history older than {days} days")

# ========== РАЗДЕЛЬНЫЕ ПОДПИСКИ ==========

def add_parser_subscription(user_id, days=0, hours=0):
    """Добавить подписку на парсер"""
    with get_db() as conn:
        user = conn.execute("SELECT parser_until FROM users WHERE user_id = ?", (user_id,)).fetchone()
        if user and user['parser_until']:
            sub_until = datetime.fromisoformat(user['parser_until']) + timedelta(days=days, hours=hours)
        else:
            sub_until = datetime.now() + timedelta(days=days, hours=hours)
        conn.execute("UPDATE users SET parser_until = ? WHERE user_id = ?", (sub_until.isoformat(), user_id))
        if hours > 0:
            logger.info(f"[DB] Parser subscription added for user {user_id}: +{hours} hours")
        else:
            logger.info(f"[DB] Parser subscription added for user {user_id}: +{days} days")

def add_sender_subscription(user_id, days=0, hours=0):
    """Добавить подписку на сендер"""
    with get_db() as conn:
        user = conn.execute("SELECT sender_until FROM users WHERE user_id = ?", (user_id,)).fetchone()
        if user and user['sender_until']:
            sub_until = datetime.fromisoformat(user['sender_until']) + timedelta(days=days, hours=hours)
        else:
            sub_until = datetime.now() + timedelta(days=days, hours=hours)
        conn.execute("UPDATE users SET sender_until = ? WHERE user_id = ?", (sub_until.isoformat(), user_id))
        if hours > 0:
            logger.info(f"[DB] Sender subscription added for user {user_id}: +{hours} hours")
        else:
            logger.info(f"[DB] Sender subscription added for user {user_id}: +{days} days")

def add_combo_subscription(user_id, days=0, hours=0):
    """Добавить комбо подписку (парсер + сендер)"""
    add_parser_subscription(user_id, days=days, hours=hours)
    add_sender_subscription(user_id, days=days, hours=hours)
    if hours > 0:
        logger.info(f"[DB] Combo subscription added for user {user_id}: +{hours} hours")
    else:
        logger.info(f"[DB] Combo subscription added for user {user_id}: +{days} days")

def has_parser_subscription(user_id):
    """Проверить наличие подписки на парсер"""
    with get_db() as conn:
        user = conn.execute("SELECT parser_until FROM users WHERE user_id = ?", (user_id,)).fetchone()
        if user and user['parser_until']:
            return datetime.fromisoformat(user['parser_until']) > datetime.now()
    return False

def has_sender_subscription(user_id):
    """Проверить наличие подписки на сендер"""
    with get_db() as conn:
        user = conn.execute("SELECT sender_until FROM users WHERE user_id = ?", (user_id,)).fetchone()
        if user and user['sender_until']:
            return datetime.fromisoformat(user['sender_until']) > datetime.now()
    return False

# ========== BLUESKY АККАУНТЫ ==========

def save_bluesky_account(user_id, handle, app_password):
    """Сохранить Bluesky аккаунт"""
    with get_db() as conn:
        try:
            conn.execute("""
            INSERT INTO bluesky_accounts (user_id, handle, app_password)
            VALUES (?, ?, ?)
            """, (user_id, handle, app_password))
            logger.info(f"[DB] Bluesky account saved: {handle} for user {user_id}")
            return True
        except sqlite3.IntegrityError:
            # Обновляем существующий
            conn.execute("""
            UPDATE bluesky_accounts
            SET app_password = ?, is_active = 1
            WHERE user_id = ? AND handle = ?
            """, (app_password, user_id, handle))
            logger.info(f"[DB] Bluesky account updated: {handle} for user {user_id}")
            return True

def get_bluesky_account(user_id):
    """Получить активный Bluesky аккаунт пользователя"""
    with get_db() as conn:
        account = conn.execute("""
        SELECT * FROM bluesky_accounts
        WHERE user_id = ? AND is_active = 1
        ORDER BY last_used DESC
        LIMIT 1
        """, (user_id,)).fetchone()
        return dict(account) if account else None

def update_account_last_used(account_id):
    """Обновить время последнего использования аккаунта"""
    with get_db() as conn:
        conn.execute("""
        UPDATE bluesky_accounts
        SET last_used = ?
        WHERE id = ?
        """, (datetime.now().isoformat(), account_id))

# ========== ИСТОРИЯ СЕНДЕРА ==========

def create_sender_history(user_id, account_id, total_targets, message_text):
    """Создать запись истории отправки"""
    with get_db() as conn:
        cursor = conn.execute("""
        INSERT INTO sender_history (user_id, account_id, total_targets, sent_count, failed_count, message_text, status)
        VALUES (?, ?, ?, 0, 0, ?, 'running')
        """, (user_id, account_id, total_targets, message_text))
        return cursor.lastrowid

def update_sender_history(history_id, sent_count, failed_count, status='running'):
    """Обновить статистику отправки"""
    with get_db() as conn:
        conn.execute("""
        UPDATE sender_history
        SET sent_count = ?, failed_count = ?, status = ?
        WHERE id = ?
        """, (sent_count, failed_count, status, history_id))

def complete_sender_history(history_id, sent_count, failed_count):
    """Завершить сессию отправки"""
    with get_db() as conn:
        conn.execute("""
        UPDATE sender_history
        SET sent_count = ?, failed_count = ?, status = 'completed', completed_at = ?
        WHERE id = ?
        """, (sent_count, failed_count, datetime.now().isoformat(), history_id))
