from __future__ import annotations

from urllib.parse import urljoin

from flask import current_app, has_request_context, request


def build_staff_completion_url(label_code: str) -> str:
    safe_code = label_code.strip().upper()
    relative_path = f"/staff/s/{safe_code}"
    configured_base = (current_app.config.get("KIOSK_BASE_URL", "") or "").strip()
    if configured_base:
        return urljoin(configured_base.rstrip("/") + "/", relative_path.lstrip("/"))
    if has_request_context():
        return urljoin(request.url_root, relative_path.lstrip("/"))
    return relative_path
