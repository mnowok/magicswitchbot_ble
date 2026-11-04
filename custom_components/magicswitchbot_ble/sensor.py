"""Czujniki baterii i RSSI dla Magic Switchbot."""

from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    EntityCategory,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_ENABLE_BATTERY,
    CONF_ENABLE_RSSI,
    DEFAULT_OPTIONS,
    DOMAIN,
)
from .entity import MagicSwitchbotEntity
from .runtime import MagicSwitchbotRuntime


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Konfiguracja platformy sensor (zależnie od opcji)."""
    runtime: MagicSwitchbotRuntime = hass.data[DOMAIN][entry.entry_id]
    options = {**DEFAULT_OPTIONS, **entry.options}

    entities: list[SensorEntity] = []
    if options[CONF_ENABLE_BATTERY]:
        entities.append(MagicSwitchbotBatterySensor(runtime))
    if options[CONF_ENABLE_RSSI]:
        entities.append(MagicSwitchbotRssiSensor(runtime))

    if entities:
        async_add_entities(entities)


class MagicSwitchbotBatterySensor(MagicSwitchbotEntity, SensorEntity):
    """Poziom baterii (z reklam BLE, uzupełniany odczytem GATT)."""

    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_translation_key = "battery"

    def __init__(self, runtime: MagicSwitchbotRuntime) -> None:
        """Inicjalizacja."""
        super().__init__(runtime, "battery")

    @property
    def native_value(self) -> int | None:
        """Poziom baterii w %."""
        return self._runtime.battery


class MagicSwitchbotRssiSensor(MagicSwitchbotEntity, SensorEntity):
    """Siła sygnału (diagnostyka), z reklam BLE."""

    _attr_device_class = SensorDeviceClass.SIGNAL_STRENGTH
    _attr_native_unit_of_measurement = SIGNAL_STRENGTH_DECIBELS_MILLIWATT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False
    _attr_translation_key = "rssi"

    def __init__(self, runtime: MagicSwitchbotRuntime) -> None:
        """Inicjalizacja."""
        super().__init__(runtime, "rssi")

    @property
    def native_value(self) -> int | None:
        """RSSI w dBm."""
        return self._runtime.rssi