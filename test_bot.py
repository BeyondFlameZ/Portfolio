"""
Тесты: логика слотов/корзины/квиза и сквозные сценарии через подменённую сессию Telegram
(бот «думает», что говорит с Telegram; мы записываем все исходящие запросы).
Запуск: python test_bot.py
"""
import asyncio
import os
import tempfile
import traceback
from datetime import datetime, timedelta

import config
config.ADMIN_IDS = {999}
config.DEMO_MODE = True
import db
db.reset_for_tests(os.path.join(tempfile.mkdtemp(), "t.db"))

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.base import BaseSession
from aiogram.enums import ParseMode
from aiogram.methods import AnswerCallbackQuery, AnswerPreCheckoutQuery, EditMessageText, SendDocument, SendInvoice, SendMessage
from aiogram.types import Update

import bot as botmod
import data
import logic
from handlers import common

USER = {"id": 111, "is_bot": False, "first_name": "Тест", "username": "tester"}
ADMIN = {"id": 999, "is_bot": False, "first_name": "Владелец"}


class FakeSession(BaseSession):
    def __init__(self):
        super().__init__()
        self.sent = []
        self.mid = 1000

    async def close(self): pass
    async def stream_content(self, *a, **k):
        yield b""

    async def make_request(self, bot, method, timeout=None):
        self.sent.append(method)
        if isinstance(method, (SendMessage, SendDocument, SendInvoice)):
            self.mid += 1
            return method.__returning__.model_validate({"message_id": self.mid, "date": 0, "chat": {"id": method.chat_id, "type": "private"},
                                                         "text": getattr(method, "text", "") or ""}, context={"bot": bot})
        if isinstance(method, EditMessageText):
            return True
        return True


