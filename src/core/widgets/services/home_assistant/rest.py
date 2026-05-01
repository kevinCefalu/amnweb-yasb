"""
Home Assistant REST API helper.

Provides a QThread-based worker for polling entity states and calling services
via the Home Assistant REST API.

Reference: https://www.home-assistant.io/docs/api/rest/
"""

import json
import logging
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from PyQt6.QtCore import QThread, pyqtSignal

logger = logging.getLogger("home_assistant_rest")


class HomeAssistantRestWorker(QThread):
    """
    Background thread that polls Home Assistant entity states via REST.

    Signals
    -------
    states_fetched:
        Emitted with a list of state dicts when the poll completes successfully.
    error_occurred:
        Emitted with an error message string on failure.
    """

    states_fetched = pyqtSignal(list)
    error_occurred = pyqtSignal(str)

    def __init__(
        self,
        base_url: str,
        token: str,
        entity_ids: list[str],
        timeout_ms: int = 5000,
        verify_ssl: bool = True,
    ) -> None:
        super().__init__()
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._entity_ids = entity_ids
        self._timeout_s = max(timeout_ms / 1000.0, 0.5)
        self._verify_ssl = verify_ssl

    def run(self) -> None:
        states: list[dict[str, Any]] = []
        for entity_id in self._entity_ids:
            state = self._get_state(entity_id)
            if state is not None:
                states.append(state)
        if states:
            self.states_fetched.emit(states)

    def _get_state(self, entity_id: str) -> dict[str, Any] | None:
        url = f"{self._base_url}/api/states/{entity_id}"
        try:
            req = Request(url, headers={"Authorization": f"Bearer {self._token}", "Content-Type": "application/json"})
            with urlopen(req, timeout=self._timeout_s) as resp:
                return json.loads(resp.read().decode())
        except HTTPError as exc:
            logger.warning("REST GET %s failed: HTTP %s", url, exc.code)
        except URLError as exc:
            logger.warning("REST GET %s failed: %s", url, exc.reason)
        except Exception:
            logger.exception("REST GET %s unexpected error", url)
        return None


def call_service_rest(
    base_url: str,
    token: str,
    domain: str,
    service: str,
    service_data: dict[str, Any] | None = None,
    timeout_ms: int = 5000,
) -> bool:
    """
    Call a Home Assistant service via REST (synchronous).

    Returns ``True`` on success, ``False`` on failure.
    Intended to be called from a background thread.
    """
    url = f"{base_url.rstrip('/')}/api/services/{domain}/{service}"
    payload = json.dumps(service_data or {}).encode()
    try:
        req = Request(
            url,
            data=payload,
            method="POST",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        )
        timeout_s = max(timeout_ms / 1000.0, 0.5)
        with urlopen(req, timeout=timeout_s):
            return True
    except HTTPError as exc:
        logger.warning("REST POST %s failed: HTTP %s", url, exc.code)
    except URLError as exc:
        logger.warning("REST POST %s failed: %s", url, exc.reason)
    except Exception:
        logger.exception("REST POST %s unexpected error", url)
    return False
