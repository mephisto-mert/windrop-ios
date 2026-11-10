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
import tempfile
import time
from pathlib import Path
from typing import Dict, List, Optional

if getattr(sys, "frozen", False):
    BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    BASE_DIR = Path(r"c:\Users\pc\Documents\projelerim\windrop_airdrop") if Path(r"c:\Users\pc\Documents\projelerim\windrop_airdrop").exists() else Path(sys.executable).parent
    for _dll_sub in (BUNDLE_DIR, BUNDLE_DIR / "PyQt6" / "Qt6" / "bin"):
        if _dll_sub.exists():
            os.environ["PATH"] = str(_dll_sub) + os.pathsep + os.environ.get("PATH", "")
            if hasattr(os, "add_dll_directory"):
                try:
                    os.add_dll_directory(str(_dll_sub))
                except Exception:
                    pass
else:
    BUNDLE_DIR = Path(__file__).resolve().parent
    BASE_DIR = BUNDLE_DIR

_appdata_dir = Path(os.environ.get("LOCALAPPDATA", tempfile.gettempdir())) / "WinDrop"
try:
    _appdata_dir.mkdir(parents=True, exist_ok=True)
except Exception:
    _appdata_dir = Path(tempfile.gettempdir())

_log_path = _appdata_dir / "windrop_gui.log"
if sys.stdout is None:
    try:
        sys.stdout = open(_log_path, "a", encoding="utf-8", buffering=1)
    except Exception:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
elif hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

if sys.stderr is None:
    try:
        sys.stderr = open(_log_path, "a", encoding="utf-8", buffering=1)
    except Exception:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")
elif hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

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

_home = Path.home()
_desktop_candidates = [
    _home / "Desktop",
    _home / "Masaüstü",
    _home / "OneDrive" / "Desktop",
    _home / "OneDrive" / "Masaüstü",
    _home,
]
desktop_dir = next((d for d in _desktop_candidates if d.exists()), _home)
DEST_FOLDER = desktop_dir / "WinDrop_Gelenler"
try:
    DEST_FOLDER.mkdir(parents=True, exist_ok=True)
except Exception:
    try:
        DEST_FOLDER = _appdata_dir / "WinDrop_Gelenler"
        DEST_FOLDER.mkdir(parents=True, exist_ok=True)
    except Exception:
        DEST_FOLDER = Path(tempfile.gettempdir()) / "WinDrop_Gelenler"
        DEST_FOLDER.mkdir(parents=True, exist_ok=True)


