#!/usr/bin/env bash
# Compatibility for callers of the former shared runner.
offline_main() {
    local action="${1:?install or update required}"
    shift
    case "$action" in
        install|update)
            "${DVT_OFFLINE_PYTHON:-python3}" -m services.installation_manager.application.offline_bundles "$action" "$@"
            ;;
        *) return 2 ;;
    esac
}
