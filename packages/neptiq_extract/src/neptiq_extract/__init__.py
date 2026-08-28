"""neptiq_extract — implementation lands in a later task.

Package skeleton exists now so that the uv workspace, the import-graph
invariant checks (tools/check_zone_imports.py) and the dependency direction in
ARCHITECTURE §5 are all enforceable from Task 1 onward. Adding the package
later would mean the zone checks pass trivially until the moment they matter.
"""

from __future__ import annotations

__all__: list[str] = []
