"""Helpers for the MagicSwitchbot integration."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Final

from .const import MAGIC_MANUFACTURER_ID, SERVICE_UUID  # <-- brakujący import

MAC_PATTERN: Final = re.compile(r"^([0-9A-F]{2}:){5}[0-9A-F]{2}$")

# Reklama: 6 bajtów MAC + 1 bajt poziomu baterii + 1 bajt "hasło włączone"
ADV_BATTERY_INDEX: Final = 6
ADV_PASSWORD_INDEX: Final = 7
MIN_ADV_LEN: Final = 8


def format_mac(address: str) -> str:
    """Zwraca MAC w formacie AA:BB:CC:DD:EE:FF (albo wejście, jeśli się nie da)."""
    cleaned = re.sub(r"[^0-9A-Fa-f]", "", address).upper()
    if len(cleaned) != 12:
        return address.upper()
    return ":".join(cleaned[i : i + 2] for i in range(0, 12, 2))


def is_valid_mac(address: str) -> bool:
    """Walidacja adresu MAC."""
    return bool(MAC_PATTERN.match(format_mac(address)))


def normalize_mac(address: str) -> str:
    """Stabilny unique_id (bez separatorów, małe litery)."""
    return format_mac(address).replace(":", "").lower()


def _adv_payload(manufacturer_data: Mapping[int, bytes] | None) -> bytes | None:
    """Payload naszej firmy (1282); fallback: pierwszy sensownie długi."""
    if not manufacturer_data:
        return None
    payload = manufacturer_data.get(MAGIC_MANUFACTURER_ID)
    if payload is not None and len(payload) >= MIN_ADV_LEN:
        return payload
    for value in manufacturer_data.values():
        if len(value) >= MIN_ADV_LEN:
            return value
    return None


def parse_battery(manufacturer_data: Mapping[int, bytes] | None) -> int | None:
    """Wyciąga poziom baterii z danych rozgłoszeniowych."""
    payload = _adv_payload(manufacturer_data)
    if payload is None:
        return None
    battery = payload[ADV_BATTERY_INDEX]
    return battery if 0 <= battery <= 100 else None


def parse_password_enabled(
    manufacturer_data: Mapping[int, bytes] | None,
) -> bool | None:
    """Czy urządzenie ma ustawiony PIN (bajt 7 reklamy)."""
    payload = _adv_payload(manufacturer_data)
    if payload is None:
        return None
    return payload[ADV_PASSWORD_INDEX] == 1


def _uuid_matches(service_uuids: Iterable[str] | None) -> bool:
    """Dopasowanie UUID usługi, odporne na short-form i None."""
    target = SERVICE_UUID.lower()
    for raw in service_uuids or ():
        uuid = (raw or "").lower()
        if uuid == target:
            return True
        # niektóre backendy/proxy potrafią zwrócić "fee7"
        if len(uuid) == 4 and uuid == target[4:8]:
            return True
    return False


def is_magicswitchbot(
    name: str | None,
    service_uuids: Iterable[str] | None,
    manufacturer_data: Mapping[int, bytes] | None,
) -> bool:
    """Heurystyka rozpoznawania urządzenia Magic Switchbot.

    Kolejność = siła sygnału. `service_uuids` jest tylko ostatnią deską
    ratunku, bo 0xFEE7 to generyczny UUID używany przez wiele tanich
    modułów BLE — sam w sobie daje false positives.
    """
    if name and "magicswitch" in name.lower():
        return True
    if manufacturer_data and MAGIC_MANUFACTURER_ID in manufacturer_data:
        return True
    return _uuid_matches(service_uuids)