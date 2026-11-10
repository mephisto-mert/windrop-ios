# -*- coding: utf-8 -*-

import asyncio

import hashlib

import io

import json

import mimetypes

import os

import platform

import shutil

import sys

import tempfile

import threading

import time

import urllib.parse

import uuid

import zipfile
import logging
from pathlib import Path
from typing import Callable, Dict, List, Optional

logger = logging.getLogger("windrop.server")



import uvicorn

from fastapi import FastAPI, File, Request, UploadFile, WebSocket, WebSocketDisconnect

from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, Response

from starlette.background import BackgroundTask



from windrop_discovery import WinDropDiscoveryService, get_best_lan_ip


def enable_sleep_prevention() -> None:
    """Keeps network & PC awake so the background server never drops connection."""
    try:
        import ctypes
        ES_CONTINUOUS = 0x80000000
        ES_SYSTEM_REQUIRED = 0x00000001
        ES_AWAYMODE_REQUIRED = 0x00000040
        ret = ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_AWAYMODE_REQUIRED)
        if ret == 0:
            ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)
        print("[power] Sleep prevention enabled (ES_SYSTEM_REQUIRED | ES_AWAYMODE)", flush=True)
    except Exception as e:
        print(f"[power] Warning setting execution state: {e}", flush=True)




if sys.stdout is None:

    sys.stdout = open(os.devnull, "w", encoding="utf-8")

elif hasattr(sys.stdout, "reconfigure"):

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")



if sys.stderr is None:

    sys.stderr = open(os.devnull, "w", encoding="utf-8")

elif hasattr(sys.stderr, "reconfigure"):

    sys.stderr.reconfigure(encoding="utf-8", errors="replace")



# Ensure iOS specific Apple lossless MIME types are registered

mimetypes.add_type("image/heic", ".heic")

mimetypes.add_type("image/heif", ".heif")

mimetypes.add_type("image/x-adobe-dng", ".dng")

mimetypes.add_type("video/quicktime", ".mov")

mimetypes.add_type("audio/mp4", ".m4a")





def compute_file_sha256(filepath: Path, chunk_size: int = 4 * 1024 * 1024) -> str:

    h = hashlib.sha256()

    with open(filepath, "rb") as f:

        while True:

            chunk = f.read(chunk_size)

            if not chunk:

                break

            h.update(chunk)

    return h.hexdigest()





def is_local_ip(ip: Optional[str]) -> bool:
    if not ip:
        return False
    clean_ip = ip.strip()
    return clean_ip in ("127.0.0.1", "::1", "localhost", "testclient")


def is_local_request(request: Request) -> bool:
    """Restricts access strictly to the local PC host (127.0.0.1 / ::1).
    Prevents external proxy / Cloudflare tunnel spoofing via anti-masquerade header checks
    and blocks cross-site CSRF from external browser tabs."""
    if not request or not request.client:
        return False
    client_ip = request.client.host
    if not is_local_ip(client_ip):
        return False
    headers = request.headers
    if headers.get("cf-connecting-ip") or headers.get("x-forwarded-for") or headers.get("x-real-ip"):
        return False
    if headers.get("sec-fetch-site") == "cross-site":
        return False
    return True


def is_local_websocket(websocket: WebSocket) -> bool:
    """Restricts access strictly to local PC host (127.0.0.1 / ::1) over WebSockets."""
    if not websocket or not websocket.client:
        return False
    client_ip = websocket.client.host
    if not is_local_ip(client_ip):
        return False
    headers = websocket.headers
    if headers.get("cf-connecting-ip") or headers.get("x-forwarded-for") or headers.get("x-real-ip"):
        return False
    return True


class WinDropEngine:

    """Core lossless file transfer state, SHA-256 verifier, and event dispatcher."""



    def __init__(self, port: int = 8765, receive_dir: Optional[Path] = None):

        self.port = port

        self.pc_name = platform.node() or "Windows-PC"

        self.lan_ip = get_best_lan_ip()

        home = Path(os.path.expanduser("~"))
        desktop_candidates = [
            home / "Desktop",
            home / "Masaüstü",
            home / "OneDrive" / "Desktop",
            home / "OneDrive" / "Masaüstü",
            home,
        ]
        desktop = next((d for d in desktop_candidates if d.exists()), home)

        target_dir = receive_dir or (desktop / "WinDrop_Gelenler")
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
            self.receive_dir = target_dir
        except Exception:
            fallback_dir = Path(os.environ.get("LOCALAPPDATA", tempfile.gettempdir())) / "WinDrop" / "WinDrop_Gelenler"
            fallback_dir.mkdir(parents=True, exist_ok=True)
            self.receive_dir = fallback_dir



        self.outgoing_files: Dict[str, Dict] = {}
        self.received_history: List[Dict] = []
        self.clipboard_history: List[Dict] = []
        self.last_clipboard_text: str = ""
        self.ws_clients: List[WebSocket] = []
        self.event_listeners: List[Callable[[str, Dict], None]] = []
        self.show_gui_callback: Optional[Callable[[], None]] = None
        self._local_tokens: Dict[str, Dict] = {}

        self.discovery = WinDropDiscoveryService(
            port=self.port,
            device_name=f"{self.pc_name} (WinDrop)",
            on_peer_update=lambda peer: self._emit("peer_update", peer),
        )

    def add_received_record(self, record: dict) -> None:
        self.received_history.append(record)
        if len(self.received_history) > 100:
            self.received_history = self.received_history[-100:]



    def add_listener(self, cb: Callable[[str, Dict], None]) -> None:

        self.event_listeners.append(cb)



    def _emit(self, event_type: str, payload: Dict) -> None:

        for cb in list(self.event_listeners):

            try:

                cb(event_type, payload)

            except Exception:

                pass




    def get_pc_clipboard_text(self) -> str:
        try:
            import pyperclip
            return pyperclip.paste() or ""
        except Exception:
            return ""

    def set_pc_clipboard_text(self, text: str, source: str = "iPhone") -> dict:
        if not text:
            return {}
        # ONLY write to Windows clipboard if the text came from iPhone / external!
        # If it originated on PC, it is ALREADY on the Windows clipboard - touching it corrupts Windows paste!
        if source != "PC":
            try:
                import pyperclip
                pyperclip.copy(text)
            except Exception:
                pass
        self.last_clipboard_text = text
        is_url = bool(text.startswith("http://") or text.startswith("https://") or ("://" in text and " " not in text))
        item = {
            "id": str(uuid.uuid4())[:8],
            "text": text,
            "source": source,
            "time": time.strftime("%H:%M:%S"),
            "timestamp": time.time(),
            "preview": text,
            "length": len(text),
            "is_url": is_url
        }
        if not self.clipboard_history or self.clipboard_history[0].get("text") != text:
            self.clipboard_history.insert(0, item)
            if len(self.clipboard_history) > 30:
                self.clipboard_history = self.clipboard_history[:30]
        self._emit("clipboard_received", item)
        return item

    def set_receive_dir(self, new_dir: Path) -> None:

        new_dir.mkdir(parents=True, exist_ok=True)

        self.receive_dir = new_dir

        self._emit("config_changed", {"receive_dir": str(self.receive_dir)})



    def add_outgoing_path(self, path_str: str) -> Optional[Dict]:

        p = Path(path_str)

        if not p.exists():

            return None



        # If a directory is dropped, create a zero-compression (ZIP_STORED) archive so 0 bits are altered

        if p.is_dir():

            tmp_zip = Path(tempfile.gettempdir()) / f"{p.name}_LosslessBundle.zip"

            with zipfile.ZipFile(tmp_zip, "w", compression=zipfile.ZIP_STORED) as zf:

                for root, _, files in os.walk(p):

                    for fn in files:

                        full_f = Path(root) / fn

                        rel_f = full_f.relative_to(p.parent)

                        zf.write(full_f, arcname=str(rel_f))

            p = tmp_zip



        file_id = uuid.uuid4().hex[:12]

        sha256_hex = compute_file_sha256(p)

        mime, _ = mimetypes.guess_type(str(p))

        item = {

            "id": file_id,

            "name": p.name,

            "filename": p.name,

            "path": str(p.resolve()),

            "size": p.stat().st_size,

            "sha256": sha256_hex,

            "mime": mime or "application/octet-stream",

            "added_at": time.strftime("%H:%M:%S"),

        }

        self.outgoing_files[file_id] = item

        self._emit("outgoing_added", item)

        return item



    def clear_outgoing(self) -> None:

        self.outgoing_files.clear()

        self._emit("outgoing_cleared", {})



    def resolve_safe_dest(self, filename: str) -> Path:
        import re
        clean = filename.replace("\\", "/").strip().strip("./ ")
        clean = os.path.basename(clean)
        # Strip trailing dots, spaces, and NTFS Alternate Data Streams (::$DATA)
        clean = clean.split(":")[0].rstrip(". ")
        # Sanitize Windows illegal characters < > " | ? * and control chars
        clean = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', clean).strip(". ")
        if not clean or clean in (".", ".."):
            clean = f"iPhone_Dosya_{int(time.time())}"

        # Complete Windows reserved device names regex
        if re.match(r"^(CON|PRN|AUX|NUL|CLOCK\$|COM[1-9]|LPT[1-9])(\..*)?$", clean, re.IGNORECASE):
            clean = f"safe_{clean}"

        # Quarantine dangerous executable extensions
        ext = Path(clean).suffix.lower()
        dangerous_exts = {
            ".exe", ".bat", ".cmd", ".vbs", ".ps1", ".scr", ".pif", ".com",
            ".hta", ".cpl", ".reg", ".jar", ".dll", ".sys", ".lnk", ".msi",
            ".msp", ".wsf", ".wsh", ".scf", ".py", ".pyw", ".vbe", ".jse",
            ".ws", ".wsc", ".inf", ".appref-ms", ".application", ".gadget",
            ".msc", ".settingcontent-ms", ".psm1", ".psd1", ".iso", ".img",
            ".url", ".theme", ".themepack", ".vhd", ".vhdx"
        }
        if ext in dangerous_exts:
            clean = f"{clean}.quarantine"



        dest = (self.receive_dir / clean).resolve()

        if not dest.is_relative_to(self.receive_dir.resolve()):

            dest = self.receive_dir / f"sanitized_{int(time.time())}.quarantine"



        if not dest.exists():

            return dest

        stem = dest.stem

        suffix = dest.suffix

        counter = 1

        while True:

            candidate = self.receive_dir / f"{stem}_{counter}{suffix}"

            if not candidate.exists():

                return candidate

            counter += 1





