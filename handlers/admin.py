"""Админка владельца: /admin — статистика, записи на сегодня, последние заказы/заявки, выгрузка в Excel (CSV), рассылка."""
import asyncio
from datetime import datetime

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, CallbackQuery, Message

import config
import db
import logic
from handlers.common import kb, now_local

router = Router()


class Broadcast(StatesGroup):
    text = State()
    confirm = State()


def is_admin(uid: int) -> bool:
    return uid in config.ADMIN_IDS


def admin_kb():
    return kb([[("📅 Записи на сегодня", "a:today"), ("🛒 Заказы", "a:orders")],
               [("🔥 Заявки", "a:leads"), ("📥 Выгрузка в Excel", "a:export")],
               [("📣 Рассылка", "a:bcast")]])


@router.message(Command("admin"))
async def admin(m: Message, state: FSMContext):
    if not is_admin(m.from_user.id):
        return await m.answer("Админка доступна только владельцу. В демо её можно показать по запросу.")
    await state.clear()
    s = db.stats()
    await m.answer(f"<b>Админка</b>\nПользователей: {s['users']}\nАктивных записей: {s['bookings']}\n"
                   f"Заказов: {s['orders']} на {logic.money(s['revenue'])}\nЗаявок: {s['leads']}", reply_markup=admin_kb())


@router.callback_query(F.data.startswith("a:"))
async def admin_cb(c: CallbackQuery, state: FSMContext):
    if not is_admin(c.from_user.id):
        return await c.answer("Только для владельца", show_alert=True)
    a = c.data[2:]
    if a == "today":
        rows = db.bookings_on(f"{now_local():%Y-%m-%d}")
        text = "Записи на сегодня:\n" + ("\n".join(f"• {r['start'][11:]} {logic.service(r['service'])['name'] if logic.service(r['service']) else r['service']}, "
                                                  f"{logic.master(r['master'])['name'] if logic.master(r['master']) else r['master']} — {r['name']}, {r['phone']}"
                                                  for r in rows) or "нет")
        await c.message.answer(text)
    elif a == "orders":
        rows = db.recent("orders")
        await c.message.answer("Последние заказы:\n" + ("\n".join(
            f"#{r['id']} {logic.money(r['goods'] + r['delivery'])} {'✅ оплачен' if r['paid'] else ''} — {r['name']}, {r['phone']}" for r in rows) or "нет"))
    elif a == "leads":
        rows = db.recent("leads")
        await c.message.answer("Последние заявки:\n" + ("\n".join(f"#{r['id']} {r['name']}, {r['phone']} — {r['estimate']}" for r in rows) or "нет"))
    elif a == "export":
        stamp = f"{datetime.now():%Y%m%d}"
        for t in ("bookings", "orders", "leads", "users"):
            await c.message.answer_document(BufferedInputFile(db.export_csv(t), filename=f"{t}_{stamp}.csv"))
    elif a == "bcast":
        await state.set_state(Broadcast.text)
        await c.message.answer("Пришлите текст рассылки (или /cancel):")
    await c.answer()


@router.message(Broadcast.text)
async def bcast_text(m: Message, state: FSMContext):
    if not is_admin(m.from_user.id):
        return
    if (m.text or "").startswith("/"):
        await state.clear()
        return await m.answer("Рассылка отменена.")
    await state.update_data(text=m.html_text)
    await state.set_state(Broadcast.confirm)
    n = len(db.all_users())
    await m.answer(f"Отправить это сообщение {n} пользователям?\n\n{m.html_text}",
                   reply_markup=kb([[("✅ Отправить", "bc:yes"), ("✖️ Отмена", "bc:no")]]))


@router.callback_query(F.data.startswith("bc:"), Broadcast.confirm)
async def bcast_go(c: CallbackQuery, state: FSMContext):
    if not is_admin(c.from_user.id):
        return await c.answer()
    st = await state.get_data()
    await state.clear()
    if c.data == "bc:no":
        await c.message.edit_text("Рассылка отменена.")
        return await c.answer()
    await c.message.edit_text("Рассылаю…")
    ok = fail = 0
    for uid in db.all_users():
        try:
            await c.bot.send_message(uid, st["text"])
            ok += 1
        except Exception:
            fail += 1
        await asyncio.sleep(0.05)              # ~20 сообщений в секунду — в лимитах Telegram
    await c.message.answer(f"Готово: доставлено {ok}, не доставлено {fail} (заблокировали бота).")
    await c.answer()
