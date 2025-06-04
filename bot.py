import discord
from discord import app_commands
from discord.ui import View, Button, Modal, TextInput, select, Select
from giveaway import GiveawayModal, GiveawayView, parse_time_string
from utils import load_users, save_users, get_all_sets
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

load_dotenv()

USERS_FILE = "users.json"
SETS_FILE = "sets.json"
DISCORD_TOKEN = os.environ["BOT_TOKEN"]
POKETCG_API_KEY = os.environ["POKETCG_API_KEY"]
DROP_CHANNEL_ID = 1374695570182246440
STARTIT_BOT_ID = 572906387382861835

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

#def load_users():
#    try:
#        with open(USERS_FILE, "r") as f:
#            return json.load(f)
#    except FileNotFoundError:
#        return {}

#def save_users(data):
#    with open(USERS_FILE, "w") as f:
#        json.dump(data, f, indent=4)

#def get_all_sets():
#    try:
#        with open(SETS_FILE, "r") as f:
#            return json.load(f)
#    except FileNotFoundError:
#        return []

async def fetch_and_save_sets():
    url = "https://api.pokemontcg.io/v2/sets"
    headers = {"X-Api-Key": POKETCG_API_KEY}
    async with aiohttp.ClientSession(headers=headers) as session:
        async with session.get(url) as response:
            if response.status != 200:
                print(f"❌ Błąd pobierania zestawów: {response.status}")
                return
            data = await response.json()
            sets = data.get("data", [])
            filtered_sets = sorted(
                [s for s in sets if s.get("ptcgoCode")],
                key=lambda s: s.get("releaseDate", "2000-01-01"),
                reverse=True
            )
            with open(SETS_FILE, "w") as f:
                json.dump(filtered_sets, f, indent=4)
            print(f"✅ Zapisano {len(filtered_sets)} zestawów do sets.json")

class MyClient(discord.Client):
    def __init__(self):
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def on_ready(self):
        if not hasattr(self, '_synced'):
            await self.tree.sync()
            self._synced = True
        await fetch_and_save_sets()
        print(f"✅ Zalogowano jako {self.user} (ID: {self.user.id})")

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
    def __init__(self, cards, user_id, set_logo_url=None):
        super().__init__(timeout=120)
        self.cards = cards
        self.index = 0
        self.summaries = []
        self.user_id = str(user_id)
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
        if first:
            await interaction.edit_original_response(embed=embed, view=self)
        else:
            await interaction.response.edit_message(embed=embed, view=self)

    class NextCardButton(Button):
        def __init__(self, parent):
            super().__init__(label="➡️ Następna karta", style=discord.ButtonStyle.primary)
            self.parent = parent

        async def callback(self, interaction: discord.Interaction):
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

# --- KOMENDA Otwórz ---
@client.tree.command(name="otworz", description="Otwórz booster i zobacz karty jedna po drugiej!")
async def otworz(interaction: discord.Interaction):
    user_id = str(interaction.user.id)
    users = load_users()
    if user_id not in users or not users[user_id]["boosters"]:
        await interaction.response.send_message("❌ Nie masz boosterów do otwarcia! Użyj `/kup_booster`.", ephemeral=True)
        return
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
    view = CardRevealView(cards, user_id=str(interaction.user.id), set_logo_url=logo_url)
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
    user = users[user_id]
    boosters_counter = Counter(user["boosters"])
    view = CollectionMainView(user, boosters_counter, all_sets)
    embed = await view.build_summary_embed()
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

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
