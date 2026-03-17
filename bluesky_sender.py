# bluesky_sender.py
# -*- coding: utf-8 -*-
"""
Bluesky DM Sender - Модуль отправки личных сообщений
"""
import asyncio
import aiohttp
import logging
import re
from database import (
    get_bluesky_account,
    update_account_last_used,
    create_sender_history,
    update_sender_history,
    complete_sender_history
)

logger = logging.getLogger(__name__)

tasks_by_user = {}
sessions_by_user = {}
semaphore = asyncio.Semaphore(10)  # Ограничение параллельных запросов

bot = None

async def login_to_bluesky(session: aiohttp.ClientSession, handle: str, app_password: str) -> dict:
    """Авторизация в Bluesky"""
    try:
        login_url = "https://bsky.social/xrpc/com.atproto.server.createSession"
        data = {
            "identifier": handle,
            "password": app_password
        }
        async with session.post(login_url, json=data, timeout=10) as resp:
            if resp.status == 200:
                result = await resp.json()
                logger.info(f"[SENDER] Login successful: {handle}")

                # ИСПРАВЛЕНО: Получаем PDS endpoint из didDoc
                pds_endpoint = "https://bsky.social"  # default
                did_doc = result.get("didDoc", {})
                if did_doc and "service" in did_doc and len(did_doc["service"]) > 0:
                    pds_endpoint = did_doc["service"][0].get("serviceEndpoint", "https://bsky.social")

                logger.info(f"[SENDER] PDS endpoint: {pds_endpoint}")

                return {
                    "token": result.get("accessJwt"),
                    "did": result.get("did"),
                    "handle": result.get("handle"),
                    "pds_endpoint": pds_endpoint
                }
            else:
                logger.error(f"[SENDER] Login failed: {resp.status}")
                return None
    except Exception as e:
        logger.exception(f"[SENDER] Login error: {e}")
        return None

async def get_conversation_id(session: aiohttp.ClientSession, token: str, target_did: str, pds_endpoint: str) -> str:
    """Получить ID разговора с пользователем (или создать новый)"""
    try:
        # ИСПРАВЛЕНО: Используем GET с PDS endpoint и правильным заголовком
        url = f"{pds_endpoint}/xrpc/chat.bsky.convo.getConvoForMembers"
        headers = {
            "Authorization": f"Bearer {token}",
            "Atproto-Proxy": "did:web:api.bsky.chat#bsky_chat"
        }
        params = {"members": target_did}

        logger.debug(f"[SENDER] Getting conversation for {target_did} from {pds_endpoint}")

        async with session.get(url, headers=headers, params=params, timeout=10) as resp:
            if resp.status == 200:
                result = await resp.json()
                convo_id = result.get("convo", {}).get("id")
                if convo_id:
                    logger.info(f"[SENDER] Existing conversation found: {convo_id}")
                    return convo_id
            else:
                response_text = await resp.text()
                logger.warning(f"[SENDER] Get conversation failed: {resp.status} - {response_text[:200]}")

            # Если разговора нет - создаем новый
            return await create_conversation(session, token, target_did, pds_endpoint)

    except Exception as e:
        logger.warning(f"[SENDER] Error getting conversation: {e}")
        return None

async def create_conversation(session: aiohttp.ClientSession, token: str, target_did: str, pds_endpoint: str) -> str:
    """Создать новый разговор"""
    try:
        # ИСПРАВЛЕНО: Используем PDS endpoint и правильный заголовок
        url = f"{pds_endpoint}/xrpc/chat.bsky.convo.getConvoForMembers"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Atproto-Proxy": "did:web:api.bsky.chat#bsky_chat"
        }
        data = {"members": [target_did]}

        logger.debug(f"[SENDER] Creating conversation with {target_did} at {pds_endpoint}")
        logger.debug(f"[SENDER] Request data: {data}")

        async with session.post(url, headers=headers, json=data, timeout=10) as resp:
            response_text = await resp.text()
            if resp.status == 200:
                result = await resp.json()
                convo_id = result.get("convo", {}).get("id")
                logger.info(f"[SENDER] New conversation created: {convo_id}")
                return convo_id
            else:
                logger.error(f"[SENDER] Failed to create conversation: {resp.status}")
                logger.error(f"[SENDER] Response body: {response_text}")
                return None
    except Exception as e:
        logger.exception(f"[SENDER] Create conversation error: {e}")
        return None

def extract_links_and_create_facets(text: str) -> list:
    """Извлечь ссылки из текста и создать facets для кликабельных ссылок"""
    facets = []
    # Регулярное выражение для поиска URL
    url_pattern = re.compile(
        r'https?://(?:www\.)?[-a-zA-Z0-9@:%._\+~#=]{1,256}\.[a-zA-Z0-9()]{1,6}\b(?:[-a-zA-Z0-9()@:%_\+.~#?&/=]*)'
    )

    for match in url_pattern.finditer(text):
        url = match.group(0)
        start = match.start()
        end = match.end()

        # Создаем facet для ссылки
        facet = {
            "index": {
                "byteStart": len(text[:start].encode('utf-8')),
                "byteEnd": len(text[:end].encode('utf-8'))
            },
            "features": [
                {
                    "$type": "app.bsky.richtext.facet#link",
                    "uri": url
                }
            ]
        }
        facets.append(facet)
        logger.debug(f"[FACET] Created facet for link: {url}")

    return facets

