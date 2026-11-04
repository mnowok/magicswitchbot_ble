# MagicSwitchbot (Bluetooth Proxy)

Integracja Home Assistant dla **Magic Switchbot** — sterowanie przez BLE
(lokalny adapter albo ESPHome Bluetooth proxy). Encje `switch`, `button`,
sensor baterii i opcjonalnie RSSI.

<img src="https://raw.githubusercontent.com/mnowok/magicswitchbot_ble/main/docs/screenshot.png"
     alt="Strona urządzenia Magic Switchbot w Home Assistant" width="700">

## Wymagania

- Home Assistant 2026.3 lub nowszy
- **Connectable** Bluetooth — lokalny adapter BLE albo ESPHome Bluetooth proxy
- Urządzenie Magic Switchbot w zasięgu

## Instalacja (HACS)

1. HACS → **Integracje** → ⋮ → **Custom repositories**
2. URL: `https://github.com/mnowok/magicswitchbot_ble`, kategoria **Integration**
3. Znajdź **MagicSwitchbot (Bluetooth Proxy)** → **Download**
4. **Zrestartuj Home Assistant**
5. Ustawienia → Urządzenia i usługi → **Dodaj integrację** → **MagicSwitchbot**

## Konfiguracja

Urządzenie jest wykrywane automatycznie (matcher po nazwie `MagicSwitchBot*`
i `manufacturer_id 1282`). Jeśli się nie pojawi — np. gdy bot jest w głębokim
śnie i nie reklamuje się — wybierz **Enter MAC address manually** i wpisz adres
w formacie `AA:BB:CC:DD:EE:FF`.

## Opcje

| Opcja | Domyślnie | Opis |
|---|---|---|
| `enable_switch` | `true` | encja `switch` |
| `enable_button` | `true` | encja `button` |
| `enable_battery` | `true` | sensor poziomu baterii |
| `enable_rssi` | `false` | sensor RSSI |
| `retry_count` | `3` | liczba ponowień komendy |
| `command_timeout` | `30` | timeout komendy w sekundach |

## Rozwiązywanie problemów

- **Brak urządzenia na liście** → użyj trybu ręcznego; urządzenie śpiące nie
  reklamuje się w BLE.
- **Bateria się nie odświeża** → wartość pochodzi z reklamy BLE, więc zmienia
  się dopiero przy kolejnym rozgłoszeniu urządzenia.
- **Komendy nie docierają** → sprawdź, czy proxy BLE jest w trybie
  *connectable* i w zasięgu.

## Licencja

MIT. Projekt niezwiązany z Shenzhen Interear ani z SwitchBot.

Logi diagnostyczne:

```yaml
logger:
  default: warning
  logs:
    custom_components.magicswitchbot_ble: debug