def make_clean_closed_json(payload: dict, status_code: int = 200) -> Response:

    """Builds an explicit-length, Connection: close HTTP response so iOS Shortcuts never hangs at 50%."""

    body = json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode('utf-8')

    return Response(

        content=body,

        status_code=status_code,

        media_type="application/json; charset=utf-8",

        headers={

            "Content-Length": str(len(body)),

            "Connection": "close",

            "Content-Encoding": "identity",

            "Access-Control-Allow-Origin": "*",

            "Access-Control-Allow-Headers": "*",

            "Access-Control-Allow-Methods": "*",

            "Cache-Control": "no-cache, no-store, must-revalidate",

        }

    )





def capture_desktop_png_bytes() -> bytes:

    try:

        from remote_desktop_engine import capture_png_frame

        png = capture_png_frame()

        if png:

            return png

    except Exception:

        pass



    try:

        import ctypes

        from PIL import ImageGrab, Image

        user32 = ctypes.windll.user32

        try:

            hdesk = user32.OpenInputDesktop(0, False, 0x01FF)

            if hdesk:

                user32.SetThreadDesktop(hdesk)

        except Exception:

            pass

        try:

            im = ImageGrab.grab()

            if im and im.size[0] > 0 and im.size[1] > 0:

                out_io = io.BytesIO()

                im.convert('RGB').save(out_io, format='PNG')

                return out_io.getvalue()

        except Exception:

            pass



        # Fallback to direct GDI

        from ctypes import wintypes

        gdi32 = ctypes.windll.gdi32

        user32.SetProcessDPIAware()

        w = user32.GetSystemMetrics(0)

        h = user32.GetSystemMetrics(1)

        hwnd_desk = user32.GetDesktopWindow()

        desk_dc = user32.GetDC(hwnd_desk)

        img_dc = gdi32.CreateCompatibleDC(desk_dc)

        bmp = gdi32.CreateCompatibleBitmap(desk_dc, w, h)

        gdi32.SelectObject(img_dc, bmp)

        gdi32.BitBlt(img_dc, 0, 0, w, h, desk_dc, 0, 0, 0x00CC0020 | 0x40000000)



        class BITMAPINFOHEADER(ctypes.Structure):

            _fields_ = [

                ('biSize', wintypes.DWORD),

                ('biWidth', wintypes.LONG),

                ('biHeight', wintypes.LONG),

                ('biPlanes', wintypes.WORD),

                ('biBitCount', wintypes.WORD),

                ('biCompression', wintypes.DWORD),

                ('biSizeImage', wintypes.DWORD),

                ('biXPelsPerMeter', wintypes.LONG),

                ('biYPelsPerMeter', wintypes.LONG),

                ('biClrUsed', wintypes.DWORD),

                ('biClrImportant', wintypes.DWORD)

            ]



        class BITMAPINFO(ctypes.Structure):

            _fields_ = [('bmiHeader', BITMAPINFOHEADER), ('bmiColors', wintypes.DWORD * 3)]



        bmi = BITMAPINFO()

        bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)

        bmi.bmiHeader.biWidth = w

        bmi.bmiHeader.biHeight = -h

        bmi.bmiHeader.biPlanes = 1

        bmi.bmiHeader.biBitCount = 32

        bmi.bmiHeader.biCompression = 0



        buf = (ctypes.c_char * (w * h * 4))()

        gdi32.GetDIBits(img_dc, bmp, 0, h, ctypes.byref(buf), ctypes.byref(bmi), 0)

        gdi32.DeleteObject(bmp)

        gdi32.DeleteDC(img_dc)

        user32.ReleaseDC(hwnd_desk, desk_dc)



        im = Image.frombuffer('RGBA', (w, h), buf, 'raw', 'BGRA', 0, 1).convert('RGB')

        out_io = io.BytesIO()

        im.save(out_io, format='PNG')

        return out_io.getvalue()

    except Exception as e:

        print("[!] capture_desktop error:", e)

        return b""






def ensure_pyvncserver_running():
    import socket
    import subprocess
    s = socket.socket()
    s.settimeout(0.3)
    try:
        s.connect(('127.0.0.1', 5901))
        s.close()
        return
    except Exception:
        pass

    script_dir = os.path.dirname(os.path.abspath(__file__))
    pyvnc_src = os.path.join(script_dir, "PyVNCServer", "src")
    config_path = os.path.join(script_dir, "windrop_vnc_config.toml")
    if os.path.exists(config_path) and os.path.exists(pyvnc_src):
        env = os.environ.copy()
        env["PYTHONPATH"] = (pyvnc_src + os.pathsep + env.get("PYTHONPATH", "")).strip(os.pathsep)
        creationflags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
        try:
            subprocess.Popen(
                [sys.executable, "-m", "pyvncserver", "serve", "--config", config_path, "--log-level", "WARNING"],
                env=env,
                creationflags=creationflags
            )
        except Exception as e:
            logger.warning(f"[VNC] Could not spawn PyVNCServer: {e}")


