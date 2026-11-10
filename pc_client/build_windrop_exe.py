import io
import subprocess
import sys
import shutil
import zipfile
import os
import time
from pathlib import Path

# Force UTF-8 stream wrapping to eliminate CP1254 crashes
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

BASE_DIR = Path(r"c:\Users\pc\Documents\projelerim\windrop_airdrop")
PACKAGE_DIR = Path(r"C:\Users\pc\Desktop\WinDrop_Arkadas_Paketi")
ZIP_DEST = Path(r"C:\Users\pc\Desktop\WinDrop_Arkadas_Paketi.zip")

build_dir = BASE_DIR / "build"
dist_dir = BASE_DIR / "dist"
if build_dir.exists():
    shutil.rmtree(build_dir, ignore_errors=True)
if dist_dir.exists():
    shutil.rmtree(dist_dir, ignore_errors=True)

# Kill any existing WinDrop process to release file lock on Desktop\WinDrop.exe
print("[*] Terminating existing WinDrop processes to release file locks...")
subprocess.run(["taskkill", "/f", "/im", "WinDrop.exe"], capture_output=True)
time.sleep(1)

cmd = [
    r"C:\Users\pc\AppData\Local\Programs\Python\Python312\python.exe",
    "-m", "PyInstaller",
    "--clean",
    str(BASE_DIR / "WinDrop.spec")
]

print("[*] Building WinDrop.exe via PyInstaller with WinDrop.spec...")
res = subprocess.run(cmd, cwd=str(BASE_DIR), capture_output=True, text=True, encoding="utf-8", errors="replace")
print("Returncode:", res.returncode)

if res.returncode == 0:
    exe_src = dist_dir / "WinDrop.exe"
    desktop_exe = Path(r"C:\Users\pc\Desktop\WinDrop.exe")
    package_exe = PACKAGE_DIR / "WinDrop.exe"

    def safe_copy(src, dst, max_retries=6):
        for i in range(max_retries):
            try:
                subprocess.run(["taskkill", "/f", "/im", "WinDrop.exe"], capture_output=True)
                time.sleep(0.5)
                shutil.copy2(src, dst)
                return True
            except PermissionError:
                time.sleep(1.0)
        return shutil.copy2(src, dst)

    if exe_src.exists():
        safe_copy(exe_src, BASE_DIR / "WinDrop.exe")
        safe_copy(exe_src, desktop_exe)
        PACKAGE_DIR.mkdir(parents=True, exist_ok=True)
        safe_copy(exe_src, package_exe)
        bat_src = BASE_DIR / "Guvenlik_Duvari_Izni_Ver.bat"
        if bat_src.exists():
            safe_copy(bat_src, PACKAGE_DIR / "Guvenlik_Duvari_Izni_Ver.bat")
            safe_copy(bat_src, Path(r"C:\Users\pc\Desktop\Guvenlik_Duvari_Izni_Ver.bat"))
        print(f"[+] WinDrop.exe placed at: {desktop_exe} ({exe_src.stat().st_size // (1024*1024)} MB)")

        # Smoke test new binary
        print("[*] Running smoke-test on fresh WinDrop.exe...")
        smoke = subprocess.run([str(desktop_exe), "--smoke-test"], capture_output=True, text=True, timeout=15)
        print(f"[+] Smoke test returncode: {smoke.returncode}")
        if smoke.stdout:
            print("[+] Smoke test stdout:", smoke.stdout.strip())

        # Recreate ZIP package
        if PACKAGE_DIR.exists():
            print(f"[+] Packaging {ZIP_DEST}...")
            with zipfile.ZipFile(ZIP_DEST, "w", zipfile.ZIP_DEFLATED) as zf:
                for root, dirs, files in os.walk(PACKAGE_DIR):
                    for file in files:
                        full_path = Path(root) / file
                        arcname = full_path.relative_to(PACKAGE_DIR.parent)
                        zf.write(full_path, arcname=str(arcname))
            print(f"[+] ZIP created successfully: {ZIP_DEST.stat().st_size // (1024*1024)} MB")

        # Launch fresh WinDrop.exe in background
        print("[*] Launching fresh WinDrop.exe in tray...")
        subprocess.Popen([str(desktop_exe), "--tray"], creationflags=0x00000008 | 0x00000200) # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        print("[+] Fresh WinDrop.exe launched successfully!")
else:
    print("STDOUT:", res.stdout[-2000:])
    print("STDERR:", res.stderr[-2000:])
