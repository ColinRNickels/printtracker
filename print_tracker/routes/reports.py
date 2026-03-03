import csv
from datetime import date, datetime, time
from io import StringIO

from flask import Blueprint, Response, render_template, request

from ..models import JOB_CATEGORY_LABELS, JOB_CATEGORIES, JOB_STATUS_LABELS, PrintJob
from ..services.reports import (
    build_department_chart,
    build_monthly_summary,
    build_prints_over_time_chart,
    shift_month,
)

bp = Blueprint("reports", __name__, url_prefix="/reports")


def _month_window(month_value: str | None) -> tuple[datetime, datetime]:
    if month_value:
        month_start_date = datetime.strptime(month_value, "%Y-%m").date().replace(day=1)
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
    month_value = request.args.get("month")
    month_start, month_end = _month_window(month_value)

    jobs = (
        PrintJob.query.filter(PrintJob.created_at >= month_start, PrintJob.created_at < month_end)
        .order_by(PrintJob.created_at.desc())
        .all()
    )
    summary = build_monthly_summary(jobs)
    trend_start_date = shift_month(month_start.date(), -11)
    trend_start = datetime.combine(trend_start_date, time.min)
    trend_jobs = (
        PrintJob.query.filter(PrintJob.created_at >= trend_start, PrintJob.created_at < month_end)
        .order_by(PrintJob.created_at.asc())
        .all()
    )

    chart_data = {
        "prints_over_time": build_prints_over_time_chart(
            jobs=trend_jobs,
            end_month_start=month_start.date(),
            months=12,
        ),
        "project_type": {
            "labels": [JOB_CATEGORY_LABELS.get(category, category) for category in JOB_CATEGORIES],
            "values": [summary["category_counts"].get(category, 0) for category in JOB_CATEGORIES],
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
        category_labels=JOB_CATEGORY_LABELS,
        chart_data=chart_data,
    )


@bp.route("/monthly.csv")
def monthly_csv():
    month_value = request.args.get("month")
    month_start, month_end = _month_window(month_value)

    jobs = (
        PrintJob.query.filter(PrintJob.created_at >= month_start, PrintJob.created_at < month_end)
        .order_by(PrintJob.created_at.asc())
        .all()
    )

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
            ]
        )

    filename = f"monthly-report-{month_start.strftime('%Y-%m')}.csv"
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
