#!/bin/sh
# Write the addresses in TRUSTED_PROXY_IPS (comma separated, an address or a CIDR) as
# `set_real_ip_from` lines to the file that nginx.conf includes. nginx takes the client
# address from X-Forwarded-For only for a request from one of these addresses. Without
# the variable the file is empty and nginx trusts no forwarded header.
# Spec NF/security/network/000972.
set -eu

target=/etc/nginx/trusted-proxies.conf
: > "$target"
for address in $(printf '%s' "${TRUSTED_PROXY_IPS:-}" | tr ',' ' '); do
    case "$address" in
        *[!0-9a-fA-F.:/]*)
            echo "TRUSTED_PROXY_IPS: '$address' is no address and no CIDR" >&2
            exit 1
            ;;
    esac
    printf 'set_real_ip_from %s;\n' "$address" >> "$target"
done
