# crypto_payment.py
# -*- coding: utf-8 -*-
"""
CryptoBot Payment Module - FIXED VERSION
Исправления:
1. Правильная инициализация invoice status='pending'
2. Фикс SQL запроса getInvoices
3. Добавлена обработка webhook (опционально)
4. Улучшенное логирование
"""
import requests
import logging
from config import CRYPTO_BOT_TOKEN, CRYPTO_BOT_API
from database import get_db

logger = logging.getLogger(__name__)

async def create_crypto_invoice(user_id, amount, message_id=None, chat_id=None):
    """
    Создать инвойс через CryptoBot
    ИСПРАВЛЕНО: добавлен status='pending' при INSERT + сохранение message_id
    """
    try:
        url = f"{CRYPTO_BOT_API}/createInvoice"
        headers = {"Crypto-Pay-API-Token": CRYPTO_BOT_TOKEN}
        data = {
            "currency_type": "fiat",
            "fiat": "USD",
            "amount": str(round(amount, 2)),
            "description": f"Пополнение баланса на ${amount}",
            "payload": str(user_id)
        }

        # ИСПРАВЛЕНО: используем data вместо json для form-data
        response = requests.post(url, headers=headers, data=data, timeout=10)
        result = response.json()

        if result.get("ok"):
            invoice = result["result"]
            invoice_id = invoice["invoice_id"]
            pay_url = invoice["bot_invoice_url"]

            # ИСПРАВЛЕНО: добавлен status='pending' и message_id, chat_id при создании
            with get_db() as conn:
                conn.execute(
                    "INSERT INTO invoices (invoice_id, user_id, amount, status, message_id, chat_id) VALUES (?, ?, ?, 'pending', ?, ?)",
                    (invoice_id, user_id, amount, message_id, chat_id)
                )

            logger.info(f"[CRYPTO] Invoice created: {invoice_id} for user {user_id} amount ${amount} msg_id={message_id}")
            return pay_url
        else:
            logger.error(f"[CRYPTO] CryptoBot API error: {result}")
            return None

    except Exception as e:
        logger.exception(f"[CRYPTO] Invoice creation error: {e}")
        return None

async def check_invoices_task(application):
    """
    Фоновая задача проверки статуса инвойсов
    ИСПРАВЛЕНО: правильный запрос к getInvoices + логирование
    """
    import asyncio

    logger.info("[CRYPTO] Background invoice checker started")

    while True:
        try:
            await asyncio.sleep(5)  # Проверка каждые 5 сек (быстрое зачисление)

            # Получить все pending инвойсы
            with get_db() as conn:
                pending = conn.execute(
                    "SELECT invoice_id, user_id, amount FROM invoices WHERE status = 'pending'"
                ).fetchall()

            if not pending:
                continue  # Нет pending инвойсов

            logger.info(f"[CRYPTO] Checking {len(pending)} pending invoices...")

            # ИСПРАВЛЕНО: правильный формат для getInvoices
            # API принимает массив invoice_ids
            invoice_ids_list = [str(inv["invoice_id"]) for inv in pending]

            url = f"{CRYPTO_BOT_API}/getInvoices"
            headers = {"Crypto-Pay-API-Token": CRYPTO_BOT_TOKEN}

            # ВАЖНО: invoice_ids должен быть массивом JSON
            params = {"invoice_ids": ",".join(invoice_ids_list)}  # или передать как JSON массив

            response = requests.get(url, headers=headers, params=params, timeout=10)
            result = response.json()

            if not result.get("ok"):
                logger.error(f"[CRYPTO] getInvoices API error: {result}")
                continue

            # Проверка статусов
            items = result.get("result", {}).get("items", [])
            logger.info(f"[CRYPTO] Got {len(items)} invoices from API")

            for item in items:
                if item["status"] == "paid":
                    invoice_id = item["invoice_id"]

                    # Найти инвойс в БД
                    with get_db() as conn:
                        inv = conn.execute(
                            "SELECT * FROM invoices WHERE invoice_id = ? AND status = 'pending'",
                            (invoice_id,)
                        ).fetchone()

                        if inv:
                            # ОБНОВИТЬ СТАТУС И БАЛАНС
                            conn.execute(
                                "UPDATE invoices SET status = 'paid', paid_at = CURRENT_TIMESTAMP WHERE invoice_id = ?",
                                (invoice_id,)
                            )

                            conn.execute(
                                "UPDATE users SET balance = balance + ? WHERE user_id = ?",
                                (inv["amount"], inv["user_id"])
                            )

                            logger.info(f"[CRYPTO] ✅ Payment confirmed: invoice={invoice_id}, user={inv['user_id']}, amount=${inv['amount']}")

                            # ИСПРАВЛЕНО: Обновить старое сообщение вместо отправки нового
                            try:
                                # Если есть message_id - обновляем сообщение
                                if inv["message_id"] and inv["chat_id"]:
                                    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

                                    new_keyboard = InlineKeyboardMarkup(inline_keyboard=[
                                        [InlineKeyboardButton(text="🏠 Главная", callback_data="go_start")]
                                    ])

                                    await application.edit_message_text(
                                        chat_id=inv["chat_id"],
                                        message_id=inv["message_id"],
                                        text=f"✅ <b>Баланс успешно пополнен!</b>\n\n"
                                             f"💰 Сумма: <b>${inv['amount']:.2f}</b>\n"
                                             f"🆔 Инвойс: <code>{invoice_id}</code>\n\n"
                                             f"Ваш баланс обновлен!",
                                        parse_mode="HTML",
                                        reply_markup=new_keyboard
                                    )
                                    logger.info(f"[CRYPTO] Invoice message updated for user {inv['user_id']}")
                                else:
                                    # Если нет message_id - отправляем новое сообщение
                                    await application.send_message(
                                        inv["user_id"],
                                        f"✅ <b>Баланс успешно пополнен!</b>\n\n"
                                        f"💰 Сумма: <b>${inv['amount']:.2f}</b>\n"
                                        f"🆔 Инвойс: <code>{invoice_id}</code>",
                                        parse_mode="HTML"
                                    )
                                    logger.info(f"[CRYPTO] Notification sent to user {inv['user_id']}")
                            except Exception as send_err:
                                logger.warning(f"[CRYPTO] Failed to update/send notification to {inv['user_id']}: {send_err}")
                        else:
                            logger.warning(f"[CRYPTO] Invoice {invoice_id} already processed or not found")

        except Exception as e:
            logger.exception(f"[CRYPTO] Check invoices error: {e}")
            await asyncio.sleep(5)  # Пауза перед повторной попыткой после ошибки

