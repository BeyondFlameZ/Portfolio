"""Админка владельца: /admin — статистика, записи на сегодня, последние заказы/заявки, выгрузка в Excel (CSV), рассылка."""
import asyncio
import json
from datetime import datetime, timedelta

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, CallbackQuery, Message

import config
import db
import logic
from handlers import common
from handlers.common import kb, now_local

router = Router()


class Broadcast(StatesGroup):
    text = State()
    confirm = State()


def is_admin(uid: int) -> bool:
    return uid in config.ADMIN_IDS


def admin_kb():
    return kb([[("📅 Записи на сегодня", "a:today"), ("📆 Все записи", "a:all")],
               [("🛒 Заказы", "a:orders")],
               [("🔥 Заявки", "a:leads"), ("📥 Выгрузка в Excel", "a:export")],
               [("📣 Рассылка", "a:bcast")]])


# Служебный бот владельца (ADMIN_BOT_TOKEN): /start сразу открывает админку.
admin_bot_router = Router()


@admin_bot_router.message(Command("start"))
async def admin_bot_start(m: Message, state: FSMContext):
    if not is_admin(m.from_user.id):
        return await m.answer("Это служебный бот владельца. Доступ закрыт.")
    await m.answer("Сюда будут приходить новые записи, заказы и заявки.")
    await admin(m, state)


@admin_bot_router.message(Command("cancel"))
async def admin_bot_cancel(m: Message, state: FSMContext):
    await state.clear()
    await m.answer("Отменено.")


@router.message(Command("admin"))
async def admin(m: Message, state: FSMContext):
    if not is_admin(m.from_user.id):
        return await m.answer("Админка доступна только владельцу. В демо её можно показать по запросу.")
    await state.clear()
    s = db.stats()
    await m.answer(f"<b>Админка</b>\nПользователей: {s['users']}\nАктивных записей: {s['bookings']}\n"
                   f"Заказов: {s['orders']} на {logic.money(s['revenue'])}\nЗаявок: {s['leads']}", reply_markup=admin_kb())


WD = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]


def booking_line(r) -> str:
    svc, mst = logic.service(r["service"]), logic.master(r["master"])
    return (f"• {r['start'][11:16]} {svc['name'] if svc else r['service']}, {mst['name'] if mst else r['master']} — "
            f"{r['name']}, {r['phone']}")


def days_kb():
    """Кнопки на 14 дней вперёд: день недели, число и сколько записей."""
    today = now_local().date()
    rows, row = [], []
    for i in range(14):
        d = today + timedelta(days=i)
        n = len(db.bookings_on(f"{d:%Y-%m-%d}"))
        row.append((f"{WD[d.weekday()]} {d:%d.%m}" + (f" ({n})" if n else ""), f"a:day:{d:%Y-%m-%d}"))
        if len(row) == 3:
            rows.append(row); row = []
    if row:
        rows.append(row)
    return kb(rows)


def order_card(r) -> str:
    """Карточка заказа для владельца: состав, сумма, оплата, контакты и адрес."""
    try:
        items = json.loads(r["items"] or "{}")
    except ValueError:
        items = {}
    lines = ", ".join(f"{p['name']} × {q}" for p, q, _ in logic.cart_lines(items)) or "—"
    if r["paid"]:
        pay = "✅ оплачен онлайн"
    elif config.PAYMENT_TOKEN:
        pay = "⏳ ждёт оплаты"
    else:
        pay = "💵 оплата при получении"
    addr = r["address"] or "—"
    where = "🏃 Самовывоз" if addr == "самовывоз" else f"🚚 {addr}"
    return (f"<b>#{r['id']}</b> · {(r['created'] or '')[:16]} · {logic.money(r['goods'] + r['delivery'])} · {pay}\n"
            f"{lines}\n{r['name']}, {r['phone']}\n{where}")


async def send_long(message, text: str):
    """Telegram режет сообщения на 4096 символах — шлём кусками по строкам."""
    buf = ""
    for line in text.split("\n"):
        if len(buf) + len(line) + 1 > 3800:
            await message.answer(buf); buf = ""
        buf += line + "\n"
    if buf.strip():
        await message.answer(buf)


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
    elif a == "all":
        rows = db.bookings_from(f"{now_local():%Y-%m-%d %H:%M}")
        if not rows:
            await c.message.answer("Предстоящих записей нет.", reply_markup=days_kb())
        else:
            out, day = [f"<b>Все предстоящие записи: {len(rows)}</b>"], None
            for r in rows:
                d = r["start"][:10]
                if d != day:
                    dt = datetime.strptime(d, "%Y-%m-%d")
                    out.append(f"\n<b>{WD[dt.weekday()]} {dt:%d.%m}</b>"); day = d
                out.append(booking_line(r))
            await send_long(c.message, "\n".join(out))
            await c.message.answer("Посмотреть конкретный день:", reply_markup=days_kb())
    elif a.startswith("day:"):
        d = a[4:]
        rows = db.bookings_on(d)
        dt = datetime.strptime(d, "%Y-%m-%d")
        await send_long(c.message, f"<b>Записи на {WD[dt.weekday()]} {dt:%d.%m}:</b>\n" + ("\n".join(booking_line(r) for r in rows) or "нет"))
    elif a == "orders":
        rows = db.recent("orders")
        await send_long(c.message, "<b>Последние заказы:</b>\n\n" + ("\n\n".join(order_card(r) for r in rows) or "нет"))
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
    sender = common.CLIENT_BOT or c.bot          # клиентам пишет клиентский бот, даже если кнопку нажали в служебном
    for uid in db.all_users():
        try:
            await sender.send_message(uid, st["text"])
            ok += 1
        except Exception:
            fail += 1
        await asyncio.sleep(0.05)              # ~20 сообщений в секунду — в лимитах Telegram
    await c.message.answer(f"Готово: доставлено {ok}, не доставлено {fail} (заблокировали бота).")
    await c.answer()
