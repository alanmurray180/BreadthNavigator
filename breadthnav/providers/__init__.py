from __future__ import annotations

from .base import Provider, ProviderError

_REGISTRY = {
    "yahoo": "breadthnav.providers.yahoo:YahooProvider",
    "alpaca": "breadthnav.providers.alpaca:AlpacaProvider",
    "fmp": "breadthnav.providers.fmp:FMPProvider",
}


def available() -> list[str]:
    return list(_REGISTRY)


def get_provider(name: str) -> Provider:
    """Instantiate a provider by name. Register new sources in _REGISTRY."""
    import importlib

    try:
        module, cls = _REGISTRY[name].split(":")
    except KeyError:
        raise ProviderError(f"unknown provider {name!r}; choose from {available()}")
    return getattr(importlib.import_module(module), cls)()


__all__ = ["Provider", "ProviderError", "available", "get_provider"]
