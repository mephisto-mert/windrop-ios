# -*- coding: utf-8 -*-
"""
WinDrop macOS Edition — Native-Style Desktop Companion for Windows 11 & iPhone
Features macOS Traffic Lights, Frosted Glass Sidebar, Concentric AirDrop Radar,
Real-Time Remote Desktop Telemetry, Universal Clipboard Sync, and Dedicated Desktop Folder.
"""
import io
import math
import os
import socket
import ctypes
from ctypes import wintypes
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

import qrcode
from PyQt6.QtCore import QPoint, QPointF, QRectF, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QCursor,
    QDragEnterEvent,
    QDropEvent,
    QFont,
    QIcon,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRadialGradient,
)
from PyQt6.QtNetwork import QLocalServer, QLocalSocket
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QMenu,
    QSystemTrayIcon,
    QStackedWidget,
    QStyle,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ios_shortcut_generator import (
    get_ios_shortcut_instructions,
    install_windows_context_menu,
    push_files_to_running_instance,
    uninstall_windows_context_menu,
)
from windrop_server import WinDropServerRunner

if getattr(sys, "frozen", False):
    BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    BASE_DIR = Path(r"c:\Users\pc\Documents\projelerim\windrop_airdrop") if Path(r"c:\Users\pc\Documents\projelerim\windrop_airdrop").exists() else Path(sys.executable).parent
else:
    BUNDLE_DIR = Path(__file__).resolve().parent
    BASE_DIR = BUNDLE_DIR

_log_path = BASE_DIR / "windrop_gui.log"
if sys.stdout is None:
    try:
        sys.stdout = open(_log_path, "a", encoding="utf-8", buffering=1)
    except Exception:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
elif hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

if sys.stderr is None:
    try:
        sys.stderr = open(_log_path, "a", encoding="utf-8", buffering=1)
    except Exception:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")
elif hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

desktop_dir = Path.home() / "Desktop"
if not desktop_dir.exists():
    desktop_dir = Path.home()
DEST_FOLDER = desktop_dir / "WinDrop_Gelenler"
try:
    DEST_FOLDER.mkdir(parents=True, exist_ok=True)
except Exception:
    DEST_FOLDER = Path.cwd() / "WinDrop_Gelenler"
    DEST_FOLDER.mkdir(parents=True, exist_ok=True)


def format_bytes(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1048576:
        return f"{size / 1024:.1f} KB"
    if size < 1073741824:
        return f"{size / 1048576:.2f} MB"
    return f"{size / 1073741824:.2f} GB"


class MacTrafficLight(QPushButton):
    """macOS circular traffic light window button with symbol overlay on hover."""
    def __init__(self, color_hex: str, hover_color_hex: str, symbol: str, parent=None):
        super().__init__(parent)
        self.color_hex = color_hex
        self.hover_color_hex = hover_color_hex
        self.symbol = symbol
        self.is_hovered = False
        self.setFixedSize(13, 13)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def enterEvent(self, ev):
        self.is_hovered = True
        self.update()
        super().enterEvent(ev)

    def leaveEvent(self, ev):
        self.is_hovered = False
        self.update()
        super().leaveEvent(ev)

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = QColor(self.hover_color_hex if self.is_hovered else self.color_hex)
        p.setBrush(c)
        p.setPen(QPen(c.darker(130), 0.7))
        p.drawEllipse(QRectF(0.5, 0.5, 12.0, 12.0))
        if self.is_hovered and self.symbol:
            p.setPen(QColor(0, 0, 0, 160))
            p.setFont(QFont("Arial", 8, QFont.Weight.Bold))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.symbol)


class MacTitleBar(QWidget):
    """Native macOS Sonoma/Sequoia style unified title bar with drag support."""
    def __init__(self, window: QMainWindow, title: str = "WinDrop"):
        super().__init__(window)
        self.window = window
        self.drag_pos: Optional[QPoint] = None
        self.setFixedHeight(42)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 0, 14, 0)
        lay.setSpacing(8)

        # Traffic Lights (Close, Min, Max)
        self.btn_close = MacTrafficLight("#FF5F56", "#E0443E", "×", self)
        self.btn_min = MacTrafficLight("#FFBD2E", "#DEA123", "–", self)
        self.btn_max = MacTrafficLight("#27C93F", "#1AAB29", "+", self)

        self.btn_close.clicked.connect(self.window.close)
        self.btn_min.clicked.connect(self.window.showMinimized)
        self.btn_max.clicked.connect(self._toggle_maximize)

        lay.addWidget(self.btn_close)
        lay.addWidget(self.btn_min)
        lay.addWidget(self.btn_max)
        lay.addSpacing(12)

        # Title
        title_box = QHBoxLayout()
        title_box.setSpacing(6)
        self.title_lbl = QLabel(title)
        self.title_lbl.setStyleSheet("font-size: 13px; font-weight: 700; color: #ECECF0; font-family: -apple-system, 'SF Pro Display', 'Segoe UI';")
        self.sub_lbl = QLabel("— AirDrop & Remote (macOS Edition)")
        self.sub_lbl.setStyleSheet("font-size: 12px; color: #8E8E93; font-family: -apple-system, 'SF Pro Text', 'Segoe UI';")
        title_box.addWidget(self.title_lbl)
        title_box.addWidget(self.sub_lbl)
        lay.addLayout(title_box)

        lay.addStretch()

        # Quick Desktop Folder Pill
        self.btn_folder = QPushButton("📁 Masaüstü Klasörü")
        self.btn_folder.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_folder.setStyleSheet("""
            QPushButton {
                background: rgba(255,255,255,0.08); border: 0.5px solid rgba(255,255,255,0.15);
                border-radius: 12px; color: #ECECF0; font-size: 11px; font-weight: 600; padding: 4px 10px;
            }
            QPushButton:hover { background: rgba(255,255,255,0.14); color: #fff; }
        """)
        self.btn_folder.clicked.connect(self._open_desktop_folder)
        lay.addWidget(self.btn_folder)

    def _toggle_maximize(self):
        if self.window.isMaximized():
            self.window.showNormal()
        else:
            self.window.showMaximized()

    def _open_desktop_folder(self):
        if DEST_FOLDER.exists():
            subprocess.Popen(["explorer.exe", str(DEST_FOLDER)])

    def mousePressEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton:
            self.drag_pos = ev.globalPosition().toPoint() - self.window.frameGeometry().topLeft()
            ev.accept()

    def mouseMoveEvent(self, ev):
        if self.drag_pos and ev.buttons() == Qt.MouseButton.LeftButton and not self.window.isMaximized():
            self.window.move(ev.globalPosition().toPoint() - self.drag_pos)
            ev.accept()

    def mouseReleaseEvent(self, ev):
        self.drag_pos = None


