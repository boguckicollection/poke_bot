import json

USERS_FILE = "users.json"
SETS_FILE = "sets.json"

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
    user.setdefault("money", 0)
    user.setdefault("last_daily", 0)
    user.setdefault("daily_streak", 0)
    user.setdefault("weekly_best", {"week": 0, "year": 0, "price": 0})
    user.setdefault("achievements", [])
    return user
