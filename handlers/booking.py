"""Онлайн-запись: услуга → мастер → день → время → телефон → запись. «Мои записи» с отменой."""
from datetime import datetime, timedelta

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove

import data
import db
import logic
from handlers.common import MENU_BTN, chunks, kb, main_menu, notify_owner, now_local, parse_phone, phone_kb

router = Router()


class Book(StatesGroup):
    phone = State()


def services_kb():
    rows = [[(f"{s['name']} — {logic.money(s['price'])}", f"bs:{s['id']}")] for s in data.SERVICES]
    rows.append([("🗓 Мои записи", "bk:my"), MENU_BTN])
    return kb(rows)


@router.callback_query(F.data == "m:book")
async def book_start(c: CallbackQuery, state: FSMContext):
    await state.clear()
    s = data.SALON
    await c.message.edit_text(f"<b>{s['name']}</b>\n{s['address']}\n\nВыберите услугу:", reply_markup=services_kb())
    await c.answer()


@router.callback_query(F.data.startswith("bs:"))
async def pick_service(c: CallbackQuery):
    sid = c.data[3:]
    svc = logic.service(sid)
    if not svc:
        return await c.answer("Услуга не найдена", show_alert=True)
    rows = [[(m["name"], f"bm:{sid}:{m['id']}")] for m in logic.masters_for(sid)]
    rows.append([("⬅️ Назад", "m:book")])
    await c.message.edit_text(f"{svc['name']}, {svc['dur']} мин, {logic.money(svc['price'])}\n\nК кому записаться?", reply_markup=kb(rows))
    await c.answer()


def _day_slots(sid: str, mid: str, day: datetime, now: datetime) -> list[datetime]:
    svc = logic.service(sid)
    return logic.free_slots(day, mid, svc["dur"], db.busy(mid, f"{day:%Y-%m-%d}"), now)


@router.callback_query(F.data.startswith("bm:"))
async def pick_master(c: CallbackQuery):
    _, sid, mid = c.data.split(":")
    now = now_local()
    days = [d for d in logic.booking_days(now) if _day_slots(sid, mid, d, now)]
    if not days:
        return await c.answer("У мастера нет свободного времени на ближайшую неделю", show_alert=True)
    btns = [(logic.day_label(d, now), f"bd:{sid}:{mid}:{d:%Y%m%d}") for d in days]
    rows = chunks(btns, 2) + [[("⬅️ Назад", f"bs:{sid}")]]
    await c.message.edit_text(f"Мастер: {logic.master(mid)['name']}\nВыберите день:", reply_markup=kb(rows))
    await c.answer()


@router.callback_query(F.data.startswith("bd:"))
async def pick_day(c: CallbackQuery):
    _, sid, mid, ds = c.data.split(":")
    day = datetime.strptime(ds, "%Y%m%d")
    slots = _day_slots(sid, mid, day, now_local())
    if not slots:
        return await c.answer("На этот день всё занято, выберите другой", show_alert=True)
    btns = [(f"{t:%H:%M}", f"bt:{sid}:{mid}:{t:%Y%m%d%H%M}") for t in slots]
    rows = chunks(btns, 4) + [[("⬅️ Другой день", f"bm:{sid}:{mid}")]]
    await c.message.edit_text(f"{logic.day_label(day, now_local())}: свободное время", reply_markup=kb(rows))
    await c.answer()


@router.callback_query(F.data.startswith("bt:"))
async def pick_time(c: CallbackQuery, state: FSMContext):
    _, sid, mid, ts = c.data.split(":")
    start = datetime.strptime(ts, "%Y%m%d%H%M")
    await state.set_state(Book.phone)
    await state.update_data(sid=sid, mid=mid, start=ts)
    svc, m = logic.service(sid), logic.master(mid)
    await c.message.edit_text(f"{svc['name']} у мастера {m['name']}\n{logic.day_label(start, now_local())}, {start:%H:%M}")
    await c.message.answer("Оставьте номер телефона для подтверждения записи:", reply_markup=phone_kb())
    await c.answer()


@router.message(Book.phone)
async def got_phone(m: Message, state: FSMContext):
    phone = m.contact.phone_number if m.contact else parse_phone(m.text)
    if not phone:
        return await m.answer("Не похоже на номер. Нажмите кнопку ниже или напишите номер, например +7 999 123-45-67",
                              reply_markup=phone_kb())
    st = await state.get_data()
    await state.clear()
    svc, mst = logic.service(st["sid"]), logic.master(st["mid"])
    start = datetime.strptime(st["start"], "%Y%m%d%H%M")
    end = start + timedelta(minutes=svc["dur"])
    if start < now_local():
        return await m.answer("Это время уже прошло, выберите другое.", reply_markup=services_kb())
    bid = db.add_booking(m.from_user.id, m.from_user.full_name, phone, svc["id"], mst["id"], start, end)
    if bid is None:
        await m.answer("Ой, это время только что заняли. Выберите другое:", reply_markup=ReplyKeyboardRemove())
        return await m.answer("Услуги:", reply_markup=services_kb())
    when = f"{logic.day_label(start, now_local())}, {start:%H:%M}"
    await m.answer(f"✅ Вы записаны!\n\n{svc['name']}\nМастер: {mst['name']}\n{when}\n{data.SALON['address']}\n\n"
                   f"Напомню за пару часов до визита.", reply_markup=ReplyKeyboardRemove())
    await m.answer("Что дальше?", reply_markup=kb([[("🗓 Мои записи", "bk:my")], [MENU_BTN]]))
    await notify_owner(m.bot, f"📅 <b>Новая запись #{bid}</b>\n{svc['name']} ({logic.money(svc['price'])})\nМастер: {mst['name']}\n"
                              f"{start:%d.%m %H:%M}–{end:%H:%M}\nКлиент: {m.from_user.full_name}, {phone}", m.chat.id)


@router.callback_query(F.data == "bk:my")
async def my_bookings(c: CallbackQuery):
    rows = db.user_bookings(c.from_user.id, now_local())
    if not rows:
        await c.message.edit_text("У вас нет предстоящих записей.", reply_markup=kb([[("📅 Записаться", "m:book")], [MENU_BTN]]))
        return await c.answer()
    lines, btns = [], []
    for r in rows:
        st = datetime.fromisoformat(r["start"])
        svc, mst = logic.service(r["service"]), logic.master(r["master"])
        lines.append(f"• {st:%d.%m %H:%M} — {svc['name'] if svc else r['service']}, {mst['name'] if mst else r['master']}")
        btns.append([(f"❌ Отменить {st:%d.%m %H:%M}", f"bx:{r['id']}")])
    await c.message.edit_text("Ваши записи:\n" + "\n".join(lines), reply_markup=kb(btns + [[MENU_BTN]]))
    await c.answer()


@router.callback_query(F.data.startswith("bx:"))
async def cancel_booking(c: CallbackQuery):
    bid = int(c.data[3:])
    r = db.get_booking(bid)
    if r is None or not db.cancel_booking(bid, c.from_user.id):
        return await c.answer("Запись не найдена", show_alert=True)
    await c.answer("Запись отменена")
    await notify_owner(c.bot, f"❌ <b>Отмена записи #{bid}</b>\n{r['start']} · {r['name']}, {r['phone']}", c.message.chat.id)
    await my_bookings(c)
