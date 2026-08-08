"""Gmail API sender using an installed-app OAuth token."""

from __future__ import annotations

import base64
from email.message import EmailMessage
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build


SCOPES = ["https://www.googleapis.com/auth/gmail.send"]


class GmailSender:
    def __init__(self, credentials_file: Path, token_file: Path, sender_email: str):
        self.credentials_file = credentials_file
        self.token_file = token_file
        self.sender_email = sender_email
        self._service = None

    def _get_service(self):
        if self._service is not None:
            return self._service

        credentials = None
        if self.token_file.exists():
            credentials = Credentials.from_authorized_user_file(str(self.token_file), SCOPES)
        if credentials and credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
        if not credentials or not credentials.valid:
            if not self.credentials_file.exists():
                raise RuntimeError(
                    f"Gmail OAuth credentials file not found: {self.credentials_file}"
                )
            flow = InstalledAppFlow.from_client_secrets_file(str(self.credentials_file), SCOPES)
            credentials = flow.run_local_server(port=0)
            self.token_file.write_text(credentials.to_json(), encoding="utf-8")

        self._service = build("gmail", "v1", credentials=credentials)
        return self._service

    def send_verification_code(self, recipient: str, code: str) -> None:
        message = EmailMessage()
        message["To"] = recipient
        message["From"] = self.sender_email
        message["Subject"] = "NTNU Universe 資工系信箱驗證"
        message.set_content(code)
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
        self._get_service().users().messages().send(
            userId="me", body={"raw": raw}
        ).execute()

