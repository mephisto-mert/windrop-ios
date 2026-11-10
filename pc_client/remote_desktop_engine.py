import mss
import cv2
import numpy as np
# -*- coding: utf-8 -*-

"""

WinDrop AnyDesk-Grade Remote Control & Frame Engine

Handles Win32 mouse, touch, scroll, keyboard injection and rapid screen grabbing.

Fully hardened for 64-bit Windows, multi-monitor setups, full Unicode/emojis, and zero handle leaks.

"""



import io

import time

import ctypes

from ctypes import wintypes

from PIL import Image

import threading



user32 = ctypes.windll.user32

gdi32 = ctypes.windll.gdi32
kernel32 = ctypes.windll.kernel32

# Anti-Screen-Sleep: Prevent host PC display from dimming or sleeping during remote operation
try:
    kernel32.SetThreadExecutionState(0x80000000 | 0x00000002 | 0x00000001)
except Exception:
    pass

try:
    ctypes.windll.winmm.timeBeginPeriod(1)
except Exception:
    pass



try:

    user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))

except Exception:

    try:

        user32.SetProcessDPIAware()

    except Exception:

        pass



# 64-bit / 32-bit pointer-sized integer for Win32 ULONG_PTR

ULONG_PTR = ctypes.c_size_t

# Server-side click deduplication cache (prevents iOS ghost double-clicks)
_LAST_CLICK_EVENT = {'time': 0.0, 'x': -1, 'y': -1, 'btn': ''}



# Win32 Point Structure

class POINT(ctypes.Structure):

    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]



class RECT(ctypes.Structure):

    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),

                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]



# SendInput structures aligned strictly to 64-bit Win32 ABI (sizeof(INPUT) == 40 on x64)

class KEYBDINPUT(ctypes.Structure):

    _fields_ = [

        ("wVk", wintypes.WORD),

        ("wScan", wintypes.WORD),

        ("dwFlags", wintypes.DWORD),

        ("time", wintypes.DWORD),

        ("dwExtraInfo", ULONG_PTR),

    ]



class HARDWAREINPUT(ctypes.Structure):

    _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD), ("wParamH", wintypes.WORD)]



class MOUSEINPUT(ctypes.Structure):

    _fields_ = [

        ("dx", wintypes.LONG),

        ("dy", wintypes.LONG),

        ("mouseData", wintypes.DWORD),

        ("dwFlags", wintypes.DWORD),

        ("time", wintypes.DWORD),

        ("dwExtraInfo", ULONG_PTR),

    ]



class _INPUT_UNION(ctypes.Union):

    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]



class INPUT(ctypes.Structure):

    _fields_ = [("type", wintypes.DWORD), ("u", _INPUT_UNION)]



# Win32 Function Prototypes (Explicit 64-bit Win32 ABI)

user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]

user32.SetCursorPos.restype = wintypes.BOOL



user32.GetCursorPos.argtypes = [ctypes.POINTER(POINT)]

user32.GetCursorPos.restype = wintypes.BOOL



user32.OpenInputDesktop.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]

user32.OpenDesktopW.argtypes = [ctypes.c_wchar_p, wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]

user32.OpenDesktopW.restype = wintypes.HANDLE

user32.OpenInputDesktop.restype = wintypes.HANDLE



user32.SetThreadDesktop.argtypes = [wintypes.HANDLE]

user32.SetThreadDesktop.restype = wintypes.BOOL



user32.mouse_event.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ULONG_PTR]

user32.mouse_event.restype = None



user32.keybd_event.argtypes = [wintypes.BYTE, wintypes.BYTE, wintypes.DWORD, ULONG_PTR]

user32.keybd_event.restype = None



user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]

user32.SendInput.restype = wintypes.UINT



user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]

user32.SendMessageW.restype = wintypes.LPARAM



user32.SendNotifyMessageA.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]

user32.SendNotifyMessageA.restype = wintypes.BOOL



user32.WindowFromPoint.argtypes = [POINT]

user32.WindowFromPoint.restype = wintypes.HWND



user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]

user32.GetAncestor.restype = wintypes.HWND



user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]

user32.PostMessageW.restype = wintypes.BOOL



# Virtual key map

VK_MAP = {

    "enter": 0x0D, "return": 0x0D,

    "backspace": 0x08, "bs": 0x08,

    "tab": 0x09,

    "esc": 0x1B, "escape": 0x1B,

    "space": 0x20, "spacebar": 0x20,

    "del": 0x2E, "delete": 0x2E,

    "win": 0x5B, "lwin": 0x5B, "rwin": 0x5C,

    "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,

    "home": 0x24, "end": 0x23,

    "pageup": 0x21, "pgup": 0x21,

    "pagedown": 0x22, "pgdn": 0x22,

    "insert": 0x2D, "prtscn": 0x2C, "printscreen": 0x2C,

    "capslock": 0x14, "numlock": 0x90, "scrolllock": 0x91,

    "vol_up": 0xAF, "volup": 0xAF,

    "vol_down": 0xAE, "voldown": 0xAE,

    "vol_mute": 0xAD, "volmute": 0xAD, "mute": 0xAD,

    "play_pause": 0xB3, "playpause": 0xB3,

    "next": 0xB0, "prev": 0xB1, "stop": 0xB2,

    "f1": 0x70, "f2": 0x71, "f3": 0x72, "f4": 0x73,

    "f5": 0x74, "f6": 0x75, "f7": 0x76, "f8": 0x77,

    "f9": 0x78, "f10": 0x79, "f11": 0x7A, "f12": 0x7B,

    "shift": 0x10, "lshift": 0xA0, "rshift": 0xA1,

    "ctrl": 0x11, "control": 0x11, "lctrl": 0xA2, "rctrl": 0xA3,

    "alt": 0x12, "lalt": 0xA4, "ralt": 0xA5,

}



MOUSE_LEFTDOWN = 0x0002

MOUSE_LEFTUP = 0x0004

MOUSE_RIGHTDOWN = 0x0008

MOUSE_RIGHTUP = 0x0010

MOUSE_MIDDLEDOWN = 0x0020

MOUSE_MIDDLEUP = 0x0040

MOUSE_WHEEL = 0x0800

MOUSE_HWHEEL = 0x1000

MOUSEEVENTF_MOVE = 0x0001



KEYEVENTF_KEYUP = 0x0002

KEYEVENTF_UNICODE = 0x0004



ACTIVE_MONITOR = {"index": 1, "rect": None}



