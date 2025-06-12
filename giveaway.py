import discord
import random
from datetime import datetime, timezone, timedelta
from discord.ui import Modal, View, TextInput, Button
from poke_utils import (
    load_users,
    save_users,
    get_all_sets,
    EMBED_COLOR,
    create_embed,
    load_channels,
    ensure_user_fields,
)
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
GRAPHIC_DIR = BASE_DIR / "graphic"
CHANNELS = load_channels()
GIVEAWAY_CHANNEL_ID = int(CHANNELS.get("giveaway", 0))

def parse_time_string(s: str) -> int:
    units = {'s': 1, 'm': 60, 'h': 3600, 'd': 86400}
    return int(s[:-1]) * units[s[-1].lower()]

class GiveawayModal(Modal, title="🎉 Nowy Giveaway"):
    czas = TextInput(label="Czas trwania", placeholder="np. 10m, 1h, 1d", required=True)
    liczba_boosterow = TextInput(label="Ilość boosterów", placeholder="np. 5", required=True)
    liczba_zwyciezcow = TextInput(label="Ilość zwycięzców", placeholder="np. 1", required=True)
    booster_id = TextInput(label="ID zestawu (np. sv1)", placeholder="np. sv1", required=True)
    tytul = TextInput(label="Tytuł/okazja (opc.)", placeholder="np. 1000 członków", required=False)

    async def on_submit(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("🚫 Tylko administrator może tworzyć giveaway!", ephemeral=True)
            return

        try:
            czas_s = parse_time_string(self.czas.value)
            liczba = int(self.liczba_boosterow.value)
            zwyciezcy = int(self.liczba_zwyciezcow.value)
            ptcgo_input = self.booster_id.value.upper()
            sets = get_all_sets()
            matched_set = next((s for s in sets if s.get("ptcgoCode", "").upper() == ptcgo_input), None)

            if matched_set:
                booster_id = matched_set["id"]
                set_name = matched_set["name"]
            else:
                await interaction.response.send_message("❌ Nie znaleziono zestawu o podanym kodzie PTCGO.", ephemeral=True)
                return
        except Exception:
            await interaction.response.send_message("❌ Nieprawidłowe dane wejściowe.", ephemeral=True)
            return

        logo_url = matched_set.get("images", {}).get("logo") if matched_set else None
        title_msg = self.tytul.value.strip() if self.tytul.value else ""

        file = discord.File(GRAPHIC_DIR / "giveawey.png", filename="giveawey.png")

        end_time = datetime.now(timezone.utc) + timedelta(seconds=czas_s)
        end_ts = int(end_time.timestamp())
        desc = (
            f"🎴 Nagroda: {liczba}x **{set_name}** booster\n"
            f"👑 Zwycięzcy: {zwyciezcy}\n"
            f"⏳ Zakończenie <t:{end_ts}:R>"
        )
        if title_msg:
            desc = f"**{title_msg}**\n" + desc
        embed = create_embed(
            title="Giveaway",
            description=desc,
            color=EMBED_COLOR,
        )
        embed.timestamp = end_time
        if logo_url:
            embed.set_thumbnail(url=logo_url)
        embed.set_footer(text="Kliknij przycisk poniżej, aby wziąć udział!")

        view = GiveawayView(booster_id, liczba, zwyciezcy, czas_s, title_msg)
        view.end_time = end_time

        target_channel = (
            interaction.guild.get_channel(GIVEAWAY_CHANNEL_ID)
            if GIVEAWAY_CHANNEL_ID
            else interaction.channel
        )
        warn_missing = False
        if target_channel is None:
            # Fallback to the channel where the command was used
            target_channel = interaction.channel
            warn_missing = True

        message = await target_channel.send(embed=embed, view=view, file=file)
        view.message = message
        await view.update_embed()

        if warn_missing:
            await interaction.response.send_message(
                "⚠️ Nie znaleziono kanału giveaway. Ogłoszenie zostało wysłane tutaj.",
                ephemeral=True,
            )
        elif target_channel != interaction.channel:
            await interaction.response.send_message(
                f"✅ Giveaway został utworzony na <#{GIVEAWAY_CHANNEL_ID}>!",
                ephemeral=True,
            )
        else:
            await interaction.response.send_message("✅ Giveaway został utworzony!", ephemeral=True)

class GiveawayView(View):
    def __init__(self, booster_id, ilosc, winners, timeout, title_msg=""):
        super().__init__(timeout=timeout)
        self.entries = set()
        self.clicks = 0
        self.booster_id = booster_id
        self.ilosc = ilosc
        self.winners = winners
        self.message = None
        self.title_msg = title_msg
        self.end_time = datetime.now(timezone.utc) + timedelta(seconds=timeout)

    
    @discord.ui.button(label="🎉 Weź udział", style=discord.ButtonStyle.primary)
    async def join(self, interaction: discord.Interaction, button: Button):
        self.clicks += 1
        if interaction.user.id in self.entries:
            await interaction.response.send_message(
                "⚠️ Już bierzesz udział w giveaway!", ephemeral=True
            )
            return
        self.entries.add(interaction.user.id)
        await self.update_embed()
        await interaction.response.send_message(
            "✅ Zapisano do giveaway!", ephemeral=True
        )

    async def on_timeout(self):
        if not self.entries:
            if self.message:
                try:
                    await self.message.channel.send("📭 Giveaway zakończył się bez uczestników.")
                except Exception:
                    pass
            return
        chosen = random.sample(list(self.entries), min(self.winners, len(self.entries)))
        users = load_users()
        for uid in chosen:
            uid_str = str(uid)
            member = None
            if self.message and self.message.guild:
                try:
                    member = await self.message.guild.fetch_member(uid)
                except Exception:
                    member = None
            user = users.get(uid_str, {"username": member.name if member else str(uid)})
            ensure_user_fields(user)
            user["boosters"].extend([self.booster_id] * self.ilosc)
            users[uid_str] = user
        save_users(users)
        mentions = ", ".join(f"<@{uid}>" for uid in chosen)
        await self.message.channel.send(f"🏆 Gratulacje! Giveaway wygrywają: {mentions}")
        for uid in chosen:
            user_obj = await self.message.guild.fetch_member(uid)
            if user_obj:
                try:
                    await user_obj.send(
                        f"🎉 Gratulacje! Wygrałeś **{self.ilosc}x booster** z zestawu `{self.booster_id}`!\n"
                        f"Zostały dodane do Twojej kolekcji."
                    )
                except:
                    pass  # użytkownik może mieć zablokowane DM

    async def update_embed(self):
        if not self.message or not self.message.embeds:
            return

        end_ts = int(self.end_time.timestamp())
        names = [f"<@{uid}>" for uid in self.entries]

        embed = self.message.embeds[0]
        desc = (
            f"🎴 Nagroda: {self.ilosc}x booster z zestawu `{self.booster_id}`\n"
            f"👑 Zwycięzcy: {self.winners}\n"
            f"⏳ Zakończenie <t:{end_ts}:R>\n\n"
            f"👥 Uczestnicy ({len(self.entries)}):\n" + (", ".join(names) if names else "Brak") +
            f"\n\n🔢 Kliknięcia: {self.clicks}"
        )
        if self.title_msg:
            desc = f"**{self.title_msg}**\n" + desc
        embed.description = desc
        embed.timestamp = self.end_time

        try:
            await self.message.edit(embed=embed, view=self)
        except Exception as e:
            print(f"❌ Błąd aktualizacji embeda: {e}")


#def setup_giveaway_commands(tree):
#    @tree.command(name="giveaway", description="Utwórz nowe losowanie boosterów")
#    async def giveaway(interaction: discord.Interaction):
#        if not interaction.user.guild_permissions.administrator:
#            await interaction.response.send_message("🚫 Tylko administrator może tworzyć giveaway!", ephemeral=True)
#            return
#        await interaction.response.send_modal(GiveawayModal())
