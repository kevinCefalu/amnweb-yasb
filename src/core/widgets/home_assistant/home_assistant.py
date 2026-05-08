"""
Home Assistant widget for YASB.

Displays Home Assistant entity states and supports service calls (toggle, etc.).
Uses the WebSocket API as the preferred connection method and falls back to REST
polling when WebSocket is disabled or unavailable.
"""

import json
import logging
import os
import re
from typing import Any
from urllib.parse import urljoin, urlparse

from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSlot
from PyQt6.QtGui import QCloseEvent
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from core.utils.qobject import is_valid_qobject
from core.utils.tooltip import set_tooltip
from core.utils.utilities import PinnablePopup, refresh_widget_style
from core.validation.widgets.home_assistant.home_assistant import HaEntityConfig, HomeAssistantConfig
from core.widgets.base import BaseWidget
from core.widgets.services.home_assistant.client import HomeAssistantClient
from core.widgets.services.home_assistant.rest import HomeAssistantRestWorker, call_service_rest

logger = logging.getLogger("home_assistant_widget")


class HomeAssistantWidget(BaseWidget):
    validation_schema = HomeAssistantConfig

    _ON_STATES = frozenset({"on", "home", "open", "playing", "locked"})
    _OFF_STATES = frozenset({"off", "not_home", "closed", "paused", "unlocked"})

    def __init__(self, config: HomeAssistantConfig) -> None:
        super().__init__(class_name="home-assistant-widget")
        self.config = config

        self._show_alt_label = False
        self._entity_states: dict[str, dict[str, Any]] = {}
        self._template_states: dict[str, str] = {}
        self._ws_connected = False
        self._tooltip_enabled = config.tooltip
        self._dashboard_popup: PinnablePopup | None = None
        self._dashboard_auth_interceptor = None
        self._webengine_profile = None
        self._service_workers: set[QThread] = set()

        self._init_container()
        self.build_widget_label(config.label, config.label_alt)

        self.register_callback("toggle_label", self._toggle_label)
        self.register_callback("refresh", self._refresh)
        self.register_callback("toggle", self._toggle)
        self.register_callback("toggle_first", self._toggle_first)
        self.register_callback("toggle_all", self._toggle_all)
        self.register_callback("toggle_primary", self._toggle_primary)
        self.register_callback("toggle_dashboard", self._toggle_dashboard)
        self.register_callback("open_dashboard", self._toggle_dashboard)
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
        self._update_tooltip()

        if self._uses_dashboard_popup():
            QTimer.singleShot(1200, self._preload_dashboard_popup)

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
            self._render_entity_templates()
        else:
            logger.debug("Home Assistant WebSocket disconnected; resuming REST poll timer")
            self._template_states.clear()
            if self._poll_timer and self.config.polling.enabled:
                if not self._poll_timer.isActive():
                    self._poll_timer.start()
            self._update_label()

    @pyqtSlot(dict)
    def _on_state_changed(self, new_state: dict) -> None:
        entity_id: str = new_state.get("entity_id", "")
        if not entity_id:
            return
        configured_ids = {e.entity_id for e in self.config.entities}
        if entity_id in configured_ids:
            self._entity_states[entity_id] = new_state
            self._update_label()
            entity_cfg = next((e for e in self.config.entities if e.entity_id == entity_id), None)
            if entity_cfg and entity_cfg.template:
                self._render_entity_template(entity_cfg)

    @pyqtSlot(list)
    def _on_states_fetched(self, states: list) -> None:
        configured_ids = {e.entity_id for e in self.config.entities}
        for state in states:
            entity_id = state.get("entity_id", "")
            if entity_id in configured_ids:
                self._entity_states[entity_id] = state
        self._update_label()
        self._render_entity_templates()

    def _render_entity_templates(self) -> None:
        """Request server-side Jinja2 rendering for every entity that has a template configured."""
        if not (self._ws_client and self._ws_connected):
            return
        for entity_cfg in self.config.entities:
            if entity_cfg.template:
                self._render_entity_template(entity_cfg)

    def _render_entity_template(self, entity_cfg: HaEntityConfig) -> None:
        """Fire a render_template WebSocket request for a single entity and update its state on response."""
        if not (self._ws_client and self._ws_connected) or not entity_cfg.template:
            return
        entity_id = entity_cfg.entity_id

        def _on_rendered(rendered: str, eid: str = entity_id) -> None:
            self._template_states[eid] = str(rendered)
            self._update_label()

        self._ws_client.render_template(entity_cfg.template, callback=_on_rendered)

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
        count_on = sum(1 for e in entities if states.get(e.entity_id, {}).get("state", "").lower() in self._ON_STATES)
        count_off = sum(1 for e in entities if states.get(e.entity_id, {}).get("state", "").lower() in self._OFF_STATES)
        count_unavailable = sum(
            1 for e in entities if states.get(e.entity_id, {}).get("state", "").lower() in ("unavailable", "unknown")
        )

        # Primary entity
        primary_cfg = None
        primary_id_pref = self.config.display.primary_entity or self.config.actions.primary_entity
        if primary_id_pref:
            primary_cfg = next((e for e in entities if e.entity_id == primary_id_pref), None)
        if primary_cfg is None and entities:
            primary_cfg = entities[0]

        primary_state_dict = states.get(primary_cfg.entity_id, {}) if primary_cfg else {}
        primary_state_raw = primary_state_dict.get("state", "unavailable")
        primary_state = (
            self._template_states.get(primary_cfg.entity_id, primary_state_raw) if primary_cfg else "unavailable"
        )
        primary_state_key = str(primary_state_raw).lower()
        primary_name = (
            (primary_cfg.display_name if primary_cfg and primary_cfg.display_name else None)
            or primary_state_dict.get("attributes", {}).get("friendly_name", "")
            or (primary_cfg.entity_id if primary_cfg else "")
        )
        primary_entity_id = primary_cfg.entity_id if primary_cfg else ""

        state_icon_map = {str(k).lower(): v for k, v in self.config.state_icons.items()}
        primary_icon = state_icon_map.get(primary_state_key)
        if primary_icon is None:
            primary_icon = (
                (primary_cfg.icon if primary_cfg and primary_cfg.icon else None) or self.config.state_icon_default or ""
            )

        replacements = {
            "{count_total}": str(total),
            "{count_on}": str(count_on),
            "{count_off}": str(count_off),
            "{count_unavailable}": str(count_unavailable),
            "{primary.state}": primary_state,
            "{primary.name}": primary_name,
            "{primary.entity_id}": primary_entity_id,
            "{primary.icon}": primary_icon,
            "{icon}": primary_icon,
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
                w.setText(self._build_label_text(icon))
            else:
                w.setText(self._build_label_text(part))
            widget_index += 1

        self._update_tooltip()

    def _update_tooltip(self) -> None:
        if not self._tooltip_enabled:
            return
        if self.config.tooltip_label:
            tooltip_template = self.config.tooltip_label
        else:
            active_template = self.config.label_alt if self._show_alt_label else self.config.label
            tooltip_template = re.sub(r"<span[^>]*>|</span>", "", active_template)
        tooltip_text = self._build_label_text(tooltip_template).strip()
        if tooltip_text:
            set_tooltip(self._widget_container, tooltip_text)

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

    def _on_dashboard_popup_destroyed(self) -> None:
        self._dashboard_popup = None

    def _dashboard_url(self) -> str:
        return self.config.dashboard_url or urljoin(self.config.base_url.rstrip("/") + "/", "lovelace")

    def _uses_dashboard_popup(self) -> bool:
        dashboard_callbacks = {"toggle_dashboard", "open_dashboard"}
        return any(
            callback in dashboard_callbacks
            for callback in (
                self.config.callbacks.on_left,
                self.config.callbacks.on_middle,
                self.config.callbacks.on_right,
            )
        ) or any(binding.action in dashboard_callbacks for binding in self.config.keybindings)

    def _preload_dashboard_popup(self) -> None:
        self._ensure_dashboard_popup()

    def _ensure_dashboard_popup(self) -> PinnablePopup | None:
        popup = self._dashboard_popup
        if popup is not None and not is_valid_qobject(popup):
            self._dashboard_popup = None
            popup = None

        if popup is None:
            popup = self._create_dashboard_popup()

        return popup

    def _create_dashboard_popup(self) -> PinnablePopup:
        dashboard_url = self._dashboard_url()
        popup_cfg = self.config.dashboard_popup

        popup = PinnablePopup(
            self,
            popup_cfg.blur,
            popup_cfg.round_corners,
            popup_cfg.round_corners_type,
            popup_cfg.border_color,
        )
        popup.setProperty("class", "home-assistant-dashboard-popup")
        popup.setFixedSize(popup_cfg.width, popup_cfg.height)
        popup.set_retain_on_close(True)
        popup.set_fade_durations(180, 120)

        # Header dragging handlers (similar to AI Chat's floating window controller)
        _header_drag_pos = None

        def _header_mouse_press(event, popup_ref):
            if popup_ref._is_pinned and event.button() == Qt.MouseButton.LeftButton:
                nonlocal _header_drag_pos
                _header_drag_pos = event.globalPosition().toPoint() - popup_ref.frameGeometry().topLeft()
                event.accept()

        def _header_mouse_move(event, popup_ref):
            if popup_ref._is_pinned and _header_drag_pos is not None and event.buttons() & Qt.MouseButton.LeftButton:
                popup_ref.move(event.globalPosition().toPoint() - _header_drag_pos)
                event.accept()

        def _header_mouse_release(event, popup_ref):
            nonlocal _header_drag_pos
            if _header_drag_pos is not None:
                _header_drag_pos = None
                event.accept()

        main_layout = QVBoxLayout(popup)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        header = QFrame()
        header.setProperty("class", "header")
        # Enable dragging when pinned by setting up mouse handlers
        header.mousePressEvent = lambda a0: _header_mouse_press(a0, popup)
        header.mouseMoveEvent = lambda a0: _header_mouse_move(a0, popup)
        header.mouseReleaseEvent = lambda a0: _header_mouse_release(a0, popup)

        header_layout = QVBoxLayout(header)
        header_layout.setSpacing(0)
        header_layout.setContentsMargins(0, 0, 0, 0)

        selection_row = QHBoxLayout()
        selection_row.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        title = QLabel(popup_cfg.title)
        title.setProperty("class", "title")
        selection_row.addWidget(title)
        selection_row.addStretch(1)

        float_on_icon = "\udb84\udcac"
        float_off_icon = "\udb84\udca9"
        close_icon = "\uf00d"

        pin_btn = QPushButton(float_on_icon)
        pin_btn.setProperty("class", "float-button")
        pin_btn.setCheckable(True)
        set_tooltip(pin_btn, "Float window")

        close_btn = QPushButton(close_icon)
        close_btn.setProperty("class", "close-button")
        close_btn.setVisible(False)  # Hidden by default, shown when pinned
        close_btn.clicked.connect(popup.hide_animated)

        def _on_pin_toggled(checked: bool) -> None:
            popup.set_pinned(checked)
            popup.setProperty(
                "class", "home-assistant-dashboard-popup floating" if checked else "home-assistant-dashboard-popup"
            )
            pin_btn.setText(float_off_icon if checked else float_on_icon)
            set_tooltip(pin_btn, "Dock window" if checked else "Float window")
            # Show close button when pinned, hide when unpinned (like AI Chat)
            close_btn.setVisible(checked)
            refresh_widget_style(popup, pin_btn, close_btn)

        pin_btn.toggled.connect(_on_pin_toggled)
        selection_row.addWidget(pin_btn)
        selection_row.addWidget(close_btn)

        header_layout.addLayout(selection_row)

        main_layout.addWidget(header, 0)

        content = QFrame()
        content.setProperty("class", "content")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        webengine_loaded = False
        try:
            from PyQt6.QtCore import QUrl
            from PyQt6.QtWebEngineCore import QWebEnginePage, QWebEngineUrlRequestInterceptor
            from PyQt6.QtWebEngineWidgets import QWebEngineView

            target_host = (urlparse(self.config.base_url).hostname or "").lower()
            token = (self.config.token or "").strip()
            auth_mode = popup_cfg.auth_mode
            token_ttl_seconds = popup_cfg.legacy_token_ttl_seconds

            class _HaAuthInterceptor(QWebEngineUrlRequestInterceptor):
                def __init__(self, host: str, bearer_token: str) -> None:
                    super().__init__()
                    self._host = host
                    self._bearer_token = bearer_token

                def interceptRequest(self, info):  # type: ignore[override]
                    if not self._host or not self._bearer_token:
                        return
                    req_host = info.requestUrl().host().lower()
                    if req_host == self._host:
                        info.setHttpHeader(b"Authorization", f"Bearer {self._bearer_token}".encode())

            class _FilteredConsolePage(QWebEnginePage):
                _IGNORED_SUBSTRINGS = (
                    "Found 2 elements with non-unique id #input",
                    "The main 'lit-element' module entrypoint is deprecated",
                    "browser_mod.js?automatically-added",
                    'the name "remote-button" has already been used with this registry',
                    "Cannot convert undefined or null to object",
                )

                def javaScriptConsoleMessage(self, level, message, line_number, source_id):  # type: ignore[override]
                    if any(ignored_substring in message for ignored_substring in self._IGNORED_SUBSTRINGS):
                        return

                    source = source_id or "<unknown>"
                    if level == QWebEnginePage.JavaScriptConsoleMessageLevel.ErrorMessageLevel:
                        logger.warning("HA webview JS error (%s:%s): %s", source, line_number, message)
                    elif level == QWebEnginePage.JavaScriptConsoleMessageLevel.WarningMessageLevel:
                        logger.info("HA webview JS warning (%s:%s): %s", source, line_number, message)
                    else:
                        logger.debug("HA webview JS (%s:%s): %s", source, line_number, message)

            # --- Persistent profile: keeps localStorage / cookies across popup opens and app restarts ---
            if self._webengine_profile is None:
                from PyQt6.QtWebEngineCore import QWebEngineProfile

                _profile_dir = os.path.join(os.path.expanduser("~"), ".config", "yasb", "webengine", "ha_dashboard")
                os.makedirs(_profile_dir, exist_ok=True)
                _p = QWebEngineProfile("ha_dashboard")
                _p.setPersistentStoragePath(_profile_dir)
                _p.setCachePath(os.path.join(_profile_dir, "cache"))
                _p.setPersistentCookiesPolicy(QWebEngineProfile.PersistentCookiesPolicy.AllowPersistentCookies)
                self._webengine_profile = _p

            if (
                auth_mode == "legacy_token_injection"
                and target_host
                and token
                and self._dashboard_auth_interceptor is None
            ):
                self._dashboard_auth_interceptor = _HaAuthInterceptor(target_host, token)
            if auth_mode == "legacy_token_injection" and self._dashboard_auth_interceptor is not None:
                self._webengine_profile.setUrlRequestInterceptor(self._dashboard_auth_interceptor)
            else:
                # Browser-login mode should not inject auth headers from config token.
                self._webengine_profile.setUrlRequestInterceptor(None)

            webview = QWebEngineView(content)
            webview.setProperty("class", "dashboard-webview")
            page = _FilteredConsolePage(self._webengine_profile, webview)
            webview.setPage(page)

            if auth_mode == "legacy_token_injection" and token:
                logger.warning(
                    "Home Assistant dashboard popup is using legacy_token_injection auth mode. "
                    "Prefer browser_login for safer authentication handling."
                )

                _ha_url = self.config.base_url.rstrip("/")
                _token_val = token
                _inject_js = (
                    "(function(){"
                    "  try {"
                    "    const now = Math.floor(Date.now() / 1000);"
                    "    let shouldSetToken = true;"
                    "    const raw = localStorage.getItem('hassTokens');"
                    "    if (raw) {"
                    "      try {"
                    "        const existing = JSON.parse(raw);"
                    "        const expiresOn = Number(existing?.expires_on || 0);"
                    "        shouldSetToken = !Number.isFinite(expiresOn) || (expiresOn - now) <= 60;"
                    "      } catch (_err) {"
                    "        shouldSetToken = true;"
                    "      }"
                    "    }"
                    "    if (!shouldSetToken) { return; }"
                    f"    const ttl = {token_ttl_seconds};"
                    "    localStorage.setItem('hassUrl', " + json.dumps(_ha_url) + ");"
                    "    localStorage.setItem('hassTokens', JSON.stringify({"
                    "      access_token: " + json.dumps(_token_val) + ","
                    "      token_type: 'Bearer',"
                    "      expires_in: ttl,"
                    "      expires_on: now + ttl"
                    "    }));"
                    "    location.reload();"
                    "  } catch (_err) {}"
                    "})()"
                )

                def _inject_ha_auth(ok: bool) -> None:
                    if ok and is_valid_qobject(page):
                        page.runJavaScript(_inject_js)

                webview.loadFinished.connect(_inject_ha_auth)

            webview.setUrl(QUrl(dashboard_url))

            content_layout.addWidget(webview, 1)
            webengine_loaded = True
        except Exception:
            logger.exception("Failed to create embedded HA dashboard webview")

        if not webengine_loaded:
            fallback = QLabel("Embedded dashboard requires PyQt6-WebEngine.<br><a href='open'>Open in Browser</a>")
            fallback.setProperty("class", "fallback")
            fallback.setWordWrap(True)
            fallback.setTextFormat(Qt.TextFormat.RichText)
            fallback.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
            fallback.setOpenExternalLinks(False)
            fallback.setAlignment(Qt.AlignmentFlag.AlignCenter)
            fallback.linkActivated.connect(lambda _link: os.startfile(dashboard_url))
            content_layout.addWidget(fallback)

        main_layout.addWidget(content, 1)

        self._dashboard_popup = popup
        popup.destroyed.connect(self._on_dashboard_popup_destroyed)
        popup.set_pinned(False)
        popup.set_auto_close_enabled(True)

        return popup

    def _toggle_dashboard(self) -> None:
        popup = self._ensure_dashboard_popup()
        if popup is None:
            return

        try:
            if popup.isVisible():
                popup.hide_animated()
                return
        except RuntimeError:
            self._dashboard_popup = None
            popup = self._ensure_dashboard_popup()
            if popup is None:
                return

        popup_cfg = self.config.dashboard_popup
        popup.setPosition(
            alignment=popup_cfg.alignment,
            direction=popup_cfg.direction,
            offset_left=popup_cfg.offset_left,
            offset_top=popup_cfg.offset_top,
        )
        popup.show()

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
        class _RestServiceWorker(QThread):
            def __init__(self, base_url, token, domain, service, service_data, timeout_ms, verify_ssl):
                super().__init__()
                self._base_url = base_url
                self._token = token
                self._domain = domain
                self._service = service
                self._service_data = service_data
                self._timeout_ms = timeout_ms
                self._verify_ssl = verify_ssl

            def run(self):
                call_service_rest(
                    base_url=self._base_url,
                    token=self._token,
                    domain=self._domain,
                    service=self._service,
                    service_data=self._service_data,
                    timeout_ms=self._timeout_ms,
                    verify_ssl=self._verify_ssl,
                )

        worker = _RestServiceWorker(
            base_url=self.config.base_url,
            token=self.config.token,
            domain=domain,
            service=service,
            service_data=service_data,
            timeout_ms=self.config.polling.timeout_ms,
            verify_ssl=self.config.polling.verify_ssl,
        )
        self._service_workers.add(worker)
        worker.finished.connect(lambda w=worker: self._on_service_worker_finished(w))
        worker.start()

    def _on_service_worker_finished(self, worker: QThread) -> None:
        self._service_workers.discard(worker)
        worker.deleteLater()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._poll_timer and self._poll_timer.isActive():
            self._poll_timer.stop()

        if self._rest_worker and self._rest_worker.isRunning():
            self._rest_worker.quit()
            self._rest_worker.wait(1500)

        if self._ws_client:
            self._ws_client.disconnect()

        for worker in list(self._service_workers):
            try:
                if worker.isRunning():
                    worker.quit()
                    worker.wait(1500)
            finally:
                self._service_workers.discard(worker)
                worker.deleteLater()

        if self._dashboard_popup and is_valid_qobject(self._dashboard_popup):
            self._dashboard_popup.hide()
            self._dashboard_popup.deleteLater()
            self._dashboard_popup = None

        super().closeEvent(event)

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
