#!/bin/sh

set -eu

is_enabled() {
  case "${1:-}" in
    1|true|TRUE|yes|YES|on|ON)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

apply_netem() {
  iface="${FTP_TEST_DB_NETEM_IFACE:-eth0}"

  if ! command -v tc >/dev/null 2>&1; then
    echo "FTP test netem is enabled, but tc is not installed." >&2
    exit 1
  fi

  (
    set -- netem

    if [ -n "${FTP_TEST_DB_NETEM_DELAY:-}" ]; then
      set -- "$@" delay "${FTP_TEST_DB_NETEM_DELAY}"

      if [ -n "${FTP_TEST_DB_NETEM_JITTER:-}" ]; then
        set -- "$@" "${FTP_TEST_DB_NETEM_JITTER}"
      fi
    fi

    if [ -n "${FTP_TEST_DB_NETEM_RATE:-}" ]; then
      set -- "$@" rate "${FTP_TEST_DB_NETEM_RATE}"
    fi

    if [ -n "${FTP_TEST_DB_NETEM_LOSS:-}" ]; then
      set -- "$@" loss "${FTP_TEST_DB_NETEM_LOSS}"
    fi

    if [ "$#" -eq 1 ]; then
      echo "FTP test netem is enabled, but no netem rules were configured. Skipping qdisc setup."
      exit 0
    fi

    echo "Applying FTP test netem on ${iface}: $*"
    tc qdisc replace dev "${iface}" root "$@"
  )
}

if is_enabled "${FTP_TEST_DB_NETEM_ENABLED:-false}"; then
  apply_netem
fi

exec /bin/start_vsftpd.sh "$@"
