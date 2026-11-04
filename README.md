# MagicSwitchbot (Bluetooth Proxy)

A Home Assistant integration for **Magic Switchbot**, controlled over BLE
using a local Bluetooth adapter or an ESPHome Bluetooth proxy. It provides
`switch` and `button` entities, a battery sensor, and an optional RSSI sensor.

<img src="https://raw.githubusercontent.com/mnowok/magicswitchbot_ble/main/docs/screenshot.png"
     alt="Magic Switchbot device page in Home Assistant" width="700">

## Requirements

- Home Assistant 2026.3 or later
- **Connectable** Bluetooth, provided by a local BLE adapter or an ESPHome Bluetooth proxy
- A Magic Switchbot device within Bluetooth range

## Installation via HACS

1. In HACS, open **Integrations** and select **⋮ → Custom repositories**.
2. Enter `https://github.com/mnowok/magicswitchbot_ble` and select **Integration** as the category.
3. Find **MagicSwitchbot (Bluetooth Proxy)** and select **Download**.
4. **Restart Home Assistant.**
5. Go to **Settings → Devices & services → Add integration** and select **MagicSwitchbot**.

## Configuration

The integration discovers devices automatically by their `MagicSwitchBot*`
advertised name and manufacturer ID `1282`.

If your device does not appear—for example, because it is asleep and not
advertising—choose the manual MAC address option in the setup flow. Enter the
address in this format: `AA:BB:CC:DD:EE:FF`.

## Options

| Option | Default | Description |
|---|---:|---|
| `enable_switch` | `true` | Create a switch entity |
| `enable_button` | `true` | Create a button entity |
| `enable_battery` | `true` | Create a battery sensor |
| `enable_rssi` | `false` | Create an RSSI sensor |
| `retry_count` | `3` | Number of command retries |
| `command_timeout` | `30` | Command timeout in seconds |

## Troubleshooting

- **The device does not appear in the list:** Try manual setup. A sleeping device may not be advertising over BLE.
- **The battery level does not update:** The value comes from BLE advertisements, so it updates when the device advertises again.
- **Commands do not reach the device:** Check that the Bluetooth proxy is connectable and within range.

To enable debug logging:

    logger:
      default: warning
      logs:
        custom_components.magicswitchbot_ble: debug

## License

MIT. This project is not affiliated with Shenzhen Interear or SwitchBot.