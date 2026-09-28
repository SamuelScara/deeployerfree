#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["PySide6>=6.5"]
# ///
"""
DeepLoyerFree — automatically copies build artifacts (war, jar, ...) to their destinations.

Each "environment" defines:
  - a source folder (e.g. .../Appalti/target)
  - a file name filter (e.g. Appalti.war or geneweb-engine-*.jar)
  - a destination folder (e.g. .../apache-tomcat/webapps)

The app polls the sources every few seconds. When a matching file is newer than
the one in the destination and has stopped changing (build finished), it is
copied atomically: first to a temporary file, then renamed, so Tomcat never
sees a half-copied file.

Run:     uv run deeployerfree.py          (installs PySide6 automatically)
or:      pip install PySide6 && python3 deeployerfree.py
Option:  --tray  start minimized to the system tray.

Works on Linux and Windows, also when packaged as an executable with PyInstaller.
"""
from __future__ import annotations

import fnmatch
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QLockFile, QObject, QPointF, QRectF, QRunnable, Qt, QThreadPool, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QFontDatabase, QIcon, QPainter, QPixmap, QPolygonF
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QSplitter,
    QStyle,
    QSystemTrayIcon,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

APP_NAME = "DeepLoyerFree"
IS_WINDOWS = sys.platform == "win32"
IS_LINUX = sys.platform.startswith("linux")
IS_FROZEN = getattr(sys, "frozen", False)  # True when running as a PyInstaller executable

if IS_WINDOWS:
    CONFIG_DIR = Path(os.environ.get("APPDATA", Path.home())) / APP_NAME
    START_MENU_LINK = (
        Path(os.environ.get("APPDATA", Path.home()))
        / "Microsoft" / "Windows" / "Start Menu" / "Programs" / f"{APP_NAME}.lnk"
    )
    RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
else:
    XDG_CONFIG = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    CONFIG_DIR = XDG_CONFIG / "deeployerfree"
    AUTOSTART_FILE = XDG_CONFIG / "autostart" / "deeployerfree.desktop"
    MENU_FILE = Path.home() / ".local" / "share" / "applications" / "deeployerfree.desktop"
CONFIG_FILE = CONFIG_DIR / "config.json"
ICON_FILE = CONFIG_DIR / "deeployerfree.png"
POLL_MS = 1500
TMP_SUFFIX = ".deeployerfree-tmp"

COLORS = {
    "ok": "#3fb950",
    "wait": "#d29922",
    "busy": "#58a6ff",
    "error": "#f85149",
    "idle": None,
}


# --------------------------------------------------------------------------- #
# Model
# --------------------------------------------------------------------------- #
@dataclass
class Environment:
    name: str
    source: str
    pattern: str
    destination: str
    exclude: str = ""
    remove_old: bool = False
    stable_seconds: int = 3
    enabled: bool = True
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])

    def exclude_list(self) -> list[str]:
        return [p.strip() for p in self.exclude.split(",") if p.strip()]

    def matches(self, filename: str) -> bool:
        # fnmatch is case-insensitive on Windows and case-sensitive on Linux, matching the filesystem
        if not fnmatch.fnmatch(filename, self.pattern):
            return False
        return not any(fnmatch.fnmatch(filename, ex) for ex in self.exclude_list())

    @property
    def source_path(self) -> Path:
        return Path(self.source).expanduser()

    @property
    def dest_path(self) -> Path:
        return Path(self.destination).expanduser()


def load_config() -> tuple[list[Environment], bool]:
    try:
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return [], True
    except (OSError, json.JSONDecodeError):
        broken = CONFIG_FILE.with_suffix(".broken.json")
        shutil.copy2(CONFIG_FILE, broken)
        return [], True
    known = Environment.__dataclass_fields__
    envs = [
        Environment(**{k: v for k, v in raw.items() if k in known})
        for raw in data.get("environments", [])
    ]
    return envs, bool(data.get("monitoring", True))


