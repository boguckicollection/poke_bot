import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
USERS_FILE = BASE_DIR / "users.json"
SETS_FILE = BASE_DIR / "sets.json"
PRICE_FILE = BASE_DIR / "price.json"
DATA_FILE = BASE_DIR / "data.json"

def load_users():
    try:
        with open(USERS_FILE, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

def save_users(data):
    with open(USERS_FILE, "w") as f:
        json.dump(data, f, indent=4)

def get_all_sets():
    try:
        with open(SETS_FILE, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return []


def ensure_user_fields(user):
    """Ensure that a user dictionary contains all expected keys."""
    user.setdefault("boosters", [])
    user.setdefault("cards", [])
    user.setdefault("rare_boost", 0)
    user.setdefault("double_daily_until", 0)
    user.setdefault("streak_freeze", 0)
    user.setdefault("boosters_opened", 0)
    user.setdefault("money", 0)
    user.setdefault("last_daily", 0)
    user.setdefault("daily_streak", 0)
    user.setdefault("weekly_best", {"week": 0, "year": 0, "price": 0, "name": ""})
    user.setdefault("achievements", [])
    return user


def load_prices():
    try:
        with open(PRICE_FILE, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        sets = get_all_sets()
        prices = {}
        for s in sets:
            try:
                year = int(s.get("releaseDate", "2000/01/01").split("-")[0])
            except Exception:
                year = 2000
            age = max(0, 2025 - year)
            usd = round(4.0 + age * 0.1, 2)
            price = int(usd * 25)
            prices[s["id"]] = price
        with open(PRICE_FILE, "w") as f:
            json.dump(prices, f, indent=4)
        return prices


def save_prices(data):
    with open(PRICE_FILE, "w") as f:
        json.dump(data, f, indent=4)


def load_data():
    try:
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)
