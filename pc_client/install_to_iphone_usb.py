# -*- coding: utf-8 -*-
import asyncio
import plistlib
import sys
import uuid
from pathlib import Path

from pymobiledevice3.lockdown import create_using_usbmux
from pymobiledevice3.services.mobile_config import MobileConfigService

from build_ios_ipa_bundle import create_app_icon

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def build_windrop_webclip_profile(lan_ip: str = "192.168.1.158", port: int = 8765) -> bytes:
    icon_bytes = create_app_icon(180)
    profile_data = {
        "PayloadContent": [
            {
                "FullScreen": True,
                "IgnoreManifestScope": True,
                "Icon": icon_bytes,
                "IsRemovable": True,
                "Label": "WinDrop",
                "PayloadDescription": "WinDrop — Windows <-> iPhone Kayıpsız AirDrop Uygulaması",
                "PayloadDisplayName": "WinDrop iOS App",
                "PayloadIdentifier": "com.tris.windrop.webclip",
                "PayloadType": "com.apple.webClip.managed",
                "PayloadUUID": str(uuid.uuid5(uuid.NAMESPACE_DNS, "com.tris.windrop.webclip")).upper(),
                "PayloadVersion": 1,
                "Precomposed": True,
                "URL": f"http://{lan_ip}:{port}",
            }
        ],
        "PayloadDescription": "WinDrop Kayıpsız Windows <-> iPhone Dosya Aktarım Uygulaması (Tam Ekran Yerel İkon)",
        "PayloadDisplayName": "WinDrop AirDrop",
        "PayloadIdentifier": "com.tris.windrop.profile",
        "PayloadOrganization": "WinDrop P2P",
        "PayloadRemovalDisallowed": False,
        "PayloadType": "Configuration",
        "PayloadUUID": str(uuid.uuid5(uuid.NAMESPACE_DNS, "com.tris.windrop.profile")).upper(),
        "PayloadVersion": 1,
    }
    return plistlib.dumps(profile_data, fmt=plistlib.FMT_XML)


async def install_app_to_connected_iphone() -> None:
    lockdown = await create_using_usbmux()
    print(f"[+] Bagli Cihaz: {lockdown.display_name} ({lockdown.product_type} - UDID: {lockdown.udid})")

    profile_bytes = build_windrop_webclip_profile("192.168.1.158", 8765)
    desktop_profile = Path(r"C:\Users\pc\Desktop\WinDrop_iOS_Kurulum.mobileconfig")
    desktop_profile.write_bytes(profile_bytes)

    mc = MobileConfigService(lockdown=lockdown)
    print("[*] MobileConfigService metodlari:", [m for m in dir(mc) if not m.startswith("_")])
    try:
        await mc.install_profile(profile_bytes)
        print("[+] BASARILI! WinDrop iOS Uygulamasi USB uzerinden dogrudan iPhone 13 ana ekranina KURULDU!")
    except Exception as e:
        print("[!] install_profile sonucu:", type(e).__name__, e)
        try:
            await mc.install_profile_silent(profile_bytes)
            print("[+] BASARILI (silent)! WinDrop iOS Uygulamasi USB uzerinden kuruldu!")
        except Exception as e2:
            print("[!] install_profile_silent sonucu:", type(e2).__name__, e2)

    profiles = await mc.get_profile_list()
    print("[+] iPhone'daki Mevcut Profiller:", profiles.get("OrderedIdentifiers"))


if __name__ == "__main__":
    asyncio.run(install_app_to_connected_iphone())
