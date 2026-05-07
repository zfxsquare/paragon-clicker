from __future__ import annotations

import ctypes
import ctypes.wintypes
import sys
import time
from dataclasses import dataclass
from typing import Any

import psutil


SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79


def configure_dpi_awareness() -> None:
    if sys.platform != "win32":
        return

    try:
        user32 = ctypes.windll.user32
        user32.SetProcessDpiAwarenessContext.restype = ctypes.c_bool
        user32.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        if user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
            return
    except Exception:
        pass

    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return
    except Exception:
        pass

    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


configure_dpi_awareness()

from PySide6 import QtCore, QtGui, QtWidgets

from paragon_clicker.d2core import (
    GRID_SIZE,
    apply_progression_strategy,
    build_sequence_from_planner_input,
)


MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004


@dataclass(slots=True)
class ClickPoint:
    step: int
    local_step: int
    node_name: str
    node_kind: str
    board_key: str
    row: int
    col: int
    x: int
    y: int


@dataclass(slots=True)
class BoardSequence:
    board_key: str
    board_name: str
    board_index: int
    board_rotate: int
    entry_nodes: list[dict[str, Any]]
    steps: list[dict[str, Any]]

    @property
    def label(self) -> str:
        return f"{self.board_index}: {self.board_name} ({self.board_key})"


def get_virtual_screen_geometry() -> QtCore.QRect:
    if sys.platform == "win32":
        user32 = ctypes.windll.user32
        left = int(user32.GetSystemMetrics(SM_XVIRTUALSCREEN))
        top = int(user32.GetSystemMetrics(SM_YVIRTUALSCREEN))
        width = int(user32.GetSystemMetrics(SM_CXVIRTUALSCREEN))
        height = int(user32.GetSystemMetrics(SM_CYVIRTUALSCREEN))
        return QtCore.QRect(left, top, width, height)

    return QtGui.QGuiApplication.primaryScreen().virtualGeometry()


def get_cursor_pos() -> QtCore.QPoint:
    if sys.platform == "win32":
        point = ctypes.wintypes.POINT()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(point))
        return QtCore.QPoint(int(point.x), int(point.y))

    return QtGui.QCursor.pos()


def global_point_to_local(widget: QtWidgets.QWidget, point: QtCore.QPoint) -> QtCore.QPoint:
    geometry = widget.geometry()
    return QtCore.QPoint(point.x() - geometry.x(), point.y() - geometry.y())


def global_rect_to_local(widget: QtWidgets.QWidget, rect: QtCore.QRect) -> QtCore.QRect:
    top_left = global_point_to_local(widget, rect.topLeft())
    bottom_right = global_point_to_local(widget, rect.bottomRight())
    return QtCore.QRect(top_left, bottom_right).normalized()


