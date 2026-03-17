# bluesky_parser.py
# -*- coding: utf-8 -*-
"""
Bluesky Profile Parser
Расширенный поиск профилей с фильтрацией
"""
import asyncio
import aiohttp
import logging
from config import BLUESKY_HANDLE, BLUESKY_APP_PASSWORD
from database import (
    load_blacklist,
    is_handle_blacklisted,
    add_shown_profile,
    was_profile_shown,
    load_global_shown_profiles,
    was_profile_shown_globally,
    add_to_global_shown,
    get_global_shown_stats
)

logger = logging.getLogger(__name__)

tasks_by_user = {}
sessions_by_user = {}
semaphore = asyncio.Semaphore(50)

bot = None
result_counter = {}
admins = set()  # ID админов (заполнить в main.py)

async def login_to_bluesky(session: aiohttp.ClientSession) -> str:
    """Авторизация в Bluesky"""
    try:
        login_url = "https://bsky.social/xrpc/com.atproto.server.createSession"
        data = {
            "identifier": BLUESKY_HANDLE,
            "password": BLUESKY_APP_PASSWORD
        }
        async with session.post(login_url, json=data, timeout=10) as resp:
            if resp.status == 200:
                result = await resp.json()
                return result.get("accessJwt")
            else:
                logger.error(f"Login failed: {resp.status}")
                return None
    except Exception as e:
        logger.exception(f"Login error: {e}")
        return None

async def get_profile_info(session: aiohttp.ClientSession, token: str, handle: str):
    """Получить точную информацию о профиле"""
    try:
        url = "https://bsky.social/xrpc/app.bsky.actor.getProfile"
        headers = {"Authorization": f"Bearer {token}"}
        params = {"actor": handle}
        async with session.get(url, headers=headers, params=params, timeout=5) as resp:
            if resp.status == 200:
                return await resp.json()
            else:
                return None
    except Exception as e:
        logger.warning(f"Error getting profile {handle}: {e}")
        return None

async def search_posts_paginated(
    session: aiohttp.ClientSession,
    token: str,
    keyword: str,
    user_id: int,
    profile_limit: int = 20
):
    """
    Многоитерационный поиск по постам с накоплением авторов
    """
    try:
        posts_url = "https://bsky.social/xrpc/app.bsky.feed.searchPosts"
        headers = {"Authorization": f"Bearer {token}"}

        # Увеличенный пул в 100 раз для гарантированного результата
        target_pool_size = profile_limit * 100
        max_iterations = min(200, max(150, profile_limit * 4))  # От 150 до 200 итераций

        logger.info(f"\n{'='*70}")
        logger.info(f"SEARCH START")
        logger.info(f"  Keyword: {keyword}")
        logger.info(f"  Requested profiles: {profile_limit}")
        logger.info(f"  Target authors pool: {target_pool_size}")
        logger.info(f"  Max iterations: {max_iterations}")
        logger.info(f"{'='*70}\n")

        all_authors = set()
        cursor = None
        iteration = 0

        while len(all_authors) < target_pool_size and iteration < max_iterations:
            iteration += 1
            params = {
                "q": keyword,
                "limit": 100,
                "sort": "latest"
            }
            if cursor:
                params["cursor"] = cursor

            logger.info(f"[ITER {iteration}/{max_iterations}] Fetching 100 posts (total authors: {len(all_authors)}/{target_pool_size})")

            try:
                async with session.get(posts_url, headers=headers, params=params, timeout=20) as resp:
                    if resp.status != 200:
                        logger.error(f"API error in iter {iteration}: {resp.status}")
                        break

                    data = await resp.json()
                    posts = data.get("posts", [])
                    cursor = data.get("cursor", None)

                    logger.info(f"  Got {len(posts)} posts (cumulative: {iteration*100} posts)")

                    if not posts:
                        logger.info(f"  [ITER {iteration}] No more posts available")
                        break

                    # Извлечение новых авторов
                    new_authors_this_iter = 0
                    for post in posts:
                        author = post.get("author", {})
                        handle = author.get("handle", "unknown")
                        if handle not in all_authors:
                            all_authors.add(handle)
                            new_authors_this_iter += 1

                    logger.info(f"  New authors: {new_authors_this_iter} (total: {len(all_authors)})")

                    if not cursor:
                        logger.info(f"  [ITER {iteration}] End of results (no cursor)")
                        break

            except Exception as e:
                logger.error(f"Error in iteration {iteration}: {e}")
                if iteration < 5:  # Продолжить если ранняя ошибка
                    await asyncio.sleep(1)
                    continue
                else:
                    break

        # Конвертация в список
        authors_list = [{"handle": handle} for handle in all_authors]

        logger.info(f"\n{'='*70}")
        logger.info(f"SEARCH COMPLETE")
        logger.info(f"  Total iterations: {iteration}")
        logger.info(f"  Total posts fetched: ~{iteration * 100}")
        logger.info(f"  Unique authors found: {len(authors_list)}")
        logger.info(f"  Success rate: {len(authors_list) / target_pool_size * 100:.1f}%")
        logger.info(f"{'='*70}")

        return authors_list

    except Exception as e:
        logger.exception(f"Enhanced paginated search error: {e}")
        return []

