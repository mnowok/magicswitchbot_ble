"""Transport BLE dla MagicSwitchbot po stosie Bluetooth Home Assistant.

Zachowujemy sprawdzony mechanizm: otwieramy czysty tunel BleakClient do
urządzenia widzianego przez HA (lokalny adapter LUB proxy ESPHome), a
następnie podmieniamy w bibliotece ``magicswitchbot.device.establish_connection``
tak, aby zwracała ten gotowy tunel.

Różnica względem wersji 1.x: patch jest instalowany RAZ i korzysta z rejestru
tuneli kluczowanego adresem MAC. Dzięki temu kilka botów może wykonywać
komendy równolegle (wcześniej równoległe wywołania mogły podmienić sobie
klienta BLE).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import bleak

from homeassistant.components.bluetooth import async_ble_device_from_address
from homeassistant.core import HomeAssistant

from magicswitchbot import MagicSwitchbot
import magicswitchbot.device as magicswitchbot_device

from .const import DEFAULT_COMMAND_TIMEOUT, DEFAULT_RETRY_COUNT

_LOGGER = logging.getLogger(__name__)

# Aktywne tunele: "AA:BB:CC:DD:EE:FF" -> połączony klient bleak
_TUNNELS: dict[str, Any] = {}

_PATCH_INSTALLED = False


class MagicSwitchbotError(Exception):
    """Bazowy błąd komunikacji."""


class MagicSwitchbotNotFound(MagicSwitchbotError):
    """Urządzenie nie jest dostępne w stosie Bluetooth HA."""


class MagicSwitchbotTimeout(MagicSwitchbotError):
    """Minął czas oczekiwania na odpowiedź urządzenia."""


def _cancel_disconnect_timer(bot: Any) -> None:
    """Anuluje wewnętrzny timer rozłączenia biblioteki (sprzątanie)."""
    timer = getattr(bot, "_disconnect_timer", None)
    if timer is None:
        return
    try:
        timer.cancel()
        bot._disconnect_timer = None  # noqa: SLF001
    except Exception:  # noqa: BLE001 - sprzątanie nie może wywalić komendy
        pass


def _install_tunnel_patch() -> None:
    """Podmienia establish_connection w bibliotece (idempotentnie)."""
    global _PATCH_INSTALLED

    if _PATCH_INSTALLED:
        return

    original = magicswitchbot_device.establish_connection

    async def establish_connection(
        client_class: Any,
        device: Any,
        name: str,
        disconnected_callback: Any = None,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """Zwraca istniejący tunel HA/ESPHome albo zachowuje się jak oryginał."""
        tunnel = _TUNNELS.get(str(device.address).upper())
        if tunnel is not None:
            _LOGGER.debug(
                "MagicSwitchbot[%s]: używam tunelu HA/ESPHome", device.address
            )
            return tunnel
        return await original(
            client_class, device, name, disconnected_callback, *args, **kwargs
        )

    establish_connection._magicswitchbot_tunnel = True  # type: ignore[attr-defined]
    magicswitchbot_device.establish_connection = establish_connection  # type: ignore[assignment]
    _PATCH_INSTALLED = True
    _LOGGER.debug("MagicSwitchbot: zainstalowano patch tunelu BLE")


class MagicSwitchbotBLE:
    """Klient BLE: jedna komenda = jeden tunel = jedno połączenie."""

    def __init__(
        self,
        hass: HomeAssistant,
        address: str,
        *,
        retry_count: int = DEFAULT_RETRY_COUNT,
        command_timeout: int = DEFAULT_COMMAND_TIMEOUT,
    ) -> None:
        """Inicjalizacja."""
        self.hass = hass
        self.address = address.upper()
        self._retry_count = retry_count
        self._command_timeout = command_timeout
        self._lock = asyncio.Lock()

    # ---- API publiczne -------------------------------------------------
    async def push(self) -> bool:
        """Tryb "push button"."""
        return bool(await self._async_call("push"))

    async def turn_on(self) -> bool:
        """Tryb przełącznika - ON."""
        return bool(await self._async_call("turn_on"))

    async def turn_off(self) -> bool:
        """Tryb przełącznika - OFF."""
        return bool(await self._async_call("turn_off"))

    async def get_battery(self) -> int | None:
        """Odczyt baterii przez GATT."""
        return await self._async_call("get_battery")

    async def get_basic_info(self) -> dict[str, Any] | None:
        """Bateria + firmware + typ芯片a + info o PIN-ie."""
        return await self._async_call("get_basic_info")

    # ---- Wnętrze --------------------------------------------------------
    async def _async_call(self, method: str) -> Any:
        async with self._lock:
            return await self._async_call_locked(method)

    async def _async_call_locked(self, method: str) -> Any:
        ble_device = async_ble_device_from_address(
            self.hass, self.address, connectable=True
        )
        if ble_device is None:
            raise MagicSwitchbotNotFound(
                f"{self.address} nie jest widoczny w stosie Bluetooth"
            )

        _install_tunnel_patch()
        key = self.address
        bot = MagicSwitchbot(
            ble_device, password=None, retry_count=self._retry_count
        )

        try:
            # Ten sam tunel, co w działającej wersji: BleakClient(ble_device)
            async with bleak.BleakClient(ble_device) as client:
                _TUNNELS[key] = client
                _LOGGER.debug(
                    "MagicSwitchbot[%s]: tunel zestawiony, wołam %s()",
                    self.address,
                    method,
                )
                return await asyncio.wait_for(
                    getattr(bot, method)(), self._command_timeout
                )
        except asyncio.TimeoutError as err:
            raise MagicSwitchbotTimeout(
                f"Przekroczono czas {self._command_timeout}s dla {method}()"
            ) from err
        except MagicSwitchbotError:
            raise
        except Exception as err:  # noqa: BLE001 - mapujemy na błąd integracji
            raise MagicSwitchbotError(f"{type(err).__name__}: {err}") from err
        finally:
            _TUNNELS.pop(key, None)
            _cancel_disconnect_timer(bot)