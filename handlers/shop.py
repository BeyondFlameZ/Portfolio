"""Магазин: категории → товар (± в корзину) → корзина → оформление (имя, телефон, доставка/самовывоз, адрес) → оплата."""
import json
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, LabeledPrice, Message, PreCheckoutQuery, ReplyKeyboardRemove

import config
import data
import db
import logic
from handlers.common import fmt_phone, MENU_BTN, kb, notify_owner, parse_phone, phone_kb

router = Router()


class Checkout(StatesGroup):
    name = State()
    phone = State()
    address = State()


def cats_kb(user_id: int):
    n = sum(db.cart(user_id).values())
    rows = [[(c["name"], f"sc:{c['id']}")] for c in data.CATEGORIES]
    rows.append([(f"🧺 Корзина ({n})", "sh:cart"), MENU_BTN])
    return kb(rows)


@router.callback_query(F.data == "m:shop")
async def shop_start(c: CallbackQuery, state: FSMContext):
    await state.clear()
    await c.message.edit_text(f"<b>{data.SHOP['name']}</b>\nДоставка {logic.money(data.SHOP['delivery_price'])}, "
                              f"бесплатно от {logic.money(data.SHOP['free_delivery_from'])}.\n\nВыберите раздел:",
                              reply_markup=cats_kb(c.from_user.id))
    await c.answer()


@router.callback_query(F.data.startswith("sc:"))
async def show_cat(c: CallbackQuery):
    cid = c.data[3:]
    items = [p for p in data.PRODUCTS if p["cat"] == cid]
    rows = [[(f"{p['name']} — {logic.money(p['price'])}", f"si:{p['id']}")] for p in items]
    rows.append([("⬅️ Разделы", "m:shop"), ("🧺 Корзина", "sh:cart")])
    name = next((x["name"] for x in data.CATEGORIES if x["id"] == cid), "")
    await c.message.edit_text(name, reply_markup=kb(rows))
    await c.answer()


def item_view(user_id: int, pid: str):
    p = logic.product(pid)
    q = db.cart(user_id).get(pid, 0)
    text = f"<b>{p['name']}</b>\n{p['desc']}\n\nЦена: {logic.money(p['price'])}" + (f"\nВ корзине: {q} шт." if q else "")
    rows = [[("➖", f"sq:{pid}:-1"), (f"{q} шт.", "noop"), ("➕", f"sq:{pid}:1")],
            [("⬅️ Назад", f"sc:{p['cat']}"), ("🧺 Корзина", "sh:cart")]]
    return text, kb(rows)


@router.callback_query(F.data.startswith("si:"))
async def show_item(c: CallbackQuery):
    pid = c.data[3:]
    if not logic.product(pid):
        return await c.answer("Товар не найден", show_alert=True)
    text, markup = item_view(c.from_user.id, pid)
    await c.message.edit_text(text, reply_markup=markup)
    await c.answer()


@router.callback_query(F.data.startswith("sq:"))
async def change_qty(c: CallbackQuery):
    _, pid, d = c.data.split(":")
    if not logic.product(pid):
        return await c.answer()
    q = db.cart_add(c.from_user.id, pid, int(d))
    text, markup = item_view(c.from_user.id, pid)
    await c.message.edit_text(text, reply_markup=markup)
    await c.answer(f"В корзине: {q}")


@router.callback_query(F.data == "noop")
async def noop(c: CallbackQuery):
    await c.answer()


@router.callback_query(F.data == "sh:cart")
async def show_cart(c: CallbackQuery):
    cart = db.cart(c.from_user.id)
    rows = []
    if logic.cart_lines(cart):
        rows.append([("✅ Оформить заказ", "sh:checkout")])
        rows.append([("🗑 Очистить", "sh:clear")])
    rows.append([("⬅️ К покупкам", "m:shop"), MENU_BTN])
    await c.message.edit_text("🧺 <b>Корзина</b>\n\n" + logic.cart_text(cart), reply_markup=kb(rows))
    await c.answer()


@router.callback_query(F.data == "sh:clear")
async def clear_cart(c: CallbackQuery):
    db.cart_clear(c.from_user.id)
    await show_cart(c)


@router.callback_query(F.data == "sh:checkout")
async def checkout(c: CallbackQuery, state: FSMContext):
    if not logic.cart_lines(db.cart(c.from_user.id)):
        return await c.answer("Корзина пуста", show_alert=True)
    await state.set_state(Checkout.name)
    await c.message.edit_text("Оформление заказа.\n\nКак к вам обращаться?")
    await c.answer()


@router.message(Checkout.name)
async def co_name(m: Message, state: FSMContext):
    name = (m.text or "").strip()
    if not 1 < len(name) < 60:
        return await m.answer("Напишите имя, пожалуйста.")
    await state.update_data(name=name)
    await state.set_state(Checkout.phone)
    await m.answer("Телефон для связи:", reply_markup=phone_kb())


@router.message(Checkout.phone)
async def co_phone(m: Message, state: FSMContext):
    phone = m.contact.phone_number if m.contact else parse_phone(m.text)
    phone = fmt_phone(phone) if phone else None
    if not phone:
        return await m.answer("Не похоже на номер. Нажмите кнопку или напишите, например +7 999 123-45-67", reply_markup=phone_kb())
    await state.update_data(phone=phone)
    await m.answer("Принято.", reply_markup=ReplyKeyboardRemove())
    await m.answer("Как получить заказ?", reply_markup=kb([[("🚚 Доставка", "sd:1"), ("🏃 Самовывоз", "sd:0")]]))


