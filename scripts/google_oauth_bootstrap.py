#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


DEFAULT_SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/spreadsheets",
]


def _load_client_info(client_secrets_path: Path) -> tuple[str, str]:
    data = json.loads(client_secrets_path.read_text())
    payload = data.get("installed") or data.get("web")
    if not payload:
        raise ValueError("Client secrets JSON must contain an 'installed' or 'web' section.")
    client_id = payload.get("client_id", "").strip()
    client_secret = payload.get("client_secret", "").strip()
    if not client_id or not client_secret:
        raise ValueError("Client secrets JSON is missing client_id or client_secret.")
    return client_id, client_secret


def _run_flow(client_secrets_path: Path, scopes: list[str]):
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "google-auth-oauthlib is not installed. Run `pip install -r requirements.txt`."
        ) from exc

    flow = InstalledAppFlow.from_client_secrets_file(str(client_secrets_path), scopes=scopes)
    try:
        return flow.run_local_server(port=0, access_type="offline", prompt="consent")
    except Exception:
        # Useful on headless systems where local callback cannot be opened.
        return flow.run_console(access_type="offline", prompt="consent")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate OAuth refresh token for Gmail API + Google Sheets API."
    )
    parser.add_argument(
        "--client-secrets",
        required=True,
        help="Path to OAuth client JSON downloaded from Google Cloud.",
    )
    parser.add_argument(
        "--gmail-sender",
        default="",
        help="Optional sender address to include in the .env snippet.",
    )
    parser.add_argument(
        "--scope",
        action="append",
        dest="scopes",
        default=[],
        help="Extra scope. Can be provided multiple times.",
    )
    args = parser.parse_args()

    client_secrets_path = Path(args.client_secrets).expanduser().resolve()
    if not client_secrets_path.exists():
        raise FileNotFoundError(f"Client secrets file not found: {client_secrets_path}")

    scopes = DEFAULT_SCOPES + args.scopes
    print("Opening OAuth flow...")
    credentials = _run_flow(client_secrets_path, scopes)
    if not credentials.refresh_token:
        raise RuntimeError(
            "No refresh token returned. Revoke app access for this account and run again."
        )

    client_id, client_secret = _load_client_info(client_secrets_path)

    print("\nCopy these values into your .env:\n")
    print("EMAIL_PROVIDER=gmail_api")
    print(f"GOOGLE_OAUTH_CLIENT_ID={client_id}")
    print(f"GOOGLE_OAUTH_CLIENT_SECRET={client_secret}")
    print(f"GOOGLE_OAUTH_REFRESH_TOKEN={credentials.refresh_token}")
    print("GOOGLE_OAUTH_TOKEN_URI=https://oauth2.googleapis.com/token")
    if args.gmail_sender:
        print(f"GOOGLE_GMAIL_SENDER={args.gmail_sender}")
    print("GOOGLE_SHEETS_SYNC_ENABLED=true")
    print("GOOGLE_SHEETS_SPREADSHEET_ID=<your-spreadsheet-id>")
    print("GOOGLE_SHEETS_WORKSHEET=PrintJobs")
    print("\nDone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
