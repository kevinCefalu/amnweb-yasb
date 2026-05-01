from typing import Literal

from pydantic import Field

from core.validation.widgets.base_model import (
    CallbacksConfig,
    CustomBaseModel,
    KeybindingConfig,
)


class HomeAssistantWsConfig(CustomBaseModel):
    enabled: bool = True
    reconnect_interval_ms: int = Field(default=4000, ge=1000, le=60000)


class HomeAssistantPollingConfig(CustomBaseModel):
    enabled: bool = True
    interval_ms: int = Field(default=10000, ge=1000, le=3600000)
    timeout_ms: int = Field(default=5000, ge=500, le=60000)
    verify_ssl: bool = True


class HomeAssistantDisplayConfig(CustomBaseModel):
    primary_entity: str | None = None


class HomeAssistantActionsConfig(CustomBaseModel):
    toggle_target: Literal["first", "all", "primary"] = "first"
    primary_entity: str | None = None


class HaEntityConfig(CustomBaseModel):
    entity_id: str
    display_name: str | None = None
    icon: str | None = None
    template: str | None = None


class HomeAssistantCallbacksConfig(CallbacksConfig):
    on_left: str = "toggle_first"
    on_middle: str = "toggle_label"
    on_right: str = "refresh"


class HomeAssistantConfig(CustomBaseModel):
    base_url: str = "http://homeassistant.local:8123"
    token: str = ""
    label: str = "<span class='icon'>\uf015</span> {state}"
    label_alt: str = "HA: {primary.name}: {primary.state}"
    ws: HomeAssistantWsConfig = HomeAssistantWsConfig()
    polling: HomeAssistantPollingConfig = HomeAssistantPollingConfig()
    display: HomeAssistantDisplayConfig = HomeAssistantDisplayConfig()
    actions: HomeAssistantActionsConfig = HomeAssistantActionsConfig()
    entities: list[HaEntityConfig] = []
    callbacks: HomeAssistantCallbacksConfig = HomeAssistantCallbacksConfig()
    keybindings: list[KeybindingConfig] = []