@router.callback_query(F.data.startswith("sd:"), Checkout.phone)
async def co_delivery(c: CallbackQuery, state: FSMContext):
    if c.data == "sd:1":
        await state.update_data(delivery=True)
        await state.set_state(Checkout.address)
        await c.message.edit_text("Адрес доставки (улица, дом, квартира):")
    else:
        await state.update_data(delivery=False, address="самовывоз")
        await c.message.edit_text("Самовывоз.")
        await confirm(c.message, state, c.from_user.id)
    await c.answer()


@router.message(Checkout.address)
async def co_address(m: Message, state: FSMContext):
    addr = (m.text or "").strip()
    if len(addr) < 5:
        return await m.answer("Напишите адрес подробнее.")
    await state.update_data(address=addr)
    await confirm(m, state, m.from_user.id)


async def confirm(msg: Message, state: FSMContext, user_id: int):
    st = await state.get_data()
    cart = db.cart(user_id)
    text = (f"<b>Проверьте заказ</b>\n\n{logic.cart_text(cart, st.get('delivery', False))}\n\n"
            f"Имя: {st['name']}\nТелефон: {st['phone']}\nПолучение: {st['address']}")
    pay = "💳 Оплатить онлайн" if config.PAYMENT_TOKEN else "✅ Подтвердить (оплата при получении)"
    await msg.answer(text, reply_markup=kb([[(pay, "sh:confirm")], [("✏️ Изменить корзину", "sh:cart")]]))


def _status_kb(oid: int):
    return kb([[("🚚 В работу", f"os:{oid}:work"), ("✅ Выполнен", f"os:{oid}:done")],
               [("✖️ Отменить", f"os:{oid}:cancel")]])


@router.callback_query(F.data == "sh:confirm")
async def place_order(c: CallbackQuery, state: FSMContext):
    st = await state.get_data()
    cart = db.cart(c.from_user.id)
    if not st.get("phone") or not logic.cart_lines(cart):
        await state.clear()
        return await c.answer("Сессия оформления устарела, начните заново", show_alert=True)
    goods, fee = logic.cart_total(cart, st.get("delivery", False))
    oid = db.add_order(c.from_user.id, cart, goods, fee, st["name"], st["phone"], st["address"])
    db.cart_clear(c.from_user.id)
    await state.clear()
    lines = "\n".join(f"• {p['name']} × {q}" for p, q, _ in logic.cart_lines(cart))
    owner = (f"🛒 <b>Новый заказ #{oid}</b>\n{lines}\nСумма: {logic.money(goods + fee)}"
             f"{' (доставка ' + logic.money(fee) + ')' if fee else ''}\n{st['name']}, {st['phone']}\n"
             f"{'🏃 Самовывоз' if st['address'] == 'самовывоз' else '🚚 Доставка: ' + st['address']}")
    if config.PAYMENT_TOKEN:
        await c.message.edit_text(f"Заказ #{oid} создан. Оплатите по кнопке ниже:")
        await c.bot.send_invoice(c.message.chat.id, title=f"Заказ #{oid}", description=data.SHOP["name"],
                                 payload=f"order:{oid}", provider_token=config.PAYMENT_TOKEN, currency="RUB",
                                 prices=[LabeledPrice(label="Товары", amount=goods * 100)] +
                                        ([LabeledPrice(label="Доставка", amount=fee * 100)] if fee else []),
                                 provider_data=json.dumps(logic.yookassa_receipt(cart, fee, st["phone"], config.RECEIPT_VAT_CODE),
                                                          ensure_ascii=False) if config.RECEIPTS else None)
        await notify_owner(c.bot, owner + "\n⏳ Ждёт оплаты", c.message.chat.id, markup=_status_kb(oid))
    else:
        await c.message.edit_text(f"✅ Заказ #{oid} принят! Скоро свяжемся для подтверждения.\nСумма: {logic.money(goods + fee)}",
                                  reply_markup=kb([[MENU_BTN]]))
        await notify_owner(c.bot, owner + "\n💵 Оплата при получении", c.message.chat.id, markup=_status_kb(oid))
    await c.answer()


@router.pre_checkout_query()
async def pre_checkout(q: PreCheckoutQuery):
    ok = q.invoice_payload.startswith("order:") and db.get_order(int(q.invoice_payload[6:])) is not None
    await q.answer(ok=ok, error_message=None if ok else "Заказ не найден, оформите заново")


@router.message(F.successful_payment)
async def paid(m: Message):
    oid = int(m.successful_payment.invoice_payload[6:])
    db.mark_paid(oid)
    await m.answer(f"✅ Оплата получена, заказ #{oid} передан в работу!", reply_markup=kb([[MENU_BTN]]))
    o = db.get_order(oid)
    extra = f"\n{o['name']}, {o['phone']}\n{'🏃 Самовывоз' if o['address'] == 'самовывоз' else '🚚 ' + o['address']}" if o else ""
    await notify_owner(m.bot, f"💳 <b>Заказ #{oid} оплачен</b> — {m.successful_payment.total_amount // 100} ₽{extra}", m.chat.id)
