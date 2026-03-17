from collections import Counter
from dataclasses import dataclass
from datetime import date
from datetime import datetime
from datetime import timezone

from flask import current_app

from ..models import (
    JOB_CATEGORIES,
    JOB_CATEGORY_LABELS,
    JOB_CATEGORY_RESEARCH,
    JOB_STATUS_CANCELLED,
    JOB_STATUS_FAILED,
    JOB_STATUS_FINISHED,
    JOB_STATUS_IN_PROGRESS,
    JOB_STATUS_LABELS,
)
from .google_api import GOOGLE_SHEETS_SCOPE, build_google_service


@dataclass
class ReportJob:
    label_code: str
    created_at: datetime | None
    completed_at: datetime | None
    status: str
    category: str
    file_name: str
    user_name: str
    user_email: str
    course_number: str | None
    instructor: str | None
    department: str | None
    pi_name: str | None
    completed_by: str | None
    location: str | None

    @property
    def category_label(self) -> str:
        return JOB_CATEGORY_LABELS.get(self.category, self.category or "Other")

    @property
    def status_label(self) -> str:
        return JOB_STATUS_LABELS.get(self.status, (self.status or "").replace("_", " ").title())


def build_monthly_summary(jobs: list) -> dict:
    category_counts = Counter()
    status_counts = Counter()
    turnaround_hours = []

    for job in jobs:
        if job.category in JOB_CATEGORIES:
            category_counts[job.category] += 1
        status_counts[job.status] += 1

        if job.completed_at and job.created_at:
            duration = job.completed_at - job.created_at
            turnaround_hours.append(duration.total_seconds() / 3600)

    avg_hours = sum(turnaround_hours) / len(turnaround_hours) if turnaround_hours else 0

    return {
        "total_jobs": len(jobs),
        "category_counts": {category: category_counts.get(category, 0) for category in JOB_CATEGORIES},
        "status_counts": {
            JOB_STATUS_IN_PROGRESS: status_counts.get(JOB_STATUS_IN_PROGRESS, 0),
            JOB_STATUS_FINISHED: status_counts.get(JOB_STATUS_FINISHED, 0),
            JOB_STATUS_FAILED: status_counts.get(JOB_STATUS_FAILED, 0),
            JOB_STATUS_CANCELLED: status_counts.get(JOB_STATUS_CANCELLED, 0),
        },
        "average_turnaround_hours": avg_hours,
    }


def fetch_sheet_jobs(
    *,
    start_at: datetime,
    end_at: datetime,
    location_filter: str | None = None,
) -> tuple[list[ReportJob], list[str], str | None]:
    spreadsheet_id = current_app.config.get("GOOGLE_SHEETS_SPREADSHEET_ID", "").strip()
    if not spreadsheet_id:
        return [], [], "GOOGLE_SHEETS_SPREADSHEET_ID is not configured."

    worksheet = (
        current_app.config.get("GOOGLE_SHEETS_WORKSHEET", "PrintJobs").strip()
        or "PrintJobs"
    )
    normalized_filter = _normalize_location(location_filter)

    try:
        service = build_google_service("sheets", "v4", scopes=[GOOGLE_SHEETS_SCOPE])
        result = (
            service.spreadsheets()
            .values()
            .get(
                spreadsheetId=spreadsheet_id,
                range=_sheet_range(worksheet, "A1:Z"),
            )
            .execute()
        )
    except Exception as exc:  # noqa: BLE001
        current_app.logger.exception("Unable to load report data from Google Sheets")
        return [], [], str(exc)

    rows = result.get("values", [])
    if not rows:
        return [], [], None

    headers = rows[0]
    index_by_header = {header.strip(): idx for idx, header in enumerate(headers)}
    jobs: list[ReportJob] = []
    locations: set[str] = set()

    for row in rows[1:]:
        created_at = _parse_iso_datetime(_safe_cell(row, index_by_header, "CreatedAt"))
        if not created_at:
            continue

        location = (
            _safe_cell(row, index_by_header, "Location")
            or _safe_cell(row, index_by_header, "PrinterName")
            or ""
        ).strip()
        if location:
            locations.add(location)

        if created_at < start_at or created_at >= end_at:
            continue

        if normalized_filter and _normalize_location(location) != normalized_filter:
            continue

        status = _safe_cell(row, index_by_header, "Status").strip() or JOB_STATUS_IN_PROGRESS
        category = _safe_cell(row, index_by_header, "ProjectType").strip()

        jobs.append(
            ReportJob(
                label_code=_safe_cell(row, index_by_header, "PrintID").strip(),
                created_at=created_at,
                completed_at=_parse_iso_datetime(
                    _safe_cell(row, index_by_header, "CompletedAt")
                ),
                status=status,
                category=category,
                file_name=_safe_cell(row, index_by_header, "FileName").strip(),
                user_name=_safe_cell(row, index_by_header, "UserName").strip(),
                user_email=_safe_cell(row, index_by_header, "UserEmail").strip(),
                course_number=_nullable(_safe_cell(row, index_by_header, "CourseNumber")),
                instructor=_nullable(_safe_cell(row, index_by_header, "Instructor")),
                department=_nullable(_safe_cell(row, index_by_header, "Department")),
                pi_name=_nullable(_safe_cell(row, index_by_header, "PI")),
                completed_by=_nullable(_safe_cell(row, index_by_header, "CompletedBy")),
                location=_nullable(location),
            )
        )

    jobs.sort(key=lambda job: job.created_at or datetime.min, reverse=True)
    return jobs, sorted(locations, key=str.casefold), None


def _safe_cell(row: list[str], index_by_header: dict[str, int], header: str) -> str:
    idx = index_by_header.get(header)
    if idx is None or idx >= len(row):
        return ""
    return row[idx]


def _parse_iso_datetime(value: str) -> datetime | None:
    text = (value or "").strip()
    if not text:
        return None

    candidate = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None

    if parsed.tzinfo is not None:
        return parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _sheet_range(worksheet: str, a1_range: str) -> str:
    safe_name = worksheet.replace("'", "''")
    return f"'{safe_name}'!{a1_range}"


def _normalize_location(value: str | None) -> str:
    return (value or "").strip().lower()


def _nullable(value: str) -> str | None:
    stripped = value.strip()
    return stripped or None


def shift_month(month_start: date, delta: int) -> date:
    month_index = (month_start.year * 12 + (month_start.month - 1)) + delta
    year = month_index // 12
    month = (month_index % 12) + 1
    return date(year, month, 1)


def build_prints_over_time_chart(*, jobs: list, end_month_start: date, months: int = 12) -> dict:
    month_starts = [shift_month(end_month_start, -offset) for offset in range(months - 1, -1, -1)]
    keys = [month.strftime("%Y-%m") for month in month_starts]
    counts = {key: 0 for key in keys}

    for job in jobs:
        if not job.created_at:
            continue
        key = job.created_at.strftime("%Y-%m")
        if key in counts:
            counts[key] += 1

    return {
        "labels": [month.strftime("%b %Y") for month in month_starts],
        "values": [counts[key] for key in keys],
    }


def build_department_chart(jobs: list) -> dict:
    department_counts = Counter()
    for job in jobs:
        if job.category != JOB_CATEGORY_RESEARCH:
            continue
        if job.department:
            department_counts[job.department] += 1

    ordered = department_counts.most_common(12)
    return {
        "labels": [item[0] for item in ordered],
        "values": [item[1] for item in ordered],
    }
