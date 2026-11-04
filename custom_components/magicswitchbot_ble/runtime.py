"""Wspólny stan jednego Magic Switchbota (bateria, RSSI, firmware)."""

from __future__ import annotations

import logging
from collections.abc import Callable

from homeassistant.components.bluetooth import (
    BluetoothCallbackMatcher,
    BluetoothChange,
    BluetoothScanningMode,
    BluetoothServiceInfoBleak,
    async_register_callback,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo

from .api import MagicSwitchbotBLE, MagicSwitchbotError
from .const import (
    CONF_COMMAND_TIMEOUT,
    CONF_RETRY_COUNT,
    DEFAULT_OPTIONS,
    DOMAIN,
    MANUFACTURER,
    MODEL,
)
from .util import normalize_mac, parse_battery, parse_password_enabled

_LOGGER = logging.getLogger(__name__)


class MagicSwitchbotRuntime:
    """Trzyma stan i udostępnia go wszystkim encjom jednego bota."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Inicjalizacja."""
        self.hass = hass
        self.entry = entry
        options = {**DEFAULT_OPTIONS, **entry.options}

        self.address: str = str(entry.data[CONF_ADDRESS]).upper()
        self.unique_id: str = normalize_mac(self.address)
        self.api = MagicSwitchbotBLE(
            hass,
            self.address,
            retry_count=int(options[CONF_RETRY_COUNT]),
            command_timeout=int(options[CONF_COMMAND_TIMEOUT]),
        )

        self.battery: int | None = None
        self.rssi: int | None = None
        self.firmware: str | None = None
        self.chip_type: str | None = None
        self.password_enabled: bool | None = None

        self._listeners: list[Callable[[], None]] = []
        self._unsub_adv: Callable[[], None] | None = None

    # ---- Device registry ------------------------------------------------
    @property
    def device_info(self) -> DeviceInfo:
        """Wszystkie encje trafiają pod JEDNO urządzenie."""
        return DeviceInfo(
            identifiers={(DOMAIN, self.unique_id)},
            connections={(CONNECTION_BLUETOOTH, self.address)},
            manufacturer=MANUFACTURER,
            model=MODEL,
            sw_version=self.firmware,
            hw_version=self.chip_type,
            serial_number=self.unique_id.upper(),
        )

    # ---- Listenery encji ------------------------------------------------
    @callback
    def async_add_listener(self, update_callback: Callable[[], None]) -> Callable[[], None]:
        """Rejestruje encję jako słuchacza zmian stanu."""
        self._listeners.append(update_callback)

        @callback
        def remove_listener() -> None:
            if update_callback in self._listeners:
                self._listeners.remove(update_callback)

        return remove_listener

    @callback
    def async_update_listeners(self) -> None:
        """Powiadamia encje o zmianie stanu."""
        for update_callback in list(self._listeners):
            update_callback()

    # ---- Start / stop ---------------------------------------------------
    @callback
    def async_start(self) -> None:
        """Nasłuch reklam BLE (bateria/RSSI bez łączenia) + odczyt info."""
        self._unsub_adv = async_register_callback(
            self.hass,
            self._async_on_advertisement,
            BluetoothCallbackMatcher(address=self.address),
            BluetoothScanningMode.PASSIVE,
        )
        self.entry.async_create_background_task(
            self.hass,
            self._async_fetch_info(),
            f"{DOMAIN} {self.address} basic info",
            eager_start=True,
        )

    @callback
    def async_stop(self) -> None:
        """Sprzątanie przy wyładowaniu wpisu."""
        if self._unsub_adv is not None:
            self._unsub_adv()
            self._unsub_adv = None
        self._listeners.clear()

    # ---- Reklamy BLE ----------------------------------------------------
    @callback
    def _async_on_advertisement(
        self, service_info: BluetoothServiceInfoBleak, change: BluetoothChange
    ) -> None:
        """Aktualizuje baterię i RSSI z reklamy (bez otwierania połączenia)."""
        changed = False

        if (battery := parse_battery(service_info.manufacturer_data)) is not None:
            if battery != self.battery:
                self.battery = battery
                changed = True

        if service_info.rssi is not None and service_info.rssi != self.rssi:
            self.rssi = service_info.rssi
            changed = True

        if changed:
            self.async_update_listeners()

    # ---- Jednorazowy odczyt przez GATT ----------------------------------
    async def _async_fetch_info(self) -> None:
        """Pobiera firmware/chip/PIN i baterię z GATT (jeśli bot jest w zasięgu)."""
        try:
            info = await self.api.get_basic_info()
        except MagicSwitchbotError as err:
            _LOGGER.debug(
                "MagicSwitchbot[%s]: nie udało się odczytać informacji: %s",
                self.address,
                err,
            )
            return

        if not info:
            return

        if (battery := info.get("battery")) is not None:
            self.battery = battery
        self.firmware = info.get("firmware") or self.firmware
        self.chip_type = info.get("chip_type") or self.chip_type

        password_enabled = info.get("password_enabled")
        if password_enabled is not None:
            self.password_enabled = bool(password_enabled)

        if self.password_enabled:
            _LOGGER.warning(
                "MagicSwitchbot[%s]: urządzenie ma włączony PIN. Ta integracja "
                "wysyła komendy bez PIN-u, więc komendy mogą być odrzucane.",
                self.address,
            )

        self._async_update_device_registry()
        self.async_update_listeners()

    @callback
    def _async_update_device_registry(self) -> None:
        """Uzupełnia firmware/chip w rejestrze urządzeń."""
        registry = dr.async_get(self.hass)
        device = registry.async_get_device(identifiers={(DOMAIN, self.unique_id)})
        if device is None:
            return
        registry.async_update_device(
            device.id,
            sw_version=self.firmware,
            hw_version=self.chip_type,
        )

    @callback
    def async_password_enabled_from_adv(
        self, manufacturer_data: dict[int, bytes]
    ) -> bool | None:
        """Pomocniczo: informacja o PIN-ie z samej reklamy."""
        return parse_password_enabled(manufacturer_data)