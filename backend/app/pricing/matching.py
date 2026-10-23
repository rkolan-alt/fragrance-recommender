"""Conservative retail matching: same scent/concentration; full bottles only."""

import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from urllib.parse import unquote, urlparse

CONCENTRATIONS = {
    "extrait": r"\b(?:extrait(?: de parfum)?|parfum extract)\b",
    "edp": r"\b(?:eau de parfum|edp)\b",
    "edt": r"\b(?:eau de toilette|edt)\b",
    "edc": r"\b(?:eau de cologne|edc)\b",
    "parfum": r"\b(?:pure parfum|parfum)\b",
}
SIZE = re.compile(r"\b(\d+(?:[.,]\d+)?)\s*(ml|milliliters?|fl\.?\s*oz\.?|ounces?|oz)\b")
EXCLUDED = re.compile(
    r"\b(?:tester|testers|sample|samples|decant|decants|mini|miniature|refill|refillable|"
    r"gift set|giftset|set|shower|deodorant|lotion|body wash|hair mist|used|preowned|"
    r"pre owned|travel|roll on|rollerball|solid|oil|inspired|dupe|impression|type)\b"
)
GENERIC = {
    "spray",
    "natural",
    "vaporisateur",
    "perfume",
    "fragrance",
    "fragrances",
    "by",
    "for",
    "men",
    "women",
    "unisex",
    "mens",
    "womens",
    "new",
    "sealed",
    "bottle",
    "retail",
    "splash",
    "jumbo",
}
BRAND_ALIASES = {
    "dior": ("christian dior",),
    "montblanc": ("mont blanc",),
    "4711": ("muelhens",),
    "yves saint laurent": ("ysl",),
    "giorgio armani": ("armani",),
    "maison francis kurkdjian": ("mfk",),
}