def create_windrop_app(engine: WinDropEngine) -> FastAPI:

    from fastapi.middleware.cors import CORSMiddleware

    app = FastAPI(title="WinDrop Lossless AirDrop Engine", version="2.2.0")

    # Mount official noVNC static web client
    novnc_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "PyVNCServer", "web", "noVNC")
    if os.path.exists(novnc_dir):
        from starlette.staticfiles import StaticFiles
        app.mount("/novnc", StaticFiles(directory=novnc_dir, html=True), name="novnc")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def log_incoming_requests(request: Request, call_next):
        client = request.client.host if request.client else "unknown"
        p = request.url.path
        if not (p.startswith("/api/clipboard") or p.startswith("/api/state") or p.startswith("/favicon")):
            print(f"[HTTP {client}] {request.method} {p}", flush=True)
        return await call_next(request)

    def resolve_template_content():
        candidates = [
            Path(r"c:\Users\pc\Documents\projelerim\windrop_airdrop\templates\ios_radar.html"),
            Path(__file__).parent / "templates" / "ios_radar.html",
            Path(getattr(sys, '_MEIPASS', '')) / "templates" / "ios_radar.html",
            Path(sys.executable).parent / "templates" / "ios_radar.html",
            Path.cwd() / "templates" / "ios_radar.html",
        ]
        for c in candidates:
            if c.exists():
                html = c.read_text(encoding="utf-8")
                live_host = f"{engine.lan_ip}:{engine.port}"
                html = html.replace("192.168.1.158:8765", live_host)
                html = html.replace('placeholder="192.168.1.158"', f'placeholder="{engine.lan_ip}" value="{engine.lan_ip}"')
                html = html.replace("DESKTOP-EIJNT5O", engine.pc_name)
                return html
        return "<html><body><h1>WinDrop Ready</h1></body></html>"

    template_path = Path(__file__).parent / "templates" / "ios_radar.html"



    @app.get("/pairing-qr")

    async def get_pairing_qr_image():

        from fastapi.responses import FileResponse, Response

        qr_file = Path(__file__).parent / "pairing_qr.png"

        if qr_file.exists():

            return FileResponse(path=str(qr_file), media_type="image/png")

        return Response(content="QR not generated", status_code=404)



    @app.get("/manifest.json")

    async def pwa_manifest_json():

        return JSONResponse({

            "name": "WinDrop Remote Desktop",

            "short_name": "WinDrop",

            "start_url": "./",

            "scope": "./",

            "display": "fullscreen",

            "display_override": ["fullscreen", "standalone", "window-controls-overlay"],

            "orientation": "any",

            "background_color": "#000000",

            "theme_color": "#000000",

            "icons": [{"src": "./icon-180.png", "sizes": "180x180", "type": "image/png"}],

        })



    @app.get("/icon-180.png")

    async def pwa_icon_png():

        from fastapi.responses import Response

        from build_ios_ipa_bundle import create_app_icon

        return Response(content=create_app_icon(180), media_type="image/png")



    @app.get("/sw.js")
    async def service_worker_js():
        sw_code = """
self.addEventListener('install', (e) => {
  self.skipWaiting();
});
self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.map((k) => caches.delete(k)))).then(() => self.registration.unregister())
  );
});
"""
        return HTMLResponse(content=sw_code.strip(), media_type="application/javascript", headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"})



    @app.get("/api/download-portable-exe")

    async def download_portable_exe():

        exe_candidates = [

            Path(r"C:\Users\pc\Desktop\WinDrop_Portable.exe"),

            Path(r"C:\Users\pc\Desktop\WinDrop.exe"),

        ]

        for p in exe_candidates:

            if p.exists():

                return FileResponse(path=str(p), filename="WinDrop_Portable.exe", media_type="application/octet-stream")

        return JSONResponse({"error": "Portable EXE not found"}, status_code=404)

    
    @app.get("/WinDrop.mobileconfig")
    @app.get("/api/download/mobileconfig")
    async def get_mobileconfig_profile():
        """Serves dynamic iOS WebClip .mobileconfig profile tailored to the current PC's LAN IP."""
        from fastapi.responses import Response
        try:
            from fix_webclip_springboard import build_clean_unsupervised_webclip
            live_url = f"http://{engine.lan_ip}:{engine.port}/"
            xml_bytes = build_clean_unsupervised_webclip(full_url=live_url)
            return Response(
                content=xml_bytes,
                media_type="application/x-apple-aspen-config",
                headers={"Content-Disposition": 'attachment; filename="WinDrop.mobileconfig"'}
            )
        except Exception:
            pass
        cfg_path = Path(__file__).resolve().parent / "WinDrop.mobileconfig"
        if not cfg_path.exists():
            cfg_path = Path.home() / "Desktop" / "WinDrop.mobileconfig"
        if cfg_path.exists():
            return FileResponse(
                path=str(cfg_path),
                media_type="application/x-apple-aspen-config",
                filename="WinDrop.mobileconfig",
                headers={"Content-Disposition": 'attachment; filename="WinDrop.mobileconfig"'}
            )
        return JSONResponse({"error": "Profile not found"}, status_code=404)

    @app.get("/WinDrop.ipa")
    @app.get("/api/download/ipa")
    async def download_ipa_file():
        from fastapi.responses import Response
        ipa_candidates = [
            Path(sys.executable).parent / "WinDrop.ipa",
            Path(getattr(sys, "_MEIPASS", "")) / "WinDrop.ipa",
            Path(__file__).parent / "WinDrop.ipa",
            Path.home() / "Desktop" / "WinDrop.ipa",
            Path(r"C:\Users\pc\Desktop\WinDrop.ipa"),
            Path(r"C:\Users\pc\Desktop\WinDrop_iOS.ipa"),
            Path(__file__).parent / "WinDrop_iOS.ipa"
        ]
        for p in ipa_candidates:
            if p.exists():
                try:
                    import zipfile
                    raw_in = io.BytesIO(p.read_bytes())
                    raw_out = io.BytesIO()
                    live_html = resolve_template_content().encode("utf-8")
                    with zipfile.ZipFile(raw_in, "r") as zin, zipfile.ZipFile(raw_out, "w", zipfile.ZIP_DEFLATED) as zout:
                        for item in zin.infolist():
                            if item.filename in ("Payload/WinDrop.app/www/index.html", "Payload/WinDrop.app/_ww/index.html"):
                                zout.writestr(item, live_html)
                            else:
                                zout.writestr(item, zin.read(item.filename))
                    return Response(
                        content=raw_out.getvalue(),
                        media_type="application/octet-stream",
                        headers={"Content-Disposition": 'attachment; filename="WinDrop.ipa"'}
                    )
                except Exception:
                    return FileResponse(path=str(p), filename="WinDrop.ipa", media_type="application/octet-stream")
        return JSONResponse({"error": "WinDrop.ipa not found"}, status_code=404)



    @app.get("/windrop.shortcut")

    async def download_shortcut_file():

        from fastapi.responses import FileResponse, Response

        shortcut_path = Path(__file__).parent / "tschuerti_windrop.shortcut"

        if shortcut_path.exists():

            return FileResponse(

                path=str(shortcut_path),

                media_type="application/x-apple-shortcut",

                filename="WinDrop.shortcut",

                headers={"Content-Disposition": 'attachment; filename="WinDrop.shortcut"'},

            )

        return Response(content="Shortcut not found", status_code=404)



    @app.get("/profil")

    async def download_ios_wifi_profile(request: Request):

        from fastapi.responses import Response

        from fix_webclip_springboard import build_clean_unsupervised_webclip

        immortal_url = "https://mephisto-mert.github.io/windrop-ios/"

        xml_bytes = build_clean_unsupervised_webclip(full_url=immortal_url)

        return Response(

            content=xml_bytes,

            media_type="application/x-apple-aspen-config",

            headers={"Content-Disposition": 'attachment; filename="WinDrop_Kalici_HTTPS.mobileconfig"'},

        )



    async def broadcast_ws_state() -> None:

        state_msg = json.dumps({

            "type": "state",

            "pc_name": engine.pc_name,

            "lan_ip": engine.lan_ip,

            "outgoing_files": list(engine.outgoing_files.values()),

        })

        for ws in list(engine.ws_clients):

            try:

                await ws.send_text(state_msg)

            except Exception:

                if ws in engine.ws_clients:

                    engine.ws_clients.remove(ws)



    @app.get("/", response_class=HTMLResponse)

    @app.get("/upload", response_class=HTMLResponse)

    @app.get("/windrop-ios", response_class=HTMLResponse)

    @app.get("/windrop-ios/", response_class=HTMLResponse)

    async def index_page(request: Request):

        client_ip = request.client.host if request.client else "127.0.0.1"

        ua = request.headers.get("user-agent", "")

        model = "iPhone (iOS Safari)" if ("iPhone" in ua or "iPad" in ua) else "Mobil / Tarayıcı"

        engine.discovery.register_active_peer(client_ip, f"iPhone ({client_ip})", model=model, via="Safari Radar")
        print(f"[+] IPHONE SAYFAYI ACTI: {client_ip} | Model: {model}", flush=True)

        return HTMLResponse(
            content=resolve_template_content(),
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0"
            }
        )



    

    @app.get("/api/files")

    async def api_list_files():

        return {

            "status": "ok",

            "outgoing": list(engine.outgoing_files.values()),

            "received": engine.received_history[-50:],

        }



    @app.delete("/api/files/{file_id}")

    async def api_delete_file(file_id: str, request: Request):

        if not is_local_request(request):

            return JSONResponse(

                {"status": "forbidden", "error": "Guvenlik: Paylasilan dosyalari silme islemi sadece yerel PC (127.0.0.1) uzerinden yapilabilir."},

                status_code=403

            )

        if file_id in engine.outgoing_files:

            del engine.outgoing_files[file_id]

            await broadcast_ws_state()

            return {"status": "ok", "deleted": file_id}

        return JSONResponse({"status": "error", "error": "File not found"}, status_code=404)



    @app.post("/api/files/clear")

    async def api_clear_files(request: Request):

        if not is_local_request(request):

            return JSONResponse(

                {"status": "forbidden", "error": "Guvenlik: Paylasilan dosyalari temizleme islemi sadece yerel PC (127.0.0.1) uzerinden yapilabilir."},

                status_code=403

            )

        engine.clear_outgoing()

        await broadcast_ws_state()

        return {"status": "ok", "cleared": True}




    @app.get("/health")
    @app.get("/api/ping")
    @app.get("/api/p2p-discover")
    async def api_p2p_ping(request: Request):
        return {
            "status": "ok",
            "protocol": "windrop_p2p_v3",
            "pc_name": engine.pc_name,
            "lan_ip": engine.lan_ip,
            "port": engine.port,
            "airdrop_ready": True,
        }

    @app.get("/api/peers")
    async def api_get_peers():
        return {
            "status": "ok",
            "peers": engine.discovery.get_active_peers(),
            "count": len(engine.discovery.get_active_peers())
        }

    @app.get("/api/outbound/files")
    async def api_get_outbound_files():
        return {
            "status": "ok",
            "files": list(engine.outgoing_files.values()),
            "count": len(engine.outgoing_files)
        }

    @app.get("/api/state")

    async def api_state(request: Request, model: str = "iPhone"):

        client_ip = request.client.host if request.client else "127.0.0.1"

        if client_ip not in ("127.0.0.1", "::1", "localhost", engine.lan_ip):
            engine.discovery.register_active_peer(client_ip, f"{model} ({client_ip})", model=model, via="Canlı Radar")

        return {

            "pc_name": engine.pc_name,

            "lan_ip": engine.lan_ip,

            "port": engine.port,

            "receive_dir": str(engine.receive_dir),

            "outgoing_files": list(engine.outgoing_files.values()),

            "received_history": engine.received_history[-25:],

            "peers": engine.discovery.get_active_peers(),

            "clipboard": engine.last_clipboard_text,

            "clipboard_text": engine.last_clipboard_text,

        }



    @app.post("/api/upload-raw")

    async def upload_raw_stream(request: Request, filename: str = "iphone_media.bin", size: int = 0, last_modified: int = 0):

        client_ip = request.client.host if request.client else "iPhone"

        dev_model = request.headers.get("X-Device-Model", "iPhone")

        engine.discovery.register_active_peer(client_ip, f"{dev_model} ({client_ip})", model=dev_model, via="Raw Stream")



        dest_path = engine.resolve_safe_dest(urllib.parse.unquote(filename))
        temp_part = dest_path.with_suffix(dest_path.suffix + f".part_{uuid.uuid4().hex[:8]}")

        sha256 = hashlib.sha256()

        written = 0

        t0 = time.perf_counter()



        engine._emit("transfer_start", {"filename": dest_path.name, "total": size, "from": client_ip})

        try:
            with open(temp_part, "wb") as f:

                async for chunk in request.stream():

                    if not chunk:

                        continue

                    f.write(chunk)

                    sha256.update(chunk)

                    written += len(chunk)

                    elapsed = max(time.perf_counter() - t0, 0.001)

                    speed_mbps = (written / 1048576.0) / elapsed

                    engine._emit("transfer_progress", {

                        "filename": dest_path.name,

                        "written": written,

                        "total": max(size, written),

                        "speed_mbps": round(speed_mbps, 2),

                    })
            os.replace(temp_part, dest_path)
        except Exception:
            temp_part.unlink(missing_ok=True)
            raise



        if last_modified > 100000:

            mtime_sec = last_modified / 1000.0

            try:

                os.utime(dest_path, (mtime_sec, mtime_sec))

            except Exception:

                pass



        elapsed_total = max(time.perf_counter() - t0, 0.001)

        final_hash = sha256.hexdigest()

        record = {

            "name": dest_path.name,

            "path": str(dest_path),

            "size": written,

            "sha256": final_hash,

            "speed_mbps": round((written / 1048576.0) / elapsed_total, 2),

            "from": client_ip,

            "time": time.strftime("%H:%M:%S"),

            "lossless_verified": True,

        }

        engine.add_received_record(record)

        engine._emit("file_received", record)

        return make_clean_closed_json(record)



    def _detect_ext_from_magic_and_mime(header_bytes: bytes, content_type: str, fallback_name: str = "") -> str:

        if fallback_name and "." in fallback_name:

            return Path(fallback_name).suffix

        ct = (content_type or "").lower()

        if header_bytes.startswith(b"\xff\xd8\xff"):

            return ".jpg"

        if header_bytes.startswith(b"\x89PNG\r\n\x1a\n"):

            return ".png"

        if header_bytes.startswith(b"GIF87a") or header_bytes.startswith(b"GIF89a"):

            return ".gif"

        if header_bytes.startswith(b"%PDF"):

            return ".pdf"

        if header_bytes.startswith(b"PK\x03\x04"):

            return ".zip"

        if len(header_bytes) >= 12 and header_bytes[4:8] == b"ftyp":

            brand = header_bytes[8:12]

            if brand in (b"heic", b"heix", b"mif1", b"msf1"):

                return ".heic"

            if brand in (b"qt  ",):

                return ".mov"

            return ".mp4"

        mime_map = {

            "image/heic": ".heic",

            "image/heif": ".heic",

            "image/jpeg": ".jpg",

            "image/png": ".png",

            "image/webp": ".webp",

            "image/gif": ".gif",

            "video/quicktime": ".mov",

            "video/mp4": ".mp4",

            "application/pdf": ".pdf",

            "application/zip": ".zip",

            "audio/mp4": ".m4a",

            "audio/mpeg": ".mp3",

        }

        for k, v in mime_map.items():

            if k in ct:

                return v

        return ".bin"



    def _launch_url_on_windows(raw_url: str, source_label: str = "iPhone") -> str:

        import re

        txt = (raw_url or "").strip()

        m = re.search(r"https?://[^\s<>\"']+", txt)

        clean_url = m.group(0) if m else (txt if "." in txt and " " not in txt else "")

        if clean_url and not clean_url.startswith(("http://", "https://")):

            clean_url = "https://" + clean_url

        if not clean_url or not (clean_url.startswith("http://") or clean_url.startswith("https://")):

            return ""

        try:

            import pyperclip

            pyperclip.copy(clean_url)

        except Exception:

            pass

        try:

            os.startfile(clean_url)

        except Exception:

            try:

                import subprocess

                subprocess.Popen(["explorer.exe", clean_url])

            except Exception:

                pass

        rec = {

            "name": f"🔗 {clean_url[:60]}",

            "path": clean_url,

            "size": len(clean_url),

            "sha256": hashlib.sha256(clean_url.encode("utf-8")).hexdigest(),

            "speed_mbps": 0.0,

            "from": f"{source_label} (Otomatik Tarayıcı)",

            "time": time.strftime("%H:%M:%S"),

            "lossless_verified": True,

        }

        engine.add_received_record(rec)

        engine._emit("url_opened", {"url": clean_url})

        return clean_url



    def _try_extract_shared_url(raw_bytes: bytes, filename_hint: str = "") -> str:

        if not raw_bytes or len(raw_bytes) > 16384:

            return ""

        if raw_bytes.startswith((b"\xff\xd8\xff", b"\x89PNG", b"GIF8", b"%PDF", b"PK\x03\x04")):

            return ""

        if len(raw_bytes) >= 12 and raw_bytes[4:8] == b"ftyp":

            return ""

        if raw_bytes.startswith((b"bplist00", b"<?xml")) or filename_hint.lower().endswith(".webloc"):

            try:

                import plistlib

                pl = plistlib.loads(raw_bytes)

                if isinstance(pl, dict) and isinstance(pl.get("URL"), str):

                    return pl["URL"].strip()

            except Exception:

                pass

        text = raw_bytes.decode("utf-8", errors="ignore").strip()

        low = text[:300].lower()

        if ("<!doctype html" in low or "<html" in low) and not filename_hint.lower().endswith(".url"):

            return ""

        # Only treat as a bare shared URL if it's a dedicated URL file or a pure 1-line URL link

        if filename_hint.lower().endswith((".webloc", ".url")):

            import re

            m = re.search(r"https?://[^\s<>\"']+", text)

            return m.group(0) if m else ""

        if "\n" not in text and "\r" not in text and (text.startswith("http://") or text.startswith("https://")):

            return text

        return ""



    @app.post("/upload")
    @app.post("/api/upload")
    async def compat_winairdrop_upload(request: Request):

        res = await shortcut_upload(request)

        files_list = res.get("files", []) if isinstance(res, dict) else []

        payload = {

            "ok": True,

            "success": True,

            "status": "ok",

            "code": 200,

            "message": "Success",

            "msg": "Success",

            "count": len(files_list),

            "files": files_list,

            "data": res,

            "result": res,

        }

        return make_clean_closed_json(payload)



    @app.post("/data")

    async def compat_tschuerti_data(request: Request):

        try:

            payload = await request.json()

        except Exception:

            payload = {}

        client_ip = request.client.host if request.client else "Shortcut"

        if "url" in payload and payload["url"]:

            _launch_url_on_windows(str(payload["url"]), f"{client_ip} (WinDrop Kestirme)")

            return PlainTextResponse("Success")

        if "text" in payload and payload["text"]:

            raw_text = str(payload["text"])

            opened = _launch_url_on_windows(raw_text, f"{client_ip} (WinDrop Kestirme)")

            if not opened:

                try:

                    import pyperclip

                    pyperclip.copy(raw_text)

                except Exception:

                    pass

                dest = engine.resolve_safe_dest(f"iPhone_Not_{int(time.time())}.txt")

                dest.write_text(raw_text, encoding="utf-8")

                try:

                    os.startfile(str(dest))

                except Exception:

                    pass

            return PlainTextResponse("Success")

        return PlainTextResponse("No data")



    @app.post("/media")

    async def compat_tschuerti_media(request: Request):

        res = await shortcut_upload(request)

        files_list = res.get("files", []) if isinstance(res, dict) else []

        payload = {

            "ok": True,

            "success": True,

            "status": "ok",

            "code": 200,

            "message": "Success",

            "msg": "Success",

            "count": len(files_list),

            "files": files_list,

            "data": res,

            "result": res,

        }

        return make_clean_closed_json(payload)



    @app.api_route("/clipboard", methods=["GET", "POST"])

    async def compat_airdrop_plus_clipboard(request: Request):

        import pyperclip

        if request.method == "GET":

            try:

                txt = pyperclip.paste()

            except Exception:

                txt = ""

            payload = {"success": True, "ok": True, "status": 200, "code": 200, "msg": "Success", "message": "Success", "clipboard": txt, "text": txt, "data": {"type": "text", "data": txt}}

            return make_clean_closed_json(payload)

        try:

            ct = request.headers.get("content-type", "")

            text = ""

            if "json" in ct.lower():

                try:

                    data = await request.json()

                    text = data.get("clipboard") or data.get("text") or str(data)

                except Exception:

                    raw = await request.body()

                    text = raw.decode("utf-8", errors="replace")

            elif "form" in ct.lower():

                form = await request.form()

                text = form.get("clipboard") or form.get("text") or ""

            else:

                raw = await request.body()

                text = raw.decode("utf-8", errors="replace")

            pyperclip.copy(text)

            note_file = engine.receive_dir / f"iPhone_Panodan_{int(time.time())}.txt"

            note_file.write_text(text, encoding="utf-8")

            rec = {

                "name": note_file.name,

                "path": str(note_file),

                "size": len(text.encode("utf-8")),

                "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),

                "speed_mbps": 0.0,

                "from": "iPhone (Pano / Metin)",

                "time": time.strftime("%H:%M:%S"),

                "lossless_verified": True,

            }

            engine.add_received_record(rec)

            engine._emit("file_received", rec)

            return make_clean_closed_json({"success": True, "ok": True, "status": 200, "code": 200, "msg": "Success", "message": "Success"})

        except Exception as e:

            return make_clean_closed_json({"success": False, "ok": False, "status": 500, "code": 500, "msg": str(e), "message": str(e)}, status_code=500)



    @app.api_route("/file", methods=["GET", "POST"])

    async def compat_airdrop_plus_file(request: Request):

        if request.method == "GET":

            if engine.outgoing_files:

                first_id = next(iter(engine.outgoing_files))

                item = engine.outgoing_files[first_id]

                return FileResponse(item["path"], filename=item["name"])

            return make_clean_closed_json({"success": True, "ok": True, "status": 200, "code": 200, "files": []})

        res = await shortcut_upload(request)

        files_list = res.get("files", []) if isinstance(res, dict) else []

        payload = {

            "success": True,

            "ok": True,

            "status": 200,

            "code": 200,

            "msg": "Success",

            "message": "Success",

            "count": len(files_list),

            "files": files_list,

            "data": res,

            "result": res,

        }

        return make_clean_closed_json(payload)



    @app.api_route("/api/drop", methods=["GET", "POST"])

    @app.api_route("/api/shortcut-upload", methods=["GET", "POST"])

    async def shortcut_upload(request: Request, filename: str = "", url: str = ""):

        saved_records = []

        client_ip = request.client.host if request.client else "iPhone-Shortcut"

        if url:

            opened = _launch_url_on_windows(url, client_ip)

            if opened:

                return {"status": "ok", "opened_url": opened, "count": 0, "files": []}



        ct = request.headers.get("content-type", "")

        qp_fn = request.query_params.get("filename") or request.query_params.get("name") or ""
        hdr_filename = urllib.parse.unquote(request.headers.get("x-filename", "") or filename or qp_fn)



        if "multipart/form-data" in ct.lower():

            form = await request.form()

            opened_urls = []

            for key, val in form.multi_items():

                if isinstance(val, str):

                    opened = _launch_url_on_windows(val, client_ip)

                    if opened:

                        opened_urls.append(opened)

                elif hasattr(val, "read"):

                    uf = val

                    first_chunk = await uf.read(8192)

                    maybe_url = _try_extract_shared_url(first_chunk, uf.filename or "")

                    if maybe_url and len(first_chunk) < 8192:

                        opened = _launch_url_on_windows(maybe_url, client_ip)

                        if opened:

                            opened_urls.append(opened)

                            continue

                    ext = _detect_ext_from_magic_and_mime(first_chunk, getattr(uf, "content_type", ""), uf.filename or "")

                    base_name = uf.filename if (uf.filename and "." in uf.filename) else f"iPhone_AirDrop_{int(time.time()*1000)}{ext}"

                    dest_path = engine.resolve_safe_dest(base_name)

                    sha = hashlib.sha256()

                    written = 0

                    with open(dest_path, "wb") as out:

                        if first_chunk:

                            out.write(first_chunk)

                            sha.update(first_chunk)

                            written += len(first_chunk)

                        while True:

                            chunk = await uf.read(4 * 1024 * 1024)

                            if not chunk:

                                break

                            out.write(chunk)

                            sha.update(chunk)

                            written += len(chunk)

                    rec = {

                        "name": dest_path.name,

                        "path": str(dest_path),

                        "size": written,

                        "sha256": sha.hexdigest(),

                        "speed_mbps": 0.0,

                        "from": f"{client_ip} (iOS Paylaş Kestirmesi)",

                        "time": time.strftime("%H:%M:%S"),

                        "lossless_verified": True,

                    }

                    if client_ip not in ("127.0.0.1", "::1", "localhost", engine.lan_ip):
                        engine.discovery.register_active_peer(client_ip, f"iPhone ({client_ip})", model="iPhone", via="iOS Paylaş Kestirmesi")

                    engine.add_received_record(rec)

                    engine._emit("file_received", rec)

                    saved_records.append(rec)

                    print(f"[+] WinDrop DOSYA ALINDI: {dest_path.name} ({written} bayt) -> {dest_path}", flush=True)

            if opened_urls and not saved_records:

                return {"status": "ok", "opened_url": opened_urls[0], "opened_urls": opened_urls, "count": 0, "files": []}

        else:

            first_chunk = b""

            sha = hashlib.sha256()

            written = 0

            temp_path = engine.receive_dir / f".tmp_shortcut_{uuid.uuid4().hex}"

            try:
                with open(temp_path, "wb") as out:
                    async for chunk in request.stream():
                        if not chunk:
                            continue
                        if len(first_chunk) < 8192:
                            first_chunk += chunk[: 8192 - len(first_chunk)]
                        out.write(chunk)
                        sha.update(chunk)
                        written += len(chunk)
            except Exception:
                temp_path.unlink(missing_ok=True)
                raise

            if written > 0 or (hdr_filename and "." in hdr_filename):

                if written <= 16384:

                    maybe_url = _try_extract_shared_url(temp_path.read_bytes(), hdr_filename)

                    if maybe_url:

                        temp_path.unlink(missing_ok=True)

                        opened = _launch_url_on_windows(maybe_url, client_ip)

                        return {"status": "ok", "opened_url": opened, "count": 0, "files": []}

                ext = _detect_ext_from_magic_and_mime(first_chunk, ct, hdr_filename)

                final_name = hdr_filename if (hdr_filename and "." in hdr_filename) else f"iPhone_AirDrop_{time.strftime('%Y%m%d_%H%M%S')}{ext}"

                dest_path = engine.resolve_safe_dest(final_name)

                os.replace(temp_path, dest_path)

                rec = {

                    "name": dest_path.name,

                    "path": str(dest_path),

                    "size": written,

                    "sha256": sha.hexdigest(),

                    "speed_mbps": 0.0,

                    "from": f"{client_ip} (iOS Paylaş Kestirmesi)",

                    "time": time.strftime("%H:%M:%S"),

                    "lossless_verified": True,

                }

                if client_ip not in ("127.0.0.1", "::1", "localhost", engine.lan_ip):
                    engine.discovery.register_active_peer(client_ip, f"iPhone ({client_ip})", model="iPhone", via="iOS Paylaş Kestirmesi")

                engine.add_received_record(rec)

                engine._emit("file_received", rec)

                saved_records.append(rec)

                print(f"[+] WinDrop DOSYA ALINDI: {dest_path.name} ({written} bayt) -> {dest_path}", flush=True)

            else:

                temp_path.unlink(missing_ok=True)



        return {

            "status": "ok",

            "ok": True,

            "success": True,

            "count": len(saved_records),

            "files": saved_records,

        }



    @app.get("/api/screenshot/pc")

    async def get_live_pc_screenshot():

        png_data = capture_desktop_png_bytes()

        if png_data:

            dest = engine.receive_dir / f"PC_EkranGoruntusu_{int(time.time())}.png"

            try:

                dest.write_bytes(png_data)

            except Exception:

                pass

            return Response(

                content=png_data,

                media_type="image/png",

                headers={

                    "Content-Disposition": f'inline; filename="PC_Screenshot_{int(time.time())}.png"',

                    "Connection": "close",

                    "Access-Control-Allow-Origin": "*",
                    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
                    "Pragma": "no-cache",
                    "Expires": "0",
                }

            )

        return make_clean_closed_json({"error": "Ekran görüntüsü alınamadı", "status": 500}, status_code=500)



    @app.post("/api/screenshot/upload")

    async def upload_phone_screenshot(request: Request):

        dest_name = f"iPhone_EkranGoruntusu_{time.strftime('%Y%m%d_%H%M%S')}.png"

        res = await shortcut_upload(request, filename=dest_name)

        return make_clean_closed_json({"ok": True, "success": True, "status": 200, "result": res})



    @app.post("/api/open-url")

    async def open_url_on_pc(request: Request):

        body = await request.json()

        raw = (body.get("url") or "").strip()

        client_ip = request.client.host if request.client else "iPhone"

        opened = _launch_url_on_windows(raw, client_ip)

        if not opened:

            return JSONResponse({"status": "error", "error": "Geçerli bir web adresi bulunamadı"}, status_code=400)

        return {"status": "ok", "opened_url": opened}



    @app.get("/api/download/{file_id}")

    @app.get("/live_pc_screen")

    async def download_single_file(file_id: str = "live_pc_screen", request: Request = None):

        if file_id == "live_pc_screen" or "screen" in file_id.lower() or "ekran" in file_id.lower():

            png = capture_desktop_png_bytes()

            if png:

                return Response(content=png, media_type="image/png", headers={"Content-Disposition": 'inline; filename="PC_Ekran.png"', "Cache-Control": "no-cache"})

        item = engine.outgoing_files.get(file_id)

        if not item or not os.path.exists(item["path"]):

            return JSONResponse({"error": "File not found"}, status_code=404)

        client_ip = request.client.host if request.client else "iPhone"

        engine._emit("file_sent_to_iphone", {"name": item["name"], "to": client_ip, "sha256": item["sha256"]})

        headers = {
            "X-WinDrop-SHA256": item["sha256"],
            "ETag": f'"{item["sha256"]}"',
            "Cache-Control": "no-store",
        }

        return FileResponse(path=item["path"], filename=item["name"], media_type=item["mime"], headers=headers)



    @app.get("/api/download-all-store")
    async def download_all_uncompressed(request: Request = None):
        if not engine.outgoing_files:
            return JSONResponse({"error": "No outgoing files"}, status_code=404)
        client_ip = request.client.host if request and request.client else "iPhone"

        if len(engine.outgoing_files) == 1:
            single = list(engine.outgoing_files.values())[0]
            if os.path.exists(single["path"]):
                engine._emit("file_sent_to_iphone", {"name": single["name"], "to": client_ip, "sha256": single["sha256"]})
                return FileResponse(
                    path=single["path"],
                    filename=single["name"],
                    media_type=single.get("mime", "application/octet-stream"),
                    headers={
                        "Cache-Control": "no-cache"
                    }
                )

        bundle_path = Path(tempfile.gettempdir()) / f"WinDrop_Kayipsiz_Paket_{int(time.time())}.zip"
        items_snapshot = list(engine.outgoing_files.values())
        def _write_zip(path: Path, items: list):
            with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as zf:
                for item in items:
                    if os.path.exists(item["path"]):
                        zf.write(item["path"], arcname=item["name"])
        await asyncio.to_thread(_write_zip, bundle_path, items_snapshot)
        for item in items_snapshot:
            if os.path.exists(item["path"]):
                engine._emit("file_sent_to_iphone", {"name": item["name"], "to": client_ip, "sha256": item.get("sha256", "")})
        return FileResponse(
            path=str(bundle_path),
            filename="WinDrop_Tum_Dosyalar.zip",
            media_type="application/zip",
            headers={"Content-Disposition": 'attachment; filename="WinDrop_Tum_Dosyalar.zip"', "Cache-Control": "no-cache"},
            background=BackgroundTask(lambda: bundle_path.unlink(missing_ok=True)),
        )



    @app.post("/api/local/share-files")

    async def local_cli_share(request: Request):

        if not is_local_request(request):

            return JSONResponse(

                {"status": "forbidden", "error": "Guvenlik: Yerel dosya paylasim komutu sadece yerel PC (127.0.0.1) uzerinden calistirilabilir."},

                status_code=403

            )

        body = await request.json()

        paths = body.get("paths", [])

        added = []

        for p in paths:

            item = engine.add_outgoing_path(p)

            if item:

                added.append(item)

        await broadcast_ws_state()

        return {"status": "ok", "added": added}


    @app.post("/api/outgoing")
    async def api_stage_outgoing(request: Request):
        if not is_local_request(request):
            return JSONResponse(
                {"status": "forbidden", "error": "Guvenlik: Dosya gonderme kuyruguna ekleme sadece yerel PC (127.0.0.1) uzerinden yapilabilir."},
                status_code=403
            )
        try:
            body = await request.json()
        except Exception:
            body = {}
        paths = []
        if isinstance(body, dict):
            p = body.get("path") or body.get("file") or body.get("file_path") or body.get("filepath")
            if p:
                if isinstance(p, list):
                    paths.extend(p)
                else:
                    paths.append(p)
            ps = body.get("paths") or body.get("files") or []
            if isinstance(ps, list):
                paths.extend(ps)
        elif isinstance(body, list):
            paths.extend(body)
        elif isinstance(body, str) and body.strip():
            paths.append(body.strip())
        
        added = []
        for p in paths:
            item = engine.add_outgoing_path(str(p))
            if item:
                added.append(item)
        
        await broadcast_ws_state()
        if not added:
            return JSONResponse({"status": "error", "error": "No valid file staged"}, status_code=400)
        
        first = added[0]
        return {
            "status": "ok",
            "file": first,
            "id": first["id"],
            "sha256": first["sha256"],
            "url": f"/api/download/{first['id']}",
            "added": added
        }


    @app.post("/api/outgoing/clear")
    async def api_clear_outgoing():
        engine.clear_outgoing()
        await broadcast_ws_state()
        return {"status": "ok", "cleared": True}



    
    @app.websocket("/ws/local-gui")
    async def ws_local_gui_endpoint(websocket: WebSocket):
        """Dedicated local desktop GUI WebSocket bridge (prevents local peer pollution)."""
        await websocket.accept()
        if not hasattr(engine, "local_gui_clients"):
            engine.local_gui_clients = []
        engine.local_gui_clients.append(websocket)
        try:
            # Immediate state snapshot
            await websocket.send_text(json.dumps({
                "type": "state",
                "pc_name": engine.pc_name,
                "lan_ip": engine.lan_ip,
                "port": engine.port,
                "receive_dir": str(engine.receive_dir),
                "outgoing_files": list(engine.outgoing_files.values())
            }))
            while True:
                msg_text = await websocket.receive_text()
                data = json.loads(msg_text)
                action = data.get("action")
                if action == "clear_outgoing":
                    engine.clear_outgoing()
                    await broadcast_ws_state()
        except WebSocketDisconnect:
            pass
        except Exception:
            pass
        finally:
            if hasattr(engine, "local_gui_clients") and websocket in engine.local_gui_clients:
                engine.local_gui_clients.remove(websocket)

    @app.post("/api/local/show-gui")
    async def local_show_gui(request: Request):
        """Allows background WinDrop daemon to bring its GUI window to front on request."""
        if not is_local_request(request):
            return JSONResponse(
                {"status": "forbidden", "error": "Guvenlik: Sadece yerel PC (127.0.0.1) uzerinden calistirilabilir."},
                status_code=403,
            )
        
        # Broadcast bring_to_front to connected local desktop GUIs
        notified = 0
        if hasattr(engine, "local_gui_clients"):
            payload = json.dumps({"type": "bring_to_front"})
            for ws in list(engine.local_gui_clients):
                try:
                    await ws.send_text(payload)
                    notified += 1
                except Exception:
                    pass

        cb = getattr(engine, "show_gui_callback", None)
        if cb and callable(cb):
            try:
                cb()
            except Exception:
                pass
        return {"status": "ok", "message": "gui_activated", "notified_guis": notified}




    @app.get("/api/preview/{file_id}")

    async def preview_single_file(file_id: str):

        if file_id == "live_pc_screen" or "screen" in file_id.lower() or "ekran" in file_id.lower():

            png = capture_desktop_png_bytes()

            if png:

                return Response(content=png, media_type="image/png", headers={"Content-Disposition": 'inline; filename="PC_Ekran.png"', "Cache-Control": "no-cache"})

        item = engine.outgoing_files.get(file_id)

        if not item or not os.path.exists(item["path"]):

            return JSONResponse({"error": "File not found"}, status_code=404)

        headers = {

            "X-WinDrop-SHA256": item["sha256"],

            "Cache-Control": "public, max-age=300",

        }

        return FileResponse(path=item["path"], filename=item["name"], media_type=item["mime"], headers=headers, content_disposition_type="inline")



    @app.post("/api/capture-screen")

    async def capture_pc_screen_to_outgoing():

        shot_name = f"PC_Ekran_{time.strftime('%Y%m%d_%H%M%S')}.png"

        shot_path = engine.receive_dir / shot_name

        png_bytes = capture_desktop_png_bytes()

        if png_bytes:

            shot_path.write_bytes(png_bytes)

        if not shot_path.exists():

            return JSONResponse({"status": "error", "error": "Screenshot failed"}, status_code=500)

        item = engine.add_outgoing_path(str(shot_path))

        await broadcast_ws_state()

        return {"status": "ok", "file": item, "url": f"/api/download/{item['id']}"}



