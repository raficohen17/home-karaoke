"""Use the OS trust store for TLS (works behind TLS-inspecting proxies)."""
import truststore

_done = False


def use_system_trust() -> None:
    global _done
    if not _done:
        truststore.inject_into_ssl()
        _done = True