class SelectionOverlay(QtWidgets.QWidget):
    selection_made = QtCore.Signal(QtCore.QRect)
    selection_cancelled = QtCore.Signal()

    def __init__(self, preview_cells: list[tuple[int, int]] | None = None) -> None:
        super().__init__()
        self.setWindowTitle("Select Board Region")
        self.setWindowFlag(QtCore.Qt.WindowType.FramelessWindowHint, True)
        self.setWindowFlag(QtCore.Qt.WindowType.WindowStaysOnTopHint, True)
        self.setWindowFlag(QtCore.Qt.WindowType.Tool, True)
        self.setWindowModality(QtCore.Qt.WindowModality.ApplicationModal)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setCursor(QtCore.Qt.CursorShape.CrossCursor)

        self._start: QtCore.QPoint | None = None
        self._end: QtCore.QPoint | None = None
        self._preview_cells = preview_cells or []

        screen_rect = get_virtual_screen_geometry()
        self.setGeometry(screen_rect)

    def show_and_focus(self) -> None:
        self.showFullScreen()
        self.raise_()
        self.activateWindow()

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() != QtCore.Qt.MouseButton.LeftButton:
            return
        self._start = get_cursor_pos()
        self._end = self._start
        self.update()

    def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:
        if self._start is None:
            return
        self._end = get_cursor_pos()
        self.update()

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() != QtCore.Qt.MouseButton.LeftButton or self._start is None:
            return
        self._end = get_cursor_pos()
        rect = QtCore.QRect(self._start, self._end).normalized()
        self.close()
        if rect.width() < 5 or rect.height() < 5:
            self.selection_cancelled.emit()
            return
        self.selection_made.emit(rect)

    def keyPressEvent(self, event: QtGui.QKeyEvent) -> None:
        if event.key() == QtCore.Qt.Key.Key_Escape:
            self.close()
            self.selection_cancelled.emit()
            return
        super().keyPressEvent(event)

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(self.rect(), QtGui.QColor(5, 8, 16, 90))
        instruction = (
            "Drag from the board rectangle top-left corner to bottom-right corner. "
            "Grid lines and click points are previewed live while selecting. Press Esc to cancel."
        )
        painter.setPen(QtGui.QPen(QtGui.QColor(245, 247, 255), 1))
        painter.setFont(QtGui.QFont("Segoe UI", 12))
        painter.drawText(24, 36, instruction)

        if self._start is None or self._end is None:
            return

        rect = global_rect_to_local(self, QtCore.QRect(self._start, self._end).normalized())
        painter.setCompositionMode(QtGui.QPainter.CompositionMode.CompositionMode_Clear)
        painter.fillRect(rect, QtCore.Qt.GlobalColor.transparent)
        painter.setCompositionMode(
            QtGui.QPainter.CompositionMode.CompositionMode_SourceOver
        )
        painter.setPen(QtGui.QPen(QtGui.QColor(122, 162, 255), 2))
        painter.setBrush(QtGui.QColor(122, 162, 255, 40))
        painter.drawRect(rect)

        width = rect.right() - rect.left()
        height = rect.bottom() - rect.top()
        if width <= 0 or height <= 0:
            return

        cell_width = width / GRID_SIZE
        cell_height = height / GRID_SIZE

        grid_pen = QtGui.QPen(QtGui.QColor(97, 232, 255, 130), 1)
        painter.setPen(grid_pen)
        for index in range(1, GRID_SIZE):
            x = rect.left() + index * cell_width
            painter.drawLine(
                QtCore.QPointF(x, rect.top()),
                QtCore.QPointF(x, rect.bottom()),
            )
            y = rect.top() + index * cell_height
            painter.drawLine(
                QtCore.QPointF(rect.left(), y),
                QtCore.QPointF(rect.right(), y),
            )

        if self._preview_cells:
            painter.setPen(QtGui.QPen(QtGui.QColor(255, 208, 92), 1.5))
            painter.setBrush(QtGui.QColor(255, 208, 92, 235))
            for row, col in self._preview_cells:
                x = rect.left() + (col + 0.5) * cell_width
                y = rect.top() + (row + 0.5) * cell_height
                painter.drawEllipse(QtCore.QPointF(x, y), 3.5, 3.5)

            first_row, first_col = self._preview_cells[0]
            last_row, last_col = self._preview_cells[-1]
            first = QtCore.QPointF(
                rect.left() + (first_col + 0.5) * cell_width,
                rect.top() + (first_row + 0.5) * cell_height,
            )
            last = QtCore.QPointF(
                rect.left() + (last_col + 0.5) * cell_width,
                rect.top() + (last_row + 0.5) * cell_height,
            )
            painter.setFont(QtGui.QFont("Segoe UI", 10, QtGui.QFont.Weight.Bold))
            painter.setPen(QtGui.QPen(QtGui.QColor(135, 255, 162), 1))
            painter.drawText(first.toPoint() + QtCore.QPoint(8, -8), "Start")
            painter.setPen(QtGui.QPen(QtGui.QColor(255, 143, 143), 1))
            painter.drawText(last.toPoint() + QtCore.QPoint(8, -8), "End")


