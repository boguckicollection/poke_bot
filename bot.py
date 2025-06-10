import discord
from discord import app_commands
from discord.ui import View, Button, Modal, TextInput, select, Select
from giveaway import GiveawayModal, GiveawayView, parse_time_string
from poke_utils import (
    load_users,
    save_users,
    get_all_sets,
    ensure_user_fields,
    load_prices,
    load_data,
    save_data,
)
import os
import json
from pathlib import Path
import aiohttp
import random
from collections import Counter
import asyncio
import re
from dotenv import load_dotenv
import datetime

# Ile BoguckiCoinów odpowiada jednemu dolarowi
# Przyjęto nieco niższy przelicznik, aby zbilansować
# ceny w sklepie względem dziennych nagród
COINS_PER_USD = 20

# Prosty cache kart pobranych z API {set_id: {rarity: [cards]}}
CARD_CACHE = {}
BASE_DIR = Path(__file__).resolve().parent
GRAPHIC_DIR = BASE_DIR / "graphic"
CARD_CACHE_FILE = BASE_DIR / "card_cache.json"

def load_card_cache():
    global CARD_CACHE
    try:
        with open(CARD_CACHE_FILE, "r") as f:
            CARD_CACHE = json.load(f)
    except FileNotFoundError:
        CARD_CACHE = {}

def save_card_cache():
    with open(CARD_CACHE_FILE, "w") as f:
        json.dump(CARD_CACHE, f)


async def fetch_all_cards_for_set(session: aiohttp.ClientSession, set_id: str):
    cards = []
    page = 1
    while True:
        url = f"https://api.pokemontcg.io/v2/cards?q=set.id:{set_id}&page={page}&pageSize=250"
        async with session.get(url) as resp:
            data = await resp.json()
            cards.extend(data.get("data", []))
            if len(cards) >= data.get("totalCount", len(cards)):
                break
            page += 1
    rarity_dict = {}
    for card in cards:
        rarity = card.get("rarity", "Unknown")
        rarity_dict.setdefault(rarity, []).append(card)
    CARD_CACHE[set_id] = rarity_dict


async def prefetch_cards_for_sets(set_ids):
    if not set_ids:
        return
    headers = {"X-Api-Key": POKETCG_API_KEY}
    async with aiohttp.ClientSession(headers=headers) as session:
        for sid in set_ids:
            await fetch_all_cards_for_set(session, sid)
    save_card_cache()

EMBED_COLOR = discord.Color.dark_teal()

# Opisy osiągnięć
ACHIEVEMENTS_INFO = {
    "account_created": "Założenie konta",
    "daily_10": "10-dniowy streak daily",
    "daily_30": "30-dniowy streak daily",
    "top3_week": "TOP 3 drop tygodnia",
    "first_booster": "Pierwszy otwarty booster",
    "open_5_boosters": "Początkujący kolekcjoner (5 boosterów)",
    "open_25_boosters": "Zaawansowany kolekcjoner (25 boosterów)",
    "open_100_boosters": "Profesjonalny kolekcjoner (100 boosterów)",
    "open_500_boosters": "Uzależniony od kart (500 boosterów)",
    "open_10_boosters": "Otwórz 10 boosterów",  # zachowane dla zgodności
    "first_card": "Pierwsza karta",
    "cards_50": "Mała kolekcja (50 kart)",
    "cards_250": "Duża kolekcja (250 kart)",
    "cards_1000": "Ogromna kolekcja (1000 kart)",
    "all_rarities": "Kolekcjoner wszystkich rarów",
    "first_rare": "Pierwsza karta Rare",
    "rare_10": "Mistrz Rare (10 różnych)",
    "rare_50": "Legendarny kolekcjoner (50 Rare)",
    "first_duplicate": "Pierwszy duplikat",
    "duplicate_10": "Król duplikatów (10 kopii)",
    "duplicates_20_cards": "Zbieracz kopii (20 kart x2)",
    "first_set": "Pierwszy set",
    "sets_5": "Kolekcjoner setów (5)",
    "sets_10": "Znawca setów (10)",
    "sets_all": "Mistrz wszystkich setów",
    "new_player": "Nowy gracz (1 dzień)",
    "veteran": "Weteran (30 dni)",
    "legendary_player": "Legendarny gracz (100 dni)",
    "all_achievements": "Mistrz wszystkich osiągnięć",
}

# Nagrody pieniężne za osiągnięcia (w BC)
ACHIEVEMENT_REWARDS = {
    "account_created": 10,
    "daily_10": 50,
    "daily_30": 100,
    "top3_week": 150,
    "first_booster": 20,
    "open_5_boosters": 50,
    "open_25_boosters": 100,
    "open_100_boosters": 200,
    "open_500_boosters": 500,
    "first_card": 20,
    "cards_50": 50,
    "cards_250": 100,
    "cards_1000": 200,
    "first_rare": 20,
    "rare_10": 100,
    "rare_50": 300,
    "first_duplicate": 20,
    "duplicate_10": 100,
    "duplicates_20_cards": 200,
    "first_set": 50,
    "sets_5": 100,
    "sets_10": 200,
    "sets_all": 500,
    "new_player": 10,
    "veteran": 50,
    "legendary_player": 200,
    "master": 200,
    "all_achievements": 1000,
}

# Grupowanie osiągnięć na potrzeby paginacji
ACHIEVEMENT_GROUPS = [
    (
        "Otwieranie boosterów",
        [
            ("first_booster", 1),
            ("open_5_boosters", 5),
            ("open_25_boosters", 25),
            ("open_100_boosters", 100),
            ("open_500_boosters", 500),
        ],
    ),
    (
        "Rozmiar kolekcji",
        [
            ("first_card", 1),
            ("cards_50", 50),
            ("cards_250", 250),
            ("cards_1000", 1000),
        ],
    ),
    (
        "Rzadkie karty",
        [
            ("first_rare", 1),
            ("rare_10", 10),
            ("rare_50", 50),
        ],
    ),
    (
        "Duplikaty kart",
        [
            ("first_duplicate", 2),
            ("duplicate_10", 10),
            ("duplicates_20_cards", 20),
        ],
    ),
    (
        "Zbiory setów",
        [
            ("first_set", 1),
            ("sets_5", 5),
            ("sets_10", 10),
            ("sets_all", 0),  # target uzupełniany później
        ],
    ),
    (
        "Czas gry",
        [
            ("new_player", 1),
            ("veteran", 30),
            ("legendary_player", 100),
        ],
    ),
    (
        "Pozostałe",
        [
            ("account_created", 1),
            ("daily_10", 10),
            ("daily_30", 30),
            ("top3_week", 1),
            ("all_achievements", 1),
        ],
    ),
]

def usd_to_bc(usd: float) -> int:
    """Przelicz dolary na BoguckiCoiny."""
    return int(usd * COINS_PER_USD) if usd else 0

def progress_bar(value: int, target: int, length: int = 10) -> str:
    ratio = min(value / target, 1.0)
    filled = round(ratio * length)
    return "🟨" * filled + "⬜" * (length - filled)

def achievement_description(code: str, all_sets) -> str:
    if code.startswith("master:"):
        sid = code.split(":", 1)[1]
        name = next((s["name"] for s in all_sets if s["id"] == sid), sid)
        return f"🏆 Master set {name}"
    return f"🏅 {ACHIEVEMENTS_INFO.get(code, code)}"


async def send_achievement_message(interaction_or_user, code: str):
    """Wyślij graczowi gratulacje z osiągnięcia."""
    reward = ACHIEVEMENT_REWARDS.get(code, 0)
    embed = discord.Embed(
        title="Nowe osiągnięcie!",
        description=(
            f"Gratulacje! Zdobywasz **{ACHIEVEMENTS_INFO.get(code, code)}**\n"
            f"Nagroda: {reward} BC {COIN_EMOJI}"
        ),
        color=discord.Color.gold(),
    )

    class GoAchievementsView(View):
        @discord.ui.button(label="Otwórz osiągnięcia", style=discord.ButtonStyle.primary)
        async def show(self, i: discord.Interaction, _):
            await achievements_cmd.callback(i)

    if isinstance(interaction_or_user, discord.Interaction):
        await interaction_or_user.followup.send(embed=embed, view=GoAchievementsView(), ephemeral=True)
    else:
        try:
            await interaction_or_user.send(embed=embed, view=GoAchievementsView())
        except Exception:
            pass


def grant_achievement(user: dict, code: str) -> bool:
    """Dodaj osiągnięcie i przyznaj nagrodę. Zwraca True gdy nowe."""
    if code in user.setdefault("achievements", []):
        return False
    user["achievements"].append(code)
    reward = ACHIEVEMENT_REWARDS.get(code, ACHIEVEMENT_REWARDS.get("master", 0) if code.startswith("master:") else 0)
    user["money"] = user.get("money", 0) + reward
    return True


def check_for_all_achievements(user: dict) -> bool:
    """Sprawdź czy użytkownik zdobył wszystkie osiągnięcia."""
    required = set(ACHIEVEMENTS_INFO.keys()) - {"all_achievements"}
    return required.issubset(set(user.get("achievements", [])))


