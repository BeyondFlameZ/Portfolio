from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove

import config
import db
from handlers.common import kb, main_menu, MENU_BTN

router = Router()

WELCOME = ("Привет! Это демо-бот <b>{brand}</b>.\n\n"
           "Здесь три типовых бота, которые я делаю на заказ. Потыкайте их как клиент, "
           "после каждого действия покажу, какое уведомление получит владелец бизнеса.\n\n"
           "Выберите, что посмотреть:")

ORDER = ("<b>Что могу сделать для вашего бизнеса</b>\n\n"
         "• Онлайн-запись: услуги, мастера, свободное время, напоминания клиентам.\n"
         "• Магазин или меню доставки: каталог, корзина, оформление, онлайн-оплата.\n"
         "• Квиз и сбор заявок: расчёт цены, телефон клиента сразу менеджеру.\n"
         "• Рассылки, админка, выгрузка в Excel, интеграции с CRM и таблицами.\n"
         "• Нестандартное: парсеры, уведомления, боты для каналов, ИИ-консультант.\n\n"
         "Работаю под ключ: настрою, размещу на сервере, покажу владельцу, как пользоваться.\n\n"
         "{contact}")


@router.message(CommandStart())
async def start(m: Message, state: FSMContext):
    await state.clear()
    db.touch_user(m.from_user.id, m.from_user.full_name, m.from_user.username)
    await m.answer(WELCOME.format(brand=config.BRAND), reply_markup=main_menu())


@router.message(Command("menu"))
async def menu_cmd(m: Message, state: FSMContext):
    await state.clear()
    await m.answer("Главное меню:", reply_markup=main_menu())


@router.message(Command("cancel"))
async def cancel_cmd(m: Message, state: FSMContext):
    await state.clear()
    await m.answer("Отменено.", reply_markup=ReplyKeyboardRemove())
    await m.answer("Главное меню:", reply_markup=main_menu())


@router.callback_query(F.data == "m:home")
async def home(c: CallbackQuery, state: FSMContext):
    await state.clear()
    await c.message.edit_text(WELCOME.format(brand=config.BRAND), reply_markup=main_menu())
    await c.answer()


@router.callback_query(F.data == "m:order")
async def order_info(c: CallbackQuery):
    contact = f"Написать мне: {config.CONTACT}" if config.CONTACT else "Напишите мне на Kwork, обсудим задачу."
    await c.message.edit_text(ORDER.format(contact=contact), reply_markup=kb([[MENU_BTN]]))
    await c.answer()
