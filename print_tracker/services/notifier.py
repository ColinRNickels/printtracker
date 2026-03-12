import base64
import os
import smtplib
from email.message import EmailMessage
from email.utils import make_msgid

from flask import current_app, render_template

from ..models import JOB_STATUS_FAILED, JOB_STATUS_FINISHED
from .google_api import (
    GOOGLE_GMAIL_SEND_SCOPE,
    build_google_service,
    is_google_oauth_configured,
)


def send_completion_email(job) -> tuple[str, str | None]:
    if not job.user_email:
        return "skipped", "No user email on file."

    if job.status not in {JOB_STATUS_FINISHED, JOB_STATUS_FAILED}:
        return "skipped", "Job is not completed."

    is_success = job.status == JOB_STATUS_FINISHED
    txt_template = "email_success.txt" if is_success else "email_failure.txt"
    html_template = "email_success.html" if is_success else "email_failure.html"
    subject = (
        f"Your 3D print is ready: {job.file_name}"
        if is_success
        else f"Update about your 3D print: {job.file_name}"
    )

    logo_cid_header = make_msgid(domain="ncsu.edu")
    logo_cid_bare = logo_cid_header[1:-1]  # strip angle brackets for HTML src

    location = job.location or current_app.config.get("DEFAULT_PRINTER_NAME", "Makerspace")
    body_text = render_template(txt_template, job=job, location=location)
    body_html = render_template(html_template, job=job, logo_cid=logo_cid_bare, location=location)

    logo_path = os.path.join(
        current_app.static_folder, "ncsu-makerspace-logo-long-v2.png"
    )
    if not os.path.isfile(logo_path):
        logo_path = None

    provider = current_app.config.get("EMAIL_PROVIDER", "smtp").strip().lower()
    if provider == "gmail_api":
        return _send_with_gmail_api(
            job=job,
            subject=subject,
            body_text=body_text,
            body_html=body_html,
            logo_cid=logo_cid_header,
            logo_path=logo_path,
        )

    if provider == "auto":
        if is_google_oauth_configured():
            status, error = _send_with_gmail_api(
                job=job,
                subject=subject,
                body_text=body_text,
                body_html=body_html,
                logo_cid=logo_cid_header,
                logo_path=logo_path,
            )
            if status == "sent":
                return status, error
            current_app.logger.warning(
                "Gmail API send failed in auto mode for job %s; falling back to SMTP. Error: %s",
                job.id,
                error,
            )
        return _send_with_smtp(
            job=job,
            subject=subject,
            body_text=body_text,
            body_html=body_html,
            logo_cid=logo_cid_header,
            logo_path=logo_path,
        )

    return _send_with_smtp(
        job=job,
        subject=subject,
        body_text=body_text,
        body_html=body_html,
        logo_cid=logo_cid_header,
        logo_path=logo_path,
    )


def _build_message(
    *,
    recipient: str,
    subject: str,
    body_text: str,
    body_html: str | None = None,
    logo_cid: str | None = None,
    logo_path: str | None = None,
) -> EmailMessage:
    sender = current_app.config.get("GOOGLE_GMAIL_SENDER") or current_app.config.get(
        "SMTP_FROM_ADDRESS", ""
    )
    message = EmailMessage()
    message["Subject"] = subject
    message["To"] = recipient
    if sender:
        message["From"] = sender

    message.set_content(body_text)

    if body_html:
        message.add_alternative(body_html, subtype="html")
        if logo_path and logo_cid and os.path.isfile(logo_path):
            with open(logo_path, "rb") as img_file:
                message.get_payload()[1].add_related(
                    img_file.read(),
                    maintype="image",
                    subtype="png",
                    cid=logo_cid,
                )

    return message


def _send_with_gmail_api(
    *,
    job,
    subject: str,
    body_text: str,
    body_html: str | None = None,
    logo_cid: str | None = None,
    logo_path: str | None = None,
) -> tuple[str, str | None]:
    if not is_google_oauth_configured():
        return "skipped", "Google OAuth is not configured."

    message = _build_message(
        recipient=job.user_email,
        subject=subject,
        body_text=body_text,
        body_html=body_html,
        logo_cid=logo_cid,
        logo_path=logo_path,
    )
    raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")

    try:
        service = build_google_service("gmail", "v1", scopes=[GOOGLE_GMAIL_SEND_SCOPE])
        service.users().messages().send(
            userId="me", body={"raw": raw_message}
        ).execute()
        return "sent", None
    except Exception as exc:  # noqa: BLE001
        current_app.logger.exception(
            "Failed to send Gmail API completion email for job %s", job.id
        )
        return "failed", str(exc)


def _send_with_smtp(
    *,
    job,
    subject: str,
    body_text: str,
    body_html: str | None = None,
    logo_cid: str | None = None,
    logo_path: str | None = None,
) -> tuple[str, str | None]:
    host = current_app.config["SMTP_HOST"]
    if not host:
        current_app.logger.info(
            "SMTP not configured. Email preview for %s:\n%s", job.user_email, body_text
        )
        return "skipped", "SMTP is not configured."

    message = _build_message(
        recipient=job.user_email,
        subject=subject,
        body_text=body_text,
        body_html=body_html,
        logo_cid=logo_cid,
        logo_path=logo_path,
    )

    try:
        with smtplib.SMTP(host, current_app.config["SMTP_PORT"], timeout=15) as smtp:
            if current_app.config["SMTP_USE_TLS"]:
                smtp.starttls()
            username = current_app.config["SMTP_USERNAME"]
            password = current_app.config["SMTP_PASSWORD"]
            if username:
                smtp.login(username, password)
            smtp.send_message(message)
        return "sent", None
    except Exception as exc:  # noqa: BLE001
        current_app.logger.exception(
            "Failed to send SMTP completion email for job %s", job.id
        )
        return "failed", str(exc)
