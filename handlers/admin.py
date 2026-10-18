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
from i18n import en, tr, use_lang

router = Router()


class Broadcast(StatesGroup):
    text = State()
    confirm = State()


def is_admin(uid: int) -> bool:
    return uid in config.ADMIN_IDS


def admin_kb():
    return kb([[(tr("📅 Записи на сегодня", "📅 Today's bookings"), "a:today"), (tr("📆 Все записи", "📆 All bookings"), "a:all")],
               [(tr("🛒 Заказы", "🛒 Orders"), "a:orders"), (tr("🧹 Очистить историю", "🧹 Clear history"), "a:clear")],
               [(tr("🔥 Заявки", "🔥 Leads"), "a:leads"), (tr("📥 Выгрузка в Excel", "📥 Export to Excel"), "a:export")],
               [(tr("📣 Рассылка", "📣 Broadcast"), "a:bcast")]])


# Служебный бот владельца (ADMIN_BOT_TOKEN): /start сразу открывает админку.
admin_bot_router = Router()


@admin_bot_router.message(Command("start"))
async def admin_bot_start(m: Message, state: FSMContext):
    if not is_admin(m.from_user.id):
        return await m.answer(tr("Это служебный бот владельца. Доступ закрыт.", "This is the owner's bot. Access denied."))
    await m.answer(tr("Сюда будут приходить новые записи, заказы и заявки.", "New bookings, orders and leads will arrive here."))
    await admin(m, state)


@admin_bot_router.message(Command("cancel"))
async def admin_bot_cancel(m: Message, state: FSMContext):
    await state.clear()
    await m.answer(tr("Отменено.", "Cancelled."))


@router.message(Command("admin"))
async def admin(m: Message, state: FSMContext):
    if not is_admin(m.from_user.id):
        return await m.answer(tr("Админка доступна только владельцу. В демо её можно показать по запросу.", "The admin panel is for the owner only. I can show it on request."))
    await state.clear()
    s = db.stats()
    await m.answer(f"<b>{tr('Админка', 'Admin panel')}</b>\n{tr('Пользователей', 'Users')}: {s['users']}\n"
                   f"{tr('Активных записей', 'Active bookings')}: {s['bookings']}\n"
                   f"{tr('Заказов', 'Orders')}: {s['orders']} {tr('на', 'for')} {logic.money(s['revenue'])}\n"
                   f"{tr('Заявок', 'Leads')}: {s['leads']}", reply_markup=admin_kb())


WD_RU = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]
WD_EN = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def wd(d) -> str:
    return (WD_EN if en() else WD_RU)[d.weekday()]


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
        row.append((f"{wd(d)} {d:%d.%m}" + (f" ({n})" if n else ""), f"a:day:{d:%Y-%m-%d}"))
        if len(row) == 3:
            rows.append(row); row = []
    if row:
        rows.append(row)
    return kb(rows)


def status_label(st: str) -> str:
    return {"new": tr("🆕 Новый", "🆕 New"), "paid": tr("🆕 Новый", "🆕 New"), "work": tr("🚚 В работе", "🚚 In progress"),
            "done": tr("✅ Выполнен", "✅ Done"), "cancel": tr("✖️ Отменён", "✖️ Cancelled")}.get(st) or tr("🆕 Новый", "🆕 New")


def client_msg(st: str, oid: int) -> str | None:
    """Сообщение клиенту о смене статуса — на языке клиента (вызывать внутри use_lang)."""
    return {"work": tr(f"🚚 Ваш заказ #{oid} готовится и скоро будет у вас!", f"🚚 Your order #{oid} is being prepared and will be with you soon!"),
            "done": tr(f"✅ Заказ #{oid} выполнен. Спасибо, что выбрали нас!", f"✅ Order #{oid} is complete. Thank you for choosing us!"),
            "cancel": tr(f"Заказ #{oid} отменён. Если это ошибка — напишите нам.", f"Order #{oid} was cancelled. If this is a mistake, message us.")}.get(st)


def order_kb(r):
    """Кнопки смены статуса под карточкой заказа."""
    oid, st = r["id"], r["status"]
    if st in ("done", "cancel"):
        return kb([[(tr("↩️ Вернуть в работу", "↩️ Back to work"), f"os:{oid}:work")]])
    row = [] if st == "work" else [(tr("🚚 В работу", "🚚 In progress"), f"os:{oid}:work")]
    row.append((tr("✅ Выполнен", "✅ Done"), f"os:{oid}:done"))
    return kb([row, [(tr("✖️ Отменить", "✖️ Cancel"), f"os:{oid}:cancel")]])


