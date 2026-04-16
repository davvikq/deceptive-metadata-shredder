"""Bundled device database access."""

from __future__ import annotations

import json
import random
from functools import lru_cache

from dms.config import DATA_DIR
from dms.core.models import Device


@lru_cache(maxsize=1)
def _load_devices() -> list[Device]:
    payload = json.loads((DATA_DIR / "devices.json").read_text(encoding="utf-8"))
    return [Device(**item) for item in payload]


def get_all_makes() -> list[str]:
    """Return all makes sorted alphabetically."""

    return sorted({device.make for device in _load_devices()})


def get_all_devices() -> list[Device]:
    """Return all bundled devices."""

    return list(_load_devices())


def get_models_by_make(make: str) -> list[Device]:
    """Return devices that match the requested make."""

    return sorted(
        [device for device in _load_devices() if device.make == make],
        key=lambda item: item.model,
    )


def get_device(device_id: str) -> Device:
    """Return a single device by its identifier."""

    for device in _load_devices():
        if device.id == device_id:
            return device
    raise KeyError(f"Unknown device id: {device_id}")


def get_random_vintage() -> Device:
    """Return a random camera device released before 2005."""

    vintage = [device for device in _load_devices() if device.year <= 2005]
    if not vintage:
        raise RuntimeError("Vintage device pool is empty.")
    return random.choice(vintage)


def get_random_device(exclude_make: str | None = None) -> Device:
    """Return a random device from the bundled database."""

    devices = _load_devices()
    if exclude_make:
        devices = [device for device in devices if device.make.lower() != exclude_make.lower()]
    if not devices:
        raise RuntimeError("Device pool is empty.")
    return random.choice(devices)