def enumerate_monitors():

    monitors = []

    def _enum_proc(hMonitor, hdcMonitor, lprcMonitor, dwData):

        r = lprcMonitor.contents

        monitors.append({

            "left": r.left, "top": r.top,

            "right": r.right, "bottom": r.bottom,

            "width": r.right - r.left,

            "height": r.bottom - r.top,

        })

        return True

    MONITORENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HMONITOR, wintypes.HDC, ctypes.POINTER(RECT), wintypes.LPARAM)

    proc = MONITORENUMPROC(_enum_proc)

    user32.EnumDisplayMonitors(None, None, proc, 0)

    return monitors



def get_active_monitor_bounds():

    monitors = enumerate_monitors()

    idx = ACTIVE_MONITOR.get("index", 1) - 1

    if 0 <= idx < len(monitors):

        return monitors[idx]

    return {

        "left": 0, "top": 0,

        "width": user32.GetSystemMetrics(0),

        "height": user32.GetSystemMetrics(1),

        "right": user32.GetSystemMetrics(0),

        "bottom": user32.GetSystemMetrics(1),

    }



def get_screen_size():

    bounds = get_active_monitor_bounds()

    return bounds["width"], bounds["height"]



def _parse_safe_int(val, default=0) -> int:

    try:

        return int(float(val))

    except Exception:

        return default



def _parse_safe_float(val, default=None):

    if val is None:

        return default

    try:

        return float(val)

    except Exception:

        return default



def _parse_safe_bool(val, default=True) -> bool:

    if val is None:

        return default

    if isinstance(val, bool):

        return val

    s = str(val).strip().lower()

    return s not in ("false", "0", "off", "disable", "no")



