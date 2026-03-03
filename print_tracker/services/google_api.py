from __future__ import annotations

from typing import Sequence

from flask import current_app

GOOGLE_GMAIL_SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"
GOOGLE_SHEETS_SCOPE = "https://www.googleapis.com/auth/spreadsheets"
GOOGLE_DEFAULT_SCOPES = (
    GOOGLE_GMAIL_SEND_SCOPE,
    GOOGLE_SHEETS_SCOPE,
)


def is_google_oauth_configured() -> bool:
    return all(
        (
            current_app.config.get("GOOGLE_OAUTH_CLIENT_ID", "").strip(),
            current_app.config.get("GOOGLE_OAUTH_CLIENT_SECRET", "").strip(),
            current_app.config.get("GOOGLE_OAUTH_REFRESH_TOKEN", "").strip(),
            current_app.config.get("GOOGLE_OAUTH_TOKEN_URI", "").strip(),
        )
    )


def build_google_service(
    api_name: str,
    api_version: str,
    *,
    scopes: Sequence[str] | None = None,
):
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
    except ModuleNotFoundError as exc:  # pragma: no cover - depends on optional install state
        raise RuntimeError(
            "Google API libraries are not installed. Run `pip install -r requirements.txt`."
        ) from exc

    if not is_google_oauth_configured():
        raise RuntimeError(
            "Google OAuth is not configured. Set GOOGLE_OAUTH_CLIENT_ID, "
            "GOOGLE_OAUTH_CLIENT_SECRET, and GOOGLE_OAUTH_REFRESH_TOKEN."
        )

    requested_scopes = tuple(scopes or GOOGLE_DEFAULT_SCOPES)
    credentials = Credentials(
        token=None,
        refresh_token=current_app.config["GOOGLE_OAUTH_REFRESH_TOKEN"],
        token_uri=current_app.config["GOOGLE_OAUTH_TOKEN_URI"],
        client_id=current_app.config["GOOGLE_OAUTH_CLIENT_ID"],
        client_secret=current_app.config["GOOGLE_OAUTH_CLIENT_SECRET"],
        scopes=requested_scopes,
    )
    credentials.refresh(Request())
    return build(api_name, api_version, credentials=credentials, cache_discovery=False)
