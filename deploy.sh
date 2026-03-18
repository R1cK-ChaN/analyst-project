#!/usr/bin/env bash
#
# deploy.sh — deploy analyst-telegram to Contabo VPS
#
# The bot runs as a systemd service (analyst-telegram.service) with
# Restart=always. This script uses systemctl for process management.
#
# Usage:
#   ./deploy.sh              # sync + restart (default)
#   ./deploy.sh sync         # sync code only, no restart
#   ./deploy.sh restart      # restart bot only, no sync
#   ./deploy.sh stop         # stop bot
#   ./deploy.sh status       # check bot status
#   ./deploy.sh logs         # tail bot logs (journalctl)
#
set -euo pipefail

VPS="rick@vl"
SERVICE="analyst-telegram"

RSYNC_EXCLUDES=(
    --exclude='.git'
    --exclude='__pycache__'
    --exclude='*.pyc'
    --exclude='.env'
    --exclude='*.db'
    --exclude='*.db-wal'
    --exclude='*.db-shm'
    --exclude='.venv'
    --exclude='node_modules'
    --exclude='.analyst'
    --exclude='.pytest_cache'
    --exclude='*.egg-info'
    --exclude='relay_session*'
)

_remote() {
    ssh -T "$VPS" "$@"
}

do_sync() {
    echo "==> Syncing code ..."
    rsync -azq "${RSYNC_EXCLUDES[@]}" \
        "$(dirname "$0")/" "$VPS:~/analyst-project/"
    echo "    Done."

    echo "==> Installing package ..."
    _remote "cd ~/analyst-project && .venv/bin/pip install -e . -q 2>&1 | tail -3"
    echo "    Done."
}

do_stop() {
    echo "==> Stopping $SERVICE ..."
    _remote "sudo systemctl stop $SERVICE"
    echo "    Stopped."
}

do_start() {
    echo "==> Starting $SERVICE ..."
    _remote "sudo systemctl start $SERVICE"
    sleep 2
    if _remote "systemctl is-active --quiet $SERVICE"; then
        local pid
        pid=$(_remote "systemctl show -p MainPID --value $SERVICE")
        echo "    Running (PID $pid)."
    else
        echo "    ERROR: failed to start. Recent logs:"
        _remote "journalctl -u $SERVICE -n 15 --no-pager" || true
        return 1
    fi
}

do_restart() {
    echo "==> Restarting $SERVICE ..."
    _remote "sudo systemctl restart $SERVICE"
    sleep 2
    if _remote "systemctl is-active --quiet $SERVICE"; then
        local pid
        pid=$(_remote "systemctl show -p MainPID --value $SERVICE")
        echo "    Running (PID $pid)."
    else
        echo "    ERROR: failed to restart. Recent logs:"
        _remote "journalctl -u $SERVICE -n 15 --no-pager" || true
        return 1
    fi
}

do_status() {
    echo "==> Status:"
    _remote "systemctl status $SERVICE --no-pager -l" || true
}

do_logs() {
    echo "==> Logs (Ctrl+C to stop):"
    ssh -t "$VPS" "journalctl -u $SERVICE -f --no-pager"
}

# ---- Main ----
cmd="${1:-deploy}"
case "$cmd" in
    deploy|"")
        do_sync
        do_restart
        echo "==> Deploy complete."
        ;;
    sync)    do_sync ;;
    restart) do_restart ;;
    stop)    do_stop ;;
    start)   do_start ;;
    status)  do_status ;;
    logs)    do_logs ;;
    *)
        echo "Usage: $0 {deploy|sync|restart|stop|start|status|logs}"
        exit 1
        ;;
esac
