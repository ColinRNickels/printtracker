import csv
from datetime import date, datetime, time
from io import StringIO

from flask import (
    Blueprint,
    Response,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from ..models import JOB_CATEGORY_LABELS, JOB_CATEGORIES, JOB_STATUS_LABELS, PrintJob
from ..services.reports import (
    build_department_chart,
    fetch_sheet_jobs,
    build_monthly_summary,
    build_prints_over_time_chart,
    shift_month,
)

bp = Blueprint("reports", __name__, url_prefix="/reports")

STAFF_SESSION_KEY = "staff_authenticated"


@bp.before_request
def require_staff_auth():
    if session.get(STAFF_SESSION_KEY):
        return None
    return redirect(url_for("staff.login", next=request.full_path.rstrip("?")))


def _month_window(month_value: str | None) -> tuple[datetime, datetime]:
    if month_value:
        try:
            month_start_date = (
                datetime.strptime(month_value, "%Y-%m").date().replace(day=1)
            )
        except ValueError as exc:
            raise ValueError("Month must use the YYYY-MM format.") from exc
    else:
        today = date.today()
        month_start_date = date(today.year, today.month, 1)

    if month_start_date.month == 12:
        month_end_date = date(month_start_date.year + 1, 1, 1)
    else:
        month_end_date = date(month_start_date.year, month_start_date.month + 1, 1)

    month_start = datetime.combine(month_start_date, time.min)
    month_end = datetime.combine(month_end_date, time.min)
    return month_start, month_end


@bp.route("/monthly")
def monthly():
    month_value = (request.args.get("month") or "").strip() or None
    location_value = (request.args.get("location") or "").strip()
    selected_location = location_value or ""
    try:
        month_start, month_end = _month_window(month_value)
    except ValueError as exc:
        flash(str(exc), "error")
        month_start, month_end = _month_window(None)
        month_value = month_start.strftime("%Y-%m")

    trend_start_date = shift_month(month_start.date(), -11)
    trend_start = datetime.combine(trend_start_date, time.min)
    jobs: list = []
    trend_jobs: list = []
    available_locations: list[str] = []

    sheet_jobs, available_locations, sheet_error = fetch_sheet_jobs(
        start_at=trend_start,
        end_at=month_end,
        location_filter=selected_location or None,
    )
    if sheet_error:
        flash(f"Google Sheets report data unavailable: {sheet_error}", "warning")
    else:
        trend_jobs = sheet_jobs
        jobs = [
            job
            for job in sheet_jobs
            if job.created_at and month_start <= job.created_at < month_end
        ]

    if sheet_error:
        query = PrintJob.query.filter(
            PrintJob.created_at >= month_start, PrintJob.created_at < month_end
        )
        if selected_location:
            query = query.filter(PrintJob.location == selected_location)
        jobs = query.order_by(PrintJob.created_at.desc()).all()

        trend_query = PrintJob.query.filter(
            PrintJob.created_at >= trend_start, PrintJob.created_at < month_end
        )
        if selected_location:
            trend_query = trend_query.filter(PrintJob.location == selected_location)
        trend_jobs = trend_query.order_by(PrintJob.created_at.asc()).all()

        db_locations = (
            PrintJob.query.with_entities(PrintJob.location)
            .filter(PrintJob.location.isnot(None))
            .distinct()
            .all()
        )
        available_locations = sorted(
            {
                (location or "").strip()
                for (location,) in db_locations
                if (location or "").strip()
            },
            key=str.casefold,
        )

    summary = build_monthly_summary(jobs)

    chart_data = {
        "prints_over_time": build_prints_over_time_chart(
            jobs=trend_jobs,
            end_month_start=month_start.date(),
            months=12,
        ),
        "project_type": {
            "labels": [
                JOB_CATEGORY_LABELS.get(category, category)
                for category in JOB_CATEGORIES
            ],
            "values": [
                summary["category_counts"].get(category, 0)
                for category in JOB_CATEGORIES
            ],
        },
        "department": build_department_chart(jobs),
        "status": {
            "labels": [
                JOB_STATUS_LABELS.get("in_progress", "In Progress"),
                JOB_STATUS_LABELS.get("finished", "Finished"),
                JOB_STATUS_LABELS.get("failed", "Failed"),
            ],
            "values": [
                summary["status_counts"].get("in_progress", 0),
                summary["status_counts"].get("finished", 0),
                summary["status_counts"].get("failed", 0),
            ],
        },
    }

    return render_template(
        "reports_monthly.html",
        jobs=jobs,
        summary=summary,
        month_value=month_start.strftime("%Y-%m"),
        month_label=month_start.strftime("%B %Y"),
        selected_location=selected_location,
        available_locations=available_locations,
        category_labels=JOB_CATEGORY_LABELS,
        chart_data=chart_data,
    )


@bp.route("/monthly.csv")
def monthly_csv():
    month_value = (request.args.get("month") or "").strip() or None
    location_value = (request.args.get("location") or "").strip()
    try:
        month_start, month_end = _month_window(month_value)
    except ValueError:
        month_start, month_end = _month_window(None)

    jobs: list = []
    sheet_jobs, _, sheet_error = fetch_sheet_jobs(
        start_at=month_start,
        end_at=month_end,
        location_filter=location_value or None,
    )
    if not sheet_error:
        jobs = sorted(
            sheet_jobs,
            key=lambda job: job.created_at or datetime.min,
        )
    else:
        query = PrintJob.query.filter(
            PrintJob.created_at >= month_start, PrintJob.created_at < month_end
        )
        if location_value:
            query = query.filter(PrintJob.location == location_value)
        jobs = query.order_by(PrintJob.created_at.asc()).all()

    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "PrintID",
            "CreatedAt",
            "CompletedAt",
            "Status",
            "ProjectType",
            "FileName",
            "UserName",
            "UserEmail",
            "CourseNumber",
            "Instructor",
            "Department",
            "PI",
            "CompletedBy",
            "Location",
        ]
    )
    for job in jobs:
        writer.writerow(
            [
                job.label_code,
                job.created_at.isoformat() if job.created_at else "",
                job.completed_at.isoformat() if job.completed_at else "",
                job.status_label,
                job.category_label,
                job.file_name,
                job.user_name,
                job.user_email,
                job.course_number or "",
                job.instructor or "",
                job.department or "",
                job.pi_name or "",
                job.completed_by or "",
                job.location or "",
            ]
        )

    filename = f"monthly-report-{month_start.strftime('%Y-%m')}.csv"
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
