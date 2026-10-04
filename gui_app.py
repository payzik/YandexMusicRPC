import getpass
import logging
import logging.handlers
import multiprocessing
import os
import sys
import threading
import traceback
from collections import deque
from datetime import datetime
from html import escape
from string import Template

from PyQt6.QtCore import QPointF, Qt, QTimer, QObject, QUrl, pyqtSignal
from PyQt6.QtGui import (
    QColor, QDesktopServices, QFont, QIcon, QLinearGradient, QPainter, QPainterPath, QPen,
    QPixmap, QPolygonF,
)
from PyQt6.QtNetwork import QLocalServer, QLocalSocket
from PyQt6.QtWidgets import (
    QApplication, QButtonGroup, QCheckBox, QComboBox, QFrame, QGridLayout,
    QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMenu, QMessageBox,
    QPlainTextEdit, QProgressBar, QPushButton, QScrollArea, QStackedWidget,
    QSystemTrayIcon, QVBoxLayout, QWidget,
)

import main as core


APP_NAME = "WinYandexMusicRPC"
STARTUP_FLAG = "--run-through-startup"
INSTANCE_KEY = f"{APP_NAME}-gui-{getpass.getuser()}"

REFRESH_MS = 250          # UI refresh period (only does work when something changed)
SESSIONS_REFRESH_MS = 5000
LOG_MAX_LINES = 1000
COVER_SIZE = 160

PAGE_OVERVIEW, PAGE_SETTINGS, PAGE_SESSIONS, PAGE_LOGS = range(4)

# ---------------------------------------------------------------- palette / style

PALETTE = dict(
    bg="#0f0b1a", side="#130e22", card="#1a1330", border="#2a2048",
    field="#150f28", hover="#241a42", text="#ece8f7", muted="#8f86ad",
    accent="#8b5cf6", accent_hi="#a78bfa", accent_lo="#6d28d9",
    ok="#4ade80", warn="#fbbf24", err="#f87171",
)

STYLE = Template(r'''
    * { font-family: "Segoe UI Variable Text", "Segoe UI"; font-size: 14px; color: $text; }
    QMainWindow, #root { background: $bg; }
    QLabel { background: transparent; }
    #sidebar { background: $side; border-right: 1px solid $border; }
    #brand { font-size: 17px; font-weight: 700; }
    #muted, #brandSub { color: $muted; }
    #pageTitle { font-size: 28px; font-weight: 700; }
    #card { background: $card; border: 1px solid $border; border-radius: 14px; }
    #cardTitle { color: $muted; font-size: 11px; font-weight: 700; letter-spacing: 1px; }
    #trackTitle { font-size: 26px; font-weight: 700; }
    #trackArtist { font-size: 17px; color: #c9c1e3; }
    #statValue { font-size: 16px; font-weight: 600; }

    #pill { border-radius: 10px; padding: 5px 12px; background: $field; color: $muted; }
    #pill[kind="playing"] { background: rgba(139,92,246,0.18); color: $accent_hi; }
    #pill[kind="paused"] { background: rgba(251,191,36,0.14); color: $warn; }

    #status { font-weight: 600; color: $err; }
    #status[state="waiting"] { color: $warn; }
    #status[state="running"] { color: $ok; }

    QPushButton#nav { background: transparent; border: 0; border-left: 3px solid transparent;
                      border-radius: 0; padding: 11px 16px; text-align: left; color: $muted; font-weight: 600; }
    QPushButton#nav:hover { background: $hover; color: $text; }
    QPushButton#nav:checked { background: rgba(139,92,246,0.14); border-left: 3px solid $accent; color: $text; }

    QPushButton { background: $field; border: 1px solid $border; border-radius: 10px; padding: 9px 16px; }
    QPushButton:hover { background: $hover; border-color: $accent_lo; }
    QPushButton:disabled { color: $muted; background: $field; border-color: $border; }
    QPushButton#primary { border: 0; color: #ffffff; font-weight: 700; min-width: 150px; padding: 10px 18px;
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 $accent_lo, stop:1 $accent); }
    QPushButton#primary:hover { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 $accent, stop:1 $accent_hi); }
    QPushButton#primary[mode="stop"] { background: $field; border: 1px solid $accent_lo; color: $accent_hi; }
    QPushButton#primary[mode="stop"]:hover { background: $hover; }
    QPushButton#primary:disabled { background: $field; border: 1px solid $border; color: $muted; }
    QPushButton#support { background: transparent; border: 0; border-radius: 6px; padding: 5px 8px;
                          text-align: left; color: $muted; font-size: 12px; }
    QPushButton#support:hover { color: $accent_hi; background: $hover; }
    QPushButton#danger { color: $err; }
    QPushButton#danger:hover { border-color: $err; }

    QComboBox, QLineEdit { background: $field; border: 1px solid $border; border-radius: 9px; padding: 8px 10px; }
    QComboBox:hover, QLineEdit:focus { border-color: $accent_lo; }
    QComboBox::drop-down { border: 0; width: 28px; }
    QComboBox::down-arrow { image: url("$arrow_icon"); width: 12px; height: 12px; }
    QComboBox QAbstractItemView { background: $card; border: 1px solid $border; selection-background-color: $accent_lo; outline: 0; }
    QCheckBox { spacing: 10px; background: transparent; }
    QCheckBox::indicator { width: 18px; height: 18px; border-radius: 5px; border: 1px solid #3a2d63; background: $field; }
    QCheckBox::indicator:hover { border-color: $accent; }
    QCheckBox::indicator:checked { background: $accent; border-color: $accent; image: url("$check_icon"); }

    QProgressBar { background: $field; border: 0; border-radius: 3px; }
    QProgressBar::chunk { border-radius: 3px;
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 $accent_lo, stop:1 #c4b5fd); }

    QPlainTextEdit { background: $field; border: 1px solid $border; border-radius: 10px; padding: 8px;
                     font-family: Consolas, "Cascadia Mono", monospace; font-size: 13px; }
    QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; border: 0; }
    QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
    QScrollBar::handle:vertical { background: $border; border-radius: 4px; min-height: 30px; }
    QScrollBar::handle:vertical:hover { background: $accent_lo; }
    QScrollBar::add-line, QScrollBar::sub-line { height: 0; }
    QMenu { background: $card; border: 1px solid $border; padding: 6px; }
    QMenu::item { padding: 7px 22px; border-radius: 6px; }
    QMenu::item:selected { background: $accent_lo; }
    QMenu::separator { height: 1px; background: $border; margin: 6px 4px; }
    QToolTip { background: $card; color: $text; border: 1px solid $border; padding: 4px; }
    QMessageBox { background: $bg; }
''')

