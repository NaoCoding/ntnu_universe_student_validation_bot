"""NTNU Universe Discord verification bot."""

from __future__ import annotations

import logging
import asyncio
import time
from datetime import datetime, timezone
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


def discord_timestamp(timestamp: float) -> str:
    """Render a Unix timestamp using Discord's viewer-localized timestamp format."""

    return f"<t:{int(timestamp)}:F>"


def applicant_embed(
    *,
    title: str,
    description: str,
    color: discord.Color,
) -> discord.Embed:
    """Build a consistent, readable embed for applicant-facing messages."""

    embed = discord.Embed(title=title, description=description, color=color)
    embed.set_footer(text="NTNU Universe｜學生驗證中心")
    return embed


def panel_embed() -> discord.Embed:
    embed = applicant_embed(
        title="NTNU Universe｜學生驗證中心",
        description=(
            "請選擇最適合你的驗證方式。完成驗證後，系統會自動發放對應的 Discord 身分組。"
        ),
        color=discord.Color.blurple(),
    )
    embed.add_field(
        name="📧 學校信箱驗證",
        value="使用 NTNU 學校信箱收取驗證碼，通常可立即完成。請注意此方式僅限本系生 aka 學號系所代號為 47 的學生",
        inline=False,
    )
    embed.add_field(
        name="🧾 人工驗證",
        value="無法使用學校信箱時，私訊機器人並提交學生證或入學文件。",
        inline=False,
    )
    embed.add_field(
        name="開始前請準備",
        value="請確認你已加入正確的 Discord 伺服器，並開啟接收機器人私訊。",
        inline=False,
    )
    return embed


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
            embed = applicant_embed(
                title="請附上驗證文件",
                description="我還沒有收到附件，請在這則私訊中重新上傳文件。",
                color=discord.Color.gold(),
            )
            embed.add_field(
                name="可接受的文件",
                value="學生證、紙本錄取通知、紙本入學通知，或師大 APP 最新版首頁（含數位證件）畫面。",
                inline=False,
            )
            await message.channel.send(embed=embed)
            return

        admin_channel = await self.fetch_channel_safe(self.settings.admin_channel_id)
        if admin_channel is None:
            await message.channel.send(
                embed=applicant_embed(
                    title="文件暫時無法送出",
                    description="目前無法聯絡管理員頻道，請稍後重新傳送文件。",
                    color=discord.Color.red(),
                )
            )
            return

        files: list[discord.File] = []
        failed_urls: list[str] = []
        for attachment in message.attachments:
            try:
                files.append(await attachment.to_file())
            except (discord.HTTPException, discord.Forbidden):
                failed_urls.append(attachment.url)

        received_at = message.created_at.timestamp()
        embed = self.requester_embed(
            message.author,
            title="人工驗證申請",
            description="使用者已上傳文件，請管理員審核。",
            color=discord.Color.orange(),
            requested_at=session.requested_at,
        )
        embed.add_field(name="來源伺服器 ID", value=str(session.guild_id), inline=True)
        embed.add_field(name="文件收到時間", value=discord_timestamp(received_at), inline=True)
        if failed_urls:
            embed.add_field(
                name="無法轉存的附件連結",
                value="\n".join(failed_urls),
                inline=False,
            )
        await admin_channel.send(embed=embed, files=files or [])
        confirmation = applicant_embed(
            title="文件已送交管理員 ✅",
            description="你的文件已成功轉交，請耐心等待人工審核。管理員完成審核後會協助你完成驗證。",
            color=discord.Color.green(),
        )
        confirmation.add_field(name="已收到文件", value=str(len(files)), inline=True)
        if failed_urls:
            confirmation.add_field(
                name="需要重新確認",
                value="部分附件無法轉送，請稍後重新上傳那些文件。",
                inline=False,
            )
        await message.channel.send(embed=confirmation)

    async def fetch_channel_safe(self, channel_id: int) -> Any | None:
        channel = self.get_channel(channel_id)
        if channel is not None:
            return channel
        try:
            return await self.fetch_channel(channel_id)
        except (discord.HTTPException, discord.Forbidden):
            logger.exception("Unable to access channel %s", channel_id)
            return None

    def requester_embed(
        self,
        user: discord.User | discord.Member,
        *,
        title: str,
        description: str,
        color: discord.Color,
        requested_at: float,
        passed_at: float | None = None,
    ) -> discord.Embed:
        profile_url = f"https://discord.com/users/{user.id}"
        embed = discord.Embed(title=title, description=description, color=color)
        embed.set_author(
            name=f"{user.display_name} ({user.id})",
            url=profile_url,
            icon_url=user.display_avatar.url,
        )
        embed.add_field(
            name="申請人",
            value=f"{user.mention}\n[開啟 Discord 個人檔案]({profile_url})",
            inline=False,
        )
        embed.add_field(name="申請時間", value=discord_timestamp(requested_at), inline=True)
        if passed_at is not None:
            embed.add_field(name="通過時間", value=discord_timestamp(passed_at), inline=True)
            embed.timestamp = datetime.fromtimestamp(passed_at, tz=timezone.utc)
        else:
            embed.timestamp = datetime.fromtimestamp(requested_at, tz=timezone.utc)
        return embed

    async def send_admin_embed(
        self,
        embed: discord.Embed,
        *,
        content: str | None = None,
        files: list[discord.File] | None = None,
    ) -> bool:
        channel = await self.fetch_channel_safe(self.settings.admin_channel_id)
        if channel is None:
            return False
        await channel.send(content=content, embed=embed, files=files or [])
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
        label="學校信箱驗證",
        emoji="📧",
        style=discord.ButtonStyle.primary,
        custom_id="ntnu:email",
    )
    async def email_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await interaction.response.send_modal(SchoolEmailModal(self.bot))

    @discord.ui.button(
        label="人工驗證",
        emoji="🧾",
        style=discord.ButtonStyle.secondary,
        custom_id="ntnu:manual",
    )
    async def manual_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                embed=applicant_embed(
                    title="請回到伺服器操作",
                    description="這個驗證按鈕只能在 Discord 伺服器內使用。",
                    color=discord.Color.red(),
                ),
                ephemeral=True,
            )
            return
        requested_at = interaction.created_at.timestamp()
        self.bot.database.save_manual_session(
            interaction.user.id,
            interaction.guild.id,
            requested_at=requested_at,
        )
        instructions = applicant_embed(
            title="人工驗證已開啟",
            description="下一步：請開啟與機器人的私訊，並上傳一份或多份驗證文件。",
            color=discord.Color.blurple(),
        )
        instructions.add_field(
            name="可接受的文件",
            value="學生證、紙本錄取通知、紙本入學通知，或師大 APP 最新版首頁（含數位證件）畫面。",
            inline=False,
        )
        instructions.add_field(
            name="審核方式",
            value="文件會轉送給管理員人工審核，請等待審核結果。",
            inline=False,
        )
        await interaction.response.send_message(
            embed=instructions,
            ephemeral=True,
        )
        try:
            dm_instructions = applicant_embed(
                title="人工驗證文件上傳",
                description="請在這則私訊中上傳一份或多份文件。上傳後請等待管理員審核。",
                color=discord.Color.blurple(),
            )
            dm_instructions.add_field(
                name="提醒",
                value="請確認圖片清晰、資料完整，且文件上的姓名或學號可辨識。",
                inline=False,
            )
            await interaction.user.send(embed=dm_instructions)
        except discord.Forbidden:
            embed = self.bot.requester_embed(
                interaction.user,
                title="人工驗證需要協助",
                description="使用者無法接收機器人私訊，請管理員主動協助人工驗證。",
                color=discord.Color.red(),
                requested_at=requested_at,
            )
            await self.bot.send_admin_embed(embed)
            await interaction.followup.send(
                embed=applicant_embed(
                    title="無法開啟私訊",
                    description="你的隱私設定阻擋了機器人私訊。請允許伺服器成員或機器人傳送私訊後，再重新點選人工驗證。",
                    color=discord.Color.red(),
                ),
                ephemeral=True,
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
                embed=applicant_embed(
                    title="學校信箱格式不正確",
                    description="請輸入有效的 NTNU 學校信箱，再重新提交。",
                    color=discord.Color.red(),
                ),
                ephemeral=True,
            )
            return
        if interaction.guild is None:
            await interaction.response.send_message(
                embed=applicant_embed(
                    title="請回到伺服器完成驗證",
                    description="學校信箱驗證必須在 Discord 伺服器內進行。",
                    color=discord.Color.red(),
                ),
                ephemeral=True,
            )
            return

        student_number, email = parsed
        requested_at = interaction.created_at.timestamp()
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
                embed=applicant_embed(
                    title="驗證信寄送失敗",
                    description="目前無法寄出驗證信，請稍後再試；如果問題持續，也可以改用人工驗證。",
                    color=discord.Color.red(),
                ),
                ephemeral=True,
            )
            return

        self.bot.database.save_email_session(
            interaction.user.id,
            interaction.guild.id,
            email,
            student_number,
            code,
            time.time() + self.bot.settings.verification_code_ttl_minutes * 60,
            requested_at=requested_at,
        )
        email_sent = applicant_embed(
            title="驗證信已寄出 📬",
            description="請查看你的信箱，取得驗證碼後點選下方按鈕完成驗證。",
            color=discord.Color.green(),
        )
        email_sent.add_field(name="寄送至", value=f"`{email}`", inline=False)
        email_sent.add_field(
            name="有效期限",
            value=f"{self.bot.settings.verification_code_ttl_minutes} 分鐘",
            inline=True,
        )
        email_sent.add_field(
            name="找不到信件？",
            value="請先檢查垃圾郵件、垃圾信件匣或促銷內容匣；確認後仍找不到，再重新申請。",
            inline=True,
        )
        await interaction.followup.send(
            embed=email_sent,
            view=CodeEntryView(self.bot),
            ephemeral=True,
        )


