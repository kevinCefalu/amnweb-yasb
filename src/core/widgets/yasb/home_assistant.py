"""
Home Assistant widget for YASB.

Displays Home Assistant entity states and supports service calls (toggle, etc.).
Uses the WebSocket API as the preferred connection method and falls back to REST
polling when WebSocket is disabled or unavailable.
"""

import logging
import re
from typing import Any

from PyQt6.QtCore import QTimer, Qt, pyqtSlot
from PyQt6.QtWidgets import QLabel

from core.validation.widgets.yasb.home_assistant import HomeAssistantConfig
from core.widgets.base import BaseWidget
from core.widgets.services.home_assistant.client import HomeAssistantClient
from core.widgets.services.home_assistant.rest import HomeAssistantRestWorker, call_service_rest

logger = logging.getLogger("home_assistant_widget")


class HomeAssistantWidget(BaseWidget):
    validation_schema = HomeAssistantConfig

    def __init__(self, config: HomeAssistantConfig) -> None:
        super().__init__(class_name="home-assistant-widget")
        self.config = config

        self._show_alt_label = False
        self._entity_states: dict[str, dict[str, Any]] = {}
        self._ws_connected = False

        self._init_container()
        self.build_widget_label(config.label, config.label_alt)

        self.register_callback("toggle_label", self._toggle_label)
        self.register_callback("refresh", self._refresh)
        self.register_callback("toggle", self._toggle)
        self.register_callback("toggle_first", self._toggle_first)
        self.register_callback("toggle_all", self._toggle_all)
        self.register_callback("call_service", self._call_service_cb)

        self.callback_left = config.callbacks.on_left
        self.callback_middle = config.callbacks.on_middle
        self.callback_right = config.callbacks.on_right

        self._ws_client: HomeAssistantClient | None = None
        self._poll_timer: QTimer | None = None
        self._rest_worker: HomeAssistantRestWorker | None = None

        if config.ws.enabled:
            self._init_websocket()

        if config.polling.enabled:
            self._init_polling()

        self._update_label()

    def _init_websocket(self) -> None:
        self._ws_client = HomeAssistantClient(
            base_url=self.config.base_url,
            token=self.config.token,
            reconnect_interval_ms=self.config.ws.reconnect_interval_ms,
            parent=self,
        )
        self._ws_client.state_changed.connect(self._on_state_changed)
        self._ws_client.states_fetched.connect(self._on_states_fetched)
        self._ws_client.connection_status.connect(self._on_ws_connection_status)
        self._ws_client.connect()

    def _init_polling(self) -> None:
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(self.config.polling.interval_ms)
        self._poll_timer.timeout.connect(self._do_poll)
        self._poll_timer.start()
        QTimer.singleShot(500, self._do_poll)

    @pyqtSlot(bool)
    def _on_ws_connection_status(self, connected: bool) -> None:
        self._ws_connected = connected
        if connected:
            logger.debug("Home Assistant WebSocket connected; pausing REST poll timer")
            if self._poll_timer:
                self._poll_timer.stop()
        else:
            logger.debug("Home Assistant WebSocket disconnected; resuming REST poll timer")
            if self._poll_timer and self.config.polling.enabled:
                if not self._poll_timer.isActive():
                    self._poll_timer.start()

    @pyqtSlot(dict)
    def _on_state_changed(self, new_state: dict) -> None:
        entity_id: str = new_state.get("entity_id", "")
        if not entity_id:
            return
        configured_ids = {e.entity_id for e in self.config.entities}
        if entity_id in configured_ids:
            self._entity_states[entity_id] = new_state
            self._update_label()

    @pyqtSlot(list)
    def _on_states_fetched(self, states: list) -> None:
        configured_ids = {e.entity_id for e in self.config.entities}
        for state in states:
            entity_id = state.get("entity_id", "")
            if entity_id in configured_ids:
                self._entity_states[entity_id] = state
        self._update_label()

    def _do_poll(self) -> None:
        if self._ws_connected:
            return
        entity_ids = [e.entity_id for e in self.config.entities]
        if not entity_ids:
            return
        if self._rest_worker and self._rest_worker.isRunning():
            return
        self._rest_worker = HomeAssistantRestWorker(
            base_url=self.config.base_url,
            token=self.config.token,
            entity_ids=entity_ids,
            timeout_ms=self.config.polling.timeout_ms,
            verify_ssl=self.config.polling.verify_ssl,
        )
        self._rest_worker.states_fetched.connect(self._on_states_fetched)
        self._rest_worker.start()

    def _build_label_text(self, template: str) -> str:
        """Replace YASB-style placeholders in *template* with current entity state data."""
        states = self._entity_states
        entities = self.config.entities

        # Aggregate counts
        total = len(entities)
        count_on = sum(1 for e in entities if states.get(e.entity_id, {}).get("state", "").lower() in ("on", "home", "open", "playing", "locked"))
        count_off = sum(1 for e in entities if states.get(e.entity_id, {}).get("state", "").lower() in ("off", "not_home", "closed", "paused", "unlocked"))
        count_unavailable = sum(1 for e in entities if states.get(e.entity_id, {}).get("state", "").lower() in ("unavailable", "unknown"))

        # Primary entity
        primary_cfg = None
        primary_id_pref = self.config.display.primary_entity or self.config.actions.primary_entity
        if primary_id_pref:
            primary_cfg = next((e for e in entities if e.entity_id == primary_id_pref), None)
        if primary_cfg is None and entities:
            primary_cfg = entities[0]

        primary_state_dict = states.get(primary_cfg.entity_id, {}) if primary_cfg else {}
        primary_state = primary_state_dict.get("state", "unavailable")
        primary_name = (
            (primary_cfg.display_name if primary_cfg and primary_cfg.display_name else None)
            or primary_state_dict.get("attributes", {}).get("friendly_name", "")
            or (primary_cfg.entity_id if primary_cfg else "")
        )
        primary_entity_id = primary_cfg.entity_id if primary_cfg else ""

        replacements = {
            "{count_total}": str(total),
            "{count_on}": str(count_on),
            "{count_off}": str(count_off),
            "{count_unavailable}": str(count_unavailable),
            "{primary.state}": primary_state,
            "{primary.name}": primary_name,
            "{primary.entity_id}": primary_entity_id,
            "{state}": primary_state,
        }

        result = template
        for placeholder, value in replacements.items():
            result = result.replace(placeholder, value)
        return result

    def _update_label(self) -> None:
        active_widgets = self._widgets_alt if self._show_alt_label else self._widgets
        active_template = self.config.label_alt if self._show_alt_label else self.config.label

        label_parts = re.split("(<span.*?>.*?</span>)", active_template)
        label_parts = [p for p in label_parts if p]

        widget_index = 0
        for part in label_parts:
            part = part.strip()
            if not part:
                continue
            if widget_index >= len(active_widgets):
                break
            w = active_widgets[widget_index]
            if not isinstance(w, QLabel):
                widget_index += 1
                continue
            if "<span" in part and "</span>" in part:
                icon = re.sub(r"<span.*?>|</span>", "", part).strip()
                w.setText(icon)
            else:
                w.setText(self._build_label_text(part))
            widget_index += 1

    def _toggle_label(self) -> None:
        self._show_alt_label = not self._show_alt_label
        for w in self._widgets:
            w.setVisible(not self._show_alt_label)
        for w in self._widgets_alt:
            w.setVisible(self._show_alt_label)
        self._update_label()

    def _refresh(self) -> None:
        if self._ws_client and self._ws_connected:
            self._ws_client.get_states()
        else:
            self._do_poll()

    def _toggle(self) -> None:
        target = self.config.actions.toggle_target
        if target == "all":
            self._toggle_all()
        elif target == "primary":
            self._toggle_primary()
        else:
            self._toggle_first()

    def _toggle_first(self) -> None:
        if not self.config.entities:
            return
        entity_id = self.config.entities[0].entity_id
        self._do_toggle(entity_id)

    def _toggle_all(self) -> None:
        for entity in self.config.entities:
            self._do_toggle(entity.entity_id)

    def _toggle_primary(self) -> None:
        pref_id = self.config.actions.primary_entity or self.config.display.primary_entity
        if pref_id:
            self._do_toggle(pref_id)
        elif self.config.entities:
            self._do_toggle(self.config.entities[0].entity_id)

    def _do_toggle(self, entity_id: str) -> None:
        domain = entity_id.split(".")[0]
        self._call_service(domain=domain, service="toggle", service_data={"entity_id": entity_id})

    def _call_service(self, domain: str, service: str, service_data: dict[str, Any] | None = None) -> None:
        if self._ws_client and self._ws_connected:
            self._ws_client.call_service(domain=domain, service=service, service_data=service_data)
        else:
            self._call_service_rest_bg(domain=domain, service=service, service_data=service_data)

    def _call_service_rest_bg(self, domain: str, service: str, service_data: dict[str, Any] | None = None) -> None:
        from PyQt6.QtCore import QThread

        class _Worker(QThread):
            def __init__(self, base_url, token, domain, service, service_data, timeout_ms):
                super().__init__()
                self._base_url = base_url
                self._token = token
                self._domain = domain
                self._service = service
                self._service_data = service_data
                self._timeout_ms = timeout_ms

            def run(self):
                call_service_rest(
                    base_url=self._base_url,
                    token=self._token,
                    domain=self._domain,
                    service=self._service,
                    service_data=self._service_data,
                    timeout_ms=self._timeout_ms,
                )

        worker = _Worker(
            base_url=self.config.base_url,
            token=self.config.token,
            domain=domain,
            service=service,
            service_data=service_data,
            timeout_ms=self.config.polling.timeout_ms,
        )
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def _call_service_cb(self, service_str: str = "", entity_id: str = "") -> None:
        """Callback entry point: ``call_service "domain.service" "entity_id"``."""
        if "." not in service_str:
            logger.warning("call_service: invalid service string '%s' (expected 'domain.service')", service_str)
            return
        domain, service = service_str.split(".", 1)
        service_data: dict[str, Any] = {}
        if entity_id:
            service_data["entity_id"] = entity_id
        self._call_service(domain=domain, service=service, service_data=service_data or None)