def build_achievement_pages(user, all_sets):
    """Zbuduj listę embedów przedstawiających postępy w osiągnięciach."""
    ach = user.get("achievements", [])
    opened = user.get("boosters_opened", 0)
    total_cards = len(user["cards"])
    rare_ids = {c["id"] for c in user["cards"] if c.get("rarity") == "Rare"}
    rare_count = len(rare_ids)
    counts = Counter(c["id"] for c in user["cards"])
    max_dup = max(counts.values()) if counts else 0
    dup20 = len([v for v in counts.values() if v >= 2])
    set_ids = {c["id"].split("-")[0] for c in user["cards"]}
    days = int((datetime.datetime.now(datetime.UTC).timestamp() - user.get("created_at", 0)) / 86400)
    pages = []
    for title, entries in ACHIEVEMENT_GROUPS:
        embed = discord.Embed(title=title, color=discord.Color.green())
        for code, target in entries:
            value = 0
            tgt = target
            if code in {"first_booster", "open_5_boosters", "open_25_boosters", "open_100_boosters", "open_500_boosters"}:
                value = opened
            elif code in {"first_card", "cards_50", "cards_250", "cards_1000"}:
                value = total_cards
            elif code in {"first_rare", "rare_10", "rare_50"}:
                value = rare_count
            elif code == "duplicates_20_cards":
                value = dup20
            elif code in {"first_duplicate", "duplicate_10"}:
                value = max_dup
            elif code in {"first_set", "sets_5", "sets_10", "sets_all"}:
                value = len(set_ids)
                if code == "sets_all":
                    tgt = len(all_sets)
            elif code in {"new_player", "veteran", "legendary_player"}:
                value = days
            elif code in {"daily_10", "daily_30"}:
                value = user.get("daily_streak", 0)
                tgt = target
            elif code in {"account_created", "top3_week", "all_achievements"}:
                value = 1 if code in ach else 0
            bar = progress_bar(value, tgt)
            status = "✅" if code in ach else ""
            embed.add_field(name=ACHIEVEMENTS_INFO.get(code, code), value=f"{bar} {value}/{tgt} {status}", inline=False)
        pages.append(embed)
    return pages

# --- parametry ekonomii ---
START_MONEY = 100
BOOSTER_PRICE = 100
DAILY_AMOUNT = 50
DAILY_COOLDOWN = 24 * 3600
STREAK_BONUS = 200

load_dotenv()
load_card_cache()

USERS_FILE = BASE_DIR / "users.json"
SETS_FILE = BASE_DIR / "sets.json"
DISCORD_TOKEN = os.environ["BOT_TOKEN"]
POKETCG_API_KEY = os.environ["POKETCG_API_KEY"]
DROP_CHANNEL_ID = 1374695570182246440
STARTIT_BOT_ID = 572906387382861835
# Kanał do ogłaszania aktualizacji sklepu
SHOP_CHANNEL_ID = DROP_CHANNEL_ID

# Przedmioty dostępne w sklepie
ITEMS = {
    "rare_boost": {
        "name": "Rare Booster",
        "price": 200,
        "desc": "Zwiększa szansę na rzadkie karty w następnym boosterze",
    },
    "double_daily": {
        "name": "Double Daily",
        "price": 300,
        "desc": "Przez 7 dni podwaja monety z komendy /daily",
    },
    "mystery_booster": {
        "name": "Mystery Booster",
        "price": 500,
        "desc": "Natychmiast daje losowy booster",
    },
    "streak_freeze": {
        "name": "Streak Freeze",
        "price": 150,
        "desc": "Utrzymuje serię daily gdy raz ją pominiesz",
    },
}

# Grafika tyłu karty używana w animacji odsłaniania
CARD_BACK_URL = "https://m.media-amazon.com/images/I/61vOBvbsYJL._AC_UF1000,1000_QL80_DpWeblab_.jpg"
# lub jeśli chcesz użyć oficjalnego:
# CARD_BACK_URL = "https://images.pokemontcg.io/other/official-backs/2021.jpg"

# Grafika nagłówka sklepu
SHOP_IMAGE_PATH = GRAPHIC_DIR / "shop.png"
# Ikona waluty
COIN_IMAGE_PATH = GRAPHIC_DIR / "coin.png"
# Emoji waluty używane w komunikatach
BC_COIN_ID = os.environ.get("BC_COIN_ID", "1381617796282319010")
COIN_EMOJI = f"<:bc_coin:{BC_COIN_ID}>"
FUN_EMOJIS = ["✨", "🎉", "🎲", "🔥", "💎", "🎁", "🌟", "🚀", "🃏"]

# Pamięć koszyków użytkowników {uid: {"boosters": {set_id: qty}, "items": {item: qty}}}
carts = {}

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

async def fetch_and_save_sets():
    url = "https://api.pokemontcg.io/v2/sets"
    headers = {"X-Api-Key": POKETCG_API_KEY}
    async with aiohttp.ClientSession(headers=headers) as session:
        async with session.get(url) as response:
            if response.status != 200:
                print(f"❌ Błąd pobierania zestawów: {response.status}")
                return []
            data = await response.json()
            sets = data.get("data", [])
            filtered_sets = sorted(
                [s for s in sets if s.get("ptcgoCode")],
                key=lambda s: s.get("releaseDate", "2000-01-01"),
                reverse=True,
            )
            try:
                with open(SETS_FILE, "r") as f:
                    existing = json.load(f)
            except FileNotFoundError:
                existing = []
            existing_ids = {s["id"] for s in existing}
            new_sets = [s for s in filtered_sets if s["id"] not in existing_ids]
            if new_sets:
                with open(SETS_FILE, "w") as f:
                    json.dump(filtered_sets, f, indent=4)
                print(f"✅ Dodano {len(new_sets)} nowych setów")
            return new_sets
          
def group_sets_by_language_and_series():
    sets = get_all_sets()
    result = {}
    for s in sets:
        lang = "Angielski"
        # Prosta heurystyka - można rozbudować przy realnych danych
        result.setdefault(lang, {}).setdefault(s["series"], []).append(s)
    return result

def booster_price_usd_for_set(set_obj):
    """Wylicz umowną cenę boostera na podstawie roku wydania."""
    try:
        year = int(set_obj.get("releaseDate", "2000/01/01").split("/")[0])
    except Exception:
        year = 2000
    age = max(0, 2025 - year)
    return round(4.0 + age * 0.1, 2)


def booster_price_coins(set_id):
    prices = load_prices()
    if set_id in prices:
        return prices[set_id]
    sets = get_all_sets()
    set_obj = next((s for s in sets if s["id"] == set_id), None)
    if not set_obj:
        return BOOSTER_PRICE
    usd = booster_price_usd_for_set(set_obj)
    return int(usd * COINS_PER_USD)


def weighted_random_set(sets):
    """Choose a random set weighted by inverse price."""
    if not sets:
        return None
    prices = [booster_price_coins(s["id"]) for s in sets]
    weights = [1 / p if p else 1 for p in prices]
    return random.choices(sets, weights=weights, k=1)[0]


def compute_cart_total(cart):
    total = 0
    for sid, q in cart.get("boosters", {}).items():
        total += q * booster_price_coins(sid)
    total += sum(q * ITEMS[i]["price"] for i, q in cart.get("items", {}).items())
    return total

def build_cart_embed(user_id, message):
    users = load_users()
    user = users.get(user_id, {})
    money = user.get("money", 0)
    cart = carts.get(user_id, {"boosters": {}, "items": {}})
    total = compute_cart_total(cart)
    embed = discord.Embed(title="Koszyk", description=message, color=EMBED_COLOR)
    embed.set_image(url="attachment://koszyk.png")
    embed.add_field(name="Wartość koszyka", value=f"{total} BC {COIN_EMOJI}", inline=False)
    embed.add_field(name="Twoje saldo", value=f"{money} BC {COIN_EMOJI}", inline=False)
    if money < total:
        embed.add_field(name="Brakuje środków", value="Nie masz wystarczającej liczby BC!", inline=False)
    return embed

def current_week_info():
    now = datetime.datetime.now(datetime.UTC)
    week = now.isocalendar()[1]
    year = now.isocalendar()[0]
    return week, year

def update_weekly_best(user, price, name):
    week, year = current_week_info()
    best = user.get("weekly_best", {})
    if (
        best.get("week") != week
        or best.get("year") != year
        or price > best.get("price", 0)
    ):
        user["weekly_best"] = {"week": week, "year": year, "price": price, "name": name}

def check_master_set(user, set_id, all_sets):
    set_info = next((s for s in all_sets if s["id"] == set_id), None)
    if not set_info:
        return False
    total = set_info.get("total", 0)
    owned = len({c["id"] for c in user["cards"] if c["id"].startswith(set_id)})
    if total > 0 and owned >= total:
        ach = f"master:{set_id}"
        return grant_achievement(user, ach)
    return False

def booster_image_url(set_id: str) -> str:
    """Return the URL of the booster pack image for a given set."""
    return f"https://images.pokemontcg.io/{set_id}/booster.png"

