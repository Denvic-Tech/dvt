#!/bin/sh

set -eu

TEMPLATE_PATH="${CADDYFILE_TEMPLATE_PATH:-/etc/caddy/Caddyfile.template}"
OUTPUT_PATH="${CADDYFILE_OUTPUT_PATH:-/etc/caddy/Caddyfile}"
CADDY_BIN="${CADDY_BIN:-caddy}"
SKIP_CADDY_VALIDATE="${SKIP_CADDY_VALIDATE:-false}"
SKIP_CADDY_RUN="${SKIP_CADDY_RUN:-false}"
RAW_PUBLIC_URLS="${DVT_PUBLIC_URL:-http://localhost}"

trim() {
    printf '%s' "$1" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//'
}

fail() {
    printf '%s\n' "$1" >&2
    exit 1
}

validate_and_format_site_address() {
    raw_entry="$(trim "$1")"

    if [ -z "$raw_entry" ]; then
        return 1
    fi

    normalized_entry="$(printf '%s' "$raw_entry" | sed -E 's#^(https?://[^/?#]+)/*$#\1#')"

    case "$normalized_entry" in
        http://*|https://*)
            ;;
        *)
            fail "Invalid DVT_PUBLIC_URL entry '$raw_entry': only absolute http:// or https:// URLs are supported."
            ;;
    esac

    scheme="${normalized_entry%%://*}"
    authority="${normalized_entry#*://}"

    case "$authority" in
        "")
            fail "Invalid DVT_PUBLIC_URL entry '$raw_entry': host is required."
            ;;
        *'@'*)
            fail "Invalid DVT_PUBLIC_URL entry '$raw_entry': userinfo is not supported."
            ;;
        *'/'*|*'?'*|*'#'*)
            fail "Invalid DVT_PUBLIC_URL entry '$raw_entry': path, query, and fragment are not supported."
            ;;
    esac

    if ! printf '%s' "$authority" | grep -Eq '^(\[[^]]+\]|[^:]+)(:[0-9]+)?$'; then
        fail "Invalid DVT_PUBLIC_URL entry '$raw_entry': host format is not supported."
    fi

    host="$(printf '%s' "$authority" | sed -E 's/^(\[[^]]+\]|[^:]+)(:[0-9]+)?$/\1/')"

    if [ -z "$host" ]; then
        fail "Invalid DVT_PUBLIC_URL entry '$raw_entry': host is required."
    fi

    printf '%s://%s' "$scheme" "$host"
}

site_addresses=""
remaining_urls="$RAW_PUBLIC_URLS"

while :; do
    case "$remaining_urls" in
        *';'*)
            current_entry="${remaining_urls%%;*}"
            remaining_urls="${remaining_urls#*;}"
            ;;
        *)
            current_entry="$remaining_urls"
            remaining_urls=""
            ;;
    esac

    if formatted_entry="$(validate_and_format_site_address "$current_entry")"; then
        if [ -z "$site_addresses" ]; then
            site_addresses="$formatted_entry"
        else
            site_addresses="$site_addresses, $formatted_entry"
        fi
    fi

    if [ -z "$remaining_urls" ]; then
        break
    fi
done

if [ -z "$site_addresses" ]; then
    fail "DVT_PUBLIC_URL must contain at least one valid http:// or https:// URL."
fi

sed "s#__SITE_ADDRESSES__#$site_addresses#" "$TEMPLATE_PATH" > "$OUTPUT_PATH"
"$CADDY_BIN" fmt --overwrite "$OUTPUT_PATH" >/dev/null

if [ "$SKIP_CADDY_VALIDATE" != "true" ]; then
    "$CADDY_BIN" validate --config "$OUTPUT_PATH" --adapter caddyfile
fi

if [ "$SKIP_CADDY_RUN" = "true" ]; then
    exit 0
fi

exec "$CADDY_BIN" run --config "$OUTPUT_PATH" --adapter caddyfile