def save_config(envs: list[Environment], monitoring: bool) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"monitoring": monitoring, "environments": [asdict(e) for e in envs]}
    tmp = CONFIG_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, CONFIG_FILE)


def find_candidates(env: Environment) -> list[Path]:
    """Source files matching the filter. Raises OSError if the folder is missing."""
    files = [p for p in env.source_path.iterdir() if p.is_file() and env.matches(p.name)]
    if env.remove_old and len(files) > 1:
        files = [max(files, key=lambda p: p.stat().st_mtime)]
    return sorted(files)


def needs_deploy(src: Path, dest_dir: Path) -> bool:
    try:
        d = (dest_dir / src.name).stat()
    except FileNotFoundError:
        return True
    s = src.stat()
    return s.st_size != d.st_size or s.st_mtime - d.st_mtime > 1


def make_icon() -> QIcon:
    """Icon drawn at runtime: no external asset to ship."""
    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        pm = QPixmap(size, size)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#2f6fdd"))
        p.drawRoundedRect(QRectF(0, 0, size, size), size * 0.22, size * 0.22)
        p.setBrush(QColor("#ffffff"))
        pts = [(0.18, 0.42), (0.52, 0.42), (0.52, 0.24), (0.84, 0.5),
               (0.52, 0.76), (0.52, 0.58), (0.18, 0.58)]
        p.drawPolygon(QPolygonF([QPointF(x * size, y * size) for x, y in pts]))
        p.end()
        icon.addPixmap(pm)
    return icon


def short_path(p: str) -> str:
    home = str(Path.home())
    return "~" + p[len(home):] if p.startswith(home) else p


def human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n} B"


# --------------------------------------------------------------------------- #
# Background copy
# --------------------------------------------------------------------------- #
class TaskSignals(QObject):
    log = Signal(str)
    finished = Signal(str, bool, str)  # env_id, ok, message


class DeployTask(QRunnable):
    def __init__(self, env: Environment, files: list[Path]):
        super().__init__()
        self.env = replace(env)  # snapshot: the config may change while copying
        self.files = files
        self.signals = TaskSignals()
        self.sigs: dict[str, tuple[int, int]] = {}
        for f in files:
            try:
                st = f.stat()
                self.sigs[str(f)] = (st.st_size, st.st_mtime_ns)
            except OSError:
                pass

    def run(self) -> None:
        env, dest = self.env, self.env.dest_path
        tmp: Path | None = None
        try:
            if not dest.is_dir():
                raise FileNotFoundError(f"la cartella di destinazione non esiste: {dest}")
            names = []
            for src in self.files:
                t0 = time.monotonic()
                tmp = dest / f".{src.name}{TMP_SUFFIX}"
                shutil.copy2(src, tmp)
                os.replace(tmp, dest / src.name)
                tmp = None
                size = human_size((dest / src.name).stat().st_size)
                self.signals.log.emit(
                    f"[{env.name}] Copiato {src.name} ({size}, {time.monotonic() - t0:.1f} s)"
                )
                names.append(src.name)

            if env.remove_old and names:
                for old in dest.iterdir():
                    if old.is_file() and old.name not in names and env.matches(old.name):
                        old.unlink()
                        self.signals.log.emit(f"[{env.name}] Rimossa versione precedente {old.name}")

            self.signals.finished.emit(env.id, True, ", ".join(names))
        except Exception as exc:  # noqa: BLE001 - any error must be shown to the user
            if tmp is not None:
                tmp.unlink(missing_ok=True)
            self.signals.finished.emit(env.id, False, str(exc))