class GridPreviewOverlay(QtWidgets.QWidget):
    dismissed = QtCore.Signal()

    def __init__(self, region: QtCore.QRect, points: list[ClickPoint]) -> None:
        super().__init__()
        self._region = region.normalized()
        self._points = points
        self.setWindowTitle("Grid Preview")
        self.setWindowFlag(QtCore.Qt.WindowType.FramelessWindowHint, True)
        self.setWindowFlag(QtCore.Qt.WindowType.WindowStaysOnTopHint, True)
        self.setWindowFlag(QtCore.Qt.WindowType.Tool, True)
        self.setWindowModality(QtCore.Qt.WindowModality.ApplicationModal)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground, True)

        screen_rect = get_virtual_screen_geometry()
        self.setGeometry(screen_rect)

    def show_and_focus(self) -> None:
        self.showFullScreen()
        self.raise_()
        self.activateWindow()

    def keyPressEvent(self, event: QtGui.QKeyEvent) -> None:
        if event.key() == QtCore.Qt.Key.Key_Escape:
            self.close()
            self.dismissed.emit()
            return
        super().keyPressEvent(event)

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            self.close()
            self.dismissed.emit()
            return
        super().mouseReleaseEvent(event)

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(self.rect(), QtGui.QColor(5, 8, 16, 68))

        instruction = (
            "21x21 grid preview. Cyan lines show cell boundaries, gold dots show click centers. "
            "Click anywhere or press Esc to close."
        )
        painter.setPen(QtGui.QPen(QtGui.QColor(245, 247, 255), 1))
        painter.setFont(QtGui.QFont("Segoe UI", 12))
        painter.drawText(24, 36, instruction)

        local_region = global_rect_to_local(self, self._region)

        painter.setBrush(QtGui.QColor(58, 79, 123, 28))
        painter.setPen(QtGui.QPen(QtGui.QColor(122, 162, 255), 2))
        painter.drawRect(local_region)
        painter.fillRect(local_region, QtGui.QColor(122, 162, 255, 18))

        cell_width = local_region.width() / GRID_SIZE
        cell_height = local_region.height() / GRID_SIZE

        grid_pen = QtGui.QPen(QtGui.QColor(97, 232, 255, 110), 1)
        painter.setPen(grid_pen)
        for index in range(1, GRID_SIZE):
            x = local_region.left() + index * cell_width
            painter.drawLine(
                QtCore.QPointF(x, local_region.top()),
                QtCore.QPointF(x, local_region.bottom()),
            )
            y = local_region.top() + index * cell_height
            painter.drawLine(
                QtCore.QPointF(local_region.left(), y),
                QtCore.QPointF(local_region.right(), y),
            )

        painter.setPen(QtGui.QPen(QtGui.QColor(255, 208, 92), 1.5))
        painter.setBrush(QtGui.QColor(255, 208, 92, 230))
        for point in self._points:
            center = global_point_to_local(self, QtCore.QPoint(point.x, point.y))
            painter.drawEllipse(QtCore.QPointF(center), 3.5, 3.5)

        if self._points:
            first = global_point_to_local(self, QtCore.QPoint(self._points[0].x, self._points[0].y))
            last = global_point_to_local(self, QtCore.QPoint(self._points[-1].x, self._points[-1].y))
            painter.setFont(QtGui.QFont("Segoe UI", 10, QtGui.QFont.Weight.Bold))
            painter.setPen(QtGui.QPen(QtGui.QColor(135, 255, 162), 1))
            painter.drawText(first + QtCore.QPoint(8, -8), "Start")
            painter.setPen(QtGui.QPen(QtGui.QColor(255, 143, 143), 1))
            painter.drawText(last + QtCore.QPoint(8, -8), "End")


def activate_process_window(process_name: str) -> bool:
    if sys.platform != "win32":
        return True

    normalized_name = process_name.strip().casefold()
    if not normalized_name:
        return False

    user32 = ctypes.windll.user32
    matching_windows: list[int] = []
    enum_proc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    def callback(hwnd: int, lparam: int) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True
        if user32.IsIconic(hwnd):
            return True
        if user32.GetWindowTextLengthW(hwnd) <= 0:
            return True

        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value == 0:
            return True

        try:
            if psutil.Process(pid.value).name().casefold() == normalized_name:
                matching_windows.append(hwnd)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
        return True

    user32.EnumWindows(enum_proc(callback), 0)
    if not matching_windows:
        return False

    hwnd = matching_windows[0]
    user32.SetForegroundWindow(hwnd)
    user32.SetActiveWindow(hwnd)
    time.sleep(0.2)
    return True


def is_failsafe_triggered() -> bool:
    if sys.platform != "win32":
        return False

    point = ctypes.wintypes.POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(point))
    return point.x <= 0 and point.y <= 0


