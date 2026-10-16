"""Чистая логика без Telegram: слоты записи, корзина, расчёт квиза. Покрыта тестами."""
from __future__ import annotations

from datetime import datetime, timedelta

import data

WD = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]


def service(sid: str) -> dict | None:
    return next((s for s in data.SERVICES if s["id"] == sid), None)


def master(mid: str) -> dict | None:
    return next((m for m in data.MASTERS if m["id"] == mid), None)


def masters_for(sid: str) -> list[dict]:
    return [m for m in data.MASTERS if sid in m["services"]]


def free_slots(day: datetime, mid: str, dur_min: int, busy: list[tuple[datetime, datetime]], now: datetime) -> list[datetime]:
    """Свободные начала услуги длиной dur_min у мастера в день day. busy — занятые интервалы [начало, конец)."""
    m = master(mid)
    if m is None or day.weekday() in m["days_off"]:
        return []
    s = data.SALON
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
    return [base + timedelta(days=k) for k in range(data.SALON["days_ahead"])]


def day_label(d: datetime, now: datetime) -> str:
    if d.date() == now.date():
        return f"Сегодня {d:%d.%m}"
    if d.date() == (now + timedelta(days=1)).date():
        return f"Завтра {d:%d.%m}"
    return f"{WD[d.weekday()]} {d:%d.%m}"


# ---------------------------------------------------------------- магазин
def product(pid: str) -> dict | None:
    return next((p for p in data.PRODUCTS if p["id"] == pid), None)


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
    if delivery and goods < data.SHOP["free_delivery_from"]:
        fee = data.SHOP["delivery_price"]
    return goods, fee


def cart_text(cart: dict[str, int], delivery: bool | None = None) -> str:
    lines = cart_lines(cart)
    if not lines:
        return "Корзина пуста."
    rows = [f"• {p['name']} × {q} = {s} ₽" for p, q, s in lines]
    goods, fee = cart_total(cart, bool(delivery))
    rows.append(f"\nТовары: {goods} ₽")
    if delivery:
        rows.append(f"Доставка: {fee} ₽" if fee else "Доставка: бесплатно")
        rows.append(f"Итого: {goods + fee} ₽")
    elif delivery is None and goods < data.SHOP["free_delivery_from"]:
        rows.append(f"Бесплатная доставка от {data.SHOP['free_delivery_from']} ₽")
    return "\n".join(rows)


# ---------------------------------------------------------------- квиз
def quiz_estimate(answers: dict[str, str]) -> tuple[int, int] | None:
    """Ориентир цены (от, до) по ответам: коэфф. объекта × площадь × цена за м² ±20%."""
    q = {x["id"]: {o[0]: o[2] for o in x["options"]} for x in data.QUIZ["questions"]}
    try:
        base = q["obj"][answers["obj"]] * q["area"][answers["area"]] * q["kind"][answers["kind"]]
    except KeyError:
        return None
    return int(round(base * 0.8, -3)), int(round(base * 1.2, -3))


def quiz_option_label(qid: str, oid: str) -> str:
    for x in data.QUIZ["questions"]:
        if x["id"] == qid:
            for o in x["options"]:
                if o[0] == oid:
                    return o[1]
    return oid


def money(x: int) -> str:
    return f"{x:,}".replace(",", " ") + " ₽"
