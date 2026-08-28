"""neptiq_security — SSRF validation, taint types, sanitisers, credentials.

Import note for Zone U authors: ``neptiq_security.taint`` and
``neptiq_security.ssrf`` are Zone-U-safe and are exactly what Zone U needs.
``neptiq_security.credentials`` is NOT: invariant 1 forbids Zone U importing
it, and tools/check_zone_imports.py fails the build on violation. This
``__init__`` therefore does NOT re-export the credentials API — importing
``neptiq_security`` must not transitively hand Zone U a decryption primitive.
"""

from __future__ import annotations

from neptiq_security.ssrf import (
    BLOCKED_NETWORKS,
    CLOUD_METADATA_HOSTS,
    DnsResolver,
    ValidatedDestination,
    classify_ip,
    validate_destination,
    validate_redirect_hop,
)
from neptiq_security.taint import Tainted, TaintSource, strip_invisible, taint

__all__ = [
    "BLOCKED_NETWORKS",
    "CLOUD_METADATA_HOSTS",
    "DnsResolver",
    "TaintSource",
    "Tainted",
    "ValidatedDestination",
    "classify_ip",
    "strip_invisible",
    "taint",
    "validate_destination",
    "validate_redirect_hop",
]