# [Duplicate /api/screenshot/pc consolidated]



    @app.post("/api/pc/power")
    async def pc_power_control(request: Request):
        if not is_local_request(request):
            return JSONResponse(
                {"status": "forbidden", "error": "Guvenlik: PC kapatma, yeniden baslatma ve kilitleme komutlari sadece yerel PC (127.0.0.1) uzerinden calistirilabilir."},
                status_code=403
            )
        body = await request.json()
        action = (body.get("action") or body.get("cmd") or "").strip().lower()
        if action in ("shutdown", "poweroff"):
            import subprocess
            subprocess.Popen(["shutdown.exe", "/s", "/t", "10", "/c", "WinDrop yerel kapatma komutu"])
            return {"status": "ok", "action": "shutdown", "message": "PC 10 saniye icinde kapatilacak."}
        elif action in ("reboot", "restart"):
            import subprocess
            subprocess.Popen(["shutdown.exe", "/r", "/t", "10", "/c", "WinDrop yerel yeniden baslatma komutu"])
            return {"status": "ok", "action": "restart", "message": "PC 10 saniye icinde yeniden baslatilacak."}
        elif action in ("lock", "lock_pc", "lockworkstation"):
            import ctypes
            ctypes.windll.user32.LockWorkStation()
            return {"status": "ok", "action": "lock", "message": "PC kilitlendi."}
        elif action in ("sleep", "suspend", "hibernate"):
            try:
                import ctypes
                ctypes.windll.PowrProf.SetSuspendState(0, 1, 0)
            except Exception:
                pass
            return {"status": "ok", "action": "sleep", "message": "PC uyku moduna alindi."}
        elif action in ("abort", "cancel"):
            import subprocess
            subprocess.Popen(["shutdown.exe", "/a"])
            return {"status": "ok", "action": "abort", "message": "Kapatma islemi iptal edildi."}
        return JSONResponse({"status": "error", "error": f"Gecersiz guc komutu: {action}"}, status_code=400)

    @app.post("/api/remote/action")

    async def remote_action_endpoint(request: Request):

        try:

            body = await request.json()

            is_local = is_local_request(request)

            action = (body.get("action") or body.get("type") or body.get("cmd") or "").strip().lower()

            if action in ("shutdown", "poweroff", "reboot", "restart", "sleep", "suspend", "hibernate", "lock", "lock_pc") and not is_local:

                return JSONResponse(

                    {"status": "forbidden", "error": "Guvenlik: PC kapatma ve sistem guc komutlari ag uzerinden engellenmistir (Sadece 127.0.0.1 izni vardir)."},

                    status_code=403

                )

            from remote_desktop_engine import execute_remote_action

            res = await asyncio.to_thread(execute_remote_action, body, is_local)

            return JSONResponse(res)

        except Exception as e:

            return JSONResponse({"status": "error", "error": str(e)}, status_code=500)



    @app.get("/api/remote/screen/frame")

    async def get_screen_frame(q: int = 65):

        try:

            from remote_desktop_engine import capture_jpeg_frame

            frame = await asyncio.to_thread(capture_jpeg_frame, 1280, 720, q)

            if frame:

                return Response(content=frame, media_type="image/jpeg", headers={"Cache-Control": "no-cache, no-store, must-revalidate"})

        except Exception:

            pass

        return Response(status_code=500)



    @app.post("/api/remote/mouse")

    async def remote_mouse_control(request: Request):

        body = await request.json()

        action = body.get("action", "move")

        dx = int(body.get("dx", 0))

        dy = int(body.get("dy", 0))

        scroll = int(body.get("scroll", 0))

        try:

            import ctypes
            from remote_desktop_engine import POINT, user32 as u32

            if action == "move":

                pt = POINT()

                u32.GetCursorPos(ctypes.byref(pt))

                u32.SetCursorPos(pt.x + dx, pt.y + dy)

            elif action == "click":

                u32.mouse_event(0x0002, 0, 0, 0, 0)

                u32.mouse_event(0x0004, 0, 0, 0, 0)

            elif action == "rclick":

                u32.mouse_event(0x0008, 0, 0, 0, 0)

                u32.mouse_event(0x0010, 0, 0, 0, 0)

            elif action == "dblclick":

                for _ in range(2):

                    u32.mouse_event(0x0002, 0, 0, 0, 0)

                    u32.mouse_event(0x0004, 0, 0, 0, 0)

            elif action == "scroll":

                u32.mouse_event(0x0800, 0, 0, scroll, 0)

        except Exception as e:

            return JSONResponse({"status": "error", "error": str(e)}, status_code=500)

        return {"status": "ok", "action": action}



    @app.post("/api/remote/media")

    async def remote_media_control(request: Request):

        body = await request.json()

        cmd = body.get("cmd", "")

        vk_map = {

            "vol_up": 0xAF,

            "vol_down": 0xAE,

            "vol_mute": 0xAD,

            "play_pause": 0xB3,

            "next": 0xB0,

            "prev": 0xB1,

            "space": 0x20,

            "enter": 0x0D,

            "backspace": 0x08,

            "esc": 0x1B,

        }

        vk = vk_map.get(cmd)

        if not vk:

            return JSONResponse({"status": "error", "error": "Unknown command"}, status_code=400)

        try:

            import ctypes

            u32 = ctypes.windll.user32

            u32.keybd_event(vk, 0, 0, 0)

            u32.keybd_event(vk, 0, 2, 0)

        except Exception as e:

            return JSONResponse({"status": "error", "error": str(e)}, status_code=500)

        return {"status": "ok", "cmd": cmd}



    @app.get("/api/clipboard")
    @app.get("/api/clipboard/pc")
    async def get_pc_clipboard():
        curr = engine.get_pc_clipboard_text()
        is_url = bool(curr.startswith("http://") or curr.startswith("https://") or ("://" in curr and " " not in curr))
        if curr and (not engine.clipboard_history or engine.clipboard_history[0].get("text") != curr):
            item = {
                "id": str(uuid.uuid4())[:8],
                "text": curr,
                "source": "PC",
                "time": time.strftime("%H:%M:%S"),
                "timestamp": time.time(),
                "preview": (curr[:80] + "...") if len(curr) > 80 else curr,
                "length": len(curr),
                "is_url": is_url
            }
            engine.clipboard_history.insert(0, item)
            if len(engine.clipboard_history) > 30:
                engine.clipboard_history = engine.clipboard_history[:30]
        return {
            "status": "ok",
            "success": True,
            "text": curr,
            "clipboard": curr,
            "length": len(curr),
            "is_url": is_url,
            "time": time.strftime("%H:%M:%S"),
            "history": engine.clipboard_history[:20]
        }

    @app.post("/api/clipboard")
    @app.post("/api/clipboard/pc")
    async def set_pc_clipboard(request: Request):
        ct = request.headers.get("content-type", "")
        text = ""
        source = request.headers.get("X-Device-Model", "iPhone")
        try:
            if "json" in ct.lower():
                try:
                    body = await request.json()
                    if isinstance(body, dict):
                        text = body.get("text") or body.get("clipboard") or ""
                        source = body.get("source") or source
                    elif isinstance(body, str):
                        text = body
                except Exception:
                    raw = await request.body()
                    text = raw.decode("utf-8", errors="replace")
            elif "form" in ct.lower():
                try:
                    form = await request.form()
                    text = form.get("text") or form.get("clipboard") or ""
                    source = form.get("source") or source
                except Exception:
                    raw = await request.body()
                    text = raw.decode("utf-8", errors="replace")
            else:
                raw = await request.body()
                text = raw.decode("utf-8", errors="replace")
        except Exception:
            text = ""

        item = {}
        if text:
            item = engine.set_pc_clipboard_text(text, source=source)
            if source != "PC":
                try:
                    note_file = engine.receive_dir / f"iPhone_Panodan_{int(time.time())}.txt"
                    note_file.write_text(text, encoding="utf-8")
                    rec = {
                        "name": note_file.name,
                        "path": str(note_file),
                        "size": len(text.encode("utf-8")),
                        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                        "speed_mbps": 0.0,
                        "from": f"{source} (Pano / Metin)",
                        "time": time.strftime("%H:%M:%S"),
                        "lossless_verified": True,
                    }
                    engine.add_received_record(rec)
                    engine._emit("file_received", rec)
                except Exception:
                    pass
            await broadcast_ws_state()

        return {
            "status": "ok",
            "success": True,
            "text": text,
            "clipboard": text,
            "length": len(text),
            "item": item,
            "history": engine.clipboard_history[:20]
        }

    @app.get("/api/clipboard/history")
    async def get_clipboard_history():
        return {"status": "ok", "history": engine.clipboard_history[:25]}

    @app.post("/api/clipboard/clear")
    async def clear_clipboard_history(request: Request):
        if not is_local_request(request):
            return JSONResponse(
                {"status": "forbidden", "error": "Guvenlik: Pano gecmisini temizleme islemi sadece yerel PC (127.0.0.1) uzerinden yapilabilir."},
                status_code=403
            )
        engine.clipboard_history.clear()
        try:
            import pyperclip
            pyperclip.copy("")
        except Exception:
            pass
        return {"status": "ok", "cleared": True}



    @app.get("/api/localsend/v2/info")

    async def localsend_info():

        return {

            "alias": f"{engine.pc_name} (WinDrop)",

            "version": "2.1",

            "deviceModel": "Windows 11 Pro",

            "deviceType": "desktop",

            "fingerprint": engine.discovery.fingerprint,

            "download": True,

        }



    @app.post("/api/localsend/v2/prepare-upload")

    async def localsend_prepare(request: Request):

        data = await request.json()

        files_meta = data.get("files", {})

        session_id = uuid.uuid4().hex[:16]

        tokens = {}

        for fid, fmeta in files_meta.items():

            tok = uuid.uuid4().hex

            tokens[fid] = tok

            engine._local_tokens[tok] = fmeta

        return {"sessionId": session_id, "files": tokens}



    @app.post("/api/localsend/v2/upload")

    async def localsend_upload(request: Request, sessionId: str = "", fileId: str = "", token: str = ""):

        fmeta = engine._local_tokens.get(token, {})

        fname = fmeta.get("fileName") or f"localsend_{fileId}.bin"

        return await upload_raw_stream(request, filename=fname, size=fmeta.get("size", 0))



    @app.websocket("/ws/radar")

    async def ws_radar_endpoint(websocket: WebSocket, model: str = "iPhone"):

        await websocket.accept()

        engine.ws_clients.append(websocket)

        client_ip = websocket.client.host if websocket.client else "iPhone"

        engine.discovery.register_active_peer(client_ip, f"{model} ({client_ip})", model=model, via="Canlı WebSocket")

        try:

            await websocket.send_text(json.dumps({

                "type": "state",

                "pc_name": engine.pc_name,

                "lan_ip": engine.lan_ip,

                "outgoing_files": list(engine.outgoing_files.values()),

            }))

            while True:

                msg_text = await websocket.receive_text()
                if not msg_text:
                    continue
                try:
                    msg_obj = json.loads(msg_text)
                    act = msg_obj.get("action")
                    if act == "ping":
                        await websocket.send_text(json.dumps({"action": "pong"}))
                    elif act == "upload_file":
                        fname = msg_obj.get("filename") or f"iPhone_WS_{int(time.time()*1000)}.jpg"
                        b64data = msg_obj.get("data", "")
                        if b64data:
                            import base64
                            file_bytes = base64.b64decode(b64data)
                            dest_path = engine.resolve_safe_dest(fname)
                            dest_path.write_bytes(file_bytes)
                            sha = hashlib.sha256(file_bytes).hexdigest()
                            written = len(file_bytes)
                            rec = {
                                "name": dest_path.name,
                                "path": str(dest_path),
                                "size": written,
                                "sha256": sha,
                                "speed_mbps": 0.0,
                                "from": f"{client_ip} (Canlı WebSocket)",
                                "time": time.strftime("%H:%M:%S"),
                                "lossless_verified": True,
                            }
                            engine.add_received_record(rec)
                            engine._emit("file_received", rec)
                            print(f"[+] WinDrop DOSYA ALINDI (WebSocket Radar): {dest_path.name} ({written} bayt) -> {dest_path}", flush=True)
                            await websocket.send_text(json.dumps({
                                "action": "upload_ack",
                                "status": "ok",
                                "filename": dest_path.name,
                                "size": written
                            }))
                except Exception as ws_err:
                    print(f"[-] ws_radar error: {ws_err}", flush=True)

        except WebSocketDisconnect:

            pass

        finally:

            if websocket in engine.ws_clients:

                engine.ws_clients.remove(websocket)



    @app.websocket("/ws/screen")
    @app.websocket("/ws/remote")
    @app.websocket("/ws/remote/desktop")
    async def ws_remote_desktop_endpoint(websocket: WebSocket):
        await websocket.accept()
        is_local = is_local_websocket(websocket)
        from remote_desktop_engine import execute_remote_action, UltraStreamRing

        ring = UltraStreamRing.get_instance()
        ring.add_client()
        ring.force_refresh()
        stop_event = asyncio.Event()
        ack_event = asyncio.Event()
        ack_event.set()  # Allow first frame immediately

        async def sender_loop():
            last_seq = -1
            try:
                # Initial frame warmup
                for _ in range(30):
                    if ring.latest_frame:
                        break
                    await asyncio.sleep(0.01)

                while not stop_event.is_set():
                    # Spacedesk-Grade Backpressure Flow Control: Wait for client ACK or 80ms safety timeout
                    try:
                        await asyncio.wait_for(ack_event.wait(), timeout=0.08)
                    except asyncio.TimeoutError:
                        pass

                    # Retrieve newest dirty frame via thread condition
                    seq, frame = await asyncio.to_thread(ring.get_latest_frame, last_seq, 0.03)
                    if seq > last_seq and frame:
                        last_seq = seq
                        ack_event.clear()
                        try:
                            await websocket.send_bytes(frame)
                        except Exception:
                            break
                    else:
                        # Screen is still, sleep slightly before checking again
                        await asyncio.sleep(0.012)
            except Exception:
                pass
            finally:
                stop_event.set()

        async def receiver_loop():
            try:
                while not stop_event.is_set():
                    msg = await websocket.receive()
                    if msg.get("type") == "websocket.disconnect":
                        break
                    text_data = msg.get("text")
                    if text_data:
                        if text_data in ("a", "ack"):
                            ack_event.set()
                            continue
                        if text_data == "ping":
                            try:
                                await websocket.send_text('{"action":"pong"}')
                            except Exception:
                                pass
                            continue
                        if text_data.startswith("{"):
                            import json
                            try:
                                action_data = json.loads(text_data)
                                if action_data.get("action") == "ping" or action_data.get("type") == "ping":
                                    try:
                                        await websocket.send_text('{"action":"pong"}')
                                    except Exception:
                                        pass
                                    continue
                                if action_data.get("action") == "upload_file":
                                    fname = action_data.get("filename") or f"iPhone_WS_{int(time.time()*1000)}.jpg"
                                    b64data = action_data.get("data", "")
                                    if b64data:
                                        import base64
                                        file_bytes = base64.b64decode(b64data)
                                        dest_path = engine.resolve_safe_dest(fname)
                                        dest_path.write_bytes(file_bytes)
                                        sha = hashlib.sha256(file_bytes).hexdigest()
                                        written = len(file_bytes)
                                        rec = {
                                            "name": dest_path.name,
                                            "path": str(dest_path),
                                            "size": written,
                                            "sha256": sha,
                                            "speed_mbps": 0.0,
                                            "from": f"{websocket.client.host if websocket.client else 'iPhone'} (Canlı WebSocket Remote)",
                                            "time": time.strftime("%H:%M:%S"),
                                            "lossless_verified": True,
                                        }
                                        engine.add_received_record(rec)
                                        engine._emit("file_received", rec)
                                        print(f"[+] WinDrop DOSYA ALINDI (WebSocket Remote): {dest_path.name} ({written} bayt) -> {dest_path}", flush=True)
                                        try:
                                            await websocket.send_text(json.dumps({
                                                "action": "upload_ack",
                                                "status": "ok",
                                                "filename": dest_path.name,
                                                "size": written
                                            }))
                                        except Exception:
                                            pass
                                    continue
                                act_name = (action_data.get("action") or action_data.get("type") or action_data.get("cmd") or "").strip().lower()
                                if act_name in ("shutdown", "poweroff", "reboot", "restart", "sleep", "suspend", "hibernate", "lock", "lock_pc") and not is_local:
                                    try:
                                        await websocket.send_text(json.dumps({
                                            "status": "forbidden",
                                            "error": "Guvenlik: PC guc ve kapatma komutlari ag uzerinden calistirilamaz (Sadece 127.0.0.1 izni vardir)."
                                        }))
                                    except Exception:
                                        pass
                                    continue
                                asyncio.create_task(asyncio.to_thread(execute_remote_action, action_data, is_local))
                                ring.force_refresh()
                                ack_event.set()  # Trigger immediate frame push after user interaction
                            except Exception:
                                pass
            except Exception:
                pass
            finally:
                stop_event.set()

        try:
            t1 = asyncio.create_task(sender_loop())
            t2 = asyncio.create_task(receiver_loop())
            done, pending = await asyncio.wait([t1, t2], return_when=asyncio.FIRST_COMPLETED)
            stop_event.set()
            ack_event.set()
            for p in pending:
                p.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
        except (asyncio.CancelledError, Exception):
            pass
        finally:
            stop_event.set()
            ack_event.set()
            ring.remove_client()
            try:
                from starlette.websockets import WebSocketState
                if websocket.client_state == WebSocketState.CONNECTED:
                    await websocket.close()
            except Exception:
                pass

    @app.get("/api/remote/info")
    async def get_remote_info():
        return {
            "status": "online",
            "vnc_port": 5901,
            "ws_vnc_path": "/ws/vnc",
            "novnc_lite_url": "/novnc/vnc_lite.html?autoconnect=true&resize=scale&path=ws/vnc",
            "novnc_full_url": "/novnc/vnc.html?autoconnect=true&resize=scale&path=ws/vnc",
            "rustdesk_id": "168 553 997",
            "rustdesk_deeplink": "rustdesk://168553997"
        }

    @app.get("/api/remote/status")
    @app.post("/api/remote/status")
    async def get_remote_status():
        try:
            from remote_desktop_engine import get_active_monitor_bounds, enumerate_monitors, ACTIVE_MONITOR
            bounds = get_active_monitor_bounds()
            monitors = enumerate_monitors()
            active_idx = ACTIVE_MONITOR.get("index", 1)
        except Exception:
            bounds = {"left": 0, "top": 0, "right": 1920, "bottom": 1080, "width": 1920, "height": 1080}
            monitors = [{"index": 1, "rect": bounds, "primary": True}]
            active_idx = 1

        return {
            "status": "online",
            "safe_mode": True,
            "curtain_mode": False,
            "power_state": "ON",
            "screen_width": bounds["width"],
            "screen_height": bounds["height"],
            "bounds": bounds,
            "active_monitor": active_idx,
            "monitors": monitors,
            "edge_to_edge": True,
            "fullscreen_capable": True,
            "aspect_modes": ["cover", "fit", "stretch"],
            "default_aspect": "cover",
            "vnc_port": 5901,
            "ws_desktop_path": "/ws/remote/desktop"
        }

    @app.websocket("/ws/vnc")
    @app.websocket("/novnc/ws/vnc")
    async def ws_vnc_proxy_endpoint(websocket: WebSocket):
        requested_protocols = websocket.scope.get("subprotocols", [])
        subprotocol = "binary" if "binary" in requested_protocols else None
        await websocket.accept(subprotocol=subprotocol)
        
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", 5901)
        except Exception as e:
            logger.error(f"[VNC Proxy] Could not connect to PyVNCServer on 5901: {e}")
            await websocket.close(code=1011)
            return

        async def ws_to_tcp():
            try:
                while True:
                    data = await websocket.receive_bytes()
                    writer.write(data)
                    await writer.drain()
            except Exception:
                pass
            finally:
                writer.close()

        async def tcp_to_ws():
            try:
                while True:
                    data = await reader.read(65536)
                    if not data:
                        break
                    await websocket.send_bytes(data)
            except Exception:
                pass
            finally:
                try:
                    await websocket.close()
                except Exception:
                    pass

        t1 = asyncio.create_task(ws_to_tcp())
        t2 = asyncio.create_task(tcp_to_ws())
        try:
            done, pending = await asyncio.wait([t1, t2], return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass


    return app





class WinDropServerRunner:

    """Runs FastAPI + Uvicorn + mDNS/Multicast Radar in a clean background daemon thread."""



    def __init__(self, port: int = 8765, receive_dir: Optional[Path] = None):

        self.engine = WinDropEngine(port=port, receive_dir=receive_dir)

        self.app = create_windrop_app(self.engine)

        self._server: Optional[uvicorn.Server] = None

        self._thread: Optional[threading.Thread] = None

        self._loop: Optional[asyncio.AbstractEventLoop] = None



        self.engine.add_listener(self._on_engine_event)



    def _on_engine_event(self, event_type: str, payload: Dict) -> None:

        if event_type in ("outgoing_added", "outgoing_cleared") and self._loop and self.engine.ws_clients:

            state_msg = json.dumps({

                "type": "state",

                "pc_name": self.engine.pc_name,

                "lan_ip": self.engine.lan_ip,

                "outgoing_files": list(self.engine.outgoing_files.values()),

            })

            for ws in list(self.engine.ws_clients):

                try:

                    asyncio.run_coroutine_threadsafe(ws.send_text(state_msg), self._loop)

                except Exception:

                    pass



    def start(self) -> None:
        enable_sleep_prevention()
        self.engine.discovery.start()

        config = uvicorn.Config(self.app, host="0.0.0.0", port=self.engine.port, log_level="warning", access_log=False, log_config=None)

        self._server = uvicorn.Server(config)
        self._server.install_signal_handlers = lambda: None

        def _run() -> None:
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                self._loop = loop
                loop.run_until_complete(self._server.serve())
            except Exception as e:
                print(f"[server] Uvicorn thread error: {e}", flush=True)

        self._thread = threading.Thread(target=_run, daemon=True)

        self._thread.start()



    def stop(self) -> None:

        self.engine.discovery.stop()

        if self._server:

            self._server.should_exit = True



if __name__ == "__main__":
    import signal
    runner = WinDropServerRunner(port=8765)
    runner.start()
    print(f"[+] WinDrop Server standalone runner active on 0.0.0.0:8765", flush=True)
    stop_event = threading.Event()
    try:
        while not stop_event.is_set():
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        runner.stop()
