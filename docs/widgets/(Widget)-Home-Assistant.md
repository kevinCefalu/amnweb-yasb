# Home Assistant Widget

The Home Assistant widget connects to a [Home Assistant](https://www.home-assistant.io/) instance and displays entity
states directly in the YASB status bar. It supports optional service calls (e.g. toggling lights or switches) via click
or keybinding.

## Connection modes

- **WebSocket** (preferred)  -  real-time push updates via the
  [Home Assistant WebSocket API](https://developers.home-assistant.io/docs/api/websocket/).
- **REST polling** (fallback)  -  periodic HTTP GET requests to the
  [REST API](https://www.home-assistant.io/docs/api/rest/) when WebSocket is disabled or disconnected.

Both modes can be active at the same time; REST polling is automatically paused while the WebSocket connection is
healthy.

> **Widget type note:** The `type` string namespace can change between releases. If a sample `type` does not validate
> in your setup, copy the canonical widget `type` from your installed `schema.json` (or from your generated default
> config) and keep the same `options` structure shown below.

## Options

|        Option        |    Type     |                   Default                    |                                                   Description                                                    |
| -------------------- | ----------- | -------------------------------------------- | ---------------------------------------------------------------------------------------------------------------- |
| `base_url`           | string      | `"http://homeassistant.local:8123"`          | Base URL of your Home Assistant instance                                                                         |
| `token`              | string      | `""`                                         | Long-Lived Access Token. Use `"$env:YASB_HASS_TOKEN"` to read from `.env`                                        |
| `dashboard_url`      | string/null | `null`                                       | URL to open in the dashboard popup. Defaults to `<base_url>/lovelace`                                            |
| `label`              | string      | `"<span class='icon'>\uf015</span> {state}"` | Label template (see [Placeholders](#placeholders))                                                               |
| `label_alt`          | string      | `"HA: {primary.name}: {primary.state}"`      | Alternative label template                                                                                       |
| `tooltip`            | boolean     | `true`                                       | Enable hover tooltip for the widget                                                                              |
| `tooltip_label`      | string/null | `null`                                       | Optional tooltip template. If omitted, the active label template is used (with `<span>` tags removed)            |
| `state_icons`        | dict        | `{}`                                         | Map Home Assistant states to icons (for `{icon}` / `{primary.icon}`), e.g. `{ "on": "\uf0eb", "off": "\uf011" }` |
| `state_icon_default` | string/null | `null`                                       | Fallback icon when no state-specific icon matches                                                                |
| `dashboard_popup`    | dict        | see below                                    | Popup styling/position/size for the embedded dashboard                                                           |
| `entities`           | list        | `[]`                                         | List of entity config objects (see [Entity options](#entity-options))                                            |
| `ws`                 | dict        | see below                                    | WebSocket connection settings                                                                                    |
| `polling`            | dict        | see below                                    | REST polling settings                                                                                            |
| `display`            | dict        | see below                                    | Display settings                                                                                                 |
| `actions`            | dict        | see below                                    | Action / toggle settings                                                                                         |
| `callbacks`          | dict        | see below                                    | Mouse-click callbacks                                                                                            |
| `keybindings`        | list        | `[]`                                         | Keybinding definitions                                                                                           |

### `ws` options

|         Option          |  Type   | Default |                  Description                   |
| ----------------------- | ------- | ------- | ---------------------------------------------- |
| `enabled`               | boolean | `true`  | Enable WebSocket connection                    |
| `reconnect_interval_ms` | integer | `4000`  | Reconnect delay in milliseconds (1000 - 60000) |

### `polling` options

|    Option     |  Type   | Default |                  Description                   |
| ------------- | ------- | ------- | ---------------------------------------------- |
| `enabled`     | boolean | `true`  | Enable REST polling (used as fallback)         |
| `interval_ms` | integer | `10000` | Poll interval in milliseconds (1000 - 3600000) |
| `timeout_ms`  | integer | `5000`  | Request timeout in milliseconds (500 - 60000)  |
| `verify_ssl`  | boolean | `true`  | Verify SSL certificates                        |

### `display` options

|      Option      |  Type  | Default |                                                   Description                                                   |
| ---------------- | ------ | ------- | --------------------------------------------------------------------------------------------------------------- |
| `primary_entity` | string | `null`  | Entity ID to use as the primary entity for `{primary.*}` placeholders. Defaults to the first entity in the list |

### `actions` options

|      Option      |  Type  |  Default  |                                                 Description                                                  |
| ---------------- | ------ | --------- | ------------------------------------------------------------------------------------------------------------ |
| `toggle_target`  | string | `"first"` | Which entities to toggle when the `toggle` callback fires: `"first"`, `"all"`, or `"primary"`                |
| `primary_entity` | string | `null`    | Override the primary entity for toggle actions. Falls back to `display.primary_entity` then the first entity |

### `dashboard_popup` options

|        Option        |  Type   |      Default       |                      Description                       |
| -------------------- | ------- | ------------------ | ------------------------------------------------------ |
| `width`              | integer | `1000`             | Popup width                                            |
| `height`             | integer | `700`              | Popup height                                           |
| `title`              | string  | `"Home Assistant"` | Popup header title                                     |
| `alignment`          | string  | `"right"`          | Popup horizontal alignment (`left`, `center`, `right`) |
| `direction`          | string  | `"down"`           | Popup direction relative to widget (`up`, `down`)      |
| `offset_left`        | integer | `0`                | Horizontal offset                                      |
| `offset_top`         | integer | `0`                | Vertical offset                                        |
| `blur`               | boolean | `true`             | Enable blur backdrop for popup                         |
| `round_corners`      | boolean | `true`             | Round popup corners                                    |
| `round_corners_type` | string  | `"normal"`         | Corner rounding style                                  |
| `border_color`       | string  | `"system"`         | Border color mode                                      |
| `auth_mode`          | string  | `"browser_login"`  | Dashboard auth mode: `browser_login` (recommended) or `legacy_token_injection` |
| `legacy_token_ttl_seconds` | integer | `1800`      | TTL for injected dashboard token in legacy mode (60-86400 seconds) |

### Dashboard auth modes

- `browser_login` (default): opens the dashboard with normal Home Assistant browser login/session behavior.
- `legacy_token_injection`: injects the configured `token` into browser storage for auto-login compatibility.
  This mode is less secure and should only be used when needed for existing setups.

### Entity options

Each entry in the `entities` list accepts:

|     Option     |  Type  |   Default    |                                      Description                                      |
| -------------- | ------ | ------------ | ------------------------------------------------------------------------------------- |
| `entity_id`    | string | *(required)* | Home Assistant entity ID, e.g. `light.kitchen`                                        |
| `display_name` | string | `null`       | Optional human-readable name (overrides `friendly_name` from HA)                      |
| `icon`         | string | `null`       | Optional icon override                                                                |
| `template`     | string | `null`       | Optional server-side Jinja2 template sent to HA's `render_template` WebSocket command |

### `callbacks` options

|  Callback   |     Default      |      Description       |
| ----------- | ---------------- | ---------------------- |
| `on_left`   | `"toggle_first"` | Action on left click   |
| `on_middle` | `"toggle_label"` | Action on middle click |
| `on_right`  | `"refresh"`      | Action on right click  |

## Placeholders

Use these in `label` and `label_alt` templates:

|      Placeholder      |                                               Description                                                |
| --------------------- | -------------------------------------------------------------------------------------------------------- |
| `{state}`             | Alias for `{primary.state}`                                                                              |
| `{primary.state}`     | State of the primary entity (e.g. `on`, `off`, `unavailable`)                                            |
| `{primary.name}`      | Display name of the primary entity                                                                       |
| `{primary.entity_id}` | Entity ID of the primary entity                                                                          |
| `{icon}`              | Icon for the primary entity state from `state_icons` (fallback: entity `icon` then `state_icon_default`) |
| `{primary.icon}`      | Same as `{icon}`                                                                                         |
| `{count_total}`       | Total number of configured entities                                                                      |
| `{count_on}`          | Number of entities whose state is considered "on"                                                        |
| `{count_off}`         | Number of entities whose state is considered "off"                                                       |
| `{count_unavailable}` | Number of entities in unavailable/unknown state                                                          |

## Callbacks

|                  Callback                   |                              Description                               |
| ------------------------------------------- | ---------------------------------------------------------------------- |
| `toggle_label`                              | Switch between `label` and `label_alt`                                 |
| `refresh`                                   | Force an immediate state refresh (WebSocket `get_states` or REST poll) |
| `toggle`                                    | Toggle entities according to `actions.toggle_target`                   |
| `toggle_first`                              | Always toggle the first configured entity                              |
| `toggle_all`                                | Toggle all configured entities                                         |
| `toggle_dashboard`                          | Toggle an embedded Home Assistant dashboard popup                      |
| `open_dashboard`                            | Alias of `toggle_dashboard`                                            |
| `call_service "domain.service" "entity_id"` | Call an arbitrary HA service                                           |

## Toggle strategies

The `actions.toggle_target` option controls what the generic `toggle` callback does:

|    Value    |                                                 Behaviour                                                  |
| ----------- | ---------------------------------------------------------------------------------------------------------- |
| `"first"`   | Toggle only the first entity in the `entities` list                                                        |
| `"all"`     | Toggle every entity in the `entities` list                                                                 |
| `"primary"` | Toggle the entity specified by `actions.primary_entity` (or `display.primary_entity`, or the first entity) |

You can always bypass this option by binding `toggle_first` or `toggle_all` directly.

## Secrets / token handling

Store your Home Assistant Long-Lived Access Token in a `.env` file inside your YASB config directory:

```env
YASB_HASS_TOKEN=your_long_lived_access_token_here
```

Then reference it in `config.yaml`:

```yaml
token: "$env:YASB_HASS_TOKEN"
```

YASB will expand `$env:VARIABLE_NAME` at startup. The token never needs to be written directly into `config.yaml`.

> **How to create a token:** In Home Assistant open your profile → *Long-Lived Access Tokens* → *Create Token*.

## Example Configuration

### Single entity  -  WebSocket with env token

```yaml
home_assistant:
  type: "home_assistant.home_assistant.HomeAssistantWidget"
  options:
    base_url: "http://homeassistant.local:8123"
    token: "$env:YASB_HASS_TOKEN"
    label: "<span class='icon'>\uf015</span> {state}"
    label_alt: "Kitchen light: {primary.state}"
    entities:
      - entity_id: "light.kitchen"
        display_name: "Kitchen"
    callbacks:
      on_left: "toggle_first"
      on_middle: "toggle_label"
      on_right: "refresh"
```

### Multiple entities  -  aggregate counts

```yaml
home_assistant:
  type: "home_assistant.home_assistant.HomeAssistantWidget"
  options:
    base_url: "http://homeassistant.local:8123"
    token: "$env:YASB_HASS_TOKEN"

    display:
      primary_entity: "light.living_room"

    actions:
      toggle_target: "all"

    label: "<span class='icon'>\uf0eb</span> {count_on}/{count_total}"
    label_alt: "Lights: {primary.name} {primary.state}"

    entities:
      - entity_id: "light.living_room"
        display_name: "Living Room"
      - entity_id: "light.kitchen"
        display_name: "Kitchen"
      - entity_id: "light.bedroom"
        display_name: "Bedroom"

    callbacks:
      on_left: "toggle"
      on_middle: "toggle_label"
      on_right: "refresh"
```

### Open dashboard popup on right click

```yaml
home_assistant:
  type: "home_assistant.home_assistant.HomeAssistantWidget"
  options:
    base_url: "http://homeassistant.local:8123"
    token: "$env:YASB_HASS_TOKEN"

    dashboard_url: "http://homeassistant.local:8123/lovelace/0"
    dashboard_popup:
      width: 1100
      height: 760
      title: "Home Dashboard"
      alignment: "right"
      direction: "down"
      blur: true
      round_corners: true
      border_color: "system"

    callbacks:
      on_left: "toggle_first"
      on_middle: "toggle_label"
      on_right: "toggle_dashboard"
```

Use the CSS class `.home-assistant-dashboard-popup` (and child classes like `.header`, `.title`, `.content`,
`.float-button`, `.close-button`) in `styles.css` to style the popup chrome. When the popup is pinned/floating,
the root class includes `.floating`.

### Embedded dashboard requirements

- The embedded dashboard popup uses `PyQt6-WebEngine`.
- If `PyQt6-WebEngine` is not available, the popup still opens with a fallback message and an **Open in Browser**
  button.
- Source installs should include `PyQt6-WebEngine` via project dependencies.
- Packaged builds (MSI/exe) should include WebEngine modules so end users do not need to install anything manually.

### State-based icons

```yaml
home_assistant:
  type: "home_assistant.home_assistant.HomeAssistantWidget"
  options:
    base_url: "http://homeassistant.local:8123"
    token: "$env:YASB_HASS_TOKEN"

    state_icons:
      on: "\uf0eb"
      off: "\uf011"
      unavailable: "\uf071"
      unknown: "\uf128"
    state_icon_default: "\uf059"

    label: "<span class='icon'>{icon}</span> {state}"
    label_alt: "{primary.name}: <span class='icon'>{primary.icon}</span> {primary.state}"
    tooltip: true
    tooltip_label: "{primary.name}: {primary.state} ({count_on}/{count_total} on)"

    entities:
      - entity_id: "light.cabinet_accent_light"
        display_name: "Desk Key Light"
        icon: "\uf0eb"
```

### Polling-only (WebSocket disabled)

```yaml
home_assistant:
  type: "home_assistant.home_assistant.HomeAssistantWidget"
  options:
    base_url: "https://my-ha-instance.duckdns.org"
    token: "$env:YASB_HASS_TOKEN"

    ws:
      enabled: false

    polling:
      enabled: true
      interval_ms: 30000
      timeout_ms: 8000
      verify_ssl: true

    label: "{state}"
    entities:
      - entity_id: "sensor.outdoor_temperature"
        display_name: "Outside"
```

### Advanced  -  call arbitrary service via keybinding

```yaml
home_assistant:
  type: "home_assistant.home_assistant.HomeAssistantWidget"
  options:
    base_url: "http://homeassistant.local:8123"
    token: "$env:YASB_HASS_TOKEN"
    label: "{state}"
    entities:
      - entity_id: "scene.movie_time"
    keybindings:
      - keys: "ctrl+shift+h"
        action: 'call_service "scene.turn_on" "scene.movie_time"'
```

## Example Style

```css
.home-assistant-widget {
    padding: 0 6px;
}
.home-assistant-widget .widget-container {
    /* widget container */
}
.home-assistant-widget .icon {
    font-size: 14px;
    min-width: 18px;
}
.home-assistant-widget .label {
    font-size: 12px;
    font-family: "Segoe UI";
    color: #ffffff;
}
```
