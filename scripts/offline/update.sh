#!/usr/bin/env bash
# Use the trusted host CLI with the complete signed archive supplied via --bundle.
set -euo pipefail
exec "${DVT_OFFLINE_PYTHON:-python3}" -m services.installation_manager.application.offline_bundles update "$@"