def orders_menu():
    n = db.order_counts()
    return kb([[(f"{tr('🆕 Активные', '🆕 Active')} ({n['active']})", "a:o_active"), (f"{tr('✅ Выполненные', '✅ Done')} ({n['done']})", "a:o_done")],
               [(tr("📋 Последние 10", "📋 Last 10"), "a:o_recent")]])


def order_card(r) -> str:
    """Карточка заказа для владельца: состав, сумма, оплата, контакты и адрес."""
    try:
        items = json.loads(r["items"] or "{}")
    except ValueError:
        items = {}
    lines = ", ".join(f"{p['name']} × {q}" for p, q, _ in logic.cart_lines(items)) or "—"
    if r["paid"]:
        pay = tr("💳 оплачен онлайн", "💳 paid online")
    elif config.PAYMENT_TOKEN:
        pay = tr("⏳ ждёт оплаты", "⏳ awaiting payment")
    else:
        pay = tr("💵 оплата при получении", "💵 pay on delivery")
    addr = r["address"] or "—"
    where = tr("🏃 Самовывоз", "🏃 Pickup") if addr == "самовывоз" else f"🚚 {addr}"
    cr = (r["created"] or "").replace("T", " ")
    try:
        cr = datetime.strptime(cr[:16], "%Y-%m-%d %H:%M").strftime("%d.%m %H:%M")
    except ValueError:
        pass
    return (f"{status_label(r['status'])}\n<b>#{r['id']}</b> · {cr} · {logic.money(r['goods'] + r['delivery'])} · {pay}\n"
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
        return await c.answer(tr("Только для владельца", "Owner only"), show_alert=True)
    a = c.data[2:]
    if a == "today":
        rows = db.bookings_on(f"{now_local():%Y-%m-%d}")
        text = tr("Записи на сегодня:", "Today's bookings:") + "\n" + ("\n".join(booking_line(r) for r in rows) or tr("нет", "none"))
        await c.message.answer(text)
    elif a == "all":
        rows = db.bookings_from(f"{now_local():%Y-%m-%d %H:%M}")
        if not rows:
            await c.message.answer(tr("Предстоящих записей нет.", "No upcoming bookings."), reply_markup=days_kb())
        else:
            out, day = [f"<b>{tr('Все предстоящие записи', 'All upcoming bookings')}: {len(rows)}</b>"], None
            for r in rows:
                d = r["start"][:10]
                if d != day:
                    dt = datetime.strptime(d, "%Y-%m-%d")
                    out.append(f"\n<b>{wd(dt)} {dt:%d.%m}</b>"); day = d
                out.append(booking_line(r))
            await send_long(c.message, "\n".join(out))
            await c.message.answer(tr("Посмотреть конкретный день:", "View a specific day:"), reply_markup=days_kb())
    elif a.startswith("day:"):
        d = a[4:]
        rows = db.bookings_on(d)
        dt = datetime.strptime(d, "%Y-%m-%d")
        await send_long(c.message, f"<b>{tr('Записи на', 'Bookings for')} {wd(dt)} {dt:%d.%m}:</b>\n" + ("\n".join(booking_line(r) for r in rows) or tr("нет", "none")))
    elif a == "orders":
        await c.message.answer(f"<b>{tr('Заказы', 'Orders')}</b>", reply_markup=orders_menu())
    elif a == "o_active":
        rows = db.orders_by("active")
        if not rows:
            await c.message.answer(tr("Активных заказов нет 👌", "No active orders 👌"))
        for r in rows:                                     # каждый отдельным сообщением — со своими кнопками
            await c.message.answer(order_card(r), reply_markup=order_kb(r))
    elif a == "o_done":
        rows = db.orders_by("done", 10)
        await send_long(c.message, f"<b>{tr('Выполненные и отменённые', 'Done and cancelled')}:</b>\n\n" + ("\n\n".join(order_card(r) for r in rows) or tr("нет", "none")))
    elif a == "o_recent":
        rows = db.orders_by("recent", 10)
        await send_long(c.message, f"<b>{tr('Последние заказы', 'Latest orders')}:</b>\n\n" + ("\n\n".join(order_card(r) for r in rows) or tr("нет", "none")))
    elif a == "clear":
        await c.message.answer(tr("Что удалить?", "What should I delete?"), reply_markup=kb([
            [(tr("🗑 Выполненные и отменённые заказы", "🗑 Done and cancelled orders"), "cl:finished")],
            [(tr("💣 Всё: заказы, записи, заявки", "💣 Everything: orders, bookings, leads"), "cl:all")],
            [(tr("✖️ Ничего", "✖️ Nothing"), "cl:no")]]))
    elif a == "leads":
        rows = db.recent("leads")
        await c.message.answer(tr("Последние заявки:", "Latest leads:") + "\n" + ("\n".join(f"#{r['id']} {r['name']}, {r['phone']} — {r['estimate']}" for r in rows) or tr("нет", "none")))
    elif a == "export":
        stamp = f"{datetime.now():%Y%m%d}"
        for t in ("bookings", "orders", "leads", "users"):
            await c.message.answer_document(BufferedInputFile(db.export_csv(t), filename=f"{t}_{stamp}.csv"))
    elif a == "bcast":
        await state.set_state(Broadcast.text)
        await c.message.answer(tr("Пришлите текст рассылки (или /cancel):", "Send the broadcast text (or /cancel):"))
    await c.answer()


@router.callback_query(F.data.startswith("os:"))
async def order_status(c: CallbackQuery):
    if not is_admin(c.from_user.id):
        return await c.answer(tr("Только для владельца", "Owner only"), show_alert=True)
    _, oid, st = c.data.split(":")
    oid = int(oid)
    if not db.set_order_status(oid, st):
        return await c.answer(tr("Заказ не найден (возможно, история очищена)", "Order not found (history may have been cleared)"), show_alert=True)
    r = db.get_order(oid)
    await c.message.edit_text(order_card(r), reply_markup=order_kb(r))
    if r["user_id"]:
        with use_lang(db.get_lang(r["user_id"])):          # клиенту — на его языке
            msg = client_msg(st, oid)
        if msg:
            try:                                           # клиенту пишет клиентский бот
                await (common.CLIENT_BOT or c.bot).send_message(r["user_id"], msg)
            except Exception:
                pass
    await c.answer(status_label(st))


@router.callback_query(F.data.startswith("cl:"))
async def clear_cb(c: CallbackQuery):
    if not is_admin(c.from_user.id):
        return await c.answer(tr("Только для владельца", "Owner only"), show_alert=True)
    what = c.data[3:]
    if what == "no":
        await c.message.edit_text(tr("Ничего не удалено.", "Nothing deleted."))
    elif what in ("finished", "all") and not c.data.endswith("!"):
        txt = (tr("Удалить все выполненные и отменённые заказы?", "Delete all done and cancelled orders?") if what == "finished" else
               tr("Стереть ВСЕ заказы, записи и заявки? Нумерация начнётся с #1. Список пользователей для рассылки останется.",
                  "Erase ALL orders, bookings and leads? Numbering restarts from #1. The broadcast user list stays."))
        await c.message.edit_text(txt + "\n" + tr("Отменить будет нельзя. Сначала можно сделать выгрузку в Excel.",
                                                  "This can't be undone. You can export to Excel first."),
                                  reply_markup=kb([[(tr("Да, удалить", "Yes, delete"), f"cl:{what}!"), (tr("✖️ Нет", "✖️ No"), "cl:no")]]))
    else:
        n = db.clear_history(what.rstrip("!"))
        await c.message.edit_text(f"🧹 {tr('Готово, удалено строк', 'Done, rows deleted')}: {n}.")
    await c.answer()


@router.message(Broadcast.text)
async def bcast_text(m: Message, state: FSMContext):
    if not is_admin(m.from_user.id):
        return
    if (m.text or "").startswith("/"):
        await state.clear()
        return await m.answer(tr("Рассылка отменена.", "Broadcast cancelled."))
    await state.update_data(text=m.html_text)
    await state.set_state(Broadcast.confirm)
    n = len(db.all_users())
    await m.answer(tr(f"Отправить это сообщение {n} пользователям?", f"Send this message to {n} users?") + f"\n\n{m.html_text}",
                   reply_markup=kb([[(tr("✅ Отправить", "✅ Send"), "bc:yes"), (tr("✖️ Отмена", "✖️ Cancel"), "bc:no")]]))


@router.callback_query(F.data.startswith("bc:"), Broadcast.confirm)
async def bcast_go(c: CallbackQuery, state: FSMContext):
    if not is_admin(c.from_user.id):
        return await c.answer()
    st = await state.get_data()
    await state.clear()
    if c.data == "bc:no":
        await c.message.edit_text(tr("Рассылка отменена.", "Broadcast cancelled."))
        return await c.answer()
    await c.message.edit_text(tr("Рассылаю…", "Sending…"))
    ok = fail = 0
    sender = common.CLIENT_BOT or c.bot          # клиентам пишет клиентский бот, даже если кнопку нажали в служебном
    for uid in db.all_users():
        try:
            await sender.send_message(uid, st["text"])
            ok += 1
        except Exception:
            fail += 1
        await asyncio.sleep(0.05)              # ~20 сообщений в секунду — в лимитах Telegram
    await c.message.answer(tr(f"Готово: доставлено {ok}, не доставлено {fail} (заблокировали бота).", f"Done: delivered {ok}, failed {fail} (blocked the bot)."))
    await c.answer()
