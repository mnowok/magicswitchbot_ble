"""Config flow i options flow dla Magic Switchbot."""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from typing import Any

import voluptuous as vol

from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_ADDRESS, CONF_NAME, CONF_PASSWORD
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import (
    PIN_LENGTH,
    MagicSwitchbotAuthError,
    MagicSwitchbotBLE,
    MagicSwitchbotError,
    MagicSwitchbotPinNotChanged,
    MagicSwitchbotPinUnverified,
)
from .const import (
    CONF_COMMAND_TIMEOUT,
    CONF_ENABLE_BATTERY,
    CONF_ENABLE_BUTTON,
    CONF_ENABLE_RSSI,
    CONF_ENABLE_SWITCH,
    CONF_RETRY_COUNT,
    DEFAULT_COMMAND_TIMEOUT,
    DEFAULT_OPTIONS,
    DEFAULT_RETRY_COUNT,
    DOMAIN,
    MAX_COMMAND_TIMEOUT,
    MIN_COMMAND_TIMEOUT,
    MODEL,
)
from .util import format_mac, is_magicswitchbot, is_valid_mac, normalize_mac

_LOGGER = logging.getLogger(__name__)

DEFAULT_NAME = "Magic Switchbot"

# Hasło (PIN) ustawione w aplikacji MagicSwitchBot; puste = brak hasła.
PASSWORD_SELECTOR = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))

# Nowy PIN ustawiany z HA: dokładnie 6 cyfr, jak w aplikacji (stała długość
# parametru komendy - krótszy PIN przesunąłby token w ramce).
CONF_NEW_PIN = "new_pin"
CONF_NEW_PIN_CONFIRM = "new_pin_confirm"
PIN_PATTERN = re.compile(rf"\d{{{PIN_LENGTH}}}")


