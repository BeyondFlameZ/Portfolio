"""
Бот-витрина для портфолио: три типовых бота (онлайн-запись, магазин, квиз-заявки) + админка владельца.
Запуск: BOT_TOKEN=... ADMIN_IDS=... python bot.py
"""
import asyncio
import logging
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand

import config
import db
import logic
from handlers import admin, booking, fallback, menu, quiz, shop
from handlers.common import log, now_local

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def build_dispatcher() -> Dispatcher:
    dp = Dispatcher()
    dp.include_routers(menu.router, admin.router, booking.router, shop.router, quiz.router, fallback.router)
    return dp


async def reminders(bot: Bot):
    """Раз в минуту: напомнить клиентам о записи за REMIND_BEFORE_MIN минут."""
    while True:
        try:
            now = now_local()
            for r in db.due_reminders(now + timedelta(minutes=config.REMIND_BEFORE_MIN), now):
                st = datetime.fromisoformat(r["start"])
                svc, mst = logic.service(r["service"]), logic.master(r["master"])
                try:
                    await bot.send_message(r["user_id"], f"⏰ Напоминаем: сегодня в {st:%H:%M} — {svc['name'] if svc else ''}, "
                                                         f"мастер {mst['name'] if mst else ''}. Ждём вас!")
                except Exception as e:
                    log.warning("напоминание %s: %s", r["id"], e)
                db.mark_reminded(r["id"])
        except Exception:
            log.exception("цикл напоминаний")
        await asyncio.sleep(60)


async def main():
    if not config.BOT_TOKEN:
        raise SystemExit("Нет BOT_TOKEN — добавь переменную на Railway")
    bot = Bot(config.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    db.conn()
    await bot.set_my_commands([BotCommand(command="start", description="Главное меню"),
                               BotCommand(command="admin", description="Админка (для владельца)"),
                               BotCommand(command="cancel", description="Отменить текущее действие")])
    asyncio.create_task(reminders(bot))
    await build_dispatcher().start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
