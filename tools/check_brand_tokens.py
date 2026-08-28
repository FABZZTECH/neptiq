#!/usr/bin/env python3
"""Brand-token drift check (Task 1 amendment F).

brand/tokens.css is the single source of truth for NEPTIQ's colours, but the
values are necessarily DUPLICATED in three other places:

  * every ``brand/*.svg`` master, as literal hex in ``fill``/``stroke``
    attributes — because rsvg-convert and resvg do not resolve external
    stylesheets, so a master referencing ``var(--neptiq-gold)`` would rasterise
    with no colour at all;
  * ``apps/web/styles/tokens.css``, which mirrors them for the Next.js app;
  * ``apps/web/app/layout.tsx``, in the ``themeColor`` viewport metadata, which
    must be a literal for the browser chrome.

brand/tokens.css itself says: *"If you change a value here, you MUST update the
matching literal hex in each brand/*.svg master by hand."* An instruction in a
comment is not a control. This script is the control: it extracts every hex
value from every one of those files and fails the build if any of them
disagrees with tokens.css.

Exit code 0 = consistent. 1 = drift, with a report of exactly which file holds
which stale value.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BRAND_DIR = REPO_ROOT / "brand"
TOKENS_CSS = BRAND_DIR / "tokens.css"
WEB_TOKENS_CSS = REPO_ROOT / "apps" / "web" / "styles" / "tokens.css"
WEB_LAYOUT = REPO_ROOT / "apps" / "web" / "app" / "layout.tsx"
BUILD_SCRIPT = REPO_ROOT / "scripts" / "build-brand.sh"

# --neptiq-gold: #C9A227;
_TOKEN_DECL = re.compile(
    r"--neptiq-(?P<name>gold|teal|ink|paper)\s*:\s*(?P<hex>#[0-9A-Fa-f]{3,8})\s*;"
)
# Any hex literal, wherever it appears.
_ANY_HEX = re.compile(r"#[0-9A-Fa-f]{6}\b")
# NEPTIQ_INK="#0B0F14" in the build script.
_SHORTHAND_HEX_LEN = 3  # #abc expands to #aabbcc
_SH_ASSIGN = re.compile(r'NEPTIQ_(?P<name>INK|PAPER|GOLD|TEAL)\s*=\s*"(?P<hex>#[0-9A-Fa-f]{6})"')


def normalise(value: str) -> str:
    """Upper-case and expand shorthand so #fff and #FFFFFF compare equal."""
    v = value.lstrip("#").upper()
    if len(v) == _SHORTHAND_HEX_LEN:
        v = "".join(c * 2 for c in v)
    return "#" + v


def read_canonical() -> dict[str, str]:
    if not TOKENS_CSS.is_file():
        sys.stderr.write(f"FATAL: {TOKENS_CSS} not found — brand tokens missing\n")
        raise SystemExit(1)
    tokens = {
        m.group("name"): normalise(m.group("hex"))
        for m in _TOKEN_DECL.finditer(TOKENS_CSS.read_text(encoding="utf-8"))
    }
    missing = {"gold", "teal", "ink", "paper"} - tokens.keys()
    if missing:
        sys.stderr.write(f"FATAL: {TOKENS_CSS} is missing token(s): {sorted(missing)}\n")
        raise SystemExit(1)
    return tokens


