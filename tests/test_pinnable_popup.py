import sys
import unittest
from pathlib import Path

from PyQt6.QtCore import QEvent, QPoint, QPointF, Qt
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import QApplication, QWidget

# Ensure local src/ imports resolve when running tests from repo root.
REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from core.utils.utilities import PinnablePopup  # noqa: E402


class _TestablePinnablePopup(PinnablePopup):
    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.hide_animated_calls = 0

    def hide_animated(self):
        self.hide_animated_calls += 1


class PinnablePopupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.parent = QWidget()
        self.parent.resize(200, 120)
        self.popup = _TestablePinnablePopup(self.parent)
        self.popup.resize(100, 60)
        self.popup.move(20, 30)

    def tearDown(self):
        self.popup.deleteLater()
        self.parent.deleteLater()

    def _mouse_event(
        self,
        event_type: QEvent.Type,
        local_pos: QPoint,
        global_pos: QPoint,
        button: Qt.MouseButton,
        buttons: Qt.MouseButton,
    ) -> QMouseEvent:
        return QMouseEvent(
            event_type,
            QPointF(local_pos),
            QPointF(global_pos),
            button,
            buttons,
            Qt.KeyboardModifier.NoModifier,
        )

    def test_set_pinned_false_clears_drag_position(self):
        self.popup.set_pinned(True)
        self.popup._drag_pos = QPoint(7, 9)

        self.popup.set_pinned(False)

        self.assertFalse(self.popup.is_pinned)
        self.assertIsNone(self.popup._drag_pos)

    def test_mouse_press_sets_drag_position_when_pinned(self):
        self.popup.set_pinned(True)
        press_event = self._mouse_event(
            QEvent.Type.MouseButtonPress,
            QPoint(10, 10),
            QPoint(130, 170),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
        )

        self.popup.mousePressEvent(press_event)

        expected = QPoint(130, 170) - self.popup.frameGeometry().topLeft()
        self.assertEqual(self.popup._drag_pos, expected)
        self.assertTrue(press_event.isAccepted())

    def test_mouse_move_updates_position_when_dragging(self):
        self.popup.set_pinned(True)
        self.popup._drag_pos = QPoint(12, 14)
        move_event = self._mouse_event(
            QEvent.Type.MouseMove,
            QPoint(15, 15),
            QPoint(260, 300),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.LeftButton,
        )

        self.popup.mouseMoveEvent(move_event)

        self.assertEqual(self.popup.pos(), QPoint(248, 286))
        self.assertTrue(move_event.isAccepted())

    def test_mouse_release_clears_drag_position_when_pinned(self):
        self.popup.set_pinned(True)
        self.popup._drag_pos = QPoint(4, 6)
        release_event = self._mouse_event(
            QEvent.Type.MouseButtonRelease,
            QPoint(15, 15),
            QPoint(50, 60),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.NoButton,
        )

        self.popup.mouseReleaseEvent(release_event)

        self.assertIsNone(self.popup._drag_pos)
        self.assertTrue(release_event.isAccepted())

    def test_window_deactivate_event_hides_only_when_unpinned(self):
        event_unpinned = QEvent(QEvent.Type.WindowDeactivate)

        handled_unpinned = self.popup.event(event_unpinned)

        self.assertTrue(handled_unpinned)
        self.assertEqual(self.popup.hide_animated_calls, 1)

        self.popup.set_pinned(True)
        event_pinned = QEvent(QEvent.Type.WindowDeactivate)

        handled_pinned = self.popup.event(event_pinned)

        self.assertTrue(handled_pinned)
        self.assertEqual(self.popup.hide_animated_calls, 1)
        self.assertTrue(event_pinned.isAccepted())


if __name__ == "__main__":
    unittest.main()
