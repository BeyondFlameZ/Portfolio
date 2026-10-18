"""English demo catalog (USD). Same ids as data.py so bookings/orders stay compatible."""

SALON = {
    "name": "Razor Barbershop",
    "address": "1 Example Street",
    "open_hour": 10, "close_hour": 21, "step_min": 30, "days_ahead": 7, "min_lead_min": 60,
}

SERVICES = [
    {"id": "cut", "name": "Men's haircut", "price": 35, "dur": 60},
    {"id": "beard", "name": "Beard trim", "price": 20, "dur": 30},
    {"id": "combo", "name": "Haircut + beard", "price": 50, "dur": 90},
    {"id": "kid", "name": "Kids haircut", "price": 25, "dur": 30},
]

MASTERS = [
    {"id": "ivan", "name": "Jack", "services": ["cut", "beard", "combo"], "days_off": [6]},
    {"id": "artem", "name": "Mike", "services": ["cut", "combo", "kid"], "days_off": [0]},
    {"id": "oleg", "name": "Leo", "services": ["cut", "beard", "kid"], "days_off": [2, 6]},
]

SHOP = {"name": "Bean Coffee", "delivery_price": 5, "free_delivery_from": 40}

CATEGORIES = [
    {"id": "coffee", "name": "☕ Coffee"},
    {"id": "dessert", "name": "🍰 Desserts"},
    {"id": "beans", "name": "🫘 Beans to go"},
]

PRODUCTS = [
    {"id": "esp", "cat": "coffee", "name": "Espresso", "price": 3, "desc": "Double shot, 2 oz"},
    {"id": "cap", "cat": "coffee", "name": "Cappuccino", "price": 5, "desc": "12 oz, any milk"},
    {"id": "raf", "cat": "coffee", "name": "Vanilla latte", "price": 6, "desc": "12 oz"},
    {"id": "flat", "cat": "coffee", "name": "Flat white", "price": 5, "desc": "8 oz, double espresso"},
    {"id": "chz", "cat": "dessert", "name": "Cheesecake", "price": 7, "desc": "New York style"},
    {"id": "crs", "cat": "dessert", "name": "Croissant", "price": 4, "desc": "Butter, baked today"},
    {"id": "brn", "cat": "dessert", "name": "Brownie", "price": 4, "desc": "Dark chocolate"},
    {"id": "eth", "cat": "beans", "name": "Ethiopia, 250 g", "price": 18, "desc": "Berries, citrus. Filter roast"},
    {"id": "bra", "cat": "beans", "name": "Brazil, 250 g", "price": 15, "desc": "Nuts, chocolate. Espresso roast"},
]

QUIZ = {
    "title": "Renovation cost calculator",
    "company": "Turnkey Renovation Studio",
    "questions": [
        {"id": "obj", "text": "What are we renovating?", "options": [("flat", "Apartment", 1.0), ("house", "House", 1.2), ("office", "Office", 1.1)]},
        {"id": "area", "text": "Floor area?", "options": [("s", "up to 400 sq ft", 300), ("m", "400–800 sq ft", 600), ("l", "over 800 sq ft", 1000)]},
        {"id": "kind", "text": "Type of renovation?", "options": [("cosm", "Cosmetic", 25), ("cap", "Full renovation", 60), ("design", "Designer", 110)]},
        {"id": "when", "text": "When to start?", "options": [("now", "As soon as possible", 1.0), ("soon", "In 1–3 months", 1.0), ("later", "Just looking", 1.0)]},
    ],
}