# --------------------------------------------------------------------------- #
# Environment dialog
# --------------------------------------------------------------------------- #
class EnvDialog(QDialog):
    def __init__(self, parent: QWidget, env: Environment | None = None):
        super().__init__(parent)
        self._env = env
        self.setWindowTitle("Modifica ambiente" if env else "Nuovo ambiente")
        self.setMinimumWidth(680)

        self.name = QLineEdit(env.name if env else "")
        self.name.setPlaceholderText("es. Appalti")
        self.source = QLineEdit(env.source if env else "")
        self.source.setPlaceholderText("Cartella dove la build produce il file, es. .../Appalti/target")
        self.pattern = QLineEdit(env.pattern if env else "")
        self.pattern.setPlaceholderText("Appalti.war   oppure   geneweb-engine-*.jar")
        self.exclude = QLineEdit(env.exclude if env else "")
        self.exclude.setPlaceholderText("Facoltativo, separati da virgola: *-sources.jar, *-javadoc.jar")
        self.dest = QLineEdit(env.destination if env else "")
        self.dest.setPlaceholderText("Dove copiarlo, es. .../apache-tomcat/webapps")

        self.stable = QSpinBox()
        self.stable.setRange(1, 300)
        self.stable.setSuffix(" s")
        self.stable.setValue(env.stable_seconds if env else 3)
        self.stable.setToolTip("Il file viene copiato solo dopo che è rimasto invariato per questo tempo.")

        self.remove_old = QCheckBox("Tieni solo l'ultima versione in destinazione")
        self.remove_old.setChecked(env.remove_old if env else False)
        self.remove_old.setToolTip(
            "Dopo la copia elimina dalla destinazione gli altri file che corrispondono al filtro.\n"
            "Utile quando la versione è nel nome (es. geneweb-engine-*.jar)."
        )
        self.enabled = QCheckBox("Attivo")
        self.enabled.setChecked(env.enabled if env else True)

        self.preview = QLabel()
        self.preview.setWordWrap(True)
        self.preview.setStyleSheet("color: palette(mid);")

        form = QFormLayout()
        form.addRow("Nome", self.name)
        form.addRow("Cartella sorgente", self._with_browse(self.source, "Scegli la cartella sorgente"))
        form.addRow("File da copiare", self.pattern)
        form.addRow("Escludi", self.exclude)
        form.addRow("Cartella destinazione", self._with_browse(self.dest, "Scegli la cartella di destinazione"))
        form.addRow("Attesa fine build", self.stable)
        form.addRow("", self.remove_old)
        form.addRow("", self.enabled)
        form.addRow("", self.preview)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText("Salva")
        buttons.button(QDialogButtonBox.Cancel).setText("Annulla")
        buttons.accepted.connect(self._validate)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

        for w in (self.source, self.pattern, self.exclude):
            w.textChanged.connect(self._update_preview)
        self.remove_old.toggled.connect(self._update_preview)
        self._update_preview()

    def _with_browse(self, edit: QLineEdit, title: str) -> QWidget:
        box = QWidget()
        row = QHBoxLayout(box)
        row.setContentsMargins(0, 0, 0, 0)
        btn = QPushButton("Sfoglia…")

        def pick() -> None:
            start = str(Path(edit.text()).expanduser()) if edit.text() else str(Path.home())
            chosen = QFileDialog.getExistingDirectory(self, title, start)
            if chosen:
                edit.setText(chosen)

        btn.clicked.connect(pick)
        row.addWidget(edit)
        row.addWidget(btn)
        return box

    def build(self) -> Environment:
        return Environment(
            name=self.name.text().strip(),
            source=self.source.text().strip(),
            pattern=self.pattern.text().strip(),
            destination=self.dest.text().strip(),
            exclude=self.exclude.text().strip(),
            remove_old=self.remove_old.isChecked(),
            stable_seconds=self.stable.value(),
            enabled=self.enabled.isChecked(),
            id=self._env.id if self._env else uuid.uuid4().hex[:8],
        )

    def _update_preview(self) -> None:
        env = self.build()
        if not env.source or not env.pattern:
            self.preview.setText("Indica cartella sorgente e file per vedere cosa verrà copiato.")
            return
        try:
            files = find_candidates(env)
        except OSError:
            self.preview.setText("La cartella sorgente non esiste ancora. Va bene se la crea la build.")
            return
        if files:
            self.preview.setText("Adesso verrebbe copiato: " + ", ".join(f.name for f in files))
        else:
            self.preview.setText("Nessun file corrisponde al momento. Normale se non hai ancora compilato.")

    def _validate(self) -> None:
        env = self.build()
        error = None
        if not env.name:
            error = "Dai un nome all'ambiente."
        elif not env.source or not env.destination:
            error = "Indica sia la cartella sorgente sia quella di destinazione."
        elif not env.pattern:
            error = "Indica il file da copiare, ad esempio Appalti.war."
        elif "/" in env.pattern or "\\" in env.pattern:
            error = "Nel campo «File da copiare» va solo il nome del file, non un percorso."
        elif not env.dest_path.is_dir():
            error = f"La cartella di destinazione non esiste:\n{env.dest_path}"
        elif env.source_path.resolve() == env.dest_path.resolve():
            error = "Sorgente e destinazione devono essere cartelle diverse."
        elif env.remove_old and env.pattern[0] in "*?[":
            error = (
                "Con «Tieni solo l'ultima versione» il filtro deve iniziare con un nome fisso "
                "(es. geneweb-engine-*.jar), altrimenti rischi di cancellare altri file in destinazione."
            )
        if error:
            QMessageBox.warning(self, "Controlla i dati", error)
            return
        self.accept()