class MagicSwitchbotConfigFlow(ConfigFlow, domain=DOMAIN):
    """Dodawanie bota z GUI (bez YAML)."""

    VERSION = 1

    def __init__(self) -> None:
        """Inicjalizacja flow."""
        self._discovered_address: str | None = None
        self._discovered_name: str = DEFAULT_NAME

    # ---- Auto-discovery (manifest matchers) -----------------------------
    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        """Urządzenie znalezione przez stos Bluetooth (także przez proxy ESPHome)."""
        address = format_mac(discovery_info.address)
        await self.async_set_unique_id(normalize_mac(address))
        self._abort_if_unique_id_configured(updates={CONF_ADDRESS: address})

        self._discovered_address = address
        self._discovered_name = discovery_info.name or DEFAULT_NAME
        self.context["title_placeholders"] = {
            "name": self._discovered_name,
            "address": address,
        }
        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Potwierdzenie dodania wykrytego urządzenia."""
        assert self._discovered_address is not None

        if user_input is not None:
            return await self._async_create_entry(
                self._discovered_address,
                user_input[CONF_NAME],
                user_input.get(CONF_PASSWORD),
            )

        return self.async_show_form(
            step_id="bluetooth_confirm",
            description_placeholders={
                "name": self._discovered_name,
                "address": self._discovered_address,
            },
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_NAME, default=self._discovered_name): str,
                    vol.Optional(CONF_PASSWORD): PASSWORD_SELECTOR,
                }
            ),
        )

    # ---- Dodawanie ręczne -----------------------------------------------
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Menu: wybór z listy (jeśli coś jest) albo ręczny MAC."""
        menu_options: list[str] = []

        try:
            if self._async_discovered_devices():
                menu_options.append("pick_device")
        except Exception:  # noqa: BLE001 — skan nie może wywalić flow
            _LOGGER.exception("Skan BLE nie powiódł się — tylko tryb ręczny")

        menu_options.append("manual")

        if len(menu_options) == 1:
            return await self.async_step_manual()

        return self.async_show_menu(step_id="user", menu_options=menu_options)

    async def async_step_pick_device(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Wybór urządzenia z listy wykrytych."""
        devices = self._async_discovered_devices()
        if not devices:
            return self.async_abort(reason="no_devices_found")

        if user_input is not None:
            return await self._async_create_entry(
                user_input[CONF_ADDRESS],
                user_input[CONF_NAME],
                user_input.get(CONF_PASSWORD),
            )

        default_name = next(iter(devices.values())).split("(")[0].strip() or DEFAULT_NAME
        return self.async_show_form(
            step_id="pick_device",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ADDRESS): vol.In(devices),
                    vol.Required(CONF_NAME, default=default_name): str,
                    vol.Optional(CONF_PASSWORD): PASSWORD_SELECTOR,
                }
            ),
            description_placeholders={"count": str(len(devices))},
        )

    async def async_step_manual(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ręczne wpisanie adresu MAC."""
        errors: dict[str, str] = {}

        if user_input is not None:
            address = format_mac(user_input[CONF_ADDRESS])
            if not is_valid_mac(address):
                errors[CONF_ADDRESS] = "invalid_mac"
            else:
                return await self._async_create_entry(
                    address,
                    user_input.get(CONF_NAME) or DEFAULT_NAME,
                    user_input.get(CONF_PASSWORD),
                )

        return self.async_show_form(
            step_id="manual",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ADDRESS): str,
                    vol.Required(CONF_NAME, default=DEFAULT_NAME): str,
                    vol.Optional(CONF_PASSWORD): PASSWORD_SELECTOR,
                }
            ),
            errors=errors,
        )

    # ---- Pomocnicze -----------------------------------------------------
    @callback
    def _async_discovered_devices(self) -> dict[str, str]:
        """Lista wykrytych, jeszcze nieskonfigurowanych botów."""
        configured = self._async_current_ids()   # ignorowane też odfiltrowane
        found: dict[str, str] = {}

        for info in async_discovered_service_info(self.hass, connectable=True):
            address = format_mac(info.address)
            if normalize_mac(address) in configured or address in found:
                continue
            if not is_magicswitchbot(
                info.name, info.service_uuids, info.manufacturer_data
            ):
                continue

            label = f"{info.name or MODEL} ({address})"
            found[address] = label

        return found

    async def _async_create_entry(
        self, address: str, name: str, password: str | None = None
    ) -> ConfigFlowResult:
        """Tworzy wpis konfiguracyjny."""
        address = format_mac(address)
        await self.async_set_unique_id(normalize_mac(address), raise_on_progress=False)
        self._abort_if_unique_id_configured(updates={CONF_ADDRESS: address})

        data = {CONF_ADDRESS: address, CONF_NAME: name or DEFAULT_NAME}
        if password:
            data[CONF_PASSWORD] = password

        return self.async_create_entry(
            title=name or DEFAULT_NAME,
            data=data,
            options={},
        )

    # ---- Ponowne uwierzytelnienie (hasło/PIN) ---------------------------
    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Urządzenie odrzuciło hasło - poproś o nowe."""
        entry = self._get_reauth_entry()
        # flow_title używa {name} i {address}; HA sam ustawia tylko {name}.
        self.context["title_placeholders"] = {
            "name": entry.title,
            "address": str(entry.data[CONF_ADDRESS]).upper(),
        }
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Formularz nowego hasła po odrzuceniu starego."""
        return await self._async_password_step(
            self._get_reauth_entry(), "reauth_confirm", user_input
        )

    # ---- Ponowna konfiguracja: hasło w HA oraz PIN na urządzeniu --------
    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Menu: zapis hasła w HA, zmiana albo usunięcie PIN-u na urządzeniu."""
        entry = self._get_reconfigure_entry()
        placeholders = self._entry_placeholders(entry)
        self.context["title_placeholders"] = placeholders
        return self.async_show_menu(
            step_id="reconfigure",
            menu_options=["reconfigure_password", "change_pin", "remove_pin"],
            description_placeholders=placeholders,
        )

    async def async_step_reconfigure_password(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Zapis hasła zmienionego w aplikacji, bez czekania na odrzucenie."""
        return await self._async_password_step(
            self._get_reconfigure_entry(), "reconfigure_password", user_input
        )

    async def async_step_change_pin(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ustawienie albo zmiana PIN-u na samym urządzeniu."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            new_pin = user_input.get(CONF_NEW_PIN) or ""
            if not PIN_PATTERN.fullmatch(new_pin):
                errors[CONF_NEW_PIN] = "invalid_pin_format"
            elif new_pin != user_input.get(CONF_NEW_PIN_CONFIRM):
                errors[CONF_NEW_PIN_CONFIRM] = "pin_mismatch"
            elif error := await self._async_change_device_pin(entry, new_pin):
                errors["base"] = error
            else:
                return self.async_update_and_abort(
                    entry, data_updates={CONF_PASSWORD: new_pin}, reason="pin_changed"
                )

        return self.async_show_form(
            step_id="change_pin",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_NEW_PIN): PASSWORD_SELECTOR,
                    vol.Required(CONF_NEW_PIN_CONFIRM): PASSWORD_SELECTOR,
                }
            ),
            description_placeholders=self._entry_placeholders(entry),
            errors=errors,
        )

    async def async_step_remove_pin(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Usunięcie PIN-u z urządzenia (po potwierdzeniu)."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            if error := await self._async_change_device_pin(entry, None):
                errors["base"] = error
            else:
                return self.async_update_and_abort(
                    entry, data_updates={CONF_PASSWORD: ""}, reason="pin_removed"
                )

        return self.async_show_form(
            step_id="remove_pin",
            data_schema=vol.Schema({}),
            description_placeholders=self._entry_placeholders(entry),
            errors=errors,
        )

    async def _async_change_device_pin(
        self, entry: ConfigEntry, new_pin: str | None
    ) -> str | None:
        """Zmienia PIN na urządzeniu; zwraca klucz błędu albo None."""
        api = self._api_for_entry(entry)
        try:
            await api.change_device_pin(new_pin)
        except MagicSwitchbotAuthError:
            return "current_pin_rejected"
        except MagicSwitchbotPinNotChanged as err:
            _LOGGER.debug("Zmiana PIN-u nieudana: %s", err)
            return "pin_not_changed"
        except MagicSwitchbotPinUnverified as err:
            _LOGGER.warning("Nie udało się potwierdzić zmiany PIN-u: %s", err)
            return "pin_unverified"
        except MagicSwitchbotError as err:
            _LOGGER.debug("Zmiana PIN-u nieudana: %s", err)
            return "cannot_connect"
        return None

    def _api_for_entry(self, entry: ConfigEntry) -> MagicSwitchbotBLE:
        """Klient BLE wpisu: działający (wspólna blokada) albo tymczasowy."""
        # Działający wpis ma własnego klienta z blokadą - używamy go, by
        # operacja nie zderzyła się z komendą wysyłaną w tym samym czasie.
        runtime = getattr(entry, "runtime_data", None)
        if runtime is not None:
            return runtime.api
        return MagicSwitchbotBLE(
            self.hass,
            str(entry.data[CONF_ADDRESS]).upper(),
            password=entry.data.get(CONF_PASSWORD) or None,
        )

    @staticmethod
    def _entry_placeholders(entry: ConfigEntry) -> dict[str, str]:
        """Nazwa i adres do tytułu i opisów formularzy."""
        return {"name": entry.title, "address": str(entry.data[CONF_ADDRESS]).upper()}

    async def _async_password_step(
        self,
        entry: ConfigEntry,
        step_id: str,
        user_input: dict[str, Any] | None,
    ) -> ConfigFlowResult:
        """Formularz hasła, sprawdzanego na urządzeniu przed zapisem."""
        address = str(entry.data[CONF_ADDRESS]).upper()
        errors: dict[str, str] = {}

        if user_input is not None:
            password = user_input.get(CONF_PASSWORD) or ""
            api = self._api_for_entry(entry)

            try:
                await api.check_auth(password or None)
            except MagicSwitchbotAuthError:
                errors["base"] = "invalid_auth"
            except MagicSwitchbotError as err:
                _LOGGER.debug(
                    "MagicSwitchbot[%s]: sprawdzenie hasła nieudane: %s",
                    address,
                    err,
                )
                errors["base"] = "cannot_connect"
            else:
                # Przeładowanie po zmianie danych wykona listener aktualizacji
                # z __init__.py (async_update_reload_and_abort zrobiłby to drugi raz).
                return self.async_update_and_abort(
                    entry, data_updates={CONF_PASSWORD: password}
                )

        return self.async_show_form(
            step_id=step_id,
            data_schema=vol.Schema(
                {vol.Optional(CONF_PASSWORD): PASSWORD_SELECTOR}
            ),
            description_placeholders={"name": entry.title, "address": address},
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Options flow."""
        return MagicSwitchbotOptionsFlow()


class MagicSwitchbotOptionsFlow(OptionsFlow):
    """Opcje: które encje tworzyć + parametry BLE."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Formularz opcji."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        current = {**DEFAULT_OPTIONS, **self.config_entry.options}

        # Wpisy zapisane przy starym minimum (10 s) mogą mieć wartość spoza
        # zakresu - podpowiadamy najbliższą dozwoloną.
        command_timeout = min(
            max(int(current[CONF_COMMAND_TIMEOUT]), MIN_COMMAND_TIMEOUT),
            MAX_COMMAND_TIMEOUT,
        )

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_ENABLE_SWITCH, default=current[CONF_ENABLE_SWITCH]
                ): bool,
                vol.Required(
                    CONF_ENABLE_BUTTON, default=current[CONF_ENABLE_BUTTON]
                ): bool,
                vol.Required(
                    CONF_ENABLE_BATTERY, default=current[CONF_ENABLE_BATTERY]
                ): bool,
                vol.Required(
                    CONF_ENABLE_RSSI, default=current[CONF_ENABLE_RSSI]
                ): bool,
                vol.Required(
                    CONF_RETRY_COUNT, default=current[CONF_RETRY_COUNT]
                ): vol.All(vol.Coerce(int), vol.Range(min=0, max=10)),
                vol.Required(
                    CONF_COMMAND_TIMEOUT, default=command_timeout
                ): vol.All(
                    vol.Coerce(int),
                    vol.Range(min=MIN_COMMAND_TIMEOUT, max=MAX_COMMAND_TIMEOUT),
                ),
            }
        )

        return self.async_show_form(step_id="init", data_schema=schema)