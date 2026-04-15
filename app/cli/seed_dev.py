"""Seed the local dev database with a realistic two-person household dataset.

    python -m app.cli.seed_dev           # seed (refuses if data already exists)
    python -m app.cli.seed_dev --reset   # wipe seed users + their data, reseed

Refuses to run in production-equivalent settings. Exercises the same service
functions the web app uses, so schema drift breaks the script loudly.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.database import get_session_factory
from app.models.asset import Asset
from app.models.service_record import ServiceRecord
from app.models.user import User
from app.services.assets import create_asset
from app.services.components import COMPONENT_PRESETS, create_component
from app.services.fuel_logs import create_fuel_log
from app.services.maintenance_tasks import complete_task, create_task
from app.services.service_records import create_service_record

SEED_PASSWORD = "seeddev"
SEED_EMAILS_BY_USERNAME = {
    "demo_admin": "demo_admin@example.test",
    "demo_user": "demo_user@example.test",
}
SEED_USERNAMES = tuple(SEED_EMAILS_BY_USERNAME)
SEED_EMAILS = tuple(SEED_EMAILS_BY_USERNAME.values())


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--reset",
        action="store_true",
        help=(
            "Delete seed users (demo_admin, demo_user) and all their data "
            "before reseeding."
        ),
    )
    return parser.parse_args(argv)


def run(
    argv: list[str] | None = None,
    *,
    session: Session | None = None,
    settings: Settings | None = None,
) -> int:
    args = _parse_args(argv)
    settings = settings or get_settings()

    if settings.is_production:
        print(
            "refusing to seed: dev seed data only runs in local/dev debug settings",
            file=sys.stderr,
        )
        return 2

    owns_session = session is None
    session = session or get_session_factory()()
    try:
        existing = _existing_seed_accounts(session)
        if _has_seed_identity_collision(existing):
            print(
                "refusing to seed: a non-seed user is using a reserved seed identity",
                file=sys.stderr,
            )
            return 1

        if existing and not args.reset:
            print(
                "seed users already present; pass --reset to wipe and reseed",
                file=sys.stderr,
            )
            return 1

        if args.reset:
            _reset(session)

        counts = _seed(session)
    finally:
        if owns_session:
            session.close()

    print(
        "seeded "
        f"users={counts['users']} assets={counts['assets']} "
        f"components={counts['components']} records={counts['records']} "
        f"fuel_logs={counts['fuel_logs']} tasks={counts['tasks']}"
    )
    return 0


def _reset(session: Session) -> None:
    """Delete seed users and cascade-delete all assets they own."""
    seed_users = session.query(User).filter(User.username.in_(SEED_USERNAMES)).all()
    for user in seed_users:
        # Delete assets owned by this user; cascades wipe records, docs, tasks,
        # components. Service records created by a seed user against *shared*
        # assets owned by someone else also need cleanup; in practice the seed
        # always runs as a self-contained pair, so deleting these users' assets
        # is sufficient.
        assets = session.query(Asset).filter(Asset.created_by_id == user.id).all()
        for asset in assets:
            session.delete(asset)
        session.delete(user)
    session.commit()


def _existing_seed_accounts(session: Session) -> list[User]:
    return (
        session.query(User)
        .filter(or_(User.username.in_(SEED_USERNAMES), User.email.in_(SEED_EMAILS)))
        .all()
    )


def _has_seed_identity_collision(users: list[User]) -> bool:
    return any(
        user.email != SEED_EMAILS_BY_USERNAME.get(user.username)
        for user in users
    )


def _seed(session: Session) -> dict[str, int]:
    today = date.today()

    demo_admin = _make_user(
        session,
        "demo_admin",
        "Demo Admin",
        SEED_EMAILS_BY_USERNAME["demo_admin"],
        role="admin",
    )
    demo_user = _make_user(
        session,
        "demo_user",
        "Demo User",
        SEED_EMAILS_BY_USERNAME["demo_user"],
        role="user",
    )
    session.commit()

    counts = {
        "users": 2,
        "assets": 0,
        "components": 0,
        "records": 0,
        "fuel_logs": 0,
        "tasks": 0,
    }

    # --- Vehicle: 2018 Honda CR-V (shared, demo admin's) ---------------------
    crv = create_asset(
        session,
        {
            "name": "Honda CR-V",
            "category": "vehicle",
            "make": "Honda",
            "model_name": "CR-V",
            "year": 2018,
            "location": "Driveway",
            "purchase_date": today - timedelta(days=1400),
            "purchase_price": Decimal("24500.00"),
            "purchase_vendor": "Honda of Downtown",
            "current_mileage": 72400,
            "fuel_type": "gasoline",
            "vin": "TESTVIN0000000000",
            "license_plate": "DEMO-123",
            "insurance_info": "Example Insurance, policy DEMO-000",
        },
        demo_admin,
    )
    crv.visibility = "shared"
    session.commit()
    counts["assets"] += 1
    crv_components = _seed_components(session, crv, "vehicle")
    counts["components"] += len(crv_components)

    counts["records"] += _seed_records(
        session,
        crv,
        demo_admin,
        [
            (
                today - timedelta(days=520),
                "Oil change + filter",
                "QuickLube",
                "85.00",
                False,
                55200,
                ["oil", "air filter"],
            ),
            (
                today - timedelta(days=360),
                "Brake pads (front)",
                "Mike's Auto",
                "420.00",
                False,
                61200,
                ["brakes"],
            ),
            (today - timedelta(days=240), "Tire rotation", None, "40.00", True, 65800, ["tires"]),
            (
                today - timedelta(days=120),
                "Oil change",
                "QuickLube",
                "92.00",
                False,
                69100,
                ["oil"],
            ),
            (
                today - timedelta(days=30),
                "Battery replacement",
                "AutoZone",
                "189.00",
                True,
                72100,
                ["battery"],
            ),
        ],
        crv_components,
    )
    counts["fuel_logs"] += _seed_fuel_logs(
        session,
        crv,
        demo_admin,
        [
            (today - timedelta(days=150), "17.4", "61.77", 68210, "Costco Gas", True),
            (today - timedelta(days=112), "16.8", "58.46", 68895, "Shell", True),
            (today - timedelta(days=75), "15.9", "54.70", 69525, "Mobil", True),
            (today - timedelta(days=42), "13.2", "45.54", 70880, "Costco Gas", False),
            (today - timedelta(days=18), "16.6", "56.27", 71980, "Sunoco", True),
            (today - timedelta(days=5), "10.8", "36.71", 72400, "Costco Gas", True),
        ],
    )

    # --- Vehicle: 2021 Trek bike (demo user's personal) ----------------------
    bike = create_asset(
        session,
        {
            "name": "Trek Domane",
            "category": "vehicle",
            "make": "Trek",
            "model_name": "Domane AL 4",
            "year": 2021,
            "location": "Garage",
            "purchase_date": today - timedelta(days=900),
            "purchase_price": Decimal("1299.00"),
            "purchase_vendor": "Local Spokes",
            "current_mileage": 3420,
            "fuel_type": "none",
        },
        demo_user,
    )
    bike.visibility = "personal"
    session.commit()
    counts["assets"] += 1
    bike_components = _seed_components(session, bike, "vehicle")
    counts["components"] += len(bike_components)
    counts["records"] += _seed_records(
        session,
        bike,
        demo_user,
        [
            (today - timedelta(days=400), "New chain", "Local Spokes", "45.00", False, 1200, []),
            (today - timedelta(days=150), "Tune-up", "Local Spokes", "75.00", False, 2500, []),
        ],
        bike_components,
    )

    # --- Appliance: LG washer (shared, demo admin's) -------------------------
    washer = create_asset(
        session,
        {
            "name": "LG Front-Load Washer",
            "category": "appliance",
            "make": "LG",
            "model_name": "WM3900HWA",
            "year": 2022,
            "location": "Laundry Room",
            "purchase_date": today - timedelta(days=700),
            "purchase_price": Decimal("899.00"),
            "purchase_vendor": "Home Depot",
            "warranty_expiration": today + timedelta(days=400),
        },
        demo_admin,
    )
    counts["assets"] += 1
    washer_components = _seed_components(session, washer, "appliance")
    counts["components"] += len(washer_components)
    counts["records"] += _seed_records(
        session,
        washer,
        demo_admin,
        [
            (
                today - timedelta(days=300),
                "Clean drain pump filter",
                None,
                "0.00",
                True,
                None,
                ["filter"],
            ),
            (
                today - timedelta(days=90),
                "Replaced door gasket",
                "Sears Repair",
                "215.00",
                False,
                None,
                [],
            ),
        ],
        washer_components,
    )

    # --- Appliance: Bosch dishwasher (shared, demo admin's) ------------------
    dishwasher = create_asset(
        session,
        {
            "name": "Bosch 800 Dishwasher",
            "category": "appliance",
            "make": "Bosch",
            "model_name": "SHPM88Z75N",
            "year": 2023,
            "location": "Kitchen",
            "purchase_date": today - timedelta(days=420),
            "purchase_price": Decimal("1249.00"),
            "purchase_vendor": "AJ Madison",
            "warranty_expiration": today + timedelta(days=300),
        },
        demo_admin,
    )
    counts["assets"] += 1
    dishwasher_components = _seed_components(session, dishwasher, "appliance")
    counts["components"] += len(dishwasher_components)
    counts["records"] += _seed_records(
        session,
        dishwasher,
        demo_admin,
        [
            (today - timedelta(days=180), "Descale cycle", None, "12.00", True, None, []),
            (
                today - timedelta(days=45),
                "Replace spray arm",
                "Bosch Service",
                "140.00",
                False,
                None,
                [],
            ),
        ],
        dishwasher_components,
    )

    # --- Home system: Carrier HVAC (shared, demo admin's) --------------------
    hvac = create_asset(
        session,
        {
            "name": "Carrier Central HVAC",
            "category": "home_system",
            "make": "Carrier",
            "model_name": "Infinity 26",
            "year": 2020,
            "location": "Basement + Attic",
            "purchase_date": today - timedelta(days=1600),
            "purchase_price": Decimal("8400.00"),
            "purchase_vendor": "Comfort Pros HVAC",
        },
        demo_admin,
    )
    counts["assets"] += 1
    hvac_components = _seed_components(session, hvac, "home_system")
    counts["components"] += len(hvac_components)
    counts["records"] += _seed_records(
        session,
        hvac,
        demo_admin,
        [
            (
                today - timedelta(days=500),
                "Seasonal tune-up",
                "Comfort Pros",
                "220.00",
                False,
                None,
                ["compressor"],
            ),
            (today - timedelta(days=250), "Filter change", None, "30.00", True, None, ["filter"]),
            (today - timedelta(days=150), "Filter change", None, "30.00", True, None, ["filter"]),
            (
                today - timedelta(days=60),
                "Refrigerant top-up",
                "Comfort Pros",
                "185.00",
                False,
                None,
                ["refrigerant"],
            ),
        ],
        hvac_components,
    )

    # --- Tech: Synology NAS (demo admin's personal) --------------------------
    nas = create_asset(
        session,
        {
            "name": "Synology NAS",
            "category": "tech",
            "make": "Synology",
            "model_name": "DS923+",
            "year": 2023,
            "location": "Office closet",
            "purchase_date": today - timedelta(days=500),
            "purchase_price": Decimal("649.00"),
            "purchase_vendor": "B&H Photo",
        },
        demo_admin,
    )
    nas.visibility = "personal"
    session.commit()
    counts["assets"] += 1
    nas_components = _seed_components(session, nas, "tech")
    counts["components"] += len(nas_components)
    counts["records"] += _seed_records(
        session,
        nas,
        demo_admin,
        [
            (
                today - timedelta(days=200),
                "DSM firmware upgrade to 7.2.1",
                None,
                "0.00",
                True,
                None,
                ["firmware"],
            ),
            (
                today - timedelta(days=90),
                "Replaced bay 3 drive (WD Red 8TB)",
                "Newegg",
                "219.00",
                True,
                None,
                ["storage"],
            ),
        ],
        nas_components,
    )

    # --- Maintenance tasks: one of every schedule type + one completed -------

    # Interval task, overdue by date
    create_task(
        session,
        crv.id,
        {
            "title": "Engine oil change",
            "description": "5W-30 full synthetic, replace oil filter.",
            "schedule_type": "interval",
            "interval_value": 6,
            "interval_unit": "months",
            "next_due": today - timedelta(days=35),
            "priority": "high",
        },
        demo_admin,
        component_ids=[c.id for c in crv_components if c.name in ("oil", "air filter")],
    )
    counts["tasks"] += 1

    # Calendar task, upcoming within 14 days
    create_task(
        session,
        hvac.id,
        {
            "title": "Seasonal HVAC filter change",
            "description": "Replace 20x25x1 MERV 11.",
            "schedule_type": "calendar",
            "calendar_month": ((today + timedelta(days=10)).month),
            "calendar_day": ((today + timedelta(days=10)).day),
            "next_due": today + timedelta(days=10),
            "priority": "normal",
        },
        demo_admin,
        component_ids=[c.id for c in hvac_components if c.name == "filter"],
    )
    counts["tasks"] += 1

    # One-time task, future
    create_task(
        session,
        dishwasher.id,
        {
            "title": "Register extended warranty before it lapses",
            "schedule_type": "one_time",
            "next_due": today + timedelta(days=60),
            "priority": "low",
        },
        demo_admin,
    )
    counts["tasks"] += 1

    # Usage-based task, overdue by mileage (bike is at 3420, trigger at 3000)
    create_task(
        session,
        bike.id,
        {
            "title": "Replace bike chain",
            "description": "Swap chain every 3000 km.",
            "schedule_type": "usage",
            "usage_trigger_label": "km",
            "usage_trigger_value": 3000,
            "next_due_usage_value": 3000,
            "priority": "normal",
        },
        demo_user,
    )
    counts["tasks"] += 1

    # Completed task: link an existing washer record so last_completed_record_id
    # gets exercised.
    washer_gasket_record = (
        session.query(ServiceRecord)
        .filter_by(asset_id=washer.id)
        .order_by(ServiceRecord.service_date.desc())
        .first()
    )
    completed_task = create_task(
        session,
        washer.id,
        {
            "title": "Annual washer gasket inspection",
            "schedule_type": "interval",
            "interval_value": 1,
            "interval_unit": "years",
            "next_due": today - timedelta(days=400),
            "priority": "low",
        },
        demo_admin,
    )
    complete_task(session, completed_task, washer_gasket_record)
    counts["tasks"] += 1

    return counts


def _make_user(
    session: Session, username: str, display_name: str, email: str, *, role: str
) -> User:
    user = User(
        username=username,
        display_name=display_name,
        email=email,
        role=role,
        password_hash="",
        wizard_completed=True,
    )
    user.set_password(SEED_PASSWORD)
    session.add(user)
    session.flush()
    return user


def _seed_components(session: Session, asset: Asset, category: str) -> list:
    components = []
    for name in COMPONENT_PRESETS.get(category, []):
        components.append(create_component(session, asset.id, {"name": name}))
    return components


def _seed_records(
    session: Session,
    asset: Asset,
    user: User,
    entries: list[tuple],
    components: list,
) -> int:
    by_name = {c.name: c for c in components}
    for service_date, title, vendor, cost, is_diy, mileage, component_names in entries:
        component_ids = [by_name[n].id for n in component_names if n in by_name]
        create_service_record(
            session,
            asset.id,
            {
                "title": title,
                "service_date": service_date,
                "vendor": vendor,
                "cost": Decimal(cost),
                "is_diy": is_diy,
                "mileage_at_service": mileage,
            },
            user,
            component_ids=component_ids or None,
        )
    return len(entries)


def _seed_fuel_logs(
    session: Session,
    asset: Asset,
    user: User,
    entries: list[tuple],
) -> int:
    for fillup_date, gallons, total_cost, mileage, station, full_tank in entries:
        create_fuel_log(
            session,
            asset,
            {
                "fillup_date": fillup_date,
                "gallons": Decimal(gallons),
                "total_cost": Decimal(total_cost),
                "mileage_at_fillup": mileage,
                "station": station,
                "full_tank": full_tank,
            },
            user,
        )
    return len(entries)


if __name__ == "__main__":
    sys.exit(run())
