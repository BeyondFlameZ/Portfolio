"""Последний роутер: сообщения вне сценариев."""
from aiogram import Router
from aiogram.filters import StateFilter
from aiogram.types import Message

from handlers.common import main_menu
from i18n import tr

router = Router()


@router.message(StateFilter(None))
async def fallback(m: Message):
    await m.answer(tr("Я бот-витрина, работаю кнопками. Выберите, что посмотреть:", "I'm a demo bot and work with buttons. Choose what to try:"),
                   reply_markup=main_menu())