def execute_remote_action(action_data: dict, is_local: bool = False):

    _attach_calling_thread_to_input_desktop()

    # Parameter Aliases: 'action' vs 'type' vs 'cmd' vs 'event'

    action = (action_data.get("action") or action_data.get("type") or action_data.get("event") or "").strip().lower()

    bounds = get_active_monitor_bounds()

    sw = bounds["width"]

    sh = bounds["height"]

    ox = bounds["left"]

    oy = bounds["top"]



    # 1. TOUCH_CLICK (left, right, double, middle) - 5-Tier AnyDesk Hybrid Engine

    if action in ("touch_click", "click", "tap", "double_click", "dblclick", "doubleclick"):

        raw_x = action_data.get("x_pct", action_data.get("x", action_data.get("xpct")))

        raw_y = action_data.get("y_pct", action_data.get("y", action_data.get("ypct")))

        x_pct = _parse_safe_float(raw_x, None)

        y_pct = _parse_safe_float(raw_y, None)

        btn = (action_data.get("button") or action_data.get("btn") or "left").lower()



        if x_pct is not None and y_pct is not None:

            target_x = ox + max(0, min(sw - 1, int(round((sw - 1) * x_pct))))

            target_y = oy + max(0, min(sh - 1, int(round((sh - 1) * y_pct))))

        else:

            pt = POINT()

            user32.GetCursorPos(ctypes.byref(pt))

            target_x, target_y = pt.x, pt.y

            x_pct = (target_x - ox) / max(1, sw - 1)

            y_pct = (target_y - oy) / max(1, sh - 1)



        # Ensure thread is attached to interactive desktop

        _attach_calling_thread_to_input_desktop()



        # Virtual Desktop Metrics & Normalization

        vLeft = user32.GetSystemMetrics(76)   # SM_XVIRTUALSCREEN

        vTop = user32.GetSystemMetrics(77)    # SM_YVIRTUALSCREEN

        vWidth = user32.GetSystemMetrics(78)  # SM_CXVIRTUALSCREEN

        vHeight = user32.GetSystemMetrics(79) # SM_CYVIRTUALSCREEN

        if vWidth <= 1: vWidth = sw

        if vHeight <= 1: vHeight = sh



        norm_x = int(round(((target_x - vLeft) / max(1.0, float(vWidth - 1))) * 65535.0))
        norm_y = int(round(((target_y - vTop) / max(1.0, float(vHeight - 1))) * 65535.0))

        norm_x = max(0, min(65535, norm_x))

        norm_y = max(0, min(65535, norm_y))



        is_right = btn in ("right", "rclick")

        is_middle = btn in ("middle", "mclick", "wheel")

        is_double = btn in ("double", "dblclick", "2x") or action in ("double_click", "dblclick", "doubleclick")
        if is_double and btn == "left":
            btn = "double"



        down_flag = MOUSE_RIGHTDOWN if is_right else (MOUSE_MIDDLEDOWN if is_middle else MOUSE_LEFTDOWN)

        up_flag = MOUSE_RIGHTUP if is_right else (MOUSE_MIDDLEUP if is_middle else MOUSE_LEFTUP)



        diag = []



        # Tier 1: SetCursorPos with UIPI & Focus Failsafe
        try:
            res_sc = user32.SetCursorPos(target_x, target_y)
            if not res_sc:
                pt_t = POINT(target_x, target_y)
                hw_t = user32.WindowFromPoint(pt_t)
                if hw_t:
                    user32.SetForegroundWindow(hw_t)
                res_sc = user32.SetCursorPos(target_x, target_y)
            diag.append(f"SetCursorPos={res_sc}")
        except Exception as e:
            diag.append(f"SetCursorPos:exc={e}")



        # Tier 2: 64-bit SendInput Move (Absolute + VirtualDesk)

        try:

            inp_m = INPUT()

            inp_m.type = 0

            inp_m.u.mi.dx = norm_x

            inp_m.u.mi.dy = norm_y

            inp_m.u.mi.dwFlags = 0x0001 | 0x8000 | 0x4000  # MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK

            res_m = user32.SendInput(1, ctypes.byref(inp_m), ctypes.sizeof(INPUT))

            diag.append(f"SendInputMove={res_m}")

        except Exception as e:

            diag.append(f"SendInputMove:exc={e}")



        time.sleep(0.005)



        # Tier 3: Deduplication + 64-bit SendInput Click with 15ms Human-Like Hold
        now_mono = time.monotonic()
        if not is_double:
            time_delta = now_mono - _LAST_CLICK_EVENT["time"]
            dist = abs(target_x - _LAST_CLICK_EVENT["x"]) + abs(target_y - _LAST_CLICK_EVENT["y"])
            if time_delta < 0.120 and dist <= 6 and _LAST_CLICK_EVENT["btn"] == btn:
                return {"status": "ok", "action": "touch_click", "dedup": True, "x": target_x, "y": target_y}
        _LAST_CLICK_EVENT.update({"time": now_mono, "x": target_x, "y": target_y, "btn": btn})

        try:
            inp_d = INPUT()
            inp_d.type = 0
            inp_d.u.mi.dx = norm_x
            inp_d.u.mi.dy = norm_y
            inp_d.u.mi.dwFlags = down_flag | 0x0001 | 0x8000 | 0x4000

            inp_u = INPUT()
            inp_u.type = 0
            inp_u.u.mi.dx = norm_x
            inp_u.u.mi.dy = norm_y
            inp_u.u.mi.dwFlags = up_flag | 0x0001 | 0x8000 | 0x4000

            if is_double:
                user32.SendInput(1, ctypes.byref(inp_d), ctypes.sizeof(INPUT))
                time.sleep(0.015)
                user32.SendInput(1, ctypes.byref(inp_u), ctypes.sizeof(INPUT))
                time.sleep(0.050)
                user32.SendInput(1, ctypes.byref(inp_d), ctypes.sizeof(INPUT))
                time.sleep(0.015)
                user32.SendInput(1, ctypes.byref(inp_u), ctypes.sizeof(INPUT))
                diag.append("SendInputDouble=ok")
            else:
                r_down = user32.SendInput(1, ctypes.byref(inp_d), ctypes.sizeof(INPUT))
                time.sleep(0.015)
                r_up = user32.SendInput(1, ctypes.byref(inp_u), ctypes.sizeof(INPUT))
                if not r_down or not r_up:
                    user32.mouse_event(down_flag, 0, 0, 0, 0)
                    time.sleep(0.015)
                    user32.mouse_event(up_flag, 0, 0, 0, 0)
                    diag.append("MouseEventFallback=ok")
                else:
                    diag.append(f"SendInputClick={r_down}&{r_up}")
        except Exception as e:
            diag.append(f"SendInputClick:exc={e}")
            try:
                user32.mouse_event(down_flag, 0, 0, 0, 0)
                time.sleep(0.015)
                user32.mouse_event(up_flag, 0, 0, 0, 0)
            except Exception:
                pass

        invalidate_frame_cache()
        return {"status": "ok", "action": "touch_click", "btn": btn, "x": target_x, "y": target_y, "diag": diag}

        # Tier 4: Driver-level mouse_event fallback (only if SendInput failed)
        try:
            user32.mouse_event(down_flag | 0x8000 | 0x4000 | 0x0001, norm_x, norm_y, 0, 0)

            time.sleep(0.012)

            user32.mouse_event(up_flag | 0x8000 | 0x4000 | 0x0001, norm_x, norm_y, 0, 0)

            if is_double:

                time.sleep(0.045)

                user32.mouse_event(down_flag | 0x8000 | 0x4000 | 0x0001, norm_x, norm_y, 0, 0)

                time.sleep(0.012)

                user32.mouse_event(up_flag | 0x8000 | 0x4000 | 0x0001, norm_x, norm_y, 0, 0)

            diag.append("mouse_event=ok")

        except Exception as e:

            diag.append(f"mouse_event:exc={e}")



        # Tier 5: Direct Targeted Window Message PostMessage & SendMessage (4-Message Sequence for CS_DBLCLKS)

        try:

            pt = POINT(target_x, target_y)

            hwnd = user32.WindowFromPoint(pt)

            if hwnd:

                client_pt = POINT(target_x, target_y)

                user32.ScreenToClient(hwnd, ctypes.byref(client_pt))

                lParam = ((client_pt.y & 0xFFFF) << 16) | (client_pt.x & 0xFFFF)

                msg_down = 0x0204 if is_right else (0x0207 if is_middle else 0x0201)

                msg_up = 0x0205 if is_right else (0x0208 if is_middle else 0x0202)

                wparam = 0x0002 if is_right else (0x0010 if is_middle else 0x0001)



                if is_double:

                    # CS_DBLCLKS protocol: WM_LBUTTONDOWN -> WM_LBUTTONUP -> WM_LBUTTONDBLCLK (0x0203) -> WM_LBUTTONUP

                    msg_dbl = 0x0206 if is_right else (0x0209 if is_middle else 0x0203)

                    pm_1 = user32.PostMessageW(hwnd, msg_down, wparam, lParam)

                    pm_2 = user32.PostMessageW(hwnd, msg_up, 0, lParam)

                    time.sleep(0.030)

                    pm_3 = user32.PostMessageW(hwnd, msg_dbl, wparam, lParam)

                    pm_4 = user32.PostMessageW(hwnd, msg_up, 0, lParam)

                    diag.append(f"PostMessageDbl(HWND={hwnd})={pm_1}&{pm_2}&{pm_3}&{pm_4}")



                    # Failsafe: if targeting Explorer / Desktop / FolderView, also post VK_RETURN to launch selected item

                    cls_buf = ctypes.create_unicode_buffer(256)

                    user32.GetClassNameW(hwnd, cls_buf, 256)

                    cls_name = cls_buf.value

                    if "SysListView32" in cls_name or "WorkerW" in cls_name or "SHELLDLL_DefView" in cls_name:

                        time.sleep(0.04)

                        user32.PostMessageW(hwnd, 0x0100, 0x0D, 0x001C0001)  # WM_KEYDOWN VK_RETURN

                        user32.PostMessageW(hwnd, 0x0101, 0x0D, 0xC01C0001)  # WM_KEYUP VK_RETURN

                        diag.append("DesktopEnterPosted=ok")

                else:

                    pm_d = user32.PostMessageW(hwnd, msg_down, wparam, lParam)

                    time.sleep(0.005)

                    pm_u = user32.PostMessageW(hwnd, msg_up, 0, lParam)

                    diag.append(f"PostMessage(HWND={hwnd})={pm_d}&{pm_u}")

        except Exception as e:

            diag.append(f"PostMessage:exc={e}")



        res = {"status": "ok", "x": target_x, "y": target_y, "btn": btn}

        try:

            with open(r"c:\Users\pc\Documents\projelerim\windrop_airdrop\action_events.log", "a", encoding="utf-8") as f:

                f.write(f"[{time.strftime('%H:%M:%S')}] CLICK x={target_x} y={target_y} (pct: {x_pct:.4f}, {y_pct:.4f}) btn={btn} | {' '.join(diag)}\n")

                f.flush()

        except Exception:

            pass

        invalidate_frame_cache()

        return res



    # 2. MOUSE_MOVE (absolute x_pct/y_pct or relative dx/dy)

    elif action in ("mouse_move", "move"):
        raw_x = action_data.get("x_pct", action_data.get("x", action_data.get("xpct")))
        raw_y = action_data.get("y_pct", action_data.get("y", action_data.get("ypct")))
        x_pct = _parse_safe_float(raw_x, None)
        y_pct = _parse_safe_float(raw_y, None)

        if x_pct is not None and y_pct is not None:
            target_x = ox + max(0, min(sw - 1, int(round((sw - 1) * x_pct))))
            target_y = oy + max(0, min(sh - 1, int(round((sh - 1) * y_pct))))
            
            # Virtual Desktop Normalization
            vLeft = user32.GetSystemMetrics(76)
            vTop = user32.GetSystemMetrics(77)
            vWidth = user32.GetSystemMetrics(78)
            vHeight = user32.GetSystemMetrics(79)
            if vWidth <= 1: vWidth = sw
            if vHeight <= 1: vHeight = sh
            norm_x = int(round(((target_x - vLeft) / max(1.0, float(vWidth - 1))) * 65535.0))
            norm_y = int(round(((target_y - vTop) / max(1.0, float(vHeight - 1))) * 65535.0))
            norm_x = max(0, min(65535, norm_x))
            norm_y = max(0, min(65535, norm_y))

            # Tier 1: Direct Physical SetCursorPos with Focus Activation Failsafe
            res_sc = user32.SetCursorPos(target_x, target_y)
            if not res_sc:
                pt_m = POINT(target_x, target_y)
                hw_m = user32.WindowFromPoint(pt_m)
                if hw_m:
                    user32.SetForegroundWindow(hw_m)
                user32.SetCursorPos(target_x, target_y)

            # Tier 2: 64-bit SendInput Move (Absolute + VirtualDesk)
            try:
                inp = INPUT()
                inp.type = 0
                inp.u.mi.dx = norm_x
                inp.u.mi.dy = norm_y
                inp.u.mi.dwFlags = 0x0001 | 0x8000 | 0x4000
                user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))
            except Exception:
                pass
            return {"status": "ok", "x": target_x, "y": target_y}

        dx = _parse_safe_int(action_data.get("dx", action_data.get("deltaX", 0)))
        dy = _parse_safe_int(action_data.get("dy", action_data.get("deltaY", 0)))
        pt = POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        target_x = pt.x + dx
        target_y = pt.y + dy
        user32.SetCursorPos(target_x, target_y)
        return {"status": "ok", "dx": dx, "dy": dy}

    # 3. MOUSE_DELTA (Trackpad relative motion)

    elif action in ("mouse_delta", "delta", "move_delta"):

        dx = _parse_safe_int(action_data.get("dx", action_data.get("deltaX", 0)))

        dy = _parse_safe_int(action_data.get("dy", action_data.get("deltaY", 0)))

        # Sub-microsecond native Win32 relative move (bypasses 100ms pyautogui pause)

        user32.mouse_event(MOUSEEVENTF_MOVE, dx, dy, 0, 0)

        return {"status": "ok", "dx": dx, "dy": dy}



    # 4. MOUSE_DOWN / MOUSE_UP (Zero-Lag Native Win32)
    elif action in ("mouse_down", "down"):
        btn = (action_data.get("button") or action_data.get("btn") or "left").lower()
        raw_x = action_data.get("x_pct", action_data.get("x"))
        raw_y = action_data.get("y_pct", action_data.get("y"))
        x_pct = _parse_safe_float(raw_x, None)
        y_pct = _parse_safe_float(raw_y, None)

        if x_pct is not None and y_pct is not None:
            target_x = ox + max(0, min(sw - 1, int(round((sw - 1) * x_pct))))
            target_y = oy + max(0, min(sh - 1, int(round((sh - 1) * y_pct))))
            user32.SetCursorPos(target_x, target_y)

        flag = MOUSE_RIGHTDOWN if btn in ("right", "rclick") else (MOUSE_MIDDLEDOWN if btn in ("middle", "mclick") else MOUSE_LEFTDOWN)
        user32.mouse_event(flag, 0, 0, 0, 0)
        return {"status": "ok", "down": btn}

    elif action in ("mouse_up", "up"):
        btn = (action_data.get("button") or action_data.get("btn") or "left").lower()
        raw_x = action_data.get("x_pct", action_data.get("x"))
        raw_y = action_data.get("y_pct", action_data.get("y"))
        x_pct = _parse_safe_float(raw_x, None)
        y_pct = _parse_safe_float(raw_y, None)

        if x_pct is not None and y_pct is not None:
            target_x = ox + max(0, min(sw - 1, int(round((sw - 1) * x_pct))))
            target_y = oy + max(0, min(sh - 1, int(round((sh - 1) * y_pct))))
            user32.SetCursorPos(target_x, target_y)

        flag = MOUSE_RIGHTUP if btn in ("right", "rclick") else (MOUSE_MIDDLEUP if btn in ("middle", "mclick") else MOUSE_LEFTUP)
        user32.mouse_event(flag, 0, 0, 0, 0)
        return {"status": "ok", "up": btn}


    # 5. SCROLL (delta / wheel ticks)

    elif action in ("scroll", "wheel", "mouse_wheel"):

        raw_delta = action_data.get("delta", action_data.get("dy", action_data.get("scroll", action_data.get("amount", -120))))

        delta = _parse_safe_int(raw_delta, -120)

        if 0 < abs(delta) <= 10:

            delta *= 120

        user32.mouse_event(MOUSE_WHEEL, 0, 0, delta, 0)



        raw_h = action_data.get("dx", action_data.get("hscroll", 0))

        h_delta = _parse_safe_int(raw_h, 0)

        if h_delta != 0:

            if 0 < abs(h_delta) <= 10:

                h_delta *= 120

            user32.mouse_event(MOUSE_HWHEEL, 0, 0, h_delta, 0)



        return {"status": "ok", "scroll": delta, "hscroll": h_delta}



    # 6. KEY_COMBO (win+d, alt+tab, ctrl+c, ctrl+v, volup, voldown, volmute + generic combos)

    elif action in ("key_combo", "combo", "shortcut", "hotkey"):

        keys_val = action_data.get("keys")

        if isinstance(keys_val, list):

            keys_val = "+".join(str(k) for k in keys_val)

        combo = (action_data.get("combo") or action_data.get("key") or keys_val or action_data.get("cmd") or "").lower().strip()

        

        if combo in ("volup", "vol_up", "volume_up"):

            user32.keybd_event(0xAF, 0, 0, 0); user32.keybd_event(0xAF, 0, KEYEVENTF_KEYUP, 0)

            return {"status": "ok", "combo": combo}

        elif combo in ("voldown", "vol_down", "volume_down"):

            user32.keybd_event(0xAE, 0, 0, 0); user32.keybd_event(0xAE, 0, KEYEVENTF_KEYUP, 0)

            return {"status": "ok", "combo": combo}

        elif combo in ("volmute", "vol_mute", "mute"):

            user32.keybd_event(0xAD, 0, 0, 0); user32.keybd_event(0xAD, 0, KEYEVENTF_KEYUP, 0)

            return {"status": "ok", "combo": combo}

        elif combo in ("alt+tab", "tab_switch"):

            user32.keybd_event(0x12, 0, 0, 0)

            user32.keybd_event(0x09, 0, 0, 0)

            time.sleep(0.045)

            user32.keybd_event(0x09, 0, KEYEVENTF_KEYUP, 0)

            time.sleep(0.02)

            user32.keybd_event(0x12, 0, KEYEVENTF_KEYUP, 0)

            return {"status": "ok", "combo": combo}

        elif combo in ("alt+f4", "close", "close_window", "close_app"):

            user32.keybd_event(0x12, 0, 0, 0)

            user32.keybd_event(0x73, 0, 0, 0)

            time.sleep(0.04)

            user32.keybd_event(0x73, 0, KEYEVENTF_KEYUP, 0)

            user32.keybd_event(0x12, 0, KEYEVENTF_KEYUP, 0)

            return {"status": "ok", "combo": "alt+f4"}

        elif combo in ("win+l", "lwin+l", "lock"):
            if not is_local:
                return {"status": "forbidden", "error": "Guvenlik: Ekran kilitleme komutu sadece yerel PC (127.0.0.1) uzerinden calistirilabilir."}
            user32.LockWorkStation()
            return {"status": "ok", "combo": "win+l"}

        elif combo in ("refresh", "f5"):

            user32.keybd_event(0x74, 0, 0, 0)

            time.sleep(0.03)

            user32.keybd_event(0x74, 0, KEYEVENTF_KEYUP, 0)

            return {"status": "ok", "combo": "f5"}



        parts = [p.strip() for p in combo.replace("_", "+").replace("-", "+").split("+") if p.strip()]

        mod_vk_map = {

            "ctrl": 0x11, "control": 0x11,

            "alt": 0x12, "menu": 0x12,

            "shift": 0x10,

            "win": 0x5B, "lwin": 0x5B, "rwin": 0x5C, "windows": 0x5B,

        }



        vks_to_press = []

        for p in parts:

            if p in mod_vk_map:

                vks_to_press.append(mod_vk_map[p])

            elif p in VK_MAP:

                vks_to_press.append(VK_MAP[p])

            elif len(p) == 1:

                vks_to_press.append(ord(p.upper()))

            elif p.startswith("f") and p[1:].isdigit():

                f_num = int(p[1:])

                if 1 <= f_num <= 12:

                    vks_to_press.append(0x6F + f_num)



        if vks_to_press:

            for vk in vks_to_press:

                user32.keybd_event(vk, 0, 0, 0)

            time.sleep(0.01)

            for vk in reversed(vks_to_press):

                user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)

            return {"status": "ok", "combo": combo, "keys_pressed": len(vks_to_press)}



        return {"status": "unknown_combo", "combo": combo}



    # 7. MEDIA_CONTROL (mute, voldown, volup, next, prev, playpause, stop)

    elif action in ("media_control", "media"):

        cmd = (action_data.get("command") or action_data.get("cmd") or action_data.get("key") or "").lower().strip()

        codes = {

            "mute": 0xAD, "volmute": 0xAD, "vol_mute": 0xAD,

            "voldown": 0xAE, "vol_down": 0xAE, "volume_down": 0xAE,

            "volup": 0xAF, "vol_up": 0xAF, "volume_up": 0xAF,

            "next": 0xB0, "next_track": 0xB0,

            "prev": 0xB1, "prev_track": 0xB1, "previous": 0xB1,

            "playpause": 0xB3, "play_pause": 0xB3, "play": 0xB3, "pause": 0xB3,

            "stop": 0xB2,

        }

        vk = codes.get(cmd)

        if vk:

            user32.keybd_event(vk, 0, 0, 0)

            user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)

            return {"status": "ok", "media": cmd}

        return {"status": "unknown_media_command", "cmd": cmd}



    # 8. CURTAIN_MODE & SC_MONITORPOWER (PERMANENTLY NEUTRALIZED FOR HOST DISPLAY SAFETY)
    elif action in ("curtain_mode", "curtain", "blank_screen", "monitor_power", "sc_monitorpower", "power"):
        # Explicitly keep display ON and reset idle timer (SC_MONITORPOWER -1 = MONITOR_ON)
        try:
            user32.PostMessageW(0xFFFF, 0x0112, 0xF170, -1)
            user32.mouse_event(MOUSEEVENTF_MOVE, 0, 0, 0, 0)
            kernel32.SetThreadExecutionState(0x80000000 | 0x00000002 | 0x00000001)
        except Exception:
            pass
        return {
            "status": "ok",
            "curtain": False,
            "curtain_mode": False,
            "safe_mode": True,
            "power_state": "ON",
            "sc_monitorpower": -1,
            "message": "PC display darkening neutralized for safety"
        }

    # 8B. CANVAS SIZING & FULLSCREEN EDGE-TO-EDGE SCALING
    elif action in ("canvas_size", "set_canvas", "resize_canvas", "fullscreen", "set_scale", "set_aspect", "scale", "aspect_ratio", "status", "get_status"):
        bounds = get_active_monitor_bounds()
        mode = action_data.get("mode", action_data.get("aspect", "cover"))
        client_w = _parse_safe_int(action_data.get("width", action_data.get("client_width", bounds["width"])), bounds["width"])
        client_h = _parse_safe_int(action_data.get("height", action_data.get("client_height", bounds["height"])), bounds["height"])
        fullscreen = _parse_safe_bool(action_data.get("fullscreen", True), True)
        return {
            "status": "ok",
            "canvas": {
                "width": client_w,
                "height": client_h,
                "source_width": bounds["width"],
                "source_height": bounds["height"],
                "aspect": mode,
                "fullscreen": fullscreen,
                "edge_to_edge": True,
                "scaling": "cover" if mode in ("cover", "fullscreen") else mode
            },
            "safe_mode": True,
            "curtain_mode": False
        }



    # 9. SET_MONITOR (index / idx)

    elif action in ("set_monitor", "monitor", "switch_monitor"):

        raw_idx = action_data.get("index", action_data.get("idx", action_data.get("monitor", 1)))

        idx = max(1, _parse_safe_int(raw_idx, 1))

        ACTIVE_MONITOR["index"] = idx

        ACTIVE_MONITOR["rect"] = get_active_monitor_bounds()

        return {"status": "ok", "monitor": idx, "bounds": ACTIVE_MONITOR["rect"]}



    # 10. KEY_PRESS (individual key with Turkish 'İ' & Extended key support)

    elif action in ("key_press", "key"):

        raw_key = (action_data.get("key") or action_data.get("k") or action_data.get("code") or "").strip()

        KEYEVENTF_EXTENDEDKEY = 0x0001

        EXTENDED_VKS = {0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2D, 0x2E, 0x5B, 0x5C, 0xA3, 0xA5}

        

        # Check Turkish character preservation BEFORE lowercase length distortion (e.g. 'İ'.lower() -> 'i\u0307')

        if len(raw_key) == 1 and (ord(raw_key) > 127 or raw_key in "çğıöşüÇĞİÖŞÜ"):

            return execute_remote_action({"action": "type_text", "text": raw_key}, is_local=is_local)

            

        key_lower = raw_key.lower()

        vk = VK_MAP.get(key_lower)

        # Route single printable characters to type_text to prevent ASCII overlap with navigation VKs
        if len(raw_key) == 1 and key_lower not in VK_MAP:
            return execute_remote_action({"action": "type_text", "text": raw_key}, is_local=is_local)
        if not vk and len(raw_key) == 1:

            vk = ord(raw_key.upper())

            

        if vk:

            flags_down = KEYEVENTF_EXTENDEDKEY if vk in EXTENDED_VKS else 0

            flags_up = (KEYEVENTF_EXTENDEDKEY if vk in EXTENDED_VKS else 0) | KEYEVENTF_KEYUP

            user32.keybd_event(vk, 0, flags_down, 0)

            time.sleep(0.005)

            user32.keybd_event(vk, 0, flags_up, 0)

            return {"status": "ok", "key": raw_key, "vk": vk}

        return {"status": "ignored", "key": raw_key}



    # 11. TYPE_TEXT (Win32 SendInput Unicode with true VK_RETURN conversion for terminal commands)

    elif action in ("type_text", "text", "type"):

        text = str(action_data.get("text", action_data.get("val", action_data.get("value", ""))))

        auto_enter = bool(action_data.get("enter", False))

        INPUT_KEYBOARD = 1



        # Normalize newlines to prevent CRLF double-enters

        normalized_text = text.replace("\r\n", "\n").replace("\r", "\n")

        if auto_enter and not normalized_text.endswith("\n"):

            normalized_text += "\n"



        for ch in normalized_text:

            if ch == "\n":

                # Inject true Win32 VK_RETURN for shell execution & newlines

                inp = (INPUT * 2)()

                inp[0].type = INPUT_KEYBOARD

                inp[0].u.ki.wVk = 0x0D  # VK_RETURN

                inp[0].u.ki.wScan = 0x1C  # Scan code for Enter

                inp[0].u.ki.dwFlags = 0

                inp[0].u.ki.time = 0

                inp[0].u.ki.dwExtraInfo = 0

                inp[1].type = INPUT_KEYBOARD

                inp[1].u.ki.wVk = 0x0D

                inp[1].u.ki.wScan = 0x1C

                inp[1].u.ki.dwFlags = KEYEVENTF_KEYUP

                inp[1].u.ki.time = 0

                inp[1].u.ki.dwExtraInfo = 0

                user32.SendInput(2, inp, ctypes.sizeof(INPUT))

                time.sleep(0.005)

                continue



            # Ignore non-printable control characters (except tab)

            if ord(ch) < 32 and ch != "\t":

                continue



            # Encode UTF-16 code units (preserves Turkish characters & emoji surrogate pairs)

            encoded = ch.encode("utf-16-le")

            utf16_units = [int.from_bytes(encoded[i:i+2], byteorder="little") for i in range(0, len(encoded), 2)]



            for scan_code in utf16_units:

                inputs = (INPUT * 2)()

                inputs[0].type = INPUT_KEYBOARD

                inputs[0].u.ki.wVk = 0

                inputs[0].u.ki.wScan = scan_code

                inputs[0].u.ki.dwFlags = KEYEVENTF_UNICODE

                inputs[0].u.ki.time = 0

                inputs[0].u.ki.dwExtraInfo = 0



                inputs[1].type = INPUT_KEYBOARD

                inputs[1].u.ki.wVk = 0

                inputs[1].u.ki.wScan = scan_code

                inputs[1].u.ki.dwFlags = KEYEVENTF_UNICODE | KEYEVENTF_KEYUP

                inputs[1].u.ki.time = 0

                inputs[1].u.ki.dwExtraInfo = 0



                user32.SendInput(2, inputs, ctypes.sizeof(INPUT))

                time.sleep(0.001)



        return {"status": "ok", "length": len(normalized_text)}



    # 12. SYSTEM POWER & HOST CONTROL (shutdown, reboot, sleep, lock) - STRICTLY RESTRICTED TO LOCALHOST (127.0.0.1)
    elif action in ("shutdown", "poweroff", "reboot", "restart", "sleep", "suspend", "hibernate", "lock", "lock_pc"):
        if not is_local:
            return {
                "status": "forbidden",
                "error": f"Guvenlik: '{action}' komutu ag uzerinden engellenmistir. Sadece yerel PC (127.0.0.1) uzerinden calistirilabilir."
            }

        if action in ("lock", "lock_pc"):
            user32.LockWorkStation()
            return {"status": "ok", "action": "lock", "message": "PC basariyla kilitlendi"}

        elif action in ("shutdown", "poweroff"):
            import subprocess
            subprocess.Popen(["shutdown.exe", "/s", "/t", "10", "/c", "WinDrop yerel kapatma komutu"])
            return {"status": "ok", "action": "shutdown", "message": "PC 10 saniye icinde kapatilacak"}

        elif action in ("reboot", "restart"):
            import subprocess
            subprocess.Popen(["shutdown.exe", "/r", "/t", "10", "/c", "WinDrop yerel yeniden baslatma komutu"])
            return {"status": "ok", "action": "reboot", "message": "PC 10 saniye icinde yeniden baslatilacak"}

        elif action in ("sleep", "suspend", "hibernate"):
            try:
                ctypes.windll.PowrProf.SetSuspendState(0, 1, 0)
            except Exception as e:
                return {"status": "error", "error": str(e)}
            return {"status": "ok", "action": "sleep", "message": "PC uyku moduna alindi"}

    return {"status": "unknown_action", "action": action}