def build_shop_embed(user_id):
    sets = get_all_sets()
    purchases = load_data()
    embed = discord.Embed(
        title="Sklep",
        description=(
            "W sklepie znajdziesz boostery i itemy. "
            "Użyj przycisków poniżej, aby dodać produkty do koszyka."
        ),
        color=EMBED_COLOR,
    )
    embed.set_image(url="attachment://shop.png")
    embed.set_footer(text="BoguckiCoin (BC)", icon_url="attachment://coin.png")

    if purchases:
        top = sorted(purchases.items(), key=lambda x: x[1], reverse=True)[:5]
        best_id, best_count = top[0]
        best_set = next((s for s in sets if s['id'] == best_id), None)
        best_name = best_set['name'] if best_set else best_id
        embed.set_image(url=booster_image_url(best_id))
        if best_set and 'images' in best_set and 'logo' in best_set['images']:
            embed.set_thumbnail(url=best_set['images']['logo'])
        embed.add_field(name="🏅 Najpopularniejszy booster", value="\u200b", inline=False)
        embed.add_field(
            name=f"__**1. {best_name}**__",
            value=f"{best_count} sprzedanych",
            inline=False,
        )
        lines = []
        for idx, (sid, cnt) in enumerate(top[1:], start=2):
            name = next((s['name'] for s in sets if s['id'] == sid), sid)
            lines.append(f"{idx}. {name} - {cnt} szt.")
        if lines:
            embed.add_field(
                name="Pozostałe popularne",
                value="\n".join(lines),
                inline=False,
            )
    items_desc = [
        f"**{info['name']}** - {info['price']} BC {COIN_EMOJI} \u2014 {info['desc']}"
        for info in ITEMS.values()
    ]
    embed.add_field(name="Dostępne itemy", value="\n".join(items_desc) or "Brak", inline=False)
    cart = carts.get(user_id)
    if cart and (cart.get("boosters") or cart.get("items")):
        lines = []
        for sid, q in cart.get("boosters", {}).items():
            name = next((s['name'] for s in sets if s['id']==sid), sid)
            lines.append(f"{name} x{q}")
        for iid, q in cart.get("items", {}).items():
            lines.append(f"{ITEMS[iid]['name']} x{q}")
        total = compute_cart_total(cart)
        lines.append(f"**Razem: {total} BC {COIN_EMOJI}**")
        embed.add_field(name="Koszyk", value="\n".join(lines), inline=False)
    return embed

class QuantityModal(Modal):
    def __init__(self, callback):
        super().__init__(title="Podaj ilość")
        self.callback_fn = callback
        self.qty = TextInput(label="Ilość", default="1")
        self.add_item(self.qty)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            qty = max(1, int(self.qty.value))
        except ValueError:
            qty = 1
        await self.callback_fn(interaction, qty)


class QuickBuyView(View):
    def __init__(self, shop_view):
        super().__init__(timeout=60)
        self.shop_view = shop_view

    @discord.ui.button(label="Kup", style=discord.ButtonStyle.success)
    async def finalize(self, interaction: discord.Interaction, button: Button):
        await self.shop_view.finalize(interaction)

    @discord.ui.button(label="Wyczyść koszyk", style=discord.ButtonStyle.danger)
    async def clear(self, interaction: discord.Interaction, button: Button):
        carts.pop(self.shop_view.user_id, None)
        await self.shop_view.update()
        await interaction.response.send_message("Koszyk wyczyszczony", ephemeral=True)

    @discord.ui.button(label="Dodaj kolejny", style=discord.ButtonStyle.primary)
    async def add_more(self, interaction: discord.Interaction, button: Button):
        btn = ShopView.AddBoosterButton(self.shop_view)
        await btn.callback(interaction)

class ShopView(View):
    def __init__(self, user_id):
        super().__init__(timeout=180)
        self.user_id = str(user_id)
        self.message = None
        self.add_item(self.AddBoosterButton(self))
        self.add_item(self.AddItemButton(self))
        self.add_item(self.ClearButton(self))

    async def finalize(self, interaction: discord.Interaction):
        users = load_users()
        uid = self.user_id
        if uid not in users:
            await interaction.response.send_message("📭 Nie masz konta.", ephemeral=True)
            return
        ensure_user_fields(users[uid])
        cart = carts.get(uid)
        if not cart or (not cart.get("boosters") and not cart.get("items")):
            await interaction.response.send_message("Koszyk jest pusty", ephemeral=True)
            return
        total = compute_cart_total(cart)
        if users[uid].get("money", 0) < total:
            await interaction.response.send_message("❌ Za mało BC", ephemeral=True)
            return
        users[uid]["money"] -= total
        data = load_data()
        mystery_results = []
        for sid, q in cart.get("boosters", {}).items():
            users[uid]["boosters"].extend([sid] * q)
            data[sid] = data.get(sid, 0) + q
        save_data(data)
        now_ts = datetime.datetime.now(datetime.UTC).timestamp()
        for iid, q in cart.get("items", {}).items():
            if iid == "double_daily":
                end = users[uid].get("double_daily_until", 0)
                start_from = max(end, now_ts)
                users[uid]["double_daily_until"] = start_from + 7 * 24 * 3600 * q
            elif iid == "mystery_booster":
                sets = get_all_sets()
                for _ in range(q):
                    chosen = weighted_random_set(sets)
                    if not chosen:
                        continue
                    sid = chosen["id"]
                    users[uid]["boosters"].append(sid)
                    data[sid] = data.get(sid, 0) + 1
                    mystery_results.append(chosen.get("name", sid))
            elif iid == "streak_freeze":
                users[uid]["streak_freeze"] = users[uid].get("streak_freeze", 0) + q
            else:
                users[uid][iid] = users[uid].get(iid, 0) + q
        save_users(users)
        carts.pop(uid, None)
        await self.update()
        emj = random.choice(FUN_EMOJIS)
        msg = f"{emj} Zakupiono za {total} BC {COIN_EMOJI}"
        if mystery_results:
            boosters = ", ".join(mystery_results)
            msg += f"\nWylosowano: {boosters}"
        await interaction.response.send_message(msg, ephemeral=True)


    async def interaction_check(self, interaction: discord.Interaction):
        return str(interaction.user.id) == self.user_id

    async def update(self):
        if self.message:
            embed = build_shop_embed(self.user_id)
            file1 = discord.File(SHOP_IMAGE_PATH, filename="shop.png")
            file2 = discord.File(COIN_IMAGE_PATH, filename="coin.png")
            await self.message.edit(embed=embed, view=self, attachments=[file1, file2])

    class AddBoosterButton(Button):
        def __init__(self, parent):
            super().__init__(label="Dodaj booster", style=discord.ButtonStyle.primary)
            self.parent = parent

        async def callback(self, interaction: discord.Interaction):
            groups = group_sets_by_language_and_series()

            lang_options = [discord.SelectOption(label=lang, value=lang) for lang in groups]

            class LanguageView(View):
                def __init__(self, parent):
                    super().__init__(timeout=60)
                    self.parent = parent

                @select(placeholder="Wybierz język", options=lang_options)
                async def select_lang(self, i2: discord.Interaction, menu_lang: discord.ui.Select):
                    lang = menu_lang.values[0]
                    eras = groups.get(lang, {})
                    era_opts = [discord.SelectOption(label=e, value=e) for e in eras]

                    class EraView(View):
                        def __init__(self, shop_view):
                            super().__init__(timeout=60)
                            self.shop_view = shop_view

                        @select(placeholder="Wybierz erę", options=era_opts)
                        async def select_era(self, i3: discord.Interaction, menu_era: discord.ui.Select):
                            era = menu_era.values[0]
                            sets_list = eras.get(era, [])
                            set_opts = [
                                discord.SelectOption(
                                    label=s['name'],
                                    value=s['id'],
                                    description=f"{booster_price_coins(s['id'])} BC {COIN_EMOJI}",
                                )
                                for s in sets_list[:25]
                            ]

                            class SetView(View):
                                def __init__(self, shop_view):
                                    super().__init__(timeout=60)
                                    self.shop_view = shop_view

                                @select(placeholder="Wybierz set", options=set_opts)
                                async def select_set(self, i4: discord.Interaction, menu_set: discord.ui.Select):
                                    set_id = menu_set.values[0]
                                    set_name = next((s['name'] for s in sets_list if s['id']==set_id), set_id)

                                    async def after_qty(i5, qty, shop_view=self.shop_view):
                                        cart = carts.setdefault(shop_view.user_id, {"boosters": {}, "items": {}})
                                        cart['boosters'][set_id] = cart['boosters'].get(set_id, 0) + qty
                                        await shop_view.update()
                                        embed = build_cart_embed(shop_view.user_id, f"Dodano {qty}x {set_name}")
                                        file = discord.File(GRAPHIC_DIR / "koszyk.png", filename="koszyk.png")
                                        await i5.response.send_message(embed=embed, view=QuickBuyView(shop_view), ephemeral=True, files=[file])

                                    modal = QuantityModal(after_qty)
                                    await i4.response.send_modal(modal)

                            embed = discord.Embed(title="Wybierz set", color=EMBED_COLOR)
                            embed.set_image(url="attachment://wybierz_set.png")
                            file = discord.File(GRAPHIC_DIR / "wybierz_set.png", filename="wybierz_set.png")
                            await i3.response.edit_message(embed=embed, view=SetView(self.shop_view), attachments=[file])

                    embed = discord.Embed(title="Wybierz erę", color=EMBED_COLOR)
                    embed.set_image(url="attachment://wybierz_set.png")
                    file = discord.File(GRAPHIC_DIR / "wybierz_set.png", filename="wybierz_set.png")
                    await i2.response.edit_message(embed=embed, view=EraView(self.parent.parent), attachments=[file])

            embed = discord.Embed(title="Wybierz język", color=EMBED_COLOR)
            embed.set_image(url="attachment://wybierz_set.png")
            file = discord.File(GRAPHIC_DIR / "wybierz_set.png", filename="wybierz_set.png")
            await interaction.response.send_message(embed=embed, view=LanguageView(self), ephemeral=True, file=file)

    class AddItemButton(Button):
        def __init__(self, parent):
            super().__init__(label="Dodaj item", style=discord.ButtonStyle.primary)
            self.parent = parent

        async def callback(self, interaction: discord.Interaction):
            options = [discord.SelectOption(label=info['name'], value=iid) for iid, info in ITEMS.items()]

            class ItemSelectView(View):
                def __init__(self, parent):
                    super().__init__(timeout=60)
                    self.parent = parent

                @select(placeholder="Wybierz item", options=options)
                async def select_cb(self, i2: discord.Interaction, menu_item: discord.ui.Select):
                    item_id = menu_item.values[0]
                    item_name = ITEMS[item_id]['name']

                    async def after_qty(i3, qty):
                        cart = carts.setdefault(self.parent.parent.user_id, {"boosters": {}, "items": {}})
                        cart['items'][item_id] = cart['items'].get(item_id, 0) + qty
                        await self.parent.parent.update()
                        embed = build_cart_embed(self.parent.parent.user_id, f"Dodano {qty}x {item_name}")
                        file = discord.File(GRAPHIC_DIR / "koszyk.png", filename="koszyk.png")
                        await i3.response.send_message(embed=embed, view=QuickBuyView(self.parent.parent), ephemeral=True, files=[file])

                    modal = QuantityModal(after_qty)
                    await i2.response.send_modal(modal)

            embed = discord.Embed(title="Wybierz item", color=EMBED_COLOR)
            embed.set_image(url="attachment://koszyk.png")
            file = discord.File(GRAPHIC_DIR / "koszyk.png", filename="koszyk.png")
            await interaction.response.send_message(embed=embed, view=ItemSelectView(self), ephemeral=True, files=[file])

    class ClearButton(Button):
        def __init__(self, parent):
            super().__init__(label="Wyczyść koszyk", style=discord.ButtonStyle.danger)
            self.parent = parent

        async def callback(self, interaction: discord.Interaction):
            carts.pop(self.parent.user_id, None)
            await self.parent.update()
            await interaction.response.send_message("Koszyk wyczyszczony", ephemeral=True)

