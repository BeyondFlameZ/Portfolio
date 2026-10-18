from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove

import config
import db
from i18n import LANG, en, tr
from handlers.common import kb, main_menu, menu_btn

router = Router()

WELCOME_RU = ("Привет! Это демо-бот <b>{brand}</b>.\n\n"
           "Здесь три типовых бота, которые я делаю на заказ. Потыкайте их как клиент, "
           "после каждого действия покажу, какое уведомление получит владелец бизнеса.\n\n"
           "Выберите, что посмотреть:")

ORDER_RU = ("<b>Что могу сделать для вашего бизнеса</b>\n\n"
         "• Онлайн-запись: услуги, мастера, свободное время, напоминания клиентам.\n"
         "• Магазин или меню доставки: каталог, корзина, оформление, онлайн-оплата.\n"
         "• Квиз и сбор заявок: расчёт цены, телефон клиента сразу менеджеру.\n"
         "• Рассылки, админка, выгрузка в Excel, интеграции с CRM и таблицами.\n"
         "• Нестандартное: парсеры, уведомления, боты для каналов, ИИ-консультант.\n\n"
         "Работаю под ключ: настрою, размещу на сервере, покажу владельцу, как пользоваться.\n\n"
         "{contact}")


WELCOME_EN = ("Hi! This is a demo bot by <b>{brand}</b>.\n\n"
              "Here are three typical bots I build for businesses. Try them as a customer: after each step "
              "I'll show you the notification the business owner receives.\n\n"
              "Choose what to try:")

ORDER_EN = ("<b>What I can build for your business</b>\n\n"
            "• Online booking: services, staff, free slots, reminders.\n"
            "• Shop or delivery menu: catalog, cart, checkout, online payments (Stripe, crypto).\n"
            "• Quizzes and lead capture: price estimate, phone straight to your manager.\n"
            "• Broadcasts, admin panel, Excel export, CRM / Google Sheets integrations.\n"
            "• Custom: crypto & trading bots (Bybit/Binance), parsers, alerts, channel bots, AI assistants.\n\n"
            "Turnkey: I set it up, host it and show you how to use it.\n\n"
            "{contact}")


def WELCOME():
    return WELCOME_EN if en() else WELCOME_RU


def ORDER():
    return ORDER_EN if en() else ORDER_RU


@router.message(CommandStart())
async def start(m: Message, state: FSMContext):
    await state.clear()
    db.touch_user(m.from_user.id, m.from_user.full_name, m.from_user.username)
    await m.answer(WELCOME().format(brand=config.BRAND), reply_markup=main_menu())


@router.message(Command("menu"))
async def menu_cmd(m: Message, state: FSMContext):
    await state.clear()
    await m.answer(tr("Главное меню:", "Main menu:"), reply_markup=main_menu())


@router.message(Command("cancel"))
async def cancel_cmd(m: Message, state: FSMContext):
    await state.clear()
    await m.answer(tr("Отменено.", "Cancelled."), reply_markup=ReplyKeyboardRemove())
    await m.answer(tr("Главное меню:", "Main menu:"), reply_markup=main_menu())


@router.callback_query(F.data == "m:home")
async def home(c: CallbackQuery, state: FSMContext):
    await state.clear()
    await c.message.edit_text(WELCOME().format(brand=config.BRAND), reply_markup=main_menu())
    await c.answer()


@router.callback_query(F.data == "m:order")
async def order_info(c: CallbackQuery):
    contact = (f"{tr('Написать мне', 'Contact me')}: {config.CONTACT}" if config.CONTACT
               else tr("Напишите мне, обсудим задачу.", "Message me and let's discuss your project."))
    await c.message.edit_text(ORDER().format(contact=contact), reply_markup=kb([[menu_btn()]]))
    await c.answer()


# Подключается в клиентского бота только в раздельном режиме (ADMIN_BOT_TOKEN задан).
admin_hint_router = Router()


@admin_hint_router.message(Command("admin"))
async def admin_hint(m: Message):
    if m.from_user.id in config.ADMIN_IDS:
        return await m.answer(tr("Админка и уведомления — в служебном боте владельца. Откройте его и нажмите /start.",
                                 "The admin panel and notifications are in the separate owner bot. Open it and press /start."))
    await m.answer(tr("Админка доступна только владельцу.", "The admin panel is for the owner only."))


@router.callback_query(F.data == "m:lang")
async def switch_lang(c: CallbackQuery, state: FSMContext):
    """Переключатель 🇬🇧/🇷🇺: запоминаем выбор и перерисовываем меню на новом языке."""
    await state.clear()
    new = "ru" if en() else "en"
    db.set_lang(c.from_user.id, new)
    LANG.set(new)
    await c.message.edit_text(WELCOME().format(brand=config.BRAND), reply_markup=main_menu())
    await c.answer("English" if new == "en" else "Русский")
