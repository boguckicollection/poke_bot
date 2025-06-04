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
