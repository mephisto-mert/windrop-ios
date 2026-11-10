# -*- coding: utf-8 -*-
import asyncio
import hashlib
import json
import os
import plistlib
import socket
import struct
import sys
import time
from pathlib import Path
from typing import Dict, List

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def check_usbmuxd_raw() -> Dict:
    """Zero-dependency pure stdlib check against Apple Mobile Device Service (127.0.0.1:27015)."""
    try:
        payload = plistlib.dumps({
            "MessageType": "ListDevices",
            "ClientVersionString": "WinDrop-USB-2.0",
            "ProgName": "WinDrop",
            "kLibUSBMuxVersion": 3,
        })
        header = struct.pack("<IIII", 16 + len(payload), 1, 8, 1)
        with socket.create_connection(("127.0.0.1", 27015), timeout=0.6) as sock:
            sock.sendall(header + payload)
            resp_hdr = sock.recv(16)
            if len(resp_hdr) < 16:
                return {"connected": False}
            total_len = struct.unpack("<I", resp_hdr[:4])[0]
            body_len = total_len - 16
            body = b""
            while len(body) < body_len:
                chunk = sock.recv(body_len - len(body))
                if not chunk:
                    break
                body += chunk
            data = plistlib.loads(body)
            dev_list = data.get("DeviceList", [])
            for dev in dev_list:
                props = dev.get("Properties", {})
                if props.get("ConnectionType") == "USB":
                    udid = props.get("SerialNumber") or ""
                    return {
                        "connected": True,
                        "name": "iPhone (USB Kablo)",
                        "model": f"PID:{props.get('ProductID', '')}",
                        "udid": udid,
                    }
    except Exception as e:
        return {"connected": False, "error": str(e)}
    return {"connected": False}


async def usb_status() -> Dict:
    raw = check_usbmuxd_raw()
    try:
        from pymobiledevice3.lockdown import create_using_usbmux
        ld = create_using_usbmux()
        if inspect_coro := getattr(ld, "__await__", None):
            ld = await ld
        return {
            "connected": True,
            "name": getattr(ld, "display_name", None) or "iPhone",
            "model": getattr(ld, "product_type", None) or "iPhone",
            "ios": getattr(ld, "product_version", None) or "",
            "udid": getattr(ld, "udid", None) or raw.get("udid", ""),
        }
    except Exception as e:
        if raw.get("connected"):
            return raw
        return {"connected": False, "error": str(e)}


async def _get_lockdown():
    from pymobiledevice3.lockdown import create_using_usbmux
    ld = create_using_usbmux()
    if hasattr(ld, "__await__"):
        ld = await ld
    return ld


async def usb_push_files(file_paths: List[str]) -> Dict:
    from pymobiledevice3.services.house_arrest import HouseArrestService
    lockdown = await _get_lockdown()
    target_bundles = ["com.anydesk.AnyDesk", "com.blackmagic-design.DaVinciCamera"]
    pushed_results = []

    for fpath in file_paths:
        p = Path(fpath)
        if not p.exists() or not p.is_file():
            continue
        raw_bytes = p.read_bytes()
        sha256_hex = hashlib.sha256(raw_bytes).hexdigest()
        t0 = time.perf_counter()
        delivered_to = []

        for bid in target_bundles:
            try:
                ha = await HouseArrestService.create(lockdown=lockdown, bundle_id=bid, documents_only=True)
                remote_file = f"/Documents/{p.name}"
                await ha.set_file_contents(remote_file, raw_bytes)
                await ha.close()
                app_label = "AnyDesk" if "anydesk" in bid else "Blackmagic Cam"
                delivered_to.append(f"Dosyalar ➔ iPhone'umda ➔ {app_label} ➔ {p.name}")
            except Exception:
                continue

        elapsed = max(time.perf_counter() - t0, 0.001)
        mbps = round((len(raw_bytes) / 1048576.0) / elapsed, 2)
        pushed_results.append({
            "name": p.name,
            "size": len(raw_bytes),
            "sha256": sha256_hex,
            "speed_mbps": mbps,
            "locations": delivered_to,
        })

    return {"status": "ok", "iphone": lockdown.display_name, "files": pushed_results}


