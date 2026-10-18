"""SQLite: пользователи, записи, корзины, заказы, заявки. Один файл на Volume /data."""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone

import config

_conn: sqlite3.Connection | None = None


def conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        os.makedirs(os.path.dirname(config.DB_PATH) or ".", exist_ok=True)
        _conn = sqlite3.connect(config.DB_PATH, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.executescript("""
        CREATE TABLE IF NOT EXISTS users(user_id INTEGER PRIMARY KEY, name TEXT, username TEXT, first_seen TEXT);
        CREATE TABLE IF NOT EXISTS bookings(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, name TEXT, phone TEXT,
            service TEXT, master TEXT, start TEXT, end TEXT, status TEXT DEFAULT 'active', reminded INTEGER DEFAULT 0, created TEXT);
        CREATE INDEX IF NOT EXISTS ix_b_master ON bookings(master, start);
        CREATE TABLE IF NOT EXISTS carts(user_id INTEGER, product TEXT, qty INTEGER, PRIMARY KEY(user_id, product));
        CREATE TABLE IF NOT EXISTS orders(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, items TEXT, goods INTEGER, delivery INTEGER,
            name TEXT, phone TEXT, address TEXT, paid INTEGER DEFAULT 0, status TEXT DEFAULT 'new', created TEXT);
        CREATE TABLE IF NOT EXISTS leads(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, name TEXT, phone TEXT,
            answers TEXT, estimate TEXT, created TEXT);
        """)
    return _conn


def reset_for_tests(path: str):
    global _conn
    if _conn is not None:
        _conn.close()
    _conn = None
    config.DB_PATH = path


def now_s() -> str:
    """Время создания записи — местное время заведения (TZ_OFFSET_HOURS), а не UTC."""
    return (datetime.now(timezone.utc) + timedelta(hours=config.TZ_OFFSET)).strftime("%Y-%m-%d %H:%M")


# ---------------------------------------------------------------- пользователи
def touch_user(user_id: int, name: str, username: str | None):
    c = conn()
    c.execute("INSERT INTO users VALUES(?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET name=excluded.name, username=excluded.username",
              (user_id, name, username or "", now_s()))
    c.commit()


def all_users() -> list[int]:
    return [r[0] for r in conn().execute("SELECT user_id FROM users")]


# ---------------------------------------------------------------- записи
def busy(master_id: str, day: str) -> list[tuple[datetime, datetime]]:
    rows = conn().execute("SELECT start, end FROM bookings WHERE master=? AND status='active' AND start LIKE ?",
                          (master_id, day + "%")).fetchall()
    return [(datetime.fromisoformat(r["start"]), datetime.fromisoformat(r["end"])) for r in rows]


def add_booking(user_id, name, phone, service_id, master_id, start: datetime, end: datetime) -> int | None:
    """Атомарно: если слот уже заняли, вернёт None."""
    c = conn()
    with c:
        clash = c.execute("SELECT 1 FROM bookings WHERE master=? AND status='active' AND NOT (end<=? OR start>=?)",
                          (master_id, start.isoformat(sep=" ", timespec="minutes"), end.isoformat(sep=" ", timespec="minutes"))).fetchone()
        if clash:
            return None
        cur = c.execute("INSERT INTO bookings(user_id,name,phone,service,master,start,end,created) VALUES(?,?,?,?,?,?,?,?)",
                        (user_id, name, phone, service_id, master_id, start.isoformat(sep=" ", timespec="minutes"),
                         end.isoformat(sep=" ", timespec="minutes"), now_s()))
        return cur.lastrowid


def user_bookings(user_id: int, from_local: datetime) -> list[sqlite3.Row]:
    return conn().execute("SELECT * FROM bookings WHERE user_id=? AND status='active' AND start>=? ORDER BY start",
                          (user_id, from_local.isoformat(sep=" ", timespec="minutes"))).fetchall()


def get_booking(bid: int) -> sqlite3.Row | None:
    return conn().execute("SELECT * FROM bookings WHERE id=?", (bid,)).fetchone()


def cancel_booking(bid: int, user_id: int) -> bool:
    c = conn()
    with c:
        cur = c.execute("UPDATE bookings SET status='cancelled' WHERE id=? AND user_id=? AND status='active'", (bid, user_id))
    return cur.rowcount > 0


def bookings_on(day: str) -> list[sqlite3.Row]:
    return conn().execute("SELECT * FROM bookings WHERE status='active' AND start LIKE ? ORDER BY start", (day + "%",)).fetchall()


def bookings_from(start_local: str, limit: int = 300) -> list[sqlite3.Row]:
    """Все активные записи начиная с момента start_local ('YYYY-MM-DD HH:MM'), по времени."""
    return conn().execute("SELECT * FROM bookings WHERE status='active' AND start>=? ORDER BY start LIMIT ?",
                          (start_local, limit)).fetchall()


def due_reminders(until_local: datetime, from_local: datetime) -> list[sqlite3.Row]:
    return conn().execute("SELECT * FROM bookings WHERE status='active' AND reminded=0 AND start<=? AND start>?",
                          (until_local.isoformat(sep=" ", timespec="minutes"), from_local.isoformat(sep=" ", timespec="minutes"))).fetchall()


def mark_reminded(bid: int):
    c = conn()
    with c:
        c.execute("UPDATE bookings SET reminded=1 WHERE id=?", (bid,))


# ---------------------------------------------------------------- корзина и заказы
def cart(user_id: int) -> dict[str, int]:
    return {r["product"]: r["qty"] for r in conn().execute("SELECT product, qty FROM carts WHERE user_id=?", (user_id,))}


def cart_add(user_id: int, pid: str, delta: int) -> int:
    c = conn()
    with c:
        q = (c.execute("SELECT qty FROM carts WHERE user_id=? AND product=?", (user_id, pid)).fetchone() or [0])[0]
        q = max(0, min(99, q + delta))
        if q:
            c.execute("INSERT OR REPLACE INTO carts VALUES(?,?,?)", (user_id, pid, q))
        else:
            c.execute("DELETE FROM carts WHERE user_id=? AND product=?", (user_id, pid))
    return q


def cart_clear(user_id: int):
    c = conn()
    with c:
        c.execute("DELETE FROM carts WHERE user_id=?", (user_id,))


def add_order(user_id, items: dict, goods: int, delivery: int, name, phone, address) -> int:
    c = conn()
    with c:
        cur = c.execute("INSERT INTO orders(user_id,items,goods,delivery,name,phone,address,created) VALUES(?,?,?,?,?,?,?,?)",
                        (user_id, json.dumps(items, ensure_ascii=False), goods, delivery, name, phone, address, now_s()))
    return cur.lastrowid


def mark_paid(order_id: int):
    c = conn()
    with c:
        c.execute("UPDATE orders SET paid=1 WHERE id=?", (order_id,))


def get_order(order_id: int) -> sqlite3.Row | None:
    return conn().execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()


# Статусы заказа: new — новый, work — в работе (готовится/везут), done — выполнен, cancel — отменён.
# 'paid' — старое значение из прежней версии, считается новым.
ACTIVE = ("new", "work", "paid")


def set_order_status(order_id: int, status: str) -> bool:
    assert status in ("new", "work", "done", "cancel")
    c = conn()
    with c:
        cur = c.execute("UPDATE orders SET status=? WHERE id=?", (status, order_id))
    return cur.rowcount > 0


def orders_by(kind: str, n: int = 20) -> list[sqlite3.Row]:
    """kind: active — новые и в работе (старые сверху, в порядке очереди); done — выполненные и отменённые; recent — все последние."""
    c = conn()
    if kind == "active":
        return c.execute(f"SELECT * FROM orders WHERE status IN ({','.join('?' * len(ACTIVE))}) ORDER BY id LIMIT ?", (*ACTIVE, n)).fetchall()
    if kind == "done":
        return c.execute("SELECT * FROM orders WHERE status IN ('done','cancel') ORDER BY id DESC LIMIT ?", (n,)).fetchall()
    return c.execute("SELECT * FROM orders ORDER BY id DESC LIMIT ?", (n,)).fetchall()


def order_counts() -> dict:
    c = conn()
    one = lambda q, *a: c.execute(q, a).fetchone()[0]
    return {"active": one(f"SELECT COUNT(*) FROM orders WHERE status IN ({','.join('?' * len(ACTIVE))})", *ACTIVE),
            "done": one("SELECT COUNT(*) FROM orders WHERE status IN ('done','cancel')"),
            "all": one("SELECT COUNT(*) FROM orders")}


def clear_history(what: str) -> int:
    """
    finished — удалить выполненные и отменённые заказы;
    all — стереть все заказы, записи, заявки и корзины (пользователи остаются для рассылки).
    Возвращает, сколько строк удалено.
    """
    c = conn()
    with c:
        if what == "finished":
            return c.execute("DELETE FROM orders WHERE status IN ('done','cancel')").rowcount
        n = 0
        for t in ("orders", "bookings", "leads", "carts"):
            n += c.execute(f"DELETE FROM {t}").rowcount
        c.execute("DELETE FROM sqlite_sequence WHERE name IN ('orders','bookings','leads')")   # нумерация снова с #1
        return n


def recent(table: str, n: int = 10) -> list[sqlite3.Row]:
    assert table in ("orders", "leads", "bookings")
    return conn().execute(f"SELECT * FROM {table} ORDER BY id DESC LIMIT ?", (n,)).fetchall()


# ---------------------------------------------------------------- заявки
def add_lead(user_id, name, phone, answers: dict, estimate: str) -> int:
    c = conn()
    with c:
        cur = c.execute("INSERT INTO leads(user_id,name,phone,answers,estimate,created) VALUES(?,?,?,?,?,?)",
                        (user_id, name, phone, json.dumps(answers, ensure_ascii=False), estimate, now_s()))
    return cur.lastrowid


# ---------------------------------------------------------------- админка
def stats() -> dict:
    c = conn()
    one = lambda q: c.execute(q).fetchone()[0]
    return {"users": one("SELECT COUNT(*) FROM users"),
            "bookings": one("SELECT COUNT(*) FROM bookings WHERE status='active'"),
            "orders": one("SELECT COUNT(*) FROM orders"),
            "revenue": one("SELECT COALESCE(SUM(goods+delivery),0) FROM orders"),
            "leads": one("SELECT COUNT(*) FROM leads")}


def export_csv(table: str) -> bytes:
    import csv
    import io
    assert table in ("orders", "leads", "bookings", "users")
    cur = conn().execute(f"SELECT * FROM {table} ORDER BY rowid")
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow([d[0] for d in cur.description])
    w.writerows(cur.fetchall())
    return ("﻿" + buf.getvalue()).encode("utf-8")       # BOM — чтобы Excel открыл кириллицу
