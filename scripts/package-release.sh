#!/usr/bin/env bash
# package-release.sh — Build a versioned installer zip for Raspberry Pi OS Desktop.
#
# Usage: ./scripts/package-release.sh v1.2.0
#
# Output: dist/PrintTracker-v1.2.0-pi.zip  (+ .sha256 checksum)
#         Upload this zip to GitHub Releases or Google Drive.
#         Users extract it, then double-click "Install PrintTracker.desktop".

set -Eeuo pipefail

VERSION="${1:-}"
if [[ -z "$VERSION" ]]; then
  echo "Usage: $0 <version>  (e.g. $0 v1.2.0)" >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
INSTALLER_DIR="$PROJECT_DIR/installer"
DIST_DIR="$PROJECT_DIR/dist"
BUNDLE_NAME="PrintTracker-${VERSION}-pi"
STAGING="$(mktemp -d)"

trap 'rm -rf "$STAGING"' EXIT

[[ -d "$INSTALLER_DIR" ]] || { echo "installer/ directory not found at $INSTALLER_DIR" >&2; exit 1; }
command -v zip >/dev/null || { echo "zip is not installed. Run: sudo apt install zip" >&2; exit 1; }

mkdir -p "$DIST_DIR"

# Stage files
BUNDLE_DIR="$STAGING/$BUNDLE_NAME"
mkdir -p "$BUNDLE_DIR"
cp "$INSTALLER_DIR"/*.desktop "$BUNDLE_DIR/"
chmod +x "$BUNDLE_DIR"/*.desktop

# Zip, preserving execute permissions
(cd "$STAGING" && zip -r "$DIST_DIR/${BUNDLE_NAME}.zip" "$BUNDLE_NAME/")

# Checksum
(cd "$DIST_DIR" && sha256sum "${BUNDLE_NAME}.zip" > "${BUNDLE_NAME}.zip.sha256")

echo ""
echo "Built:"
echo "  $DIST_DIR/${BUNDLE_NAME}.zip"
echo "  $DIST_DIR/${BUNDLE_NAME}.zip.sha256"
echo ""
echo "Upload the .zip to GitHub Releases or Google Drive."
echo "Users: extract the zip, then double-click 'Install PrintTracker.desktop'."