async def usb_pull_latest_dcim(dest_dir: str, limit: int = 10) -> Dict:
    from pymobiledevice3.services.afc import AfcService
    lockdown = await _get_lockdown()
    afc = AfcService(lockdown=lockdown)
    out_dir = Path(dest_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    dcim_folders = await afc.listdir("/DCIM")
    apple_folders = sorted([d for d in dcim_folders if d.endswith("APPLE")], reverse=True)
    media_candidates = []

    for folder in apple_folders:
        items = await afc.listdir(f"/DCIM/{folder}")
        for fn in sorted(items, reverse=True):
            if fn.startswith(".") or fn.endswith(".AAE"):
                continue
            media_candidates.append((f"/DCIM/{folder}/{fn}", fn))
            if len(media_candidates) >= limit:
                break
        if len(media_candidates) >= limit:
            break

    pulled = []
    for remote_path, fname in media_candidates:
        t0 = time.perf_counter()
        raw_bytes = await afc.get_file_contents(remote_path)
        sha_hex = hashlib.sha256(raw_bytes).hexdigest()
        local_path = out_dir / fname
        local_path.write_bytes(raw_bytes)
        elapsed = max(time.perf_counter() - t0, 0.001)
        mbps = round((len(raw_bytes) / 1048576.0) / elapsed, 2)
        pulled.append({
            "name": fname,
            "path": str(local_path),
            "size": len(raw_bytes),
            "sha256": sha_hex,
            "speed_mbps": mbps,
        })

    return {"status": "ok", "count": len(pulled), "files": pulled}


async def usb_install_app_profile(lan_ip: str = "192.168.1.158") -> Dict:
    from pymobiledevice3.services.mobile_config import MobileConfigService
    from install_to_iphone_usb import build_windrop_webclip_profile
    lockdown = await _get_lockdown()
    mc = MobileConfigService(lockdown=lockdown)
    profile_bytes = build_windrop_webclip_profile(lan_ip, 8765)
    res = mc.install_profile(profile_bytes)
    if hasattr(res, "__await__"):
        await res
    return {
        "status": "ok",
        "device": lockdown.display_name,
        "udid": lockdown.udid,
        "message": "WinDrop uygulama profili USB kablosuyla iPhone'a gönderildi!",
    }


async def usb_auto_sync_loop(engine=None) -> None:
    """Continuously watches USB-connected iPhone and pulls newly taken photos/screenshots to Desktop."""
    try:
        from pymobiledevice3.lockdown import create_using_usbmux
        from pymobiledevice3.services.afc import AfcService
    except ImportError:
        return

    dest_dir = getattr(engine, "receive_dir", None) or Path(r"C:\Users\pc\Desktop\WinDrop_Alinanlar")
    dest_dir = Path(dest_dir)
    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        return
    synced_log = dest_dir / ".synced_media.txt"
    synced = set()
    if synced_log.exists():
        try:
            synced = set(synced_log.read_text(encoding="utf-8").splitlines())
        except Exception:
            pass

    first_scan = True
    while True:
        try:
            ld = create_using_usbmux()
            if hasattr(ld, "__await__"):
                ld = await ld
            afc = AfcService(lockdown=ld)
            dcim_dirs = [d for d in await afc.listdir("/DCIM") if d.endswith("APPLE")]
            dcim_dirs.sort()
            if dcim_dirs:
                latest_dir = f"/DCIM/{dcim_dirs[-1]}"
                files = [f for f in await afc.listdir(latest_dir) if not f.startswith(".")]
                if first_scan and not synced_log.exists():
                    for fn in files:
                        synced.add(fn)
                    synced_log.write_text("\n".join(synced) + "\n", encoding="utf-8")
                    first_scan = False
                    await asyncio.sleep(2.5)
                    continue
                first_scan = False
                files.sort(reverse=True)
                for fn in files:
                    if fn in synced:
                        continue
                    try:
                        st = await afc.stat(f"{latest_dir}/{fn}")
                        size = st.get("st_size", 0)
                        if size > 300 * 1024 * 1024:
                            continue
                        loc_path = dest_dir / fn
                        if not loc_path.exists():
                            data = await afc.get_file_contents(f"{latest_dir}/{fn}")
                            loc_path.write_bytes(data)
                            if engine and hasattr(engine, "_emit"):
                                engine._emit("file_received", {"name": fn, "size": len(data), "path": str(loc_path)})
                        synced.add(fn)
                        with open(synced_log, "a", encoding="utf-8") as f:
                            f.write(f"{fn}\n")
                    except Exception:
                        pass
        except Exception:
            pass
        await asyncio.sleep(2.5)


def cli_main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "status":
        res = asyncio.run(usb_status())
    elif cmd == "push":
        res = asyncio.run(usb_push_files(sys.argv[2:]))
    elif cmd == "pull-dcim":
        dest = sys.argv[2] if len(sys.argv) > 2 else r"C:\Users\pc\Desktop\WinDrop_Alinanlar"
        cnt = int(sys.argv[3]) if len(sys.argv) > 3 else 5
        res = asyncio.run(usb_pull_latest_dcim(dest, cnt))
    elif cmd == "install-profile":
        ip = sys.argv[2] if len(sys.argv) > 2 else "192.168.1.158"
        res = asyncio.run(usb_install_app_profile(ip))
    else:
        res = {"error": f"Unknown command: {cmd}"}
    print(json.dumps(res, ensure_ascii=False))


if __name__ == "__main__":
    cli_main()