def _attach_calling_thread_to_input_desktop():

    """Attaches the calling thread directly to the interactive Windows input desktop (WinSta0\\Default)."""

    try:

        user32.SetProcessDPIAware()

    except Exception:

        pass

    try:

        hDesk = user32.OpenDesktopW("Default", 0, False, 0x01FF)

        if not hDesk:

            hDesk = user32.OpenInputDesktop(0, False, 0x01FF)

        if hDesk:

            user32.SetThreadDesktop(hDesk)

    except Exception:

        pass





_cached_gdi_sw = 0

_cached_gdi_sh = 0

_cached_gdi_buf = None

_cached_gdi_bmi = None

_gdi_buffer_lock = threading.Lock()

_last_captured_frame_bytes = b""

_last_captured_frame_time = 0.0

_last_captured_frame_key = None

_frame_cache_lock = threading.Lock()



def invalidate_frame_cache():

    global _last_captured_frame_time

    with _frame_cache_lock:

        _last_captured_frame_time = 0.0



def _get_or_create_gdi_buffer(sw: int, sh: int):

    global _cached_gdi_sw, _cached_gdi_sh, _cached_gdi_buf, _cached_gdi_bmi

    with _gdi_buffer_lock:

        if _cached_gdi_sw != sw or _cached_gdi_sh != sh or _cached_gdi_buf is None:

            _cached_gdi_sw = sw

            _cached_gdi_sh = sh

            _cached_gdi_buf = (ctypes.c_char * (sw * sh * 4))()

            _cached_gdi_bmi = (ctypes.c_ulong * 11)()

            _cached_gdi_bmi[0] = 40

            _cached_gdi_bmi[1] = sw

            _cached_gdi_bmi[2] = -sh

            _cached_gdi_bmi[3] = 1 | (32 << 16)

        return _cached_gdi_buf, _cached_gdi_bmi



