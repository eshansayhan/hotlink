import asyncio
import os
import socket

import aiohttp
import discord
from discord import app_commands

from app import access_store
from app.monitoring.logger import stream_logger


class HFStreamBot(discord.Client):
    def __init__(self) -> None:
        connector = aiohttp.TCPConnector(family=socket.AF_INET)
        super().__init__(intents=discord.Intents.none(), connector=connector)
        self.tree = app_commands.CommandTree(self)
        self._register_commands()

    def _register_commands(self) -> None:
        @self.tree.command(name="kod", description="HFStream için kişiye özel erişim kodu üretir.")
        async def issue_access_code(interaction: discord.Interaction) -> None:
            channel_id = os.getenv("DISCORD_CHANNEL_ID", "").strip()
            if channel_id.isdigit() and interaction.channel_id != int(channel_id):
                await interaction.response.send_message(
                    "Kod almak için destek sunucusundaki belirlenmiş kod kanalını kullan.",
                    ephemeral=True,
                )
                return

            username = getattr(interaction.user, "name", "")
            user_label = f"{username} ({interaction.user.id})" if username else str(interaction.user.id)
            code = access_store.issue_code(
                str(interaction.user.id),
                note=f"Discord Bot: {user_label}",
                ip_address="Discord Gateway",
            )
            code_msg = (
                f"HFStream erişim kodun: {code}\n"
                "Lütfen kodu uygulamadan aktifleştirin."
            )
            try:
                await interaction.user.send(code_msg)
                await interaction.response.send_message(
                    "Başarıyla kod mesaj olarak gönderildi, lütfen mesaj kutunuzu kontrol edin.",
                    ephemeral=True,
                )
            except Exception:
                await interaction.response.send_message(
                    code_msg,
                    ephemeral=True,
                )

        @self.tree.command(name="surem", description="Aktif HFStream erişim kodunuzun kalan süresini gösterir.")
        async def check_remaining_time(interaction: discord.Interaction) -> None:
            active_info = access_store.get_user_active_code(str(interaction.user.id))
            if active_info:
                remaining = active_info["remaining_seconds"]
                h = remaining // 3600
                m = (remaining % 3600) // 60
                time_str = f"{h} saat {m} dakika" if h > 0 else f"{m} dakika"
                status_note = " *(Cihazla eşleşti)*" if active_info["redeemed"] else " *(Henüz kullanılmadı)*"
                content = f"⏱️ **HFStream Erişim Durumunuz**\n🔑 Kodunuz: `{active_info['code']}`\n⏳ Kalan Süreniz: **{time_str}**{status_note}"
            else:
                content = "❌ Aktif bir erişim kodunuz bulunmamaktadır.\n`/kod` yazarak anında yeni kod alabilirsiniz."
            await interaction.response.send_message(content, ephemeral=True)

    async def setup_hook(self) -> None:
        guild_id = os.getenv("DISCORD_GUILD_ID", "").strip()
        if guild_id.isdigit():
            guild = discord.Object(id=int(guild_id))
            self.tree.copy_global_to(guild=guild)
            commands = await self.tree.sync(guild=guild)
            stream_logger.info("DISCORD", f"Bot commands synchronized to configured guild ({len(commands)} command(s)).")
        else:
            commands = await self.tree.sync()
            stream_logger.info("DISCORD", f"Bot commands synchronized globally ({len(commands)} command(s)).")

    async def on_ready(self) -> None:
        stream_logger.info("DISCORD", f"Bot connected as {self.user}.")


bot: HFStreamBot | None = None


async def run_bot() -> None:
    global bot
    token = os.getenv("DISCORD_BOT_TOKEN", "").strip()
    if not token:
        stream_logger.error("DISCORD", "Bot not started: DISCORD_BOT_TOKEN is missing or empty.")
        return

    retry_delay = 5
    while True:
        stream_logger.info("DISCORD", "Starting Discord bot connection (IPv4 forced).")
        bot = HFStreamBot()
        try:
            await bot.start(token)
            break
        except asyncio.CancelledError:
            stream_logger.info("DISCORD", "Bot task cancelled.")
            if bot and not bot.is_closed():
                await bot.close()
            break
        except Exception as error:
            message = str(error).replace(token, "[REDACTED]")
            stream_logger.error("DISCORD", f"Bot connection failed ({type(error).__name__}): {message}. Retrying in {retry_delay}s...")
            if bot and not bot.is_closed():
                try:
                    await bot.close()
                except Exception:
                    pass
            await asyncio.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, 60)
