"""
Бот-витрина для портфолио: три типовых бота (онлайн-запись, магазин, квиз-заявки) + админка владельца.
Запуск: BOT_TOKEN=... ADMIN_IDS=... python bot.py
"""
import asyncio
import logging
from datetime import datetime, timedelta

from aiogram import BaseMiddleware, Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand

import config
import db
import logic
from i18n import LANG, detect, tr, use_lang
from handlers import admin, booking, fallback, menu, quiz, shop
from handlers import common
from handlers.common import log, now_local

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


class LangMiddleware(BaseMiddleware):
    """Язык на каждый апдейт: сохранённый выбор пользователя, иначе язык его Telegram."""
    async def __call__(self, handler, event, data):
        user = data.get("event_from_user")
        lang = None
        if user is not None:
            lang = db.get_lang(user.id) or detect(user.language_code)
        tok = LANG.set(lang or LANG.get())
        try:
            return await handler(event, data)
        finally:
            LANG.reset(tok)


def _with_lang(dp: Dispatcher) -> Dispatcher:
    dp.update.outer_middleware(LangMiddleware())
    return dp


def _detached(*routers):
    """Роутеры aiogram цепляются к одному диспетчеру. Отвязываем перед сборкой, чтобы диспетчеры можно было пересоздавать (тесты)."""
    for r in routers:
        r._parent_router = None
    return routers


def build_dispatcher(split: bool = False) -> Dispatcher:
    """Клиентский бот. split=True — админка вынесена в служебного бота, здесь только подсказка на /admin."""
    dp = _with_lang(Dispatcher())
    if split:
        dp.include_routers(*_detached(menu.router, menu.admin_hint_router, booking.router, shop.router, quiz.router, fallback.router))
    else:
        dp.include_routers(*_detached(menu.router, admin.router, booking.router, shop.router, quiz.router, fallback.router))
    return dp


def build_admin_dispatcher() -> Dispatcher:
    """Служебный бот владельца: /start → админка, сюда же приходят уведомления."""
    dp = _with_lang(Dispatcher())
    dp.include_routers(*_detached(admin.admin_bot_router, admin.router))
    return dp


async def reminders(bot: Bot):
    """Раз в минуту: напомнить клиентам о записи за REMIND_BEFORE_MIN минут."""
    while True:
        try:
            now = now_local()
            for r in db.due_reminders(now + timedelta(minutes=config.REMIND_BEFORE_MIN), now):
                st = datetime.fromisoformat(r["start"])
                with use_lang(db.get_lang(r["user_id"])):          # напоминание — на языке клиента
                    svc, mst = logic.service(r["service"]), logic.master(r["master"])
                    text = tr(f"⏰ Напоминаем: сегодня в {st:%H:%M} — {svc['name'] if svc else ''}, мастер {mst['name'] if mst else ''}. Ждём вас!",
                              f"⏰ Reminder: today at {st:%H:%M} — {svc['name'] if svc else ''} with {mst['name'] if mst else ''}. See you!")
                try:
                    await bot.send_message(r["user_id"], text)
                except Exception as e:
                    log.warning("напоминание %s: %s", r["id"], e)
                db.mark_reminded(r["id"])
        except Exception:
            log.exception("цикл напоминаний")
        await asyncio.sleep(60)


async def main():
    if not config.BOT_TOKEN:
        raise SystemExit("Нет BOT_TOKEN — добавь переменную на Railway")
    props = DefaultBotProperties(parse_mode=ParseMode.HTML)
    bot = Bot(config.BOT_TOKEN, default=props)
    db.conn()
    split = bool(config.ADMIN_BOT_TOKEN)
    asyncio.create_task(reminders(bot))
    if not split:
        await bot.set_my_commands([BotCommand(command="start", description="Главное меню"),
                                   BotCommand(command="admin", description="Админка (для владельца)"),
                                   BotCommand(command="cancel", description="Отменить текущее действие")])
        await bot.set_my_commands([BotCommand(command="start", description="Main menu"),
                                   BotCommand(command="admin", description="Admin panel (owner)"),
                                   BotCommand(command="cancel", description="Cancel current action")], language_code="en")
        await build_dispatcher().start_polling(bot)
        return
    admin_bot = Bot(config.ADMIN_BOT_TOKEN, default=props)
    common.CLIENT_BOT, common.ADMIN_BOT = bot, admin_bot
    await bot.set_my_commands([BotCommand(command="start", description="Главное меню"),
                               BotCommand(command="cancel", description="Отменить текущее действие")])
    await bot.set_my_commands([BotCommand(command="start", description="Main menu"),
                               BotCommand(command="cancel", description="Cancel current action")], language_code="en")
    await admin_bot.set_my_commands([BotCommand(command="start", description="Админка"),
                                     BotCommand(command="cancel", description="Отменить рассылку")])
    await admin_bot.set_my_commands([BotCommand(command="start", description="Admin panel"),
                                     BotCommand(command="cancel", description="Cancel broadcast")], language_code="en")
    log.info("Раздельный режим: клиентский бот + служебный бот владельца")
    await asyncio.gather(build_dispatcher(split=True).start_polling(bot, handle_signals=False),
                         build_admin_dispatcher().start_polling(admin_bot, handle_signals=False))


if __name__ == "__main__":
    asyncio.run(main())
