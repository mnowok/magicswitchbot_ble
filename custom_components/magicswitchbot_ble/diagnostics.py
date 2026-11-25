"""Diagnostyka Magic Switchbot (przycisk "Pobierz diagnostykę")."""

from __future__ import annotations

from typing import Any

from homeassistant.components.bluetooth import (
    async_last_service_info,
    async_scanner_count,
)
from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD
from homeassistant.core import HomeAssistant

from .runtime import MagicSwitchbotRuntime
from .util import parse_battery, parse_password_enabled

TO_REDACT = {CONF_PASSWORD}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> dict[str, Any]:
    """Zwraca stan wpisu, bota i ostatniej reklamy BLE."""
    runtime: MagicSwitchbotRuntime = entry.runtime_data

    service_info = async_last_service_info(
        hass, runtime.address, connectable=True
    )
    advertisement: dict[str, Any] | None = None
    if service_info is not None:
        advertisement = {
            "name": service_info.name,
            "address": service_info.address,
            "rssi": service_info.rssi,
            "source": service_info.source,
            "connectable": service_info.connectable,
            "time": service_info.time,
            "service_uuids": service_info.service_uuids,
            "manufacturer_data": {
                str(company_id): payload.hex()
                for company_id, payload in service_info.manufacturer_data.items()
            },
            "parsed_battery": parse_battery(service_info.manufacturer_data),
            "parsed_password_enabled": parse_password_enabled(
                service_info.manufacturer_data
            ),
        }

    return {
        "entry": {
            "title": entry.title,
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": dict(entry.options),
        },
        "device": {
            "available": runtime.available,
            "battery": runtime.battery,
            "rssi": runtime.rssi,
            "firmware": runtime.firmware,
            "chip_type": runtime.chip_type,
            "password_enabled": runtime.password_enabled,
            "password_configured": bool(entry.data.get(CONF_PASSWORD)),
        },
        "bluetooth": {
            "connectable_scanners": async_scanner_count(hass, connectable=True),
            "last_advertisement": advertisement,
        },
    }
