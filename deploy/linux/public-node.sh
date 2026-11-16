# shellcheck shell=bash
# Sourced by deploy/linux/smarthome: what a server reached from the internet
# needs beyond the app itself.
#
#   offsite-backup DEST         copy the backups to DEST now: a folder (a NAS
#                               or USB disk mounted here) or user@host:/path
#                               (over SSH, with rsync)
#   offsite-setup DEST [HOUR]   do that every day at HOUR (default 4), with a
#                               systemd timer; offsite-remove stops it
#   fail2ban-setup              ban addresses that keep failing to log in, at
#                               the server's firewall (needs fail2ban and the
#                               reverse proxy's access log)

OFFSITE_UNIT="smarthome-offsite"
OFFSITE_DIR="${SMARTHOME_SYSTEMD_DIR:-/etc/systemd/system}"
F2B_DIR="${SMARTHOME_FAIL2BAN_DIR:-/etc/fail2ban}"

is_remote() { [[ "$1" == *:* ]]; }

cmd_offsite_backup() {
    local dest="${1:-}" tmp
    [[ -n "$dest" ]] || die "Give a place: offsite-backup /mnt/nas/smarthome, or offsite-backup user@host:/path"
    need_docker
    tmp="$(mktemp -d)"
    compose cp "$SERVICE:/app/data/backups/." "$tmp" >/dev/null
    local count
    count="$(find "$tmp" -type f | wc -l)"
    if [[ "$count" -eq 0 ]]; then
        rm -rf "$tmp"
        die "No backups to copy yet ($SELF backup makes one)."
    fi
    if is_remote "$dest"; then
        command -v rsync >/dev/null 2>&1 || { rm -rf "$tmp"; die "rsync is needed: sudo dnf -y install rsync (or sudo apt install -y rsync)"; }
        # BatchMode: never stop to ask for a password (set up an SSH key first).
        rsync -a -e "ssh -o BatchMode=yes" "$tmp/" "$dest/" || { rm -rf "$tmp"; die "Could not copy to $dest. Check: ssh ${dest%%:*} works without a password, and the folder exists."; }
    else
        mkdir -p "$dest"
        cp -a "$tmp/." "$dest/"
    fi
    rm -rf "$tmp"
    say "Copied $count backup file(s) to $dest"
    say "Keep SECRETS_KEY with them, somewhere else again: saved logins in them open only with it."
}

offsite_service_text() {
    local dest="$1"
    cat <<EOF
# Written by $SELF offsite-setup. Copies the backups off this server.
[Unit]
Description=Smart Home Unified Control: copy backups off this server
After=docker.service network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=$(id -un)
WorkingDirectory=$ROOT
# bash reads the script: SELinux may not let systemd run one in a home folder.
ExecStart=/bin/bash $ROOT/deploy/linux/smarthome offsite-backup $dest
EOF
}

offsite_timer_text() {
    local hour="$1"
    cat <<EOF
# Written by $SELF offsite-setup.
[Unit]
Description=Copy Smart Home Unified Control backups off this server, daily

[Timer]
OnCalendar=*-*-* $(printf '%02d' "$hour"):15:00
Persistent=true

[Install]
WantedBy=timers.target
EOF
}

cmd_offsite_setup() {
    local dest="${1:-}" hour="${2:-4}"
    [[ -n "$dest" ]] || die "Give a place: offsite-setup /mnt/nas/smarthome [HOUR], or offsite-setup user@host:/path [HOUR]"
    [[ "$hour" =~ ^([01]?[0-9]|2[0-3])$ ]] || die "HOUR is 0 to 23"
    [[ "$dest" =~ ^[A-Za-z0-9._@:/~+-]+$ ]] || die "Use a place without spaces or special characters: $dest"
    command -v systemctl >/dev/null 2>&1 || die "No systemd here: add a cron job instead (docs/DEPLOY-LINUX.md, section 6)"
    say "Trying it once now..."
    cmd_offsite_backup "$dest"
    local tmp
    tmp="$(mktemp)"
    offsite_service_text "$dest" > "$tmp"
    as_root install -m 644 "$tmp" "$OFFSITE_DIR/$OFFSITE_UNIT.service"
    offsite_timer_text "$hour" > "$tmp"
    as_root install -m 644 "$tmp" "$OFFSITE_DIR/$OFFSITE_UNIT.timer"
    rm -f "$tmp"
    as_root systemctl daemon-reload
    as_root systemctl enable --now "$OFFSITE_UNIT.timer" >/dev/null 2>&1
    conf_set OFFSITE "$dest"
    say "Backups are copied to $dest every day at $(printf '%02d' "$hour"):15. Check with: systemctl list-timers $OFFSITE_UNIT.timer"
}

