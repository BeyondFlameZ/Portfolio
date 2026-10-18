"""Последний роутер: сообщения вне сценариев."""
from aiogram import Router
from aiogram.filters import StateFilter
from aiogram.types import Message

from handlers.common import main_menu

router = Router()


@router.message(StateFilter(None))
async def fallback(m: Message):
    await m.answer("Я бот-витрина, работаю кнопками. Выберите, что посмотреть:", reply_markup=main_menu())