async def send_dm(session: aiohttp.ClientSession, token: str, convo_id: str, message: str, pds_endpoint: str) -> bool:
    """Отправить DM сообщение с поддержкой кликабельных ссылок"""
    try:
        # ИСПРАВЛЕНО: Используем PDS endpoint и правильный заголовок
        url = f"{pds_endpoint}/xrpc/chat.bsky.convo.sendMessage"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Atproto-Proxy": "did:web:api.bsky.chat#bsky_chat"
        }

        # Извлекаем ссылки и создаем facets для кликабельности
        facets = extract_links_and_create_facets(message)

        message_data = {
            "text": message
        }

        # Добавляем facets только если есть ссылки
        if facets:
            message_data["facets"] = facets
            logger.info(f"[SENDER] Added {len(facets)} clickable link(s) to message")

        data = {
            "convoId": convo_id,
            "message": message_data
        }

        async with session.post(url, headers=headers, json=data, timeout=10) as resp:
            if resp.status == 200:
                logger.info(f"[SENDER] Message sent successfully to {convo_id}")
                return True
            else:
                logger.error(f"[SENDER] Failed to send message: {resp.status}")
                return False
    except Exception as e:
        logger.exception(f"[SENDER] Send DM error: {e}")
        return False

async def get_profile_did(session: aiohttp.ClientSession, token: str, handle: str) -> str:
    """Получить DID профиля по хэндлу"""
    try:
        # ИСПРАВЛЕНО: Убираем https://bsky.app/profile/ если есть и @ если есть
        clean_handle = handle.replace("https://bsky.app/profile/", "").replace("@", "").strip()

        url = "https://bsky.social/xrpc/app.bsky.actor.getProfile"
        headers = {"Authorization": f"Bearer {token}"}
        params = {"actor": clean_handle}

        logger.debug(f"[SENDER] Requesting DID for: {clean_handle}")

        async with session.get(url, headers=headers, params=params, timeout=10) as resp:
            if resp.status == 200:
                result = await resp.json()
                did = result.get("did")
                if did:
                    logger.info(f"[SENDER] ✅ Got DID for {clean_handle}: {did}")
                    return did
                else:
                    logger.error(f"[SENDER] ❌ No DID in response for {clean_handle}")
                    return None
            else:
                error_text = await resp.text()
                logger.error(f"[SENDER] ❌ API error {resp.status} for {clean_handle}: {error_text[:200]}")
                return None
    except asyncio.TimeoutError:
        logger.error(f"[SENDER] ❌ Timeout getting DID for {handle}")
        return None
    except Exception as e:
        logger.exception(f"[SENDER] ❌ Error getting DID for {handle}: {e}")
        return None

def parse_profile_links(file_content: str) -> list:
    """Извлечь ссылки на профили из текстового файла"""
    links = []
    lines = file_content.strip().split('\n')

    for line in lines:
        line = line.strip()
        # Пропускаем комментарии и пустые строки
        if not line or line.startswith('#'):
            continue

        # Извлекаем хэндл из ссылки или используем как есть
        if 'bsky.app/profile/' in line:
            handle = line.split('bsky.app/profile/')[-1].strip()
        elif 'bsky.social' in line or '.' in line:
            handle = line
        else:
            continue

        links.append(handle)

    logger.info(f"[SENDER] Parsed {len(links)} profile links from file")
    return links