class MyClient(discord.Client):
    def __init__(self):
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def on_ready(self):
        if not hasattr(self, '_synced'):
            await self.tree.sync()
            self._synced = True
        await fetch_and_save_sets()
        if not CARD_CACHE:
            await prefetch_cards_for_sets([s["id"] for s in get_all_sets()])
        self.loop.create_task(self.shop_update_loop())
        self.loop.create_task(self.weekly_ranking_loop())
        print(f"✅ Zalogowano jako {self.user} (ID: {self.user.id})")

    async def shop_update_loop(self):
        await self.wait_until_ready()
        while not self.is_closed():
            now = datetime.datetime.now(datetime.UTC)
            target = now.replace(hour=20, minute=0, second=0, microsecond=0)
            if now >= target:
                target += datetime.timedelta(days=1)
            await asyncio.sleep((target - now).total_seconds())
            new_sets = await fetch_and_save_sets()
            if new_sets:
                channel = self.get_channel(SHOP_CHANNEL_ID)
                if channel:
                    names = ", ".join(s["name"] for s in new_sets)
                    await channel.send(f"🆕 Nowe sety w sklepie: {names}")
                await prefetch_cards_for_sets([s["id"] for s in new_sets])

    async def weekly_ranking_loop(self):
        await self.wait_until_ready()
        processed = None
        while not self.is_closed():
            week, year = current_week_info()
            now = datetime.datetime.now(datetime.UTC)
            if now.weekday() == 6 and processed != (week, year):
                users = load_users()
                entries = []
                for uid, data in users.items():
                    ensure_user_fields(data)
                    best = data.get("weekly_best")
                    if (
                        best
                        and best.get("week") == week
                        and best.get("year") == year
                        and best.get("price", 0) > 0
                    ):
                        entries.append((uid, best.get("price", 0), best.get("name", "")))
                top3 = sorted(entries, key=lambda x: x[1], reverse=True)[:3]
                lines = []
                changed = False
                for idx, (uid, price, name) in enumerate(top3):
                    reward = (3 - idx) * 50
                    users[uid]["money"] = users[uid].get("money", 0) + reward
                    bc = usd_to_bc(price)
                    lines.append(f"{idx+1}. <@{uid}> - {name} ({bc} BC {COIN_EMOJI})")
                    new_codes = []
                    if grant_achievement(users[uid], "top3_week"):
                        new_codes.append("top3_week")
                    if check_for_all_achievements(users[uid]) and grant_achievement(users[uid], "all_achievements"):
                        new_codes.append("all_achievements")
                    changed = True
                    for code in new_codes:
                        user_obj = self.get_user(int(uid))
                        if user_obj:
                            await send_achievement_message(user_obj, code)
                if lines:
                    embed = discord.Embed(
                        title="TOP 3 dropy tygodnia",
                        description="\n".join(lines),
                        color=discord.Color.purple(),
                    )
                    channel = self.get_channel(DROP_CHANNEL_ID)
                    if channel:
                        await channel.send(embed=embed)
                if changed:
                    save_users(users)
                processed = (week, year)
            await asyncio.sleep(3600)

client = MyClient()