LOG_COLORS = {
    core.LogType.Error.value: PALETTE["err"],
    core.LogType.Notification.value: PALETTE["warn"],
    core.LogType.Update_Status.value: PALETTE["accent_hi"],
}


# ---------------------------------------------------------------- logging bridge

class LogBus(QObject):
    message = pyqtSignal(str, int)


log_bus = LogBus()
LOG_BUFFER = deque(maxlen=LOG_MAX_LINES)
_original_log = core.log

# The journal is also kept on disk (%LOCALAPPDATA%\WinYandexMusicRPC\app.log, ~1 MB at most),
# so the cause of a glitch can still be read after the window was closed or the app restarted.
try:
    _file_log = logging.getLogger("wym.file")
    _file_log.setLevel(logging.INFO)
    _file_log.propagate = False
    _handler = logging.handlers.RotatingFileHandler(
        os.path.join(core.config_manager.temp_dir, "app.log"),
        maxBytes=512 * 1024, backupCount=1, encoding="utf-8")
    _handler.setFormatter(logging.Formatter("%(asctime)s %(message)s", "%Y-%m-%d %H:%M:%S"))
    _file_log.addHandler(_handler)
except Exception:
    _file_log = None


def gui_log(text, type=core.LogType.Default):
    if sys.stdout is not None:  # windowed exe has no console to print to
        try:
            _original_log(text, type)
        except Exception:
            pass
    line = f"[{datetime.now().strftime('%H:%M:%S')}] {text}"
    LOG_BUFFER.append((line, type.value))
    if _file_log is not None:
        try:
            _file_log.info("[%s] %s", type.name, text)
        except Exception:
            pass
    try:
        log_bus.message.emit(line, type.value)
    except RuntimeError:
        pass


core.log = gui_log


# ---------------------------------------------------------------- small helpers

class WorkerSignals(QObject):
    finished = pyqtSignal()
    error = pyqtSignal(str)
    result = pyqtSignal(object)


class Worker:
    """Runs fn in a plain thread; results come back through Qt signals (GUI thread)."""

    def __init__(self, fn, *args, **kwargs):
        self.fn, self.args, self.kwargs = fn, args, kwargs
        self.signals = WorkerSignals()

    def run(self):
        try:
            self.signals.result.emit(self.fn(*self.args, **self.kwargs))
        except Exception as e:
            self.signals.error.emit(str(e))
        finally:
            self.signals.finished.emit()


