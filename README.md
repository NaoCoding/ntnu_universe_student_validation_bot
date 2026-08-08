# NTNU Universe student validation bot

This bot provides two verification paths in Discord:

1. Students with an NTNU CS email receive an MD5 verification code through the Gmail API. A successful code entry assigns a configured Discord role and posts a rich embed containing the requester profile, email, role, request time, and pass time to the admin-only channel.
2. Users without a qualifying email can opt into manual verification. They receive a DM prompt, and attachments sent to the bot by DM are forwarded to the admin-only channel for human review with the requester profile and request time.

Verification requests are stored in the SQLite `verification_records` table. Each record keeps Unix timestamps for `requested_at` and, when the automated email verification succeeds, `passed_at`.

## Setup

1. Install Python 3.11+ and dependencies:

   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```

2. Copy `.env.example` to `.env` and fill in the Discord token, channel IDs, Gmail sender, and the three hash values. `.env`, Gmail OAuth files, and the SQLite database are ignored by git.

3. In the Discord Developer Portal, enable the **Server Members Intent** and **Message Content Intent** for the bot. Invite it with the `bot` and `applications.commands` scopes and permissions to send messages, attach files, manage roles, and use application commands. The bot's role must be above every student role it assigns.

4. In Google Cloud, enable the Gmail API, create an OAuth client for a Desktop app, and save the downloaded file as `credentials.json` (or set `GMAIL_CREDENTIALS_FILE`). Run the bot once from a machine with a browser so Google can create `token.json`. The Gmail account must be permitted to send as `GMAIL_SENDER_EMAIL`.

5. Configure role assignment with exact mappings, prefix mappings, and an optional additive default role:

   ```env
   STUDENT_ROLE_MAP_JSON={"12347001":"資工系學生","12347002":"資工系學生"}
   STUDENT_ROLE_PREFIX_MAP_JSON={"41247":"資工系41247學生"}
   DEFAULT_STUDENT_ROLE="已驗證學生"
   ```

   The prefix `41247` matches every `41247XXX` student number. Exact and prefix-specific roles are granted first, and `DEFAULT_STUDENT_ROLE` is also granted when configured. This means a matching user can receive both `資工系41247學生` and `已驗證學生`.

6. Start the bot:

   ```powershell
   python bot.py
   ```

   As a server administrator, run `/setup_verification` in the configured verification channel. The command posts the persistent button panel.

## Verification code formula

The sent code is exactly:

```text
MD5(CONCAT(normalized_user_email,
           CONCAT(VERIFICATION_HASH_SECRET_PART_1,
                  VERIFICATION_HASH_SECRET_PART_2)))
```

Set the real values only in `.env`; do not commit them. The sample `.env.example` contains placeholders only.

## Tests

```powershell
python -m unittest discover -s tests -v
```
