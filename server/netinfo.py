"""Find the address your phone can use to reach this computer."""

import socket


def lan_ips() -> list[str]:
    ips: set[str] = set()
    # The address used to reach the internet is almost always the Wi-Fi/Ethernet one.
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            ips.add(s.getsockname()[0])
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except OSError:
        pass
    return sorted(ip for ip in ips if not ip.startswith("127."))


def phone_urls(port: int) -> list[str]:
    return [f"http://{ip}:{port}" for ip in lan_ips()]
