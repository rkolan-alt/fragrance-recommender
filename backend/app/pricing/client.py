"""Quota-capped Amazon US search provider."""

import httpx


class PricingError(Exception):
    """Safe error: never include a provider URL containing an API key."""


class PricingQuotaError(PricingError):
    pass


class SerpApiClient:
    def __init__(self, key: str, transport=None, *, reserve=None, response_sink=None):
        self.key, self.transport = key, transport
        self.reserve = reserve
        self.response_sink = response_sink

    async def _request(self, params):
        if not self.key:
            raise PricingError("Pricing provider not configured")
        if self.reserve is not None and not await self.reserve():
            raise PricingQuotaError("Daily pricing query cap reached")
        try:
            async with httpx.AsyncClient(timeout=30, transport=self.transport) as client:
                response = await client.get(
                    "https://serpapi.com/search.json",
                    params={**params, "api_key": self.key},
                )
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError):
            raise PricingError("Pricing provider request failed") from None
        if not isinstance(payload, dict) or payload.get("error"):
            raise PricingError("Pricing provider returned an error")
        if self.response_sink is not None:
            self.response_sink(payload)
        return payload

    async def search(self, brand: str, name: str) -> list[dict]:
        payload = await self._request(
            {"engine": "amazon", "amazon_domain": "amazon.com", "k": f"{brand} {name} 100 ml"}
        )
        return amazon_offers(payload)


def amazon_offers(payload):
    offers = []
    for result in payload.get("organic_results") or []:
        if not isinstance(result, dict) or result.get("no_featured_offers_available"):
            continue
        offers.append(
            {
                **result,
                "source": "Amazon",
                "link": result.get("link_clean") or result.get("link"),
                "details_and_offers": [str(result.get("stock", ""))],
            }
        )
    return offers