# --------------------------------------------------------------------------- #
# Main window
# --------------------------------------------------------------------------- #
class MainWindow(QMainWindow):
    COLS = ["Attivo", "Nome", "File", "Sorgente", "Destinazione", "Stato", "Ultima copia"]

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1150, 620)

        self.envs, self.monitoring = load_config()
        self.prev_sig: dict[tuple[str, str], tuple[int, int]] = {}
        self.failed_sig: dict[tuple[str, str], tuple[int, int]] = {}
        self.busy: dict[str, DeployTask] = {}
        self.status: dict[str, tuple[str, str]] = {}
        self.last_copy: dict[str, str] = {}
        self.pool = QThreadPool.globalInstance()
        self._quitting = False
        self._tray_hint_shown = False

        self.app_icon = make_icon()
        self.setWindowIcon(self.app_icon)

        self._build_ui()
        self._build_tray()
        self._refresh_table()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._poll)
        self.timer.start(POLL_MS)

        self.log(f"Avviato. Configurazione in {short_path(str(CONFIG_FILE))}")
        if not self.envs:
            self.log("Nessun ambiente configurato: premi «Aggiungi» per crearne uno.")

    # ---------------- UI ----------------
    def _build_ui(self) -> None:
        st = self.style()
        tb = self.addToolBar("Azioni")
        tb.setMovable(False)
        tb.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)

        self.act_add = QAction(st.standardIcon(QStyle.SP_FileDialogNewFolder), "Aggiungi", self)
        self.act_edit = QAction(st.standardIcon(QStyle.SP_FileDialogDetailedView), "Modifica", self)
        self.act_del = QAction(st.standardIcon(QStyle.SP_TrashIcon), "Rimuovi", self)
        self.act_now = QAction(st.standardIcon(QStyle.SP_MediaPlay), "Copia adesso", self)
        self.act_monitor = QAction("Monitoraggio attivo", self)
        self.act_monitor.setCheckable(True)
        self.act_monitor.setChecked(self.monitoring)

        self.act_add.triggered.connect(self._add)
        self.act_edit.triggered.connect(self._edit)
        self.act_del.triggered.connect(self._remove)
        self.act_now.triggered.connect(self._copy_now)
        self.act_monitor.toggled.connect(self._set_monitoring)

        for a in (self.act_add, self.act_edit, self.act_del):
            tb.addAction(a)
        tb.addSeparator()
        tb.addAction(self.act_now)
        tb.addSeparator()
        tb.addAction(self.act_monitor)

        menu = self.menuBar().addMenu("Opzioni")
        self.act_autostart = QAction("Avvia all'accesso", self)
        self.act_autostart.setCheckable(True)
        self.act_autostart.setChecked(autostart_enabled())
        self.act_autostart.setEnabled(IS_WINDOWS or IS_LINUX)
        self.act_autostart.toggled.connect(self._toggle_autostart)
        act_menu = QAction("Aggiungi al menu Start" if IS_WINDOWS else "Aggiungi al menu applicazioni", self)
        act_menu.setEnabled(IS_WINDOWS or IS_LINUX)
        act_menu.triggered.connect(self._add_to_menu)
        self.act_quit = QAction("Esci", self)
        self.act_quit.setShortcut("Ctrl+Q")
        self.act_quit.triggered.connect(self._quit)
        menu.addAction(self.act_autostart)
        menu.addAction(act_menu)
        menu.addSeparator()
        menu.addAction(self.act_quit)

        self.table = QTableWidget(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels(self.COLS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.Stretch)
        hh.setSectionResizeMode(4, QHeaderView.Stretch)
        self.table.itemChanged.connect(self._on_item_changed)
        self.table.cellDoubleClicked.connect(lambda *_: self._edit())
        self.table.itemSelectionChanged.connect(self._update_actions)

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(2000)
        self.log_view.setFont(QFontDatabase.systemFont(QFontDatabase.FixedFont))

        split = QSplitter(Qt.Vertical)
        split.addWidget(self.table)
        split.addWidget(self.log_view)
        split.setSizes([360, 220])
        self.setCentralWidget(split)

    def _build_tray(self) -> None:
        self.tray: QSystemTrayIcon | None = None
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self.tray = QSystemTrayIcon(self.app_icon, self)
        self.tray.setToolTip(APP_NAME)
        menu = QMenu(self)
        act_show = QAction("Mostra finestra", self)
        act_show.triggered.connect(self._show_window)
        menu.addAction(act_show)
        menu.addAction(self.act_monitor)
        menu.addSeparator()
        menu.addAction(self.act_quit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()
        QApplication.instance().setQuitOnLastWindowClosed(False)

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.Trigger:
            if self.isVisible():
                self.hide()
            else:
                self._show_window()

    def _show_window(self) -> None:
        self.show()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event) -> None:  # noqa: N802
        if self.tray and not self._quitting:
            event.ignore()
            self.hide()
            if not self._tray_hint_shown:
                self.tray.showMessage(APP_NAME, "Continuo a lavorare qui. Per chiudere usa Esci.",
                                      QSystemTrayIcon.Information, 4000)
                self._tray_hint_shown = True
            return
        self._quit()

    def _quit(self) -> None:
        self._quitting = True
        self.timer.stop()
        if self.busy:
            self.log("Attendo la fine delle copie in corso…")
            self.pool.waitForDone(60_000)
        QApplication.instance().quit()

    # ---------------- table ----------------
    def _refresh_table(self) -> None:
        self.table.blockSignals(True)
        self.table.setRowCount(len(self.envs))
        for r, env in enumerate(self.envs):
            chk = QTableWidgetItem()
            chk.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            chk.setCheckState(Qt.Checked if env.enabled else Qt.Unchecked)
            self.table.setItem(r, 0, chk)
            cells = (
                (1, env.name, env.name),
                (2, env.pattern, f"Escludi: {env.exclude}" if env.exclude else env.pattern),
                (3, short_path(env.source), env.source),
                (4, short_path(env.destination), env.destination),
            )
            for c, text, tip in cells:
                item = QTableWidgetItem(text)
                item.setToolTip(tip)
                self.table.setItem(r, c, item)
            self.table.setItem(r, 5, QTableWidgetItem())
            self.table.setItem(r, 6, QTableWidgetItem())
        self.table.blockSignals(False)
        self._update_status_cells()
        self._update_actions()

    def _status_for(self, env: Environment) -> tuple[str, str]:
        if env.id in self.busy:
            return "Copia in corso…", "busy"
        if not env.enabled:
            return "Disattivato", "idle"
        if not self.monitoring:
            return "In pausa", "idle"
        return self.status.get(env.id, ("In ascolto", "idle"))

    def _update_status_cells(self) -> None:
        self.table.blockSignals(True)
        for r, env in enumerate(self.envs):
            text, kind = self._status_for(env)
            item = self.table.item(r, 5)
            if item is None:
                continue
            item.setText(text)
            item.setToolTip(text)
            color = COLORS[kind]
            item.setForeground(QColor(color) if color else self.palette().text())
            self.table.item(r, 6).setText(self.last_copy.get(env.id, "—"))
        self.table.blockSignals(False)
        active = sum(1 for e in self.envs if e.enabled)
        state = "attivo" if self.monitoring else "in pausa"
        self.statusBar().showMessage(f"Monitoraggio {state} · {active} ambienti attivi su {len(self.envs)}")

    def _selected_index(self) -> int | None:
        rows = self.table.selectionModel().selectedRows()
        return rows[0].row() if rows else None

    def _update_actions(self) -> None:
        has = self._selected_index() is not None
        for a in (self.act_edit, self.act_del, self.act_now):
            a.setEnabled(has)

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if item.column() != 0 or item.row() >= len(self.envs):
            return
        env = self.envs[item.row()]
        env.enabled = item.checkState() == Qt.Checked
        self._save()
        self.log(f"[{env.name}] {'Attivato' if env.enabled else 'Disattivato'}")
        self._update_status_cells()

    # ---------------- actions ----------------
    def _save(self) -> None:
        try:
            save_config(self.envs, self.monitoring)
        except OSError as exc:
            QMessageBox.critical(self, APP_NAME, f"Impossibile salvare la configurazione:\n{exc}")

    def _forget_state(self, env_id: str) -> None:
        for d in (self.prev_sig, self.failed_sig):
            for key in [k for k in d if k[0] == env_id]:
                del d[key]
        self.status.pop(env_id, None)

    def _add(self) -> None:
        dlg = EnvDialog(self)
        if dlg.exec():
            env = dlg.build()
            self.envs.append(env)
            self._save()
            self._refresh_table()
            self.table.selectRow(len(self.envs) - 1)
            self.log(f"[{env.name}] Ambiente creato")

    def _edit(self) -> None:
        idx = self._selected_index()
        if idx is None:
            return
        dlg = EnvDialog(self, self.envs[idx])
        if dlg.exec():
            self.envs[idx] = dlg.build()
            self._forget_state(self.envs[idx].id)
            self._save()
            self._refresh_table()
            self.table.selectRow(idx)
            self.log(f"[{self.envs[idx].name}] Ambiente modificato")

    def _remove(self) -> None:
        idx = self._selected_index()
        if idx is None:
            return
        env = self.envs[idx]
        answer = QMessageBox.question(
            self, "Rimuovi ambiente",
            f"Rimuovere «{env.name}»?\nI file già copiati restano dove sono.",
        )
        if answer == QMessageBox.Yes:
            self.envs.pop(idx)
            self._forget_state(env.id)
            self._save()
            self._refresh_table()
            self.log(f"[{env.name}] Ambiente rimosso")

    def _copy_now(self) -> None:
        idx = self._selected_index()
        if idx is None:
            return
        env = self.envs[idx]
        if env.id in self.busy:
            return
        try:
            files = find_candidates(env)
        except OSError:
            QMessageBox.warning(self, APP_NAME, f"La cartella sorgente non esiste:\n{env.source_path}")
            return
        if not files:
            QMessageBox.information(
                self, APP_NAME, f"Nessun file «{env.pattern}» in {short_path(env.source)}."
            )
            return
        self._start_copy(env, files)

    def _set_monitoring(self, on: bool) -> None:
        self.monitoring = on
        self._save()
        self.log("Monitoraggio attivo" if on else "Monitoraggio in pausa")
        self._update_status_cells()

    # ---------------- polling loop ----------------
    def _poll(self) -> None:
        if self.monitoring:
            now = time.time()
            for env in self.envs:
                if env.enabled and env.id not in self.busy:
                    self._check_env(env, now)
        self._update_status_cells()

    def _check_env(self, env: Environment, now: float) -> None:
        if not env.dest_path.is_dir():
            self.status[env.id] = ("Destinazione non trovata", "error")
            return
        try:
            files = find_candidates(env)
        except OSError:
            self.status[env.id] = ("Sorgente non trovata (in attesa della build)", "wait")
            return
        if not files:
            self.status[env.id] = ("Nessun file da copiare", "idle")
            return

        ready: list[Path] = []
        waiting = failed = False
        for p in files:
            try:
                st = p.stat()
                sig = (st.st_size, st.st_mtime_ns)
                if not needs_deploy(p, env.dest_path):
                    self.prev_sig.pop((env.id, str(p)), None)
                    continue
            except OSError:
                continue
            key = (env.id, str(p))
            if self.failed_sig.get(key) == sig:
                failed = True  # already failed with this exact file: retry only once it changes
                continue
            prev = self.prev_sig.get(key)
            self.prev_sig[key] = sig
            if prev == sig and now - st.st_mtime >= env.stable_seconds:
                ready.append(p)
                self.prev_sig.pop(key, None)
            else:
                waiting = True

        if ready:
            self._start_copy(env, ready)
        elif waiting:
            self.status[env.id] = ("Build in corso, attendo…", "wait")
        elif not failed:
            self.status[env.id] = ("Aggiornato", "ok")

    def _start_copy(self, env: Environment, files: list[Path]) -> None:
        task = DeployTask(env, files)
        task.signals.log.connect(self.log)
        task.signals.finished.connect(self._on_copy_finished)
        self.busy[env.id] = task
        self.log(f"[{env.name}] Copio {', '.join(f.name for f in files)} → {short_path(env.destination)}")
        self._update_status_cells()
        self.pool.start(task)

    def _on_copy_finished(self, env_id: str, ok: bool, message: str) -> None:
        task = self.busy.pop(env_id, None)
        env = next((e for e in self.envs if e.id == env_id), None)
        name = env.name if env else (task.env.name if task else env_id)
        if ok:
            self.status[env_id] = ("Aggiornato", "ok")
            self.last_copy[env_id] = datetime.now().strftime("%H:%M:%S")
            if task:
                for path in task.sigs:
                    self.failed_sig.pop((env_id, path), None)
            if self.tray and not self.isVisible():
                self.tray.showMessage(APP_NAME, f"{name}: copiato {message}", QSystemTrayIcon.Information, 3000)
        else:
            self.status[env_id] = (f"Errore: {message}", "error")
            self.log(f"[{name}] Errore: {message}")
            if task:
                for path, sig in task.sigs.items():
                    self.failed_sig[(env_id, path)] = sig
            if self.tray:
                self.tray.showMessage(APP_NAME, f"{name}: copia non riuscita", QSystemTrayIcon.Warning, 5000)
        self._update_status_cells()

    # ---------------- autostart and menu ----------------
    def _toggle_autostart(self, on: bool) -> None:
        try:
            set_autostart(on, self.app_icon)
            self.log("Avvio all'accesso attivato" if on else "Avvio all'accesso disattivato")
        except OSError as exc:
            QMessageBox.warning(self, APP_NAME, f"Operazione non riuscita:\n{exc}")

    def _add_to_menu(self) -> None:
        try:
            where = add_to_menu(self.app_icon)
            self.log(f"Collegamento creato: {short_path(str(where))}")
        except (OSError, subprocess.SubprocessError) as exc:
            QMessageBox.warning(self, APP_NAME, f"Operazione non riuscita:\n{exc}")

    # ---------------- log ----------------
    def log(self, message: str) -> None:
        self.log_view.appendPlainText(f"{datetime.now():%H:%M:%S}  {message}")


# --------------------------------------------------------------------------- #
# OS integration (Linux / Windows)
# --------------------------------------------------------------------------- #
def launch_command() -> tuple[str, list[str]]:
    """Program and arguments to relaunch this app (executable or script)."""
    if IS_FROZEN:
        return sys.executable, []
    script = str(Path(__file__).resolve())
    uv = shutil.which("uv")
    if uv and not IS_WINDOWS:
        return uv, ["run", script]
    python = Path(sys.executable)
    if IS_WINDOWS and (python.parent / "pythonw.exe").exists():
        python = python.parent / "pythonw.exe"  # no console window
    return str(python), [script]


def _quoted(program: str, args: list[str]) -> str:
    return " ".join(f'"{x}"' if " " in x or not x.startswith("-") else x for x in [program, *args])


def _write_desktop_file(path: Path, tray: bool, icon: QIcon) -> None:
    program, args = launch_command()
    if tray:
        args = [*args, "--tray"]
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    icon.pixmap(256, 256).save(str(ICON_FILE))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "[Desktop Entry]\n"
        "Type=Application\n"
        f"Name={APP_NAME}\n"
        "Comment=Copia automatica dei file di build\n"
        f"Exec={_quoted(program, args)}\n"
        f"Icon={ICON_FILE}\n"
        "Terminal=false\n"
        "Categories=Development;\n"
        "X-GNOME-Autostart-enabled=true\n",
        encoding="utf-8",
    )