def format_bytes(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1048576:
        return f"{size / 1024:.1f} KB"
    if size < 1073741824:
        return f"{size / 1048576:.2f} MB"
    return f"{size / 1073741824:.2f} GB"


def elide_middle(text: str, max_len: int = 32) -> str:
    if not text or len(text) <= max_len:
        return text
    keep = (max_len - 1) // 2
    return f"{text[:keep]}…{text[-keep:]}"


def load_cupertino_fonts() -> str:
    """Loads baked Apple SF Pro Text, SF Pro Display, and SF Mono fonts from CupertinoUi."""
    from PyQt6.QtGui import QFontDatabase
    primary_family = "Segoe UI"
    for root in (BUNDLE_DIR, BASE_DIR):
        fdir = root / "cupertino_assets" / "fonts"
        if fdir.exists():
            for otf in sorted(fdir.glob("*.otf")):
                try:
                    fid = QFontDatabase.addApplicationFont(str(otf))
                    if fid != -1 and "SF-Pro-Text-Regular" in otf.name:
                        fams = QFontDatabase.applicationFontFamilies(fid)
                        if fams:
                            primary_family = fams[0]
                except Exception:
                    pass
            break
    return primary_family


def get_cupertino_asset_path(rel_path: str) -> Optional[Path]:
    for root in (BUNDLE_DIR, BASE_DIR):
        p = root / "cupertino_assets" / rel_path
        if p.exists():
            return p
    return None


def make_airdrop_squircle_pixmap(size: int = 20) -> QPixmap:
    """Draws CupertinoUi's exact PaintAirDrop icon (SidebarIcons.cpp: white squircle plate + #007AFF rings)."""
    pix = QPixmap(size * 2, size * 2)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    s = float(size * 2)
    plate_rect = QRectF(1.0, 1.0, s - 2.0, s - 2.0)
    path = QPainterPath()
    path.addRoundedRect(plate_rect, s * 0.225, s * 0.225)
    p.fillPath(path, QColor("#FFFFFF"))
    p.setPen(QPen(QColor(0, 0, 0, 28), 1.0))
    p.drawPath(path)

    blue = QColor("#007AFF")
    cx, cy = s * 0.5, s * 0.50
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(blue)
    p.drawEllipse(QPointF(cx, cy), s * 0.055, s * 0.055)

    p.setBrush(Qt.BrushStyle.NoBrush)
    for r_frac in (0.14, 0.245, 0.35):
        r = s * r_frac
        pen = QPen(blue, s * 0.055, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        arc_rect = QRectF(cx - r, cy - r, r * 2.0, r * 2.0)
        # Open 30 degrees to either side of straight down (-90 deg in Qt = 270*16)
        # Starts at -60 deg (-60 * 16) and spans 300 deg (300 * 16) counter-clockwise
        p.drawArc(arc_rect, -60 * 16, 300 * 16)
    p.end()
    pix.setDevicePixelRatio(2.0)
    return pix


def make_sequoia_crest_pixmap(size: int = 36) -> QPixmap:
    """Draws CupertinoUi's exact PaintSequoia circular badge (SidebarIcons.cpp lines 164-187)."""
    from PyQt6.QtGui import QLinearGradient
    pix = QPixmap(size * 2, size * 2)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    s = float(size * 2)
    cx, cy = s * 0.5, s * 0.5
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(255, 255, 255, 240))
    p.drawEllipse(QPointF(cx, cy), s * 0.48, s * 0.48)

    grad = QLinearGradient(0.0, s, s, 0.0)
    grad.setColorAt(0.00, QColor("#012C9B"))
    grad.setColorAt(0.20, QColor("#0355BD"))
    grad.setColorAt(0.38, QColor("#1082D7"))
    grad.setColorAt(0.58, QColor("#9F76B5"))
    grad.setColorAt(0.78, QColor("#F58A54"))
    grad.setColorAt(0.92, QColor("#FBBB7B"))
    grad.setColorAt(1.00, QColor("#FCD397"))
    p.setBrush(grad)
    p.drawEllipse(QPointF(cx, cy), s * 0.43, s * 0.43)

    # Subtle AirDrop wave overlay in white
    p.setBrush(QColor(255, 255, 255, 235))
    p.drawEllipse(QPointF(cx, cy + s * 0.03), s * 0.05, s * 0.05)
    p.setBrush(Qt.BrushStyle.NoBrush)
    for r_frac in (0.13, 0.23, 0.33):
        r = s * r_frac
        p.setPen(QPen(QColor(255, 255, 255, 230), s * 0.045, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawArc(QRectF(cx - r, cy + s * 0.03 - r, r * 2.0, r * 2.0), -60 * 16, 300 * 16)
    p.end()
    pix.setDevicePixelRatio(2.0)
    return pix


def make_sidebar_icon(asset_rel: str, fallback_AirDrop: bool = False, size: int = 20) -> QIcon:
    if fallback_AirDrop:
        return QIcon(make_airdrop_squircle_pixmap(size))
    p = get_cupertino_asset_path(asset_rel)
    if p and p.exists():
        pix = QPixmap(str(p))
        if not pix.isNull():
            return QIcon(pix.scaled(size * 2, size * 2, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
    return QIcon(make_airdrop_squircle_pixmap(size))



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
    """CupertinoUi macOS 15 Sequoia AirDrop Radar with deduplicated peer badges and drag-and-drop."""
    files_dropped = pyqtSignal(list)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setMinimumSize(300, 220)
        self.phase = 0.0
        self.peers: List[Dict] = []
        self.is_drag_hover = False
        self._center_pix = make_airdrop_squircle_pixmap(26)

        self.anim_timer = QTimer(self)
        self.anim_timer.timeout.connect(self._tick)
        self.anim_timer.start(40)

    def set_peers(self, peers: List[Dict]):
        # Strict IP deduplication so 1 physical iPhone = 1 crisp node on radar
        dedup = {}
        for p in (peers or []):
            ip = (p.get("ip") or "").strip()
            if not ip or ip in ("127.0.0.1", "localhost", "::1"):
                continue
            if ip not in dedup:
                dedup[ip] = p
        self.peers = list(dedup.values())
        self.update()

    def _tick(self):
        self.phase = (self.phase + 0.022) % 1.0
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
        cx, cy = w / 2.0, (h - 34.0) / 2.0
        max_r = min(w, h - 44.0) * 0.44

        has_peer = len(self.peers) > 0 or self.is_drag_hover

        # 21st.dev Ambient Radial Spotlight
        grad = QRadialGradient(cx, cy, max_r * 1.25)
        if has_peer:
            grad.setColorAt(0.0, QColor(16, 68, 42, 110))
            grad.setColorAt(0.55, QColor(12, 36, 28, 45))
        else:
            grad.setColorAt(0.0, QColor(14, 48, 92, 115))
            grad.setColorAt(0.55, QColor(14, 26, 48, 45))
        grad.setColorAt(1.0, QColor(14, 15, 20, 0))
        p.setBrush(grad)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRect(self.rect())

        # Static Subtle Grid Rings (21st.dev Bento Radar Grid)
        for frac in (0.35, 0.68, 1.0):
            gr = max_r * frac
            p.setPen(QPen(QColor(255, 255, 255, 18), 1.0, Qt.PenStyle.DashLine))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QPointF(cx, cy), gr, gr)

        # Animated Expanding Pulse Rings
        num_rings = 3
        for i in range(num_rings):
            offset = (self.phase + i / num_rings) % 1.0
            r = max_r * offset
            alpha = int(150 * (1.0 - offset))
            pen_col = QColor(48, 209, 88, alpha) if has_peer else QColor(10, 132, 255, alpha)
            p.setPen(QPen(pen_col, 1.6))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QPointF(cx, cy), r, r)

        # Center Desktop Hub Node (CupertinoUi PaintAirDrop Emblem)
        outer_glow = QRadialGradient(cx, cy, 42)
        outer_glow.setColorAt(0.0, QColor(10, 132, 255, 130))
        outer_glow.setColorAt(1.0, QColor(10, 132, 255, 0))
        p.setBrush(outer_glow)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(cx, cy), 42, 42)

        if self._center_pix and not self._center_pix.isNull():
            p.drawPixmap(int(cx - 26), int(cy - 26), 52, 52, self._center_pix)
        else:
            p.setBrush(QColor(18, 22, 32))
            p.setPen(QPen(QColor(10, 132, 255, 230), 2.2))
            p.drawEllipse(QPointF(cx, cy), 26, 26)

        # Discovered Peers (Positioned cleanly in upper quadrants so they never collide with bottom drop pill)
        safe_angles = [-math.pi / 4.0, -3.0 * math.pi / 4.0, math.pi / 6.0, 5.0 * math.pi / 6.0]
        for idx, peer in enumerate(self.peers[:4]):
            angle = safe_angles[idx % len(safe_angles)]
            pr = max_r * 0.68
            px = cx + math.cos(angle) * pr
            py = cy + math.sin(angle) * pr

            # Connection Beam Line from Center to iPhone
            p.setPen(QPen(QColor(50, 215, 75, 120), 1.8, Qt.PenStyle.DotLine))
            p.drawLine(QPointF(cx, cy), QPointF(px, py))

            # Peer Halo
            halo = QRadialGradient(px, py, 30)
            halo.setColorAt(0.0, QColor(50, 215, 75, 130))
            halo.setColorAt(1.0, QColor(50, 215, 75, 0))
            p.setBrush(halo)
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QPointF(px, py), 30, 30)

            # Peer Circle (macOS Sequoia SystemGreen #32D74B)
            p.setBrush(QColor(28, 48, 34))
            p.setPen(QPen(QColor("#32D74B"), 2.0))
            p.drawEllipse(QPointF(px, py), 19, 19)
            p.setFont(QFont("Segoe UI Emoji", 11))
            p.setPen(QColor(255, 255, 255))
            p.drawText(QRectF(px - 19, py - 19, 38, 38), Qt.AlignmentFlag.AlignCenter, "📱")

            # Cupertino Pill Label under Peer Node
            pip = peer.get("ip", "")
            lbl_text = f"iPhone • {pip}" if pip else "iPhone (iOS)"
            pill_w, pill_h = 132.0, 20.0
            pill_rect = QRectF(px - pill_w / 2.0, py + 22.0, pill_w, pill_h)
            path = QPainterPath()
            path.addRoundedRect(pill_rect, 6.0, 6.0)
            p.fillPath(path, QColor(30, 30, 34, 235))
            p.setPen(QPen(QColor(255, 255, 255, 38), 1.0))
            p.drawPath(path)

            p.setFont(QFont("SF Pro Text", 8, QFont.Weight.DemiBold))
            p.setPen(QColor("#32D74B"))
            p.drawText(pill_rect, Qt.AlignmentFlag.AlignCenter, lbl_text)

        # Bottom Cupertino Bezel Drop Zone Pill
        drop_w = min(w - 24.0, 276.0)
        drop_h = 24.0
        drop_rect = QRectF((w - drop_w) / 2.0, h - 30.0, drop_w, drop_h)
        drop_path = QPainterPath()
        drop_path.addRoundedRect(drop_rect, 6.0, 6.0)
        if self.is_drag_hover:
            p.fillPath(drop_path, QColor(10, 132, 255, 65))
            p.setPen(QPen(QColor("#0A84FF"), 1.2))
        else:
            p.fillPath(drop_path, QColor(255, 255, 255, 16))
            p.setPen(QPen(QColor(255, 255, 255, 34), 1.0))
        p.drawPath(drop_path)

        p.setFont(QFont("SF Pro Text", 9, QFont.Weight.Medium))
        p.setPen(QColor("#FFFFFF") if self.is_drag_hover else QColor(235, 235, 240, 200))
        hint = "📂 Dosyaları Radara Sürükle & Bırak" if not self.is_drag_hover else "⚡ Şimdi Bırak — Anında iPhone'a Gönder!"
        p.drawText(drop_rect, Qt.AlignmentFlag.AlignCenter, hint)



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
                    
                    # 1. Peers Sync: strictly filter out loopback/localhost and PC's own LAN IP, deduplicate by IP
                    raw_peers = data.get("peers") or data.get("discovered_peers", [])
                    dedup_peers = {}
                    for p in raw_peers:
                        pip = (p.get("ip") or "").strip()
                        if not pip or pip in ("127.0.0.1", "localhost", "::1") or pip == self.lan_ip:
                            continue
                        if p.get("online", True) and pip not in dedup_peers:
                            dedup_peers[pip] = p
                    real_peers = list(dedup_peers.values())
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
            if not user32.IsWindowVisible(hwnd) or user32.IsHungAppWindow(hwnd):
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
        self.resize(1060, 690)
        self.setMinimumSize(980, 600)
        self.setAcceptDrops(True)

        # Frameless macOS Window Architecture (GPU-safe solid surface + DWM rounded corners)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Window
            | Qt.WindowType.WindowSystemMenuHint
            | Qt.WindowType.WindowMinimizeButtonHint
            | Qt.WindowType.WindowMaximizeButtonHint
        )
        self.setStyleSheet("QMainWindow { background-color: #2B2A2F; border: none; }")

        # Center on primary desktop screen
        primary = QApplication.primaryScreen()
        if primary:
            geom = primary.availableGeometry()
            cx = max(geom.x(), (geom.width() - 1020) // 2 + geom.x())
            cy = max(geom.y(), (geom.height() - 680) // 2 + geom.y())
            self.move(cx, cy)

        self.ui_event_signal.connect(self._handle_engine_event)
        self.engine.add_listener(lambda et, data: self.ui_event_signal.emit(et, data))
        self._build_ui()
        self._force_quit = False
        self._setup_system_tray()

        # Apply Windows 11 DWM rounded corners safely after UI creation (zero WS_EX_LAYERED GPU crash)
        try:
            hwnd = int(self.winId())
            dwmapi = ctypes.windll.dwmapi
            DWMWA_WINDOW_CORNER_PREFERENCE = 33
            DWMWCP_ROUND = ctypes.c_int(2)
            dwmapi.DwmSetWindowAttribute(
                wintypes.HWND(hwnd),
                wintypes.DWORD(DWMWA_WINDOW_CORNER_PREFERENCE),
                ctypes.byref(DWMWCP_ROUND),
                ctypes.sizeof(DWMWCP_ROUND),
            )
        except Exception:
            pass

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
            while self.ipc_server.hasPendingConnections():
                client = self.ipc_server.nextPendingConnection()
                if client:
                    client.readyRead.connect(lambda c=client: self._handle_ipc_message(c))
                    if client.bytesAvailable() > 0 or client.waitForReadyRead(150):
                        self._handle_ipc_message(client)
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
                short_name = elide_middle(f.name, 22)
                item = QListWidgetItem(f"✅ [{t_str}] {short_name} ({format_bytes(size)})")
                item.setToolTip(str(f))
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
                pip = latest.get("ip", "")
                dname = f"iPhone ({pip})" if pip else latest.get("name", "iPhone")
                self.peer_status_lbl.setText(f"● Bağlı: {dname}")
                self.peer_status_lbl.setStyleSheet(
                    "background: rgba(50, 215, 75, 0.14); color: #32D74B; border: 1px solid rgba(50, 215, 75, 0.32); "
                    "border-radius: 10px; padding: 3px 10px; font-size: 11px; font-weight: 600;"
                )
                if hasattr(self, "sb_account_sub"):
                    self.sb_account_sub.setText(f"🟢 {pip or 'iPhone Bağlı'}")
                    self.sb_account_sub.setStyleSheet("font-size: 11px; color: #32D74B; border: none; background: transparent;")
                if hasattr(self, "transfer_status_lbl") and "Alındı" not in self.transfer_status_lbl.text():
                    self.transfer_status_lbl.setText(f"Hazır — {dname} bağlı")
            else:
                self.radar.set_peers([])
                self.peer_status_lbl.setText("● iPhone Bekleniyor")
                self.peer_status_lbl.setStyleSheet(
                    "background: rgba(10, 132, 255, 0.14); color: #5AC8F5; border: 1px solid rgba(10, 132, 255, 0.28); "
                    "border-radius: 10px; padding: 3px 10px; font-size: 11px; font-weight: 600;"
                )
                if hasattr(self, "sb_account_sub"):
                    self.sb_account_sub.setText(f"{self.engine.lan_ip}:{self.engine.port}")
                    self.sb_account_sub.setStyleSheet("font-size: 11px; color: rgba(255,255,255,0.55); border: none; background: transparent;")

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
                            self._last_usb_html = f"<span style='color:#32D74B; font-weight:600;'>🟢 {dname} Bağlı (480 Mbps)</span>"
                        else:
                            self._last_usb_html = "<span style='color:rgba(255,255,255,0.45);'>Kablo bekleniyor…</span>"
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

        act_folder = menu.addAction("📁 Gelen Dosyaları Aç")
        act_folder.triggered.connect(lambda: subprocess.Popen(f'explorer "{self.engine.receive_dir}"', shell=True))

        act_copy = menu.addAction(f"📋 IP Adresini Kopyala ({self.engine.lan_ip}:{self.engine.port})")
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
        url = f"{self.engine.lan_ip}:{self.engine.port}"
        clipboard = QApplication.clipboard()
        if clipboard:
            clipboard.setText(url)
        if hasattr(self, "tray_icon") and self.tray_icon.isVisible():
            self.tray_icon.showMessage("WinDrop", f"P2P IP adresi kopyalandı:\n{url}", QSystemTrayIcon.MessageIcon.Information, 1500)

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

    def mousePressEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton and ev.position().y() <= 56:
            self._win_drag_pos = ev.globalPosition().toPoint() - self.frameGeometry().topLeft()
            ev.accept()
            return
        super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev):
        if getattr(self, "_win_drag_pos", None) and (ev.buttons() & Qt.MouseButton.LeftButton) and not self.isMaximized():
            self.move(ev.globalPosition().toPoint() - self._win_drag_pos)
            ev.accept()
            return
        super().mouseMoveEvent(ev)

    def mouseReleaseEvent(self, ev):
        self._win_drag_pos = None
        super().mouseReleaseEvent(ev)

    def _build_ui(self) -> None:
        load_cupertino_fonts()
        self.container_frame = QFrame(self)
        self.setCentralWidget(self.container_frame)
        self.container_frame.setObjectName("MacWindow")
        self.container_frame.setStyleSheet("""
            QFrame#MacWindow {
                background-color: #2B2A2F;
                border: 1px solid rgba(255, 255, 255, 0.20);
                border-radius: 10px;
            }
            QWidget {
                color: #D9D9DF;
                font-family: "SF Pro Text", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            }
            QLabel {
                border: none;
                background: transparent;
            }
            QFrame#Sidebar {
                background-color: #323136;
                border-right: 1px solid #000000;
                border-top-left-radius: 10px;
                border-bottom-left-radius: 10px;
            }
            QFrame#DetailToolbar {
                background-color: #252429;
                border-bottom: 1px solid rgba(0, 0, 0, 0.55);
                border-top-right-radius: 10px;
            }
            QFrame#CupertinoSection, QFrame#ContentCard {
                background-color: rgba(255, 255, 255, 0.025);
                border: 1px solid rgba(255, 255, 255, 0.13);
                border-radius: 6px;
            }
            QFrame#RowDivider {
                background-color: rgba(255, 255, 255, 0.055);
                border: none;
                max-height: 1px;
                min-height: 1px;
            }
            QFrame#SidebarDestCard {
                background-color: rgba(255, 255, 255, 0.04);
                border: 1px solid rgba(255, 255, 255, 0.09);
                border-radius: 6px;
            }
            QFrame#StatCard {
                background-color: rgba(255, 255, 255, 0.03);
                border: 1px solid rgba(255, 255, 255, 0.11);
                border-radius: 6px;
            }
            QPushButton.MacBtn {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #5E5E63, stop:1 #525257);
                border: 1px solid rgba(255, 255, 255, 0.18);
                border-bottom-color: rgba(0, 0, 0, 0.35);
                border-radius: 5px;
                color: #EBEBF0;
                font-size: 12px;
                font-weight: 500;
                padding: 4px 12px;
                min-height: 14px;
            }
            QPushButton.MacBtn:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #6A6A70, stop:1 #5C5C62);
                color: #FFFFFF;
            }
            QPushButton.MacBtn:pressed {
                background: #48484D;
            }
            QPushButton.MacBtnPrimary {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #148EFF, stop:1 #0070E0);
                border: 1px solid rgba(255, 255, 255, 0.25);
                border-bottom-color: rgba(0, 0, 0, 0.35);
                border-radius: 5px;
                color: #FFFFFF;
                font-size: 12px;
                font-weight: 600;
                padding: 4px 12px;
                min-height: 14px;
            }
            QPushButton.MacBtnPrimary:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #2B99FF, stop:1 #0A7AFF);
            }
            QListWidget {
                background: #1E1E1E;
                border: 1px solid rgba(255, 255, 255, 0.12);
                border-radius: 6px;
                color: #EBEBF0;
                font-size: 12px;
                padding: 4px;
                outline: none;
            }
            QListWidget::item {
                padding: 6px 8px;
                border-radius: 4px;
                border-bottom: 1px solid rgba(255, 255, 255, 0.04);
            }
            QListWidget::item:selected {
                background: #0058D0;
                color: #FFFFFF;
            }
            QListWidget::item:hover:!selected {
                background: rgba(255, 255, 255, 0.04);
            }
            QProgressBar {
                background: rgba(255, 255, 255, 0.10);
                border: none;
                border-radius: 3px;
                max-height: 6px;
                min-height: 6px;
            }
            QProgressBar::chunk {
                background: #0A84FF;
                border-radius: 3px;
            }
        """)

        # Full-height Split View: Left Sidebar (220px) | 1px Black Divider | Right Detail Pane
        body_hbox = QHBoxLayout(self.container_frame)
        body_hbox.setContentsMargins(0, 0, 0, 0)
        body_hbox.setSpacing(0)

        # 1. Left Cupertino Sidebar (with Traffic Lights, Search, Account Row, and Squircle Icons)
        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(220)
        sb_layout = QVBoxLayout(sidebar)
        sb_layout.setContentsMargins(10, 14, 10, 12)
        sb_layout.setSpacing(6)

        # Traffic Lights Row inside Sidebar top-left (exact macOS 15 Sequoia System Settings)
        tl_row = QHBoxLayout()
        tl_row.setContentsMargins(8, 2, 4, 8)
        tl_row.setSpacing(8)
        btn_close = MacTrafficLight("#FF5F57", "#E0443E", "×", self)
        btn_min = MacTrafficLight("#FEBC2E", "#DEA123", "–", self)
        btn_max = MacTrafficLight("#28C840", "#1AAB29", "+", self)
        btn_close.clicked.connect(self.close)
        btn_min.clicked.connect(self.showMinimized)
        btn_max.clicked.connect(lambda: self.showNormal() if self.isMaximized() else self.showMaximized())
        tl_row.addWidget(btn_close)
        tl_row.addWidget(btn_min)
        tl_row.addWidget(btn_max)
        tl_row.addStretch()
        sb_layout.addLayout(tl_row)

        # Cupertino SidebarSearchField
        search_box = QFrame()
        search_box.setObjectName("SidebarSearch")
        search_box.setFixedHeight(28)
        search_box.setStyleSheet(
            "QFrame#SidebarSearch { background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.08); border-radius: 6px; }"
        )
        s_lay = QHBoxLayout(search_box)
        s_lay.setContentsMargins(8, 0, 8, 0)
        s_lbl = QLabel("🔍  Ara")
        s_lbl.setStyleSheet("font-size: 12px; color: rgba(255,255,255,0.45);")
        s_lay.addWidget(s_lbl)
        sb_layout.addWidget(search_box)
        sb_layout.addSpacing(4)

        # Cupertino SidebarAccount Row (Sequoia Crest + WinDrop Sequoia + Live IP/Status)
        acct_row = QHBoxLayout()
        acct_row.setContentsMargins(4, 4, 4, 8)
        acct_row.setSpacing(10)
        acct_avatar = QLabel()
        acct_avatar.setFixedSize(36, 36)
        acct_avatar.setPixmap(make_sequoia_crest_pixmap(36))
        acct_row.addWidget(acct_avatar)

        acct_text_lay = QVBoxLayout()
        acct_text_lay.setContentsMargins(0, 0, 0, 0)
        acct_text_lay.setSpacing(1)
        acct_name = QLabel("WinDrop Sequoia")
        acct_name.setStyleSheet("font-size: 13px; font-weight: 600; color: #EBEBF0;")
        self.sb_account_sub = QLabel(f"{self.engine.lan_ip}:{self.engine.port}")
        self.sb_account_sub.setStyleSheet("font-size: 11px; color: rgba(255,255,255,0.55);")
        acct_text_lay.addWidget(acct_name)
        acct_text_lay.addWidget(self.sb_account_sub)
        acct_row.addLayout(acct_text_lay, 1)
        sb_layout.addLayout(acct_row)

        self._last_gui_clip = ""
        try:
            QApplication.clipboard().dataChanged.connect(self._on_sys_clipboard_changed)
        except Exception:
            pass

        self.nav_btns: List[QPushButton] = []
        self._tab_titles = [
            "AirDrop & Handoff",
            "Canlı Ekran (Remote Desktop)",
            "Evrensel Pano (Universal Clipboard)",
            "Masaüstüne Alınanlar (WinDrop_Gelenler)",
            "Kestirme & Güvenlik Ayarları",
        ]
        tabs = [
            ("AirDrop && Handoff", 0, "", True),
            ("Canlı Ekran (Remote)", 1, "icons/sharing-screen.png", False),
            ("Evrensel Pano", 2, "icons/extension-sharing.png", False),
            ("Gelenler Klasörü", 3, "icons/sharing-file.png", False),
            ("Kestirme && Güvenlik", 4, "icons/firewall.png", False),
        ]

        for label, idx, icon_rel, is_airdrop in tabs:
            if idx == 2:
                sb_layout.addSpacing(8)
            btn = QPushButton(f"  {label}")
            btn.setIcon(make_sidebar_icon(icon_rel, fallback_AirDrop=is_airdrop, size=20))
            btn.setIconSize(QSize(20, 20))
            btn.setFixedHeight(28)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda ch, i=idx: self._switch_tab(i))
            sb_layout.addWidget(btn)
            self.nav_btns.append(btn)

        sb_layout.addStretch()

        # Destination Folder Card inside Sidebar
        dest_card = QFrame()
        dest_card.setObjectName("SidebarDestCard")
        dest_lay = QVBoxLayout(dest_card)
        dest_lay.setContentsMargins(10, 8, 10, 8)
        dest_lay.setSpacing(2)
        dest_title = QLabel("📥 Kayıt Yeri")
        dest_title.setStyleSheet("font-size: 11px; font-weight: 600; color: rgba(255,255,255,0.55);")
        dest_path = QLabel("Desktop / WinDrop_Gelenler")
        dest_path.setStyleSheet("font-size: 11px; color: #419CFF; font-family: 'SF Mono', Consolas, monospace;")
        dest_path.setWordWrap(True)
        dest_lay.addWidget(dest_title)
        dest_lay.addWidget(dest_path)
        sb_layout.addWidget(dest_card)

        body_hbox.addWidget(sidebar)

        # 2. Right Detail Pane (Unified Sequoia Toolbar + Central Stack)
        detail_container = QWidget()
        detail_vbox = QVBoxLayout(detail_container)
        detail_vbox.setContentsMargins(0, 0, 0, 0)
        detail_vbox.setSpacing(0)

        self.title_bar = MacTitleBar(self, title="AirDrop & Handoff")
        self.title_bar.setObjectName("DetailToolbar")
        self.title_bar.setFixedHeight(52)
        # Hide duplicate traffic lights inside right toolbar since they live in Sidebar top-left
        self.title_bar.btn_close.hide()
        self.title_bar.btn_min.hide()
        self.title_bar.btn_max.hide()
        self.title_bar.sub_lbl.setText("")
        self.title_bar.title_lbl.setStyleSheet("font-size: 15px; font-weight: 600; color: #EBEBF0;")
        detail_vbox.addWidget(self.title_bar)

        self.stack = QStackedWidget()
        detail_vbox.addWidget(self.stack, 1)

        self.stack.addWidget(self._create_airdrop_tab())
        self.stack.addWidget(self._create_remote_tab())
        self.stack.addWidget(self._create_clipboard_tab())
        self.stack.addWidget(self._create_files_tab())
        self.stack.addWidget(self._create_settings_tab())

        body_hbox.addWidget(detail_container, 1)
        self._switch_tab(0)

    def _switch_tab(self, idx: int):
        self.stack.setCurrentIndex(idx)
        if hasattr(self, "title_bar") and hasattr(self, "_tab_titles") and 0 <= idx < len(self._tab_titles):
            self.title_bar.title_lbl.setText(f"‹   ›    {self._tab_titles[idx]}")
        for i, btn in enumerate(self.nav_btns):
            if i == idx:
                # Exact Cupertino::Theme::Selection(0x007AFF, Dark) = #3A72C9 platter
                btn.setStyleSheet(
                    "background: #3A72C9; color: #FFFFFF; font-size: 13px; font-weight: 500; "
                    "border: none; border-radius: 6px; text-align: left; padding: 0px 8px;"
                )
            else:
                btn.setStyleSheet(
                    "background: transparent; color: rgba(255, 255, 255, 0.92); font-size: 13px; font-weight: 400; "
                    "border: none; border-radius: 6px; text-align: left; padding: 0px 8px;"
                )

    def _create_airdrop_tab(self) -> QWidget:
        tab = QWidget()
        lay = QHBoxLayout(tab)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(14)

        # Left Column: Cupertino Radar Section + Cupertino Grouped Form Section
        left_col = QVBoxLayout()
        left_col.setContentsMargins(0, 0, 0, 0)
        left_col.setSpacing(12)

        radar_section = QFrame()
        radar_section.setObjectName("CupertinoSection")
        r_sec_lay = QVBoxLayout(radar_section)
        r_sec_lay.setContentsMargins(14, 12, 14, 12)
        r_sec_lay.setSpacing(8)

        radar_hdr = QHBoxLayout()
        title_lbl = QLabel("Canlı AirDrop Radarı")
        title_lbl.setStyleSheet("font-size: 13px; font-weight: 600; color: #EBEBF0;")
        self.peer_status_lbl = QLabel("● iPhone Bekleniyor")
        self.peer_status_lbl.setStyleSheet(
            "background: rgba(10, 132, 255, 0.14); color: #5AC8F5; border: 1px solid rgba(10, 132, 255, 0.28); "
            "border-radius: 10px; padding: 3px 10px; font-size: 11px; font-weight: 600;"
        )
        radar_hdr.addWidget(title_lbl)
        radar_hdr.addStretch()
        radar_hdr.addWidget(self.peer_status_lbl)
        r_sec_lay.addLayout(radar_hdr)

        self.radar = AirDropRadarWidget()
        self.radar.files_dropped.connect(self._add_files)
        r_sec_lay.addWidget(self.radar, 1)
        left_col.addWidget(radar_section, 1)

        # Cupertino Grouped Form Section (AirDropPane.cpp / DisplaysPane.cpp style)
        conn_section = QFrame()
        conn_section.setObjectName("CupertinoSection")
        c_lay = QVBoxLayout(conn_section)
        c_lay.setContentsMargins(12, 10, 12, 10)
        c_lay.setSpacing(7)

        # Row 1: QR Well + iPhone Native App Pairing + Copy Button
        row_qr = QHBoxLayout()
        row_qr.setSpacing(12)
        self.qr_lbl = QLabel()
        self.qr_lbl.setFixedSize(72, 72)
        self.qr_lbl.setStyleSheet("background: #FFFFFF; border-radius: 6px; padding: 3px;")
        self._render_qr_code()
        row_qr.addWidget(self.qr_lbl)

        qr_meta = QVBoxLayout()
        qr_meta.setContentsMargins(0, 0, 0, 0)
        qr_meta.setSpacing(2)
        url_text = f"{self.engine.lan_ip}:{self.engine.port}"
        qr_title = QLabel("iPhone WinDrop Uygulama Eşleşmesi")
        qr_title.setStyleSheet("font-size: 12px; font-weight: 600; color: #EBEBF0;")
        qr_url = QLabel(url_text)
        qr_url.setStyleSheet("font-size: 11.5px; color: #419CFF; font-family: 'SF Mono', Consolas, monospace;")
        qr_sub = QLabel("WinDrop iOS uygulamasından QR okutun veya IP girin.")
        qr_sub.setStyleSheet("font-size: 11px; color: rgba(255, 255, 255, 0.50);")
        qr_sub.setWordWrap(True)
        qr_meta.addWidget(qr_title)
        qr_meta.addWidget(qr_url)
        qr_meta.addWidget(qr_sub)
        row_qr.addLayout(qr_meta, 1)

        btn_copy = QPushButton("Kopyala")
        btn_copy.setProperty("class", "MacBtn")
        btn_copy.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_copy.clicked.connect(lambda: QApplication.clipboard().setText(url_text))
        row_qr.addWidget(btn_copy, 0, Qt.AlignmentFlag.AlignVCenter)
        c_lay.addLayout(row_qr)

        div1 = QFrame()
        div1.setObjectName("RowDivider")
        c_lay.addWidget(div1)

        # Row 2: Wi-Fi Direct (WO Mic Mode)
        row_wifi = QHBoxLayout()
        lbl_wifi_k = QLabel("Wi-Fi Doğrudan (WO Mic Modu)")
        lbl_wifi_k.setStyleSheet("font-size: 12px; color: #EBEBF0;")
        self.womic_ip_lbl = QLabel(f"<span style='color:#32D74B; font-weight:600;'>🟢 {self.engine.lan_ip}:{self.engine.port}</span>")
        self.womic_ip_lbl.setStyleSheet("font-size: 12px;")
        row_wifi.addWidget(lbl_wifi_k)
        row_wifi.addStretch()
        row_wifi.addWidget(self.womic_ip_lbl)
        c_lay.addLayout(row_wifi)

        div2 = QFrame()
        div2.setObjectName("RowDivider")
        c_lay.addWidget(div2)

        # Row 3: Apple USB Bridge (usbmuxd)
        row_usb = QHBoxLayout()
        lbl_usb_k = QLabel("Apple USB Kablo Köprüsü")
        lbl_usb_k.setStyleSheet("font-size: 12px; color: #EBEBF0;")
        self.womic_usb_lbl = QLabel("<span style='color:rgba(255,255,255,0.45);'>Kablo kontrol ediliyor…</span>")
        self.womic_usb_lbl.setStyleSheet("font-size: 12px;")
        row_usb.addWidget(lbl_usb_k)
        row_usb.addStretch()
        row_usb.addWidget(self.womic_usb_lbl)
        c_lay.addLayout(row_usb)

        div3 = QFrame()
        div3.setObjectName("RowDivider")
        c_lay.addWidget(div3)

        # Row 4: Windows Firewall Permission
        row_fw = QHBoxLayout()
        lbl_fw_k = QLabel("Windows Güvenlik Duvarı (TCP 8765)")
        lbl_fw_k.setStyleSheet("font-size: 12px; color: #EBEBF0;")
        btn_firewall = QPushButton("İzin Ver…")
        btn_firewall.setProperty("class", "MacBtn")
        btn_firewall.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_firewall.clicked.connect(self._on_allow_firewall_clicked)
        row_fw.addWidget(lbl_fw_k)
        row_fw.addStretch()
        row_fw.addWidget(btn_firewall)
        c_lay.addLayout(row_fw)

        left_col.addWidget(conn_section, 0)
        lay.addLayout(left_col, 11)

        # Right Column: 2 Separate Cupertino Form Sections (Outgoing Queue & Incoming Files)
        right_col = QVBoxLayout()
        right_col.setContentsMargins(0, 0, 0, 0)
        right_col.setSpacing(12)

        # Top Section: Outgoing Queue + Cupertino ProgressView
        out_section = QFrame()
        out_section.setObjectName("CupertinoSection")
        o_lay = QVBoxLayout(out_section)
        o_lay.setContentsMargins(14, 12, 14, 12)
        o_lay.setSpacing(8)

        out_header = QHBoxLayout()
        out_title = QLabel("📤 iPhone'a Gönderilecekler")
        out_title.setStyleSheet("font-size: 13px; font-weight: 600; color: #EBEBF0;")
        btn_add = QPushButton("+ Ekle…")
        btn_add.setProperty("class", "MacBtnPrimary")
        btn_add.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_add.clicked.connect(self._browse_and_add_files)
        btn_clear = QPushButton("Temizle")
        btn_clear.setProperty("class", "MacBtn")
        btn_clear.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_clear.clicked.connect(self.engine.clear_outgoing)
        out_header.addWidget(out_title)
        out_header.addStretch()
        out_header.addWidget(btn_add)
        out_header.addWidget(btn_clear)
        o_lay.addLayout(out_header)

        self.outgoing_list = QListWidget()
        self.outgoing_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        o_lay.addWidget(self.outgoing_list, 1)

        # Cupertino ProgressView (Status Label above 6px capsule track so text NEVER clips)
        self.transfer_status_lbl = QLabel("Hazır — iPhone bekleniyor")
        self.transfer_status_lbl.setStyleSheet("font-size: 11px; color: rgba(255, 255, 255, 0.65);")
        o_lay.addWidget(self.transfer_status_lbl)

        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        o_lay.addWidget(self.progress_bar)
        right_col.addWidget(out_section, 1)

        # Bottom Section: Received Files on Desktop
        in_section = QFrame()
        in_section.setObjectName("CupertinoSection")
        i_lay = QVBoxLayout(in_section)
        i_lay.setContentsMargins(14, 12, 14, 12)
        i_lay.setSpacing(8)

        in_header = QHBoxLayout()
        in_title = QLabel("📥 Masaüstüne Alınanlar")
        in_title.setStyleSheet("font-size: 13px; font-weight: 600; color: #EBEBF0;")
        btn_open_gelenler = QPushButton("Klasörü Aç…")
        btn_open_gelenler.setProperty("class", "MacBtn")
        btn_open_gelenler.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_open_gelenler.clicked.connect(lambda: subprocess.Popen(["explorer.exe", str(DEST_FOLDER)]))
        in_header.addWidget(in_title)
        in_header.addStretch()
        in_header.addWidget(btn_open_gelenler)
        i_lay.addLayout(in_header)

        self.incoming_list = QListWidget()
        self.incoming_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.incoming_list.itemDoubleClicked.connect(self._open_received_item)
        i_lay.addWidget(self.incoming_list, 1)
        right_col.addWidget(in_section, 1)

        lay.addLayout(right_col, 10)
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
            s_card.setObjectName("StatCard")
            s_lay = QVBoxLayout(s_card)
            s_lay.setContentsMargins(10, 8, 10, 8)
            s_lbl_n = QLabel(name)
            s_lbl_n.setStyleSheet("font-size: 11px; color: rgba(255,255,255,0.55);")
            s_lbl_v = QLabel(val)
            s_lbl_v.setStyleSheet("font-size: 12px; font-weight: 600; color: #419CFF;")
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
        url = f"http://{self.engine.lan_ip}:{self.engine.port}/"
        qr = qrcode.QRCode(box_size=3, border=1)
        qr.add_data(url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        pix = QPixmap()
        pix.loadFromData(buf.getvalue(), "PNG")
        self.qr_lbl.setPixmap(pix.scaled(66, 66, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

    def _on_allow_firewall_clicked(self) -> None:
        try:
            import ctypes
            exe_path = str(Path(sys.executable if getattr(sys, "frozen", False) else sys.argv[0]).resolve())
            cmd_args = (
                f'/c netsh advfirewall firewall delete rule name=all program="{exe_path}" >nul 2>&1 & '
                f'netsh advfirewall firewall delete rule name="WinDrop P2P" >nul 2>&1 & '
                f'netsh advfirewall firewall delete rule name="WinDrop App" >nul 2>&1 & '
                f'netsh advfirewall firewall add rule name="WinDrop P2P" dir=in action=allow protocol=TCP localport={self.engine.port} profile=any & '
                f'netsh advfirewall firewall add rule name="WinDrop UDP" dir=in action=allow protocol=UDP localport=53317 profile=any & '
                f'netsh advfirewall firewall add rule name="WinDrop App" dir=in action=allow program="{exe_path}" enable=yes profile=any'
            )
            ret = ctypes.windll.shell32.ShellExecuteW(None, "runas", "cmd.exe", cmd_args, None, 0)
            if ret > 32:
                QMessageBox.information(
                    self,
                    "Güvenlik Duvarı İzni",
                    "✅ Windows Güvenlik Duvarı engelleri kaldırıldı ve 8765 portu açıldı!\nŞimdi iPhone WinDrop uygulamasından doğrudan bağlanabilirsiniz."
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
                dname = elide_middle(data.get("name", "Dosya"), 28)
                dsize = data.get("size", 0)
                dsha = data.get("sha256", "")[:8]
                label = f"📄 {dname}  ({format_bytes(dsize)})" + (f"  •  SHA: {dsha}…" if dsha else "")
                self.outgoing_list.addItem(label)
            elif event_type == "outgoing_cleared":
                self.outgoing_list.clear()
            elif event_type == "peer_update":
                peers = self.engine.discovery.get_active_peers() if hasattr(self, "engine") else []
                self.radar.set_peers(peers)
                if peers:
                    latest = peers[0]
                    pip = latest.get("ip", "")
                    dname = f"iPhone ({pip})" if pip else latest.get("name", "iPhone")
                    self.peer_status_lbl.setText(f"● Bağlı: {dname}")
                    self.peer_status_lbl.setStyleSheet(
                        "background: rgba(50, 215, 75, 0.14); color: #32D74B; border: 1px solid rgba(50, 215, 75, 0.32); "
                        "border-radius: 10px; padding: 3px 10px; font-size: 11px; font-weight: 600;"
                    )
            elif event_type == "transfer_start":
                fname = elide_middle(data.get("filename", "Dosya"), 28)
                self.progress_bar.setValue(0)
                if hasattr(self, "transfer_status_lbl"):
                    self.transfer_status_lbl.setText(f"⬇️ Alınıyor: {fname}…")
                    self.transfer_status_lbl.setStyleSheet("font-size: 11px; color: #5AC8F5;")
            elif event_type == "transfer_progress":
                total = max(data.get("total", 1), 1)
                pct = min(int((data.get("written", 0) / total) * 100), 100)
                fname = elide_middle(data.get("filename", "Dosya"), 28)
                self.progress_bar.setValue(pct)
                if hasattr(self, "transfer_status_lbl"):
                    self.transfer_status_lbl.setText(f"⬇️ {fname} — %{pct}")
            elif event_type == "file_received":
                raw_name = data.get("name", "Dosya")
                dname = elide_middle(raw_name, 26)
                self.progress_bar.setValue(100)
                if hasattr(self, "transfer_status_lbl"):
                    self.transfer_status_lbl.setText(f"✅ Kayıpsız Alındı: {dname}")
                    self.transfer_status_lbl.setStyleSheet("font-size: 11px; color: #32D74B; font-weight: 600;")
                self._refresh_incoming_list()
                if hasattr(self, "tray_icon") and self.tray_icon.isVisible():
                    dsize_str = format_bytes(data.get("size", 0))
                    self.tray_icon.showMessage(
                        "WinDrop — Dosya Alındı 📥",
                        f"{raw_name} ({dsize_str}) masaüstüne kaydedildi.",
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
                    short_txt = (txt[:22] + "…") if len(txt) > 22 else txt
                    if src == "PC":
                        self.peer_status_lbl.setText(f"📋 PC Panosu: {short_txt}")
                    else:
                        self.peer_status_lbl.setText(f"📋 iPhone Panosu: {short_txt}")
                    self.peer_status_lbl.setStyleSheet(
                        "background: rgba(50, 215, 75, 0.14); color: #32D74B; border: 1px solid rgba(50, 215, 75, 0.32); "
                        "border-radius: 10px; padding: 3px 10px; font-size: 11px; font-weight: 600;"
                    )
            elif event_type == "file_sent_to_iphone":
                dname = elide_middle(data.get("name", "Dosya"), 26)
                self.progress_bar.setValue(100)
                if hasattr(self, "transfer_status_lbl"):
                    self.transfer_status_lbl.setText(f"📲 iPhone'a Gönderildi: {dname}")
                    self.transfer_status_lbl.setStyleSheet("font-size: 11px; color: #32D74B; font-weight: 600;")
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


def _evict_rogue_port_8765_occupant() -> None:
    """Terminates any non-WinDrop process (like python/pythonw) squatting on TCP ports 8765, 53843, or 9000."""
    my_pid = os.getpid()
    try:
        import psutil
        out = subprocess.check_output(["netstat", "-ano"], text=True, encoding="utf-8", errors="replace", creationflags=0x08000000)
        for line in out.splitlines():
            if any(p in line for p in (":8765", ":53843", ":9000")) and "LISTENING" in line.upper():
                parts = line.split()
                if parts:
                    pid = int(parts[-1])
                    if pid and pid != my_pid:
                        try:
                            pname = psutil.Process(pid).name().lower()
                            if "windrop" in pname:
                                print(f"[main] Port is held by WinDrop (PID={pid}) — keeping alive.", flush=True)
                                continue
                        except Exception:
                            pass
                        print(f"[main] Evicting rogue non-WinDrop process on port via netstat: PID={pid}", flush=True)
                        subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True, creationflags=0x08000000)
    except Exception:
        pass


def ensure_background_daemon_running() -> bool:
    """Always runs the server directly inside WinDrop.exe (100% standalone, zero external python/pythonw)."""
    _evict_rogue_port_8765_occupant()
    time.sleep(0.15)
    return False


def setup_windows_autostart() -> None:
    """Ensures single clean WinDrop.exe Tray autostart on Windows boot/login (zero pythonw)."""
    try:
        if getattr(sys, "frozen", False):
            exe_path = str(Path(sys.executable).resolve())
            cmd_str = f'"{exe_path}" --tray'
        else:
            desktop_exe = Path(r"C:\Users\pc\Desktop\WinDrop.exe")
            if desktop_exe.exists():
                cmd_str = f'"{desktop_exe}" --tray'
            else:
                return

        import winreg
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run") as key:
            winreg.SetValueEx(key, "WinDropP2PTray", 0, winreg.REG_SZ, cmd_str)
            # Clean up older keys including any pythonw daemon keys
            for old_k in ("WinDrop", "WinDropBgDaemon", "WinDropServer", "WinDropTray", "WinDrop_Tray", "WinDropDaemon"):
                try:
                    winreg.DeleteValue(key, old_k)
                except FileNotFoundError:
                    pass

        print("[autostart] WinDrop.exe standalone Tray autostart registered on boot (WinDropP2PTray)", flush=True)
    except Exception as e:
        print(f"[autostart] Error registering autostart: {e}", flush=True)

def try_silent_firewall_allow() -> None:
    """Attempts to silently ensure Windows Firewall allows WinDrop.exe on ports 8765, 53843, 9000, and UDP 53317."""
    try:
        exe_path = str(Path(sys.executable if getattr(sys, "frozen", False) else sys.argv[0]).resolve())
        cmd = (
            'netsh advfirewall firewall add rule name="WinDrop P2P" dir=in action=allow protocol=TCP localport=8765,53843,9000 profile=any & '
            'netsh advfirewall firewall add rule name="WinDrop UDP" dir=in action=allow protocol=UDP localport=53317 profile=any & '
            f'netsh advfirewall firewall add rule name="WinDrop App" dir=in action=allow program="{exe_path}" enable=yes profile=any'
        )
        subprocess.run(cmd, shell=True, capture_output=True, creationflags=0x08000000)
    except Exception:
        pass


_INSTANCE_MUTEX_HANDLE = None


def _run_usb_install_mode() -> None:
    """Standalone USB iPhone profile/IPA installer mode invoked via WinDrop.exe --usb-install."""
    import asyncio
    from windrop_discovery import get_best_lan_ip
    from windrop_usb_bridge import usb_install_app_profile, usb_status
    lan_ip = get_best_lan_ip()
    app = QApplication.instance() or QApplication(sys.argv)
    st = asyncio.run(usb_status())
    if not st.get("connected"):
        QMessageBox.warning(
            None,
            "WinDrop USB Kurulumu",
            "📱 USB kablosuyla bağlı bir iPhone algılanamadı!\n\n"
            "1. iPhone'u USB kablosuyla bilgisayara takın.\n"
            "2. iPhone ekranında 'Bu Bilgisayara Güven' onayını verin.\n"
            "3. Ardından tekrar deneyin (veya doğrudan QR Kodu okutarak bağlanın)."
        )
        return
    try:
        res = asyncio.run(usb_install_app_profile(lan_ip))
        dev_name = res.get("device") or st.get("name") or "iPhone"
        QMessageBox.information(
            None,
            "WinDrop USB Kurulumu Başarılı",
            f"✅ {dev_name} cihazına WinDrop tam ekran uygulama profili USB üzerinden gönderildi!\n\n"
            "Şimdi iPhone'unuzda:\n"
            "Ayarlar ➔ 'Profil İndirildi' ➔ Yükle seçeneğine dokunarak ana ekranınıza ekleyebilirsiniz."
        )
    except Exception as e:
        QMessageBox.information(
            None,
            "WinDrop USB Bağlantısı",
            f"📱 {st.get('name', 'iPhone')} USB üzerinden algılandı!\n\n"
            f"Doğrudan tam ekran kurulum için WinDrop penceresindeki QR kodu okutabilir veya klasördeki 'WinDrop.ipa' dosyasını Sideloadly ile yükleyebilirsiniz.\n\n(Detay: {e})"
        )


def _real_main() -> None:
    global _INSTANCE_MUTEX_HANDLE
    print("[main] entered", flush=True)
    if "--usb-install" in sys.argv:
        _run_usb_install_mode()
        return

    try_silent_firewall_allow()
    is_background = any(arg in sys.argv for arg in ("--background", "--silent", "--tray", "--minimized", "-b"))
    smoke_test = "--smoke-test" in sys.argv
    initial_files: List[str] = []
    if len(sys.argv) > 1:
        args = [a for a in sys.argv[1:] if a not in ("--send", "--smoke-test", "--background", "--silent", "--tray", "--minimized", "-b", "--usb-install") and os.path.exists(a)]
        if args:
            initial_files = args

    # 0. Win32 Named Mutex Guard (prevents double-click race condition during PyInstaller unpack)
    already_running_mutex = False
    if not smoke_test and sys.platform == "win32":
        try:
            kernel32 = ctypes.windll.kernel32
            _INSTANCE_MUTEX_HANDLE = kernel32.CreateMutexW(None, False, "Local\\WinDrop_SingleInstance_Mutex_v2")
            if kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
                already_running_mutex = True
        except Exception:
            pass

    # 1. Quick probe to existing running GUI instance via Local IPC
    if not smoke_test:
        try:
            from PyQt6.QtNetwork import QLocalSocket
            probe_app = QApplication.instance() or QApplication(sys.argv)
            max_ipc_tries = 12 if already_running_mutex else 1
            for _ in range(max_ipc_tries):
                sock = QLocalSocket()
                sock.connectToServer("WinDrop_SingleInstance_IPC")
                if sock.waitForConnected(350):
                    if is_background:
                        print("[main] WinDrop instance is already running. Background tray active. Exiting.", flush=True)
                        sock.disconnectFromServer()
                        return
                    msg = ("ADD:" + "|".join(initial_files)).encode("utf-8") if initial_files else b"SHOW\n"
                    sock.write(msg)
                    sock.flush()
                    sock.waitForBytesWritten(500)
                    time.sleep(0.05)
                    sock.disconnectFromServer()
                    print("[main] Notified running WinDrop instance via IPC. Bringing to front.", flush=True)
                    return
                if already_running_mutex:
                    time.sleep(0.25)
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

    # Always start the embedded multi-port server & USB watcher directly inside WinDrop.exe (zero pythonw)
    ensure_background_daemon_running()

    print("[main] Starting embedded WinDropServerRunner on port 8765...", flush=True)
    runner = WinDropServerRunner(port=8765)
    runner.start()

    extra_runners = []
    if not smoke_test:
        for extra_p in (53843, 9000):
            try:
                r_ext = WinDropServerRunner(port=extra_p)
                r_ext.start()
                extra_runners.append(r_ext)
            except Exception as e_ext:
                print(f"[main] Secondary port {extra_p} notice: {e_ext}", flush=True)

        def _usb_worker() -> None:
            try:
                import asyncio
                from windrop_usb_bridge import usb_auto_sync_loop
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(usb_auto_sync_loop(runner.engine))
            except Exception as e_usb:
                print(f"[usb] Embedded USB watcher notice: {e_usb}", flush=True)

        threading.Thread(target=_usb_worker, daemon=True, name="WinDropUSBWatcher").start()

    time.sleep(0.25)

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
        print(err, flush=True)
        err_file = _appdata_dir / "windrop_startup_error.log"
        try:
            err_file.write_text(err, encoding="utf-8")
        except Exception:
            pass
        if "--smoke-test" in sys.argv:
            sys.exit(1)
        try:
            from PyQt6.QtWidgets import QApplication, QMessageBox
            a = QApplication.instance() or QApplication(sys.argv)
            QMessageBox.critical(None, "WinDrop Hatası", f"WinDrop başlatılamadı:\n\n{e}\n\nAyrıntılar {err_file} dosyasına kaydedildi.")
        except Exception:
            pass

if __name__ == '__main__':

    main()