class Harness:
    def __init__(self):
        self.session = FakeSession()
        self.bot = Bot("123:ABC", session=self.session, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
        self.dp = botmod.build_dispatcher()
        self.uid = 0

    def _upd(self, **kw):
        self.uid += 1
        return Update.model_validate({"update_id": self.uid, **kw}, context={"bot": self.bot})

    def msg(self, text=None, user=USER, contact=None, payment=None):
        m = {"message_id": self.uid + 1, "date": 0, "chat": {"id": user["id"], "type": "private"}, "from": user}
        if text is not None: m["text"] = text
        if text and text.startswith("/"):
            m["entities"] = [{"type": "bot_command", "offset": 0, "length": len(text.split()[0])}]
        if contact: m["contact"] = {"phone_number": contact, "first_name": user["first_name"], "user_id": user["id"]}
        if payment: m["successful_payment"] = payment
        return run(self.dp.feed_update(self.bot, self._upd(message=m)))

    def cb(self, data_, user=USER):
        q = {"id": str(self.uid), "from": user, "chat_instance": "x", "data": data_,
             "message": {"message_id": 5, "date": 0, "chat": {"id": user["id"], "type": "private"}, "text": "x"}}
        return run(self.dp.feed_update(self.bot, self._upd(callback_query=q)))

    def precheckout(self, payload, user=USER):
        q = {"id": "pc1", "from": user, "currency": "RUB", "total_amount": 100, "invoice_payload": payload}
        return run(self.dp.feed_update(self.bot, self._upd(pre_checkout_query=q)))

    def texts(self, since=0, to=None):
        out = []
        for m in self.session.sent[since:]:
            if isinstance(m, (SendMessage, EditMessageText)) and (to is None or getattr(m, "chat_id", to) == to):
                out.append(m.text)
        return out

    def buttons(self, since=0):
        out = []
        for m in self.session.sent[since:]:
            rm = getattr(m, "reply_markup", None)
            if rm is not None and hasattr(rm, "inline_keyboard"):
                out = [b.callback_data for row in rm.inline_keyboard for b in row]
        return out

    def alerts(self, since=0):
        return [m.text for m in self.session.sent[since:] if isinstance(m, AnswerCallbackQuery) and m.text]


def run(c):
    return asyncio.get_event_loop().run_until_complete(c)


# ================================================================== логика
def test_slots_respect_hours_busy_and_days_off():
    now = datetime(2026, 10, 19, 8, 0)                          # понедельник 08:00
    day = datetime(2026, 10, 19)
    s = logic.free_slots(day, "ivan", 60, [], now)
    assert s[0] == datetime(2026, 10, 19, 10, 0) and s[-1] == datetime(2026, 10, 19, 20, 0), s
    busy = [(datetime(2026, 10, 19, 12, 0), datetime(2026, 10, 19, 13, 30))]
    s2 = logic.free_slots(day, "ivan", 60, busy, now)
    assert datetime(2026, 10, 19, 11, 30) not in s2 and datetime(2026, 10, 19, 12, 30) not in s2
    assert datetime(2026, 10, 19, 11, 0) in s2 and datetime(2026, 10, 19, 13, 30) in s2
    assert logic.free_slots(day, "artem", 60, [], now) == []     # выходной в понедельник
    late = logic.free_slots(day, "ivan", 60, [], datetime(2026, 10, 19, 15, 10))
    assert late[0] == datetime(2026, 10, 19, 16, 30)              # не раньше чем через час, по сетке 30 мин


def test_cart_totals_and_free_delivery():
    assert logic.cart_total({"cap": 2}, True) == (500, 200)
    assert logic.cart_total({"eth": 2}, True) == (1780, 0)
    assert logic.cart_total({"cap": 2}, False) == (500, 0)
    assert logic.cart_lines({"nope": 3, "esp": 0}) == []


def test_quiz_estimate():
    lo, hi = logic.quiz_estimate({"obj": "flat", "area": "m", "kind": "cap", "when": "now"})
    assert (lo, hi) == (672000, 1008000)
    assert logic.quiz_estimate({"obj": "flat"}) is None


def test_phone_parse():
    assert common.parse_phone("+7 999 123-45-67") and common.parse_phone("89991234567")
    assert not common.parse_phone("привет") and not common.parse_phone("123")


# ================================================================== сценарии
H = None


def h():
    global H
    if H is None:
        H = Harness()
    return H


def test_start_menu_and_order_info():
    x = h(); n = len(x.session.sent)
    x.msg("/start")
    assert any("демо-бот" in t for t in x.texts(n))
    assert set(x.buttons(n)) == {"m:book", "m:shop", "m:quiz", "m:order"}
    x.cb("m:order")
    assert any("Что могу сделать" in t for t in x.texts(n))


def test_booking_flow_end_to_end_and_owner_preview():
    x = h()
    x.cb("m:book"); x.cb("bs:cut")
    n = len(x.session.sent); x.cb("bm:cut:ivan")
    days = [b for b in x.buttons(n) if b.startswith("bd:")]
    assert days, x.texts(n)
    n = len(x.session.sent); x.cb(days[-1])
    times = [b for b in x.buttons(n) if b.startswith("bt:")]
    assert times
    n = len(x.session.sent); x.cb(times[0])
    assert any("номер телефона" in t for t in x.texts(n))
    n = len(x.session.sent); x.msg("не номер")
    assert any("Не похоже на номер" in t for t in x.texts(n))
    n = len(x.session.sent); x.msg(contact="+79991234567")
    t = x.texts(n)
    assert any("Вы записаны" in s for s in t), t
    assert any("Новая запись" in s for s in x.texts(n, to=999)), "владелец не получил уведомление"
    assert any("Так это сообщение получит владелец" in s for s in x.texts(n, to=111)), "нет демо-превью"
    # тот же слот второй раз — уже занят
    x.cb("m:book"); x.cb("bs:cut"); x.cb("bm:cut:ivan"); x.cb(days[-1])
    n = len(x.session.sent); x.cb(times[0])
    x.msg(contact="+79990000000")
    assert any("только что заняли" in s for s in x.texts(n))
    # мои записи и отмена
    n = len(x.session.sent); x.cb("bk:my")
    cancels = [b for b in x.buttons(n) if b.startswith("bx:")]
    assert len(cancels) == 1
    n = len(x.session.sent); x.cb(cancels[0])
    assert "Запись отменена" in x.alerts(n)
    assert any("Отмена записи" in s for s in x.texts(n, to=999))
    assert not db.user_bookings(111, common.now_local())


def test_shop_flow_cash():
    x = h()
    config.PAYMENT_TOKEN = ""
    x.cb("m:shop"); x.cb("sc:coffee"); x.cb("si:cap")
    x.cb("sq:cap:1"); x.cb("sq:cap:1"); x.cb("sq:cap:-1"); x.cb("si:chz"); x.cb("sq:chz:1")
    assert db.cart(111) == {"cap": 1, "chz": 1}
    n = len(x.session.sent); x.cb("sh:cart")
    assert any("Капучино × 1 = 250 ₽" in s and "Чизкейк × 1" in s for s in x.texts(n))
    x.cb("sh:checkout"); x.msg("Иван"); x.msg("+7 900 000-00-00")
    n = len(x.session.sent); x.cb("sd:1")
    assert any("Адрес" in s for s in x.texts(n))
    n = len(x.session.sent); x.msg("ул. Ленина, 5, кв 3")
    assert any("Проверьте заказ" in s and "Доставка: 200 ₽" in s and "Итого: 740 ₽" in s for s in x.texts(n)), x.texts(n)
    n = len(x.session.sent); x.cb("sh:confirm")
    assert any("Заказ #" in s and "принят" in s for s in x.texts(n))
    assert any("Новый заказ" in s and "740" in s and "Доставка: ул. Ленина, 5, кв 3" in s for s in x.texts(n, to=999))
    assert db.cart(111) == {}
    # в админке у заказа видны состав, адрес и способ оплаты
    n = len(x.session.sent); x.cb("a:orders", user=ADMIN)
    t = "\n".join(x.texts(n))
    assert "ул. Ленина, 5, кв 3" in t and "Капучино × 1" in t and "Чизкейк × 1" in t and "оплата при получении" in t, t


def test_shop_flow_online_payment():
    x = h()
    config.PAYMENT_TOKEN = "TEST:123"
    try:
        x.cb("m:shop"); x.cb("si:eth"); x.cb("sq:eth:1"); x.cb("sh:checkout")
        x.msg("Пётр"); x.msg(contact="+79001112233")
        x.cb("sd:0")
        n = len(x.session.sent); x.cb("sh:confirm")
        inv = [m for m in x.session.sent[n:] if isinstance(m, SendInvoice)]
        assert len(inv) == 1 and inv[0].prices[0].amount == 89000 and inv[0].currency == "RUB"
        oid = int(inv[0].payload[6:])
        n = len(x.session.sent); x.precheckout(inv[0].payload)
        pc = [m for m in x.session.sent[n:] if isinstance(m, AnswerPreCheckoutQuery)]
        assert pc and pc[0].ok
        x.msg(payment={"currency": "RUB", "total_amount": 89000, "invoice_payload": inv[0].payload,
                       "telegram_payment_charge_id": "t", "provider_payment_charge_id": "p"})
        assert db.get_order(oid)["paid"] == 1
        assert any("оплачен" in s and "Самовывоз" in s and "Пётр" in s for s in x.texts(0, to=999))
        n2 = len(x.session.sent); x.cb("a:orders", user=ADMIN)
        assert any(f"#{oid}" in s and "оплачен онлайн" in s for s in x.texts(n2))
        n = len(x.session.sent); x.precheckout("order:999999")
        assert not [m for m in x.session.sent[n:] if isinstance(m, AnswerPreCheckoutQuery)][0].ok
    finally:
        config.PAYMENT_TOKEN = ""


def test_phone_format_and_local_time():
    assert common.fmt_phone("79113376594") == "+7 911 337-65-94"
    assert common.fmt_phone("+7 (911) 337-65-94") == "+7 911 337-65-94"
    assert common.fmt_phone("89113376594") == "+7 911 337-65-94"
    assert common.fmt_phone("380501234567") == "+380501234567"
    assert db.now_s()[:16] == f"{common.now_local():%Y-%m-%d %H:%M}"


def test_receipt_for_yookassa():
    x = h()
    config.PAYMENT_TOKEN = "TEST:123"; config.RECEIPTS = True
    try:
        x.cb("m:shop"); x.cb("si:cap"); x.cb("sq:cap:1"); x.cb("sq:cap:1"); x.cb("sh:checkout")
        x.msg("Ольга"); x.msg("8 (900) 111-22-33"); x.cb("sd:1"); x.msg("пр. Мира, 10")
        n = len(x.session.sent); x.cb("sh:confirm")
        inv = [m for m in x.session.sent[n:] if isinstance(m, SendInvoice)][0]
        import json as _j
        r = _j.loads(inv.provider_data)["receipt"]
        assert r["customer"]["phone"] == "79001112233"
        total_items = sum(float(i["amount"]["value"]) * float(i["quantity"]) for i in r["items"])
        assert abs(total_items * 100 - sum(p.amount for p in inv.prices)) < 1, (total_items, inv.prices)
        assert any(i["description"] == "Доставка" and i["payment_subject"] == "service" for i in r["items"])
        assert all(i["vat_code"] == 1 and i["amount"]["currency"] == "RUB" for i in r["items"])
    finally:
        config.PAYMENT_TOKEN = ""; config.RECEIPTS = False


def test_quiz_flow():
    x = h()
    x.cb("m:quiz"); x.cb("qa:0:flat"); x.cb("qa:1:m")
    n = len(x.session.sent); x.cb("qb:2")                         # назад ко 2-му вопросу
    assert any("вопрос 2 из 4" in s for s in x.texts(n))
    x.cb("qa:1:m"); x.cb("qa:2:cap")
    n = len(x.session.sent); x.cb("qa:3:now")
    assert any("672 000 ₽ – 1 008 000 ₽" in s for s in x.texts(n)), x.texts(n)
    n = len(x.session.sent); x.msg("+7 911 222 33 44")
    assert any("Заявка принята" in s for s in x.texts(n))
    assert any("Новая заявка" in s and "Капитальный" in s for s in x.texts(n, to=999))


def test_admin_panel_export_and_broadcast():
    x = h()
    n = len(x.session.sent); x.msg("/admin")
    assert any("только владельцу" in s for s in x.texts(n))
    n = len(x.session.sent); x.msg("/admin", user=ADMIN)
    assert any("Админка" in s and f"Заказов: {db.stats()['orders']}" in s for s in x.texts(n)), x.texts(n)
    n = len(x.session.sent); x.cb("a:export", user=ADMIN)
    docs = [m for m in x.session.sent[n:] if isinstance(m, SendDocument)]
    assert len(docs) == 4
    x.cb("a:bcast", user=ADMIN); x.msg("Акция: −20% на капучино!", user=ADMIN)
    n = len(x.session.sent); x.cb("bc:yes", user=ADMIN)
    assert any(isinstance(m, SendMessage) and m.chat_id == 111 and "Акция" in m.text for m in x.session.sent[n:])
    assert any("доставлено" in s for s in x.texts(n))
    n = len(x.session.sent); x.cb("a:orders")                     # не админ
    assert "Только для владельца" in x.alerts(n)


def test_cancel_and_start_reset_state():
    x = h()
    x.cb("m:shop"); x.cb("si:esp"); x.cb("sq:esp:1"); x.cb("sh:checkout")
    n = len(x.session.sent); x.msg("/start")
    assert any("демо-бот" in s for s in x.texts(n))
    n = len(x.session.sent); x.msg("какой-то текст")              # не должен попасть в оформление
    assert not any("Телефон" in s for s in x.texts(n))
    assert any("работаю кнопками" in s for s in x.texts(n))


def test_broadcast_cancel_command():
    x = h()
    x.cb("a:bcast", user=ADMIN)
    n = len(x.session.sent); x.msg("/cancel", user=ADMIN)
    assert any("отмен" in s.lower() for s in x.texts(n))
    n = len(x.session.sent); x.msg("обычный текст", user=ADMIN)
    assert not any("Отправить это сообщение" in s for s in x.texts(n))


def test_reminders_sent_once():
    x = h()
    st = common.now_local() + timedelta(minutes=90)
    bid = db.add_booking(111, "Тест", "+7", "cut", "oleg", st, st + timedelta(minutes=60))
    assert bid
    due = db.due_reminders(common.now_local() + timedelta(minutes=config.REMIND_BEFORE_MIN), common.now_local())
    assert any(r["id"] == bid for r in due)
    db.mark_reminded(bid)
    due = db.due_reminders(common.now_local() + timedelta(minutes=config.REMIND_BEFORE_MIN), common.now_local())
    assert not any(r["id"] == bid for r in due)


class SplitHarness(Harness):
    """Раздельный режим: клиентский бот + служебный бот владельца со своей сессией."""
    def __init__(self):
        super().__init__()
        self.dp = botmod.build_dispatcher(split=True)
        self.asession = FakeSession()
        self.abot = Bot("456:DEF", session=self.asession, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
        self.adp = botmod.build_admin_dispatcher()
        common.CLIENT_BOT, common.ADMIN_BOT = self.bot, self.abot

    def amsg(self, text, user=ADMIN):
        m = {"message_id": self.uid + 1, "date": 0, "chat": {"id": user["id"], "type": "private"}, "from": user, "text": text}
        if text.startswith("/"):
            m["entities"] = [{"type": "bot_command", "offset": 0, "length": len(text.split()[0])}]
        self.uid += 1
        return run(self.adp.feed_update(self.abot, Update.model_validate({"update_id": self.uid, "message": m}, context={"bot": self.abot})))

    def acb(self, data_, user=ADMIN):
        q = {"id": str(self.uid), "from": user, "chat_instance": "x", "data": data_,
             "message": {"message_id": 5, "date": 0, "chat": {"id": user["id"], "type": "private"}, "text": "x"}}
        self.uid += 1
        return run(self.adp.feed_update(self.abot, Update.model_validate({"update_id": self.uid, "callback_query": q}, context={"bot": self.abot})))

    def atexts(self, since=0, to=None):
        return [m.text for m in self.asession.sent[since:] if isinstance(m, (SendMessage, EditMessageText))
                and (to is None or getattr(m, "chat_id", to) == to)]


def test_admin_all_bookings_and_day_view():
    x = h()
    base = common.now_local().replace(hour=12, minute=0) + timedelta(days=2)
    b1 = db.add_booking(111, "Анна", "+7900", "cut", "ivan", base, base + timedelta(minutes=60))
    b2 = db.add_booking(111, "Борис", "+7901", "cut", "oleg", base + timedelta(days=3), base + timedelta(days=3, minutes=60))
    n = len(x.session.sent); x.cb("a:all", user=ADMIN)
    t = "\n".join(x.texts(n))
    assert "Анна" in t and "Борис" in t and "Все предстоящие записи" in t, t
    day = f"a:day:{base:%Y-%m-%d}"
    assert day in x.buttons(n)
    n = len(x.session.sent); x.cb(day, user=ADMIN)
    t = "\n".join(x.texts(n))
    assert "Анна" in t and "Борис" not in t, t
    n = len(x.session.sent); x.cb("a:all")                        # не админ
    assert "Только для владельца" in x.alerts(n)


def test_split_admin_bot():
    x = SplitHarness()
    try:
        # заявка в клиентском боте → уведомление владельцу приходит в служебный бот, а не в клиентский
        x.cb("m:quiz"); x.cb("qa:0:flat"); x.cb("qa:1:m"); x.cb("qa:2:cap"); x.cb("qa:3:now")
        n, na = len(x.session.sent), len(x.asession.sent)
        x.msg("+7 911 222 33 44")
        assert any("Новая заявка" in s for s in x.atexts(na, to=999)), (x.atexts(na), x.texts(n))
        assert not any("Новая заявка" in s for s in x.texts(n, to=999)), "уведомление ушло в клиентский бот"
        assert any("служебный бот" in s for s in x.texts(n, to=111)), "нет демо-превью"
        # /admin в клиентском боте — подсказка, админки нет
        n = len(x.session.sent); x.msg("/admin", user=ADMIN)
        assert any("служебном боте" in s for s in x.texts(n)) and not any("Админка</b>" in s for s in x.texts(n))
        # служебный бот: чужому закрыт, владельцу /start открывает админку
        na = len(x.asession.sent); x.amsg("/start", user=USER)
        assert any("Доступ закрыт" in s for s in x.atexts(na))
        na = len(x.asession.sent); x.amsg("/start")
        assert any("Админка" in s for s in x.atexts(na)), x.atexts(na)
        # рассылка из служебного бота уходит клиентам через клиентский бот
        x.acb("a:bcast"); x.amsg("Скидка 10% сегодня")
        n, na = len(x.session.sent), len(x.asession.sent); x.acb("bc:yes")
        assert any(isinstance(m, SendMessage) and m.chat_id == 111 and "Скидка" in m.text for m in x.session.sent[n:])
        assert any("доставлено" in s for s in x.atexts(na))
    finally:
        common.CLIENT_BOT = common.ADMIN_BOT = None


if __name__ == "__main__":
    asyncio.set_event_loop(asyncio.new_event_loop())
    fns = [v for k, v in globals().items() if k.startswith("test_")]
    ok = 0
    for f in fns:
        try:
            f(); ok += 1; print("ok  ", f.__name__)
        except Exception:
            print("FAIL", f.__name__); traceback.print_exc()
    print(f"\n{ok}/{len(fns)} прошли")
