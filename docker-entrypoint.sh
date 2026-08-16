#!/bin/sh
# Container entrypoint: run the Core API under Xvfb when the auto-login flow
# needs a headful Chromium (BITGET_HEADFUL=true, the reference behaviour).
# xvfb-run picks a free display; without DISPLAY the poller falls back to a
# headless login browser on its own.
set -e

if [ "${BITGET_HEADFUL:-true}" = "true" ] && [ -z "${DISPLAY:-}" ]; then
    exec xvfb-run -a -s "-screen 0 1280x720x24" python run_core.py
fi

exec python run_core.py
