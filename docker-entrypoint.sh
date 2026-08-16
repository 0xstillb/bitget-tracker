#!/bin/sh
# Container entrypoint: run the Core API under Xvfb when the auto-login flow
# needs a headful Chromium (BITGET_HEADFUL=true, the reference behaviour).
# Xvfb runs directly (-ac = no xauth needed) because xvfb-run's xauth wrapper
# is not available in the slim image. Without DISPLAY the poller falls back to
# a headless login browser on its own.
set -e

if [ "${BITGET_HEADFUL:-true}" = "true" ] && [ -z "${DISPLAY:-}" ]; then
    Xvfb :99 -screen 0 1280x720x24 -nolisten tcp -ac &
    XVFB_PID=$!
    export DISPLAY=:99
    trap 'kill $XVFB_PID 2>/dev/null || true' EXIT TERM INT
    python run_core.py
    status=$?
    kill $XVFB_PID 2>/dev/null || true
    exit $status
fi

exec python run_core.py