async def run_sender(user_id: int, handle: str, app_password: str, target_handles: list, message_text: str):
    """Запустить процесс массовой отправки DM"""
    if user_id in tasks_by_user and not tasks_by_user[user_id].done():
        await bot.send_message(user_id, "⚠️ Сендер уже работает. Дождитесь завершения.")
        return False

    async def sender_coroutine():
        session = None
        auth_data = None
        history_id = None
        sent_count = 0
        failed_count = 0

        try:
            async with semaphore:
                session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=300))
                sessions_by_user[user_id] = session

                # Авторизация
                await bot.send_message(user_id, "🔐 Авторизация в Bluesky...")
                auth_data = await login_to_bluesky(session, handle, app_password)

                if not auth_data or not auth_data.get("token"):
                    await bot.send_message(user_id, "❌ Ошибка авторизации. Проверьте логин и пароль.")
                    return

                token = auth_data["token"]
                pds_endpoint = auth_data.get("pds_endpoint", "https://bsky.social")

                # Получаем account_id
                account = get_bluesky_account(user_id)
                account_id = account['id'] if account else None

                # Создаем запись истории
                history_id = create_sender_history(user_id, account_id, len(target_handles), message_text)

                # Импорт для кнопки
                from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🛑 Остановить отправку", callback_data=f"stop_sender_{user_id}")]
                ])

                await bot.send_message(
                    user_id,
                    f"✅ Авторизация успешна!\n\n"
                    f"📤 Начинаю отправку сообщений...\n"
                    f"Целей: {len(target_handles)}\n\n"
                    f"Это может занять некоторое время...",
                    reply_markup=keyboard
                )

                logger.info(f"\n{'='*70}")
                logger.info(f"SENDER START - User {user_id}")
                logger.info(f"  Account: {handle}")
                logger.info(f"  Targets: {len(target_handles)}")
                logger.info(f"  Message length: {len(message_text)} chars")
                logger.info(f"{'='*70}\n")

                # Отправка сообщений
                for idx, target_handle in enumerate(target_handles, 1):
                    try:
                        # Получаем DID профиля
                        target_did = await get_profile_did(session, token, target_handle)
                        if not target_did:
                            logger.warning(f"[{idx}/{len(target_handles)}] Skipped {target_handle}: No DID")
                            failed_count += 1
                            continue

                        # Получаем/создаем разговор
                        convo_id = await get_conversation_id(session, token, target_did, pds_endpoint)
                        if not convo_id:
                            logger.warning(f"[{idx}/{len(target_handles)}] Skipped {target_handle}: No conversation")
                            failed_count += 1
                            continue

                        # Отправляем сообщение
                        success = await send_dm(session, token, convo_id, message_text, pds_endpoint)
                        if success:
                            sent_count += 1
                            logger.info(f"[{idx}/{len(target_handles)}] ✅ Sent to {target_handle}")
                        else:
                            failed_count += 1
                            logger.warning(f"[{idx}/{len(target_handles)}] ❌ Failed {target_handle}")

                        # Обновляем историю каждые 5 сообщений
                        if idx % 5 == 0:
                            update_sender_history(history_id, sent_count, failed_count)
                            await bot.send_message(
                                user_id,
                                f"📊 Прогресс: {idx}/{len(target_handles)}\n"
                                f"✅ Отправлено: {sent_count}\n"
                                f"❌ Ошибок: {failed_count}"
                            )

                        # Пауза между отправками (защита от rate limit)
                        await asyncio.sleep(2)

                    except Exception as target_error:
                        logger.error(f"[{idx}/{len(target_handles)}] Error for {target_handle}: {target_error}")
                        failed_count += 1

                # Завершаем историю
                complete_sender_history(history_id, sent_count, failed_count)

                # Обновляем last_used аккаунта
                if account_id:
                    update_account_last_used(account_id)

                logger.info(f"\n{'='*70}")
                logger.info(f"SENDER COMPLETE - User {user_id}")
                logger.info(f"  Total targets: {len(target_handles)}")
                logger.info(f"  Sent: {sent_count}")
                logger.info(f"  Failed: {failed_count}")
                logger.info(f"  Success rate: {sent_count/len(target_handles)*100:.1f}%")
                logger.info(f"{'='*70}\n")

                # Итоговое сообщение
                status = "✅" if sent_count > 0 else "⚠️"
                await bot.send_message(
                    user_id,
                    f"{status} <b>Отправка завершена!</b>\n\n"
                    f"📊 Статистика:\n"
                    f"✅ Отправлено: <b>{sent_count}</b>\n"
                    f"❌ Ошибок: <b>{failed_count}</b>\n"
                    f"📈 Успех: <b>{sent_count/len(target_handles)*100:.1f}%</b>\n\n"
                    f"💬 Сообщение: {message_text[:50]}{'...' if len(message_text) > 50 else ''}",
                    parse_mode="HTML"
                )

        except asyncio.CancelledError:
            logger.info(f"Sender cancelled for user {user_id}")
            if history_id:
                update_sender_history(history_id, sent_count, failed_count, 'cancelled')
        except Exception as e:
            logger.exception(f"Sender error for user {user_id}: {e}")
            await bot.send_message(user_id, f"❌ Критическая ошибка сендера: {str(e)[:100]}")
            if history_id:
                update_sender_history(history_id, sent_count, failed_count, 'error')
        finally:
            if session:
                await session.close()
            cleanup_user(user_id)

    def cleanup_user(uid):
        if uid in sessions_by_user:
            del sessions_by_user[uid]
        if uid in tasks_by_user:
            del tasks_by_user[uid]

    task = asyncio.create_task(sender_coroutine())
    tasks_by_user[user_id] = task

    return True

def get_active_sender_users():
    """Получить список пользователей с активным сендером"""
    return list(tasks_by_user.keys())

async def cancel_sender_for_user(user_id: int):
    """Отменить сендер для пользователя"""
    if user_id in tasks_by_user:
        tasks_by_user[user_id].cancel()
        await bot.send_message(user_id, "🛑 Отправка отменена")
        return True
    await bot.send_message(user_id, "ℹ️ Нет активной отправки для отмены")
    return False

async def shutdown_senders():
    """Остановить все активные сендеры"""
    for task in list(tasks_by_user.values()):
        if not task.done():
            task.cancel()
    for session in list(sessions_by_user.values()):
        try:
            await session.close()
        except:
            pass
    tasks_by_user.clear()
    sessions_by_user.clear()
    logger.info("All senders shutdown complete")