def move_mouse_and_click(x: int, y: int) -> None:
    if sys.platform != "win32":
        raise RuntimeError("Mouse automation is only supported on Windows")

    user32 = ctypes.windll.user32
    if not user32.SetCursorPos(int(x), int(y)):
        raise RuntimeError(f"SetCursorPos failed for ({x}, {y})")

    if is_failsafe_triggered():
        raise RuntimeError("Fail-safe triggered")

    user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)


class ResolvePlannerWorker(QtCore.QThread):
    resolved = QtCore.Signal(dict)
    failed = QtCore.Signal(str)
    status = QtCore.Signal(str)

    def __init__(self, planner_input: str) -> None:
        super().__init__()
        self._planner_input = planner_input

    def run(self) -> None:
        try:
            self.status.emit("Parsing planner URL and fetching build data...")
            sequence = build_sequence_from_planner_input(self._planner_input)
            self.resolved.emit(sequence)
        except Exception as error:
            self.failed.emit(str(error))


class ClickWorker(QtCore.QThread):
    progress = QtCore.Signal(int, int, str)
    finished_with_status = QtCore.Signal(bool, str)

    def __init__(
        self,
        points: list[ClickPoint],
        start_delay: float,
        click_interval: float,
        target_process_name: str,
    ) -> None:
        super().__init__()
        self._points = points
        self._start_delay = start_delay
        self._click_interval = click_interval
        self._target_process_name = target_process_name
        self._stop_requested = False

    def request_stop(self) -> None:
        self._stop_requested = True

    def run(self) -> None:
        try:
            if self._start_delay > 0:
                end_at = time.time() + self._start_delay
                while time.time() < end_at:
                    if self._stop_requested:
                        self.finished_with_status.emit(False, "Stopped before clicking")
                        return
                    time.sleep(0.05)

            self.progress.emit(
                0,
                len(self._points),
                f"Activating process window: {self._target_process_name}",
            )
            if not activate_process_window(self._target_process_name):
                self.finished_with_status.emit(
                    False,
                    f"Could not find a visible window for process {self._target_process_name}",
                )
                return

            for index, point in enumerate(self._points, start=1):
                if self._stop_requested:
                    self.finished_with_status.emit(False, "Stopped by user")
                    return
                if is_failsafe_triggered():
                    self.finished_with_status.emit(False, "Fail-safe triggered")
                    return
                move_mouse_and_click(point.x, point.y)
                self.progress.emit(
                    index,
                    len(self._points),
                    f"{point.local_step}. {point.node_name} -> ({point.x}, {point.y})",
                )
                if index < len(self._points) and self._click_interval > 0:
                    time.sleep(self._click_interval)

            self.finished_with_status.emit(True, "Click sequence completed")
        except Exception as error:  # pragma: no cover
            self.finished_with_status.emit(False, f"Clicking failed: {error}")


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Paragon Clicker")
        self.resize(1120, 760)

        self.sequence_data: dict[str, Any] | None = None
        self.variant_data: dict[str, Any] | None = None
        self.full_variant_data: dict[str, Any] | None = None
        self.board_sequences: list[BoardSequence] = []
        self.current_region: QtCore.QRect | None = None
        self.current_points: list[ClickPoint] = []
        self.overlay: SelectionOverlay | None = None
        self.preview_overlay: GridPreviewOverlay | None = None
        self.resolve_worker: ResolvePlannerWorker | None = None
        self.click_worker: ClickWorker | None = None
        self._region_selection_active = False
        self._grid_preview_active = False

        self._build_ui()

    def _build_ui(self) -> None:
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        root = QtWidgets.QVBoxLayout(central)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        source_group = QtWidgets.QGroupBox("D2Core Planner URL")
        source_layout = QtWidgets.QGridLayout(source_group)
        self.url_edit = QtWidgets.QLineEdit("https://www.d2core.com/d4/planner?bd=1Tok")
        self.parse_button = QtWidgets.QPushButton("Parse URL")
        self.variant_combo = QtWidgets.QComboBox()
        self.process_edit = QtWidgets.QLineEdit("Diablo IV.exe")
        self.current_points_spin = QtWidgets.QSpinBox()
        self.current_points_spin.setRange(0, 400)
        self.current_points_spin.setValue(0)
        self.apply_strategy_button = QtWidgets.QPushButton("Apply Strategy")
        source_layout.addWidget(QtWidgets.QLabel("Planner URL"), 0, 0)
        source_layout.addWidget(self.url_edit, 0, 1)
        source_layout.addWidget(self.parse_button, 0, 2)
        source_layout.addWidget(QtWidgets.QLabel("Variant"), 1, 0)
        source_layout.addWidget(self.variant_combo, 1, 1, 1, 2)
        source_layout.addWidget(QtWidgets.QLabel("Target Process"), 2, 0)
        source_layout.addWidget(self.process_edit, 2, 1, 1, 2)
        source_layout.addWidget(QtWidgets.QLabel("Current Points"), 3, 0)
        source_layout.addWidget(self.current_points_spin, 3, 1)
        source_layout.addWidget(self.apply_strategy_button, 3, 2)
        root.addWidget(source_group)

        options_group = QtWidgets.QGroupBox("Board Setup")
        options_layout = QtWidgets.QGridLayout(options_group)
        self.board_combo = QtWidgets.QComboBox()
        self.select_region_button = QtWidgets.QPushButton("Select Region")
        self.preview_button = QtWidgets.QPushButton("Preview Grid Clicks")
        self.start_button = QtWidgets.QPushButton("Start Clicking")
        self.stop_button = QtWidgets.QPushButton("Stop")
        self.stop_button.setEnabled(False)
        self.delay_spin = QtWidgets.QDoubleSpinBox()
        self.delay_spin.setRange(0.0, 30.0)
        self.delay_spin.setSingleStep(0.5)
        self.delay_spin.setValue(3.0)
        self.delay_spin.setSuffix(" s")
        self.interval_spin = QtWidgets.QDoubleSpinBox()
        self.interval_spin.setRange(0.0, 10.0)
        self.interval_spin.setSingleStep(0.05)
        self.interval_spin.setValue(0.12)
        self.interval_spin.setSuffix(" s")
        self.region_label = QtWidgets.QLabel("No region selected")
        self.region_label.setWordWrap(True)

        options_layout.addWidget(QtWidgets.QLabel("Board"), 0, 0)
        options_layout.addWidget(self.board_combo, 0, 1, 1, 3)
        options_layout.addWidget(QtWidgets.QLabel("Start Delay"), 1, 0)
        options_layout.addWidget(self.delay_spin, 1, 1)
        options_layout.addWidget(QtWidgets.QLabel("Click Interval"), 1, 2)
        options_layout.addWidget(self.interval_spin, 1, 3)
        options_layout.addWidget(self.select_region_button, 2, 0)
        options_layout.addWidget(self.preview_button, 2, 1)
        options_layout.addWidget(self.start_button, 2, 2)
        options_layout.addWidget(self.stop_button, 2, 3)
        options_layout.addWidget(self.region_label, 3, 0, 1, 4)
        root.addWidget(options_group)

        splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        root.addWidget(splitter, 1)

        left_panel = QtWidgets.QWidget()
        left_layout = QtWidgets.QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        self.info_text = QtWidgets.QPlainTextEdit()
        self.info_text.setReadOnly(True)
        left_layout.addWidget(self.info_text)
        splitter.addWidget(left_panel)

        right_panel = QtWidgets.QWidget()
        right_layout = QtWidgets.QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        self.table = QtWidgets.QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            ["Step", "Local", "Node", "Kind", "Row", "Col", "Screen XY"]
        )
        self.table.horizontalHeader().setSectionResizeMode(
            2, QtWidgets.QHeaderView.ResizeMode.Stretch
        )
        self.table.horizontalHeader().setSectionResizeMode(
            6, QtWidgets.QHeaderView.ResizeMode.Stretch
        )
        self.table.setEditTriggers(
            QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self.table.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.table.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.SingleSelection
        )
        right_layout.addWidget(self.table)
        splitter.addWidget(right_panel)
        splitter.setSizes([320, 780])

        log_group = QtWidgets.QGroupBox("Log")
        log_layout = QtWidgets.QVBoxLayout(log_group)
        self.log_text = QtWidgets.QPlainTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumBlockCount(500)
        log_layout.addWidget(self.log_text)
        root.addWidget(log_group, 1)

        self.parse_button.clicked.connect(self.on_parse_url)
        self.variant_combo.currentIndexChanged.connect(self.on_variant_changed)
        self.apply_strategy_button.clicked.connect(self.on_apply_strategy)
        self.board_combo.currentIndexChanged.connect(self.on_board_changed)
        self.select_region_button.clicked.connect(self.on_select_region)
        self.preview_button.clicked.connect(self.on_preview_grid)
        self.start_button.clicked.connect(self.on_start_clicking)
        self.stop_button.clicked.connect(self.on_stop_clicking)

    def log(self, message: str) -> None:
        self.log_text.appendPlainText(message)

    def on_parse_url(self) -> None:
        planner_input = self.url_edit.text().strip()
        if not planner_input:
            QtWidgets.QMessageBox.information(
                self, "No URL", "Enter a D2Core planner URL first."
            )
            return
        self.parse_button.setEnabled(False)
        self.log(f"Parsing planner input: {planner_input}")
        self.resolve_worker = ResolvePlannerWorker(planner_input)
        self.resolve_worker.status.connect(self.log)
        self.resolve_worker.failed.connect(self.on_parse_failed)
        self.resolve_worker.resolved.connect(self.on_parse_resolved)
        self.resolve_worker.start()

    def on_parse_failed(self, message: str) -> None:
        self.parse_button.setEnabled(True)
        self.resolve_worker = None
        self.log(f"Parse failed: {message}")
        QtWidgets.QMessageBox.critical(self, "Parse Failed", message)

    def on_parse_resolved(self, sequence_data: dict[str, Any]) -> None:
        self.parse_button.setEnabled(True)
        self.resolve_worker = None
        self.sequence_data = sequence_data

        max_points = max(
            (int(variant.get("meta", {}).get("pointCount", 0)) for variant in sequence_data.get("variants", [])),
            default=0,
        )
        self.current_points_spin.blockSignals(True)
        self.current_points_spin.setRange(0, max_points)
        self.current_points_spin.setValue(max_points)
        self.current_points_spin.blockSignals(False)

        self.variant_combo.blockSignals(True)
        self.variant_combo.clear()
        for index, variant in enumerate(sequence_data.get("variants", [])):
            label = variant.get("meta", {}).get("variantName") or f"Variant {index}"
            self.variant_combo.addItem(f"{index}: {label}", variant)
        self.variant_combo.blockSignals(False)

        self.current_region = None
        self.region_label.setText("No region selected")
        self.current_points = []
        self.table.setRowCount(0)
        self.on_variant_changed()
        title = sequence_data.get("meta", {}).get("title") or "Unknown"
        self.log(f"Planner parsed successfully: {title}")

    def current_variant(self) -> dict[str, Any] | None:
        data = self.variant_combo.currentData()
        return data if isinstance(data, dict) else None

    def on_apply_strategy(self) -> None:
        self.on_variant_changed()

    def on_variant_changed(self) -> None:
        variant = self.current_variant()
        self.full_variant_data = variant
        self.variant_data = variant
        self.board_sequences = []
        self.current_region = None
        self.region_label.setText("No region selected")
        self.current_points = []
        self.table.setRowCount(0)
        self.board_combo.blockSignals(True)
        self.board_combo.clear()
        self.board_combo.blockSignals(False)

        if variant is None:
            self.info_text.setPlainText("No variant loaded")
            return

        current_points = int(self.current_points_spin.value())
        self.variant_data = apply_progression_strategy(variant, current_points)

        if not self.variant_data.get("boardSequences"):
            meta = self.variant_data.get("meta", {})
            self.info_text.setPlainText(
                "\n".join(
                    [
                        f"Build: {self.sequence_data.get('meta', {}).get('title', '-') if self.sequence_data else '-'}",
                        f"Variant: {meta.get('variantName', '-')}",
                        f"Strategy: legendary and glyph first, then rarity",
                        f"Points: {meta.get('pointCount', 0)} / {meta.get('availablePointCount', current_points)} / {meta.get('fullPointCount', 0)}",
                        "No nodes planned for the current point count.",
                    ]
                )
            )
            return

        self.board_sequences = [
            BoardSequence(
                board_key=item["boardKey"],
                board_name=item["boardName"],
                board_index=int(item["boardIndex"]),
                board_rotate=int(item["boardRotate"]),
                entry_nodes=item.get("entryNodes", []),
                steps=item.get("steps", []),
            )
            for item in self.variant_data.get("boardSequences", [])
        ]

        self.board_combo.blockSignals(True)
        for board in self.board_sequences:
            self.board_combo.addItem(board.label, board)
        self.board_combo.blockSignals(False)
        self.on_board_changed()

    def current_board(self) -> BoardSequence | None:
        data = self.board_combo.currentData()
        return data if isinstance(data, BoardSequence) else None

    def on_board_changed(self) -> None:
        board = self.current_board()
        if board is None:
            self.info_text.setPlainText("No board selected")
            self.current_points = []
            self.table.setRowCount(0)
            return

        entry_desc = (
            ", ".join(
                f"{item.get('nodeName', item.get('nodeKey'))} ({item.get('rawCoord', {}).get('row')}, {item.get('rawCoord', {}).get('col')})"
                for item in board.entry_nodes
            )
            or "-"
        )
        meta = (self.variant_data or {}).get("meta", {})
        self.info_text.setPlainText(
            "\n".join(
                [
                    f"Build: {self.sequence_data.get('meta', {}).get('title', '-') if self.sequence_data else '-'}",
                    f"Character: {meta.get('char', '-')}",
                    f"Variant: {meta.get('variantName', '-')}",
                    f"Strategy: legendary and glyph first, then rarity",
                    f"Points: {meta.get('pointCount', 0)} / {meta.get('availablePointCount', 0)} / {meta.get('fullPointCount', meta.get('pointCount', 0))}",
                    f"Board: {board.board_name}",
                    f"Key: {board.board_key}",
                    f"Index: {board.board_index}",
                    f"Rotate: {board.board_rotate}",
                    f"Clicks: {len(board.steps)}",
                    f"Entry: {entry_desc}",
                ]
            )
        )
        self.refresh_preview()

    def on_select_region(self) -> None:
        board = self.current_board()
        if board is None:
            QtWidgets.QMessageBox.information(
                self, "No Board", "Parse a URL and select a board first."
            )
            return
        self.log(f"Selecting region for {board.board_key}")
        self._region_selection_active = True
        self.hide()
        QtCore.QTimer.singleShot(150, lambda: self._show_region_overlay(board))

    def _show_region_overlay(self, board: BoardSequence) -> None:
        preview_cells = [
            (int(step["rotatedCoord"]["row"]), int(step["rotatedCoord"]["col"]))
            for step in board.steps
        ]
        self.overlay = SelectionOverlay(preview_cells=preview_cells)
        self.overlay.selection_made.connect(self.on_region_selected)
        self.overlay.selection_cancelled.connect(self.on_region_cancelled)
        self.overlay.show_and_focus()

    def _restore_after_region_selection(self) -> None:
        self._region_selection_active = False
        self.overlay = None
        self.show()
        self.raise_()
        self.activateWindow()

    def _restore_after_grid_preview(self) -> None:
        self._grid_preview_active = False
        self.preview_overlay = None
        self.show()
        self.raise_()
        self.activateWindow()

    def on_region_selected(self, rect: QtCore.QRect) -> None:
        self.current_region = rect.normalized()
        self.region_label.setText(
            f"Region: left={self.current_region.left()} top={self.current_region.top()} right={self.current_region.right()} bottom={self.current_region.bottom()}"
        )
        self.log("Region selected")
        self._restore_after_region_selection()
        self.refresh_preview()

    def on_region_cancelled(self) -> None:
        self.log("Region selection cancelled")
        self._restore_after_region_selection()

    def build_click_points(
        self, board: BoardSequence, rect: QtCore.QRect
    ) -> list[ClickPoint]:
        left = rect.left()
        top = rect.top()
        width = rect.right() - rect.left()
        height = rect.bottom() - rect.top()
        if width <= 0 or height <= 0:
            return []

        cell_width = width / GRID_SIZE
        cell_height = height / GRID_SIZE
        points: list[ClickPoint] = []
        for step in board.steps:
            coord = step["rotatedCoord"]
            col = int(coord["col"])
            row = int(coord["row"])
            x = left + (col + 0.5) * cell_width
            y = top + (row + 0.5) * cell_height
            points.append(
                ClickPoint(
                    step=int(step["step"]),
                    local_step=int(step["localStep"]),
                    node_name=str(step["nodeName"]),
                    node_kind=str(step["nodeKind"]),
                    board_key=str(step["boardKey"]),
                    row=row,
                    col=col,
                    x=int(round(x)),
                    y=int(round(y)),
                )
            )
        return points

    def on_preview_grid(self) -> None:
        board = self.current_board()
        if board is None:
            QtWidgets.QMessageBox.information(self, "No Board", "Select a board first.")
            return
        if self.current_region is None:
            QtWidgets.QMessageBox.information(
                self, "No Region", "Select the board region first."
            )
            return

        self.refresh_preview()
        if not self.current_points:
            QtWidgets.QMessageBox.warning(
                self, "No Points", "No click points were generated."
            )
            return

        self.log(f"Showing grid preview for {board.board_key}")
        self._grid_preview_active = True
        self.hide()
        QtCore.QTimer.singleShot(150, self._show_grid_preview_overlay)

    def _show_grid_preview_overlay(self) -> None:
        if self.current_region is None or not self.current_points:
            self._restore_after_grid_preview()
            return
        self.preview_overlay = GridPreviewOverlay(self.current_region, self.current_points)
        self.preview_overlay.dismissed.connect(self.on_grid_preview_closed)
        self.preview_overlay.show_and_focus()

    def on_grid_preview_closed(self) -> None:
        self.log("Grid preview closed")
        self._restore_after_grid_preview()

    def refresh_preview(self) -> None:
        board = self.current_board()
        if board is None or self.current_region is None:
            self.current_points = []
            self.table.setRowCount(0)
            return

        self.current_points = self.build_click_points(board, self.current_region)
        self.table.setRowCount(len(self.current_points))
        for row_index, point in enumerate(self.current_points):
            cells = [
                str(point.step),
                str(point.local_step),
                point.node_name,
                point.node_kind,
                str(point.row),
                str(point.col),
                f"{point.x}, {point.y}",
            ]
            for col_index, value in enumerate(cells):
                item = QtWidgets.QTableWidgetItem(value)
                if col_index in {0, 1, 4, 5}:
                    item.setTextAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(row_index, col_index, item)
        self.table.resizeRowsToContents()

    def on_start_clicking(self) -> None:
        board = self.current_board()
        if board is None:
            QtWidgets.QMessageBox.information(self, "No Board", "Select a board first.")
            return
        if self.current_region is None:
            QtWidgets.QMessageBox.information(
                self, "No Region", "Select the board region first."
            )
            return
        self.refresh_preview()
        if not self.current_points:
            QtWidgets.QMessageBox.warning(
                self, "No Points", "No click points were generated."
            )
            return

        target_process_name = self.process_edit.text().strip()
        if not target_process_name:
            QtWidgets.QMessageBox.information(
                self, "No Process", "Enter the target process name first."
            )
            return

        self.click_worker = ClickWorker(
            self.current_points,
            float(self.delay_spin.value()),
            float(self.interval_spin.value()),
            target_process_name,
        )
        self.click_worker.progress.connect(self.on_worker_progress)
        self.click_worker.finished_with_status.connect(self.on_worker_finished)
        self.click_worker.start()
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.select_region_button.setEnabled(False)
        self.parse_button.setEnabled(False)
        self.log(
            f"Starting click sequence for {board.board_key} with {len(self.current_points)} clicks after activating {target_process_name}"
        )

    def on_stop_clicking(self) -> None:
        if self.click_worker is not None:
            self.click_worker.request_stop()
            self.log("Stop requested")

    def on_worker_progress(self, index: int, total: int, message: str) -> None:
        self.log(f"[{index}/{total}] {message}")

    def on_worker_finished(self, success: bool, message: str) -> None:
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.select_region_button.setEnabled(True)
        self.parse_button.setEnabled(True)
        self.click_worker = None
        self.log(message)
        if not success:
            QtWidgets.QMessageBox.warning(self, "Clicking Stopped", message)


def main() -> int:
    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName("Paragon Clicker")
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
