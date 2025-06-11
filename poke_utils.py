import json
import time
from pathlib import Path
import discord

BASE_DIR = Path(__file__).resolve().parent
USERS_FILE = BASE_DIR / "users.json"
SETS_FILE = BASE_DIR / "sets.json"
PRICE_FILE = BASE_DIR / "price.json"
DATA_FILE = BASE_DIR / "data.json"
EVENTS_FILE = BASE_DIR / "events.json"
CHANNELS_FILE = BASE_DIR / "channels.json"

# Default color for embeds used across the bot
EMBED_COLOR = discord.Color.dark_teal()

def create_embed(title: str, description: str | None = None, *, color: discord.Color | None = None) -> discord.Embed:
    """Return a consistently styled embed."""
    if color is None:
        color = EMBED_COLOR
    return discord.Embed(title=title, description=description, color=color)

def load_users():
    try:
        with open(USERS_FILE, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError:
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
    except json.JSONDecodeError:
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
    user.setdefault("money_sales", 0)
    user.setdefault("money_events", 0)
    user.setdefault("money_achievements", 0)
    user.setdefault("last_daily", 0)
    user.setdefault("daily_streak", 0)
    user.setdefault("weekly_best", {"week": 0, "year": 0, "price": 0, "name": ""})
    user.setdefault("weekly_community", {"week": 0, "year": 0, "score": 0})
    user.setdefault("achievements", [])
    user.setdefault("badges", [])
    user.setdefault("created_at", int(time.time()))
    return user


def load_prices():
    try:
        with open(PRICE_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
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
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)


def load_events():
    try:
        with open(EVENTS_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def save_events(data):
    with open(EVENTS_FILE, "w") as f:
        json.dump(data, f, indent=4)


def active_event_types(now=None):
    if now is None:
        now = time.time()
    events = load_events()
    types = set()
    for ev in events:
        if ev.get("start", 0) <= now <= ev.get("end", 0):
            types.add(ev.get("type"))
    return types


def load_channels():
    try:
        with open(CHANNELS_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_channels(data):
    with open(CHANNELS_FILE, "w") as f:
        json.dump(data, f, indent=4)
