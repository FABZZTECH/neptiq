"""neptiq_url — pure, property-tested URL normalisation.

No I/O, no dependency on neptiq_db. Safe for Zone U.
"""

from __future__ import annotations

from neptiq_url.normalise import (
    ALLOWED_SCHEMES,
    DEFAULT_PORTS,
    TRACKING_PARAMS,
    UrlNormalisationError,
    is_same_registrable_site,
    normalise,
    url_hash,
)

__all__ = [
    "ALLOWED_SCHEMES",
    "DEFAULT_PORTS",
    "TRACKING_PARAMS",
    "UrlNormalisationError",
    "is_same_registrable_site",
    "normalise",
    "url_hash",
]
