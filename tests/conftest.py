import ipaddress
import socket
import time

import pytest

from mesa_legal_data.sources import request_control

KNOWN_TEST_HOSTS = {
    "mevzuat.gov.tr": ["1.1.1.1"],
    "www.mevzuat.gov.tr": ["1.1.1.1"],
    "resmigazete.gov.tr": ["1.1.1.1"],
    "www.resmigazete.gov.tr": ["1.1.1.1"],
    "kararlarbilgibankasi.anayasa.gov.tr": ["1.1.1.1"],
    "karararama.yargitay.gov.tr": ["1.1.1.1"],
    "localhost": ["127.0.0.1"],
    "localhost.localdomain": ["127.0.0.1"],
    "127.0.0.1": ["127.0.0.1"],
    "192.168.1.1": ["192.168.1.1"],
    "10.0.0.1": ["10.0.0.1"],
    "169.254.169.254": ["169.254.169.254"],
}


@pytest.fixture(autouse=True)
def reset_request_control_state(monkeypatch):
    """
    Autouse fixture that resets process-global request control state between tests
    and injects a fast virtual clock/sleeper to eliminate real wall-clock delays in mocked tests.
    """
    request_control.reset_source_states()
    request_control.reset_run_budget()

    virtual_clock = [time.monotonic()]

    def fake_monotonic() -> float:
        return virtual_clock[0]

    def fake_sleep(seconds: float) -> None:
        if seconds > 0:
            virtual_clock[0] += seconds

    monkeypatch.setattr(request_control, "time_func", fake_monotonic)
    monkeypatch.setattr(request_control, "sleep_func", fake_sleep)

    yield
    request_control.reset_source_states()
    request_control.reset_run_budget()


@pytest.fixture(autouse=True)
def mock_dns(monkeypatch):
    """
    Autouse fixture that intercepts socket.getaddrinfo across all test suites,
    ensuring URL and security tests are 100% deterministic and offline.
    """
    custom_mappings: dict[str, list[str]] = {}

    def register_dns(host: str, *ips: str):
        custom_mappings[host.lower().rstrip(".")] = list(ips)

    def fake_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
        if not host:
            raise socket.gaierror(-2, "Name or service not known")

        norm_host = str(host).lower().rstrip(".")
        resolved_ips = custom_mappings.get(norm_host) or KNOWN_TEST_HOSTS.get(norm_host)

        if resolved_ips is None:
            try:
                ip_obj = ipaddress.ip_address(norm_host)
                resolved_ips = [str(ip_obj)]
            except ValueError:
                if (
                    "disallowed" in norm_host
                    or "attacker" in norm_host
                    or "example" in norm_host
                    or "safe" in norm_host
                ):
                    resolved_ips = ["1.1.1.1"]
                elif "invalid" in norm_host or "nonexistent" in norm_host:
                    raise socket.gaierror(-2, f"Name or service not known: {host}")
                else:
                    resolved_ips = ["1.1.1.1"]

        res = []
        for ip_str in resolved_ips:
            try:
                ip_obj = ipaddress.ip_address(ip_str)
                sock_fam = socket.AF_INET6 if ip_obj.version == 6 else socket.AF_INET
                target_port = port if isinstance(port, int) else 443
                res.append((sock_fam, socket.SOCK_STREAM, 6, "", (ip_str, target_port)))
            except ValueError:
                pass
        if not res:
            raise socket.gaierror(-2, f"Name or service not known: {host}")
        return res

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    return register_dns
