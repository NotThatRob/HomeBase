import calendar
import uuid
from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session, joinedload

from app.models.asset import Asset
from app.models.component import Component
from app.models.maintenance_task import (
    INTERVAL_UNITS,
    SCHEDULE_TYPES,
    TASK_PRIORITIES,
    TASK_STATUSES,
    MaintenanceTask,
)
from app.models.service_record import ServiceRecord
from app.models.user import User
from app.services.visibility import visible_asset_ids

MAINTENANCE_TASK_ALLOWED_FIELDS = {
    "title",
    "description",
    "schedule_type",
    "interval_value",
    "interval_unit",
    "calendar_month",
    "calendar_day",
    "usage_trigger_label",
    "usage_trigger_value",
    "next_due",
    "next_due_usage_value",
    "priority",
    "status",
}


def _filter_allowed(data: dict, allowed: set) -> dict:
    return {k: v for k, v in data.items() if k in allowed}


def _add_months(value: date, months: int) -> date:
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _calendar_due_after(completed_on: date, month: int, day: int) -> date:
    year = completed_on.year
    clamped_day = min(day, calendar.monthrange(year, month)[1])
    candidate = date(year, month, clamped_day)
    if candidate <= completed_on:
        year += 1
        clamped_day = min(day, calendar.monthrange(year, month)[1])
        candidate = date(year, month, clamped_day)
    return candidate


def _validate_task_data(data: dict) -> None:
    schedule_type = data.get("schedule_type")
    if schedule_type not in SCHEDULE_TYPES:
        raise ValueError("Invalid schedule type")

    priority = data.get("priority", "normal")
    if priority not in TASK_PRIORITIES:
        raise ValueError("Invalid priority")

    status = data.get("status", "upcoming")
    if status not in TASK_STATUSES:
        raise ValueError("Invalid status")

    if schedule_type == "interval":
        if not data.get("interval_value") or data.get("interval_unit") not in INTERVAL_UNITS:
            raise ValueError("Interval tasks require a value and unit")
        if int(data["interval_value"]) <= 0:
            raise ValueError("Interval value must be greater than zero")
        if not data.get("next_due"):
            raise ValueError("Interval tasks require a next due date")
    elif schedule_type == "calendar":
        month = data.get("calendar_month")
        day = data.get("calendar_day")
        if not month or not day:
            raise ValueError("Calendar tasks require month and day")
        if int(month) < 1 or int(month) > 12 or int(day) < 1 or int(day) > 31:
            raise ValueError("Calendar month/day is invalid")
    elif schedule_type == "usage":
        if not data.get("usage_trigger_value") or int(data["usage_trigger_value"]) <= 0:
            raise ValueError("Usage tasks require a trigger value greater than zero")
        if not data.get("next_due_usage_value"):
            raise ValueError("Usage tasks require a next due usage value")
    elif schedule_type == "one_time" and not data.get("next_due"):
        raise ValueError("One-time tasks require a due date")


def computed_status(task: MaintenanceTask, today: date | None = None) -> str:
    if task.status in {"completed", "paused"}:
        return task.status

    today = today or date.today()
    due_by_date = False
    due_by_usage = False

    if task.next_due:
        due_by_date = task.next_due <= today
    if (
        task.next_due_usage_value is not None
        and task.asset
        and task.asset.vehicle_meta
        and task.asset.vehicle_meta.current_mileage is not None
    ):
        due_by_usage = task.asset.vehicle_meta.current_mileage >= task.next_due_usage_value

    if due_by_date and task.next_due and task.next_due < today:
        return "overdue"
    if due_by_usage:
        return "due"
    if due_by_date:
        return "due"
    return "upcoming"


def list_tasks_for_asset(
    db: Session,
    asset_id: uuid.UUID,
    include_completed: bool = False,
) -> list[MaintenanceTask]:
    query = (
        db.query(MaintenanceTask)
        .options(
            joinedload(MaintenanceTask.components),
            joinedload(MaintenanceTask.created_by),
            joinedload(MaintenanceTask.asset).joinedload(Asset.vehicle_meta),
        )
        .filter(MaintenanceTask.asset_id == asset_id)
    )
    if not include_completed:
        query = query.filter(MaintenanceTask.status != "completed")
    return query.order_by(MaintenanceTask.next_due.asc().nullslast()).all()


def get_task(db: Session, task_id: uuid.UUID) -> MaintenanceTask | None:
    return (
        db.query(MaintenanceTask)
        .options(
            joinedload(MaintenanceTask.components),
            joinedload(MaintenanceTask.created_by),
            joinedload(MaintenanceTask.asset).joinedload(Asset.vehicle_meta),
        )
        .filter(MaintenanceTask.id == task_id)
        .first()
    )


def create_task(
    db: Session,
    asset_id: uuid.UUID,
    data: dict,
    user: User,
    component_ids: list[uuid.UUID] | None = None,
) -> MaintenanceTask:
    filtered = _filter_allowed(data, MAINTENANCE_TASK_ALLOWED_FIELDS)
    filtered.setdefault("priority", "normal")
    filtered.setdefault("status", "upcoming")
    _validate_task_data(filtered)
    task = MaintenanceTask(asset_id=asset_id, created_by_id=user.id, **filtered)
    if component_ids:
        task.components = _components_for_asset(db, asset_id, component_ids)
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def update_task(
    db: Session,
    task: MaintenanceTask,
    data: dict,
    component_ids: list[uuid.UUID] | None = None,
) -> MaintenanceTask:
    filtered = _filter_allowed(data, MAINTENANCE_TASK_ALLOWED_FIELDS)
    filtered.setdefault("priority", task.priority)
    filtered.setdefault("status", task.status)
    _validate_task_data(filtered)
    for key, value in filtered.items():
        setattr(task, key, value)
    if component_ids is not None:
        task.components = _components_for_asset(db, task.asset_id, component_ids)
    db.commit()
    db.refresh(task)
    return task


