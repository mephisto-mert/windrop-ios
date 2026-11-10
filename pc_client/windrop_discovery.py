# -*- coding: utf-8 -*-
import io
import json
import os
import platform
import socket
import struct
import sys
import threading
import time
import uuid
from typing import Callable, Dict, List, Optional

import psutil
try:
    from zeroconf import IPVersion, ServiceInfo, Zeroconf
    HAS_ZEROCONF = True
except Exception:
    HAS_ZEROCONF = False
    Zeroconf = None
    ServiceInfo = None
    IPVersion = None

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

LOCALSEND_MULTICAST_GROUP = "224.0.0.167"
LOCALSEND_MULTICAST_PORT = 53317


def get_all_lan_ips() -> List[str]:
    """Returns all non-virtual, non-loopback IPv4 addresses."""
    virtual_keywords = ("vethernet", "wsl", "docker", "vmware", "vbox", "hyper-v", "loopback", "tailscale", "tun", "tap", "radmin", "hamachi")
    found: List[str] = []
    try:
        stats = psutil.net_if_stats()
        addrs = psutil.net_if_addrs()
        for iface, addr_list in addrs.items():
            iface_low = iface.lower()
            if any(k in iface_low for k in virtual_keywords):
                continue
            if iface in stats and not stats[iface].isup:
                continue
            for addr in addr_list:
                if addr.family == socket.AF_INET:
                    ip = addr.address
                    if not ip.startswith("127.") and not ip.startswith("169.254.") and not ip.startswith("192.168.56.") and not ip.startswith("25.") and not ip.startswith("26."):
                        found.append(ip)
    except Exception:
        pass
    return list(dict.fromkeys(found))


def get_best_lan_ip() -> str:
    """Finds the primary physical Wi-Fi / LAN IPv4 address (prioritizes default gateway route)."""
    # 1. Primary: Query OS routing table via dummy UDP socket to 8.8.8.8 (zero packets sent)
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            route_ip = s.getsockname()[0]
            if route_ip and not route_ip.startswith("127.") and not route_ip.startswith("169.254.") and not route_ip.startswith("192.168.56.") and not route_ip.startswith("25.") and not route_ip.startswith("26."):
                return route_ip
    except Exception:
        pass

    # 2. Secondary: Inspect physical interfaces (prioritize iPhone Hotspot 172.20.10.x, then Wi-Fi)
    all_ips = get_all_lan_ips()
    for ip in all_ips:
        if ip.startswith("172.20.10."):
            return ip
    if all_ips:
        return all_ips[0]

    return "127.0.0.1"