class CollectionMainView(View):
    def __init__(self, user, boosters_counter, all_sets):
        super().__init__(timeout=180)
        self.user = user
        self.boosters_counter = boosters_counter
        self.all_sets = all_sets
        self.add_item(self.SetViewButton(self.user, self.all_sets))
        self.add_item(self.BoosterOpenButton(self.user, self.boosters_counter, self.all_sets))

    async def build_summary_embed(self):
        user = self.user
        boosters_counter = self.boosters_counter
        all_sets = self.all_sets

        total_cards = sum(
            c["count"] if isinstance(c, dict) and "count" in c else 1
            for c in user["cards"]
        )
        unique_cards = len(
            set(c["id"] if isinstance(c, dict) else c for c in user["cards"])
        )
        total_boosters = sum(boosters_counter.values())

        id_to_card = {}
        for c in user["cards"]:
            cid = c["id"] if isinstance(c, dict) else c
            price = c.get("price_usd", 0) if isinstance(c, dict) else 0
            if cid not in id_to_card:
                id_to_card[cid] = {"id": cid, "price_usd": price, "count": 1}
            else:
                id_to_card[cid]["count"] += 1

        card_values = []
        for val in id_to_card.values():
            card_values.append((val["id"], val["price_usd"], val["count"]))

        top5 = sorted(card_values, key=lambda x: x[1], reverse=True)[:5]

        embed = discord.Embed(
            title="Twoja kolekcja Pokémon",
            description=(
                f"Masz **{total_cards} kart** (*{unique_cards} unikalnych*)\n"
                f"Masz **{total_boosters} boosterów** do otwarcia"
            ),
            color=EMBED_COLOR
        )
        embed.set_image(url="attachment://kolekcja.png")
        if top5 and top5[0][1] > 0:
            najdrozsza_id = top5[0][0]
            img_url = ""
            card_name = najdrozsza_id
            set_code = najdrozsza_id.split("-")[0]
            card_number = najdrozsza_id.split("-")[1]
            ptcgo_code = "-"
            for s in all_sets:
                if s["id"] == set_code:
                    ptcgo_code = s["ptcgoCode"]
                    break
            for c in user["cards"]:
                if c["id"] == najdrozsza_id:
                    card_name = c.get("name", najdrozsza_id)
                    img_url = c.get("img_url", "")
                    break
            if img_url:
                embed.set_image(url=img_url)
                set_obj = next((s for s in all_sets if s.get("id") == set_code), None)
                if set_obj and "images" in set_obj and "logo" in set_obj["images"]:
                    embed.set_thumbnail(url=set_obj["images"]["logo"])
            embed.add_field(
                name=f"💎 Najcenniejsza karta",
                value=(
                    f"{card_name} | `{ptcgo_code}` | #{card_number} x{top5[0][2]}\n"
                    f"**{usd_to_bc(top5[0][1])} BC {COIN_EMOJI}**"
                ),
                inline=False
            )
        if len(top5) > 1:
            opis = ""
            for idx, (cid, price, cnt) in enumerate(top5[1:], start=2):
                card_name = cid
                set_code = cid.split("-")[0]
                card_number = cid.split("-")[1]
                ptcgo_code = "-"
                for s in all_sets:
                    if s["id"] == set_code:
                        ptcgo_code = s["ptcgoCode"]
                        break
                for c in user["cards"]:
                    if c["id"] == cid:
                        card_name = c.get("name", cid)
                        break
                opis += (
                    f"{idx}. {card_name} | `{ptcgo_code}` | #{card_number} x{cnt} "
                    f"— **{usd_to_bc(price)} BC {COIN_EMOJI}**\n"
                )
            embed.add_field(name="Pozostałe z TOP 5:", value=opis, inline=False)
        hist = user.get("history", [])
        all_total_usd = sum(price * cnt for _, price, cnt in card_values)
        all_total_bc = usd_to_bc(all_total_usd)
        if len(hist) >= 2:
            diff = hist[-1]["total_usd"] - hist[-2]["total_usd"]
            if diff > 0:
                change = f"⬆️ +{diff:.2f} USD"
            elif diff < 0:
                change = f"⬇️ {diff:.2f} USD"
            else:
                change = "↔️ 0.00 USD"
        else:
            change = "Brak danych"
        embed.add_field(
            name="Suma wartości kolekcji:",
            value=(
                f"**{all_total_usd:.2f} USD** / **{all_total_bc} BC {COIN_EMOJI}**\n"
                f"Zmiana od ostatniej aktualizacji: {change}"
            ),
            inline=False
        )
        boost_count = user.get("rare_boost", 0)
        if boost_count > 0:
            embed.add_field(name="Rare Boosty do użycia", value=f"{boost_count} szt.", inline=False)
        money = user.get("money", 0)
        embed.add_field(name="💰 Saldo", value=f"{money} BC {COIN_EMOJI}", inline=False)
        return embed
    
    class ViewCardsButton(Button):
        def __init__(self, user, sets, set_id):
            super().__init__(label="🔍 Zobacz karty z zestawu", style=discord.ButtonStyle.primary)
            self.user = user
            self.sets = sets
            self.set_id = set_id

        async def callback(self, interaction: discord.Interaction):
            # Można tu dodać pokazanie kart użytkownika z danego setu
            cards = [c for c in self.user["cards"] if c['id'].startswith(self.set_id)]
            if not cards:
                await interaction.response.send_message("❌ Nie masz kart z tego zestawu.", ephemeral=True)
                return

            lines = [f"• {c['name']}" for c in cards[:25]]
            embed = discord.Embed(
                title="Twoje karty z zestawu",
                description="\n".join(lines),
                color=EMBED_COLOR
            )
            embed.set_image(url="attachment://sety.png")
            file = discord.File(GRAPHIC_DIR / "sety.png", filename="sety.png")
            await interaction.response.send_message(embed=embed, ephemeral=True, file=file)

    class SetViewButton(Button):
        def __init__(self, user, all_sets):
            super().__init__(label="Przeglądaj sety", style=discord.ButtonStyle.secondary)
            self.user = user
            self.all_sets = all_sets

        async def callback(self, interaction: discord.Interaction):
            sets = self.all_sets
            user_cards = self.user["cards"]
            user_set_ids = {c['id'].split('-')[0] for c in user_cards}

            options = [
                discord.SelectOption(
                    label=s['name'],
                    value=s['id'],
                    description=f"Wydano: {s.get('releaseDate', 'brak daty')}"
                )
                for s in sets if s['id'] in user_set_ids
            ][:25]

            if not options:
                await interaction.response.send_message(
                    "Nie masz jeszcze żadnych kart z żadnego setu!", ephemeral=True
                )
                return
            class SetDropdownView(View):
                def __init__(self, user, sets, options, selected_set_id=None):
                    super().__init__(timeout=120)
                    self.user = user
                    self.sets = sets
                    self.options = options

                    self.add_item(SetDropdownSelect(self, options))
                    if selected_set_id:
                        self.add_item(CollectionMainView.ViewCardsButton(user, sets, selected_set_id))


            class SetDropdownSelect(Select):
                def __init__(self, parent_view, options):
                    super().__init__(placeholder="Wybierz set", options=options)
                    self.parent_view = parent_view

                async def callback(self, interaction: discord.Interaction):
                    set_id = self.values[0]
                    embed = await build_set_embed(
                        self.parent_view.user,
                        self.parent_view.sets,
                        set_id,
                    )
                    view = SetDropdownView(
                        user=self.parent_view.user,
                        sets=self.parent_view.sets,
                        options=self.parent_view.options,
                        selected_set_id=set_id,
                    )
                    file = discord.File(GRAPHIC_DIR / "sety.png", filename="sety.png")
                    await interaction.response.edit_message(embed=embed, view=view, attachments=[file])

            view = SetDropdownView(self.user, sets, options)
            embed = discord.Embed(
                title="Twoje sety",
                description="Wybierz set z listy poniżej",
                color=EMBED_COLOR,
            )
            embed.set_image(url="attachment://sety.png")
            file = discord.File(GRAPHIC_DIR / "sety.png", filename="sety.png")
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True, file=file)
    class BoosterOpenButton(Button):
        def __init__(self, user, boosters_counter, all_sets):
            super().__init__(label="Otwórz boostery", style=discord.ButtonStyle.success)
            self.user = user
            self.boosters_counter = boosters_counter
            self.all_sets = all_sets

        async def callback(self, interaction: discord.Interaction):
            if not self.user["boosters"]:
                await interaction.response.send_message(
                    "❌ Nie masz boosterów do otwarcia!",
                    ephemeral=True,
                )
                return

            id_to_name = {s["id"]: s["name"] for s in self.all_sets}
            counts = Counter(self.user["boosters"])
            options = [
                discord.SelectOption(
                    label=f"{id_to_name.get(bid, bid)} x{cnt}", value=bid
                )
                for bid, cnt in counts.items()
            ]

            class BoosterSelectView(View):
                @select(placeholder="Wybierz booster do otwarcia", options=options)
                async def select_cb(self, i2: discord.Interaction, menu: discord.ui.Select):
                    chosen = menu.values[0]
                    users = load_users()
                    uid = str(i2.user.id)
                    ensure_user_fields(users[uid])
                    if chosen in users[uid]["boosters"]:
                        users[uid]["boosters"].remove(chosen)
                        save_users(users)
                        await i2.response.defer()
                        await open_booster(i2, chosen)
                    else:
                        await i2.response.send_message("Nie znaleziono boostera.", ephemeral=True)

            await interaction.response.send_message(
                "🃏 Wybierz booster do otwarcia:",
                view=BoosterSelectView(),
                ephemeral=True,
            )

async def build_set_embed(user, sets, set_id):
    set_obj = next((s for s in sets if s['id'] == set_id), None)
    user_cards = [c for c in user["cards"] if c["id"].split("-")[0] == set_id]
    total_cards = set_obj.get("total", 0)
    owned = len(set([c["id"] for c in user_cards]))
    percent = (owned / total_cards) * 100 if total_cards else 0
    filled = round(percent / 10)
    bar = "🟨" * filled + "⬜" * (10 - filled)
    top5 = sorted(
        [(c["id"], c["name"], c["price_usd"], c["img_url"]) for c in user_cards],
        key=lambda x: x[2], reverse=True
    )[:5]
    embed = discord.Embed(
        title=f"{set_obj['name']} ({set_obj['ptcgoCode']})",
        description=(
            f"Masz {owned}/{total_cards} kart ({percent:.1f}%)\n"
            f"{bar}"
        ),
        color=EMBED_COLOR
    )
    embed.set_image(url="attachment://sety.png")
    if top5:
        lines = []
        for idx, (cid, name, price, url) in enumerate(top5):
            lines.append(f"{idx+1}. {name} — {usd_to_bc(price)} BC {COIN_EMOJI}")
        embed.add_field(
            name="🔝 **TOP 5 najdroższych kart**",
            value="\n".join(lines),
            inline=False
        )
        embed.set_image(url=top5[0][3])
    numery = sorted(set(int(c["id"].split("-")[1]) for c in user_cards))
    if numery:
        nums = ", ".join(str(n) for n in numery)
        embed.add_field(name="📄 **Posiadane karty (numery)**", value=nums, inline=False)
    if owned == total_cards and total_cards > 0:
        embed.add_field(name="🎉 Ukończono master set!", value="Masz wszystkie karty z tego setu!", inline=False)
    return embed

