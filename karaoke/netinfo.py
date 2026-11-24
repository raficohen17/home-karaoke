"""Pick the LAN address guests' phones can reach."""
from __future__ import annotations

import ipaddress
import re
import subprocess

_IFACE = re.compile(r"^(\S+?):\s+flags=")
_INET = re.compile(r"^\s+inet (\d+\.\d+\.\d+\.\d+)")


def parse_ifconfig(text: str) -> list[tuple[str, str]]:
    """[(interface, ipv4)] from macOS/BSD `ifconfig` output."""
    out, iface = [], None
    for line in text.splitlines():
        m = _IFACE.match(line)
        if m:
            iface = m.group(1)
            continue
        m = _INET.match(line)
        if m and iface:
            out.append((iface, m.group(1)))
    return out


def pick_lan_ip(addrs: list[tuple[str, str]]) -> str | None:
    """Prefer Wi-Fi/Ethernet (en*, eth*, wl*) private IPv4; skip loopback, VPN tunnels, bridges."""

    def rank(item):
        iface, ip = item
        a = ipaddress.ip_address(ip)
        if a.is_loopback or a.is_link_local or not a.is_private:
            return None
        if iface.startswith(("utun", "tun", "tap", "ppp", "ipsec", "bridge", "vmnet", "docker", "lo")):
            return None
        physical = 0 if iface.startswith(("en", "eth", "wl")) else 1
        home = 0 if ip.startswith("192.168.") else 1 if ip.startswith("10.") else 2
        return (physical, home, iface)

    ranked = sorted((r, ip) for (iface, ip) in addrs if (r := rank((iface, ip))) is not None)
    return ranked[0][1] if ranked else None


def lan_ip() -> str:
    try:
        text = subprocess.run(["ifconfig"], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.TimeoutExpired):
        text = ""
    return pick_lan_ip(parse_ifconfig(text)) or "127.0.0.1"