def autostart_enabled() -> bool:
    if IS_WINDOWS:
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
                winreg.QueryValueEx(key, APP_NAME)
            return True
        except OSError:
            return False
    if IS_LINUX:
        return AUTOSTART_FILE.exists()
    return False


def set_autostart(on: bool, icon: QIcon) -> None:
    if IS_WINDOWS:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            if on:
                program, args = launch_command()
                winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, _quoted(program, [*args, "--tray"]))
            else:
                try:
                    winreg.DeleteValue(key, APP_NAME)
                except FileNotFoundError:
                    pass
    elif IS_LINUX:
        if on:
            _write_desktop_file(AUTOSTART_FILE, tray=True, icon=icon)
        else:
            AUTOSTART_FILE.unlink(missing_ok=True)


def add_to_menu(icon: QIcon) -> Path:
    if IS_WINDOWS:
        program, args = launch_command()
        ps = (
            "$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:LNK); "
            "$s.TargetPath = $env:TARGET; $s.Arguments = $env:ARGS; "
            "$s.WorkingDirectory = $env:WORKDIR; $s.Save()"
        )
        env = {
            **os.environ,
            "LNK": str(START_MENU_LINK),
            "TARGET": program,
            "ARGS": " ".join(f'"{a}"' for a in args),
            "WORKDIR": str(Path(program).parent),
        }
        START_MENU_LINK.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
            env=env, check=True, capture_output=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return START_MENU_LINK
    _write_desktop_file(MENU_FILE, tray=False, icon=icon)
    return MENU_FILE


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setWindowIcon(make_icon())

    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    lock = QLockFile(str(CONFIG_DIR / "deeployerfree.lock"))
    lock.setStaleLockTime(0)
    if not lock.tryLock(100):
        QMessageBox.information(None, APP_NAME, "DeepLoyerFree è già aperto. Cercalo tra le icone della barra di sistema.")
        return 1

    win = MainWindow()
    if not ("--tray" in sys.argv and win.tray):
        win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())