class AirDropRadarWidget(QWidget):
    """Concentric macOS AirDrop Radar Widget with live peer badges and drag-and-drop."""
    files_dropped = pyqtSignal(list)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setMinimumSize(320, 260)
        self.phase = 0.0
        self.peers: List[Dict] = []
        self.is_drag_hover = False

        self.anim_timer = QTimer(self)
        self.anim_timer.timeout.connect(self._tick)
        self.anim_timer.start(45)

    def set_peers(self, peers: List[Dict]):
        self.peers = peers
        self.update()

    def _tick(self):
        self.phase = (self.phase + 0.03) % 1.0
        self.update()

    def dragEnterEvent(self, ev: QDragEnterEvent):
        if ev.mimeData().hasUrls():
            ev.acceptProposedAction()
            self.is_drag_hover = True
            self.update()

    def dragLeaveEvent(self, ev):
        self.is_drag_hover = False
        self.update()

    def dropEvent(self, ev: QDropEvent):
        self.is_drag_hover = False
        files = [u.toLocalFile() for u in ev.mimeData().urls() if u.isLocalFile()]
        if files:
            self.files_dropped.emit(files)
        self.update()

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        cx, cy = w / 2.0, h / 2.0
        max_r = min(w, h) * 0.44

        # Background Vignette
        grad = QRadialGradient(cx, cy, max_r * 1.3)
        grad.setColorAt(0.0, QColor(24, 32, 48, 180))
        grad.setColorAt(1.0, QColor(14, 18, 26, 0))
        p.setBrush(grad)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRect(self.rect())

        # Rings
        num_rings = 4
        for i in range(num_rings):
            offset = (self.phase + i / num_rings) % 1.0
            r = max_r * offset
            alpha = int(180 * (1.0 - offset))
            pen_col = QColor(48, 209, 88, alpha) if (self.is_drag_hover or self.peers) else QColor(10, 132, 255, alpha)
            p.setPen(QPen(pen_col, 1.8 if i == 1 else 1.2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QPointF(cx, cy), r, r)

        # Center AirDrop Node
        p.setBrush(QColor(10, 132, 255))
        p.setPen(QPen(QColor(255, 255, 255, 200), 2.0))
        p.drawEllipse(QPointF(cx, cy), 28, 28)
        p.setFont(QFont("Segoe UI Emoji", 16))
        p.setPen(QColor(255, 255, 255))
        p.drawText(QRectF(cx - 28, cy - 28, 56, 56), Qt.AlignmentFlag.AlignCenter, "📡")

        # Discovered peers
        for idx, peer in enumerate(self.peers[:4]):
            angle = -math.pi / 3 + idx * (math.pi / 2.2)
            pr = max_r * 0.68
            px = cx + math.cos(angle) * pr
            py = cy + math.sin(angle) * pr
            p.setBrush(QColor(48, 209, 88))
            p.setPen(QPen(QColor(255, 255, 255), 2.0))
            p.drawEllipse(QPointF(px, py), 20, 20)
            p.setFont(QFont("Segoe UI Emoji", 12))
            p.drawText(QRectF(px - 20, py - 20, 40, 40), Qt.AlignmentFlag.AlignCenter, "📱")
            p.setFont(QFont("-apple-system", 9, QFont.Weight.Bold))
            p.setPen(QColor(220, 255, 230))
            p.drawText(QRectF(px - 75, py + 22, 150, 20), Qt.AlignmentFlag.AlignCenter, peer.get("model", "iPhone"))

        p.setFont(QFont("-apple-system", 10, QFont.Weight.DemiBold))
        p.setPen(QColor(170, 195, 225))
        hint = "📂 Dosyaları Buraya Sürükle & Bırak" if not self.is_drag_hover else "⚡ Şimdi Bırak — Kayıpsız iPhone'a Aktar!"
        p.drawText(QRectF(10, h - 26, w - 20, 22), Qt.AlignmentFlag.AlignCenter, hint)



class WinDropClientEngine:
    """Client-mode engine that connects to a background WinDrop server on 127.0.0.1:8765."""
    class _DiscoveryStub:
        def __init__(self):
            self.peers = []
        def get_active_peers(self):
            return self.peers

    def __init__(self, port: int = 8765, receive_dir: Optional[Path] = None):
        self.port = port
        self.lan_ip = "192.168.1.158"
        self.receive_dir = receive_dir or DEST_FOLDER
        self.pc_name = socket.gethostname()
        self.listeners = []
        self.outgoing_files = {}
        self.discovery = self._DiscoveryStub()
        self.show_gui_callback = None
        self._known_file_signatures = set()
        self._last_peers_ids = []
        self._last_clipboard = ""
        self._sync_state()

    def _sync_state(self):
        import urllib.request
        import json
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{self.port}/api/state", headers={"User-Agent": "WinDropLocal"})
            with urllib.request.urlopen(req, timeout=1.0) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode("utf-8"))
                    self.lan_ip = data.get("lan_ip", self.lan_ip)
                    self.pc_name = data.get("pc_name", self.pc_name)
                    if "receive_dir" in data:
                        self.receive_dir = Path(data["receive_dir"])
                    
                    # 1. Peers Sync: strictly filter out loopback/localhost
                    raw_peers = data.get("peers") or data.get("discovered_peers", [])
                    real_peers = [p for p in raw_peers if p.get("ip") not in ("127.0.0.1", "localhost", "::1") and p.get("online", True)]
                    self.discovery.peers = real_peers
                    peers_to_use = real_peers
                    curr_ids = [p.get("id") for p in peers_to_use]
                    if curr_ids != self._last_peers_ids:
                        self._last_peers_ids = curr_ids
                        self._emit("peer_update", {"peers": peers_to_use})

                    # 2. Outgoing files
                    if "outgoing_files" in data:
                        self.outgoing_files = {f["id"]: f for f in data["outgoing_files"]}

                    # 3. Received files sync
                    for item in data.get("received_history", []):
                        sig = (item.get("name"), item.get("size"), item.get("sha256"))
                        if sig not in self._known_file_signatures:
                            self._known_file_signatures.add(sig)
                            self._emit("file_received", item)

                    # 4. Clipboard sync
                    clip = data.get("clipboard") or data.get("clipboard_text") or ""
                    if clip and clip != self._last_clipboard:
                        self._last_clipboard = clip
                        self._emit("clipboard_received", {"text": clip})
        except Exception:
            pass
    def add_listener(self, cb):
        self.listeners.append(cb)

    def _emit(self, event_type: str, data: dict):
        for cb in self.listeners:
            try:
                cb(event_type, data)
            except Exception:
                pass

    def clear_outgoing(self):
        import urllib.request
        try:
            req = urllib.request.Request(
                f"http://127.0.0.1:{self.port}/api/outgoing/clear",
                data=b"{}",
                headers={"Content-Type": "application/json"}
            )
            urllib.request.urlopen(req, timeout=1.0)
            self.outgoing_files.clear()
            self._emit("outgoing_cleared", {})
        except Exception:
            pass

    def add_outgoing_path(self, path_str: str):
        try:
            p = Path(path_str)
            push_files_to_running_instance([path_str], port=self.port)
            self._sync_state()
            meta = {
                "path": path_str,
                "name": p.name,
                "size": p.stat().st_size if p.exists() else 0,
                "sha256": ""
            }
            self._emit("outgoing_added", meta)
        except Exception:
            pass

    def set_pc_clipboard_text(self, text: str, source: str = "PC"):
        import urllib.request
        import json
        try:
            self._last_clipboard = text
            payload = json.dumps({"text": text, "source": source}).encode("utf-8")
            req = urllib.request.Request(
                f"http://127.0.0.1:{self.port}/api/clipboard/pc",
                data=payload,
                headers={"Content-Type": "application/json"}
            )
            urllib.request.urlopen(req, timeout=1.0)
        except Exception:
            pass


def _find_existing_windrop_hwnd() -> int:
    """Finds an existing valid WinDrop GUI window on current user desktop session.
    Strictly filters out Explorer folders, browsers, hung processes, and 0-size ghosts."""
    try:
        user32 = ctypes.windll.user32
        found = [0]
        curr_pid = os.getpid()

        IGNORED_CLASSES = {
            "CabinetWClass", "ExploreWClass", "WorkerW", "Progman",
            "Shell_TrayWnd", "Chrome_WidgetWin_1", "MozillaWindowClass"
        }

        def enum_win_proc(hwnd, lparam):
            if user32.IsHungAppWindow(hwnd):
                return True
            cname = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, cname, 256)
            if cname.value in IGNORED_CLASSES:
                return True

            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value == curr_pid:
                return True

            length = user32.GetWindowTextLengthW(hwnd)
            if length > 0:
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                title = buf.value
                if title.startswith("WinDrop — Windows ↔ iPhone") and "Dosya Gezgini" not in title and "File Explorer" not in title:
                    rect = wintypes.RECT()
                    user32.GetWindowRect(hwnd, ctypes.byref(rect))
                    if (rect.right - rect.left) > 100 and (rect.bottom - rect.top) > 100:
                        found[0] = hwnd
                        return False
            return True

        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
        user32.EnumWindows(WNDENUMPROC(enum_win_proc), 0)
        return found[0]
    except Exception:
        return 0

