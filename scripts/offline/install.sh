#!/usr/bin/env bash
# DVT offline install entrypoint. Distributor substitutes the archive version.
set -euo pipefail
DVT_ARCHIVE_VERSION='{version}'
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/offline-runtime.sh"
offline_main install "$@"
