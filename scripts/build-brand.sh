#!/usr/bin/env bash
#
# NEPTIQ brand asset pipeline.
#
# Renders every distributable brand asset from the hand-written SVG masters
# in brand/. The masters are the single source of truth; everything this
# script produces is generated output and MUST be gitignored.
#
# Requires: rsvg-convert (librsvg), ImageMagick (convert/magick).
# Both are used only as raster renderers of the master SVGs — no asset
# geometry is generated or altered by this script, only rasterised/padded/
# composited from the paths already committed in brand/*.svg.
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
BRAND_DIR="${REPO_ROOT}/brand"
OUT_DIR="${REPO_ROOT}/apps/web/public/brand"

NEPTIQ_INK="#0B0F14"
NEPTIQ_PAPER="#FAFAF8"

command -v rsvg-convert >/dev/null 2>&1 || { echo "ERROR: rsvg-convert not found." >&2; exit 1; }
command -v convert      >/dev/null 2>&1 || { echo "ERROR: ImageMagick 'convert' not found." >&2; exit 1; }

mkdir -p "${OUT_DIR}"
rm -f "${OUT_DIR}"/*.png "${OUT_DIR}"/*.ico "${OUT_DIR}"/*.svg

echo "==> NEPTIQ brand build"
echo "    masters: ${BRAND_DIR}"
echo "    output:  ${OUT_DIR}"

# ---------------------------------------------------------------------------
# favicon.svg — direct copy of the mark master, browsers rasterise natively
# ---------------------------------------------------------------------------
cp "${BRAND_DIR}/neptiq-mark.svg" "${OUT_DIR}/favicon.svg"
echo "  favicon.svg"

# ---------------------------------------------------------------------------
# favicon.ico — multi-size 16/32/48 from neptiq-mark.svg
# ---------------------------------------------------------------------------
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "${TMP_DIR}"' EXIT

for size in 16 32 48; do
  rsvg-convert -w "${size}" -h "${size}" \
    "${BRAND_DIR}/neptiq-mark.svg" -o "${TMP_DIR}/favicon-${size}.png"
done
convert "${TMP_DIR}/favicon-16.png" "${TMP_DIR}/favicon-32.png" "${TMP_DIR}/favicon-48.png" \
  "${OUT_DIR}/favicon.ico"
echo "  favicon.ico (16/32/48)"

# ---------------------------------------------------------------------------
# apple-touch-icon.png — 180x180, opaque background (paper), no transparency
# ---------------------------------------------------------------------------
rsvg-convert -w 180 -h 180 -b "${NEPTIQ_PAPER}" \
  "${BRAND_DIR}/neptiq-mark.svg" -o "${TMP_DIR}/apple-touch-raw.png"
convert "${TMP_DIR}/apple-touch-raw.png" -background "${NEPTIQ_PAPER}" -alpha remove -alpha off \
  "${OUT_DIR}/apple-touch-icon.png"
echo "  apple-touch-icon.png (180x180, opaque)"

# ---------------------------------------------------------------------------
# icon-192.png / icon-512.png — PWA icons, transparent background
# ---------------------------------------------------------------------------
rsvg-convert -w 192 -h 192 "${BRAND_DIR}/neptiq-mark.svg" -o "${OUT_DIR}/icon-192.png"
rsvg-convert -w 512 -h 512 "${BRAND_DIR}/neptiq-mark.svg" -o "${OUT_DIR}/icon-512.png"
echo "  icon-192.png, icon-512.png"

# ---------------------------------------------------------------------------
# icon-512-maskable.png — 512x512 canvas, mark scaled into safe zone.
# Maskable icon spec: outer 10% on every edge may be cropped by the OS mask,
# so keep all content inside the central "safe zone". We use 20% total
# padding per edge as required (i.e. content occupies the central 60%,
# 20% margin on each of the 4 sides) for extra safety margin.
# ---------------------------------------------------------------------------
MASK_CANVAS=512
MASK_PAD_PCT=20
MASK_CONTENT=$(( MASK_CANVAS * (100 - 2 * MASK_PAD_PCT) / 100 ))  # 512*60/100 = 307
rsvg-convert -w "${MASK_CONTENT}" -h "${MASK_CONTENT}" \
  "${BRAND_DIR}/neptiq-mark.svg" -o "${TMP_DIR}/mask-content.png"
convert -size "${MASK_CANVAS}x${MASK_CANVAS}" xc:"${NEPTIQ_PAPER}" \
  "${TMP_DIR}/mask-content.png" -gravity center -composite \
  "${OUT_DIR}/icon-512-maskable.png"
echo "  icon-512-maskable.png (20% safe-zone padding, opaque paper background)"

# ---------------------------------------------------------------------------
# oauth-logo.png — 120x120, square, opaque, target well under 1 MB
# ---------------------------------------------------------------------------
rsvg-convert -w 120 -h 120 -b "${NEPTIQ_PAPER}" \
  "${BRAND_DIR}/neptiq-mark.svg" -o "${TMP_DIR}/oauth-raw.png"
convert "${TMP_DIR}/oauth-raw.png" -background "${NEPTIQ_PAPER}" -alpha remove -alpha off \
  -strip "${OUT_DIR}/oauth-logo.png"
OAUTH_BYTES=$(stat -c%s "${OUT_DIR}/oauth-logo.png")
if [ "${OAUTH_BYTES}" -ge 1048576 ]; then
  echo "ERROR: oauth-logo.png is ${OAUTH_BYTES} bytes, must be under 1 MB" >&2
  exit 1
fi
echo "  oauth-logo.png (120x120, opaque, ${OAUTH_BYTES} bytes)"

# ---------------------------------------------------------------------------
# email-header.png — 600px wide (logical) at 2x pixel density = 1200px wide
# Uses the horizontal lockup so it carries the wordmark, on paper background.
# Horizontal lockup master viewBox is 280x64 (aspect ratio 4.375:1).
# ---------------------------------------------------------------------------
EMAIL_W=1200
EMAIL_H=$(( EMAIL_W * 64 / 280 ))  # preserve lockup aspect ratio
rsvg-convert -w "${EMAIL_W}" -h "${EMAIL_H}" -b "${NEPTIQ_PAPER}" \
  "${BRAND_DIR}/neptiq-lockup-horizontal.svg" -o "${TMP_DIR}/email-lockup.png"
# Composite onto a fixed 1200x300 opaque paper canvas (600px @2x logical height
# budget), centring the lockup, so downstream email clients get a stable frame.
EMAIL_CANVAS_H=300
convert -size "${EMAIL_W}x${EMAIL_CANVAS_H}" xc:"${NEPTIQ_PAPER}" \
  "${TMP_DIR}/email-lockup.png" -gravity center -composite \
  -background "${NEPTIQ_PAPER}" -alpha remove -alpha off \
  "${OUT_DIR}/email-header.png"
echo "  email-header.png (${EMAIL_W}x${EMAIL_CANVAS_H}, 600px logical width @2x)"

# ---------------------------------------------------------------------------
# og-default.png — 1200x630, opaque, ink background with paper lockup centred
# ---------------------------------------------------------------------------
OG_W=1200
OG_H=630
LOCKUP_TARGET_W=720
LOCKUP_TARGET_H=$(( LOCKUP_TARGET_W * 64 / 280 ))
rsvg-convert -w "${LOCKUP_TARGET_W}" -h "${LOCKUP_TARGET_H}" \
  "${BRAND_DIR}/neptiq-lockup-horizontal-dark.svg" -o "${TMP_DIR}/og-lockup.png"
convert -size "${OG_W}x${OG_H}" xc:"${NEPTIQ_INK}" \
  "${TMP_DIR}/og-lockup.png" -gravity center -composite \
  -background "${NEPTIQ_INK}" -alpha remove -alpha off \
  "${OUT_DIR}/og-default.png"
echo "  og-default.png (${OG_W}x${OG_H}, dark lockup on ink background)"

echo "==> NEPTIQ brand build complete: $(ls -1 "${OUT_DIR}" | wc -l) files in ${OUT_DIR}"