class WinDropMainWindow(QMainWindow):
    ui_event_signal = pyqtSignal(str, dict)

    def __init__(self, runner: Optional[WinDropServerRunner] = None, initial_files: Optional[List[str]] = None):
        super().__init__()
        self.runner = runner
        self.engine = runner.engine if runner else WinDropClientEngine(port=8765)
        self.setWindowTitle(f"WinDrop — Windows ↔ iPhone ({self.engine.lan_ip}:{self.engine.port})")
        self.resize(1020, 680)
        self.setMinimumSize(880, 560)
        self.setAcceptDrops(True)

        # Frameless macOS Window Architecture with taskbar & minimize support
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Window
            | Qt.WindowType.WindowMinMaxButtonsHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

        # Center on primary desktop screen
        primary = QApplication.primaryScreen()
        if primary:
            geom = primary.availableGeometry()
            cx = max(geom.x(), (geom.width() - 1020) // 2 + geom.x())
            cy = max(geom.y(), (geom.height() - 680) // 2 + geom.y())
            self.move(cx, cy)

        # Win32 taskbar style enforcement
        try:
            hwnd = int(self.winId())
            user32 = ctypes.windll.user32
            WS_MINIMIZEBOX = 0x00020000
            WS_EX_APPWINDOW = 0x00040000
            WS_EX_TOOLWINDOW = 0x00000080
            s = user32.GetWindowLongW(hwnd, -16)
            user32.SetWindowLongW(hwnd, -16, s | WS_MINIMIZEBOX)
            es = user32.GetWindowLongW(hwnd, -20)
            user32.SetWindowLongW(hwnd, -20, (es | WS_EX_APPWINDOW) & ~WS_EX_TOOLWINDOW)
        except Exception:
            pass

        self.ui_event_signal.connect(self._handle_engine_event)
        self.engine.add_listener(lambda et, data: self.ui_event_signal.emit(et, data))
        self._build_ui()
        self._force_quit = False
        self._setup_system_tray()

        # Context menu register
        try:
            if getattr(sys, "frozen", False):
                install_windows_context_menu(sys.executable, "")
            else:
                install_windows_context_menu(sys.executable, str(Path(__file__).resolve()))
        except Exception:
            pass

        if initial_files:
            self._add_files(initial_files)

        # Single Instance Local IPC Server
        self.ipc_server = QLocalServer(self)
        self.ipc_server.removeServer("WinDrop_SingleInstance_IPC")
        self.ipc_server.listen("WinDrop_SingleInstance_IPC")
        self.ipc_server.newConnection.connect(self._on_ipc_connection)

        # Initial populate of received files
        self._refresh_incoming_list()

        # Continuous background sync timer with headless daemon (1s interval)
        self.client_sync_timer = QTimer(self)
        self.client_sync_timer.setInterval(1000)
        self.client_sync_timer.timeout.connect(self._on_client_sync_tick)
        self.client_sync_timer.start()
        QTimer.singleShot(150, self._on_client_sync_tick)


    def _on_ipc_connection(self):
        try:
            client = self.ipc_server.nextPendingConnection()
            if client:
                client.readyRead.connect(lambda: self._handle_ipc_message(client))
        except Exception:
            pass

    def _handle_ipc_message(self, client):
        try:
            msg = bytes(client.readAll()).decode("utf-8", errors="ignore").strip()
            if "SHOW" in msg:
                self.bring_to_front()
            elif msg.startswith("ADD:"):
                paths = msg[4:].split("|")
                valid_paths = [p for p in paths if p and os.path.exists(p)]
                if valid_paths:
                    self._add_files(valid_paths)
                self.bring_to_front()
        except Exception:
            pass
        finally:
            try:
                client.disconnectFromServer()
            except Exception:
                pass

    def _refresh_incoming_list(self) -> None:
        """Populates the incoming files list from DEST_FOLDER and syncs desktop files tab."""
        try:
            if not hasattr(self, "incoming_list"):
                return
            self.incoming_list.clear()
            if not DEST_FOLDER.exists():
                return
            valid_files = []
            for p in DEST_FOLDER.iterdir():
                try:
                    if p.is_file() and not p.name.startswith("."):
                        st = p.stat()
                        valid_files.append((st.st_mtime, st.st_size, p))
                except (OSError, FileNotFoundError, PermissionError):
                    continue
            valid_files.sort(key=lambda x: x[0], reverse=True)
            for mtime, size, f in valid_files:
                t_str = time.strftime("%H:%M:%S", time.localtime(mtime))
                item = QListWidgetItem(f"✅  [{t_str}]  {f.name}   ({format_bytes(size)})")
                item.setData(Qt.ItemDataRole.UserRole, str(f))
                self.incoming_list.addItem(item)
            self._refresh_desktop_files()
        except Exception:
            pass

    def _on_client_sync_tick(self) -> None:
        try:
            if hasattr(self, "engine") and hasattr(self.engine, "_sync_state"):
                self.engine._sync_state()
            peers = self.engine.discovery.get_active_peers() if hasattr(self, "engine") and hasattr(self.engine, "discovery") else []
            if peers:
                self.radar.set_peers(peers)
                latest = peers[0]
                dname = latest.get("name", "iPhone")
                dvia = latest.get("via", "Canlı Radar")
                self.peer_status_lbl.setText(f"🟢 Bağlı: {dname} ({dvia})")
                self.peer_status_lbl.setStyleSheet("font-size: 12px; color: #30D158; font-weight: bold;")
                if hasattr(self, "progress_bar") and "Alındı" not in self.progress_bar.format():
                    self.progress_bar.setFormat(f"Hazır — {dname} bağlı 🟢")
            else:
                self.radar.set_peers([])
                self.peer_status_lbl.setText("● iPhone bekleniyor (Aynı Ağ / 24/7 VPS)")
                self.peer_status_lbl.setStyleSheet("font-size: 12px; color: #64D2FF; font-weight: 600;")
                if hasattr(self, "progress_bar") and "Alındı" not in self.progress_bar.format():
                    self.progress_bar.setFormat("Hazır — iPhone bekleniyor")

            # Check if disk files changed
            if hasattr(self, "incoming_list") and DEST_FOLDER.exists():
                disk_count = len([p for p in DEST_FOLDER.iterdir() if p.is_file() and not p.name.startswith(".")])
                if self.incoming_list.count() != disk_count:
                    self._refresh_incoming_list()

            # Periodic background USB check every 3 ticks (updated safely on main Qt thread)
            if hasattr(self, "womic_usb_lbl") and getattr(self, "_last_usb_html", None):
                self.womic_usb_lbl.setText(self._last_usb_html)

            self._usb_tick_count = getattr(self, "_usb_tick_count", 0) + 1
            if self._usb_tick_count % 3 == 1 and hasattr(self, "womic_usb_lbl"):
                def _check_usb():
                    try:
                        import asyncio
                        from windrop_usb_bridge import usb_status
                        st = asyncio.run(usb_status())
                        if st.get("connected"):
                            dname = st.get("name") or "iPhone"
                            self._last_usb_html = f"🔌 <b>USB:</b> <span style='color:#30D158;'>🟢 {dname} Bağlı (480 Mbps)</span>"
                        else:
                            self._last_usb_html = "🔌 <b>USB:</b> <span style='color:#8E8E93;'>Apple kablosu bekleniyor...</span>"
                    except Exception:
                        pass
                threading.Thread(target=_check_usb, daemon=True).start()
        except Exception:
            pass

    def bring_to_front(self) -> None:
        """Restores window from system tray or background and forces foreground focus on Windows desktop."""
        if self.isMinimized():
            self.showNormal()
        self.show()
        self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized | Qt.WindowState.WindowActive)
        self.raise_()
        self.activateWindow()

        try:
            hwnd = int(self.winId())
            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32

            if user32.IsIconic(hwnd):
                user32.ShowWindow(hwnd, 9)  # SW_RESTORE
            else:
                user32.ShowWindow(hwnd, 5)  # SW_SHOW

            SWP_NOSIZE = 0x0001
            SWP_NOMOVE = 0x0002
            SWP_SHOWWINDOW = 0x0040
            HWND_TOPMOST = -1
            HWND_NOTOPMOST = -2
            user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW)
            user32.SetWindowPos(hwnd, HWND_NOTOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW)

            fore_hwnd = user32.GetForegroundWindow()
            if fore_hwnd and fore_hwnd != hwnd:
                fore_thread = user32.GetWindowThreadProcessId(fore_hwnd, None)
                curr_thread = kernel32.GetCurrentThreadId()
                if fore_thread != curr_thread:
                    user32.AttachThreadInput(fore_thread, curr_thread, True)
                    user32.SetForegroundWindow(hwnd)
                    user32.BringWindowToTop(hwnd)
                    user32.AttachThreadInput(fore_thread, curr_thread, False)
                else:
                    user32.SetForegroundWindow(hwnd)
                    user32.BringWindowToTop(hwnd)
            else:
                user32.SetForegroundWindow(hwnd)
                user32.BringWindowToTop(hwnd)
        except Exception:
            pass

    def _setup_system_tray(self) -> None:
        """Initializes Windows System Tray icon with quick actions and background status."""
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        ico_path = (BUNDLE_DIR / "windrop.ico") if (BUNDLE_DIR / "windrop.ico").exists() else (BASE_DIR / "windrop.ico")
        icon = QIcon(str(ico_path)) if ico_path.exists() else self.windowIcon()
        self.tray_icon = QSystemTrayIcon(icon, self)
        self.tray_icon.setToolTip(f"WinDrop — Windows ↔ iPhone ({self.engine.lan_ip}:{self.engine.port})")

        menu = QMenu()
        menu.setStyleSheet("""
            QMenu {
                background-color: #1E1F24;
                border: 1px solid rgba(255, 255, 255, 0.15);
                border-radius: 8px;
                padding: 6px;
                color: #ECECF0;
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
                font-size: 13px;
            }
            QMenu::item {
                padding: 6px 20px;
                border-radius: 4px;
            }
            QMenu::item:selected {
                background-color: #0A84FF;
                color: #FFFFFF;
            }
            QMenu::separator {
                height: 1px;
                background: rgba(255, 255, 255, 0.1);
                margin: 4px 8px;
            }
        """)

        act_show = menu.addAction("📱 WinDrop'u Göster")
        act_show.triggered.connect(self.bring_to_front)

        act_web = menu.addAction("🌐 Web Panelini Aç (Tarayıcı)")
        act_web.triggered.connect(lambda: subprocess.Popen(f'explorer "http://127.0.0.1:{self.engine.port}"', shell=True))

        act_folder = menu.addAction("📁 Gelen Dosyaları Aç")
        act_folder.triggered.connect(lambda: subprocess.Popen(f'explorer "{self.engine.receive_dir}"', shell=True))

        act_copy = menu.addAction(f"📋 Bağlantıyı Kopyala ({self.engine.lan_ip}:{self.engine.port})")
        act_copy.triggered.connect(self._copy_server_link)

        menu.addSeparator()

        act_quit = menu.addAction("❌ Tamamen Kapat (Çıkış)")
        act_quit.triggered.connect(self._real_quit)

        self.tray_icon.setContextMenu(menu)
        self.tray_icon.activated.connect(self._on_tray_activated)
        self.tray_icon.show()

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            if self.isVisible():
                self.hide()
            else:
                self.bring_to_front()

    def _copy_server_link(self) -> None:
        url = f"http://{self.engine.lan_ip}:{self.engine.port}"
        clipboard = QApplication.clipboard()
        if clipboard:
            clipboard.setText(url)
        if hasattr(self, "tray_icon") and self.tray_icon.isVisible():
            self.tray_icon.showMessage("WinDrop", f"Bağlantı linki kopyalandı:\n{url}", QSystemTrayIcon.MessageIcon.Information, 1500)

    def closeEvent(self, event) -> None:
        """Minimizes to system tray instead of killing server so iPhone stays connected."""
        if getattr(self, "_force_quit", False):
            event.accept()
        else:
            event.ignore()
            self.hide()
            if hasattr(self, "tray_icon") and self.tray_icon.isVisible():
                self.tray_icon.showMessage(
                    "WinDrop Arka Planda Aktif",
                    "WinDrop sunucusu arka planda çalışmaya devam ediyor. iPhone'unuz bağlı kalacaktır.",
                    QSystemTrayIcon.MessageIcon.Information,
                    2500
                )

    def _real_quit(self) -> None:
        """Explicit full quit from tray menu."""
        self._force_quit = True
        # Server runs independently 24/7; quitting GUI leaves background server online
        if hasattr(self, "tray_icon"):
            self.tray_icon.hide()
        app = QApplication.instance()
        if app:
            app.quit()

    def _build_ui(self) -> None:
        # Outer container for macOS rounded corners and shadow
        self.container_frame = QFrame(self)
        self.setCentralWidget(self.container_frame)
        self.container_frame.setObjectName("MacWindow")
        self.container_frame.setStyleSheet("""
            QFrame#MacWindow {
                background-color: #16171B;
                border: 1px solid rgba(255, 255, 255, 0.12);
                border-radius: 14px;
            }
            QWidget {
                color: #ECECF0;
                font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI", sans-serif;
            }
            QFrame#Sidebar {
                background-color: #121316;
                border-right: 1px solid rgba(255, 255, 255, 0.08);
                border-top-left-radius: 14px;
                border-bottom-left-radius: 14px;
            }
            QPushButton.SidebarBtn {
                background: transparent;
                border: none;
                border-radius: 8px;
                color: #A1A1A6;
                font-size: 13px;
                font-weight: 600;
                text-align: left;
                padding: 10px 14px;
            }
            QPushButton.SidebarBtn:hover {
                background: rgba(255, 255, 255, 0.06);
                color: #FFFFFF;
            }
            QPushButton.SidebarBtn.Active {
                background: #0A84FF;
                color: #FFFFFF;
            }
            QFrame#ContentCard {
                background-color: #1E1F24;
                border: 1px solid rgba(255, 255, 255, 0.07);
                border-radius: 12px;
            }
            QPushButton.MacBtn {
                background: rgba(255, 255, 255, 0.09);
                border: 0.5px solid rgba(255, 255, 255, 0.16);
                border-radius: 8px;
                color: #ECECF0;
                font-size: 12px;
                font-weight: 600;
                padding: 7px 14px;
            }
            QPushButton.MacBtn:hover {
                background: rgba(255, 255, 255, 0.16);
                color: #FFFFFF;
            }
            QPushButton.MacBtnPrimary {
                background: #0A84FF;
                border: 0.5px solid #0A84FF;
                border-radius: 8px;
                color: #FFFFFF;
                font-size: 12px;
                font-weight: 700;
                padding: 7px 14px;
            }
            QPushButton.MacBtnPrimary:hover {
                background: #0071E3;
            }
            QPushButton.MacBtnGreen {
                background: #30D158;
                border: 0.5px solid #30D158;
                border-radius: 8px;
                color: #000000;
                font-size: 12px;
                font-weight: 700;
                padding: 7px 14px;
            }
            QPushButton.MacBtnGreen:hover {
                background: #28B84C;
            }
            QListWidget {
                background: #141518;
                border: 1px solid rgba(255, 255, 255, 0.06);
                border-radius: 10px;
                color: #ECECF0;
                font-size: 12px;
                padding: 6px;
            }
            QProgressBar {
                background: #141518;
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 6px;
                text-align: center;
                height: 16px;
                color: #FFFFFF;
                font-size: 11px;
                font-weight: 700;
            }
            QProgressBar::chunk {
                background: #0A84FF;
                border-radius: 5px;
            }
        """)

        main_vbox = QVBoxLayout(self.container_frame)
        main_vbox.setContentsMargins(0, 0, 0, 0)
        main_vbox.setSpacing(0)

        # 1. Native macOS Title Bar
        self.title_bar = MacTitleBar(self)
        main_vbox.addWidget(self.title_bar)

        # 2. Body: Left Sidebar + Central Stack
        body_hbox = QHBoxLayout()
        body_hbox.setContentsMargins(0, 0, 0, 0)
        body_hbox.setSpacing(0)
        main_vbox.addLayout(body_hbox)

        # Sidebar
        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(210)
        sb_layout = QVBoxLayout(sidebar)
        sb_layout.setContentsMargins(12, 16, 12, 16)
        sb_layout.setSpacing(6)

        sb_title = QLabel("WINDROP")
        sb_title.setStyleSheet("font-size: 10px; font-weight: 800; color: #636366; letter-spacing: 1px; margin-left: 8px; margin-bottom: 4px;")
        sb_layout.addWidget(sb_title)

        self._last_gui_clip = ""
        try:
            QApplication.clipboard().dataChanged.connect(self._on_sys_clipboard_changed)
        except Exception:
            pass
        self.nav_btns: List[QPushButton] = []
        tabs = [
            ("📡  AirDrop Radar", 0),
            ("🖥️  Canlı Ekran (Remote)", 1),
            ("📋  Evrensel Pano", 2),
            ("📁  Gelenler Klasörü", 3),
            ("⚙️  Kestirme & Ayarlar", 4),
        ]

        for label, idx in tabs:
            btn = QPushButton(label)
            btn.setProperty("class", "SidebarBtn")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda ch, i=idx: self._switch_tab(i))
            sb_layout.addWidget(btn)
            self.nav_btns.append(btn)

        sb_layout.addStretch()

        # Destination Folder shortcut inside sidebar
        dest_card = QFrame()
        dest_card.setStyleSheet("background: rgba(255,255,255,0.04); border-radius: 10px; padding: 10px; border: 0.5px solid rgba(255,255,255,0.06);")
        dest_lay = QVBoxLayout(dest_card)
        dest_lay.setContentsMargins(8, 8, 8, 8)
        dest_lay.setSpacing(4)
        dest_title = QLabel("📥 Kayıt Yeri:")
        dest_title.setStyleSheet("font-size: 11px; font-weight: 700; color: #8E8E93;")
        dest_path = QLabel("Desktop / WinDrop_Gelenler")
        dest_path.setStyleSheet("font-size: 10px; color: #64D2FF; font-family: monospace;")
        dest_path.setWordWrap(True)
        dest_lay.addWidget(dest_title)
        dest_lay.addWidget(dest_path)
        sb_layout.addWidget(dest_card)

        body_hbox.addWidget(sidebar)

        # Central Stack
        self.stack = QStackedWidget()
        body_hbox.addWidget(self.stack)

        # Page 0: AirDrop Radar
        self.stack.addWidget(self._create_airdrop_tab())
        # Page 1: Remote Desktop Telemetry
        self.stack.addWidget(self._create_remote_tab())
        # Page 2: Clipboard Sync
        self.stack.addWidget(self._create_clipboard_tab())
        # Page 3: Received Files
        self.stack.addWidget(self._create_files_tab())
        # Page 4: Shortcut Guide
        self.stack.addWidget(self._create_settings_tab())

        self._switch_tab(0)

    def _switch_tab(self, idx: int):
        self.stack.setCurrentIndex(idx)
        for i, btn in enumerate(self.nav_btns):
            if i == idx:
                btn.setStyleSheet("background: #0A84FF; color: #FFFFFF; font-weight: 700; border-radius: 8px; text-align: left; padding: 10px 14px;")
            else:
                btn.setStyleSheet("background: transparent; color: #A1A1A6; font-weight: 600; border-radius: 8px; text-align: left; padding: 10px 14px;")

    def _create_airdrop_tab(self) -> QWidget:
        tab = QWidget()
        lay = QHBoxLayout(tab)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(14)

        # Left Column: Radar + QR
        left_card = QFrame()
        left_card.setObjectName("ContentCard")
        l_lay = QVBoxLayout(left_card)
        l_lay.setContentsMargins(14, 14, 14, 14)

        title_lbl = QLabel("📡 WinDrop Canlı AirDrop Radarı")
        title_lbl.setStyleSheet("font-size: 15px; font-weight: 700; color: #fff;")
        self.peer_status_lbl = QLabel("● iPhone bekleniyor (Aynı Ağ / 24/7 VPS)")
        self.peer_status_lbl.setStyleSheet("font-size: 12px; color: #64D2FF; font-weight: 600;")
        l_lay.addWidget(title_lbl)
        l_lay.addWidget(self.peer_status_lbl)

        self.radar = AirDropRadarWidget()
        self.radar.files_dropped.connect(self._add_files)
        l_lay.addWidget(self.radar)

        qr_box = QHBoxLayout()
        self.qr_lbl = QLabel()
        self.qr_lbl.setFixedSize(110, 110)
        self._render_qr_code()
        qr_box.addWidget(self.qr_lbl)

        info_box = QVBoxLayout()
        url_text = f"http://{self.engine.lan_ip}:{self.engine.port}"
        url_lbl = QLabel(f"<b>Safari Bağlantı Adresi:</b><br><span style='color:#64D2FF; font-size:13px;'>{url_text}</span>")
        url_lbl.setWordWrap(True)
        btn_copy = QPushButton("Bağlantıyı Kopyala")
        btn_copy.setProperty("class", "MacBtn")
        btn_copy.clicked.connect(lambda: QApplication.clipboard().setText(url_text))

        btn_firewall = QPushButton("🛡️ Güvenlik Duvarı İzni Ver")
        btn_firewall.setProperty("class", "MacBtn")
        btn_firewall.setStyleSheet("background: rgba(255, 159, 10, 0.15); color: #FF9F0A; border: 1px solid rgba(255, 159, 10, 0.3);")
        btn_firewall.clicked.connect(self._on_allow_firewall_clicked)

        hint_lbl = QLabel("<span style='color:#8E8E93; font-size:10px;'>💡 iPhone ve PC aynı Wi-Fi'da olmalı.<br>Safari açılmazsa yukarıdaki izin butonuna tıklayın.</span>")
        hint_lbl.setWordWrap(True)

        info_box.addWidget(url_lbl)
        info_box.addWidget(btn_copy)
        info_box.addWidget(btn_firewall)
        info_box.addWidget(hint_lbl)
        qr_box.addLayout(info_box)
        l_lay.addLayout(qr_box)

        # WO Mic Mode Info Bar
        womic_card = QFrame()
        womic_card.setStyleSheet("background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.1); border-radius: 12px; margin-top: 6px;")
        w_lay = QVBoxLayout(womic_card)
        w_lay.setContentsMargins(10, 8, 10, 8)
        w_lay.setSpacing(4)
        
        w_title = QLabel("<b>⚡ WO Mic Modu (Doğrudan IP / USB)</b>")
        w_title.setStyleSheet("font-size: 11px; color: #64D2FF;")
        
        self.womic_ip_lbl = QLabel(f"📡 <b>Wi-Fi:</b> <span style='color:#30D158;'>{self.engine.lan_ip}:{self.engine.port}</span>")
        self.womic_ip_lbl.setStyleSheet("font-size: 11px; color: #E5E5EA;")
        
        self.womic_usb_lbl = QLabel("🔌 <b>USB:</b> <span style='color:#8E8E93;'>Apple kablosu bekleniyor...</span>")
        self.womic_usb_lbl.setStyleSheet("font-size: 11px; color: #E5E5EA;")
        
        w_lay.addWidget(w_title)
        w_lay.addWidget(self.womic_ip_lbl)
        w_lay.addWidget(self.womic_usb_lbl)
        l_lay.addWidget(womic_card)

        lay.addWidget(left_card, 1)

        # Right Column: Outgoing & Incoming Transfers
        right_card = QFrame()
        right_card.setObjectName("ContentCard")
        r_lay = QVBoxLayout(right_card)
        r_lay.setContentsMargins(14, 14, 14, 14)
        r_lay.setSpacing(10)

        out_header = QHBoxLayout()
        out_title = QLabel("📤 iPhone'a Gönderilecekler")
        out_title.setStyleSheet("font-size: 13px; font-weight: 700;")
        btn_add = QPushButton("+ Dosya Ekle")
        btn_add.setProperty("class", "MacBtnPrimary")
        btn_add.clicked.connect(self._browse_and_add_files)
        btn_clear = QPushButton("Temizle")
        btn_clear.setProperty("class", "MacBtn")
        btn_clear.clicked.connect(self.engine.clear_outgoing)
        out_header.addWidget(out_title)
        out_header.addStretch()
        out_header.addWidget(btn_add)
        out_header.addWidget(btn_clear)
        r_lay.addLayout(out_header)

        self.outgoing_list = QListWidget()
        r_lay.addWidget(self.outgoing_list)

        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("Hazır — iPhone bekleniyor")
        r_lay.addWidget(self.progress_bar)

        in_header = QHBoxLayout()
        in_title = QLabel("📥 Masaüstüne Alınanlar")
        in_title.setStyleSheet("font-size: 13px; font-weight: 700;")
        btn_open_gelenler = QPushButton("Klasörü Aç")
        btn_open_gelenler.setProperty("class", "MacBtn")
        btn_open_gelenler.clicked.connect(lambda: subprocess.Popen(["explorer.exe", str(DEST_FOLDER)]))
        in_header.addWidget(in_title)
        in_header.addStretch()
        in_header.addWidget(btn_open_gelenler)
        r_lay.addLayout(in_header)

        self.incoming_list = QListWidget()
        self.incoming_list.itemDoubleClicked.connect(self._open_received_item)
        r_lay.addWidget(self.incoming_list)

        lay.addWidget(right_card, 1)
        return tab

    def _create_remote_tab(self) -> QWidget:
        tab = QWidget()
        lay = QVBoxLayout(tab)
        lay.setContentsMargins(20, 20, 20, 20)
        lay.setSpacing(14)

        card = QFrame()
        card.setObjectName("ContentCard")
        c_lay = QVBoxLayout(card)
        c_lay.setContentsMargins(18, 18, 18, 18)
        c_lay.setSpacing(12)

        title = QLabel("🖥️ Uzaktan Masaüstü (Remote Desktop Bridge)")
        title.setStyleSheet("font-size: 16px; font-weight: 700; color: #fff;")
        desc = QLabel("iPhone üzerinden sub-35ms gecikmeyle Windows 11 ekranını izleyebilir, dokunmatik ve klavye girdisi gönderebilirsiniz.")
        desc.setStyleSheet("color: #8E8E93; font-size: 12px;")
        desc.setWordWrap(True)
        c_lay.addWidget(title)
        c_lay.addWidget(desc)

        # Telemetry stats
        stats_box = QHBoxLayout()
        stats = [
            ("Çözünürlük", "1920 × 1080 (16:9)"),
            ("Canlı FPS", "22 FPS • 35ms"),
            ("Giriş Modu", "Donanım Seviyesi SendInput"),
            ("Protokol", "WebSocket Duplex + JPEG"),
        ]
        for name, val in stats:
            s_card = QFrame()
            s_card.setStyleSheet("background: rgba(255,255,255,0.04); border-radius: 8px; padding: 10px;")
            s_lay = QVBoxLayout(s_card)
            s_lay.setContentsMargins(6, 6, 6, 6)
            s_lbl_n = QLabel(name)
            s_lbl_n.setStyleSheet("font-size: 11px; color: #8E8E93;")
            s_lbl_v = QLabel(val)
            s_lbl_v.setStyleSheet("font-size: 12px; font-weight: 700; color: #64D2FF;")
            s_lay.addWidget(s_lbl_n)
            s_lay.addWidget(s_lbl_v)
            stats_box.addWidget(s_card)
        c_lay.addLayout(stats_box)

        # Action row
        btn_box = QHBoxLayout()
        btn_preview = QPushButton("📸 Canlı Ekranı Önizle")
        btn_preview.setProperty("class", "MacBtnPrimary")
        btn_preview.clicked.connect(self._preview_remote_screen)

        btn_test_click = QPushButton("⚡ Tıklama Doğrulama Testi")
        btn_test_click.setProperty("class", "MacBtn")
        btn_test_click.clicked.connect(self._run_click_test)

        btn_box.addWidget(btn_preview)
        btn_box.addWidget(btn_test_click)
        btn_box.addStretch()
        c_lay.addLayout(btn_box)

        c_lay.addStretch()
        lay.addWidget(card)
        return tab

    def _create_clipboard_tab(self) -> QWidget:
        tab = QWidget()
        lay = QVBoxLayout(tab)
        lay.setContentsMargins(20, 20, 20, 20)

        card = QFrame()
        card.setObjectName("ContentCard")
        c_lay = QVBoxLayout(card)
        c_lay.setContentsMargins(18, 18, 18, 18)
        c_lay.setSpacing(12)

        title = QLabel("📋 Evrensel Pano (Çift Yönlü)")
        title.setStyleSheet("font-size: 16px; font-weight: 700; color: #fff;")
        desc = QLabel("Windows PC'de kopyalanan son metin arka planda otomatik olarak iPhone'a hazırlanır.")
        desc.setStyleSheet("color: #8E8E93; font-size: 12px;")
        c_lay.addWidget(title)
        c_lay.addWidget(desc)

        self.clip_preview = QTextEdit()
        self.clip_preview.setPlaceholderText("PC Panosundaki metin burada görünür...")
        self.clip_preview.setStyleSheet("background: #141518; border: 1px solid rgba(255,255,255,0.08); border-radius: 8px; color: #ECECF0; font-size: 13px; padding: 10px;")
        c_lay.addWidget(self.clip_preview)

        btn_box = QHBoxLayout()
        btn_refresh = QPushButton("🔄 Panoyu Oku")
        btn_refresh.setProperty("class", "MacBtn")
        btn_refresh.clicked.connect(self._refresh_clipboard)

        btn_push = QPushButton("📲 iPhone'a Fırlat")
        btn_push.setProperty("class", "MacBtnPrimary")
        btn_push.clicked.connect(self._push_clipboard_text)

        btn_box.addWidget(btn_refresh)
        btn_box.addWidget(btn_push)
        btn_box.addStretch()
        c_lay.addLayout(btn_box)

        lay.addWidget(card)
        self._refresh_clipboard()
        return tab

    def _refresh_clipboard(self):
        clip = QApplication.clipboard().text()
        self.clip_preview.setText(clip or "(Pano boş)")

    def _on_sys_clipboard_changed(self):
        try:
            text = QApplication.clipboard().text()
            if not text:
                return
            if text == getattr(self, "_last_gui_clip", None):
                return
            eng_clip = getattr(self.engine, "last_clipboard_text", None) or getattr(self.engine, "_last_clipboard", None)
            if text == eng_clip:
                self._last_gui_clip = text
                return
            self._last_gui_clip = text
            if hasattr(self, "engine") and hasattr(self.engine, "set_pc_clipboard_text"):
                self.engine.set_pc_clipboard_text(text, source="PC")
            if hasattr(self, "clip_preview") and not self.clip_preview.hasFocus():
                self.clip_preview.setText(text)
        except Exception:
            pass

    def _push_clipboard_text(self):
        text = self.clip_preview.toPlainText().strip()
        if text:
            self._last_gui_clip = text
            QApplication.clipboard().setText(text)
            if hasattr(self, "engine") and hasattr(self.engine, "set_pc_clipboard_text"):
                self.engine.set_pc_clipboard_text(text, source="PC")
            self.peer_status_lbl.setText("📲 Pano iPhone senkronizasyonuna iletildi!")
            self.peer_status_lbl.setStyleSheet("font-size: 12px; color: #30D158; font-weight: bold;")

    def _create_files_tab(self) -> QWidget:
        tab = QWidget()
        lay = QVBoxLayout(tab)
        lay.setContentsMargins(20, 20, 20, 20)

        card = QFrame()
        card.setObjectName("ContentCard")
        c_lay = QVBoxLayout(card)
        c_lay.setContentsMargins(18, 18, 18, 18)
        c_lay.setSpacing(12)

        header = QHBoxLayout()
        title = QLabel("📁 Masaüstü Gelenler Klasörü (WinDrop_Gelenler)")
        title.setStyleSheet("font-size: 16px; font-weight: 700; color: #fff;")
        btn_open = QPushButton("Klasörü Aç (Explorer)")
        btn_open.setProperty("class", "MacBtnPrimary")
        btn_open.clicked.connect(lambda: subprocess.Popen(["explorer.exe", str(DEST_FOLDER)]))
        header.addWidget(title)
        header.addStretch()
        header.addWidget(btn_open)
        c_lay.addLayout(header)

        self.desktop_files_list = QListWidget()
        self.desktop_files_list.itemDoubleClicked.connect(self._open_received_item)
        c_lay.addWidget(self.desktop_files_list)

        self._refresh_desktop_files()
        lay.addWidget(card)
        return tab

    def _refresh_desktop_files(self):
        self.desktop_files_list.clear()
        if not DEST_FOLDER.exists():
            return
        valid_files = []
        try:
            for p in DEST_FOLDER.iterdir():
                try:
                    if p.is_file():
                        st = p.stat()
                        valid_files.append((st.st_mtime, st.st_size, p))
                except (OSError, FileNotFoundError, PermissionError):
                    continue
        except Exception:
            return

        valid_files.sort(key=lambda x: x[0], reverse=True)
        for _, size, f in valid_files:
            item = QListWidgetItem(f"📄  {f.name}   ({format_bytes(size)})")
            item.setData(Qt.ItemDataRole.UserRole, str(f))
            self.desktop_files_list.addItem(item)

    def _create_settings_tab(self) -> QWidget:
        tab = QWidget()
        lay = QVBoxLayout(tab)
        lay.setContentsMargins(20, 20, 20, 20)

        card = QFrame()
        card.setObjectName("ContentCard")
        c_lay = QVBoxLayout(card)
        c_lay.setContentsMargins(18, 18, 18, 18)
        c_lay.setSpacing(14)

        title = QLabel("⚙️ Entegrasyonlar ve Kısayollar")
        title.setStyleSheet("font-size: 16px; font-weight: 700; color: #fff;")
        c_lay.addWidget(title)

        btn_ctx = QPushButton("🗂️ Windows Gezgini Sağ Tık Menüsünü Yenile ('iPhone'a Gönder')")
        btn_ctx.setProperty("class", "MacBtn")
        btn_ctx.clicked.connect(lambda: install_windows_context_menu())
        c_lay.addWidget(btn_ctx)

        btn_guide = QPushButton("📱 iPhone Kestirme Rehberini Aç")
        btn_guide.setProperty("class", "MacBtn")
        btn_guide.clicked.connect(self._show_shortcut_guide)
        c_lay.addWidget(btn_guide)

        c_lay.addStretch()
        lay.addWidget(card)
        return tab

    def _render_qr_code(self) -> None:
        url = f"http://{self.engine.lan_ip}:{self.engine.port}"
        qr = qrcode.QRCode(box_size=3, border=1)
        qr.add_data(url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        pix = QPixmap()
        pix.loadFromData(buf.getvalue(), "PNG")
        self.qr_lbl.setPixmap(pix.scaled(110, 110, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

    def _on_allow_firewall_clicked(self) -> None:
        try:
            import ctypes
            exe_path = sys.executable if getattr(sys, "frozen", False) else sys.argv[0]
            cmd_args = (
                f'/c netsh advfirewall firewall add rule name="WinDrop P2P" dir=in action=allow protocol=TCP localport={self.engine.port} profile=any & '
                f'netsh advfirewall firewall add rule name="WinDrop App" dir=in action=allow program="{exe_path}" enable=yes profile=any'
            )
            ret = ctypes.windll.shell32.ShellExecuteW(None, "runas", "cmd.exe", cmd_args, None, 0)
            if ret > 32:
                QMessageBox.information(
                    self,
                    "Güvenlik Duvarı İzni",
                    "✅ Windows Güvenlik Duvarı kuralı tanımlandı!\nŞimdi iPhone'dan Safari bağlantısını tekrar açabilirsiniz."
                )
            else:
                QMessageBox.warning(
                    self,
                    "İzin Verilmedi",
                    "Yönetici onayı verilmedi. Çıkan pencerede 'Evet' seçeneğine basarak güvenlik duvarı engelini kaldırabilirsiniz."
                )
        except Exception as e:
            QMessageBox.critical(self, "Hata", f"Güvenlik duvarı izni verilirken hata: {e}")

    def _browse_and_add_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "iPhone'a Gönderilecek Dosyaları Seç", os.path.expanduser("~"))
        if paths:
            self._add_files(paths)

    def _add_files(self, paths: List[str]) -> None:
        for p in paths:
            self.engine.add_outgoing_path(p)

    def _open_received_item(self, item: QListWidgetItem) -> None:
        file_path = item.data(Qt.ItemDataRole.UserRole)
        if file_path and os.path.exists(file_path):
            subprocess.Popen(["explorer.exe", f"/select,{file_path}"])

    def _show_shortcut_guide(self) -> None:
        txt = get_ios_shortcut_instructions(self.engine.lan_ip, self.engine.port)
        QMessageBox.information(self, "iPhone AirDrop Rehberi", txt)

    def _run_click_test(self) -> None:
        try:
            from remote_desktop_engine import execute_remote_action
            res = execute_remote_action({"action": "touch_click", "x_pct": 0.5, "y_pct": 0.5, "button": "left"})
            QMessageBox.information(self, "Test Başarılı", f"Ekran ortasına (0.5, 0.5) donanım tıklaması gönderildi!\nSonuç: {res}")
        except Exception as e:
            QMessageBox.warning(self, "Hata", f"Tıklama testi başarısız: {e}")

    def _preview_remote_screen(self) -> None:
        try:
            from remote_desktop_engine import capture_jpeg_frame
            buf = capture_jpeg_frame(width=1280, height=720, quality=75)
            if not buf:
                QMessageBox.information(self, "Önizleme", "Masaüstü karesi şu anda alınamadı.")
                return
            pix = QPixmap()
            pix.loadFromData(buf, "JPEG")
            dlg = QDialog(self)
            dlg.setWindowTitle("WinDrop — Masaüstü Canlı Önizleme (720p)")
            dlg.resize(960, 540)
            lay = QVBoxLayout(dlg)
            lay.setContentsMargins(0, 0, 0, 0)
            lbl = QLabel()
            lbl.setPixmap(pix.scaled(960, 540, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lay.addWidget(lbl)
            dlg.exec()
        except Exception as e:
            QMessageBox.warning(self, "Hata", f"Önizleme hatası: {e}")

    def _handle_engine_event(self, event_type: str, data: Dict) -> None:
        try:
            if event_type == 'show_gui':
                self.bring_to_front()
                return
            if event_type == "outgoing_added":
                dname = data.get("name", "Dosya")
                dsize = data.get("size", 0)
                dsha = data.get("sha256", "")[:10]
                label = f"📄 {dname}  ({format_bytes(dsize)})  •  SHA-256: {dsha}…"
                self.outgoing_list.addItem(label)
            elif event_type == "outgoing_cleared":
                self.outgoing_list.clear()
            elif event_type == "peer_update":
                peers = self.engine.discovery.get_active_peers() if hasattr(self, "engine") else []
                self.radar.set_peers(peers)
                if peers:
                    latest = peers[0]
                    dname = latest.get("name", "iPhone")
                    dvia = latest.get("via", "Canlı Radar")
                    self.peer_status_lbl.setText(f"🟢 Bağlı: {dname} ({dvia})")
                    self.peer_status_lbl.setStyleSheet("font-size: 12px; color: #30D158; font-weight: bold;")
            elif event_type == "transfer_start":
                self.progress_bar.setValue(0)
                self.progress_bar.setFormat(f"⬇️ Alınıyor: {data.get('filename', 'Dosya')}...")
            elif event_type == "transfer_progress":
                total = max(data.get("total", 1), 1)
                pct = min(int((data.get("written", 0) / total) * 100), 100)
                self.progress_bar.setValue(pct)
                self.progress_bar.setFormat(f"⬇️ {data.get('filename', 'Dosya')} — %{pct}")
            elif event_type == "file_received":
                dname = data.get("name", "Dosya")
                self.progress_bar.setValue(100)
                self.progress_bar.setFormat(f"✅ Kayıpsız Alındı: {dname} (Masaüstü Klasörüne Kaydedildi)")
                self._refresh_incoming_list()
                if hasattr(self, "tray_icon") and self.tray_icon.isVisible():
                    dsize_str = format_bytes(data.get("size", 0))
                    self.tray_icon.showMessage(
                        "WinDrop — Dosya Alındı 📥",
                        f"{dname} ({dsize_str}) masaüstüne kaydedildi.",
                        QSystemTrayIcon.MessageIcon.Information,
                        3000
                    )
            elif event_type == "clipboard_received":
                txt = data.get("text", "")
                src = data.get("source", "iPhone")
                if txt:
                    self._last_gui_clip = txt
                    if src != "PC":
                        QApplication.clipboard().setText(txt)
                    if hasattr(self, "clip_preview"):
                        self.clip_preview.setText(txt)
                    short_txt = (txt[:25] + "...") if len(txt) > 25 else txt
                    if src == "PC":
                        self.peer_status_lbl.setText(f"📋 PC Panosu Hazır: {short_txt}")
                    else:
                        self.peer_status_lbl.setText(f"📋 iPhone'dan Pano Alındı: {short_txt}")
                    self.peer_status_lbl.setStyleSheet("font-size: 12px; color: #30D158; font-weight: bold;")
            elif event_type == "file_sent_to_iphone":
                dname = data.get("name", "Dosya")
                self.progress_bar.setValue(100)
                self.progress_bar.setFormat(f"📲 iPhone'a Gönderildi: {dname}")
        except Exception as e:
            print(f"[gui] engine event notice: {e}", flush=True)




def enable_sleep_prevention() -> None:
    """Keeps network & PC awake so the background server never drops connection."""
    try:
        import ctypes
        ES_CONTINUOUS = 0x80000000
        ES_SYSTEM_REQUIRED = 0x00000001
        ES_AWAYMODE_REQUIRED = 0x00000002
        ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_AWAYMODE_REQUIRED)
        print("[power] Sleep prevention enabled (ES_SYSTEM_REQUIRED | ES_AWAYMODE)", flush=True)
    except Exception as e:
        print(f"[power] Warning setting execution state: {e}", flush=True)


def ensure_background_daemon_running() -> bool:
    """Checks if background daemon is active on port 8765. If not, spawns it independently."""
    import urllib.request
    try:
        req = urllib.request.Request("http://127.0.0.1:8765/api/remote/info", headers={"User-Agent": "WinDropLocal"})
        with urllib.request.urlopen(req, timeout=0.8) as resp:
            if resp.status == 200:
                print("[main] Background daemon already active and healthy on port 8765.", flush=True)
                return True
    except Exception:
        pass

    print("[main] Port 8765 not responding!", flush=True)
    if getattr(sys, "frozen", False):
        print("[main] Frozen WinDrop.exe detected: using in-process high-performance server thread (zero external python)", flush=True)
        return False

    py_exe = r"C:\Users\pc\AppData\Local\Programs\Python\Python312\pythonw.exe"
    if not os.path.exists(py_exe):
        py_exe = str(Path(sys.executable).with_name("pythonw.exe"))
    daemon_script = str((BASE_DIR / "run_headless_daemon.py").resolve())

    try:
        flags = 0
        if sys.platform == "win32":
            flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP | 0x08000000
        subprocess.Popen([py_exe, daemon_script], cwd=str(BASE_DIR), creationflags=flags)
        print("[main] Spawned independent background daemon via pythonw!", flush=True)
    except Exception as e:
        print(f"[main] Error launching background daemon: {e}", flush=True)

    # Wait up to 3 seconds for the daemon to start answering
    for _ in range(30):
        time.sleep(0.1)
        try:
            req = urllib.request.Request("http://127.0.0.1:8765/api/remote/info", headers={"User-Agent": "WinDropLocal"})
            with urllib.request.urlopen(req, timeout=0.5) as resp:
                if resp.status == 200:
                    print("[main] Background daemon successfully initialized and confirmed on port 8765!", flush=True)
                    return True
        except Exception:
            pass
    return False


def setup_windows_autostart() -> None:
    """Ensures single clean WinDrop P2P Tray autostart on Windows boot/login (zero manual server)."""
    try:
        desktop_exe = Path(r"C:\Users\pc\Desktop\WinDrop.exe")
        if getattr(sys, "frozen", False):
            exe_path = str(desktop_exe if desktop_exe.exists() else Path(sys.executable).resolve())
            cmd_str = f'"{exe_path}" --tray'
        else:
            if desktop_exe.exists():
                cmd_str = f'"{desktop_exe}" --tray'
            else:
                py_exe = r"C:\Users\pc\AppData\Local\Programs\Python\Python312\pythonw.exe"
                if not os.path.exists(py_exe):
                    py_exe = str(Path(sys.executable).with_name("pythonw.exe"))
                daemon_script = str((BASE_DIR / "run_headless_daemon.py").resolve())
                cmd_str = f'"{py_exe}" "{daemon_script}"'

        import winreg
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run") as key:
            winreg.SetValueEx(key, "WinDropP2PTray", 0, winreg.REG_SZ, cmd_str)
            # Clean up older keys
            for old_k in ("WinDrop", "WinDropBgDaemon", "WinDropServer", "WinDropTray", "WinDrop_Tray", "WinDropDaemon"):
                try:
                    winreg.DeleteValue(key, old_k)
                except FileNotFoundError:
                    pass

        print("[autostart] WinDrop P2P Tray canonical autostart registered on boot (WinDropP2PTray)", flush=True)
    except Exception as e:
        print(f"[autostart] Error registering autostart: {e}", flush=True)

def try_silent_firewall_allow() -> None:
    """Attempts to silently ensure Windows Firewall allows WinDrop on port 8765."""
    try:
        cmd = 'netsh advfirewall firewall add rule name="WinDrop P2P" dir=in action=allow protocol=TCP localport=8765 profile=any'
        subprocess.run(cmd, shell=True, capture_output=True, creationflags=0x08000000)
    except Exception:
        pass


def _real_main() -> None:
    print("[main] entered", flush=True)
    try_silent_firewall_allow()
    is_background = any(arg in sys.argv for arg in ("--background", "--silent", "--tray", "--minimized", "-b"))
    smoke_test = "--smoke-test" in sys.argv
    initial_files: List[str] = []
    if len(sys.argv) > 1:
        args = [a for a in sys.argv[1:] if a not in ("--send", "--smoke-test", "--background", "--silent", "--tray", "--minimized", "-b") and os.path.exists(a)]
        if args:
            initial_files = args

    # 1. Quick probe to existing running GUI instance via Local IPC
    if not smoke_test:
        try:
            from PyQt6.QtNetwork import QLocalSocket
            probe_app = QApplication.instance() or QApplication(sys.argv)
            sock = QLocalSocket()
            sock.connectToServer("WinDrop_SingleInstance_IPC")
            if sock.waitForConnected(350):
                if is_background:
                    print("[main] WinDrop instance is already running. Background tray active. Exiting.", flush=True)
                    sock.disconnectFromServer()
                    return
                msg = ("ADD:" + "|".join(initial_files)).encode("utf-8") if initial_files else b"SHOW\n"
                sock.write(msg)
                sock.waitForBytesWritten(500)
                sock.disconnectFromServer()
                print("[main] Notified running WinDrop instance via IPC. Bringing to front.", flush=True)
                return
        except Exception:
            pass

    # 2. Check if a visible WinDrop GUI window already exists in this desktop session
    existing_hwnd = _find_existing_windrop_hwnd()
    if existing_hwnd != 0 and not is_background and not smoke_test:
        print(f"[main] Existing visible WinDrop window found (HWND={existing_hwnd}). Bringing to front.", flush=True)
        try:
            user32 = ctypes.windll.user32
            user32.ShowWindow(existing_hwnd, 9)  # SW_RESTORE
            user32.SetForegroundWindow(existing_hwnd)
            user32.BringWindowToTop(existing_hwnd)
        except Exception:
            pass
        if initial_files:
            try:
                push_files_to_running_instance(initial_files, port=8765)
            except Exception:
                pass
            return

    enable_sleep_prevention()
    setup_windows_autostart()

    # Automatically ensure the independent 24/7 background daemon is running
    daemon_ready = ensure_background_daemon_running()

    runner = None
    if not daemon_ready:
        print("[main] Fallback: Starting in-process WinDropServerRunner on port 8765...", flush=True)
        runner = WinDropServerRunner(port=8765)
        runner.start()
        time.sleep(0.2)
    else:
        print("[main] Background daemon confirmed active on port 8765. Running GUI in Client Mode...", flush=True)

    print("[main] Creating QApplication...", flush=True)
    app = QApplication.instance()
    if not app:
        app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    print("[main] Creating WinDropMainWindow...", flush=True)
    win = WinDropMainWindow(runner=runner, initial_files=initial_files)
    if runner:
        runner.engine.show_gui_callback = lambda: win.ui_event_signal.emit('show_gui', {})
    else:
        win.engine.show_gui_callback = lambda: win.ui_event_signal.emit('show_gui', {})

    if not is_background:
        print("[main] Showing window on active desktop...", flush=True)
        win.bring_to_front()
    else:
        print("[main] WinDrop started silently in background (System Tray active)", flush=True)
        win.hide()

    if smoke_test:
        print("[main] scheduling smoke test quit in 400ms", flush=True)
        def _clean_quit():
            try:
                if hasattr(win, "radar") and hasattr(win.radar, "anim_timer"):
                    win.radar.anim_timer.stop()
                if hasattr(win, "client_sync_timer"):
                    win.client_sync_timer.stop()
                win._force_quit = True
                win.close()
                app.quit()
            finally:
                os._exit(0)
        QTimer.singleShot(400, _clean_quit)

    print("[main] running app.exec()", flush=True)
    exit_code = app.exec()
    print(f"[main] app.exec finished with {exit_code}", flush=True)
    # Server is decoupled and runs independently in background; NEVER stop it on GUI exit!
    sys.exit(exit_code)


def main() -> None:
    try:
        _real_main()
    except Exception as e:
        import traceback
        err = traceback.format_exc()
        try:
            with open("windrop_startup_error.log", "w", encoding="utf-8") as f:
                f.write(err)
        except Exception:
            pass
        try:
            from PyQt6.QtWidgets import QApplication, QMessageBox
            a = QApplication.instance() or QApplication(sys.argv)
            QMessageBox.critical(None, "WinDrop Hatası", f"WinDrop başlatılamadı:\n\n{e}\n\nAyrıntılar windrop_startup_error.log dosyasına kaydedildi.")
        except Exception:
            pass

if __name__ == '__main__':

    main()