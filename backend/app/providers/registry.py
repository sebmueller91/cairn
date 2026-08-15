from app.providers.base import PriceProvider
from app.providers.coingecko import CoinGeckoProvider
from app.providers.frankfurter import FrankfurterProvider
from app.providers.stooq import StooqProvider
from app.providers.yahoo import YahooFinanceProvider

_REGISTRY: dict[str, PriceProvider] = {
    # Stooq's CSV endpoints now gate behind a JS bot challenge (found via
    # live testing against the deployed app, 2026-08-15) — kept registered
    # since the adapter itself still works fine if that ever reverts, but
    # Yahoo is the one actually configured on instruments for now.
    "stooq": StooqProvider(),
    "yahoo": YahooFinanceProvider(),
    "coingecko": CoinGeckoProvider(),
    "frankfurter": FrankfurterProvider(),
}


def get_provider(name: str) -> PriceProvider:
    try:
        return _REGISTRY[name]
    except KeyError:
        raise ValueError(f"unknown price provider: {name}") from None


def known_provider_names() -> list[str]:
    return list(_REGISTRY)
