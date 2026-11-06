# shellcheck shell=bash
# Sourced by deploy/linux/smarthome: give the app the HTTPS certificate this
# server's web server already uses, and keep it up to date when it renews.
#
#   cert-import [--cert FILE --key FILE]   import it now (while Settings >
#                                          Admin > HTTPS > "Take the
#                                          certificate from this server's web
#                                          server" is on)
#   cert-auto-setup                        check every 6 hours and after each
#                                          certbot renewal; cert-auto-remove
#
# Found, in this order: CERT_FILE/KEY_FILE in deploy/linux/local.conf, then
# Apache (httpd or apache2: SSLCertificateFile/SSLCertificateKeyFile), nginx
# (ssl_certificate/ssl_certificate_key), Caddy's own certificates, and
# certbot (/etc/letsencrypt/live). Self-signed placeholders are skipped.

CERT_UNIT="smarthome-cert"
CERT_SPLIT="-----SMARTHOME KEY FOLLOWS-----"
CERT_ROOT="${SMARTHOME_CERT_ROOT:-}"   # tests: a folder standing in for /

cert_conf_files() {  # the web servers' configuration files, Apache first
    local dir
    for dir in /etc/httpd/conf.d /etc/httpd/conf /etc/apache2/sites-enabled /etc/apache2/conf-enabled \
               /etc/nginx/conf.d /etc/nginx/sites-enabled /etc/nginx; do
        [[ -d "$CERT_ROOT$dir" ]] || continue
        find "$CERT_ROOT$dir" -maxdepth 1 -type f 2>/dev/null | sort
    done
}

cert_placeholder() {  # the distributions' self-signed stand-ins
    case "$1" in
        */localhost.crt|*/ssl-cert-snakeoil.pem|*/localhost.key|*/ssl-cert-snakeoil.key) return 0 ;;
    esac
    return 1
}