def normalize(value):
    value = unicodedata.normalize("NFKD", value).casefold()
    value = re.sub(r"\b(men|women)['’]s\b", r"\1s", value)
    value = "".join(c for c in value if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", re.sub(r"[^\w., ]", " ", value)).strip()


def concentration(title):
    text = normalize(title)
    found = []
    for name, pattern in CONCENTRATIONS.items():
        if re.search(pattern, text):
            found.append(name)
            # Remove specific phrases before checking bare "parfum", so an EDP
            # is one concentration but an EDP + EDT bundle remains ambiguous.
            text = re.sub(pattern, " ", text)
    return found[0] if len(found) == 1 else None


def size_ml(title):
    sizes = []
    for amount, unit in SIZE.findall(normalize(title)):
        value = float(amount.replace(",", "."))
        sizes.append(value if unit.startswith("m") else value * 29.5735)
    if not sizes or max(sizes) - min(sizes) > 5:
        return None
    # Whole retail bottles only. 3.3 and 3.4 fl oz both commonly represent 100 ml.
    return round(sizes[0], 1) if 25 <= sizes[0] <= 300 else None


def identity(title):
    text = SIZE.sub(" ", normalize(title))
    for pattern in CONCENTRATIONS.values():
        text = re.sub(pattern, " ", text)
    text = re.sub(r"[^a-z0-9 ]", " ", text)
    return " ".join(w for w in text.split() if w not in GENERIC)


@dataclass(frozen=True)
class MatchedOffer:
    store: str
    title: str
    price: Decimal
    size_ml: float
    concentration: str
    url: str


def match_offer(brand: str, name: str, raw: dict, *, identity_index=None) -> MatchedOffer | None:
    return assess_offer(brand, name, raw, identity_index=identity_index)[0]


def assess_offer(
    brand: str, name: str, raw: dict, *, identity_index=None
) -> tuple[MatchedOffer | None, str]:
    """The production matcher and validator share the same rejection reasons."""
    title = raw.get("title", "")
    if not isinstance(title, str) or EXCLUDED.search(normalize(title)):
        return None, "excluded_product"
    expected = concentration(name)
    actual = concentration(title)
    # Ambiguous catalog variants cannot safely be advertised as the same bottle.
    if expected is None or actual != expected:
        return None, "concentration_mismatch_or_missing"
    size = size_ml(title)
    if size is None or re.search(r"\b\d+\s*[x×]\s*\d", title.casefold()):
        return None, "invalid_or_missing_size"
    source = normalize(str(raw.get("source", "")))
    store = {
        "amazon": "amazon",
        "amazon.com": "amazon",
    }.get(source)
    url = raw.get("link", "")
    availability = normalize(" ".join(str(v) for v in raw.get("details_and_offers", [])))
    if re.search(r"\b(?:out of stock|sold out|unavailable)\b", availability):
        return None, "unavailable"
    if raw.get("monthly_payment_duration") or raw.get("installments_description"):
        return None, "installment_price"
    if not store or not isinstance(url, str):
        return None, "unsupported_store_or_link"
    try:
        parsed = urlparse(url)
        host = parsed.hostname or ""
    except ValueError:
        return None, "invalid_url"
    domain = "amazon.com"
    if (
        parsed.scheme != "https"
        or parsed.username
        or parsed.password
        or not (host == domain or host.endswith("." + domain))
        or parsed.path in {"", "/", "/s", "/search"}
        or raw.get("multiple_sources") is True
    ):
        return None, "untrusted_or_aggregate_link"
    currency = raw.get("currency")
    display = str(raw.get("price", ""))
    if currency not in (None, "USD") or (currency is None and not re.match(r"^\$[\d,]+", display)):
        return None, "non_usd_or_missing_currency"
    try:
        price = Decimal(str(raw.get("extracted_price"))).quantize(Decimal("0.01"))
        if not price.is_finite() or not 0 < price <= 10000:
            return None, "invalid_price"
    except (InvalidOperation, ValueError):
        return None, "invalid_price"
    if not identity_matches(brand, name, title, identity_index=identity_index, url=url):
        return None, "identity_mismatch"
    return MatchedOffer(store, title, price, size, actual, url), "accepted"


@lru_cache(maxsize=8192)
def canonical_brand(brand):
    value = identity(brand)
    for canonical, aliases in BRAND_ALIASES.items():
        if value in {identity(canonical), *(identity(alias) for alias in aliases)}:
            return identity(canonical)
    return value


def identity_tokens(brand, text):
    """Remove retail wording and this brand, keeping fragrance/flanker words."""
    brand_name = canonical_brand(brand)
    value = identity(text)
    aliases = BRAND_ALIASES.get(brand_name, ())
    for alias in aliases:
        alias = identity(alias)
        if alias not in brand_name or brand_name not in value:
            value = re.sub(r"\b" + re.escape(alias) + r"\b", brand_name, value)
    scent = re.sub(r"\b" + re.escape(brand_name) + r"\b", " ", value).split()
    return frozenset(scent), value


class IdentityIndex:
    """Full-catalog names distinguish descriptive words from actual flankers."""

    def __init__(self, records):
        self.by_brand = {}
        self.brands = {}
        self.by_scent = {}
        for brand, name in records:
            key = canonical_brand(brand)
            tokens, _ = identity_tokens(brand, name)
            self.brands[key] = key
            for alias in BRAND_ALIASES.get(key, ()):
                self.brands[identity(alias)] = key
            if tokens:
                self.by_scent.setdefault(tokens, set()).add(key)
                self.by_brand.setdefault(key, set()).add((tokens, concentration(name)))

    def accepts(self, brand, name, title, target, actual, url=None):
        if not target <= actual:
            return False
        # Explicit other-brand prefixes/bylines must not pass merely because
        # their titles also mention the target scent.
        full = identity(title)
        own = canonical_brand(brand)
        brand_segments = [full]
        brand_segments.extend(
            identity(part) for part in re.split(r"\bby\s+", title, flags=re.I)[1:]
        )
        for segment in brand_segments:
            words = segment.split()
            for length in range(1, len(words) + 1):
                other = self.brands.get(" ".join(words[:length]))
                if other and other != own and not set(other.split()) <= target:
                    return False
        # Shared names (e.g. Legend by Montblanc and Sapil) need brand context.
        # A product URL's words can disambiguate search results but never replace
        # scent, concentration, size or conflicting-brand checks.
        if len(self.by_scent.get(target, ())) > 1:
            variants = [own, *(identity(a) for a in BRAND_ALIASES.get(own, ()))]
            context = identity(title + " " + unquote(urlparse(url or "").path).replace("-", " "))
            if not any(re.search(r"\b" + re.escape(v) + r"\b", context) for v in variants):
                return False
        for tokens, _variant in self.by_brand.get(own, ()):
            # A longer matching catalog name identifies a flanker, e.g. Flame.
            if target < tokens and tokens <= actual:
                return False
        return True


@lru_cache(maxsize=1)
def get_identity_index():
    # Pricing needs the complete catalog, including fragrances outside the
    # recommendation pool. No feature matrices or paid queries are needed.
    import pandas as pd

    from app.config import settings

    catalog = pd.read_parquet(
        settings.data_dir / "processed" / "perfumes.parquet", columns=["brand", "name"]
    )
    return IdentityIndex(catalog.itertuples(index=False, name=None))


def identity_matches(brand: str, name: str, title: str, *, identity_index=None, url=None) -> bool:
    if EXCLUDED.search(normalize(title)):
        return False
    # Advertising note lists are descriptions, not additional fragrance names.
    title = re.split(
        r"\b(?:with notes of|notes of|top notes|heart notes|base notes)\b",
        title,
        maxsplit=1,
        flags=re.I,
    )[0]
    target, expected_full = identity_tokens(brand, name)
    actual, actual_full = identity_tokens(brand, title)
    if not target:
        if not expected_full.split() or not set(expected_full.split()) <= set(actual_full.split()):
            return False
        if identity_index is not None:
            return identity_index.accepts(brand, name, title, target, actual, url)
        return set(actual_full.split()) == set(expected_full.split())
    if identity_index is not None:
        return identity_index.accepts(brand, name, title, target, actual, url)
    # Standalone callers without catalog context retain exact scent matching.
    return target == actual