class CardRevealView(View):
    def __init__(self, cards, user_id, set_id, set_logo_url=None):
        super().__init__(timeout=120)
        self.cards = cards
        self.index = 0
        self.summaries = []
        self.user_id = str(user_id)
        self.set_id = set_id
        self.set_logo_url = set_logo_url

    async def interaction_check(self, interaction):
        return str(interaction.user.id) == self.user_id

    async def show_card(self, interaction, first=False):
        card = self.cards[self.index]
        rarity = card.get("rarity", "Unknown")
        rarity_colors = {"Common": 0xAAAAAA, "Uncommon": 0x1E90FF, "Rare": 0xFFD700}
        rarity_emojis = {"Common": "⚪", "Uncommon": "🔵", "Rare": "⭐"}
        emoji = rarity_emojis.get(rarity, "❔")
        embed = discord.Embed(
            title=f"{self.index + 1}. {card['name']}",
            description=f"{emoji} Rzadkość: **{rarity}**",
            color=rarity_colors.get(rarity, 0xFFFFFF)
        )
        embed.set_image(url=card["images"]["large"])
        embed.set_footer(text=f"Karta {self.index + 1} z {len(self.cards)}")
        if self.set_logo_url:
            embed.set_thumbnail(url=self.set_logo_url)
        price = None
        if "tcgplayer" in card and "prices" in card["tcgplayer"]:
            prices = card["tcgplayer"]["prices"]
            for ver in prices.values():
                if "market" in ver and ver["market"]:
                    price = ver["market"]
                    break
        if price:
            embed.add_field(
                name="Wartość rynkowa",
                value=f"{price:.2f} USD ({usd_to_bc(price)} BC {COIN_EMOJI})",
                inline=True
            )
        else:
            embed.add_field(name="Wartość rynkowa", value="Brak danych", inline=True)
        self.summaries.append(f"{emoji} {card['name']} ({rarity})")
        self.clear_items()
        if self.index < len(self.cards) - 1:
            self.add_item(self.NextCardButton(self))
        else:
            self.add_item(self.SummaryButton(self))
        if first or interaction.response.is_done():
            await interaction.edit_original_response(embed=embed, view=self, attachments=[])
        else:
            await interaction.response.edit_message(embed=embed, view=self, attachments=[])

    class NextCardButton(Button):
        def __init__(self, parent):
            super().__init__(label="➡️ Następna karta", style=discord.ButtonStyle.primary)
            self.parent = parent

        async def callback(self, interaction: discord.Interaction):
            back = discord.Embed()
            back.set_image(url=CARD_BACK_URL)
            await interaction.response.edit_message(embed=back, view=self.parent, attachments=[])
            await asyncio.sleep(0.7)
            self.parent.index += 1
            await self.parent.show_card(interaction, first=False)

    class SummaryButton(Button):
        def __init__(self, parent):
            super().__init__(label="Podsumowanie", style=discord.ButtonStyle.success)
            self.parent = parent

        async def callback(self, interaction: discord.Interaction):
            users = load_users()
            uid = str(self.parent.user_id)
            if uid in users:
                ensure_user_fields(users[uid])
                max_price = 0
                max_name = ""
                for card in self.parent.cards:
                    price = None
                    if "tcgplayer" in card and "prices" in card["tcgplayer"]:
                        for ver in card["tcgplayer"]["prices"].values():
                            if "market" in ver and ver["market"]:
                                price = ver["market"]
                                break
                    img_url = ""
                    if "images" in card:
                        img_url = card["images"].get("small") or card["images"].get("large") or ""
                    users[uid]["cards"].append({
                        "id": card["id"],
                        "name": card["name"],
                        "price_usd": price or 0,
                        "img_url": img_url,
                        "rarity": card.get("rarity", "")
                    })
                    if price and price > max_price:
                        max_price = price
                        max_name = card["name"]
                update_weekly_best(users[uid], max_price, max_name)
                all_sets = get_all_sets()
                if check_master_set(users[uid], self.parent.set_id, all_sets):
                    new_codes.append(f"master:{self.parent.set_id}")
                users[uid]["boosters_opened"] = users[uid].get("boosters_opened", 0) + 1
                opened = users[uid]["boosters_opened"]
                ach_list = users[uid].setdefault("achievements", [])
                new_codes = []
                if opened >= 1 and grant_achievement(users[uid], "first_booster"):
                    new_codes.append("first_booster")
                if opened >= 5 and grant_achievement(users[uid], "open_5_boosters"):
                    new_codes.append("open_5_boosters")
                if opened >= 25 and grant_achievement(users[uid], "open_25_boosters"):
                    new_codes.append("open_25_boosters")
                if opened >= 100 and grant_achievement(users[uid], "open_100_boosters"):
                    new_codes.append("open_100_boosters")
                if opened >= 500 and grant_achievement(users[uid], "open_500_boosters"):
                    new_codes.append("open_500_boosters")
                total_cards = len(users[uid]["cards"])
                if total_cards >= 1 and grant_achievement(users[uid], "first_card"):
                    new_codes.append("first_card")
                if total_cards >= 50 and grant_achievement(users[uid], "cards_50"):
                    new_codes.append("cards_50")
                if total_cards >= 250 and grant_achievement(users[uid], "cards_250"):
                    new_codes.append("cards_250")
                if total_cards >= 1000 and grant_achievement(users[uid], "cards_1000"):
                    new_codes.append("cards_1000")

                # Rzadkie karty
                rare_ids = {c["id"] for c in users[uid]["cards"] if c.get("rarity") == "Rare"}
                if len(rare_ids) >= 1 and grant_achievement(users[uid], "first_rare"):
                    new_codes.append("first_rare")
                if len(rare_ids) >= 10 and grant_achievement(users[uid], "rare_10"):
                    new_codes.append("rare_10")
                if len(rare_ids) >= 50 and grant_achievement(users[uid], "rare_50"):
                    new_codes.append("rare_50")

                counts = Counter(c["id"] for c in users[uid]["cards"])
                if any(v >= 2 for v in counts.values()) and grant_achievement(users[uid], "first_duplicate"):
                    new_codes.append("first_duplicate")
                if any(v >= 10 for v in counts.values()) and grant_achievement(users[uid], "duplicate_10"):
                    new_codes.append("duplicate_10")
                if len([v for v in counts.values() if v >= 2]) >= 20 and grant_achievement(users[uid], "duplicates_20_cards"):
                    new_codes.append("duplicates_20_cards")

                set_ids = {c["id"].split("-")[0] for c in users[uid]["cards"]}
                if len(set_ids) >= 1 and grant_achievement(users[uid], "first_set"):
                    new_codes.append("first_set")
                if len(set_ids) >= 5 and grant_achievement(users[uid], "sets_5"):
                    new_codes.append("sets_5")
                if len(set_ids) >= 10 and grant_achievement(users[uid], "sets_10"):
                    new_codes.append("sets_10")
                if len(set_ids) == len(all_sets) and grant_achievement(users[uid], "sets_all"):
                    new_codes.append("sets_all")

                if check_for_all_achievements(users[uid]) and grant_achievement(users[uid], "all_achievements"):
                    new_codes.append("all_achievements")

                save_users(users)
                for code in new_codes:
                    await send_achievement_message(interaction, code)
                drop_channel = None
                if hasattr(interaction, "guild") and interaction.guild:
                    drop_channel = interaction.guild.get_channel(DROP_CHANNEL_ID)
                for card in self.parent.cards:
                    rarity = card.get("rarity", "")
                    price = None
                    if "tcgplayer" in card and "prices" in card["tcgplayer"]:
                        for ver in card["tcgplayer"]["prices"].values():
                            if "market" in ver and ver["market"]:
                                price = ver["market"]
                                break
                    price_bc = usd_to_bc(price or 0)
                    if drop_channel and rarity in RAREST_TYPES:
                        embed = discord.Embed(
                            title="🔥 WYJĄTKOWY DROP!",
                            description=(
                                f"{interaction.user.mention} trafił/a **{card['name']}**\n"
                                f"`{card.get('set', {}).get('ptcgoCode', '-')}` | #{card.get('number', '-') }\n"
                                f"Rzadkość: {card.get('rarity', 'Unknown')}\n"
                                f"Wartość: **{price_bc} BC {COIN_EMOJI}**"
                            ),
                            color=discord.Color.gold(),
                        )
                        if "images" in card and "large" in card["images"]:
                            embed.set_image(url=card["images"]["large"])
                        await drop_channel.send(embed=embed)
                summary = "\n".join(self.parent.summaries)
                total_usd = 0
                for card in self.parent.cards:
                    price = None
                    if "tcgplayer" in card and "prices" in card["tcgplayer"]:
                        for ver in card["tcgplayer"]["prices"].values():
                            if "market" in ver and ver["market"]:
                                price = ver["market"]
                                break
                    if price:
                        total_usd += price
                total_bc = usd_to_bc(total_usd)
                podsumowanie = (
                    f"💰 **Suma wartości boostera:** {total_usd:.2f} USD ({total_bc} BC {COIN_EMOJI})"
                )
                class AfterBoosterView(View):
                    @discord.ui.button(label="Przejdź do kolekcji", style=discord.ButtonStyle.primary)
                    async def to_collection(self, i: discord.Interaction, button: Button):
                        users = load_users()
                        user = users[str(i.user.id)]
                        all_sets = get_all_sets()
                        boosters_counter = Counter(user["boosters"])
                        view = CollectionMainView(user, boosters_counter, all_sets)
                        embed = await view.build_summary_embed()
                        file = discord.File(GRAPHIC_DIR / "kolekcja.png", filename="kolekcja.png")
                        await i.response.send_message(embed=embed, view=view, ephemeral=True, file=file)
                await interaction.response.edit_message(
                    content=(
                        f"{random.choice(FUN_EMOJIS)} Koniec boostera! Oto Twoje karty:\n"
                        f"```{summary}```\n"
                        f"{podsumowanie}"
                    ),
                    embed=None,
                    view=AfterBoosterView(),
                )


class AchievementsView(View):
    def __init__(self, embeds, user_id):
        super().__init__(timeout=120)
        self.embeds = embeds
        self.index = 0
        self.user_id = str(user_id)
        if len(embeds) > 1:
            self.add_item(self.PrevButton(self))
            self.add_item(self.NextButton(self))

    async def interaction_check(self, interaction: discord.Interaction):
        return str(interaction.user.id) == self.user_id

    class PrevButton(Button):
        def __init__(self, parent):
            super().__init__(label="⬅️", style=discord.ButtonStyle.secondary)
            self.parent = parent

        async def callback(self, interaction: discord.Interaction):
            if self.parent.index > 0:
                self.parent.index -= 1
            await interaction.response.edit_message(embed=self.parent.embeds[self.parent.index], view=self.parent)

    class NextButton(Button):
        def __init__(self, parent):
            super().__init__(label="➡️", style=discord.ButtonStyle.secondary)
            self.parent = parent

        async def callback(self, interaction: discord.Interaction):
            if self.parent.index < len(self.parent.embeds) - 1:
                self.parent.index += 1
            await interaction.response.edit_message(embed=self.parent.embeds[self.parent.index], view=self.parent)