class CodeEntryView(discord.ui.View):
    def __init__(self, bot: VerificationBot):
        super().__init__(timeout=600)
        self.bot = bot

    @discord.ui.button(label="輸入驗證碼", emoji="🔐", style=discord.ButtonStyle.success)
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
            await interaction.response.send_message(
                embed=applicant_embed(
                    title="找不到待驗證資料",
                    description="這組驗證流程可能已經完成或失效，請回到驗證面板重新開始。",
                    color=discord.Color.red(),
                ),
                ephemeral=True,
            )
            return
        if time.time() > session.expires_at:
            self.bot.database.delete_email_session(interaction.user.id)
            await interaction.response.send_message(
                embed=applicant_embed(
                    title="驗證碼已過期",
                    description="請重新點選學校信箱驗證，再寄送一組新的驗證碼。",
                    color=discord.Color.gold(),
                ),
                ephemeral=True,
            )
            return
        if not codes_match(session.code, str(self.code)):
            await interaction.response.send_message(
                embed=applicant_embed(
                    title="驗證碼不正確",
                    description="請確認你輸入的是最新一封信中的 32 位驗證碼，再試一次。",
                    color=discord.Color.red(),
                ),
                ephemeral=True,
            )
            return
        if interaction.guild is None or interaction.guild.id != session.guild_id:
            await interaction.response.send_message(
                embed=applicant_embed(
                    title="請回到原本的伺服器",
                    description="這組驗證碼只能在你開始驗證的 Discord 伺服器使用。",
                    color=discord.Color.red(),
                ),
                ephemeral=True,
            )
            return

        roles = self.bot.roles_for_student(interaction.guild, session.student_number)
        if not roles:
            await interaction.response.send_message(
                embed=applicant_embed(
                    title="信箱驗證完成，但需要管理員協助",
                    description="你的驗證碼正確，不過目前沒有設定對應的 Discord 身分組。管理員會協助處理。",
                    color=discord.Color.gold(),
                ),
                ephemeral=True,
            )
            embed = self.bot.requester_embed(
                interaction.user,
                title="信箱驗證通過，但缺少角色設定",
                description="驗證碼正確，但找不到此學號對應的 Discord 身分組。",
                color=discord.Color.red(),
                requested_at=session.requested_at,
            )
            embed.add_field(name="Email", value=session.email, inline=True)
            embed.add_field(name="學號", value=session.student_number, inline=True)
            await self.bot.send_admin_embed(embed)
            return

        member = interaction.guild.get_member(interaction.user.id)
        if member is None:
            try:
                member = await interaction.guild.fetch_member(interaction.user.id)
            except (discord.HTTPException, discord.NotFound):
                member = None
        if member is None:
            await interaction.response.send_message(
                embed=applicant_embed(
                    title="找不到伺服器成員資料",
                    description="請稍後再試；如果問題持續，請聯絡管理員。",
                    color=discord.Color.red(),
                ),
                ephemeral=True,
            )
            return

        try:
            await member.add_roles(*roles, reason="NTNU school email verification")
        except (discord.Forbidden, discord.HTTPException):
            logger.exception("Failed to assign roles to %s", member.id)
            await interaction.response.send_message(
                embed=applicant_embed(
                    title="驗證完成，但身分組發放失敗",
                    description="你的驗證碼正確，但身分組暫時無法自動發放。請聯絡管理員協助。",
                    color=discord.Color.gold(),
                ),
                ephemeral=True,
            )
            return

        passed_at = time.time()
        self.bot.database.mark_verification_passed(
            interaction.user.id,
            "email",
            passed_at=passed_at,
        )
        self.bot.database.delete_email_session(interaction.user.id)
        role_names = "、".join(role.name for role in roles)
        success = applicant_embed(
            title="驗證成功 🎉",
            description="恭喜！你已完成學生驗證，以下身分組已加入你的帳號。",
            color=discord.Color.green(),
        )
        success.add_field(name="已取得身分組", value=role_names, inline=False)
        await interaction.response.send_message(embed=success, ephemeral=True)
        embed = self.bot.requester_embed(
            interaction.user,
            title="信箱驗證成功",
            description="使用者已通過學校信箱驗證並取得身分組。",
            color=discord.Color.green(),
            requested_at=session.requested_at,
            passed_at=passed_at,
        )
        embed.add_field(name="Email", value=session.email, inline=True)
        embed.add_field(name="學號", value=session.student_number, inline=True)
        embed.add_field(name="已發放身分組", value=role_names, inline=False)
        await self.bot.send_admin_embed(embed)


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