class Card(QFrame):
    def __init__(self, title=None, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(18, 16, 18, 16)
        self.body.setSpacing(10)
        if title:
            label = QLabel(title.upper())
            label.setObjectName("cardTitle")
            self.body.addWidget(label)


class SidebarButton(QPushButton):
    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self.setObjectName("nav")
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(44)


def set_text(label, text):
    if label.text() != text:
        label.setText(text)


def set_prop(widget, name, value):
    """Set a dynamic property and re-polish only when it really changed."""
    if widget.property(name) != value:
        widget.setProperty(name, value)
        widget.style().unpolish(widget)
        widget.style().polish(widget)


def icon_file(name, size, color, points):
    """QSS cannot draw check marks / arrows, so render them to small pngs once."""
    import os
    path = os.path.join(core.config_manager.temp_dir, name)
    if not os.path.exists(path):
        pm = QPixmap(size, size)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor(color), 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        p.drawPolyline(QPolygonF([QPointF(x, y) for x, y in points]))
        p.end()
        pm.save(path)
    return path.replace("\\", "/")


def rounded_pixmap(source, size, radius, dpr):
    px = int(size * dpr)
    src = source.scaled(px, px, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
    out = QPixmap(px, px)
    out.fill(Qt.GlobalColor.transparent)
    p = QPainter(out)
    p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
    path = QPainterPath()
    path.addRoundedRect(0, 0, px, px, radius * dpr, radius * dpr)
    p.setClipPath(path)
    p.drawPixmap((px - src.width()) // 2, (px - src.height()) // 2, src)
    p.end()
    out.setDevicePixelRatio(dpr)
    return out


def placeholder_cover(size, dpr):
    px = int(size * dpr)
    pm = QPixmap(px, px)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    grad = QLinearGradient(0, 0, px, px)
    grad.setColorAt(0, QColor(PALETTE["accent_lo"]))
    grad.setColorAt(1, QColor("#2a1f4d"))
    path = QPainterPath()
    path.addRoundedRect(0, 0, px, px, 14 * dpr, 14 * dpr)
    p.fillPath(path, grad)
    p.setPen(QColor(255, 255, 255, 170))
    p.setFont(QFont("Segoe UI Symbol", int(size * 0.3 * dpr / 1.33)))
    p.drawText(pm.rect(), Qt.AlignmentFlag.AlignCenter, "♫")
    p.end()
    pm.setDevicePixelRatio(dpr)
    return pm


# ---------------------------------------------------------------- main window

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1080, 720)
        self.setMinimumSize(900, 620)

        self._presence_thread = None
        self._quitting = False
        self._tray_hint_shown = False
        self._workers = set()
        self._tray = None
        self._cover_url = None
        self._last_state_key = None
        self._instance_server = None

        self.setWindowIcon(QIcon(core.Get_IconPath()))
        self.setStyleSheet(STYLE.substitute(
            PALETTE,
            check_icon=icon_file("check.png", 18, "#ffffff", [(4.5, 9.5), (7.8, 12.8), (13.5, 5.5)]),
            arrow_icon=icon_file("arrow.png", 12, PALETTE["accent_hi"], [(2.5, 4.5), (6, 8), (9.5, 4.5)]),
        ))
        self._build_ui()
        self._build_tray()
        self._load_settings_to_ui()
        log_bus.message.connect(self._on_log)
        self._replay_logs()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._refresh_state)
        self.timer.start(REFRESH_MS)

        self.sessions_timer = QTimer(self)
        self.sessions_timer.timeout.connect(self._refresh_sessions_if_visible)
        self.sessions_timer.start(SESSIONS_REFRESH_MS)

        self._refresh_state()
        self._init_account()

    @property
    def has_tray(self):
        return self._tray is not None

    # ------------------------------------------------------------ UI construction

    def _build_ui(self):
        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        side = QFrame()
        side.setObjectName("sidebar")
        side.setFixedWidth(230)
        sl = QVBoxLayout(side)
        sl.setContentsMargins(0, 22, 0, 16)
        sl.setSpacing(4)

        head = QVBoxLayout()
        head.setContentsMargins(20, 0, 16, 0)
        brand = QLabel("♫  Yandex Music RPC")
        brand.setObjectName("brand")
        sub = QLabel("Discord Rich Presence")
        sub.setObjectName("brandSub")
        head.addWidget(brand)
        head.addWidget(sub)
        sl.addLayout(head)
        sl.addSpacing(22)

        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        for index, label in enumerate(["Обзор", "Настройки", "Сессии", "Журнал"]):
            button = SidebarButton(label)
            self.nav_group.addButton(button, index)
            sl.addWidget(button)
        self.nav_group.button(PAGE_OVERVIEW).setChecked(True)
        self.nav_group.idClicked.connect(self._show_page)
        sl.addStretch()

        foot = QVBoxLayout()
        foot.setContentsMargins(20, 0, 16, 0)
        self.status = QLabel("●  Остановлено")
        self.status.setObjectName("status")
        version = QLabel(core.CURRENT_VERSION)
        version.setObjectName("muted")
        foot.addWidget(self.status)
        foot.addWidget(version)
        foot.addSpacing(6)
        support = QPushButton("♥  Поддержать на Boosty")
        support.setObjectName("support")
        support.setCursor(Qt.CursorShape.PointingHandCursor)
        support.setToolTip(core.SUPPORT_URL)
        support.clicked.connect(self._open_support)
        foot.addWidget(support)
        sl.addLayout(foot)
        layout.addWidget(side)

        self.pages = QStackedWidget()
        layout.addWidget(self.pages, 1)
        self.pages.addWidget(self._overview_page())
        self.pages.addWidget(self._scrollable(self._settings_page()))
        self.pages.addWidget(self._sessions_page())
        self.pages.addWidget(self._logs_page())

    @staticmethod
    def _open_support():
        QDesktopServices.openUrl(QUrl(core.SUPPORT_URL))

    @staticmethod
    def _page():
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(16)
        return page, layout

    @staticmethod
    def _scrollable(page):
        """Pages taller than the window scroll instead of squeezing their cards."""
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.Shape.NoFrame)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        area.viewport().setAutoFillBackground(False)
        page.setAutoFillBackground(False)
        area.setWidget(page)
        return area

    @staticmethod
    def _title(text):
        label = QLabel(text)
        label.setObjectName("pageTitle")
        return label

    def _overview_page(self):
        page, layout = self._page()

        header = QHBoxLayout()
        header.addWidget(self._title("Обзор"))
        header.addStretch()
        self.toggle_btn = QPushButton("Запустить RPC")
        self.toggle_btn.setObjectName("primary")
        self.toggle_btn.setProperty("mode", "start")
        self.toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.toggle_btn.clicked.connect(self._toggle_presence)
        header.addWidget(self.toggle_btn)
        layout.addLayout(header)

        hero = Card()
        row = QHBoxLayout()
        row.setSpacing(20)
        self.cover = QLabel()
        self.cover.setFixedSize(COVER_SIZE, COVER_SIZE)
        self._placeholder = placeholder_cover(COVER_SIZE, self.devicePixelRatioF())
        self.cover.setPixmap(self._placeholder)
        row.addWidget(self.cover)

        meta = QVBoxLayout()
        meta.setSpacing(5)
        self.track_title = QLabel("Ничего не играет")
        self.track_title.setObjectName("trackTitle")
        self.track_artist = QLabel("Запустите RPC и откройте Яндекс Музыку")
        self.track_artist.setObjectName("trackArtist")
        self.track_album = QLabel("")
        self.track_album.setObjectName("muted")
        for label in (self.track_title, self.track_artist, self.track_album):
            label.setWordWrap(False)
            meta.addWidget(label)
        meta.addSpacing(6)
        self.playback_label = QLabel("Ожидание")
        self.playback_label.setObjectName("pill")
        meta.addWidget(self.playback_label, 0, Qt.AlignmentFlag.AlignLeft)
        meta.addStretch()
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(6)
        meta.addWidget(self.progress)
        times = QHBoxLayout()
        self.elapsed = QLabel("0:00")
        self.total = QLabel("0:00")
        self.elapsed.setObjectName("muted")
        self.total.setObjectName("muted")
        times.addWidget(self.elapsed)
        times.addStretch()
        times.addWidget(self.total)
        meta.addLayout(times)
        row.addLayout(meta, 1)
        hero.body.addLayout(row)
        layout.addWidget(hero)

        grid = QGridLayout()
        grid.setSpacing(14)
        self.stat_discord = self._stat_card(grid, 0, 0, "Discord", "Не запущен")
        self.stat_session = self._stat_card(grid, 0, 1, "Media Session", "Автоматически")
        self.stat_account = self._stat_card(grid, 1, 0, "Яндекс Музыка", "Не авторизован")
        self.stat_version = self._stat_card(grid, 1, 1, "Версия", core.CURRENT_VERSION)
        self.stat_source = self._stat_card(grid, 2, 0, "Источник", "-")
        self.stat_phone = self._stat_card(grid, 2, 1, "Режим телефона", "Выключен")
        layout.addLayout(grid)
        layout.addStretch()
        return page

    @staticmethod
    def _stat_card(grid, row, col, title, value):
        card = Card(title)
        label = QLabel(value)
        label.setObjectName("statValue")
        card.body.addWidget(label)
        grid.addWidget(card, row, col)
        return label

    def _settings_page(self):
        page, layout = self._page()
        layout.addWidget(self._title("Настройки"))

        rpc = Card("Discord RPC")
        grid = QGridLayout()
        grid.setHorizontalSpacing(20)
        grid.setVerticalSpacing(12)
        grid.setColumnStretch(1, 1)

        def combo(row, label, items):
            grid.addWidget(QLabel(label), row, 0)
            box = QComboBox()
            for text, data in items:
                box.addItem(text, data)
            box.currentIndexChanged.connect(self._save_settings)
            grid.addWidget(box, row, 1)
            return box

        self.activity = combo(0, "Тип активности", [
            ("Слушает", core.ActivityTypeConfig.LISTENING.name),
            ("Играет", core.ActivityTypeConfig.PLAYING.name)])
        self.buttons = combo(1, "Кнопки", [
            ("Web + приложение", core.ButtonConfig.BOTH.name),
            ("Только браузер", core.ButtonConfig.YANDEX_MUSIC_WEB.name),
            ("Только приложение", core.ButtonConfig.YANDEX_MUSIC_APP.name),
            ("Без кнопок", core.ButtonConfig.NEITHER.name)])
        self.language = combo(2, "Язык RPC", [
            ("Русский", core.LanguageConfig.RUSSIAN.name),
            ("English", core.LanguageConfig.ENGLISH.name)])
        self.strong = QCheckBox("Точное совпадение трека и исполнителя")
        self.strong.toggled.connect(self._save_settings)
        grid.addWidget(self.strong, 3, 0, 1, 2)
        rpc.body.addLayout(grid)
        layout.addWidget(rpc)

        phone = Card("Телефон")
        self.phone_cb = QCheckBox("Показывать, что играет на телефоне (iPhone / Android)")
        self.phone_cb.toggled.connect(self._toggle_phone_mode)
        phone.body.addWidget(self.phone_cb)
        phone_hint = QLabel("Приложение следит за состоянием плеера вашего аккаунта и, если играет телефон, "
                            "показывает это в Discord («Слушает на iPhone»). Работает, пока запущен RPC и открыт "
                            "Discord на этом ПК. Нужен вход в аккаунт Яндекса.")
        phone_hint.setObjectName("muted")
        phone_hint.setWordWrap(True)
        phone.body.addWidget(phone_hint)
        layout.addWidget(phone)

        app = Card("Приложение")
        self.autostart = QCheckBox("Запускать вместе с Windows (сразу в трее, RPC включается сам)")
        self.autostart.toggled.connect(self._toggle_autostart)
        app.body.addWidget(self.autostart)
        tray_hint = QLabel("Крестик сворачивает окно в трей — RPC продолжает работать. Полный выход: меню значка в трее.")
        tray_hint.setObjectName("muted")
        tray_hint.setWordWrap(True)
        app.body.addWidget(tray_hint)
        layout.addWidget(app)

        account = Card("Аккаунт Яндекс Музыки")
        row = QHBoxLayout()
        self.account_line = QLineEdit()
        self.account_line.setReadOnly(True)
        self.account_line.setPlaceholderText("Не авторизован")
        row.addWidget(self.account_line, 1)
        self.login_btn = QPushButton("Войти / обновить токен")
        self.login_btn.clicked.connect(self._login_token)
        row.addWidget(self.login_btn)
        self.logout_btn = QPushButton("Выйти")
        self.logout_btn.setObjectName("danger")
        self.logout_btn.clicked.connect(self._logout_token)
        row.addWidget(self.logout_btn)
        account.body.addLayout(row)
        layout.addWidget(account)
        layout.addStretch()
        return page

    def _sessions_page(self):
        page, layout = self._page()
        layout.addWidget(self._title("Media Sessions"))
        card = Card("Каким приложением управлять")
        self.session_box = QComboBox()
        self.session_box.currentIndexChanged.connect(self._set_session)
        card.body.addWidget(self.session_box)
        row = QHBoxLayout()
        refresh = QPushButton("Обновить список")
        refresh.clicked.connect(self._refresh_sessions)
        row.addWidget(refresh)
        row.addStretch()
        card.body.addLayout(row)
        layout.addWidget(card)
        hint = QLabel("В списке только сессии Яндекс Музыки. Браузеры, Telegram и другие источники игнорируются.")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addStretch()
        return page

    def _logs_page(self):
        page, layout = self._page()
        header = QHBoxLayout()
        header.addWidget(self._title("Журнал"))
        header.addStretch()
        copy = QPushButton("Копировать")
        copy.clicked.connect(lambda: QApplication.clipboard().setText(self.log_view.toPlainText()))
        header.addWidget(copy)
        clear = QPushButton("Очистить")
        clear.clicked.connect(lambda: self.log_view.clear())
        header.addWidget(clear)
        layout.addLayout(header)
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(LOG_MAX_LINES)
        layout.addWidget(self.log_view, 1)
        return page

    # ------------------------------------------------------------ tray / window

    def _build_tray(self):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self._tray = QSystemTrayIcon(self.windowIcon(), self)
        self._tray_menu = QMenu()
        self._tray_menu.addAction("Открыть окно").triggered.connect(self.bring_to_front)
        self._tray_toggle = self._tray_menu.addAction("Запустить RPC")
        self._tray_toggle.triggered.connect(self._toggle_presence)
        self._tray_menu.addSeparator()
        self._tray_menu.addAction("Выход").triggered.connect(self.quit_app)
        self._tray.setContextMenu(self._tray_menu)
        self._tray.activated.connect(self._on_tray_activated)
        self._tray.setToolTip(APP_NAME)
        self._tray.show()

    def _on_tray_activated(self, reason):
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self.bring_to_front()

    def bring_to_front(self):
        if self.isMinimized():
            self.showNormal()
        else:
            self.show()
        self.raise_()
        self.activateWindow()

    def listen_for_instances(self):
        """A second launch pings this server instead of opening a duplicate RPC."""
        QLocalServer.removeServer(INSTANCE_KEY)
        self._instance_server = QLocalServer(self)
        self._instance_server.newConnection.connect(self._on_instance_ping)
        self._instance_server.listen(INSTANCE_KEY)

    def _on_instance_ping(self):
        conn = self._instance_server.nextPendingConnection()
        if conn is not None:
            conn.disconnectFromServer()
        self.bring_to_front()

    def quit_app(self):
        self._quitting = True
        self.close()

    def closeEvent(self, event):
        if not self._quitting and self._tray is not None:
            event.ignore()
            self.hide()
            if not self._tray_hint_shown:
                self._tray_hint_shown = True
                self._tray.showMessage(APP_NAME, "Работает в трее. Полный выход — через меню значка.",
                                       QSystemTrayIcon.MessageIcon.Information, 4000)
            return
        self._shutdown()
        event.accept()
        QApplication.quit()

    def _shutdown(self):
        try:
            core.Presence.stop()
        except Exception:
            pass
        if self._tray is not None:
            self._tray.hide()

    # ------------------------------------------------------------ navigation / sessions

    def _show_page(self, index):
        self.pages.setCurrentIndex(index)
        if index == PAGE_SESSIONS:
            self._refresh_sessions()

    def _refresh_sessions_if_visible(self):
        if self.isVisible() and self.pages.currentIndex() == PAGE_SESSIONS:
            self._refresh_sessions()

    def _refresh_sessions(self):
        def task():
            return core.run_async(core.get_session_ids(only_yandex=True), timeout=8) or []
        self._run_bg(task, self._set_sessions)

    def _fill_sessions(self, ids, selected):
        box = self.session_box
        box.blockSignals(True)
        box.clear()
        box.addItem("Автоматически", "Automatic")
        for sid in ids:
            box.addItem(sid, sid)
        if selected != "Automatic" and selected not in ids:
            box.addItem(f"{selected} (недоступна)", selected)
        box.setCurrentIndex(max(0, box.findData(selected)))
        box.blockSignals(False)

    def _set_sessions(self, ids):
        self._fill_sessions(ids, core.config_manager.get_selected_session())

    def _set_session(self, _index):
        selected = self.session_box.currentData()
        if not selected:
            return
        try:
            core.config_manager.set_selected_session(selected)
            if core.Presence.running:
                core.Presence.need_restart()
        except Exception as e:
            gui_log(f"Не удалось выбрать сессию: {e}", core.LogType.Error)

    # ------------------------------------------------------------ settings

    def _load_settings_to_ui(self):
        # Programmatic changes must not fire _save_settings/_set_session: they would
        # write half-loaded widget values (defaults) back over the saved config.
        guarded = (self.activity, self.buttons, self.language, self.strong, self.autostart, self.session_box, self.phone_cb)
        for w in guarded:
            w.blockSignals(True)
        try:
            core.get_saves_settings(False)

            def select(combo, value):
                index = combo.findData(value.name)
                if index >= 0:
                    combo.setCurrentIndex(index)

            select(self.activity, core.activityType_config)
            select(self.buttons, core.button_config)
            select(self.language, core.language_config)
            self.strong.setChecked(bool(core.strong_find))
            self.phone_cb.setChecked(bool(core.phone_mode))
            self.autostart.setChecked(bool(core.auto_start_windows))
            self.account_line.setText(self._account_text())
            self._fill_sessions([], core.config_manager.get_selected_session())
        except Exception:
            gui_log(traceback.format_exc(), core.LogType.Error)
        finally:
            for w in guarded:
                w.blockSignals(False)

    def _save_settings(self, *_):
        try:
            core.config_manager.set_enum_setting('UserSettings', 'activity_type', core.ActivityTypeConfig[self.activity.currentData()])
            core.config_manager.set_enum_setting('UserSettings', 'buttons_settings', core.ButtonConfig[self.buttons.currentData()])
            core.config_manager.set_enum_setting('UserSettings', 'language', core.LanguageConfig[self.language.currentData()])
            core.config_manager.set_setting('UserSettings', 'strong_find', str(self.strong.isChecked()))
            core.get_saves_settings(False)
            if core.Presence.running:
                core.Presence.need_restart()
        except Exception as e:
            gui_log(f"Не удалось сохранить настройки: {e}", core.LogType.Error)

    def _toggle_phone_mode(self, checked):
        try:
            core.config_manager.set_setting('UserSettings', 'phone_mode', str(bool(checked)))
            core.get_saves_settings(False)  # the RPC loop picks it up by itself, no restart needed
        except Exception as e:
            gui_log(f"Режим телефона: {e}", core.LogType.Error)

    def _phone_status_text(self, state):
        if not core.YNISON_AVAILABLE:
            return "Недоступен"
        if not core.phone_mode:
            return "Выключен"
        if not core.ya_token:
            return "Нужен вход в аккаунт"
        if state == "stopped":
            return "Включён (запустите RPC)"
        return {"connected": "Следит за аккаунтом", "error": "Ошибка, см. журнал"}.get(
            core.PhoneWatcher.status, "Подключение…")

    def _toggle_autostart(self, checked):
        try:
            if bool(core.auto_start_windows) != checked:
                core.toggle_auto_start_windows()  # synchronous: the state below is up to date
            core.get_saves_settings(False)
        except Exception as e:
            gui_log(f"Автозапуск: {e}", core.LogType.Error)
        finally:
            self.autostart.blockSignals(True)
            self.autostart.setChecked(bool(core.auto_start_windows))
            self.autostart.blockSignals(False)

    # ------------------------------------------------------------ account

    def _account_text(self):
        if not core.Presence.client:
            return "Не авторизован"
        name = core.get_account_name()
        # get_account_name() returns the string "None" for an anonymous client (no token).
        return "Без токена — войдите в аккаунт" if name in ("None", "") else name

    def _init_account(self):
        # Load the saved token right at startup so the account is shown immediately,
        # not only after the RPC has been started. Network call -> worker thread.
        self._run_bg(lambda: core.Init_yaToken(False))

    def _login_token(self):
        self.login_btn.setEnabled(False)
        self.login_btn.setText("Ожидание входа…")

        def done(_=None):
            self.login_btn.setEnabled(True)
            self.login_btn.setText("Войти / обновить токен")

        self._run_bg(lambda: core.Init_yaToken(True), done, done)

    def _logout_token(self):
        box = QMessageBox(self)
        box.setWindowTitle("Выйти из аккаунта")
        box.setText("Сохранённый токен будет удалён, и для входа понадобится авторизоваться заново.")
        confirm = box.addButton("Выйти из аккаунта", QMessageBox.ButtonRole.DestructiveRole)
        box.addButton("Отмена", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is not confirm:
            return

        def task():
            core.Remove_yaToken_From_Memmory()
            core.ya_token = ''
            # Keep a running RPC alive with an anonymous client instead of a None one.
            core.Presence.client = core.Client().init() if core.Presence.running else None

        self._run_bg(task, on_error=lambda e: gui_log(f"Выход: {e}", core.LogType.Error))

    # ------------------------------------------------------------ presence control

    def _toggle_presence(self):
        if core.Presence.state != "stopped":
            core.Presence.stop()
        else:
            self.start_presence()

    def start_presence(self):
        if self._presence_thread and self._presence_thread.is_alive():
            return
        core.get_saves_settings(False)
        self._presence_thread = threading.Thread(target=self._presence_runner, name="wym-presence", daemon=True)
        self._presence_thread.start()

    def _presence_runner(self):
        try:
            core.Init_yaToken(False)
            core.Presence.start()
        except Exception:
            gui_log(traceback.format_exc(), core.LogType.Error)
        finally:
            core.Presence._finish()

    # ------------------------------------------------------------ periodic refresh

    def _refresh_state(self):
        state = core.Presence.state
        stopping = state == "stopped" and self._presence_thread is not None and self._presence_thread.is_alive()
        track = core.Presence.currentTrack
        if track and not track.get('success'):
            track = None

        self._update_tray(state, track)
        if not self.isVisible() or self.isMinimized():
            return

        # Toggle button + status line.
        if stopping:
            text, mode, enabled = "Останавливаю…", "stop", False
        elif state == "running":
            text, mode, enabled = "Остановить RPC", "stop", True
        elif state == "waiting":
            text, mode, enabled = "Отменить", "stop", True
        else:
            text, mode, enabled = "Запустить RPC", "start", True
        set_text(self.toggle_btn, text)
        set_prop(self.toggle_btn, "mode", mode)
        if self.toggle_btn.isEnabled() != enabled:
            self.toggle_btn.setEnabled(enabled)
        status_text = {"running": "●  Работает", "waiting": "●  Ожидание Discord…"}.get(state, "●  Остановлено")
        set_text(self.status, status_text)
        set_prop(self.status, "state", state)

        set_text(self.stat_discord, "Подключен" if core.Presence.rpc else ("Ожидание Discord…" if state == "waiting" else "Не запущен"))
        selected = core.config_manager.get_selected_session()
        set_text(self.stat_session, "Автоматически" if selected == "Automatic" else selected)
        account = self._account_text()
        set_text(self.stat_account, account)
        if self.account_line.text() != account:
            self.account_line.setText(account)
        self.logout_btn.setEnabled(bool(core.ya_token))
        set_text(self.stat_phone, self._phone_status_text(state))
        if track and track.get('source') == 'phone':
            set_text(self.stat_source, f"Телефон ({track.get('device') or '-'})")
        elif track:
            set_text(self.stat_source, "Этот компьютер")
        else:
            set_text(self.stat_source, "-")

        if track:
            self._show_track(track)
        else:
            self._show_idle(state)

    def _show_track(self, track):
        set_text(self.track_title, track.get('title', '—'))
        set_text(self.track_artist, track.get('artist', '—'))
        set_text(self.track_album, track.get('album', ''))
        playing = track.get('playback') == core.PlaybackStatus.Playing.name
        pill = "Сейчас играет" if playing else "На паузе"
        if track.get('source') == 'phone':
            pill += f" · {track.get('device') or 'телефон'}"
        set_text(self.playback_label, pill)
        set_prop(self.playback_label, "kind", "playing" if playing else "paused")

        # 'start-time' is the position the core keeps current: the Windows snapshot
        # advanced to "now" and folded into the current lap (repeat one), see Presence._run.
        start = track.get('start-time')
        live = float(start.total_seconds()) if start is not None else 0.0
        duration = float(track.get('durationSec', 0) or 0)
        if duration:
            live = min(live, duration)
        set_text(self.elapsed, core.format_duration(int(live * 1000)))
        set_text(self.total, track.get('formatted_duration', '0:00'))
        self.progress.setValue(int(live / duration * 1000) if duration else 0)

        url = track.get('og-image')
        if url != self._cover_url:
            self._cover_url = url
            if url:
                self._load_cover(url)
            else:
                self.cover.setPixmap(self._placeholder)

    def _show_idle(self, state):
        set_text(self.track_title, "Ничего не играет")
        set_text(self.track_artist, "Запустите RPC и откройте Яндекс Музыку" if state == "stopped"
                 else "Откройте Яндекс Музыку и включите трек")
        set_text(self.track_album, "")
        set_text(self.playback_label, "Ожидание")
        set_prop(self.playback_label, "kind", "")
        set_text(self.elapsed, "0:00")
        set_text(self.total, "0:00")
        if self.progress.value():
            self.progress.setValue(0)
        if self._cover_url is not None:
            self._cover_url = None
            self.cover.setPixmap(self._placeholder)

    def _update_tray(self, state, track):
        if self._tray is None:
            return
        key = (state, track.get('label') if track else None, track.get('source') if track else None)
        if key == self._last_state_key:
            return
        self._last_state_key = key
        self._tray_toggle.setText("Запустить RPC" if state == "stopped" else "Остановить RPC")
        tip = APP_NAME
        if track:
            tip += f"\n{track.get('artist', '')} — {track.get('title', '')}"
            if track.get('source') == 'phone':
                tip += f"\n({track.get('device') or 'телефон'})"
        elif state == "waiting":
            tip += "\nОжидание Discord…"
        self._tray.setToolTip(tip)

    # ------------------------------------------------------------ cover

    def _load_cover(self, url):
        def task():
            import requests
            r = requests.get(url, timeout=5)
            r.raise_for_status()
            return url, r.content
        self._run_bg(task, self._set_cover)

    def _set_cover(self, payload):
        url, data = payload
        if url != self._cover_url:  # the track changed while the image was downloading
            return
        pixmap = QPixmap()
        if pixmap.loadFromData(data):
            self.cover.setPixmap(rounded_pixmap(pixmap, COVER_SIZE, 14, self.devicePixelRatioF()))

    # ------------------------------------------------------------ logs / threads

    def _run_bg(self, fn, on_result=None, on_finished=None, on_error=None):
        w = Worker(fn)
        self._workers.add(w)
        if on_result:
            w.signals.result.connect(on_result)
        if on_error:
            w.signals.error.connect(on_error)
        if on_finished:
            w.signals.finished.connect(on_finished)
        w.signals.finished.connect(lambda: self._workers.discard(w))
        threading.Thread(target=w.run, daemon=True).start()

    def _on_log(self, line, kind):
        color = LOG_COLORS.get(kind)
        html = escape(line)
        self.log_view.appendHtml(f'<span style="color:{color}">{html}</span>' if color else html)

    def _replay_logs(self):
        for line, kind in list(LOG_BUFFER):
            self._on_log(line, kind)


# ---------------------------------------------------------------- entry point

def _ping_running_instance():
    """True if another copy is already running (it is asked to show its window)."""
    sock = QLocalSocket()
    sock.connectToServer(INSTANCE_KEY)
    if sock.waitForConnected(300):
        sock.disconnectFromServer()
        sock.waitForDisconnected(300)
        return True
    return False


def _selftest():
    """`WinYandexMusicRPC.exe --selftest`: check the bundled modules and exit.

    The windowed exe has no console, so the verdict goes to selftest.txt next to the settings.
    """
    import os
    lines = [f"version {core.CURRENT_VERSION}", f"ynison available: {core.YNISON_AVAILABLE}"]
    try:
        import websockets.asyncio.client  # noqa: F401  (lazily imported by the Ynison transport)
        from yandex_music.ynison import YnisonClientAsync, messages
        YnisonClientAsync("selftest", device_id=messages.generate_device_id(seed="selftest"))
        lines.append("ynison client constructed: OK")
        ok = core.YNISON_AVAILABLE
        if "--selftest-live" in sys.argv:
            # Read-only: connects with the saved token and waits for the first state frame,
            # which proves the protobuf/websocket stack works inside the frozen build.
            import time
            import keyring
            core.ya_token = keyring.get_password('WinYandexMusicRPC', 'token') or ''
            core.phone_mode = True
            core.PhoneWatcher._next_try = 0.0
            core.PhoneWatcher.maintain()
            end = time.time() + 20
            while core.PhoneWatcher.state is None and time.time() < end:
                time.sleep(0.2)
            got = core.PhoneWatcher.state is not None
            lines.append(f"live frame received: {got} (status {core.PhoneWatcher.status}, error {core.PhoneWatcher.last_error})")
            core.PhoneWatcher.stop()
            ok = ok and got
        lines.append("result: OK" if ok else "result: FAIL")
    except Exception:
        lines.append(traceback.format_exc())
        lines.append("result: FAIL")
    try:
        with open(os.path.join(core.config_manager.temp_dir, "selftest.txt"), "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    except Exception:
        return 2
    return 0 if lines[-1] == "result: OK" else 1


def main():
    if "--selftest" in sys.argv:
        return _selftest()
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setFont(QFont("Segoe UI", 10))
    # The window hides to the tray on close; quitting is explicit (MainWindow.quit_app).
    app.setQuitOnLastWindowClosed(False)

    if _ping_running_instance():
        return 0

    win = MainWindow()
    win.listen_for_instances()
    app.aboutToQuit.connect(win._shutdown)
    try:
        # Logoff/shutdown must not be blocked by a window that only hides to the tray.
        app.commitDataRequest.connect(lambda _manager: setattr(win, "_quitting", True),
                                      Qt.ConnectionType.DirectConnection)
    except Exception:
        pass

    started_by_windows = STARTUP_FLAG in sys.argv
    if started_by_windows:
        win.start_presence()
    if not (started_by_windows and win.has_tray):
        win.show()
    return app.exec()


if __name__ == '__main__':
    # Required in the frozen exe: the token login runs in a multiprocessing child,
    # which would otherwise start another copy of the GUI instead of the login window.
    multiprocessing.freeze_support()
    sys.exit(main())
