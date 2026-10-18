"""Чистая логика без Telegram: слоты записи, корзина, расчёт квиза. Покрыта тестами."""
from __future__ import annotations

from datetime import datetime, timedelta

from i18n import D, en, tr

WD_RU = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
WD_EN = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def wd(d: datetime) -> str:
    return (WD_EN if en() else WD_RU)[d.weekday()]


def service(sid: str) -> dict | None:
    return next((s for s in D().SERVICES if s["id"] == sid), None)


def master(mid: str) -> dict | None:
    return next((m for m in D().MASTERS if m["id"] == mid), None)


def masters_for(sid: str) -> list[dict]:
    return [m for m in D().MASTERS if sid in m["services"]]


def free_slots(day: datetime, mid: str, dur_min: int, busy: list[tuple[datetime, datetime]], now: datetime) -> list[datetime]:
    """Свободные начала услуги длиной dur_min у мастера в день day. busy — занятые интервалы [начало, конец)."""
    m = master(mid)
    if m is None or day.weekday() in m["days_off"]:
        return []
    s = D().SALON
    start = day.replace(hour=s["open_hour"], minute=0, second=0, microsecond=0)
    close = day.replace(hour=s["close_hour"], minute=0, second=0, microsecond=0)
    earliest = now + timedelta(minutes=s["min_lead_min"])
    out = []
    t = start
    while t + timedelta(minutes=dur_min) <= close:
        end = t + timedelta(minutes=dur_min)
        if t >= earliest and all(end <= b0 or t >= b1 for b0, b1 in busy):
            out.append(t)
        t += timedelta(minutes=s["step_min"])
    return out


def booking_days(now: datetime) -> list[datetime]:
    base = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return [base + timedelta(days=k) for k in range(D().SALON["days_ahead"])]


def day_label(d: datetime, now: datetime) -> str:
    if d.date() == now.date():
        return f"{tr('Сегодня', 'Today')} {d:%d.%m}"
    if d.date() == (now + timedelta(days=1)).date():
        return f"{tr('Завтра', 'Tomorrow')} {d:%d.%m}"
    return f"{wd(d)} {d:%d.%m}"


# ---------------------------------------------------------------- магазин
def product(pid: str) -> dict | None:
    return next((p for p in D().PRODUCTS if p["id"] == pid), None)


def cart_lines(cart: dict[str, int]) -> list[tuple[dict, int, int]]:
    """-> [(товар, кол-во, сумма)] только существующие товары с qty > 0."""
    out = []
    for pid, q in cart.items():
        p = product(pid)
        if p and q > 0:
            out.append((p, q, p["price"] * q))
    return out


def cart_total(cart: dict[str, int], delivery: bool = False) -> tuple[int, int]:
    """-> (сумма товаров, стоимость доставки)."""
    goods = sum(s for _, _, s in cart_lines(cart))
    fee = 0
    if delivery and goods < D().SHOP["free_delivery_from"]:
        fee = D().SHOP["delivery_price"]
    return goods, fee


def cart_text(cart: dict[str, int], delivery: bool | None = None) -> str:
    lines = cart_lines(cart)
    if not lines:
        return tr("Корзина пуста.", "Your cart is empty.")
    rows = [f"• {p['name']} × {q} = {money(s)}" for p, q, s in lines]
    goods, fee = cart_total(cart, bool(delivery))
    rows.append(f"\n{tr('Товары', 'Items')}: {money(goods)}")
    if delivery:
        rows.append(f"{tr('Доставка', 'Delivery')}: {money(fee)}" if fee else tr("Доставка: бесплатно", "Delivery: free"))
        rows.append(f"{tr('Итого', 'Total')}: {money(goods + fee)}")
    elif delivery is None and goods < D().SHOP["free_delivery_from"]:
        rows.append(tr("Бесплатная доставка от ", "Free delivery from ") + money(D().SHOP['free_delivery_from']))
    return "\n".join(rows)


# ---------------------------------------------------------------- квиз
def quiz_estimate(answers: dict[str, str]) -> tuple[int, int] | None:
    """Ориентир цены (от, до) по ответам: коэфф. объекта × площадь × цена за м² ±20%."""
    q = {x["id"]: {o[0]: o[2] for o in x["options"]} for x in D().QUIZ["questions"]}
    try:
        base = q["obj"][answers["obj"]] * q["area"][answers["area"]] * q["kind"][answers["kind"]]
    except KeyError:
        return None
    return int(round(base * 0.8, -3)), int(round(base * 1.2, -3))


def quiz_option_label(qid: str, oid: str) -> str:
    for x in D().QUIZ["questions"]:
        if x["id"] == qid:
            for o in x["options"]:
                if o[0] == oid:
                    return o[1]
    return oid


def money(x: int) -> str:
    if en():
        return f"${x:,}"
    return f"{x:,}".replace(",", " ") + " ₽"


def receipt_phone(phone: str) -> str:
    """Телефон для чека ЮKassa: только цифры, российский номер с 7 в начале."""
    d = "".join(ch for ch in phone or "" if ch.isdigit())
    if len(d) == 11 and d[0] == "8":
        d = "7" + d[1:]
    elif len(d) == 10:
        d = "7" + d
    return d


def yookassa_receipt(cart: dict[str, int], delivery_fee: int, phone: str, vat_code: int = 1) -> dict:
    """
    provider_data для sendInvoice: чек 54-ФЗ в формате ЮKassa (объект receipt из create_payment).
    Сумма позиций обязана совпадать с суммой счёта, поэтому доставка — отдельной позицией-услугой.
    """
    def item(name, qty, price, subject):
        return {"description": name[:128], "quantity": f"{qty:.2f}",
                "amount": {"value": f"{price:.2f}", "currency": "RUB"},   # цена за единицу
                "vat_code": vat_code, "payment_mode": "full_payment", "payment_subject": subject}
    items = [item(p["name"], q, p["price"], "commodity") for p, q, _ in cart_lines(cart)]
    if delivery_fee:
        items.append(item("Доставка", 1, delivery_fee, "service"))
    return {"receipt": {"customer": {"phone": receipt_phone(phone)}, "items": items}}
