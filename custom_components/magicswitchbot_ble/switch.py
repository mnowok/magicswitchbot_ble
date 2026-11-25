"""Encja przełącznika (tryb ON/OFF) dla Magic Switchbot."""

from __future__ import annotations

import logging

from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoredExtraData, RestoreEntity

from .api import (
    MagicSwitchbotAuthError,
    MagicSwitchbotError,
    MagicSwitchbotNotFound,
    MagicSwitchbotTimeout,
)
from .const import DOMAIN
from .entity import MagicSwitchbotEntity
from .runtime import MagicSwitchbotRuntime

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Konfiguracja platformy switch."""
    runtime: MagicSwitchbotRuntime = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([MagicSwitchbotSwitch(runtime)])


class MagicSwitchbotSwitch(MagicSwitchbotEntity, SwitchEntity, RestoreEntity):
    """Switchbot w trybie "switch" (zaczep na prawdziwy włącznik)."""

    _attr_device_class = SwitchDeviceClass.SWITCH
    _attr_assumed_state = True
    # Brak nazwy -> encja nazywa się jak urządzenie (switch.<nazwa_bota>)

    def __init__(self, runtime: MagicSwitchbotRuntime) -> None:
        """Inicjalizacja."""
        super().__init__(runtime, "switch")

    @property
    def extra_restore_state_data(self) -> RestoredExtraData:
        """Zapamiętuje ON/OFF niezależnie od dostępności.

        Gdy bot jest poza zasięgiem, zapisany stan encji to "unavailable",
        więc sam stan nie wystarczy do odtworzenia ON/OFF po restarcie.
        """
        return RestoredExtraData({"is_on": self._attr_is_on})

    async def async_added_to_hass(self) -> None:
        """Przywraca ostatni znany stan (urządzenie nie raportuje stanu)."""
        await super().async_added_to_hass()

        if (extra := await self.async_get_last_extra_data()) is not None and (
            is_on := extra.as_dict().get("is_on")
        ) is not None:
            self._attr_is_on = bool(is_on)
        elif (
            last_state := await self.async_get_last_state()
        ) is not None and last_state.state in (STATE_ON, STATE_OFF):
            # Wpisy zapisane przez starsze wersje (bez danych dodatkowych).
            self._attr_is_on = last_state.state == STATE_ON

    async def async_turn_on(self, **kwargs: object) -> None:
        """Zamyka (ON) - wysyła turn_on()."""
        await self._async_run("turn_on", True)

    async def async_turn_off(self, **kwargs: object) -> None:
        """Otwiera (OFF) - wysyła turn_off()."""
        await self._async_run("turn_off", False)

    async def _async_run(self, method: str, expected: bool) -> None:
        """Wykonuje komendę i ustawia stan optymistyczny."""
        try:
            result = await getattr(self._runtime.api, method)()
        except MagicSwitchbotNotFound as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="device_not_found",
                translation_placeholders={"address": self._runtime.address},
            ) from err
        except MagicSwitchbotAuthError as err:
            self._runtime.async_handle_auth_failed()
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="invalid_auth",
                translation_placeholders={"address": self._runtime.address},
            ) from err
        except MagicSwitchbotTimeout as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="communication_error",
                translation_placeholders={
                    "address": self._runtime.address,
                    "error": str(err),
                },
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

        self._attr_is_on = expected
        self.async_write_ha_state()