cmd_offsite_remove() {
    [[ -f "$OFFSITE_DIR/$OFFSITE_UNIT.timer" ]] || { say "No daily copy set up."; return 0; }
    as_root systemctl disable --now "$OFFSITE_UNIT.timer" >/dev/null 2>&1 || true
    as_root rm -f "$OFFSITE_DIR/$OFFSITE_UNIT.timer" "$OFFSITE_DIR/$OFFSITE_UNIT.service"
    as_root systemctl daemon-reload
    conf_set OFFSITE ""
    say "The daily copy is off. Copies already made are left where they are."
}

proxy_access_log() {  # the reverse proxy's access log, if one is found
    local f
    for f in /var/log/httpd/ssl_access_log /var/log/httpd/access_log /var/log/apache2/access.log /var/log/apache2/other_vhosts_access.log /var/log/nginx/access.log; do
        [[ -f "${SMARTHOME_LOG_ROOT:-}$f" ]] && { printf '%s' "$f"; return 0; }
    done
    return 1
}

f2b_filter_text() {
    cat <<'EOF'
# Written by deploy/linux/smarthome fail2ban-setup.
# A refused login is a 401 from POST /api/v1/auth/login; too many tries is a
# 429 from any address. A correct password that still needs the two-factor
# code is also a 401, once per login, so maxretry is kept generous.
[Definition]
failregex = ^<HOST> \S+ \S+ \[[^\]]+\] "POST /api/v1/auth/login HTTP/[0-9.]+" 401
            ^<HOST> \S+ \S+ \[[^\]]+\] "[A-Z]+ /api/v1/\S* HTTP/[0-9.]+" 429
ignoreregex =
EOF
}

f2b_jail_text() {
    local log="$1"
    cat <<EOF
# Written by $SELF fail2ban-setup.
[smarthome]
enabled  = true
filter   = smarthome
logpath  = $log
port     = http,https
maxretry = 10
findtime = 10m
bantime  = 1h
EOF
}

cmd_fail2ban_setup() {
    command -v fail2ban-client >/dev/null 2>&1 || [[ -n "${SMARTHOME_FAIL2BAN_DIR:-}" ]] \
        || die "Install fail2ban first: sudo dnf -y install epel-release && sudo dnf -y install fail2ban (or sudo apt install -y fail2ban), then sudo systemctl enable --now fail2ban"
    local log
    log="$(proxy_access_log)" || die "No reverse-proxy access log found (Apache or nginx). fail2ban watches it: set up the proxy first ($SELF proxy-example)."
    local tmp
    tmp="$(mktemp)"
    f2b_filter_text > "$tmp"
    as_root install -D -m 644 "$tmp" "$F2B_DIR/filter.d/smarthome.conf"
    f2b_jail_text "$log" > "$tmp"
    as_root install -D -m 644 "$tmp" "$F2B_DIR/jail.d/smarthome.local"
    rm -f "$tmp"
    if [[ -z "${SMARTHOME_FAIL2BAN_DIR:-}" ]]; then
        as_root systemctl enable --now fail2ban >/dev/null 2>&1 || true
        as_root fail2ban-client reload >/dev/null 2>&1 || die "fail2ban did not reload: sudo fail2ban-client -d shows why"
    fi
    say "fail2ban watches $log: 10 refused logins in 10 minutes bans that address for an hour."
    say "Check with: sudo fail2ban-client status smarthome"
}

doctor_public_node() {  # extra lines for doctor (uses its ok/bad/note)
    local access dest
    access="$(conf_get ACCESS lan)"
    dest="$(conf_get OFFSITE "")"
    if [[ -n "$dest" ]] && systemctl is-enabled --quiet "$OFFSITE_UNIT.timer" 2>/dev/null; then
        ok "backups are copied off this server daily, to $dest"
    else
        note "backups live on this disk only: $SELF offsite-setup DEST copies them elsewhere every day"
    fi
    if [[ "$access" == "proxy" ]]; then
        if [[ -f "$F2B_DIR/jail.d/smarthome.local" ]]; then
            ok "fail2ban bans addresses that keep failing to log in"
        else
            note "reached from the internet: $SELF fail2ban-setup bans addresses that keep failing to log in"
        fi
    fi
}
