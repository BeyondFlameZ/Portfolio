"""Общее: время заведения, клавиатуры, уведомления владельцу (и превью для клиента в демо-режиме)."""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup

import config

log = logging.getLogger("bot")


def now_local() -> datetime:
    """Текущее время заведения без tzinfo (всё в БД хранится в местном времени)."""
    return (datetime.now(timezone.utc) + timedelta(hours=config.TZ_OFFSET)).replace(tzinfo=None, second=0, microsecond=0)


def kb(rows: list[list[tuple[str, str]]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=t, callback_data=d) for t, d in row] for row in rows])


def chunks(items: list, n: int) -> list[list]:
    return [items[i:i + n] for i in range(0, len(items), n)]


MENU_BTN = ("🏠 В меню", "m:home")


def main_menu() -> InlineKeyboardMarkup:
    return kb([[("📅 Онлайн-запись (барбершоп)", "m:book")],
               [("🛒 Магазин с корзиной (кофейня)", "m:shop")],
               [("📝 Квиз-калькулятор + заявка", "m:quiz")],
               [("🤖 Хочу такого бота", "m:order")]])


def phone_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="📱 Отправить мой номер", request_contact=True)]],
                               resize_keyboard=True, one_time_keyboard=True,
                               input_field_placeholder="или напишите номер вручную")


PHONE_RE = re.compile(r"[\d+()\-\s]{10,20}")


def parse_phone(text: str | None) -> str | None:
    if not text:
        return None
    t = text.strip()
    if PHONE_RE.fullmatch(t) and sum(ch.isdigit() for ch in t) >= 10:
        return t
    return None


async def notify_owner(bot: Bot, text: str, user_chat: int | None = None):
    """Уведомление владельцу бизнеса. В демо-режиме клиент тоже видит, как это выглядит у владельца."""
    for a in config.ADMIN_IDS:
        try:
            await bot.send_message(a, text)
        except Exception as e:                      # владелец мог не запускать бота
            log.warning("не отправил админу %s: %s", a, e)
    if config.DEMO_MODE and user_chat is not None and user_chat not in config.ADMIN_IDS:
        await bot.send_message(user_chat, "👀 <b>Так это сообщение получит владелец бизнеса:</b>\n\n" + text)
