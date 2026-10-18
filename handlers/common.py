"""Общее: время заведения, клавиатуры, уведомления владельцу (и превью для клиента в демо-режиме)."""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup

import config

log = logging.getLogger("bot")

# Если задан ADMIN_BOT_TOKEN, bot.py кладёт сюда оба бота:
# CLIENT_BOT — бот для клиентов, ADMIN_BOT — служебный бот владельца (уведомления и админка).
CLIENT_BOT: Bot | None = None
ADMIN_BOT: Bot | None = None


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


def fmt_phone(p: str | None) -> str:
    """Телефон в читаемом виде: +7 911 337-65-94 (российские номера), остальные — как есть с плюсом."""
    d = "".join(ch for ch in p or "" if ch.isdigit())
    if len(d) == 11 and d[0] in "78":
        return f"+7 {d[1:4]} {d[4:7]}-{d[7:9]}-{d[9:11]}"
    if len(d) == 10 and d[0] == "9":
        return f"+7 {d[0:3]} {d[3:6]}-{d[6:8]}-{d[8:10]}"
    return ("+" + d) if d else (p or "")


def parse_phone(text: str | None) -> str | None:
    if not text:
        return None
    t = text.strip()
    if PHONE_RE.fullmatch(t) and sum(ch.isdigit() for ch in t) >= 10:
        return t
    return None


async def notify_owner(bot: Bot, text: str, user_chat: int | None = None, markup=None):
    """
    Уведомление владельцу бизнеса — в служебный бот, если он настроен, иначе в этот же.
    В демо-режиме клиент тоже видит, как это выглядит у владельца.
    """
    sender = ADMIN_BOT or bot
    for a in config.ADMIN_IDS:
        try:
            await sender.send_message(a, text, reply_markup=markup)
        except Exception as e:                      # владелец мог не запускать бота
            log.warning("не отправил админу %s: %s", a, e)
    if config.DEMO_MODE and user_chat is not None and user_chat not in config.ADMIN_IDS:
        where = " (в отдельный служебный бот)" if ADMIN_BOT else ""
        await bot.send_message(user_chat, f"👀 <b>Так это сообщение получит владелец бизнеса{where}:</b>\n\n" + text)
