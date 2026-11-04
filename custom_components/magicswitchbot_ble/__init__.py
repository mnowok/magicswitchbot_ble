"""Magic Switchbot przez Bluetooth (proxy ESPHome) dla Home Assistant."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import (
    CONF_ENABLE_BATTERY,
    CONF_ENABLE_BUTTON,
    CONF_ENABLE_RSSI,
    CONF_ENABLE_SWITCH,
    DEFAULT_OPTIONS,
    DOMAIN,
)
from .runtime import MagicSwitchbotRuntime

_LOGGER = logging.getLogger(__name__)

type MagicSwitchbotConfigEntry = ConfigEntry[MagicSwitchbotRuntime]


def platforms_for(entry: ConfigEntry) -> list[Platform]:
    """Lista platform zależna od opcji wpisu."""
    options = {**DEFAULT_OPTIONS, **entry.options}
    platforms: list[Platform] = []

    if options[CONF_ENABLE_SWITCH]:
        platforms.append(Platform.SWITCH)
    if options[CONF_ENABLE_BUTTON]:
        platforms.append(Platform.BUTTON)
    if options[CONF_ENABLE_BATTERY] or options[CONF_ENABLE_RSSI]:
        platforms.append(Platform.SENSOR)

    return platforms


async def async_setup_entry(
    hass: HomeAssistant, entry: MagicSwitchbotConfigEntry
) -> bool:
    """Konfiguracja wpisu."""
    runtime = MagicSwitchbotRuntime(hass, entry)
    entry.runtime_data = runtime
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = runtime

    runtime.async_start()

    platforms = platforms_for(entry)
    if platforms:
        await hass.config_entries.async_forward_entry_setups(entry, platforms)

    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: MagicSwitchbotConfigEntry
) -> bool:
    """Wyładowanie wpisu."""
    platforms = platforms_for(entry)
    unload_ok = True
    if platforms:
        unload_ok = await hass.config_entries.async_unload_platforms(entry, platforms)

    if unload_ok:
        runtime: MagicSwitchbotRuntime | None = hass.data.get(DOMAIN, {}).pop(
            entry.entry_id, None
        )
        if runtime is not None:
            runtime.async_stop()

    return unload_ok


async def _async_options_updated(
    hass: HomeAssistant, entry: MagicSwitchbotConfigEntry
) -> None:
    """Przeładowanie wpisu po zmianie opcji."""
    await hass.config_entries.async_reload(entry.entry_id)