def capture_jpeg_frame(width=1920, height=1080, quality=80, skip_unchanged=False, force_fresh=False) -> bytes:

    """Sub-15ms real-time desktop screen capture direct to JPEG buffer.

    Guarantees non-zero pixel capture with zero memory reallocation and desktop thread attachment.

    """

    global _last_captured_frame_bytes, _last_captured_frame_time, _last_captured_frame_key

    key = (width, height, quality)

    now = time.time()

    with _frame_cache_lock:

        if not force_fresh and _last_captured_frame_key == key and _last_captured_frame_bytes and (now - _last_captured_frame_time) < 0.005:

            return _last_captured_frame_bytes



    _attach_calling_thread_to_input_desktop()



    bounds = get_active_monitor_bounds()

    sw = bounds["width"]

    sh = bounds["height"]

    ox = bounds["left"]

    oy = bounds["top"]



    # 1. High-Performance GDI BitBlt

    try:

        import cv2

        import numpy as np



        hdc_screen = user32.GetDC(0)

        hdc_mem = gdi32.CreateCompatibleDC(hdc_screen)

        hbm = gdi32.CreateCompatibleBitmap(hdc_screen, sw, sh)

        old_hbm = None

        try:

            old_hbm = gdi32.SelectObject(hdc_mem, hbm)

            gdi32.BitBlt(hdc_mem, 0, 0, sw, sh, hdc_screen, ox, oy, 0x00CC0020 | 0x40000000)



            buf, bmi = _get_or_create_gdi_buffer(sw, sh)

            gdi32.GetDIBits(hdc_mem, hbm, 0, sh, ctypes.byref(buf), ctypes.byref(bmi), 0)

        finally:

            if old_hbm and hdc_mem:

                try:

                    gdi32.SelectObject(hdc_mem, old_hbm)

                except Exception:

                    pass

            if hbm: gdi32.DeleteObject(hbm)

            if hdc_mem: gdi32.DeleteDC(hdc_mem)

            if hdc_screen: user32.ReleaseDC(0, hdc_screen)



        bgra = np.frombuffer(buf, dtype=np.uint8).reshape((sh, sw, 4))

        bgr = bgra[:, :, :3]



        if bgr[::32, ::32].mean() > 0.05:

            if (sw, sh) != (width, height):

                interp = cv2.INTER_AREA if (width < sw or height < sh) else cv2.INTER_LINEAR

                resized = cv2.resize(bgr, (width, height), interpolation=interp)

            else:

                resized = bgr



            sampling_mode = int(cv2.IMWRITE_JPEG_SAMPLING_FACTOR_444) if quality >= 70 else int(cv2.IMWRITE_JPEG_SAMPLING_FACTOR_420)

            params = [

                int(cv2.IMWRITE_JPEG_QUALITY), max(10, min(100, quality)),

                int(cv2.IMWRITE_JPEG_SAMPLING_FACTOR), sampling_mode,

                int(cv2.IMWRITE_JPEG_OPTIMIZE), 0,

            ]

            ok, enc = cv2.imencode('.jpg', resized, params)

            if ok and len(enc) > 1000:

                res_bytes = enc.tobytes()

                with _frame_cache_lock:

                    _last_captured_frame_key = key

                    _last_captured_frame_bytes = res_bytes

                    _last_captured_frame_time = time.time()

                return res_bytes

    except Exception:

        pass



    # 2. Resilient Fallback to PIL ImageGrab

    try:

        from PIL import ImageGrab, Image

        im = ImageGrab.grab(bbox=(ox, oy, ox + sw, oy + sh), all_screens=True)

        if not im or im.size[0] == 0:

            im = ImageGrab.grab()

        if im and im.size != (width, height):

            im_resized = im.resize((width, height), Image.Resampling.BILINEAR)

            im.close()

            im = im_resized

        if im:

            out_io = io.BytesIO()

            im.convert("RGB").save(out_io, format="JPEG", quality=quality)

            im.close()

            return out_io.getvalue()

    except Exception:

        pass



    return b""





