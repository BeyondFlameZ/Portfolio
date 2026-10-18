"""Настройки из переменных окружения (на Railway — вкладка Variables)."""
import os

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
ADMIN_BOT_TOKEN = os.environ.get("ADMIN_BOT_TOKEN", "")   # второй бот только для владельца: уведомления + /admin. Пусто — всё в одном боте
ADMIN_IDS = {int(x) for x in os.environ.get("ADMIN_IDS", "").replace(" ", "").split(",") if x}
DB_PATH = os.environ.get("DB_PATH", "/data/showcase.db")
BRAND = os.environ.get("BRAND", "Jack Bots")
CONTACT = os.environ.get("CONTACT", "")                 # @username для заказов, например @jack_dev
PAYMENT_TOKEN = os.environ.get("PAYMENT_TOKEN", "")     # токен платёжки из @BotFather (ЮKassa тест/боевой); пусто — оплата при получении
TZ_OFFSET = int(os.environ.get("TZ_OFFSET_HOURS", "3"))  # часовой пояс заведения (3 = Москва)
DEMO_MODE = os.environ.get("DEMO_MODE", "true").strip().lower() in ("1", "true", "yes", "on")
REMIND_BEFORE_MIN = int(os.environ.get("REMIND_BEFORE_MIN", "120"))
# Чеки 54-ФЗ через ЮKassa («Чеки от ЮKassa» или своя касса): без данных чека такие магазины отклоняют оплату
RECEIPTS = os.environ.get("RECEIPTS", "false").strip().lower() in ("1", "true", "yes", "on")
RECEIPT_VAT_CODE = int(os.environ.get("RECEIPT_VAT_CODE", "1"))   # 1 — без НДС (самозанятые, УСН); остальные коды — в доке ЮKassa
