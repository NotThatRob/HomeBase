import uuid

from sqlalchemy.orm import Session

from app.models.component import Component

COMPONENT_PRESETS: dict[str, list[str]] = {
    "vehicle": [
        "brakes",
        "oil",
        "tires",
        "battery",
        "transmission",
        "coolant",
        "air filter",
        "wipers",
    ],
    "appliance": ["filter", "motor", "belt", "compressor", "thermostat"],
    "home_system": [
        "filter",
        "compressor",
        "thermostat",
        "ductwork",
        "refrigerant",
    ],
    "tech": ["storage", "certificates", "backups", "firmware"],
}


def get_preset_components(category: str) -> list[str]:
    return COMPONENT_PRESETS.get(category, [])


def list_components(db: Session, asset_id: uuid.UUID) -> list[Component]:
    return (
        db.query(Component)
        .filter(Component.asset_id == asset_id)
        .order_by(Component.name)
        .all()
    )


def get_component(db: Session, component_id: uuid.UUID) -> Component | None:
    return db.query(Component).filter(Component.id == component_id).first()


def create_component(
    db: Session, asset_id: uuid.UUID, data: dict
) -> Component:
    component = Component(asset_id=asset_id, **data)
    db.add(component)
    db.commit()
    db.refresh(component)
    return component


def delete_component(db: Session, component: Component) -> None:
    db.delete(component)
    db.commit()
