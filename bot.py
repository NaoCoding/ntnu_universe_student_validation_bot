"""NTNU Universe Discord verification bot."""

from __future__ import annotations

import logging
import asyncio
import time
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from database import VerificationDatabase
from email_validation import parse_student_email
from gmail_service import GmailSender
from settings import Settings
from verification import codes_match, make_verification_code


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


def panel_embed() -> discord.Embed:
    return discord.Embed(
        title="NTNU Universe 資工系學生驗證",
        description=(
            "本系生請使用學校信箱驗證。\n"
            "若你不是本系生或尚未取得學校信箱，請點選人工驗證並私訊上傳文件。"
        ),
        color=discord.Color.blurple(),
    )


class VerificationBot(commands.Bot):
    def __init__(self, settings: Settings):
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents)
        self.settings = settings
        self.database = VerificationDatabase(settings.database_file)
        self.gmail = GmailSender(
            settings.gmail_credentials_file,
            settings.gmail_token_file,
            settings.gmail_sender_email,
        )

    async def setup_hook(self) -> None:
        self.add_view(VerificationPanelView(self))
        await self.tree.sync()

    async def on_ready(self) -> None:
        logger.info("Logged in as %s", self.user)

    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot:
            return
        if message.guild is None:
            await self.handle_manual_upload(message)
        await self.process_commands(message)

    async def handle_manual_upload(self, message: discord.Message) -> None:
        session = self.database.get_manual_session(message.author.id)
        if session is None:
            return
        if not message.attachments:
            await message.channel.send(
                "請附上學生證、紙本錄取通知、紙本入學通知，或師大 APP 最新版首頁（含數位證件）畫面。"
            )
            return

        admin_channel = await self.fetch_channel_safe(self.settings.admin_channel_id)
        if admin_channel is None:
            await message.channel.send("目前無法聯絡管理員頻道，請稍後再試。")
            return

        files: list[discord.File] = []
        failed_urls: list[str] = []
        for attachment in message.attachments:
            try:
                files.append(await attachment.to_file())
            except (discord.HTTPException, discord.Forbidden):
                failed_urls.append(attachment.url)

        content = (
            "人工驗證申請\n"
            f"Discord 使用者：{message.author}（ID: {message.author.id}）\n"
            f"來源伺服器 ID：{session.guild_id}"
        )
        if failed_urls:
            content += "\n無法轉存的附件連結：\n" + "\n".join(failed_urls)
        if files:
            await admin_channel.send(content=content, files=files)
        else:
            await admin_channel.send(content)
        await message.channel.send("已將你的文件送交管理員，請等待人工驗證。")

    async def fetch_channel_safe(self, channel_id: int) -> Any | None:
        channel = self.get_channel(channel_id)
        if channel is not None:
            return channel
        try:
            return await self.fetch_channel(channel_id)
        except (discord.HTTPException, discord.Forbidden):
            logger.exception("Unable to access channel %s", channel_id)
            return None

    async def send_admin_message(self, content: str) -> bool:
        channel = await self.fetch_channel_safe(self.settings.admin_channel_id)
        if channel is None:
            return False
        await channel.send(content)
        return True

    def roles_for_student(self, guild: discord.Guild, student_number: str) -> list[discord.Role]:
        """Resolve exact, prefix, and default roles without duplicates.

        A default role is additive: when configured, it is granted together
        with any exact or prefix-specific role.
        """

        configured_names: list[str] = []
        exact_role = self.settings.student_role_map.get(student_number)
        if exact_role:
            configured_names.append(exact_role)

        for prefix, role_name in sorted(
            self.settings.student_role_prefix_map.items(),
            key=lambda item: len(item[0]),
            reverse=True,
        ):
            if student_number.startswith(prefix):
                configured_names.append(role_name)

        if self.settings.default_student_role:
            configured_names.append(self.settings.default_student_role)

        roles: list[discord.Role] = []
        seen_role_ids: set[int] = set()
        for configured in configured_names:
            role = (
                guild.get_role(int(configured))
                if configured.isdigit()
                else discord.utils.get(guild.roles, name=configured)
            )
            if role is not None and role.id not in seen_role_ids:
                roles.append(role)
                seen_role_ids.add(role.id)
        return roles