class WinDropDiscoveryService:
    """Handles Apple Bonjour (mDNS) registration + LocalSend UDP Multicast radar discovery."""

    def __init__(self, port: int = 8765, device_name: Optional[str] = None, on_peer_update: Optional[Callable[[Dict], None]] = None):
        self.port = port
        self.device_name = device_name or f"{platform.node()} (WinDrop)"
        self.fingerprint = uuid.uuid5(uuid.NAMESPACE_DNS, platform.node()).hex[:32]
        self.lan_ip = get_best_lan_ip()
        self.on_peer_update = on_peer_update
        self.peers: Dict[str, Dict] = {}
        self._running = False
        self._zeroconf: Optional[Zeroconf] = None
        self._service_infos: List[ServiceInfo] = []
        self._threads: List[threading.Thread] = []

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self.lan_ip = get_best_lan_ip()

        t_mdns = threading.Thread(target=self._register_mdns, daemon=True)
        t_udp_listen = threading.Thread(target=self._udp_multicast_listener, daemon=True)
        t_udp_announce = threading.Thread(target=self._udp_multicast_announcer, daemon=True)
        self._threads = [t_mdns, t_udp_listen, t_udp_announce]
        for t in self._threads:
            t.start()

    def stop(self) -> None:
        self._running = False
        if self._zeroconf:
            try:
                for info in self._service_infos:
                    self._zeroconf.unregister_service(info)
                self._zeroconf.close()
            except Exception:
                pass

    def register_active_peer(self, ip: str, name: str, model: str = "iPhone", via: str = "iOS Safari Radar") -> Dict:
        peer_id = f"{ip}:{model}"
        peer_data = {
            "id": peer_id,
            "ip": ip,
            "name": name,
            "model": model,
            "via": via,
            "last_seen": time.time(),
            "online": True,
        }
        self.peers[peer_id] = peer_data
        if self.on_peer_update:
            try:
                self.on_peer_update(peer_data)
            except Exception:
                pass
        return peer_data

    def get_active_peers(self) -> List[Dict]:
        now = time.time()
        active = []
        for pid, p in list(self.peers.items()):
            # Devices seen within the last 30 minutes are considered active/online
            p["online"] = (now - p.get("last_seen", 0)) < 1800
            active.append(p)
        return sorted(active, key=lambda x: x.get("last_seen", 0), reverse=True)

    def _register_mdns(self) -> None:
        if not HAS_ZEROCONF:
            return
        try:
            self._zeroconf = Zeroconf(ip_version=IPVersion.V4Only)
            ip_bytes = socket.inet_aton(self.lan_ip)
            props = {
                b"alias": self.device_name.encode("utf-8"),
                b"version": b"2.1",
                b"deviceModel": b"Windows 11 PC",
                b"deviceType": b"desktop",
                b"fingerprint": self.fingerprint.encode("utf-8"),
                b"lossless": b"sha256-raw",
            }
            info_airdrop = ServiceInfo(
                "_http._tcp.local.",
                "WinDrop AirDrop._http._tcp.local.",
                addresses=[ip_bytes],
                port=self.port,
                properties=props,
                server="windrop.local.",
            )
            self._zeroconf.register_service(info_airdrop)
            self._service_infos.append(info_airdrop)

            info_airdrop_plus = ServiceInfo(
                "_http._tcp.local.",
                "AirDrop Plus._http._tcp.local.",
                addresses=[ip_bytes],
                port=53843,
                properties={b"path": b"/"},
                server="YourPcName.local.",
            )
            self._zeroconf.register_service(info_airdrop_plus)
            self._service_infos.append(info_airdrop_plus)
        except Exception:
            pass

    def _udp_multicast_listener(self) -> None:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("", LOCALSEND_MULTICAST_PORT))
            mreq = struct.pack("4s4s", socket.inet_aton(LOCALSEND_MULTICAST_GROUP), socket.inet_aton("0.0.0.0"))
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
            sock.settimeout(2.0)
            while self._running:
                try:
                    data, addr = sock.recvfrom(4096)
                    if addr[0] == self.lan_ip:
                        continue
                    payload = json.loads(data.decode("utf-8", errors="ignore"))
                    if payload.get("fingerprint") == self.fingerprint:
                        continue
                    alias = payload.get("alias") or f"Cihaz ({addr[0]})"
                    model = payload.get("deviceModel") or "iPhone / iOS"
                    self.register_active_peer(addr[0], alias, model=model, via="Multicast Radar")
                except socket.timeout:
                    continue
                except Exception:
                    continue
        except Exception:
            pass

    def _udp_multicast_announcer(self) -> None:
        packet = json.dumps({
            "alias": self.device_name,
            "version": "2.1",
            "deviceModel": "Windows 11 Pro",
            "deviceType": "desktop",
            "fingerprint": self.fingerprint,
            "port": self.port,
            "protocol": "http",
            "download": True,
            "announce": True,
        }).encode("utf-8")
        while self._running:
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP) as s:
                    s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
                    s.sendto(packet, (LOCALSEND_MULTICAST_GROUP, LOCALSEND_MULTICAST_PORT))
            except Exception:
                pass
            time.sleep(5.0)
