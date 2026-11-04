"""Constants for the MagicSwitchbot (Bluetooth proxy) integration."""

from __future__ import annotations

from typing import Any, Final

DOMAIN: Final = "magicswitchbot_ble"

MANUFACTURER: Final = "MagicSwitchbot"
MODEL: Final = "Magic SwitchBot"

CONF_ENABLE_SWITCH: Final = "enable_switch"
CONF_ENABLE_BUTTON: Final = "enable_button"
CONF_ENABLE_BATTERY: Final = "enable_battery"
CONF_ENABLE_RSSI: Final = "enable_rssi"
CONF_RETRY_COUNT: Final = "retry_count"
CONF_COMMAND_TIMEOUT: Final = "command_timeout"

DEFAULT_RETRY_COUNT: Final = 3
DEFAULT_COMMAND_TIMEOUT: Final = 30

DEFAULT_OPTIONS: Final[dict[str, Any]] = {
    CONF_ENABLE_SWITCH: True,
    CONF_ENABLE_BUTTON: True,
    CONF_ENABLE_BATTERY: True,
    CONF_ENABLE_RSSI: False,
    CONF_RETRY_COUNT: DEFAULT_RETRY_COUNT,
    CONF_COMMAND_TIMEOUT: DEFAULT_COMMAND_TIMEOUT,
}

SERVICE_UUID: Final = "0000fee7-0000-1000-8000-00805f9b34fb"

# Bluetooth SIG Company Identifier — 0x0502 = Specifi-Kali LLC (moduł OEM)
MAGIC_MANUFACTURER_ID = 1282