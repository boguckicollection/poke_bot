import discord
from discord import app_commands
from discord.ui import View, Button, Modal, TextInput, select, Select
from giveaway import GiveawayModal, GiveawayView, parse_time_string
from utils import load_users, save_users, get_all_sets, ensure_user_fields
import os
import json
import aiohttp
import random
from collections import Counter
import asyncio
import re
from dotenv import load_dotenv
import datetime

USD_PLN = 4.00
def usd_to_pln(usd):
    return usd * USD_PLN if usd else 0

# --- parametry ekonomii ---
START_MONEY = 100
BOOSTER_PRICE = 100
DAILY_AMOUNT = 50
DAILY_COOLDOWN = 24 * 3600

load_dotenv()

USERS_FILE = "users.json"
SETS_FILE = "sets.json"
DISCORD_TOKEN = os.environ["BOT_TOKEN"]
POKETCG_API_KEY = os.environ["POKETCG_API_KEY"]
DROP_CHANNEL_ID = 1374695570182246440
STARTIT_BOT_ID = 572906387382861835
# Kanał do ogłaszania aktualizacji sklepu
SHOP_CHANNEL_ID = DROP_CHANNEL_ID

# Przedmioty dostępne w sklepie
ITEMS = {
    "rare_boost": {"name": "Rare Boost", "price": 200},
}

# Grafika tyłu karty używana w animacji odsłaniania
CARD_BACK_URL = "https://m.media-amazon.com/images/I/61vOBvbsYJL._AC_UF1000,1000_QL80_DpWeblab_.jpg"

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

def compute_cart_total(cart):
    total = sum(q * BOOSTER_PRICE for q in cart.get("boosters", {}).values())
    total += sum(q * ITEMS[i]["price"] for i, q in cart.get("items", {}).items())
    return total

def current_week_info():
    now = datetime.datetime.utcnow()
    week = now.isocalendar()[1]
    year = now.isocalendar()[0]
    return week, year

def update_weekly_best(user, price):
    week, year = current_week_info()
    best = user.get("weekly_best", {})
    if best.get("week") != week or best.get("year") != year or price > best.get("price", 0):
        user["weekly_best"] = {"week": week, "year": year, "price": price}

def check_master_set(user, set_id, all_sets):
    set_info = next((s for s in all_sets if s["id"] == set_id), None)
    if not set_info:
        return False
    total = set_info.get("total", 0)
    owned = len({c["id"] for c in user["cards"] if c["id"].startswith(set_id)})
    if total > 0 and owned >= total:
        ach = f"master:{set_id}"
        if ach not in user.setdefault("achievements", []):
            user["achievements"].append(ach)
            return True
    return False

def build_shop_embed(user_id):
    sets = get_all_sets()
    embed = discord.Embed(title="Sklep", color=discord.Color.gold())
    boosters_desc = []
    for s in sets[:10]:
        boosters_desc.append(f"`{s['ptcgoCode']}` {s['name']} - {BOOSTER_PRICE} monet")
    embed.add_field(name="Boostery", value="\n".join(boosters_desc) or "Brak", inline=False)
    items_desc = [f"{info['name']} - {info['price']} monet" for info in ITEMS.values()]
    embed.add_field(name="Itemy", value="\n".join(items_desc) or "Brak", inline=False)
    cart = carts.get(user_id)
    if cart and (cart.get("boosters") or cart.get("items")):
        lines = []
        for sid, q in cart.get("boosters", {}).items():
            name = next((s['name'] for s in sets if s['id']==sid), sid)
            lines.append(f"{name} x{q}")
        for iid, q in cart.get("items", {}).items():
            lines.append(f"{ITEMS[iid]['name']} x{q}")
        total = compute_cart_total(cart)
        lines.append(f"**Razem: {total} monet**")
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