# --- KOMENDA START ---
@client.tree.command(name="start", description="Utwórz konto w grze")
async def start_cmd(interaction: discord.Interaction):
    users = load_users()
    uid = str(interaction.user.id)
    if uid in users:
        await interaction.response.send_message("Masz już konto!", ephemeral=True)
        return
    users[uid] = {
        "username": interaction.user.name,
        "boosters": [],
        "cards": [],
        "rare_boost": 0,
        "double_daily_until": 0,
        "streak_freeze": 0,
        "boosters_opened": 0,
        "money": START_MONEY,
        "last_daily": 0,
        "daily_streak": 0,
        "weekly_best": {"week": 0, "year": 0, "price": 0},
        "achievements": [],
        "created_at": int(datetime.datetime.now(datetime.UTC).timestamp()),
    }
    users[uid]["achievements"].append("account_created")
    users[uid]["money"] += ACHIEVEMENT_REWARDS.get("account_created", 0)
    save_users(users)
    welcome = (
        "**Witaj w Pok\xe9 Booster Bot!**\n"
        "Zbieraj karty Pok\xe9mon, kupuj boostery w komendzie `/sklep` i odbieraj codzienne monety przy pomocy `/daily`.\n"
        "Otw\xf3rz je komend\u0105 `/otworz` i sprawdzaj kolekcj\u0119 przez `/kolekcja`.\n"
        "Po wi\u0119cej informacji u\x17yj `/help`.\n\n"
        f"✅ Utworzono konto! Otrzymujesz {START_MONEY} BC {COIN_EMOJI}"
    )
    await interaction.response.send_message(welcome, ephemeral=True)
    await send_achievement_message(interaction, "account_created")
    try:
        await interaction.channel.send(
            f"🎉 {interaction.user.mention} dołączył do gry! Witamy!"
        )
    except Exception:
        pass

# --- KOMENDA Otwórz ---
@client.tree.command(name="otworz", description="Otwórz booster i zobacz karty jedna po drugiej!")
async def otworz(interaction: discord.Interaction):
    user_id = str(interaction.user.id)
    users = load_users()
    if user_id not in users or not users[user_id]["boosters"]:
        await interaction.response.send_message("❌ Nie masz boosterów do otwarcia! Odwiedź `/sklep`.", ephemeral=True)
        return
    ensure_user_fields(users[user_id])
    all_sets = get_all_sets()
    id_to_name = {s['id']: s['name'] for s in all_sets}
    booster_counts = Counter(users[user_id]["boosters"])
    if len(booster_counts) > 1:
        options = [
            discord.SelectOption(label=f"{id_to_name.get(booster_id, booster_id)} x{count}", value=booster_id)
            for booster_id, count in booster_counts.items()
        ]
        class BoosterSelectView(View):
            @select(placeholder="Wybierz booster do otwarcia", options=options)
            async def select_callback(self, i2: discord.Interaction, menu_booster: discord.ui.Select):
                chosen = menu_booster.values[0]
                users[user_id]["boosters"].remove(chosen)
                save_users(users)
                await i2.response.defer()
                await open_booster(i2, chosen)
        await interaction.response.send_message("🃏 Wybierz booster do otwarcia:", view=BoosterSelectView(), ephemeral=True)
    else:
        chosen = users[user_id]["boosters"].pop(0)
        save_users(users)
        await interaction.response.defer()
        await open_booster(interaction, chosen)

# --- FUNKCJA Otwierania boostera (z logo setu) ---
async def open_booster(interaction, set_id):
    cards = await fetch_cards_from_set(set_id, user_id=str(interaction.user.id))
    if not cards:
        await interaction.edit_original_response(content="⚠️ Nie udało się pobrać kart z boostera!", embed=None, view=None)
        return

    all_sets = get_all_sets()
    set_data = next((s for s in all_sets if s["id"] == set_id), None)
    logo_url = set_data["images"]["logo"] if set_data and "images" in set_data and "logo" in set_data["images"] else None

    view = CardRevealView(
        cards,
        user_id=str(interaction.user.id),
        set_id=set_id,
        set_logo_url=logo_url,
    )

    # Interaction is already deferred before calling this function, so we can
    # always edit the original response to show the first card.
    await view.show_card(interaction, first=True)

# --- KOMENDA KOLEKCJA (z paginacją, przyciski) ---
@client.tree.command(name="kolekcja", description="Twoja kolekcja, boosterki i karty z setów!")
async def kolekcja(interaction: discord.Interaction):
    user_id = str(interaction.user.id)
    users = load_users()
    all_sets = get_all_sets()
    if user_id not in users:
        await interaction.response.send_message("📭 Nie masz konta. Użyj `/start`.", ephemeral=True)
        return
    user = ensure_user_fields(users[user_id])
    boosters_counter = Counter(user["boosters"])
    view = CollectionMainView(user, boosters_counter, all_sets)
    embed = await view.build_summary_embed()
    file = discord.File(GRAPHIC_DIR / "kolekcja.png", filename="kolekcja.png")
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True, file=file)

# --- KOMENDA SALDO ---
@client.tree.command(name="saldo", description="Sprawdź ilość posiadanych monet")
async def saldo(interaction: discord.Interaction):
    users = load_users()
    uid = str(interaction.user.id)
    if uid in users:
        ensure_user_fields(users[uid])
    if uid not in users:
        await interaction.response.send_message("📭 Nie masz konta. Użyj `/start`.", ephemeral=True)
        return
    money = users[uid].get("money", 0)
    await interaction.response.send_message(
        f"💰 Twoje saldo: {money} BC {COIN_EMOJI}", ephemeral=True
    )