cert_find() {  # prints "certificate key source", or fails
    local cert key file line
    cert="$(conf_get CERT_FILE "")"
    key="$(conf_get KEY_FILE "")"
    if [[ -n "$cert" && -n "$key" ]]; then
        printf '%s %s %s\n' "$cert" "$key" "local.conf"
        return 0
    fi
    while IFS= read -r file; do
        cert="" key=""
        while IFS= read -r line; do
            line="${line%%#*}"
            case "$line" in
                *SSLCertificateFile*) cert="$(awk '{print $2}' <<<"$line")" ;;
                *SSLCertificateKeyFile*) key="$(awk '{print $2}' <<<"$line")" ;;
                *ssl_certificate_key*) key="$(awk '{print $2}' <<<"$line" | tr -d ';')" ;;
                *ssl_certificate*) cert="$(awk '{print $2}' <<<"$line" | tr -d ';')" ;;
            esac
            if [[ -n "$cert" && -n "$key" ]]; then
                if ! cert_placeholder "$cert" && [[ -f "$CERT_ROOT$cert" && -f "$CERT_ROOT$key" ]]; then
                    printf '%s %s %s\n' "$cert" "$key" "${file#"$CERT_ROOT"}"
                    return 0
                fi
                cert="" key=""
            fi
        done < "$file"
    done < <(cert_conf_files)
    # Caddy keeps the certificates it gets in its data folder.
    for file in "$CERT_ROOT"/var/lib/caddy/.local/share/caddy/certificates/*/*/*.crt; do
        [[ -f "$file" && -f "${file%.crt}.key" ]] || continue
        printf '%s %s %s\n' "${file#"$CERT_ROOT"}" "${file%.crt}.key" "Caddy"
        return 0
    done
    for file in "$CERT_ROOT"/etc/letsencrypt/live/*/fullchain.pem; do
        [[ -f "$file" ]] || continue
        printf '%s %s %s\n' "${file#"$CERT_ROOT"}" "$(dirname "${file#"$CERT_ROOT"}")/privkey.pem" "certbot"
        return 0
    done
    return 1
}

cert_read() {  # the file's text; keys are root's, so ask for sudo if needed
    local path="$CERT_ROOT$1"
    if [[ -r "$path" ]]; then cat "$path"; else as_root cat "$path"; fi
}

# shellcheck disable=SC2120  # smarthome passes the command line
cmd_cert_import() {
    local cert="" key="" source="" quiet=""
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --cert) cert="$2"; shift 2 ;;
            --key) key="$2"; shift 2 ;;
            --quiet) quiet=1; shift ;;
            *) die "cert-import [--cert FILE --key FILE] [--quiet]" ;;
        esac
    done
    if [[ -z "$cert" ]]; then
        local found
        found="$(cert_find)" || die "No web server certificate found (Apache, nginx, Caddy or certbot). Give it: $SELF cert-import --cert FILE --key FILE"
        read -r cert key source <<<"$found"
    else
        source="$cert"
    fi
    need_docker
    local result
    # One text: the source, the certificate, a dividing line, the key.
    result="$( { printf '%s\n' "$source"; cert_read "$cert"; printf '%s\n' "$CERT_SPLIT"; cert_read "$key"; } \
        | compose exec -T "$SERVICE" python scripts/import_certificate.py)" || die "The app refused the certificate from $cert."
    case "$result" in
        off) [[ -n "$quiet" ]] || say "Turn it on first: Settings > Admin > HTTPS > Take the certificate from this server's web server." ;;
        same) [[ -n "$quiet" ]] || say "The app already has the certificate from $source." ;;
        changed)
            say "Imported the certificate from $source."
            compose restart "$SERVICE" >/dev/null && wait_healthy && say "Restarted the app to use it." ;;
        *) die "Unexpected answer from the app: $result" ;;
    esac
}

cmd_cert_auto_setup() {
    command -v systemctl >/dev/null 2>&1 || die "No systemd here: run $SELF cert-import from cron instead."
    cmd_cert_import
    local tmp
    tmp="$(mktemp)"
    cat > "$tmp" <<UNIT
# Written by $SELF cert-auto-setup.
[Unit]
Description=Smart Home Unified Control: take the web server's HTTPS certificate
After=docker.service

[Service]
Type=oneshot
WorkingDirectory=$ROOT
ExecStart=$ROOT/deploy/linux/smarthome cert-import --quiet
UNIT
    as_root install -m 644 "$tmp" "$OFFSITE_DIR/$CERT_UNIT.service"
    cat > "$tmp" <<UNIT
# Written by $SELF cert-auto-setup.
[Unit]
Description=Check the web server's HTTPS certificate every 6 hours

[Timer]
OnBootSec=5min
OnUnitActiveSec=6h

[Install]
WantedBy=timers.target
UNIT
    as_root install -m 644 "$tmp" "$OFFSITE_DIR/$CERT_UNIT.timer"
    rm -f "$tmp"
    if [[ -d "$CERT_ROOT/etc/letsencrypt/renewal-hooks/deploy" ]]; then
        printf '#!/bin/sh\nsystemctl start --no-block %s.service\n' "$CERT_UNIT" > "$tmp"
        as_root install -m 755 "$tmp" "$CERT_ROOT/etc/letsencrypt/renewal-hooks/deploy/smarthome"
        rm -f "$tmp"
    fi
    as_root systemctl daemon-reload
    as_root systemctl enable --now "$CERT_UNIT.timer" >/dev/null 2>&1
    say "The certificate is checked every 6 hours (and after each certbot renewal)."
}

cmd_cert_auto_remove() {
    as_root systemctl disable --now "$CERT_UNIT.timer" >/dev/null 2>&1 || true
    as_root rm -f "$OFFSITE_DIR/$CERT_UNIT.timer" "$OFFSITE_DIR/$CERT_UNIT.service" \
        "$CERT_ROOT/etc/letsencrypt/renewal-hooks/deploy/smarthome"
    as_root systemctl daemon-reload || true
    say "Automatic certificate import is off on this server."
}
