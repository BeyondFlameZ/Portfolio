"""Магазин: категории → товар (± в корзину) → корзина → оформление (имя, телефон, доставка/самовывоз, адрес) → оплата."""
import json
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, LabeledPrice, Message, PreCheckoutQuery, ReplyKeyboardRemove

import config
import db
import logic
from i18n import D, en, tr
from handlers.common import bad_phone_text, fmt_phone, menu_btn, kb, notify_owner, parse_phone, phone_kb

router = Router()


class Checkout(StatesGroup):
    name = State()
    phone = State()
    address = State()


def cats_kb(user_id: int):
    n = sum(db.cart(user_id).values())
    rows = [[(c["name"], f"sc:{c['id']}")] for c in D().CATEGORIES]
    rows.append([(f"🧺 {tr('Корзина', 'Cart')} ({n})", "sh:cart"), menu_btn()])
    return kb(rows)


@router.callback_query(F.data == "m:shop")
async def shop_start(c: CallbackQuery, state: FSMContext):
    await state.clear()
    await c.message.edit_text(f"<b>{D().SHOP['name']}</b>\n{tr('Доставка', 'Delivery')} {logic.money(D().SHOP['delivery_price'])}, "
                              f"{tr('бесплатно от', 'free from')} {logic.money(D().SHOP['free_delivery_from'])}.\n\n"
                              + tr("Выберите раздел:", "Choose a category:"),
                              reply_markup=cats_kb(c.from_user.id))
    await c.answer()


@router.callback_query(F.data.startswith("sc:"))
async def show_cat(c: CallbackQuery):
    cid = c.data[3:]
    items = [p for p in D().PRODUCTS if p["cat"] == cid]
    rows = [[(f"{p['name']} — {logic.money(p['price'])}", f"si:{p['id']}")] for p in items]
    rows.append([(tr("⬅️ Разделы", "⬅️ Categories"), "m:shop"), (tr("🧺 Корзина", "🧺 Cart"), "sh:cart")])
    name = next((x["name"] for x in D().CATEGORIES if x["id"] == cid), "")
    await c.message.edit_text(name, reply_markup=kb(rows))
    await c.answer()


def item_view(user_id: int, pid: str):
    p = logic.product(pid)
    q = db.cart(user_id).get(pid, 0)
    pcs = tr("шт.", "pcs")
    text = (f"<b>{p['name']}</b>\n{p['desc']}\n\n{tr('Цена', 'Price')}: {logic.money(p['price'])}"
            + (f"\n{tr('В корзине', 'In cart')}: {q} {pcs}" if q else ""))
    rows = [[("➖", f"sq:{pid}:-1"), (f"{q} {pcs}", "noop"), ("➕", f"sq:{pid}:1")],
            [(tr("⬅️ Назад", "⬅️ Back"), f"sc:{p['cat']}"), (tr("🧺 Корзина", "🧺 Cart"), "sh:cart")]]
    return text, kb(rows)


@router.callback_query(F.data.startswith("si:"))
async def show_item(c: CallbackQuery):
    pid = c.data[3:]
    if not logic.product(pid):
        return await c.answer(tr("Товар не найден", "Item not found"), show_alert=True)
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
    await c.answer(f"{tr('В корзине', 'In cart')}: {q}")


@router.callback_query(F.data == "noop")
async def noop(c: CallbackQuery):
    await c.answer()


@router.callback_query(F.data == "sh:cart")
async def show_cart(c: CallbackQuery):
    cart = db.cart(c.from_user.id)
    rows = []
    if logic.cart_lines(cart):
        rows.append([(tr("✅ Оформить заказ", "✅ Checkout"), "sh:checkout")])
        rows.append([(tr("🗑 Очистить", "🗑 Clear"), "sh:clear")])
    rows.append([(tr("⬅️ К покупкам", "⬅️ Keep shopping"), "m:shop"), menu_btn()])
    await c.message.edit_text(f"🧺 <b>{tr('Корзина', 'Cart')}</b>\n\n" + logic.cart_text(cart), reply_markup=kb(rows))
    await c.answer()