# --- KOMENDA DAILY ---
@client.tree.command(name="daily", description="Odbierz dzienną nagrodę monet")
async def daily(interaction: discord.Interaction):
    users = load_users()
    uid = str(interaction.user.id)
    if uid not in users:
        await interaction.response.send_message("📭 Nie masz konta. Użyj `/start`.", ephemeral=True)
        return
    ensure_user_fields(users[uid])
    now = datetime.datetime.now(datetime.UTC).timestamp()
    last = users[uid].get("last_daily", 0)
    if now - last < DAILY_COOLDOWN:
        remaining = int(DAILY_COOLDOWN - (now - last))
        h = remaining // 3600
        m = (remaining % 3600) // 60
        s = remaining % 60
        await interaction.response.send_message(
            f"⌛ Nagrodę możesz odebrać za {h}h {m}m {s}s.", ephemeral=True
        )
        return
    # Aktualizacja serii dziennych nagród
    streak = users[uid].get("daily_streak", 0)
    if now - last <= DAILY_COOLDOWN * 1.5 and last != 0:
        streak += 1
    else:
        if last != 0 and users[uid].get("streak_freeze", 0) > 0:
            users[uid]["streak_freeze"] -= 1
            streak += 1
        else:
            streak = 1
    users[uid]["daily_streak"] = streak
    new_codes = []
    if streak >= 10 and grant_achievement(users[uid], "daily_10"):
        new_codes.append("daily_10")
    if streak >= 30 and grant_achievement(users[uid], "daily_30"):
        new_codes.append("daily_30")
    amount = DAILY_AMOUNT
    if users[uid].get("double_daily_until", 0) > now:
        amount *= 2
    bonus = 0
    if streak % 7 == 0:
        bonus = STREAK_BONUS * (streak // 7)
    total_gain = amount + bonus
    users[uid]["money"] = users[uid].get("money", 0) + total_gain
    users[uid]["last_daily"] = now
    if check_for_all_achievements(users[uid]) and grant_achievement(users[uid], "all_achievements"):
        new_codes.append("all_achievements")
    save_users(users)
    for code in new_codes:
        await send_achievement_message(interaction, code)
    emj = random.choice(FUN_EMOJIS)
    day = (streak - 1) % 7 + 1
    msg = f"{emj} Otrzymujesz {amount} BC {COIN_EMOJI}! (dzień {day}/7)"
    if bonus:
        msg += f" 🎊 Premia {bonus} BC"
    await interaction.response.send_message(msg, ephemeral=True)


# --- KOMENDA SKLEP ---
@client.tree.command(name="sklep", description="Wyświetl sklep i zarządzaj koszykiem")
async def sklep(interaction: discord.Interaction):
    users = load_users()
    uid = str(interaction.user.id)
    if uid not in users:
        await interaction.response.send_message("📭 Nie masz konta. Użyj `/start`.", ephemeral=True)
        return
    ensure_user_fields(users[uid])
    embed = build_shop_embed(uid)
    view = ShopView(uid)
    file1 = discord.File(SHOP_IMAGE_PATH, filename="shop.png")
    file2 = discord.File(COIN_IMAGE_PATH, filename="coin.png")
    await interaction.response.send_message(embed=embed, view=view, files=[file1, file2], ephemeral=True)
    view.message = await interaction.original_response()

# --- KOMENDA OSIAGNIĘCIA ---
@client.tree.command(name="osiagniecia", description="Wyświetl swoje osiągnięcia")
async def achievements_cmd(interaction: discord.Interaction):
    users = load_users()
    uid = str(interaction.user.id)
    if uid not in users:
        await interaction.response.send_message("📭 Nie masz konta. Użyj `/start`.", ephemeral=True)
        return
    user = ensure_user_fields(users[uid])
    all_sets = get_all_sets()

    pages = build_achievement_pages(user, all_sets)
    view = AchievementsView(pages, uid)
    await interaction.response.send_message(embed=pages[0], view=view, ephemeral=True)
    view.message = await interaction.original_response()

# --- KOMENDA RANKING ---
@client.tree.command(name="ranking", description="Najlepsze dropy tygodnia")
async def ranking_cmd(interaction: discord.Interaction):
    users = load_users()
    week, year = current_week_info()
    entries = []
    for uid, udata in users.items():
        ensure_user_fields(udata)
        best = udata.get("weekly_best")
        if best and best.get("week") == week and best.get("year") == year:
            entries.append((uid, best.get("price", 0), best.get("name", "")))
    top3 = sorted(entries, key=lambda x: x[1], reverse=True)[:3]
    lines = [
        f"{idx+1}. <@{uid}> - {name} ({usd_to_bc(price)} BC {COIN_EMOJI})"
        for idx, (uid, price, name) in enumerate(top3)
    ]
    if not lines:
        lines = ["Brak danych"]
    embed = discord.Embed(title="TOP 3 dropy tygodnia", description="\n".join(lines), color=discord.Color.purple())
    await interaction.response.send_message(embed=embed, ephemeral=True)
    changed = False
    notify = []
    for uid,_ in top3:
        ensure_user_fields(users[uid])
        if grant_achievement(users[uid], "top3_week"):
            notify.append(uid)
            changed = True
        if check_for_all_achievements(users[uid]) and grant_achievement(users[uid], "all_achievements"):
            notify.append(uid)
            changed = True
    if changed:
        save_users(users)
        for nuid in notify:
            user_obj = interaction.client.get_user(int(nuid))
            if user_obj:
                for code in ("top3_week", "all_achievements"):
                    if code in users[nuid]["achievements"]:
                        await send_achievement_message(user_obj, code)

# --- KOMENDA HELP ---
@client.tree.command(name="help", description="Lista komend bota")
async def help_cmd(interaction: discord.Interaction):
    commands = [
        ("/start", "Załóż konto i odbierz startowe monety"),
        ("/saldo", "Sprawdź ilość posiadanych monet"),
        ("/daily", "Codzienna nagroda pieniędzy"),
        ("/sklep", "Przeglądaj sklep z boosterami"),
        ("/kolekcja", "Twoja kolekcja kart"),
        ("/otworz", "Otwórz posiadane boostery"),
        ("/osiagniecia", "Lista zdobytych osiągnięć"),
        ("/ranking", "Najlepsze dropy tygodnia"),
    ]
    desc = "\n".join(f"**{cmd}** — {txt}" for cmd, txt in commands)
    embed = discord.Embed(title="Dostępne komendy", description=desc, color=EMBED_COLOR)
    await interaction.response.send_message(embed=embed, ephemeral=True)

# --- KOMENDA GIVEAWAY ---
@client.tree.command(name="giveaway", description="Utwórz nowe losowanie boosterów")
async def giveaway_command(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("🚫 Tylko administrator może tworzyć giveaway!", ephemeral=True)
        return
    await interaction.response.send_modal(GiveawayModal())

# --- Integracja StartIT booster + boost ---
@client.event
async def on_message(message):
    if message.author.id != STARTIT_BOT_ID:
        return
    if "kupił booster" in message.content:
        users = load_users()
        parts = message.content.split("kupił booster")
        if len(parts) != 2:
            return
        username = parts[0].strip()
        match = re.search(r"([A-Z0-9]+)", parts[1].strip(), re.IGNORECASE)
        if not match:
            return
        ptcgo_code = match.group(1).upper()
        set_id, set_name = get_set_id_by_ptcgo_code(ptcgo_code)
        if not set_id:
            await message.channel.send(f"⚠️ Nieznany booster `{ptcgo_code}` – nie został dodany do kolekcji.")
            return
        found_user = None
        for uid, data in users.items():
            if username.lower() in data["username"].lower():
                found_user = (uid, data)
                break
        if found_user:
            user_id, _ = found_user
            ensure_user_fields(users[user_id])
            users[user_id]["boosters"].append(set_id)
            save_users(users)
            class BoosterButtonsView(View):
                @discord.ui.button(label="Otwórz booster", style=discord.ButtonStyle.success)
                async def otworz(self, interaction: discord.Interaction, button: Button):
                    if str(interaction.user.id) != user_id:
                        await interaction.response.send_message("To nie jest Twój booster!", ephemeral=True)
                        return
                    users = load_users()
                    if set_id in users[user_id]["boosters"]:
                        users[user_id]["boosters"].remove(set_id)
                        save_users(users)
                        await interaction.response.defer(thinking=True, ephemeral=True)
                        await open_booster(interaction, set_id)
                    else:
                        await interaction.response.send_message("Nie znaleziono boostera do otwarcia.", ephemeral=True)
                @discord.ui.button(label="Pokaż boostery", style=discord.ButtonStyle.primary)
                async def pokaz(self, interaction: discord.Interaction, button: Button):
                    all_sets = get_all_sets()
                    user = users[user_id]
                    boosters_counter = Counter(user["boosters"])
                    view = CollectionMainView(user, boosters_counter, all_sets)
                    embed = await view.build_summary_embed()
                    file = discord.File(GRAPHIC_DIR / "kolekcja.png", filename="kolekcja.png")
                    await interaction.response.send_message(embed=embed, view=view, ephemeral=True, file=file)
            await message.channel.send(
                f"✅ Booster `{set_name}` został przydzielony do kolekcji użytkownika **{username}**!",
                view=BoosterButtonsView()
            )
        return
    if "kupił boost" in message.content or "kupił lucky boost" in message.content:
        users = load_users()
        if "kupił boost" in message.content:
            username = message.content.split("kupił boost")[0].strip()
        else:
            username = message.content.split("kupił lucky boost")[0].strip()
        found_user = None
        for uid, data in users.items():
            if username.lower() in data["username"].lower():
                found_user = (uid, data)
                break
        if found_user:
            user_id, _ = found_user
            ensure_user_fields(users[user_id])
            users[user_id]["rare_boost"] = users[user_id].get("rare_boost", 0) + 1
            save_users(users)
            await message.channel.send(
                f"🟣 Boost rare został dodany do konta użytkownika **{username}**!\n"
                f"Aktywuje się automatycznie przy następnym otwieraniu boostera."
            )

# --- LOSOWANIE KART ---
def get_set_id_by_ptcgo_code(ptcgo_code):
    sets = get_all_sets()
    for s in sets:
        if s.get("ptcgoCode", "").upper() == ptcgo_code.upper():
            return s["id"], s["name"]
    return None, None

RARITY_POOL = [
    ("Common", 6, 1.00),
    ("Uncommon", 3, 1.00),
    ("Rare", 1, 0.75),
    ("Double Rare", 1, 0.25),
    ("Ultra Rare", 1, 0.12),
    ("Illustration Rare", 1, 0.07),
    ("Special Illustration Rare", 1, 0.02),
    ("Hyper Rare", 1, 0.01),
]
RAREST_TYPES = ["Ultra Rare", "Illustration Rare", "Special Illustration Rare", "Hyper Rare"]

async def fetch_cards_from_set(set_id: str, user_id: str = None):
    headers = {"X-Api-Key": POKETCG_API_KEY}
    users = load_users()
    boost_active = False
    if user_id and user_id in users:
        ensure_user_fields(users[user_id])
        if users[user_id].get("rare_boost", 0) > 0:
            boost_active = True
            users[user_id]["rare_boost"] -= 1
            save_users(users)
    result = []
    async with aiohttp.ClientSession(headers=headers) as session:
        async def get_cards_by_rarity(rarity, count):
            set_cache = CARD_CACHE.setdefault(set_id, {})
            if rarity not in set_cache:
                url = (
                    f"https://api.pokemontcg.io/v2/cards?q=set.id:{set_id} AND rarity:\"{rarity}\""
                )
                async with session.get(url) as resp:
                    data = await resp.json()
                    set_cache[rarity] = data.get("data", [])
                    save_card_cache()
            found = set_cache.get(rarity, [])
            return random.sample(found, min(count, len(found)))

        result += await get_cards_by_rarity("Common", 4)
        result += await get_cards_by_rarity("Uncommon", 3)
        rare_pools = [
            ("Ultra Rare", 0.12),
            ("Double Rare", 0.25),
            ("Rare", 0.75),
        ]
        for _ in range(2):
            got_card = False
            for rarity, base_prob in rare_pools:
                prob = min(1.0, base_prob * 2) if boost_active else base_prob
                if random.random() < prob:
                    card = await get_cards_by_rarity(rarity, 1)
                    if card:
                        result += card
                        got_card = True
                        break
            if not got_card:
                card = await get_cards_by_rarity("Common", 1)
                if card:
                    result += card
        ir_slots = [
            ("Hyper Rare", 0.01),
            ("Special Illustration Rare", 0.02),
            ("Illustration Rare", 0.07)
        ]
        got_card = False
        for rarity, base_prob in ir_slots:
            prob = min(1.0, base_prob * 2) if boost_active else base_prob
            if random.random() < prob:
                card = await get_cards_by_rarity(rarity, 1)
                if card:
                    result += card
                    got_card = True
                    break
        if not got_card:
            card = await get_cards_by_rarity("Common", 1)
            if card:
                result += card
    commons = [c for c in result if c.get("rarity") in ["Common", "Uncommon"]]
    rares = [c for c in result if c.get("rarity") not in ["Common", "Uncommon"]]
    random.shuffle(commons)
    cards_result = commons + rares
    unique = []
    seen = set()
    for card in cards_result:
        cid = card.get("id")
        if cid not in seen:
            unique.append(card)
            seen.add(cid)
    return unique[:10]

client.run(os.environ["BOT_TOKEN"])