def set_task_status(db: Session, task: MaintenanceTask, status: str) -> MaintenanceTask:
    if status not in {"paused", "upcoming"}:
        raise ValueError("Invalid task status")
    task.status = status
    db.commit()
    db.refresh(task)
    return task


def delete_task(db: Session, task: MaintenanceTask) -> None:
    db.delete(task)
    db.commit()


def complete_task(
    db: Session,
    task: MaintenanceTask,
    record: ServiceRecord,
    completed_on: date | None = None,
) -> MaintenanceTask:
    completed_on = completed_on or record.service_date
    task.last_completed_record_id = record.id

    if task.schedule_type == "one_time":
        task.status = "completed"
    elif task.schedule_type == "interval":
        task.next_due = _next_interval_due(completed_on, task)
        task.status = "upcoming"
    elif task.schedule_type == "calendar":
        task.next_due = _calendar_due_after(
            completed_on,
            task.calendar_month or completed_on.month,
            task.calendar_day or completed_on.day,
        )
        task.status = "upcoming"
    elif task.schedule_type == "usage":
        base_usage = record.mileage_at_service or task.next_due_usage_value or 0
        task.next_due_usage_value = base_usage + (task.usage_trigger_value or 0)
        task.status = "upcoming"

    db.commit()
    db.refresh(task)
    return task


def _next_interval_due(completed_on: date, task: MaintenanceTask) -> date:
    value = task.interval_value or 0
    if task.interval_unit == "days":
        return completed_on + timedelta(days=value)
    if task.interval_unit == "weeks":
        return completed_on + timedelta(weeks=value)
    if task.interval_unit == "months":
        return _add_months(completed_on, value)
    if task.interval_unit == "years":
        return _add_months(completed_on, value * 12)
    return completed_on


def dashboard_tasks(
    db: Session,
    user: User,
    days_ahead: int = 30,
    today: date | None = None,
) -> tuple[list[MaintenanceTask], list[MaintenanceTask]]:
    today = today or date.today()
    horizon = today + timedelta(days=days_ahead)
    tasks = (
        db.query(MaintenanceTask)
        .options(
            joinedload(MaintenanceTask.asset).joinedload(Asset.vehicle_meta),
            joinedload(MaintenanceTask.components),
        )
        .filter(MaintenanceTask.asset_id.in_(visible_asset_ids(user)))
        .filter(MaintenanceTask.status.notin_(["completed", "paused"]))
        .all()
    )

    overdue: list[MaintenanceTask] = []
    upcoming: list[MaintenanceTask] = []
    for task in tasks:
        status = computed_status(task, today=today)
        if status == "overdue":
            overdue.append(task)
        elif status == "due":
            overdue.append(task)
        elif task.next_due and today < task.next_due <= horizon:
            upcoming.append(task)

    overdue.sort(key=lambda t: (t.next_due or date.max, t.title.lower()))
    upcoming.sort(key=lambda t: (t.next_due or date.max, t.title.lower()))
    return overdue, upcoming


def list_tasks_for_user(
    db: Session,
    user: User,
    *,
    asset_id: uuid.UUID | None = None,
    status_filter: str | None = None,
    priority_filter: str | None = None,
    today: date | None = None,
    completed_limit: int = 20,
) -> list[tuple[MaintenanceTask, str]]:
    today = today or date.today()
    query = (
        db.query(MaintenanceTask)
        .options(
            joinedload(MaintenanceTask.asset).joinedload(Asset.vehicle_meta),
            joinedload(MaintenanceTask.components),
        )
        .filter(MaintenanceTask.asset_id.in_(visible_asset_ids(user)))
    )
    if asset_id is not None:
        query = query.filter(MaintenanceTask.asset_id == asset_id)
    if priority_filter:
        query = query.filter(MaintenanceTask.priority == priority_filter)

    tasks = query.all()

    bucket_order = {"overdue": 0, "due": 1, "upcoming": 2, "paused": 3, "completed": 4}
    paired: list[tuple[MaintenanceTask, str]] = []
    for task in tasks:
        bucket = computed_status(task, today=today)
        if status_filter and bucket != status_filter:
            continue
        paired.append((task, bucket))

    def sort_key(item: tuple[MaintenanceTask, str]):
        task, bucket = item
        due = task.next_due or date.max
        return (bucket_order.get(bucket, 99), due, task.title.lower())

    paired.sort(key=sort_key)

    completed = [p for p in paired if p[1] == "completed"]
    non_completed = [p for p in paired if p[1] != "completed"]
    if len(completed) > completed_limit:
        completed = sorted(
            completed,
            key=lambda p: p[0].updated_at or datetime.min,
            reverse=True,
        )[:completed_limit]
    return non_completed + completed


def _components_for_asset(
    db: Session, asset_id: uuid.UUID, component_ids: list[uuid.UUID]
) -> list[Component]:
    components = (
        db.query(Component)
        .filter(Component.id.in_(component_ids))
        .filter(Component.asset_id == asset_id)
        .all()
    )
    if len(components) != len(set(component_ids)):
        raise ValueError("Component does not belong to this asset")
    return components