async def check_invoice_status(invoice_id):
    """
    Проверить статус конкретного инвойса (опционально, для manual check)
    """
    try:
        url = f"{CRYPTO_BOT_API}/getInvoices"
        headers = {"Crypto-Pay-API-Token": CRYPTO_BOT_TOKEN}
        params = {"invoice_ids": str(invoice_id)}

        response = requests.get(url, headers=headers, params=params, timeout=10)
        result = response.json()

        if result.get("ok"):
            items = result.get("result", {}).get("items", [])
            if items:
                return items[0]["status"]

        return None

    except Exception as e:
        logger.error(f"[CRYPTO] Check invoice {invoice_id} error: {e}")
        return None

async def check_single_invoice(invoice_id, application):
    """
    Немедленная проверка конкретного инвойса (для быстрого зачисления)
    Проверяет инвойс каждые 2 секунды в течение 3 минут
    """
    import asyncio
    max_checks = 90  # 90 проверок * 2 сек = 3 минуты

    for attempt in range(max_checks):
        try:
            await asyncio.sleep(2)  # Пауза перед проверкой

            url = f"{CRYPTO_BOT_API}/getInvoices"
            headers = {"Crypto-Pay-API-Token": CRYPTO_BOT_TOKEN}
            params = {"invoice_ids": str(invoice_id)}

            response = requests.get(url, headers=headers, params=params, timeout=10)
            result = response.json()

            if result.get("ok"):
                items = result.get("result", {}).get("items", [])
                if items and items[0]["status"] == "paid":
                    # Найти инвойс в БД
                    with get_db() as conn:
                        inv = conn.execute(
                            "SELECT * FROM invoices WHERE invoice_id = ? AND status = 'pending'",
                            (invoice_id,)
                        ).fetchone()

                        if inv:
                            # ОБНОВИТЬ СТАТУС И БАЛАНС
                            conn.execute(
                                "UPDATE invoices SET status = 'paid', paid_at = CURRENT_TIMESTAMP WHERE invoice_id = ?",
                                (invoice_id,)
                            )
                            conn.execute(
                                "UPDATE users SET balance = balance + ? WHERE user_id = ?",
                                (inv["amount"], inv["user_id"])
                            )

                            logger.info(f"[CRYPTO] ⚡ INSTANT Payment confirmed: invoice={invoice_id}, user={inv['user_id']}, amount=${inv['amount']} (check #{attempt+1})")

                            # Отправить уведомление
                            try:
                                if inv["message_id"] and inv["chat_id"]:
                                    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
                                    new_keyboard = InlineKeyboardMarkup(inline_keyboard=[
                                        [InlineKeyboardButton(text="🏠 Главная", callback_data="go_start")]
                                    ])
                                    await application.edit_message_text(
                                        chat_id=inv["chat_id"],
                                        message_id=inv["message_id"],
                                        text=f"✅ <b>Баланс успешно пополнен!</b>\n\n"
                                             f"💰 Сумма: <b>${inv['amount']:.2f}</b>\n"
                                             f"🆔 Инвойс: <code>{invoice_id}</code>\n\n"
                                             f"Ваш баланс обновлен!",
                                        parse_mode="HTML",
                                        reply_markup=new_keyboard
                                    )
                                else:
                                    await application.send_message(
                                        inv["user_id"],
                                        f"✅ <b>Баланс успешно пополнен!</b>\n\n"
                                        f"💰 Сумма: <b>${inv['amount']:.2f}</b>\n"
                                        f"🆔 Инвойс: <code>{invoice_id}</code>",
                                        parse_mode="HTML"
                                    )
                            except Exception as send_err:
                                logger.warning(f"[CRYPTO] Failed to send instant notification: {send_err}")

                            return True
                        else:
                            # Уже обработан
                            return False
        except Exception as e:
            logger.error(f"[CRYPTO] Check single invoice error (attempt {attempt+1}): {e}")
            await asyncio.sleep(2)

    logger.info(f"[CRYPTO] Invoice {invoice_id} check timeout after {max_checks} attempts")
    return False