def main() -> int:  # noqa: PLR0912
    # PLR0912: the branch count is one check per duplication site (SVG masters,
    # web mirror, layout literals, build script). Each is a distinct failure
    # mode with its own message; collapsing them would obscure which file drifted.
    canonical = read_canonical()
    allowed = set(canonical.values())
    failures: list[str] = []

    # --- 1. SVG masters: every hex must be a canonical brand colour ---------
    svg_masters = sorted(BRAND_DIR.glob("*.svg"))
    if not svg_masters:
        sys.stderr.write(f"FATAL: no SVG masters found in {BRAND_DIR}\n")
        return 1

    for svg in svg_masters:
        text = svg.read_text(encoding="utf-8")
        found = {normalise(h) for h in _ANY_HEX.findall(text)}
        stray = found - allowed
        if stray:
            failures.append(
                f"{svg.relative_to(REPO_ROOT)}: contains hex value(s) not in "
                f"brand/tokens.css: {sorted(stray)}"
            )
        if not found:
            # A master with no literal hex is only legitimate if it is
            # deliberately colour-agnostic, i.e. it paints with `currentColor`
            # so the embedding context supplies the colour. That is exactly
            # what a *-mono master is for.
            #
            # The failure this branch guards against is different and much
            # easier to introduce by accident: someone "tidies" a coloured
            # master by replacing its literal hex with var(--neptiq-gold).
            # rsvg-convert and resvg do not resolve CSS custom properties, so
            # the asset silently rasterises with no colour — and nothing in the
            # build fails, because the SVG is still valid.
            uses_current_color = "currentColor" in text
            uses_css_var = "var(--" in text
            if uses_css_var:
                failures.append(
                    f"{svg.relative_to(REPO_ROOT)}: paints with var(--...) CSS custom "
                    "properties instead of literal hex. Raster exporters "
                    "(rsvg-convert/resvg) do not resolve them, so this master would "
                    "export with no colour. Use literal hex from brand/tokens.css."
                )
            elif not uses_current_color:
                failures.append(
                    f"{svg.relative_to(REPO_ROOT)}: no literal hex colours and no "
                    "currentColor. A master must either carry literal brand hex or be "
                    "deliberately colour-agnostic via currentColor."
                )

    # --- 2. apps/web mirror must declare identical values -------------------
    if WEB_TOKENS_CSS.is_file():
        web_tokens = {
            m.group("name"): normalise(m.group("hex"))
            for m in _TOKEN_DECL.finditer(WEB_TOKENS_CSS.read_text(encoding="utf-8"))
        }
        for name, expected in canonical.items():
            actual = web_tokens.get(name)
            if actual is None:
                failures.append(f"{WEB_TOKENS_CSS.relative_to(REPO_ROOT)}: missing --neptiq-{name}")
            elif actual != expected:
                failures.append(
                    f"{WEB_TOKENS_CSS.relative_to(REPO_ROOT)}: --neptiq-{name} is {actual}, "
                    f"brand/tokens.css says {expected}"
                )
    else:
        failures.append(f"{WEB_TOKENS_CSS.relative_to(REPO_ROOT)}: not found")

    # --- 3. layout.tsx themeColor literals ---------------------------------
    if WEB_LAYOUT.is_file():
        layout_hexes = {normalise(h) for h in _ANY_HEX.findall(WEB_LAYOUT.read_text("utf-8"))}
        stray = layout_hexes - allowed
        if stray:
            failures.append(
                f"{WEB_LAYOUT.relative_to(REPO_ROOT)}: themeColor/other hex value(s) "
                f"not in brand/tokens.css: {sorted(stray)}"
            )

    # --- 4. build-brand.sh background constants ----------------------------
    if BUILD_SCRIPT.is_file():
        for m in _SH_ASSIGN.finditer(BUILD_SCRIPT.read_text(encoding="utf-8")):
            name = m.group("name").lower()
            actual_hex = normalise(m.group("hex"))
            expected_hex: str | None = canonical.get(name)
            if expected_hex and actual_hex != expected_hex:
                failures.append(
                    f"{BUILD_SCRIPT.relative_to(REPO_ROOT)}: NEPTIQ_{name.upper()} is "
                    f"{actual_hex}, brand/tokens.css says {expected_hex}"
                )

    # --- Report ------------------------------------------------------------
    if failures:
        sys.stderr.write("BRAND TOKEN DRIFT DETECTED\n")
        sys.stderr.write("=" * 70 + "\n")
        sys.stderr.write("brand/tokens.css is the single source of truth:\n")
        for name, value in sorted(canonical.items()):
            sys.stderr.write(f"  --neptiq-{name:<6} {value}\n")
        sys.stderr.write("\nDisagreements:\n")
        for f in failures:
            sys.stderr.write(f"  - {f}\n")
        sys.stderr.write(
            "\nFix: update the listed file(s) to match brand/tokens.css, or change "
            "brand/tokens.css and update every mirror.\n"
        )
        return 1

    print(
        f"brand tokens consistent: {len(canonical)} tokens verified across "
        f"{len(svg_masters)} SVG masters + apps/web mirror + build script"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
