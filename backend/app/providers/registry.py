from app.providers.base import PriceProvider
from app.providers.coingecko import CoinGeckoProvider
from app.providers.frankfurter import FrankfurterProvider
from app.providers.stooq import StooqProvider

_REGISTRY: dict[str, PriceProvider] = {
    "stooq": StooqProvider(),
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