@router.callback_query(F.data == "sh:clear")
async def clear_cart(c: CallbackQuery):
    db.cart_clear(c.from_user.id)
    await show_cart(c)


@router.callback_query(F.data == "sh:checkout")
async def checkout(c: CallbackQuery, state: FSMContext):
    if not logic.cart_lines(db.cart(c.from_user.id)):
        return await c.answer(tr("Корзина пуста", "Your cart is empty"), show_alert=True)
    await state.set_state(Checkout.name)
    await c.message.edit_text(tr("Оформление заказа.\n\nКак к вам обращаться?", "Checkout.\n\nWhat is your name?"))
    await c.answer()


@router.message(Checkout.name)
async def co_name(m: Message, state: FSMContext):
    name = (m.text or "").strip()
    if not 1 < len(name) < 60:
        return await m.answer(tr("Напишите имя, пожалуйста.", "Please type your name."))
    await state.update_data(name=name)
    await state.set_state(Checkout.phone)
    await m.answer(tr("Телефон для связи:", "Phone number:"), reply_markup=phone_kb())


@router.message(Checkout.phone)
async def co_phone(m: Message, state: FSMContext):
    phone = m.contact.phone_number if m.contact else parse_phone(m.text)
    phone = fmt_phone(phone) if phone else None
    if not phone:
        return await m.answer(bad_phone_text(), reply_markup=phone_kb())
    await state.update_data(phone=phone)
    await m.answer(tr("Принято.", "Got it."), reply_markup=ReplyKeyboardRemove())
    await m.answer(tr("Как получить заказ?", "Delivery or pickup?"),
                   reply_markup=kb([[(tr("🚚 Доставка", "🚚 Delivery"), "sd:1"), (tr("🏃 Самовывоз", "🏃 Pickup"), "sd:0")]]))


@router.callback_query(F.data.startswith("sd:"), Checkout.phone)
async def co_delivery(c: CallbackQuery, state: FSMContext):
    if c.data == "sd:1":
        await state.update_data(delivery=True)
        await state.set_state(Checkout.address)
        await c.message.edit_text(tr("Адрес доставки (улица, дом, квартира):", "Delivery address (street, building, apt):"))
    else:
        await state.update_data(delivery=False, address=PICKUP)
        await c.message.edit_text(tr("Самовывоз.", "Pickup."))
        await confirm(c.message, state, c.from_user.id)
    await c.answer()


@router.message(Checkout.address)
async def co_address(m: Message, state: FSMContext):
    addr = (m.text or "").strip()
    if len(addr) < 5:
        return await m.answer(tr("Напишите адрес подробнее.", "Please add more address details."))
    await state.update_data(address=addr)
    await confirm(m, state, m.from_user.id)


async def confirm(msg: Message, state: FSMContext, user_id: int):
    st = await state.get_data()
    cart = db.cart(user_id)
    text = (f"<b>{tr('Проверьте заказ', 'Check your order')}</b>\n\n{logic.cart_text(cart, st.get('delivery', False))}\n\n"
            f"{tr('Имя', 'Name')}: {st['name']}\n{tr('Телефон', 'Phone')}: {st['phone']}\n{tr('Получение', 'Receive')}: {where_text(st['address'])}")
    pay = tr("💳 Оплатить онлайн", "💳 Pay online") if config.PAYMENT_TOKEN else tr("✅ Подтвердить (оплата при получении)", "✅ Confirm (pay on delivery)")
    await msg.answer(text, reply_markup=kb([[(pay, "sh:confirm")], [(tr("✏️ Изменить корзину", "✏️ Edit cart"), "sh:cart")]]))


PICKUP = "самовывоз"            # служебная метка в базе, на экране переводится


def where_text(addr: str) -> str:
    return tr("самовывоз", "pickup") if addr == PICKUP else addr


def where_line(addr: str) -> str:
    return tr("🏃 Самовывоз", "🏃 Pickup") if addr == PICKUP else f"{tr('🚚 Доставка', '🚚 Delivery')}: {addr}"


