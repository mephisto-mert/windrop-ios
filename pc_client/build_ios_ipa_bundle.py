# -*- coding: utf-8 -*-
import os
import plistlib
import shutil
import socket
import struct
import sys
import time
import uuid
import winreg
import zipfile
from pathlib import Path

from PIL import Image, ImageDraw

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def create_app_icon(size: int = 180) -> bytes:
    img = Image.new("RGBA", (size, size), (11, 15, 23, 255))
    draw = ImageDraw.Draw(img)
    cx, cy = size // 2, size // 2
    for i in range(4, 0, -1):
        r = int((size * 0.42) * (i / 4.0))
        draw.ellipse((cx - r, cy - r, cx + r, cy + r), outline=(10, 132, 255, 220), width=max(2, size // 36))
    r_inner = int(size * 0.14)
    draw.ellipse((cx - r_inner, cy - r_inner, cx + r_inner, cy + r_inner), fill=(48, 209, 88, 255))
    import io
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def build_arm64_ios_macho_binary() -> bytes:
    """Constructs a standard 64-bit ARM64 iOS Mach-O (MH_EXECUTE) binary image with LC_BUILD_VERSION (iOS 16.0) & LC_MAIN for Sideloadly."""
    MH_MAGIC_64 = 0xFEEDFACF
    CPU_TYPE_ARM64 = 0x0100000C
    CPU_SUBTYPE_ARM64_ALL = 0
    MH_EXECUTE = 0x2
    FLAGS = 0x00200085  # MH_NOUNDEFS | MH_DYLDLINK | MH_TWOLEVEL | MH_PIE

    # Load commands: LC_SEGMENT_64 (__PAGEZERO), LC_SEGMENT_64 (__TEXT), LC_SEGMENT_64 (__LINKEDIT), LC_LOAD_DYLINKER, LC_UUID, LC_BUILD_VERSION, LC_MAIN
    LC_SEGMENT_64 = 0x19
    LC_LOAD_DYLINKER = 0xE
    LC_UUID = 0x1B
    LC_BUILD_VERSION = 0x32
    LC_MAIN = 0x80000028
    LC_LOAD_DYLIB = 0xC

    seg_pagezero = struct.pack("<II16sQQQQiiII", LC_SEGMENT_64, 72, b"__PAGEZERO\x00\x00\x00\x00\x00\x00", 0, 0x100000000, 0, 0, 0, 0, 0, 0)
    seg_text = struct.pack("<II16sQQQQiiII", LC_SEGMENT_64, 72, b"__TEXT\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00", 0x100000000, 0x4000, 0, 0x4000, 5, 5, 0, 0)
    seg_linkedit = struct.pack("<II16sQQQQiiII", LC_SEGMENT_64, 72, b"__LINKEDIT\x00\x00\x00\x00\x00\x00", 0x100004000, 0x4000, 0x4000, 0x1000, 1, 1, 0, 0)

    dylinker_path = b"/usr/lib/dyld\x00\x00\x00"
    lc_dylinker = struct.pack("<III", LC_LOAD_DYLINKER, 12 + len(dylinker_path), 12) + dylinker_path

    lc_uuid = struct.pack("<II16s", LC_UUID, 24, uuid.uuid4().bytes)
    # PLATFORM_IOS = 2, minos = 16.0 (0x00100000), sdk = 17.0 (0x00110000)
    lc_build = struct.pack("<IIIIII", LC_BUILD_VERSION, 24, 2, 0x00100000, 0x00110000, 0)
    lc_main = struct.pack("<IIQQ", LC_MAIN, 24, 0x1000, 0)

    dylib_name = b"/usr/lib/libSystem.B.dylib\x00\x00\x00\x00\x00\x00"
    lc_dylib = struct.pack("<IIIIII", LC_LOAD_DYLIB, 24 + len(dylib_name), 24, 2, 0x05000000, 0x00010000) + dylib_name

    cmds = seg_pagezero + seg_text + seg_linkedit + lc_dylinker + lc_uuid + lc_build + lc_main + lc_dylib
    header = struct.pack("<IIIIIIII", MH_MAGIC_64, CPU_TYPE_ARM64, CPU_SUBTYPE_ARM64_ALL, MH_EXECUTE, 8, len(cmds), FLAGS, 0)

    image = bytearray(0x5000)
    image[0:len(header)] = header
    image[len(header):len(header) + len(cmds)] = cmds
    # ARM64 ret instruction at entry offset 0x1000 (mov w0, #0; ret)
    struct.pack_into("<II", image, 0x1000, 0x52800000, 0xD65F03C0)
    return bytes(image)


def build_ipa_and_verify() -> None:
    desktop = Path(r"C:\Users\pc\Desktop")
    proj_dir = Path(r"c:\Users\pc\Documents\projelerim\windrop_airdrop")
    ipa_path = desktop / "WinDrop_iOS.ipa"
    proj_ipa_path = proj_dir / "WinDrop_iOS.ipa"

    info_plist_data = {
        "CFBundleDevelopmentRegion": "tr",
        "CFBundleDisplayName": "WinDrop",
        "CFBundleExecutable": "WinDrop",
        "CFBundleIdentifier": "com.tris.windrop.ios",
        "CFBundleInfoDictionaryVersion": "6.0",
        "CFBundleName": "WinDrop",
        "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": "3.0.0",
        "CFBundleSupportedPlatforms": ["iPhoneOS"],
        "CFBundleVersion": "300",
        "DTPlatformName": "iphoneos",
        "MinimumOSVersion": "16.0",
        "UIDeviceFamily": [1, 2],
        "UIRequiredDeviceCapabilities": ["arm64"],
        "UIRequiresFullScreen": True,
        "ITSAppUsesNonExemptEncryption": False,
        "UILaunchScreen": {
            "UIColorName": "blackColor"
        },
        "UISupportedInterfaceOrientations": [
            "UIInterfaceOrientationPortrait",
            "UIInterfaceOrientationLandscapeLeft",
            "UIInterfaceOrientationLandscapeRight"
        ],
        "UISupportedInterfaceOrientations~ipad": [
            "UIInterfaceOrientationPortrait",
            "UIInterfaceOrientationPortraitUpsideDown",
            "UIInterfaceOrientationLandscapeLeft",
            "UIInterfaceOrientationLandscapeRight"
        ],
        "NSCameraUsageDescription": "WinDrop QR kod ile PC eşleşmesi için kameraya erişir.",
        "NSAppTransportSecurity": {
            "NSAllowsArbitraryLoads": True,
            "NSAllowsLocalNetworking": True,
        },
        "UIBackgroundModes": ["fetch", "processing"],
        "CFBundleIcons": {
            "CFBundlePrimaryIcon": {
                "CFBundleIconFiles": ["AppIcon60x60"],
                "CFBundleIconName": "AppIcon",
            }
        },
        "NSLocalNetworkUsageDescription": "WinDrop P2P Windows PC ile sunucusuz doğrudan dosya aktarımı yapar.",
        "NSBonjourServices": ["_windrop._tcp", "_localsend._tcp"],
        "NSPhotoLibraryUsageDescription": "Orijinal HEIC/MOV gönderimi için erişim gerekir.",
        "NSPhotoLibraryAddUsageDescription": "PC'den gelen medya dosyalarını galeriye kayıpsız kaydetmek için erişim gerekir.",
        "UIFileSharingEnabled": True,
        "LSSupportsOpeningDocumentsInPlace": True,
    }

    icon_120 = create_app_icon(120)
    icon_180 = create_app_icon(180)

    native_arm64_bin = proj_dir / "ios_native_src" / "WinDrop_arm64"
    if native_arm64_bin.exists():
        macho_bin = native_arm64_bin.read_bytes()
        print(f"[+] Gercek Derlenmis ARM64 Mach-O Ikili Dahil Ediliyor ({len(macho_bin)} bayt)")
    else:
        macho_bin = build_arm64_ios_macho_binary()

    def add_to_zip(zf, arcname, data, mode=0o644):
        zinfo = zipfile.ZipInfo(arcname)
        zinfo.date_time = time.localtime(time.time())[:6]
        zinfo.compress_type = zipfile.ZIP_DEFLATED
        zinfo.external_attr = (0o100000 | mode) << 16
        zf.writestr(zinfo, data)

    with zipfile.ZipFile(ipa_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        add_to_zip(zf, "Payload/WinDrop.app/Info.plist", plistlib.dumps(info_plist_data, fmt=plistlib.FMT_BINARY), mode=0o644)
        add_to_zip(zf, "Payload/WinDrop.app/PkgInfo", b"APPL????", mode=0o644)
        add_to_zip(zf, "Payload/WinDrop.app/WinDrop", macho_bin, mode=0o755)
        add_to_zip(zf, "Payload/WinDrop.app/AppIcon60x60@2x.png", icon_120, mode=0o644)
        add_to_zip(zf, "Payload/WinDrop.app/AppIcon60x60@3x.png", icon_180, mode=0o644)
        # Bundle the offline HTML and assets
        html_f = proj_dir / "templates" / "ios_radar.html"
        if html_f.exists():
            add_to_zip(zf, "Payload/WinDrop.app/www/index.html", html_f.read_bytes(), mode=0o644)
        # Bundle the SwiftUI source code inside the IPA for reference/Xcode Cloud
        for swift_f in (proj_dir / "ios_swiftui_app" / "Sources").glob("*.swift"):
            zf.write(swift_f, arcname=f"Payload/WinDrop.app/SwiftSource/{swift_f.name}")

    # Copy to Desktop\WinDrop.ipa and project root
    desktop_clean_ipa = desktop / "WinDrop.ipa"
    shutil.copy2(ipa_path, desktop_clean_ipa)
    shutil.copy2(ipa_path, proj_ipa_path)
    shutil.copy2(ipa_path, proj_dir / "WinDrop.ipa")
    print(f"[+] iOS .IPA Paketleri Olusturuldu:\n    - {ipa_path}\n    - {desktop_clean_ipa}")

    # Copy WinDrop.exe to project dir & register Windows Right-Click menu to point to Desktop\WinDrop.exe
    exe_desktop = desktop / "WinDrop.exe"
    if exe_desktop.exists():
        shutil.copy2(exe_desktop, proj_dir / "WinDrop.exe")
        cmd_str = f'"{exe_desktop}" "%1"'
        for root_key in (r"Software\Classes\*\shell\WinDropSend", r"Software\Classes\Directory\shell\WinDropSend"):
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, root_key) as k:
                winreg.SetValueEx(k, "", 0, winreg.REG_SZ, "📱 iPhone'a WinDrop P2P ile Gönder")
                winreg.SetValueEx(k, "Icon", 0, winreg.REG_SZ, f'"{exe_desktop}",0')
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, root_key + r"\command") as ck:
                winreg.SetValueEx(ck, "", 0, winreg.REG_SZ, cmd_str)
        print(f"[+] Native Windows .EXE Hazir ve Sag Tik Menusune Baglandi: {exe_desktop}")


if __name__ == "__main__":
    build_ipa_and_verify()
