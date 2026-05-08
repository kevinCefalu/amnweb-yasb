from typing import Literal
from urllib.parse import urlparse

from pydantic import Field, field_validator

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


class HomeAssistantDashboardPopupConfig(CustomBaseModel):
    width: int = Field(default=1000, ge=320, le=4000)
    height: int = Field(default=700, ge=240, le=3000)
    title: str = "Home Assistant"
    alignment: Literal["left", "center", "right"] = "right"
    direction: Literal["up", "down"] = "down"
    offset_left: int = 0
    offset_top: int = 0
    blur: bool = True
    round_corners: bool = True
    round_corners_type: str = "normal"
    border_color: str = "system"
    auth_mode: Literal["browser_login", "legacy_token_injection"] = "browser_login"
    legacy_token_ttl_seconds: int = Field(default=1800, ge=60, le=86400)


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
    dashboard_url: str | None = None
    label: str = "<span class='icon'>\uf015</span> {state}"
    label_alt: str = "HA: {primary.name}: {primary.state}"
    tooltip: bool = True
    tooltip_label: str | None = None
    state_icons: dict[str, str] = {}
    state_icon_default: str | None = None
    dashboard_popup: HomeAssistantDashboardPopupConfig = HomeAssistantDashboardPopupConfig()
    ws: HomeAssistantWsConfig = HomeAssistantWsConfig()
    polling: HomeAssistantPollingConfig = HomeAssistantPollingConfig()
    display: HomeAssistantDisplayConfig = HomeAssistantDisplayConfig()
    actions: HomeAssistantActionsConfig = HomeAssistantActionsConfig()
    entities: list[HaEntityConfig] = []
    callbacks: HomeAssistantCallbacksConfig = HomeAssistantCallbacksConfig()
    keybindings: list[KeybindingConfig] = []

    @staticmethod
    def _validate_http_url(value: str, field_name: str) -> str:
        url = value.strip()
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            raise ValueError(f"{field_name} must use http:// or https://")
        if not parsed.netloc or parsed.hostname is None:
            raise ValueError(f"{field_name} must include a valid host")
        return url

    @field_validator("base_url")
    @classmethod
    def _validate_base_url(cls, value: str) -> str:
        return cls._validate_http_url(value, "base_url")

    @field_validator("dashboard_url", mode="before")
    @classmethod
    def _normalize_dashboard_url(cls, value: str | None) -> str | None:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("dashboard_url")
    @classmethod
    def _validate_dashboard_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return cls._validate_http_url(value, "dashboard_url")
