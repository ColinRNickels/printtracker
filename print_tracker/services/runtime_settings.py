from __future__ import annotations

from flask import current_app

from ..extensions import db
from ..models import AppSetting

KEY_EMAIL_ENABLED = "completion_email_enabled"
KEY_SAVE_LABEL_FILES = "save_label_files"
KEY_LABEL_RETENTION_DAYS = "label_retention_days"
KEY_QR_PAYLOAD_MODE = "qr_payload_mode"


def get_operational_settings() -> dict:
    default_qr_payload_mode = (current_app.config.get("LABEL_QR_PAYLOAD_MODE", "url") or "url").strip().lower()
    if default_qr_payload_mode not in {"id", "url"}:
        default_qr_payload_mode = "url"
    return {
        "completion_email_enabled": get_bool_setting(KEY_EMAIL_ENABLED, default=True),
        "save_label_files": get_bool_setting(KEY_SAVE_LABEL_FILES, default=True),
        "label_retention_days": get_int_setting(KEY_LABEL_RETENTION_DAYS, default=1, minimum=1, maximum=30),
        "qr_payload_mode": get_choice_setting(KEY_QR_PAYLOAD_MODE, default=default_qr_payload_mode, choices={"id", "url"}),
    }


def get_setting(key: str) -> str | None:
    setting = AppSetting.query.filter_by(key=key).first()
    return setting.value if setting else None


def set_setting(key: str, value: str) -> None:
    setting = AppSetting.query.filter_by(key=key).first()
    if setting:
        setting.value = value
    else:
        setting = AppSetting(key=key, value=value)
        db.session.add(setting)


def get_bool_setting(key: str, *, default: bool) -> bool:
    raw = get_setting(key)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def set_bool_setting(key: str, value: bool) -> None:
    set_setting(key, "true" if value else "false")


def get_int_setting(
    key: str,
    *,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    raw = get_setting(key)
    if raw is None:
        return default
    try:
        parsed = int(raw)
    except ValueError:
        return default
    return max(minimum, min(maximum, parsed))


def set_int_setting(key: str, value: int, *, minimum: int, maximum: int) -> None:
    bounded = max(minimum, min(maximum, int(value)))
    set_setting(key, str(bounded))


def get_choice_setting(key: str, *, default: str, choices: set[str]) -> str:
    raw = get_setting(key)
    if raw is None:
        return default
    candidate = raw.strip().lower()
    if candidate in choices:
        return candidate
    return default


def set_choice_setting(key: str, value: str, *, choices: set[str], fallback: str) -> None:
    candidate = (value or "").strip().lower()
    if candidate not in choices:
        candidate = fallback
    set_setting(key, candidate)
