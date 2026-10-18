"""Онлайн-запись: услуга → мастер → день → время → телефон → запись. «Мои записи» с отменой."""
from datetime import datetime, timedelta

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove

import db
import logic
from i18n import D, tr
from handlers.common import bad_phone_text, fmt_phone, menu_btn, chunks, kb, main_menu, notify_owner, now_local, parse_phone, phone_kb

router = Router()


class Book(StatesGroup):
    phone = State()


def services_kb():
    rows = [[(f"{s['name']} — {logic.money(s['price'])}", f"bs:{s['id']}")] for s in D().SERVICES]
    rows.append([(tr("🗓 Мои записи", "🗓 My bookings"), "bk:my"), menu_btn()])
    return kb(rows)


@router.callback_query(F.data == "m:book")
async def book_start(c: CallbackQuery, state: FSMContext):
    await state.clear()
    s = D().SALON
    await c.message.edit_text(f"<b>{s['name']}</b>\n{s['address']}\n\n" + tr("Выберите услугу:", "Choose a service:"), reply_markup=services_kb())
    await c.answer()


@router.callback_query(F.data.startswith("bs:"))
async def pick_service(c: CallbackQuery):
    sid = c.data[3:]
    svc = logic.service(sid)
    if not svc:
        return await c.answer(tr("Услуга не найдена", "Service not found"), show_alert=True)
    rows = [[(m["name"], f"bm:{sid}:{m['id']}")] for m in logic.masters_for(sid)]
    rows.append([(tr("⬅️ Назад", "⬅️ Back"), "m:book")])
    await c.message.edit_text(f"{svc['name']}, {svc['dur']} {tr('мин', 'min')}, {logic.money(svc['price'])}\n\n" + tr("К кому записаться?", "Choose a specialist:"), reply_markup=kb(rows))
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
        return await c.answer(tr("У мастера нет свободного времени на ближайшую неделю", "No free time this week"), show_alert=True)
    btns = [(logic.day_label(d, now), f"bd:{sid}:{mid}:{d:%Y%m%d}") for d in days]
    rows = chunks(btns, 2) + [[(tr("⬅️ Назад", "⬅️ Back"), f"bs:{sid}")]]
    await c.message.edit_text(f"{tr('Мастер', 'Specialist')}: {logic.master(mid)['name']}\n" + tr("Выберите день:", "Choose a day:"), reply_markup=kb(rows))
    await c.answer()


@router.callback_query(F.data.startswith("bd:"))
async def pick_day(c: CallbackQuery):
    _, sid, mid, ds = c.data.split(":")
    day = datetime.strptime(ds, "%Y%m%d")
    slots = _day_slots(sid, mid, day, now_local())
    if not slots:
        return await c.answer(tr("На этот день всё занято, выберите другой", "Fully booked, pick another day"), show_alert=True)
    btns = [(f"{t:%H:%M}", f"bt:{sid}:{mid}:{t:%Y%m%d%H%M}") for t in slots]
    rows = chunks(btns, 4) + [[(tr("⬅️ Другой день", "⬅️ Another day"), f"bm:{sid}:{mid}")]]
    await c.message.edit_text(f"{logic.day_label(day, now_local())}: " + tr("свободное время", "available times"), reply_markup=kb(rows))
    await c.answer()


@router.callback_query(F.data.startswith("bt:"))
async def pick_time(c: CallbackQuery, state: FSMContext):
    _, sid, mid, ts = c.data.split(":")
    start = datetime.strptime(ts, "%Y%m%d%H%M")
    await state.set_state(Book.phone)
    await state.update_data(sid=sid, mid=mid, start=ts)
    svc, m = logic.service(sid), logic.master(mid)
    await c.message.edit_text(f"{svc['name']} {tr('у мастера', 'with')} {m['name']}\n{logic.day_label(start, now_local())}, {start:%H:%M}")
    await c.message.answer(tr("Оставьте номер телефона для подтверждения записи:", "Leave your phone number to confirm the booking:"), reply_markup=phone_kb())
    await c.answer()


