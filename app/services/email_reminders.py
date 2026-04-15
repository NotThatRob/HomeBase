from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from html import escape

from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.models.maintenance_task import MaintenanceTask
from app.models.user import User
from app.services.email_sender import EmailMessage, EmailSendResult, send_email
from app.services.maintenance_tasks import computed_status, dashboard_tasks


@dataclass(frozen=True)
class DigestPayload:
    user: User
    overdue_tasks: list[MaintenanceTask]
    upcoming_tasks: list[MaintenanceTask]

    @property
    def task_count(self) -> int:
        return len(self.overdue_tasks) + len(self.upcoming_tasks)


@dataclass(frozen=True)
class DigestSendResult:
    user_id: str
    email: str
    status: str
    detail: str
    task_count: int = 0


def users_for_digest(db: Session, frequency: str) -> list[User]:
    return (
        db.query(User)
        .filter(User.email_digest_enabled.is_(True))
        .filter(User.email_digest_frequency == frequency)
        .filter(User.email != "")
        .order_by(User.username.asc())
        .all()
    )


def users_due_for_digest(db: Session, frequency: str, digest_time: str) -> list[User]:
    return (
        db.query(User)
        .filter(User.email_digest_enabled.is_(True))
        .filter(User.email_digest_frequency == frequency)
        .filter(User.email_digest_time == digest_time)
        .filter(User.email != "")
        .order_by(User.username.asc())
        .all()
    )


def build_digest_payload(
    db: Session,
    user: User,
    *,
    days_ahead: int = 7,
    today: date | None = None,
) -> DigestPayload:
    overdue, upcoming = dashboard_tasks(
        db,
        user,
        days_ahead=days_ahead,
        today=today,
    )
    return DigestPayload(user=user, overdue_tasks=overdue, upcoming_tasks=upcoming)


def build_digest_email(payload: DigestPayload, settings: Settings) -> EmailMessage:
    subject = f"HomeBase maintenance digest: {payload.task_count} task"
    if payload.task_count != 1:
        subject += "s"

    html_sections = [
        "<h1>Maintenance Digest</h1>",
        f"<p>{payload.task_count} task(s) need attention.</p>",
    ]
    text_sections = [f"Maintenance Digest\n{payload.task_count} task(s) need attention."]

    if payload.overdue_tasks:
        html_sections.append("<h2>Due now</h2><ul>")
        text_sections.append("\nDue now:")
        for task in payload.overdue_tasks:
            html_sections.append(_task_html(task, settings))
            text_sections.append(_task_text(task, settings))
        html_sections.append("</ul>")

    if payload.upcoming_tasks:
        html_sections.append("<h2>Upcoming</h2><ul>")
        text_sections.append("\nUpcoming:")
        for task in payload.upcoming_tasks:
            html_sections.append(_task_html(task, settings))
            text_sections.append(_task_text(task, settings))
        html_sections.append("</ul>")

    return EmailMessage(
        to=payload.user.email,
        subject=subject,
        html="\n".join(html_sections),
        text="\n".join(text_sections),
    )


def send_digest_for_user(
    db: Session,
    user: User,
    *,
    settings: Settings | None = None,
    dry_run: bool = False,
    days_ahead: int = 7,
) -> DigestSendResult:
    settings = settings or get_settings()
    payload = build_digest_payload(db, user, days_ahead=days_ahead)
    if payload.task_count == 0:
        return DigestSendResult(
            user_id=str(user.id),
            email=user.email,
            status="skipped",
            detail="No maintenance tasks to send",
        )

    message = build_digest_email(payload, settings)
    result = send_email(message, settings, dry_run=dry_run)
    return _digest_result(user, payload, result)


def send_digests(
    db: Session,
    *,
    frequency: str,
    settings: Settings | None = None,
    dry_run: bool = False,
    days_ahead: int = 7,
) -> list[DigestSendResult]:
    settings = settings or get_settings()
    results: list[DigestSendResult] = []
    for user in users_for_digest(db, frequency):
        results.append(
            send_digest_for_user(
                db,
                user,
                settings=settings,
                dry_run=dry_run,
                days_ahead=days_ahead,
            )
        )
    return results


def send_due_digests(
    db: Session,
    *,
    frequency: str,
    digest_time: str,
    settings: Settings | None = None,
    dry_run: bool = False,
    days_ahead: int = 7,
) -> list[DigestSendResult]:
    settings = settings or get_settings()
    results: list[DigestSendResult] = []
    for user in users_due_for_digest(db, frequency, digest_time):
        results.append(
            send_digest_for_user(
                db,
                user,
                settings=settings,
                dry_run=dry_run,
                days_ahead=days_ahead,
            )
        )
    return results


def _digest_result(
    user: User,
    payload: DigestPayload,
    result: EmailSendResult,
) -> DigestSendResult:
    return DigestSendResult(
        user_id=str(user.id),
        email=user.email,
        status=result.status,
        detail=result.detail,
        task_count=payload.task_count,
    )


def _task_html(task: MaintenanceTask, settings: Settings) -> str:
    href = _html_text(f"{settings.base_url.rstrip('/')}/assets/{task.asset_id}")
    due = _due_label(task)
    due_html = _html_text(due)
    return (
        "<li>"
        f"<strong>{_html_text(task.title)}</strong> on {_html_text(task.asset.name)}"
        f" - {_html_text(computed_status(task))}"
        f"{f' - {due_html}' if due else ''}"
        f' - <a href="{href}">Open asset</a>'
        "</li>"
    )


def _task_text(task: MaintenanceTask, settings: Settings) -> str:
    href = f"{settings.base_url.rstrip('/')}/assets/{task.asset_id}"
    due = _due_label(task)
    line = f"- {task.title} on {task.asset.name} [{computed_status(task)}]"
    if due:
        line += f" - {due}"
    return f"{line} - {href}"


def _due_label(task: MaintenanceTask) -> str:
    parts = []
    if task.next_due:
        parts.append(f"due {task.next_due.isoformat()}")
    if task.next_due_usage_value:
        label = task.usage_trigger_label or "units"
        parts.append(f"due at {task.next_due_usage_value:,} {label}")
    return ", ".join(parts)


def _html_text(value: object) -> str:
    return escape(str(value or ""), quote=True)
