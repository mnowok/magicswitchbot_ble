"""Transport BLE dla MagicSwitchbot po stosie Bluetooth Home Assistant.

Otwieramy tunel do urządzenia widzianego przez HA (lokalny adapter LUB proxy
ESPHome) przez ``bleak_retry_connector.establish_connection``, a następnie
podmieniamy w bibliotece ``magicswitchbot.device.establish_connection`` tak,
aby zwracała ten gotowy tunel.

Patch jest instalowany RAZ i korzysta z rejestru tuneli kluczowanego adresem
MAC. Dzięki temu kilka botów może wykonywać komendy równolegle.

Ponowienia robimy tutaj, a nie w bibliotece: każda próba dostaje NOWY tunel.
Wewnętrzne ponowienia biblioteki nie mogą działać, bo po błędzie biblioteka
rozłącza tunel, a przy kolejnej próbie dostałaby z powrotem ten sam,
już rozłączony.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Final

from bleak_retry_connector import BleakClientWithServiceCache, establish_connection

from homeassistant.components.bluetooth import async_ble_device_from_address
from homeassistant.core import HomeAssistant

from magicswitchbot import MagicSwitchbot
import magicswitchbot.device as magicswitchbot_device

from .const import DEFAULT_COMMAND_TIMEOUT, DEFAULT_RETRY_COUNT

_LOGGER = logging.getLogger(__name__)

# Aktywne tunele: "AA:BB:CC:DD:EE:FF" -> połączony klient bleak
_TUNNELS: dict[str, Any] = {}

_PATCH_INSTALLED = False

# Metody, które można bezpiecznie powtórzyć po błędzie W TRAKCIE komendy.
# push() do nich nie należy: jeśli komenda doszła, a zginęło tylko
# potwierdzenie, ponowienie oznaczałoby drugie naciśnięcie.
_IDEMPOTENT_METHODS: Final = frozenset(
    {"turn_on", "turn_off", "get_battery", "get_basic_info"}
)

# Przerwa między próbami - proxy ESPHome potrzebuje chwili na zwolnienie slotu.
_RETRY_BACKOFF: Final = 1.0


class MagicSwitchbotError(Exception):
    """Bazowy błąd komunikacji."""


class MagicSwitchbotNotFound(MagicSwitchbotError):
    """Urządzenie nie jest dostępne w stosie Bluetooth HA."""


class MagicSwitchbotTimeout(MagicSwitchbotError):
    """Minął czas oczekiwania na odpowiedź urządzenia."""


class MagicSwitchbotAuthError(MagicSwitchbotError):
    """Urządzenie odrzuciło hasło (PIN)."""


class _RetryableError(MagicSwitchbotError):
    """Nieudana próba, którą można bezpiecznie powtórzyć na nowym tunelu."""


def _describe(err: BaseException) -> str:
    """Czytelny opis błędu BLE do komunikatu dla użytkownika."""
    if isinstance(err, TimeoutError):
        return "brak odpowiedzi w wymaganym czasie"
    if isinstance(err, RuntimeError) and str(err) == "Unreachable":
        # Tak biblioteka zgłasza błąd BLE lub brak odpowiedzi na komendę.
        return "urządzenie nie odpowiedziało albo połączenie BLE zostało przerwane"
    return f"{type(err).__name__}: {err}"


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
        password: str | None = None,
        retry_count: int = DEFAULT_RETRY_COUNT,
        command_timeout: int = DEFAULT_COMMAND_TIMEOUT,
    ) -> None:
        """Inicjalizacja."""
        self.hass = hass
        self.address = address.upper()
        self._password = password or None
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

    async def check_auth(self, password: str | None) -> None:
        """Sprawdza podane hasło (PIN) bez wykonywania żadnej komendy."""
        async with self._lock:
            await self._async_call_locked(None, password or None)

    # ---- Wnętrze --------------------------------------------------------
    async def _async_call(self, method: str) -> Any:
        async with self._lock:
            return await self._async_call_locked(method, self._password)

    async def _async_execute(self, bot: MagicSwitchbot, method: str | None) -> Any:
        """Uwierzytelnia się (token sesji), a potem wykonuje metodę biblioteki."""
        # Biblioteka zwraca False, gdy urządzenie odrzuci hasło, a None przy
        # błędzie komunikacji. Po udanym _auth() metoda nie pobiera już tokenu
        # ponownie, więc liczba operacji BLE się nie zmienia.
        try:
            authenticated = await bot._auth()  # noqa: SLF001
        except Exception as err:  # noqa: BLE001 - komenda jeszcze nie wysłana
            raise _RetryableError(
                f"uwierzytelnienie nieudane: {_describe(err)}"
            ) from err

        if authenticated is False:
            raise MagicSwitchbotAuthError(
                f"{self.address} odrzucił hasło (PIN)"
            )
        if not authenticated:
            raise _RetryableError("brak odpowiedzi na uwierzytelnienie")

        if method is None:
            return True

        try:
            return await getattr(bot, method)()
        except Exception as err:  # noqa: BLE001 - mapujemy na błąd integracji
            if method in _IDEMPOTENT_METHODS:
                raise _RetryableError(
                    f"{method}() nieudane: {_describe(err)}"
                ) from err
            raise MagicSwitchbotError(
                f"brak potwierdzenia {method}(): {_describe(err)}. Komenda mogła "
                "zostać wykonana, więc nie jest ponawiana"
            ) from err

    async def _async_attempt(self, method: str | None, password: str | None) -> Any:
        """Jedna próba: nowy tunel, uwierzytelnienie, komenda, rozłączenie."""
        ble_device = async_ble_device_from_address(
            self.hass, self.address, connectable=True
        )
        if ble_device is None:
            raise MagicSwitchbotNotFound(
                f"{self.address} nie jest widoczny w stosie Bluetooth"
            )

        try:
            # Jedna próba połączenia - ponawiamy całą operację wyżej.
            client = await establish_connection(
                BleakClientWithServiceCache,
                ble_device,
                self.address,
                max_attempts=1,
                ble_device_callback=lambda: async_ble_device_from_address(
                    self.hass, self.address, connectable=True
                )
                or ble_device,
            )
        except Exception as err:  # noqa: BLE001 - mapujemy na błąd integracji
            raise _RetryableError(
                f"nie udało się połączyć: {_describe(err)}"
            ) from err

        key = self.address
        # retry_count=1: biblioteka robi jedną próbę, ponowienia są w
        # _async_call_locked (jej własne i tak nie działają na naszym tunelu).
        bot = MagicSwitchbot(ble_device, password=password, retry_count=1)
        _TUNNELS[key] = client

        try:
            _LOGGER.debug(
                "MagicSwitchbot[%s]: tunel zestawiony, wołam %s()",
                self.address,
                method,
            )
            return await self._async_execute(bot, method)
        finally:
            _TUNNELS.pop(key, None)
            _cancel_disconnect_timer(bot)
            try:
                await client.disconnect()
            except Exception as err:  # noqa: BLE001 - sprzątanie
                _LOGGER.debug(
                    "MagicSwitchbot[%s]: błąd przy rozłączaniu: %s",
                    self.address,
                    err,
                )

    async def _async_call_locked(
        self, method: str | None, password: str | None
    ) -> Any:
        """Wykonuje operację z ponowieniami, w łącznym limicie czasu."""
        _install_tunnel_patch()

        name = f"{method}()" if method else "sprawdzenie hasła"
        attempts = self._retry_count + 1
        last_error: _RetryableError | None = None

        try:
            # Limit obejmuje wszystkie próby razem z przerwami między nimi.
            async with asyncio.timeout(self._command_timeout):
                for attempt in range(1, attempts + 1):
                    try:
                        return await self._async_attempt(method, password)
                    except _RetryableError as err:
                        last_error = err
                        _LOGGER.debug(
                            "MagicSwitchbot[%s]: próba %d/%d dla %s nieudana: %s",
                            self.address,
                            attempt,
                            attempts,
                            name,
                            err,
                        )
                        if attempt < attempts:
                            await asyncio.sleep(_RETRY_BACKOFF)
        except TimeoutError as err:
            message = f"przekroczono łączny limit {self._command_timeout} s dla {name}"
            if last_error is not None:
                message += f" (ostatni błąd: {last_error})"
            raise MagicSwitchbotTimeout(message) from err

        assert last_error is not None
        raise MagicSwitchbotError(
            f"{last_error} (wykonane próby: {attempts})"
        ) from last_error