"""
Home Assistant WebSocket client.

Implements the Home Assistant WebSocket API authentication and subscription flow.
Reference: https://developers.home-assistant.io/docs/api/websocket/
"""

import json
import logging
from typing import Any, Callable

from PyQt6.QtCore import QObject, QTimer, QUrl, pyqtSignal
from PyQt6.QtNetwork import QAbstractSocket
from PyQt6.QtWebSockets import QWebSocket

logger = logging.getLogger("home_assistant_client")


class HomeAssistantClient(QObject):
    """
    QWebSocket-based client for the Home Assistant WebSocket API.

    Connection lifecycle:
      1. Connect to ws(s)://<host>/api/websocket
      2. Receive ``auth_required`` → send ``auth`` message
      3. Receive ``auth_ok`` → subscribe to ``state_changed`` events + fetch initial states
      4. Receive ``event`` messages → emit :attr:`state_changed`
      5. On disconnect: start reconnect timer
    """

    state_changed = pyqtSignal(dict)
    """Emitted when a ``state_changed`` event is received from Home Assistant."""

    states_fetched = pyqtSignal(list)
    """Emitted when the initial ``get_states`` response is received."""

    connection_status = pyqtSignal(bool)
    """Emitted with ``True`` on connection, ``False`` on disconnect/error."""

    template_rendered = pyqtSignal(int, str)
    """Emitted when a ``render_template`` response arrives (msg_id, rendered_text)."""

    service_called = pyqtSignal(int, bool)
    """Emitted when a ``call_service`` response arrives (msg_id, success)."""

    def __init__(
        self,
        base_url: str,
        token: str,
        reconnect_interval_ms: int = 4000,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)

        self._base_url = base_url.rstrip("/")
        self._token = token
        self._msg_id = 1
        self._authenticated = False
        self._subscribe_id: int | None = None

        ws_scheme = "wss" if self._base_url.startswith("https") else "ws"
        host_part = self._base_url.split("://", 1)[-1]
        self._uri = QUrl(f"{ws_scheme}://{host_part}/api/websocket")

        self._websocket = QWebSocket()
        self._websocket.connected.connect(self._on_connected)  # type: ignore
        self._websocket.disconnected.connect(self._on_disconnected)  # type: ignore
        self._websocket.textMessageReceived.connect(self._handle_message)  # type: ignore
        self._websocket.errorOccurred.connect(self._on_error)  # type: ignore

        self._reconnect_timer = QTimer(self)
        self._reconnect_timer.setInterval(reconnect_interval_ms)
        self._reconnect_timer.setSingleShot(False)
        self._reconnect_timer.timeout.connect(self.connect)  # type: ignore

        self._pending_callbacks: dict[int, Callable[[dict], None]] = {}

    def connect(self) -> None:
        """Open the WebSocket connection (no-op if already connected)."""
        if self._websocket.state() == QAbstractSocket.SocketState.ConnectedState:
            return
        logger.debug("Connecting to %s", self._uri.toString())
        self._websocket.open(self._uri)

    def disconnect(self) -> None:
        """Close the WebSocket connection and stop the reconnect timer."""
        self._reconnect_timer.stop()
        self._websocket.close()

    def is_connected(self) -> bool:
        return self._websocket.state() == QAbstractSocket.SocketState.ConnectedState

    def get_states(self) -> None:
        """Request all entity states from Home Assistant."""
        if not self._authenticated:
            return
        self._send({"type": "get_states"})

    def call_service(
        self,
        domain: str,
        service: str,
        service_data: dict[str, Any] | None = None,
        callback: Callable[[dict], None] | None = None,
    ) -> int:
        """
        Call a Home Assistant service.

        Returns the message id so the caller can correlate the response.
        """
        if not self._authenticated:
            return -1
        payload: dict[str, Any] = {
            "type": "call_service",
            "domain": domain,
            "service": service,
        }
        if service_data:
            payload["service_data"] = service_data
        msg_id = self._send(payload)
        if callback is not None:
            self._pending_callbacks[msg_id] = callback
        return msg_id

    def render_template(self, template: str, callback: Callable[[str], None] | None = None) -> int:
        """
        Ask Home Assistant to render a Jinja2 template server-side.

        Returns the message id.
        """
        if not self._authenticated:
            return -1
        msg_id = self._send({"type": "render_template", "template": template})
        if callback is not None:
            self._pending_callbacks[msg_id] = lambda msg: callback(msg.get("result", ""))
        return msg_id

    def _send(self, payload: dict[str, Any]) -> int:
        msg_id = self._msg_id
        self._msg_id += 1
        payload["id"] = msg_id
        self._websocket.sendTextMessage(json.dumps(payload))
        return msg_id

    def _on_connected(self) -> None:
        logger.debug("WebSocket connected to %s", self._uri.toString())
        self._reconnect_timer.stop()
        self._authenticated = False

    def _on_disconnected(self) -> None:
        logger.debug("WebSocket disconnected from %s", self._uri.toString())
        self._authenticated = False
        self.connection_status.emit(False)
        self._reconnect_timer.start()

    def _on_error(self, error: QAbstractSocket.SocketError) -> None:
        logger.warning("WebSocket error: %s – scheduling reconnect", error)
        self._reconnect_timer.start()

    def _handle_message(self, raw: str) -> None:
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Received non-JSON message from Home Assistant")
            return

        msg_type = msg.get("type")

        if msg_type == "auth_required":
            self._websocket.sendTextMessage(json.dumps({"type": "auth", "access_token": self._token}))

        elif msg_type == "auth_ok":
            logger.debug("Home Assistant authentication successful")
            self._authenticated = True
            self.connection_status.emit(True)
            self._subscribe_state_changed()
            self.get_states()

        elif msg_type == "auth_invalid":
            logger.error("Home Assistant authentication failed: %s", msg.get("message"))
            self.connection_status.emit(False)
            self.disconnect()

        elif msg_type == "event":
            event = msg.get("event", {})
            if event.get("event_type") == "state_changed":
                data = event.get("data", {})
                new_state = data.get("new_state")
                if new_state:
                    self.state_changed.emit(new_state)

        elif msg_type == "result":
            self._handle_result(msg)

        else:
            logger.debug("Unhandled message type: %s", msg_type)

    def _handle_result(self, msg: dict[str, Any]) -> None:
        msg_id: int | None = msg.get("id")
        success: bool = msg.get("success", False)
        result = msg.get("result")

        if msg_id is not None and msg_id in self._pending_callbacks:
            try:
                self._pending_callbacks[msg_id](msg)
            except Exception:
                logger.exception("Error in pending callback for message id %d", msg_id)
            finally:
                del self._pending_callbacks[msg_id]
            return

        if not success:
            logger.warning("Home Assistant result error (id=%s): %s", msg_id, msg.get("error"))
            return

        if isinstance(result, list):
            # Response to get_states
            self.states_fetched.emit(result)

        if msg_id == self._subscribe_id:
            logger.debug("State-changed subscription confirmed (id=%d)", msg_id)

    def _subscribe_state_changed(self) -> None:
        """Subscribe to ``state_changed`` events."""
        payload: dict[str, Any] = {
            "type": "subscribe_events",
            "event_type": "state_changed",
        }
        self._subscribe_id = self._send(payload)
        logger.debug("Subscribed to state_changed events (id=%d)", self._subscribe_id)
