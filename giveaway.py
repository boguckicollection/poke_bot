import discord
import random
import asyncio
from datetime import datetime, timezone, timedelta
from discord.ui import Modal, View, TextInput, Button
from poke_utils import load_users, save_users, get_all_sets
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
GRAPHIC_DIR = BASE_DIR / "graphic"
EMBED_COLOR = discord.Color.dark_teal()

def parse_time_string(s: str) -> int:
    units = {'s': 1, 'm': 60, 'h': 3600, 'd': 86400}
    return int(s[:-1]) * units[s[-1].lower()]

class GiveawayModal(Modal, title="🎉 Nowy Giveaway"):
    czas = TextInput(label="Czas trwania", placeholder="np. 10m, 1h, 1d", required=True)
    liczba_boosterow = TextInput(label="Ilość boosterów", placeholder="np. 5", required=True)
    liczba_zwyciezcow = TextInput(label="Ilość zwycięzców", placeholder="np. 1", required=True)
    booster_id = TextInput(label="ID zestawu (np. sv1)", placeholder="np. sv1", required=True)

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

        file = discord.File(GRAPHIC_DIR / "giveawey.png", filename="giveawey.png")

        embed = discord.Embed(
            description=(
                f"🎴 Nagroda: {liczba}x **{set_name}** booster\n"
                f"👑 Zwycięzcy: {zwyciezcy}\n"
                f"⏳ Zakończenie za: {self.czas.value}"
            ),
            color=EMBED_COLOR,
            timestamp=datetime.now(timezone.utc) + timedelta(seconds=czas_s)
        )
        if logo_url:
            embed.set_thumbnail(url=logo_url)
        embed.set_image(url="attachment://giveawey.png")
        embed.set_footer(text="Kliknij przycisk poniżej, aby wziąć udział!")

        view = GiveawayView(booster_id, liczba, zwyciezcy, czas_s)
        message = await interaction.channel.send(embed=embed, view=view, file=file)
        view.message = message
        asyncio.create_task(view.update_embed_loop())
        await interaction.response.send_message("✅ Giveaway został utworzony!", ephemeral=True)

class GiveawayView(View):
    def __init__(self, booster_id, ilosc, winners, timeout):
        super().__init__(timeout=timeout)
        self.entries = set()
        self.booster_id = booster_id
        self.ilosc = ilosc
        self.winners = winners
        self.message = None

    
    @discord.ui.button(label="🎉 Weź udział", style=discord.ButtonStyle.primary)
    async def join(self, interaction: discord.Interaction, button: Button):
        self.entries.add(interaction.user.id)
        await interaction.response.send_message("✅ Zapisano do giveaway!", ephemeral=True)

    async def on_timeout(self):
        if not self.entries:
            return
        chosen = random.sample(list(self.entries), min(self.winners, len(self.entries)))
        users = load_users()
        for uid in chosen:
            uid_str = str(uid)
            if uid_str in users:
                users[uid_str]["boosters"].extend([self.booster_id] * self.ilosc)
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
    async def update_embed_loop(self):
        while True:
            if not self.message or not self.message.embeds:
                break

            remaining = int((self.message.embeds[0].timestamp - datetime.now(timezone.utc)).total_seconds())
            if remaining <= 0:
                break

            await self.update_embed()
            await asyncio.sleep(1)

    async def update_embed(self):
        if not self.message or not self.message.embeds:
            return

        remaining_seconds = int((self.message.embeds[0].timestamp - datetime.now(timezone.utc)).total_seconds())
        names = [f"<@{uid}>" for uid in self.entries]

        embed = self.message.embeds[0]
        embed.description = (
            f"🎴 Nagroda: {self.ilosc}x booster z zestawu `{self.booster_id}`\n"
            f"👑 Zwycięzcy: {self.winners}\n"
            f"⏳ Zakończenie za: {remaining_seconds // 60}m {remaining_seconds % 60}s\n\n"
            f"👥 Uczestnicy ({len(self.entries)}):\n" + (", ".join(names) if names else "Brak")
        )

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