def _status_kb(oid: int):
    return kb([[(tr("🚚 В работу", "🚚 In progress"), f"os:{oid}:work"), (tr("✅ Выполнен", "✅ Done"), f"os:{oid}:done")],
               [(tr("✖️ Отменить", "✖️ Cancel"), f"os:{oid}:cancel")]])


@router.callback_query(F.data == "sh:confirm")
async def place_order(c: CallbackQuery, state: FSMContext):
    st = await state.get_data()
    cart = db.cart(c.from_user.id)
    if not st.get("phone") or not logic.cart_lines(cart):
        await state.clear()
        return await c.answer(tr("Сессия оформления устарела, начните заново", "Checkout expired, please start again"), show_alert=True)
    goods, fee = logic.cart_total(cart, st.get("delivery", False))
    oid = db.add_order(c.from_user.id, cart, goods, fee, st["name"], st["phone"], st["address"])
    db.cart_clear(c.from_user.id)
    await state.clear()
    lines = "\n".join(f"• {p['name']} × {q}" for p, q, _ in logic.cart_lines(cart))
    owner = (f"🛒 <b>{tr('Новый заказ', 'New order')} #{oid}</b>\n{lines}\n{tr('Сумма', 'Total')}: {logic.money(goods + fee)}"
             f"{' (' + tr('доставка', 'delivery') + ' ' + logic.money(fee) + ')' if fee else ''}\n{st['name']}, {st['phone']}\n"
             f"{where_line(st['address'])}")
    if config.PAYMENT_TOKEN:
        await c.message.edit_text(tr(f"Заказ #{oid} создан. Оплатите по кнопке ниже:", f"Order #{oid} created. Pay with the button below:"))
        await c.bot.send_invoice(c.message.chat.id, title=f"{tr('Заказ', 'Order')} #{oid}", description=D().SHOP["name"],
                                 payload=f"order:{oid}", provider_token=config.PAYMENT_TOKEN, currency="USD" if en() else "RUB",
                                 prices=[LabeledPrice(label=tr("Товары", "Items"), amount=goods * 100)] +
                                        ([LabeledPrice(label=tr("Доставка", "Delivery"), amount=fee * 100)] if fee else []),
                                 provider_data=json.dumps(logic.yookassa_receipt(cart, fee, st["phone"], config.RECEIPT_VAT_CODE),
                                                          ensure_ascii=False) if config.RECEIPTS and not en() else None)
        await notify_owner(c.bot, owner + "\n" + tr("⏳ Ждёт оплаты", "⏳ Awaiting payment"), c.message.chat.id, markup=_status_kb(oid))
    else:
        await c.message.edit_text(tr(f"✅ Заказ #{oid} принят! Скоро свяжемся для подтверждения.", f"✅ Order #{oid} placed! We'll contact you to confirm.")
                                  + f"\n{tr('Сумма', 'Total')}: {logic.money(goods + fee)}", reply_markup=kb([[menu_btn()]]))
        await notify_owner(c.bot, owner + "\n" + tr("💵 Оплата при получении", "💵 Pay on delivery"), c.message.chat.id, markup=_status_kb(oid))
    await c.answer()


@router.pre_checkout_query()
async def pre_checkout(q: PreCheckoutQuery):
    ok = q.invoice_payload.startswith("order:") and db.get_order(int(q.invoice_payload[6:])) is not None
    await q.answer(ok=ok, error_message=None if ok else tr("Заказ не найден, оформите заново", "Order not found, please order again"))


@router.message(F.successful_payment)
async def paid(m: Message):
    oid = int(m.successful_payment.invoice_payload[6:])
    db.mark_paid(oid)
    await m.answer(tr(f"✅ Оплата получена, заказ #{oid} передан в работу!", f"✅ Payment received, order #{oid} is in progress!"),
                   reply_markup=kb([[menu_btn()]]))
    o = db.get_order(oid)
    extra = f"\n{o['name']}, {o['phone']}\n{where_line(o['address'])}" if o else ""
    await notify_owner(m.bot, f"💳 <b>{tr('Заказ', 'Order')} #{oid} {tr('оплачен', 'paid')}</b> — "
                              f"{logic.money(m.successful_payment.total_amount // 100)}{extra}", m.chat.id)