@router.message(Book.phone)
async def got_phone(m: Message, state: FSMContext):
    phone = m.contact.phone_number if m.contact else parse_phone(m.text)
    phone = fmt_phone(phone) if phone else None
    if not phone:
        return await m.answer(bad_phone_text(), reply_markup=phone_kb())
    st = await state.get_data()
    await state.clear()
    svc, mst = logic.service(st["sid"]), logic.master(st["mid"])
    start = datetime.strptime(st["start"], "%Y%m%d%H%M")
    end = start + timedelta(minutes=svc["dur"])
    if start < now_local():
        return await m.answer(tr("Это время уже прошло, выберите другое.", "That time has passed, pick another one."), reply_markup=services_kb())
    bid = db.add_booking(m.from_user.id, m.from_user.full_name, phone, svc["id"], mst["id"], start, end)
    if bid is None:
        await m.answer(tr("Ой, это время только что заняли. Выберите другое:", "Oops, that slot was just taken. Pick another:"), reply_markup=ReplyKeyboardRemove())
        return await m.answer(tr("Услуги:", "Services:"), reply_markup=services_kb())
    when = f"{logic.day_label(start, now_local())}, {start:%H:%M}"
    await m.answer(tr("✅ Вы записаны!", "✅ You're booked!") + f"\n\n{svc['name']}\n{tr('Мастер', 'Specialist')}: {mst['name']}\n{when}\n"
                   f"{D().SALON['address']}\n\n" + tr("Напомню за пару часов до визита.", "I'll remind you a couple of hours before."),
                   reply_markup=ReplyKeyboardRemove())
    await m.answer(tr("Что дальше?", "What's next?"), reply_markup=kb([[(tr("🗓 Мои записи", "🗓 My bookings"), "bk:my")], [menu_btn()]]))
    await notify_owner(m.bot, f"📅 <b>{tr('Новая запись', 'New booking')} #{bid}</b>\n{svc['name']} ({logic.money(svc['price'])})\n"
                              f"{tr('Мастер', 'Specialist')}: {mst['name']}\n{start:%d.%m %H:%M}–{end:%H:%M}\n"
                              f"{tr('Клиент', 'Client')}: {m.from_user.full_name}, {phone}", m.chat.id)


@router.callback_query(F.data == "bk:my")
async def my_bookings(c: CallbackQuery):
    rows = db.user_bookings(c.from_user.id, now_local())
    if not rows:
        await c.message.edit_text(tr("У вас нет предстоящих записей.", "You have no upcoming bookings."), reply_markup=kb([[(tr("📅 Записаться", "📅 Book now"), "m:book")], [menu_btn()]]))
        return await c.answer()
    lines, btns = [], []
    for r in rows:
        st = datetime.fromisoformat(r["start"])
        svc, mst = logic.service(r["service"]), logic.master(r["master"])
        lines.append(f"• {st:%d.%m %H:%M} — {svc['name'] if svc else r['service']}, {mst['name'] if mst else r['master']}")
        btns.append([(f"❌ {tr('Отменить', 'Cancel')} {st:%d.%m %H:%M}", f"bx:{r['id']}")])
    await c.message.edit_text(tr("Ваши записи:", "Your bookings:") + "\n" + "\n".join(lines), reply_markup=kb(btns + [[menu_btn()]]))
    await c.answer()


@router.callback_query(F.data.startswith("bx:"))
async def cancel_booking(c: CallbackQuery):
    bid = int(c.data[3:])
    r = db.get_booking(bid)
    if r is None or not db.cancel_booking(bid, c.from_user.id):
        return await c.answer(tr("Запись не найдена", "Booking not found"), show_alert=True)
    await c.answer(tr("Запись отменена", "Booking cancelled"))
    await notify_owner(c.bot, f"❌ <b>{tr('Отмена записи', 'Booking cancelled')} #{bid}</b>\n{r['start']} · {r['name']}, {r['phone']}", c.message.chat.id)
    await my_bookings(c)
