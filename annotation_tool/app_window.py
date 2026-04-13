"""Main application window: manages screen stack."""

from __future__ import annotations

from pathlib import Path

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QMainWindow, QStackedWidget, QAction

from annotation_tool.screens.setup_screen import SetupScreen
from annotation_tool.screens.annotation_screen import AnnotationScreen
from annotation_tool.data.project import ProjectState


class AppWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Thermal Annotation Tool")
        self.resize(1400, 900)

        self._stack = QStackedWidget(self)
        self.setCentralWidget(self._stack)

        self._setup_screen = SetupScreen(self)
        self._setup_screen.setup_complete.connect(self._on_setup_complete)
        self._stack.addWidget(self._setup_screen)

        self._annotation_screen: AnnotationScreen | None = None

        self._build_menu()

    def _build_menu(self):
        menu = self.menuBar()

        file_menu = menu.addMenu("File")
        act_new = QAction("New Session…", self)
        act_new.setShortcut("Ctrl+N")
        act_new.triggered.connect(self._go_setup)
        file_menu.addAction(act_new)

        self._act_save = QAction("Save", self)
        self._act_save.setShortcut("Ctrl+S")
        self._act_save.setEnabled(False)
        self._act_save.triggered.connect(self._save)
        file_menu.addAction(self._act_save)

        file_menu.addSeparator()
        act_quit = QAction("Quit", self)
        act_quit.setShortcut("Ctrl+Q")
        act_quit.triggered.connect(self.close)
        file_menu.addAction(act_quit)

        help_menu = menu.addMenu("Help")
        act_shortcuts = QAction("Keyboard Shortcuts", self)
        act_shortcuts.setShortcut("?")
        act_shortcuts.triggered.connect(self._show_shortcuts)
        help_menu.addAction(act_shortcuts)

    def _on_setup_complete(self, project: ProjectState, session_info):
        # Remove old annotation screen if present
        if self._annotation_screen:
            self._stack.removeWidget(self._annotation_screen)
            self._annotation_screen.deleteLater()

        self._annotation_screen = AnnotationScreen(project, parent=self)
        self._annotation_screen.back_to_setup.connect(self._go_setup)
        self._stack.addWidget(self._annotation_screen)
        self._stack.setCurrentWidget(self._annotation_screen)
        self._act_save.setEnabled(True)

        # Apply session/GeoJSON import if provided
        if session_info:
            self._annotation_screen.apply_session(session_info)

    def _go_setup(self):
        self._stack.setCurrentWidget(self._setup_screen)

    def _save(self):
        if self._annotation_screen:
            self._annotation_screen._session.save()

    def _show_shortcuts(self):
        from PyQt5.QtWidgets import QMessageBox
        msg = QMessageBox(self)
        msg.setWindowTitle("Keyboard Shortcuts")
        msg.setText(
            "<b>Navigation</b><br>"
            "← / A — Previous image<br>"
            "→ / D — Next image<br>"
            "<br>"
            "<b>Annotation (quick-save if panel selected)</b><br>"
            "1 — Bypass Diode<br>"
            "2 — Cell<br>"
            "3 — Dust<br>"
            "4 — Module Missing<br>"
            "5 — Module Offline<br>"
            "6 — Multi Cell<br>"
            "7 — Partial String Offline<br>"
            "8 — Physical Damage<br>"
            "9 — Shading<br>"
            "0 — String Offline<br>"
            "S — Short Circuit<br>"
            "V — Vegetation<br>"
            "<br>"
            "<b>Actions</b><br>"
            "Enter — Save annotation<br>"
            "Delete — Clear selected annotation<br>"
            "Escape — Deselect<br>"
            "Ctrl+Z — Undo<br>"
            "Ctrl+Y / Ctrl+Shift+Z — Redo<br>"
            "Ctrl+S — Force save<br>"
            "<br>"
            "<b>View</b><br>"
            "F — Fit to window<br>"
            "+ / − — Zoom in/out<br>"
            "Scroll wheel — Zoom<br>"
            "Middle-mouse drag / Alt+drag — Pan<br>"
        )
        msg.exec_()