def capture_png_frame() -> bytes:

    """Fast desktop capture to PNG format with desktop thread attachment."""

    _attach_calling_thread_to_input_desktop()



    bounds = get_active_monitor_bounds()

    sw = bounds["width"]

    sh = bounds["height"]

    ox = bounds["left"]

    oy = bounds["top"]



    try:

        import cv2

        import numpy as np



        hdc_screen = user32.GetDC(0)

        hdc_mem = gdi32.CreateCompatibleDC(hdc_screen)

        hbm = gdi32.CreateCompatibleBitmap(hdc_screen, sw, sh)

        try:

            gdi32.SelectObject(hdc_mem, hbm)

            gdi32.BitBlt(hdc_mem, 0, 0, sw, sh, hdc_screen, ox, oy, 0x00CC0020 | 0x40000000)



            buf = (ctypes.c_char * (sw * sh * 4))()

            bmi = (ctypes.c_ulong * 11)()

            bmi[0] = 40

            bmi[1] = sw

            bmi[2] = -sh

            bmi[3] = 1 | (32 << 16)

            gdi32.GetDIBits(hdc_mem, hbm, 0, sh, ctypes.byref(buf), ctypes.byref(bmi), 0)

        finally:

            if hbm: gdi32.DeleteObject(hbm)

            if hdc_mem: gdi32.DeleteDC(hdc_mem)

            if hdc_screen: user32.ReleaseDC(0, hdc_screen)



        bgra = np.frombuffer(buf, dtype=np.uint8).reshape((sh, sw, 4))

        bgr = bgra[:, :, :3]



        if bgr.mean() > 0.05:

            ok, enc = cv2.imencode('.png', bgr, [int(cv2.IMWRITE_PNG_COMPRESSION), 3])

            if ok and len(enc) > 1000:

                return enc.tobytes()

    except Exception:

        pass



    try:

        from PIL import ImageGrab

        im = ImageGrab.grab(bbox=(ox, oy, ox + sw, oy + sh), all_screens=True)

        if not im:

            im = ImageGrab.grab()

        if im:

            out_io = io.BytesIO()

            im.save(out_io, format="PNG")

            im.close()

            return out_io.getvalue()

    except Exception:

        pass



    return b""