async def search_profiles(
    session: aiohttp.ClientSession,
    token: str,
    keyword: str,
    user_id: int,
    max_followers: int = 1000,
    profile_limit: int = 20
):
    """
    Основная функция поиска профилей с генерацией TXT файла
    """
    try:
        load_blacklist()
        load_global_shown_profiles()

        if user_id not in result_counter:
            result_counter[user_id] = 0

        profiles_sent = 0
        profiles_checked = 0
        skipped_global = 0
        skipped_admin = 0
        skipped_local = 0
        skipped_followers = 0  # Новый счетчик
        skipped_dm = 0  # Новый счетчик
        skipped_profile_fetch = 0  # Новый счетчик

        # НОВОЕ: Список найденных профилей для TXT файла
        found_profiles_links = []

        global_stats = get_global_shown_stats()

        logger.info(f"\n{'='*70}")
        logger.info(f"SEARCH START")
        logger.info(f"  Keyword: {keyword}")
        logger.info(f"  Max followers: {max_followers}")
        logger.info(f"  Need EXACTLY: {profile_limit} profiles")
        logger.info(f"  Global BL size: {global_stats['unique_profiles']}")
        logger.info(f"  Expected pool: {profile_limit * 20} authors")
        logger.info(f"{'='*70}\n")

        # ШАГ 1: УЛУЧШЕННЫЙ ПОИСК ПОСТОВ (большой пул)
        authors = await search_posts_paginated(session, token, keyword, user_id, profile_limit)

        if not authors:
            logger.info("No posts/authors found")
            await bot.send_message(user_id, f"❌ Посты с текстом '{keyword}' не найдены")
            return

        logger.info(f"[STEP 2] Processing LARGE pool: {len(authors)} unique authors\n")

        # ШАГ 2: ОБРАБОТКА КАЖДОГО АВТОРА
        for idx, author in enumerate(authors, 1):
            if profiles_sent >= profile_limit:
                logger.info(f"[DONE] Reached EXACT limit: {profiles_sent}/{profile_limit}")
                break

            handle = author.get("handle", "unknown")
            profiles_checked += 1

            display_name = "No name"
            avatar_url = None

            # ПРОВЕРКА 1: АДМИНСКИЙ ЧС
            if is_handle_blacklisted(handle):
                logger.info(f"  [#{idx}] @{handle} ❌ ADMIN BL (total skipped: {skipped_admin + 1})")
                skipped_admin += 1
                continue

            # ПРОВЕРКА 2: ГЛОБАЛЬНЫЙ ЧС
            if was_profile_shown_globally(handle):
                logger.info(f"  [#{idx}] @{handle} ❌ GLOBAL BL (total: {skipped_global + 1})")
                skipped_global += 1
                continue

            # ПРОВЕРКА 3: ЛОКАЛЬНЫЙ ЧС
            if was_profile_shown(user_id, handle):
                logger.info(f"  [#{idx}] @{handle} ❌ LOCAL BL (total: {skipped_local + 1})")
                skipped_local += 1
                continue

            # ПРОВЕРКА 4: ПОЛУЧИТЬ ПОЛНУЮ ИНФО ПРОФИЛЯ
            profile_full = await get_profile_info(session, token, handle)
            if not profile_full:
                logger.info(f"  [#{idx}] @{handle} ❌ Profile fetch failed (total: {skipped_profile_fetch + 1})")
                skipped_profile_fetch += 1
                continue

            display_name = profile_full.get("displayName", "No name")
            avatar_url = profile_full.get("avatar", None)
            followers_count = profile_full.get("followersCount", 0)

            logger.info(f"  [#{idx}] @{handle} | Name: {display_name[:20]}... | Followers: {followers_count}")

            # ПРОВЕРКА 5: ФИЛЬТР ПО ПОДПИСЧИКАМ
            if followers_count > max_followers:
                logger.info(f"  ❌ Too many followers: {followers_count} > {max_followers}")
                skipped_followers += 1
                continue

            # ПРОВЕРКА 6: ОТКРЫТЫЙ DM (как в 1.py)
            allow_incoming = profile_full.get("associated", {}).get("chat", {}).get("allowIncoming", None)
            viewer = profile_full.get("viewer", {})

            if viewer.get("blockedBy", False):
                logger.info(f"  ❌ Blocked by user (blockedBy=True)")
                skipped_dm += 1
                continue

            if allow_incoming != "all":
                logger.info(f"  ❌ DM closed (allowIncoming='{allow_incoming}', need 'all')")
                skipped_dm += 1
                continue

            # ✅ ВСЕ ФИЛЬТРЫ ПРОЙДЕНЫ - ОТПРАВИТЬ!
            try:
                # ДОБАВИТЬ В ЧЕРНЫЕ СПИСКИ ПЕРЕД ОТПРАВКОЙ
                add_shown_profile(user_id, handle)  # Локальный
                add_to_global_shown(handle)  # Глобальный

                profiles_sent += 1
                result_counter[user_id] = profiles_sent

                # НОВОЕ: Добавить ссылку в список для TXT файла
                profile_link = f"https://bsky.app/profile/{handle}"
                found_profiles_links.append(profile_link)

                logger.info(f"  ✅ #{profiles_sent} MATCH FOUND: @{handle} ({followers_count} followers, DM open)")
                logger.info(f"     Added to LOCAL + GLOBAL BL")

                text = (
                    f"━━━━━ #{profiles_sent} ━━━━━\n\n"
                    f"👤 Имя: {display_name}\n"
                    f"📱 Handle: @{handle}\n"
                    f"👥 Подписчиков: <b>{followers_count}</b>\n"
                    f"💬 Открыт DM: ✅ Да\n\n"
                    f"🔗 <a href='{profile_link}'>Перейти в профиль</a>"
                )

                if avatar_url:
                    await bot.send_photo(
                        user_id,
                        photo=avatar_url,
                        caption=text,
                        parse_mode="HTML"
                    )
                else:
                    await bot.send_message(user_id, text, parse_mode="HTML")

                logger.info(f"  ✅ SENT #{profiles_sent}: @{handle}")

                # Если достигли лимита - выходим
                if profiles_sent >= profile_limit:
                    break

            except Exception as send_error:
                logger.warning(f"Send error for @{handle}: {send_error}")
                # Если не отправили - НЕ добавляем в ЧС (уже добавили выше, но для safety)

            # Небольшая пауза между отправками
            await asyncio.sleep(0.3)

        # ФИНАЛЬНАЯ СТАТИСТИКА
        logger.info(f"\n{'='*70}")
        logger.info(f"SEARCH COMPLETE")
        logger.info(f"  🎯 TARGET: {profile_limit} profiles")
        logger.info(f"  ✅ SENT: {profiles_sent}/{profile_limit} ({profiles_sent/profile_limit*100:.1f}%)")
        logger.info(f"  📊 CHECKED: {profiles_checked} authors")
        logger.info(f"  🏷️  ADMIN BL: {skipped_admin}")
        logger.info(f"  🌍 GLOBAL BL: {skipped_global}")
        logger.info(f"  👤 LOCAL BL: {skipped_local}")
        logger.info(f"  👥 TOO MANY FOLLOWERS: {skipped_followers}")
        logger.info(f"  💬 CLOSED DM: {skipped_dm}")
        logger.info(f"  ❌ PROFILE FETCH FAILED: {skipped_profile_fetch}")
        logger.info(f"  📚 AUTHORS POOL SIZE: {len(authors)}")
        logger.info(f"  📈 Pool utilization: {profiles_checked/len(authors)*100:.1f}%" if len(authors) > 0 else "N/A")
        logger.info(f"{'='*70}")

        # ИТОГОВОЕ СООБЩЕНИЕ ПОЛЬЗОВАТЕЛЮ
        if profiles_sent == 0:
            await bot.send_message(
                user_id,
                f"❌ Ни одного подходящего профиля не найдено для '{keyword}'\n\n"
                f"🔧 Возможные причины:\n"
                f"• Слишком строгий лимит подписчиков ({max_followers})\n"
                f"• Все профили имеют закрытый DM\n"
                f"• Ключевое слово слишком узкое\n\n"
                f"💡 Попробуйте: расширить лимит или изменить запрос"
            )
        else:
            status = "✅" if profiles_sent >= profile_limit else "⚠️"
            if user_id in admins:  # Админам - полная статистика
                await bot.send_message(
                    user_id,
                    f"{status} Поиск завершен!\n\n"
                    f"🎯 Запрошено: {profile_limit}\n"
                    f"✅ Найдено: {profiles_sent}\n\n"
                    f"📊 Детальная статистика:\n"
                    f"• Проверено авторов: {profiles_checked}\n"
                    f"• ADMIN ЧС: {skipped_admin}\n"
                    f"• ГЛОБАЛЬНЫЙ ЧС: {skipped_global}\n"
                    f"• ЛОКАЛЬНЫЙ ЧС: {skipped_local}\n"
                    f"• Слишком много фолловеров: {skipped_followers}\n"
                    f"• Закрыт DM: {skipped_dm}\n"
                    f"• Ошибки получения профиля: {skipped_profile_fetch}\n"
                    f"• Пул авторов: {len(authors)}\n\n"
                    f"🔍 По: '{keyword}'"
                )
            else:  # Обычным - упрощенная
                await bot.send_message(
                    user_id,
                    f"{status} Поиск завершен!\n\n"
                    f"✅ Найдено профилей: {profiles_sent}"
                    f"{' (ровно ' + str(profile_limit) + ')' if profiles_sent >= profile_limit else ''}\n"
                    f"🔍 По запросу: '{keyword}'\n\n"
                    f"{'Все профили соответствуют фильтрам DM и подписчиков' if profiles_sent >= profile_limit else 'Найдено меньше чем запрошено - попробуйте изменить фильтры'}"
                )

            # НОВОЕ: Генерация и отправка TXT файла со ссылками
            if found_profiles_links:
                try:
                    import os
                    from datetime import datetime
                    from aiogram.types import FSInputFile

                    # Создаем имя файла с timestamp
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    filename = f"bluesky_profiles_{keyword[:20]}_{timestamp}.txt"
                    filepath = os.path.join(os.getcwd(), filename)

                    # Записываем ссылки в файл (каждая с новой строки)
                    with open(filepath, 'w', encoding='utf-8') as f:
                        f.write(f"# Bluesky Profile Parser - Результаты поиска\n")
                        f.write(f"# Ключевое слово: {keyword}\n")
                        f.write(f"# Найдено профилей: {profiles_sent}\n")
                        f.write(f"# Дата: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                        f.write(f"# {'='*60}\n\n")
                        for link in found_profiles_links:
                            f.write(f"{link}\n")

                    # Отправляем файл пользователю
                    file_to_send = FSInputFile(filepath)
                    await bot.send_document(
                        user_id,
                        document=file_to_send,
                        caption=f"📄 Список найденных профилей ({profiles_sent} шт.)"
                    )

                    # Удаляем временный файл
                    os.remove(filepath)
                    logger.info(f"[TXT FILE] Sent and cleaned: {filename}")

                except Exception as file_error:
                    logger.error(f"[TXT FILE] Error creating/sending file: {file_error}")
                    await bot.send_message(user_id, "⚠️ Не удалось создать файл со ссылками")

    except asyncio.TimeoutError:
        logger.error("Search timeout - too many iterations")
        await bot.send_message(user_id, "⏰ Таймаут поиска - API перегружено. Попробуйте позже.")
    except Exception as e:
        logger.exception(f"Search critical error: {e}")
        await bot.send_message(user_id, f"❌ Критическая ошибка поиска: {str(e)[:100]}")

async def run_parser_for_user(user_id: int, keyword: str, max_followers: int = 1000, profile_limit: int = 20):
    """Запустить улучшенный парсер"""
    if user_id in tasks_by_user and not tasks_by_user[user_id].done():
        await bot.send_message(user_id, "🔄 Поиск уже выполняется. Дождитесь завершения.")
        return False

    async def parser_coroutine():
        session = None
        token = None
        try:
            async with semaphore:
                # Увеличено общее время для больших поисков
                session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=600))
                sessions_by_user[user_id] = session
                token = await login_to_bluesky(session)
                if not token:
                    await bot.send_message(user_id, "❌ Ошибка авторизации в Bluesky API")
                    return
                await search_profiles(session, token, keyword, user_id, max_followers, profile_limit)
        except asyncio.CancelledError:
            logger.info(f"Parser cancelled for user {user_id}")
        except Exception as e:
            logger.exception(f"Parser error: {e}")
            await bot.send_message(user_id, f"❌ Ошибка парсера: {str(e)[:100]}")
        finally:
            if session:
                await session.close()
            cleanup_user(user_id)

    def cleanup_user(uid):
        if uid in sessions_by_user:
            del sessions_by_user[uid]
        if uid in tasks_by_user:
            del tasks_by_user[uid]
        if uid in result_counter:
            del result_counter[uid]

    task = asyncio.create_task(parser_coroutine())
    tasks_by_user[user_id] = task

    # Импорт для кнопки
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛑 Остановить парсинг", callback_data=f"stop_parser_{user_id}")]
    ])

    await bot.send_message(
        user_id,
        f"🔍 Запускаю поиск...\n\n"
        f"📝 Ключевое слово: '{keyword}'\n"
        f"👥 Max подписчиков: {max_followers}\n"
        f"🎯 Нужен: {profile_limit} профилей\n"
        f"📚 Пул: ~{profile_limit * 20} авторов (для гарантии)\n\n"
        f"⏳ Это может занять 2-10 минут в зависимости от объема...",
        reply_markup=keyboard
    )
    return True

async def cancel_parser_for_user(user_id: int):
    """Отменить парсер"""
    if user_id in tasks_by_user:
        tasks_by_user[user_id].cancel()
        await bot.send_message(user_id, "🛑 Поиск успешно отменен")
        return True
    await bot.send_message(user_id, "ℹ️ Нет активного поиска для отмены")
    return False

async def shutdown_parsers():
    """Остановить все парсеры"""
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
    result_counter.clear()
    logger.info("All parsers shutdown complete")
