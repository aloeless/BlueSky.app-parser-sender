#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Скрипт для очистки данных БД (для тестирования)
"""
import sqlite3
import os

DATABASE = "bluesky_bot.db"

def clear_db():
    """Полная очистка БД"""
    if os.path.exists(DATABASE):
        os.remove(DATABASE)
        print(f"✅ Удалена БД: {DATABASE}")
    else:
        print(f"ℹ️ БД не существует: {DATABASE}")

def clear_shown_profiles():
    """Очистить историю показанных профилей"""
    try:
        conn = sqlite3.connect(DATABASE)
        conn.execute("DELETE FROM shown_profiles")
        conn.commit()
        conn.close()
        print("✅ Очищена история показанных профилей")
    except Exception as e:
        print(f"❌ Ошибка: {e}")

def clear_blacklist():
    """Очистить черный список"""
    try:
        conn = sqlite3.connect(DATABASE)
        conn.execute("DELETE FROM blacklist")
        conn.commit()
        conn.close()
        print("✅ Очищен черный список")
    except Exception as e:
        print(f"❌ Ошибка: {e}")

def db_stats():
    """Показать статистику БД"""
    try:
        conn = sqlite3.connect(DATABASE)
        conn.row_factory = sqlite3.Row

        stats = {}
        for table in ['users', 'shown_profiles', 'blacklist', 'invoices']:
            count = conn.execute(f"SELECT COUNT(*) as cnt FROM {table}").fetchone()['cnt']
            stats[table] = count

        conn.close()

        print("\n📊 Статистика БД:")
        print(f"  👥 users: {stats['users']}")
        print(f"  🎯 shown_profiles: {stats['shown_profiles']}")
        print(f"  🚫 blacklist: {stats['blacklist']}")
        print(f"  💳 invoices: {stats['invoices']}")
    except Exception as e:
        print(f"❌ Ошибка: {e}")

if __name__ == "__main__":
    print("🔧 Очистка данных для тестирования\n")

    # Очистить историю показанных профилей (чтобы показывались заново)
    clear_shown_profiles()

    # Показать статистику
    db_stats()

    print("\n✅ Готово! Теперь выполните: python3 main.py")
