import argparse
import math
from poke_utils import load_users, ensure_user_fields

PAGE_SIZE = 10

def paginate(items, page_size=PAGE_SIZE):
    total_pages = math.ceil(len(items) / page_size)
    page = 0
    while True:
        start = page * page_size
        end = start + page_size
        print(f"\nPage {page + 1}/{total_pages}")
        for item in items[start:end]:
            print(item)
        if total_pages == 0:
            break
        cmd = input("(n)ext, (p)rev, (q)uit: ").lower()
        if cmd == 'n' and page < total_pages - 1:
            page += 1
        elif cmd == 'p' and page > 0:
            page -= 1
        elif cmd == 'q':
            break
        else:
            print("Invalid input")

def main():
    parser = argparse.ArgumentParser(description="Show user card collection")
    parser.add_argument("user_id", help="Discord user ID")
    args = parser.parse_args()

    users = load_users()
    uid = str(args.user_id)
    if uid not in users:
        print("User not found")
        return
    user = ensure_user_fields(users[uid])
    cards = user.get("cards", [])
    entries = [f"{c['id']} - {c.get('name', '')} ({c.get('price_usd',0)} USD)" for c in cards]
    if not entries:
        print("No cards")
        return
    paginate(entries)

if __name__ == "__main__":
    main()