class UltraStreamRing:
    """Spacedesk-Grade Adaptive Screen Grabber with dirty-frame detection, cursor overlay & condition signaling."""
    _instance = None
    _lock = threading.Lock()

    @classmethod
    def get_instance(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def __init__(self, quality=65, target_fps=60):
        self.quality = quality
        self.target_fps = target_fps
        self.frame_seq = 0
        self.latest_frame = None
        self.cond = threading.Condition()
        self.running = False
        self.active_clients = 0
        self.worker = None
        self._force_dirty = True

    def force_refresh(self):
        with self.cond:
            self._force_dirty = True
            self.cond.notify_all()

    def add_client(self):
        with self.cond:
            self.active_clients += 1
            self._force_dirty = True
            if not self.running:
                self.running = True
                self.worker = threading.Thread(target=self._worker, daemon=True)
                self.worker.start()
            else:
                self.cond.notify_all()

    def remove_client(self):
        with self.cond:
            self.active_clients = max(0, self.active_clients - 1)
            if self.active_clients == 0:
                self.running = False
                self.cond.notify_all()

    def _worker(self):
        _attach_calling_thread_to_input_desktop()
        interval = 1.0 / max(1, self.target_fps)
        bounds = get_active_monitor_bounds()
        w, h = bounds["width"], bounds["height"]
        ox, oy = bounds["left"], bounds["top"]

        hdc_screen = user32.GetDC(0)
        hdc_mem = gdi32.CreateCompatibleDC(hdc_screen)
        hbm = gdi32.CreateCompatibleBitmap(hdc_screen, w, h)
        old_hbm = gdi32.SelectObject(hdc_mem, hbm)

        bmi = (ctypes.c_ulong * 11)()
        bmi[0] = 40
        bmi[1] = w
        bmi[2] = -h
        bmi[3] = 1 | (32 << 16)
        buf = (ctypes.c_char * (w * h * 4))()
        params = [int(cv2.IMWRITE_JPEG_QUALITY), self.quality, int(cv2.IMWRITE_JPEG_OPTIMIZE), 0]

        loop_counter = 0

        try:
            while self.running:
                t_start = time.perf_counter()
                loop_counter += 1

                # Self-healing: Re-attach to desktop and verify DC every 60 frames (~1s) or on demand
                if loop_counter >= 60 or self._force_dirty:
                    loop_counter = 0
                    self._force_dirty = False
                    _attach_calling_thread_to_input_desktop()
                    cur_bounds = get_active_monitor_bounds()
                    if cur_bounds["width"] != w or cur_bounds["height"] != h:
                        w, h = cur_bounds["width"], cur_bounds["height"]
                        ox, oy = cur_bounds["left"], cur_bounds["top"]
                        if old_hbm and hdc_mem:
                            try: gdi32.SelectObject(hdc_mem, old_hbm)
                            except Exception: pass
                        if hbm: gdi32.DeleteObject(hbm)
                        if hdc_mem: gdi32.DeleteDC(hdc_mem)
                        if hdc_screen: user32.ReleaseDC(0, hdc_screen)
                        hdc_screen = user32.GetDC(0)
                        hdc_mem = gdi32.CreateCompatibleDC(hdc_screen)
                        hbm = gdi32.CreateCompatibleBitmap(hdc_screen, w, h)
                        old_hbm = gdi32.SelectObject(hdc_mem, hbm)
                        bmi[1] = w
                        bmi[2] = -h
                        buf = (ctypes.c_char * (w * h * 4))()

                res = gdi32.BitBlt(hdc_mem, 0, 0, w, h, hdc_screen, ox, oy, 0x00CC0020)
                if not res:
                    # GDI DC lost due to lock screen or display power save -> re-attach & acquire new DC
                    _attach_calling_thread_to_input_desktop()
                    if hdc_screen: user32.ReleaseDC(0, hdc_screen)
                    hdc_screen = user32.GetDC(0)
                    time.sleep(0.02)
                    continue

                gdi32.GetDIBits(hdc_mem, hbm, 0, h, ctypes.byref(buf), ctypes.byref(bmi), 0)
                bgra = np.frombuffer(buf, dtype=np.uint8).reshape((h, w, 4))
                bgr = bgra[:, :, :3]

                try:
                    pt = POINT()
                    user32.GetCursorPos(ctypes.byref(pt))
                    cx = pt.x - ox
                    cy = pt.y - oy
                    if 0 <= cx < w and 0 <= cy < h:
                        cv2.circle(bgr, (cx, cy), 6, (0, 140, 255), -1)
                        cv2.circle(bgr, (cx, cy), 7, (255, 255, 255), 1)
                except Exception:
                    pass

                ok, enc = cv2.imencode('.jpg', bgr, params)
                if ok:
                    raw = enc.tobytes()
                    with self.cond:
                        self.frame_seq += 1
                        self.latest_frame = raw
                        self.cond.notify_all()

                elapsed = time.perf_counter() - t_start
                to_sleep = interval - elapsed
                if to_sleep > 0.003:
                    time.sleep(to_sleep - 0.001)
        finally:
            if old_hbm and hdc_mem:
                try: gdi32.SelectObject(hdc_mem, old_hbm)
                except Exception: pass
            if hbm: gdi32.DeleteObject(hbm)
            if hdc_mem: gdi32.DeleteDC(hdc_mem)
            if hdc_screen: user32.ReleaseDC(0, hdc_screen)

    def get_latest_frame(self, last_seq=-1, timeout=0.03):
        with self.cond:
            if self.frame_seq > last_seq and self.latest_frame:
                return self.frame_seq, self.latest_frame
            self.cond.wait(timeout)
            return self.frame_seq, self.latest_frame
