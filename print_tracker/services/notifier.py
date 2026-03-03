import base64
import smtplib
from email.message import EmailMessage

from flask import current_app, render_template

from ..models import JOB_STATUS_FAILED, JOB_STATUS_FINISHED
from .google_api import GOOGLE_GMAIL_SEND_SCOPE, build_google_service, is_google_oauth_configured


def send_completion_email(job) -> tuple[str, str | None]:
    if not job.user_email:
        return "skipped", "No user email on file."

    if job.status not in {JOB_STATUS_FINISHED, JOB_STATUS_FAILED}:
        return "skipped", "Job is not completed."

    template_name = "email_success.txt" if job.status == JOB_STATUS_FINISHED else "email_failure.txt"
    subject = (
        f"Your 3D print is ready: {job.file_name}"
        if job.status == JOB_STATUS_FINISHED
        else f"Update about your 3D print: {job.file_name}"
    )
    body = render_template(template_name, job=job)

    provider = current_app.config.get("EMAIL_PROVIDER", "smtp").strip().lower()
    if provider == "gmail_api":
        return _send_with_gmail_api(job=job, subject=subject, body=body)

    if provider == "auto":
        if is_google_oauth_configured():
            status, error = _send_with_gmail_api(job=job, subject=subject, body=body)
            if status == "sent":
                return status, error
            current_app.logger.warning(
                "Gmail API send failed in auto mode for job %s; falling back to SMTP. Error: %s",
                job.id,
                error,
            )
        return _send_with_smtp(job=job, subject=subject, body=body)

    return _send_with_smtp(job=job, subject=subject, body=body)


def _build_message(*, recipient: str, subject: str, body: str) -> EmailMessage:
    sender = current_app.config.get("GOOGLE_GMAIL_SENDER") or current_app.config.get("SMTP_FROM_ADDRESS", "")
    message = EmailMessage()
    message["Subject"] = subject
    message["To"] = recipient
    if sender:
        message["From"] = sender
    message.set_content(body)
    return message


def _send_with_gmail_api(*, job, subject: str, body: str) -> tuple[str, str | None]:
    if not is_google_oauth_configured():
        return "skipped", "Google OAuth is not configured."

    message = _build_message(recipient=job.user_email, subject=subject, body=body)
    raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")

    try:
        service = build_google_service("gmail", "v1", scopes=[GOOGLE_GMAIL_SEND_SCOPE])
        service.users().messages().send(userId="me", body={"raw": raw_message}).execute()
        return "sent", None
    except Exception as exc:  # noqa: BLE001
        current_app.logger.exception("Failed to send Gmail API completion email for job %s", job.id)
        return "failed", str(exc)


def _send_with_smtp(*, job, subject: str, body: str) -> tuple[str, str | None]:
    host = current_app.config["SMTP_HOST"]
    if not host:
        current_app.logger.info("SMTP not configured. Email preview for %s:\n%s", job.user_email, body)
        return "skipped", "SMTP is not configured."

    message = _build_message(recipient=job.user_email, subject=subject, body=body)

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
        current_app.logger.exception("Failed to send SMTP completion email for job %s", job.id)
        return "failed", str(exc)
