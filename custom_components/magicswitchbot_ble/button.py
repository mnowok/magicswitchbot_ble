"""Encja przycisku (tryb PUSH) dla Magic Switchbot."""

from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import MagicSwitchbotError, MagicSwitchbotNotFound
from .const import DOMAIN
from .entity import MagicSwitchbotEntity
from .runtime import MagicSwitchbotRuntime

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Konfiguracja platformy button."""
    runtime: MagicSwitchbotRuntime = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([MagicSwitchbotPushButton(runtime)])


class MagicSwitchbotPushButton(MagicSwitchbotEntity, ButtonEntity):
    """Przycisk "push" - naciska i wraca."""

    _attr_translation_key = "push"
    _attr_icon = "mdi:gesture-tap-button"

    def __init__(self, runtime: MagicSwitchbotRuntime) -> None:
        """Inicjalizacja."""
        super().__init__(runtime, "push")

    async def async_press(self) -> None:
        """Wysyła push()."""
        try:
            result = await self._runtime.api.push()
        except MagicSwitchbotNotFound as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="device_not_found",
                translation_placeholders={"address": self._runtime.address},
            ) from err
        except MagicSwitchbotError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="communication_error",
                translation_placeholders={
                    "address": self._runtime.address,
                    "error": str(err),
                },
            ) from err

        if not result:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="command_failed",
                translation_placeholders={"address": self._runtime.address},
            )