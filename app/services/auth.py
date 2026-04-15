from collections import defaultdict, deque
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.models.user import User

# Login rate-limit state is intentionally per-process and in-memory: it resets
# on restart and is not shared across uvicorn workers. That is acceptable for
# the 2-user deployment this app targets running a single worker. If scaling
# to multiple workers or hosts, swap this for Redis (or a DB-backed counter).
_failed_login_attempts: dict[str, deque[datetime]] = defaultdict(deque)


def authenticate_user(db: Session, username: str, password: str) -> User | None:
    user = db.query(User).filter(User.username == username).first()
    if user and user.is_active and user.verify_password(password):
        return user
    return None


def get_user_by_username(db: Session, username: str) -> User | None:
    return db.query(User).filter(User.username == username).first()


def get_user_by_email(db: Session, email: str) -> User | None:
    return db.query(User).filter(User.email == email).first()


def update_profile(db: Session, user: User, display_name: str, email: str) -> User:
    user.display_name = display_name
    user.email = email
    db.commit()
    db.refresh(user)
    return user


def update_notification_preferences(
    db: Session,
    user: User,
    *,
    enabled: bool,
    frequency: str,
    digest_time: str,
) -> User:
    if frequency not in {"daily", "weekly"}:
        raise ValueError("Invalid digest frequency")
    if not _valid_digest_time(digest_time):
        raise ValueError("Digest time must use HH:MM format")

    user.email_digest_enabled = enabled
    user.email_digest_frequency = frequency
    user.email_digest_time = digest_time
    db.commit()
    db.refresh(user)
    return user


def change_password(db: Session, user: User, new_password: str) -> User:
    user.set_password(new_password)
    user.session_version += 1
    db.commit()
    db.refresh(user)
    return user


def list_users(db: Session) -> list[User]:
    return db.query(User).order_by(User.role.desc(), User.display_name, User.username).all()


def active_admin_count(db: Session) -> int:
    return db.query(User).filter(User.role == "admin", User.is_active.is_(True)).count()


def update_user_admin(
    db: Session,
    user: User,
    *,
    display_name: str,
    email: str,
    role: str,
) -> User:
    user.display_name = display_name
    user.email = email
    user.role = role
    db.commit()
    db.refresh(user)
    return user


def reset_user_password(db: Session, user: User, new_password: str) -> User:
    user.set_password(new_password)
    user.session_version += 1
    db.commit()
    db.refresh(user)
    return user


def set_user_active(db: Session, user: User, *, is_active: bool) -> User:
    if user.is_active != is_active:
        user.is_active = is_active
        user.session_version += 1
        db.commit()
        db.refresh(user)
    return user


def create_user(
    db: Session,
    *,
    username: str,
    display_name: str,
    email: str,
    role: str,
    password: str,
) -> User:
    user = User(
        username=username,
        display_name=display_name,
        email=email,
        role=role,
        password_hash="",
        wizard_completed=False,
    )
    user.set_password(password)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _rate_limit_key(username: str, client_host: str) -> str:
    return f"{client_host}:{username.strip().lower()}"


def login_is_rate_limited(
    username: str,
    client_host: str,
    max_attempts: int,
    window_seconds: int,
) -> bool:
    now = datetime.now()
    cutoff = now - timedelta(seconds=window_seconds)
    attempts = _failed_login_attempts[_rate_limit_key(username, client_host)]
    while attempts and attempts[0] < cutoff:
        attempts.popleft()
    return len(attempts) >= max_attempts


def record_failed_login(username: str, client_host: str) -> None:
    _failed_login_attempts[_rate_limit_key(username, client_host)].append(datetime.now())


def clear_failed_logins(username: str, client_host: str) -> None:
    _failed_login_attempts.pop(_rate_limit_key(username, client_host), None)


def update_last_login(db: Session, user: User) -> None:
    user.last_login = datetime.now()
    db.commit()


def _valid_digest_time(value: str) -> bool:
    if len(value) != 5 or value[2] != ":":
        return False
    hour, minute = value.split(":", 1)
    if not hour.isdigit() or not minute.isdigit():
        return False
    return 0 <= int(hour) <= 23 and 0 <= int(minute) <= 59
