"""Bazowa encja Magic Switchbot."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity
from homeassistant.core import callback

from .runtime import MagicSwitchbotRuntime


class MagicSwitchbotEntity(Entity):
    """Wspólna baza: jedno urządzenie, nasłuch stanu, brak pollingu."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, runtime: MagicSwitchbotRuntime, key: str) -> None:
        """Inicjalizacja."""
        self._runtime = runtime
        self._attr_unique_id = f"{runtime.unique_id}_{key}"

    @property
    def device_info(self) -> DeviceInfo:
        """Device info - dzięki temu wszystkie encje są pod jednym urządzeniem."""
        return self._runtime.device_info

    async def async_added_to_hass(self) -> None:
        """Subskrybuje zmiany stanu runtime."""
        self.async_on_remove(
            self._runtime.async_add_listener(self._handle_runtime_update)
        )

    @callback
    def _handle_runtime_update(self) -> None:
        """Zapisuje nowy stan encji."""
        self.async_write_ha_state()