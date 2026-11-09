"""Magic Switchbot przez Bluetooth (proxy ESPHome) dla Home Assistant."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er

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
    """Zwróć platformy wymagane przez aktualne opcje wpisu."""
    options = {**DEFAULT_OPTIONS, **entry.options}
    platforms: list[Platform] = []

    if options[CONF_ENABLE_SWITCH]:
        platforms.append(Platform.SWITCH)

    if options[CONF_ENABLE_BUTTON]:
        platforms.append(Platform.BUTTON)

    if options[CONF_ENABLE_BATTERY] or options[CONF_ENABLE_RSSI]:
        platforms.append(Platform.SENSOR)

    return platforms


@callback
def _async_remove_disabled_entities(
    hass: HomeAssistant,
    entry: MagicSwitchbotConfigEntry,
    runtime: MagicSwitchbotRuntime,
) -> None:
    """Usuń wpisy konkretnych encji wyłączonych w opcjach."""
    options = {**DEFAULT_OPTIONS, **entry.options}
    registry = er.async_get(hass)

    # Klucze odpowiadają argumentom przekazywanym
    # do konstruktora MagicSwitchbotEntity w plikach platform.
    entity_definitions = (
        (Platform.SWITCH, "switch", CONF_ENABLE_SWITCH),
        (Platform.BUTTON, "push", CONF_ENABLE_BUTTON),
        (Platform.SENSOR, "battery", CONF_ENABLE_BATTERY),
        (Platform.SENSOR, "rssi", CONF_ENABLE_RSSI),
    )

    disabled_entities = {
        (platform.value, f"{runtime.unique_id}_{key}")
        for platform, key, option in entity_definitions
        if not options[option]
    }

    if not disabled_entities:
        return

    for registry_entry in er.async_entries_for_config_entry(
        registry, entry.entry_id
    ):
        # Usuwamy wyłącznie encje należące do tej integracji.
        if registry_entry.platform != DOMAIN:
            continue

        entity_identity = (
            registry_entry.domain,
            registry_entry.unique_id,
        )

        if entity_identity not in disabled_entities:
            continue

        _LOGGER.debug(
            "Usuwanie encji %s wyłączonej w opcjach wpisu %s",
            registry_entry.entity_id,
            entry.entry_id,
        )
        registry.async_remove(registry_entry.entity_id)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MagicSwitchbotConfigEntry,
) -> bool:
    """Skonfiguruj wpis i zapamiętaj uruchamiane platformy."""
    runtime = MagicSwitchbotRuntime(hass, entry)

    # Zapamiętujemy platformy dla tej konkretnej instancji runtime.
    # Przy wyładowaniu opcje mogą już zawierać nowe wartości.
    runtime.forwarded_platforms = platforms_for(entry)

    entry.runtime_data = runtime
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = runtime

    # Przy reload ta funkcja jest wywoływana po udanym unload.
    # Usuwamy stare wpisy przed uruchomieniem nowych platform.
    # Czyszczenie działa również po restarcie Home Assistanta.
    _async_remove_disabled_entities(hass, entry, runtime)

    runtime.async_start()

    if runtime.forwarded_platforms:
        await hass.config_entries.async_forward_entry_setups(
            entry,
            runtime.forwarded_platforms,
        )

    entry.async_on_unload(entry.add_update_listener(_async_options_updated))

    return True


async def async_unload_entry(
    hass: HomeAssistant,
    entry: MagicSwitchbotConfigEntry,
) -> bool:
    """Wyładuj platformy uruchomione przez tę instancję runtime."""
    runtime = entry.runtime_data

    # Nie obliczamy platform ponownie na podstawie entry.options.
    # Nowe opcje mogą pomijać platformę, która nadal działa.
    if runtime.forwarded_platforms:
        unload_ok = await hass.config_entries.async_unload_platforms(
            entry,
            runtime.forwarded_platforms,
        )

        if not unload_ok:
            # Nadal działające encje mogą korzystać z runtime.
            return False

    runtime.async_stop()
    hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)

    return True


async def _async_options_updated(
    hass: HomeAssistant,
    entry: MagicSwitchbotConfigEntry,
) -> None:
    """Przeładuj wpis po zapisaniu nowych opcji."""
    await hass.config_entries.async_reload(entry.entry_id)