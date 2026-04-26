#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
GRUS_ROOT="$REPO_ROOT/grus"
export PYTHONPATH="$REPO_ROOT:$GRUS_ROOT"
LOG_DIR="$GRUS_ROOT/logs"
PID_FILE="$GRUS_ROOT/run_all.pids"

mkdir -p "$LOG_DIR"
mkdir -p "$GRUS_ROOT/data"

# ─────────────────────────────────────────────────────────────────────────────
# Cleanup: kill all services on exit (Ctrl+C, SIGTERM, or normal exit)
# ─────────────────────────────────────────────────────────────────────────────

PIDS=()
_CLEANED_UP=false

cleanup() {
    $_CLEANED_UP && return
    _CLEANED_UP=true
    echo ""
    echo "==> Stopping services..."
    for pid in "${PIDS[@]}"; do
        if kill -0 "$pid" 2>/dev/null; then
            kill "$pid"
            echo "    killed pid $pid"
        fi
    done
    rm -f "$PID_FILE"
    echo "==> Done."
}

trap cleanup EXIT SIGINT SIGTERM

# ─────────────────────────────────────────────────────────────────────────────
# Start a service, log to file, record PID
# ─────────────────────────────────────────────────────────────────────────────

start_service() {
    local name="$1"
    local script="$2"
    local port="$3"
    local log_file="$LOG_DIR/${port}-${name// /_}.log"

    python -m "$script" > "$log_file" 2>&1 &
    local pid=$!
    PIDS+=("$pid")
    echo "  [$pid]  $name  →  $log_file"
    echo "$name $pid" >> "$PID_FILE"
}

# ─────────────────────────────────────────────────────────────────────────────
# Wait until a port is accepting connections
# ─────────────────────────────────────────────────────────────────────────────

wait_for_port() {
    local name="$1"
    local port="$2"
    local retries=20
    local wait=0.5

    for i in $(seq 1 $retries); do
        if python -c "
import socket, sys
s = socket.socket()
s.settimeout(1)
try:
    s.connect(('localhost', $port))
    s.close()
    sys.exit(0)
except Exception:
    sys.exit(1)
" 2>/dev/null; then
            echo "    $name ready on port $port"
            return 0
        fi
        sleep "$wait"
    done

    echo "    ERROR: $name did not come up on port $port after $retries attempts"
    exit 1
}

# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

echo "=== Kill Switch Relay ==="
echo ""

rm -f "$PID_FILE"

echo "==> Starting services..."

# Start in dependency order: Flag Store depends on all three below
start_service "Policy Evaluator" "policy_evaluator.server" 50052
wait_for_port  "Policy Evaluator" 50052

start_service "Audit Logger"     "audit_logger.server"    50054
wait_for_port  "Audit Logger"     50054

start_service "Broadcaster"      "broadcaster.server"     50053
wait_for_port  "Broadcaster"      50053

start_service "Flag Store"       "flag_store.server"      50051
wait_for_port  "Flag Store"       50051

echo ""
echo "==> All services running."
echo ""
echo "    Flag Store       localhost:50051"
echo "    Policy Evaluator localhost:50052"
echo "    Broadcaster      localhost:50053"
echo "    Audit Logger     localhost:50054"
echo ""
echo "    PIDs written to: $PID_FILE"
echo "    Logs in:         $LOG_DIR/"
echo ""
echo "    Press Ctrl+C to stop all services."
echo ""

# Stay alive until signal
wait
