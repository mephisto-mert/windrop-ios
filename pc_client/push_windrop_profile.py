# -*- coding: utf-8 -*-
import asyncio
import sys
from pathlib import Path

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from pymobiledevice3.lockdown import create_using_usbmux
from pymobiledevice3.services.mobile_config import MobileConfigService
from install_to_iphone_usb import build_windrop_webclip_profile
from windrop_discovery import get_best_lan_ip


async def main():
    lan_ip = get_best_lan_ip() or "192.168.1.158"
    print(f"[*] Connecting to iPhone over USB via usbmuxd (Target PC IP: {lan_ip}:8765)...")
    ld = create_using_usbmux()
    if hasattr(ld, "__await__"):
        ld = await ld
    print(f"[+] Connected to: {ld.display_name} ({ld.product_type} - iOS {ld.product_version} - UDID: {ld.udid})")

    mcs = MobileConfigService(ld)
    profile_bytes = build_windrop_webclip_profile(lan_ip, 8765)

    desktop_profile = Path(r"C:\Users\pc\Desktop\WinDrop_iOS_Kurulum.mobileconfig")
    desktop_profile.write_bytes(profile_bytes)

    print(f"[*] Pushing standalone WinDrop direct app profile (http://{lan_ip}:8765) to iPhone...")
    res = mcs.install_profile(profile_bytes)
    if hasattr(res, "__await__"):
        await res
    print("[+] WinDrop direct IP:Port app profile successfully installed/sent to iPhone!")


if __name__ == "__main__":
    asyncio.run(main())