class VerificationPanelView(discord.ui.View):
    def __init__(self, bot: VerificationBot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(
        label="學校信箱驗證", style=discord.ButtonStyle.primary, custom_id="ntnu:email"
    )
    async def email_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await interaction.response.send_modal(SchoolEmailModal(self.bot))

    @discord.ui.button(
        label="人工驗證", style=discord.ButtonStyle.secondary, custom_id="ntnu:manual"
    )
    async def manual_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("請在伺服器內使用此按鈕。", ephemeral=True)
            return
        self.bot.database.save_manual_session(interaction.user.id, interaction.guild.id)
        await interaction.response.send_message(
            "請私訊本機器人，附上學生證／紙本錄取通知／紙本入學通知／師大 APP 最新版首頁畫面。"
            "文件會轉送至管理員頻道，請等待真人審核。",
            ephemeral=True,
        )
        try:
            await interaction.user.send(
                "人工驗證已開啟。請在這則私訊中上傳一份或多份文件，完成後請等待管理員審核。"
            )
        except discord.Forbidden:
            await self.bot.send_admin_message(
                f"使用者 {interaction.user}（ID: {interaction.user.id}）無法接收私訊，請協助人工驗證。"
            )


class SchoolEmailModal(discord.ui.Modal, title="學校信箱驗證"):
    email = discord.ui.TextInput(
        label="學校信箱",
        placeholder="XXX47XXXs@gapps.ntnu.edu.tw",
        required=True,
        max_length=80,
    )

    def __init__(self, bot: VerificationBot):
        super().__init__()
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction) -> None:
        parsed = parse_student_email(str(self.email))
        if parsed is None:
            await interaction.response.send_message(
                "信箱格式不正確，請使用 XXX47XXXs@gapps.ntnu.edu.tw 或 XXX47XXXs@ntnu.edu.tw。",
                ephemeral=True,
            )
            return
        if interaction.guild is None:
            await interaction.response.send_message("請在伺服器內完成驗證。", ephemeral=True)
            return

        student_number, email = parsed
        code = make_verification_code(
            email,
            self.bot.settings.hash_secret_part_1,
            self.bot.settings.hash_secret_part_2,
        )
        await interaction.response.defer(ephemeral=True)
        try:
            await asyncio.to_thread(self.bot.gmail.send_verification_code, email, code)
        except Exception:
            logger.exception("Failed to send verification email to %s", email)
            await interaction.followup.send(
                "驗證信寄送失敗，請稍後再試或改用人工驗證。", ephemeral=True
            )
            return

        self.bot.database.save_email_session(
            interaction.user.id,
            interaction.guild.id,
            email,
            student_number,
            code,
            time.time() + self.bot.settings.verification_code_ttl_minutes * 60,
        )
        await interaction.followup.send(
            f"驗證碼已寄到 `{email}`，請點選下方按鈕輸入（{self.bot.settings.verification_code_ttl_minutes} 分鐘內有效）。",
            view=CodeEntryView(self.bot),
            ephemeral=True,
        )


class CodeEntryView(discord.ui.View):
    def __init__(self, bot: VerificationBot):
        super().__init__(timeout=600)
        self.bot = bot

    @discord.ui.button(label="輸入驗證碼", style=discord.ButtonStyle.success)
    async def code_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await interaction.response.send_modal(CodeModal(self.bot))


class CodeModal(discord.ui.Modal, title="輸入信箱驗證碼"):
    code = discord.ui.TextInput(label="驗證碼", required=True, min_length=32, max_length=32)

    def __init__(self, bot: VerificationBot):
        super().__init__()
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction) -> None:
        session = self.bot.database.get_email_session(interaction.user.id)
        if session is None:
            await interaction.response.send_message("找不到待驗證資料，請重新開始。", ephemeral=True)
            return
        if time.time() > session.expires_at:
            self.bot.database.delete_email_session(interaction.user.id)
            await interaction.response.send_message("驗證碼已過期，請重新寄送。", ephemeral=True)
            return
        if not codes_match(session.code, str(self.code)):
            await interaction.response.send_message("驗證碼不正確，請確認信件內容。", ephemeral=True)
            return
        if interaction.guild is None or interaction.guild.id != session.guild_id:
            await interaction.response.send_message("請回到原本的 Discord 伺服器完成驗證。", ephemeral=True)
            return

        roles = self.bot.roles_for_student(interaction.guild, session.student_number)
        if not roles:
            await interaction.response.send_message(
                "信箱驗證成功，但尚未設定此學號對應的 Discord 身分組，請聯絡管理員。",
                ephemeral=True,
            )
            await self.bot.send_admin_message(
                f"信箱驗證成功但缺少角色設定：Discord ID {interaction.user.id}，email {session.email}，學號 {session.student_number}。"
            )
            return

        member = interaction.guild.get_member(interaction.user.id)
        if member is None:
            try:
                member = await interaction.guild.fetch_member(interaction.user.id)
            except (discord.HTTPException, discord.NotFound):
                member = None
        if member is None:
            await interaction.response.send_message("找不到你的伺服器成員資料，請聯絡管理員。", ephemeral=True)
            return

        try:
            await member.add_roles(*roles, reason="NTNU school email verification")
        except (discord.Forbidden, discord.HTTPException):
            logger.exception("Failed to assign roles to %s", member.id)
            await interaction.response.send_message(
                "驗證成功，但身分組無法自動發放，請聯絡管理員。", ephemeral=True
            )
            return

        self.bot.database.delete_email_session(interaction.user.id)
        role_names = "、".join(role.name for role in roles)
        await interaction.response.send_message(f"驗證成功，已取得身分組：{role_names}。", ephemeral=True)
        await self.bot.send_admin_message(
            f"信箱驗證成功：Discord ID {interaction.user.id}，email {session.email}，角色 {role_names}。"
        )


def create_bot() -> VerificationBot:
    return VerificationBot(Settings.from_env())


@app_commands.command(name="setup_verification", description="在本頻道建立 NTNU Universe 驗證面板")
async def setup_verification(interaction: discord.Interaction) -> None:
    if interaction.guild is None or not interaction.user.guild_permissions.manage_guild:
        await interaction.response.send_message("只有伺服器管理員可以使用此指令。", ephemeral=True)
        return
    bot = interaction.client
    if not isinstance(bot, VerificationBot):
        await interaction.response.send_message("Bot 設定錯誤。", ephemeral=True)
        return
    if interaction.channel_id != bot.settings.verification_channel_id:
        await interaction.response.send_message(
            "請在設定的驗證頻道使用此指令。", ephemeral=True
        )
        return
    await interaction.channel.send(embed=panel_embed(), view=VerificationPanelView(bot))
    await interaction.response.send_message("驗證面板已建立。", ephemeral=True)


def main() -> None:
    bot = create_bot()
    bot.tree.add_command(setup_verification)
    bot.run(bot.settings.discord_token)


if __name__ == "__main__":
    main()