class ShopView(View):
    def __init__(self, user_id):
        super().__init__(timeout=180)
        self.user_id = str(user_id)
        self.message = None
        self.add_item(self.AddBoosterButton(self))
        self.add_item(self.AddItemButton(self))
        self.add_item(self.FinalizeButton(self))
        self.add_item(self.ClearButton(self))

    async def interaction_check(self, interaction: discord.Interaction):
        return str(interaction.user.id) == self.user_id

    async def update(self):
        if self.message:
            embed = build_shop_embed(self.user_id)
            await self.message.edit(embed=embed, view=self)

    class AddBoosterButton(Button):
        def __init__(self, parent):
            super().__init__(label="Dodaj booster", style=discord.ButtonStyle.primary)
            self.parent = parent

        async def callback(self, interaction: discord.Interaction):
            sets = get_all_sets()
            options = [discord.SelectOption(label=s['name'], value=s['id']) for s in sets[:25]]

            class BoosterSelectView(View):
                def __init__(self, parent):
                    super().__init__(timeout=60)
                    self.parent = parent

                @select(placeholder="Wybierz booster", options=options)
                async def select_cb(self, i2: discord.Interaction, select: discord.ui.Select):
                    set_id = select.values[0]
                    set_name = next((s['name'] for s in sets if s['id']==set_id), set_id)

                    async def after_qty(i3, qty):
                        cart = carts.setdefault(self.parent.parent.user_id, {"boosters": {}, "items": {}})
                        cart['boosters'][set_id] = cart['boosters'].get(set_id, 0) + qty
                        await i3.response.send_message(f"Dodano {qty}x {set_name}", ephemeral=True)
                        await self.parent.parent.update()

                    modal = QuantityModal(after_qty)
                    await i2.response.send_modal(modal)

            await interaction.response.send_message(view=BoosterSelectView(self), ephemeral=True)

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
                async def select_cb(self, i2: discord.Interaction, select: discord.ui.Select):
                    item_id = select.values[0]
                    item_name = ITEMS[item_id]['name']

                    async def after_qty(i3, qty):
                        cart = carts.setdefault(self.parent.parent.user_id, {"boosters": {}, "items": {}})
                        cart['items'][item_id] = cart['items'].get(item_id, 0) + qty
                        await i3.response.send_message(f"Dodano {qty}x {item_name}", ephemeral=True)
                        await self.parent.parent.update()

                    modal = QuantityModal(after_qty)
                    await i2.response.send_modal(modal)

            await interaction.response.send_message(view=ItemSelectView(self), ephemeral=True)

    class FinalizeButton(Button):
        def __init__(self, parent):
            super().__init__(label="Kup", style=discord.ButtonStyle.success)
            self.parent = parent

        async def callback(self, interaction: discord.Interaction):
            users = load_users()
            uid = self.parent.user_id
            if uid not in users:
                await interaction.response.send_message("📭 Nie masz konta.", ephemeral=True)
                return
            ensure_user_fields(users[uid])
            cart = carts.get(uid)
            if not cart or (not cart.get('boosters') and not cart.get('items')):
                await interaction.response.send_message("Koszyk jest pusty", ephemeral=True)
                return
            total = compute_cart_total(cart)
            if users[uid].get('money', 0) < total:
                await interaction.response.send_message("❌ Za mało monet", ephemeral=True)
                return
            users[uid]['money'] -= total
            for sid, q in cart.get('boosters', {}).items():
                users[uid]['boosters'].extend([sid]*q)
            for iid, q in cart.get('items', {}).items():
                if iid == 'rare_boost':
                    users[uid]['rare_boost'] = users[uid].get('rare_boost', 0) + q
            save_users(users)
            carts.pop(uid, None)
            await self.parent.update()
            await interaction.response.send_message(f"✅ Zakupiono za {total} monet", ephemeral=True)

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
        self.loop.create_task(self.shop_update_loop())
        print(f"✅ Zalogowano jako {self.user} (ID: {self.user.id})")

    async def shop_update_loop(self):
        await self.wait_until_ready()
        while not self.is_closed():
            new_sets = await fetch_and_save_sets()
            if new_sets:
                channel = self.get_channel(SHOP_CHANNEL_ID)
                if channel:
                    names = ", ".join(s["name"] for s in new_sets)
                    await channel.send(f"🆕 Nowe sety w sklepie: {names}")
            await asyncio.sleep(24 * 3600)

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

        total_cards = sum(c["count"] if isinstance(c, dict) and "count" in c else 1 for c in user["cards"])
        unique_cards = len(set(c["id"] if isinstance(c, dict) else c for c in user["cards"]))
        total_boosters = sum(boosters_counter.values())
        user = self.user
        boosters_counter = self.boosters_counter
        all_sets = self.all_sets

        total_cards = sum(c["count"] if isinstance(c, dict) and "count" in c else 1 for c in user["cards"])
        unique_cards = len(set(c["id"] if isinstance(c, dict) else c for c in user["cards"]))
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
            color=discord.Color.blurple()
        )
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
                    f"**{usd_to_pln(top5[0][1]):.2f} PLN**"
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
                    f"— **{usd_to_pln(price):.2f} PLN**\n"
                )
            embed.add_field(name="Pozostałe z TOP 5:", value=opis, inline=False)
        hist = user.get("history", [])
        all_total_usd = sum(price * cnt for _, price, cnt in card_values)
        all_total_pln = usd_to_pln(all_total_usd)
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
                f"**{all_total_usd:.2f} USD** / **{all_total_pln:.2f} PLN**\n"
                f"Zmiana od ostatniej aktualizacji: {change}"
            ),
            inline=False
        )
        boost_count = user.get("rare_boost", 0)
        if boost_count > 0:
            embed.add_field(name="Rare Boosty do użycia", value=f"{boost_count} szt.", inline=False)
        money = user.get("money", 0)
        embed.add_field(name="💰 Saldo", value=f"{money} monet", inline=False)
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
                color=discord.Color.teal()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)

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
                        self.add_item(ViewCardsButton(user, sets, selected_set_id))


            class SetDropdownSelect(Select):
                def __init__(self, parent_view, options):
                    super().__init__(placeholder="Wybierz set", options=options)
                    self.parent_view = parent_view

                async def callback(self, interaction: discord.Interaction):
                    set_id = self.values[0]
                    embed = await build_set_embed(self.parent_view.user, self.parent_view.sets, set_id)
                    file = discord.File("sety.png", filename="sety.png")
                    view = SetDropdownView(
                        user=self.parent_view.user,
                        sets=self.parent_view.sets,
                        options=self.parent_view.options,
                        selected_set_id=set_id
                    )
                    view = SetDropdownView(self.user, sets, options)
                    await interaction.response.send_message(embed=embed, view=SetDropdownView(self.user, sets, options, selected_set_id=set_id), ephemeral=True)




    class BoosterOpenButton(Button):
        def __init__(self, user, boosters_counter, all_sets):
            super().__init__(label="Otwórz boostery", style=discord.ButtonStyle.success)
            self.user = user
            self.boosters_counter = boosters_counter
            self.all_sets = all_sets

        async def callback(self, interaction: discord.Interaction):
            await interaction.response.send_message(
                "Użyj komendy `/otworz`, aby otworzyć booster.",
                ephemeral=True
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
        color=discord.Color.orange()
    )
    if set_obj.get("images", {}).get("logo"):
        embed.set_thumbnail(url=set_obj["images"]["logo"])
    if top5:
        lines = []
        for idx, (cid, name, price, url) in enumerate(top5):
            lines.append(f"{idx+1}. {name} — {usd_to_pln(price):.2f} PLN")
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
                value=f"{price:.2f} USD ({usd_to_pln(price):.2f} PLN)",
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
            if interaction.response.is_done():
                await interaction.edit_original_response(embed=back, view=self.parent, attachments=[])
            else:
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
                        "img_url": img_url
                    })
                    if price and price > max_price:
                        max_price = price
                update_weekly_best(users[uid], max_price)
                all_sets = get_all_sets()
                check_master_set(users[uid], self.parent.set_id, all_sets)
                save_users(users)
                drop_channel = None
                if hasattr(interaction, "guild") and interaction.guild:
                    drop_channel = interaction.guild.get_channel(DROP_CHANNEL_ID)
                for card in self.parent.cards:
                    rarity = card.get("rarity", "").lower()
                    price = None
                    if "tcgplayer" in card and "prices" in card["tcgplayer"]:
                        for ver in card["tcgplayer"]["prices"].values():
                            if "market" in ver and ver["market"]:
                                price = ver["market"]
                                break
                    price_pln = usd_to_pln(price or 0)
                    if drop_channel and (
                        "ultra" in rarity or
                        "secret" in rarity or
                        "special" in rarity or
                        price_pln >= 20
                    ):
                        embed = discord.Embed(
                            title="🔥 WYJĄTKOWY DROP!",
                            description=(
                                f"{interaction.user.mention} trafił/a **{card['name']}**\n"
                                f"`{card.get('set', {}).get('ptcgoCode', '-')}` | #{card.get('number', '-')}\n"
                                f"Rzadkość: {card.get('rarity', 'Unknown')}\n"
                                f"Wartość: **{price_pln:.2f} PLN**"
                            ),
                            color=discord.Color.gold()
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
                total_pln = usd_to_pln(total_usd)
                podsumowanie = (
                    f"💰 **Suma wartości boostera:** {total_usd:.2f} USD ({total_pln:.2f} PLN)"
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
                        await i.response.send_message(embed=embed, view=view, ephemeral=True)
                await interaction.response.edit_message(
                    content=(
                        f"✅ Koniec boostera! Oto Twoje karty:\n"
                        f"```{summary}```\n"
                        f"{podsumowanie}"
                    ),
                    embed=None, view=AfterBoosterView()
                )

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
        "money": START_MONEY,
        "last_daily": 0,
        "daily_streak": 0,
        "weekly_best": {"week": 0, "year": 0, "price": 0},
        "achievements": [],
    }
    save_users(users)
    await interaction.response.send_message(
        f"✅ Utworzono konto! Otrzymujesz {START_MONEY} monet.", ephemeral=True
    )

# --- KOMENDA Otwórz ---
@client.tree.command(name="otworz", description="Otwórz booster i zobacz karty jedna po drugiej!")
async def otworz(interaction: discord.Interaction):
    user_id = str(interaction.user.id)
    users = load_users()
    if user_id not in users or not users[user_id]["boosters"]:
        await interaction.response.send_message("❌ Nie masz boosterów do otwarcia! Użyj `/kup_booster`.", ephemeral=True)
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
            async def select_callback(self, i2: discord.Interaction, select: discord.ui.Select):
                chosen = select.values[0]
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
    view = CardRevealView(cards, user_id=str(interaction.user.id), set_id=set_id, set_logo_url=logo_url)
    if interaction.response.is_done():
        await view.show_card(interaction, first=True)
    else:
        await interaction.response.send_message("🃏 Wybierz booster do otwarcia:", view=BoosterSelectView(), ephemeral=True)

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
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

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
    await interaction.response.send_message(f"💰 Twoje saldo: {money} monet", ephemeral=True)

# --- KOMENDA DAILY ---
@client.tree.command(name="daily", description="Odbierz dzienną nagrodę monet")
async def daily(interaction: discord.Interaction):
    users = load_users()
    uid = str(interaction.user.id)
    if uid not in users:
        await interaction.response.send_message("📭 Nie masz konta. Użyj `/start`.", ephemeral=True)
        return
    ensure_user_fields(users[uid])
    now = datetime.datetime.utcnow().timestamp()
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
        streak = 1
    users[uid]["daily_streak"] = streak
    if streak >= 30 and "daily_30" not in users[uid].get("achievements", []):
        users[uid].setdefault("achievements", []).append("daily_30")
    users[uid]["money"] = users[uid].get("money", 0) + DAILY_AMOUNT
    users[uid]["last_daily"] = now
    save_users(users)
    await interaction.response.send_message(
        f"✅ Otrzymujesz {DAILY_AMOUNT} monet!", ephemeral=True
    )

# --- KOMENDA KUP BOOSTER ---
@client.tree.command(name="kup_booster", description="Kup booster za monety")
@app_commands.describe(kod="Kod PTCGO lub ID zestawu")
async def kup_booster(interaction: discord.Interaction, kod: str):
    users = load_users()
    uid = str(interaction.user.id)
    if uid not in users:
        await interaction.response.send_message("📭 Nie masz konta. Użyj `/start`.", ephemeral=True)
        return
    ensure_user_fields(users[uid])
    sets = get_all_sets()
    target = next((s for s in sets if s.get("id") == kod.lower() or s.get("ptcgoCode", "").lower() == kod.lower()), None)
    if not target:
        await interaction.response.send_message("❌ Nie znaleziono takiego zestawu.", ephemeral=True)
        return
    if users[uid].get("money", 0) < BOOSTER_PRICE:
        await interaction.response.send_message("❌ Nie masz wystarczającej ilości monet.", ephemeral=True)
        return
    users[uid]["money"] -= BOOSTER_PRICE
    users[uid]["boosters"].append(target["id"])
    save_users(users)
    await interaction.response.send_message(
        f"✅ Kupiono booster {target['name']}!", ephemeral=True
    )

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
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
    view.message = await interaction.original_response()

# --- KOMENDA OSIAGNIĘCIA ---
@client.tree.command(name="osiagniecia", description="Wyświetl swoje osiągnięcia")
async def achievements_cmd(interaction: discord.Interaction):
    users = load_users()
    uid = str(interaction.user.id)
    if uid not in users:
        await interaction.response.send_message("📭 Nie masz konta. Użyj `/start`.", ephemeral=True)
        return
    ensure_user_fields(users[uid])
    ach = users[uid].get("achievements", [])
    all_sets = get_all_sets()
    lines = []
    for a in ach:
        if a.startswith("master:"):
            sid = a.split(":",1)[1]
            name = next((s['name'] for s in all_sets if s['id']==sid), sid)
            lines.append(f"🏆 Master set {name}")
        elif a == "daily_30":
            lines.append("⏰ 30-dniowy streak daily")
        elif a == "top3_week":
            lines.append("🥇 TOP 3 drop tygodnia")
    desc = "\n".join(lines) if lines else "Brak osiągnięć"
    embed = discord.Embed(title="Twoje osiągnięcia", description=desc, color=discord.Color.green())
    await interaction.response.send_message(embed=embed, ephemeral=True)

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
            entries.append((uid, best.get("price", 0)))
    top3 = sorted(entries, key=lambda x: x[1], reverse=True)[:3]
    lines = [f"{idx+1}. <@{uid}> - {usd_to_pln(price):.2f} PLN" for idx,(uid,price) in enumerate(top3)]
    if not lines:
        lines = ["Brak danych"]
    embed = discord.Embed(title="TOP 3 dropy tygodnia", description="\n".join(lines), color=discord.Color.purple())
    await interaction.response.send_message(embed=embed, ephemeral=True)
    changed = False
    for uid,_ in top3:
        ensure_user_fields(users[uid])
        if "top3_week" not in users[uid].get("achievements", []):
            users[uid].setdefault("achievements", []).append("top3_week")
            changed = True
    if changed:
        save_users(users)

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
                    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
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
            url = f"https://api.pokemontcg.io/v2/cards?q=set.id:{set_id} AND rarity:\"{rarity}\""
            async with session.get(url) as resp:
                data = await resp.json()
                found = data.get("data", [])
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
    return cards_result[:10]

client.run(os.environ["BOT_TOKEN"])
