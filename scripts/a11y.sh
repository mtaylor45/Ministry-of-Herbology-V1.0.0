#!/bin/sh
# Run the design system's WCAG AA audit the way CI runs it. The deployment.
#
#   scripts/a11y.sh build the web app, start the mock API, audit
#   MOH_A11Y_SKIP_BUILD=1 scripts/a11y.sh reuse web/build from a previous step
#
# `npm run a11y` (web/src/lib/ui/a11y/README.md) needs three things at once:
# the API in mock mode on MOH_API_URL, a production build in web/build, and a
# Chromium. This script provides all three, runs the audit, and leaves nothing
# running. CI's Accessibility job and `make a11y` both call it, so what a
# parts of the project runs locally is what CI runs, line for line.
#
# Chromium. The audit uses MOH_A11Y_CHROMIUM when it is set and Playwright's
# own download otherwise. Neither this repository nor CI downloads one (never
# `playwright install` here), so when MOH_A11Y_CHROMIUM is unset this looks
# for a browser that is already installed: a development container's
# /opt/pw-browsers/chromium, then a system Chrome or Chromium, which GitHub's
# Ubuntu runners carry. Finding none is a failure with the reason, not a skip.
#
#   MOH_PYTHON the interpreter with api[dev] installed default: python3
#   MOH_API_PORT where the mock API listens default: 8000
#   MOH_A11Y_REPORT also write the Markdown tables here (passed through)
#   MOH_A11Y_ONLY audit only matching routes (passed through)

set -eu

ROOT=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
PYTHON=${MOH_PYTHON:-python3}
PORT=${MOH_API_PORT:-8000}
API_URL="http://127.0.0.1:$PORT"

die() { echo "a11y: $*" >&2; exit 1; }

if [ -z "${MOH_A11Y_CHROMIUM:-}" ]; then
    for candidate in /opt/pw-browsers/chromium google-chrome-stable google-chrome chromium chromium-browser; do
        case $candidate in
            /*) [ -x "$candidate" ] && MOH_A11Y_CHROMIUM=$candidate && break ;;
            *)  found=$(command -v "$candidate" 2>/dev/null || true)
                [ -n "$found" ] && MOH_A11Y_CHROMIUM=$found && break ;;
        esac
    done
fi
[ -n "${MOH_A11Y_CHROMIUM:-}" ] || die "no Chromium or Chrome found. Set MOH_A11Y_CHROMIUM to one.
This repository never runs \`playwright install\`; see web/src/lib/ui/a11y/README.md."
export MOH_A11Y_CHROMIUM
echo "a11y: browser $MOH_A11Y_CHROMIUM"

if [ -z "${MOH_A11Y_SKIP_BUILD:-}" ]; then
    echo "a11y: building the web app"
    (cd "$ROOT/web" && npm run build >/dev/null)
fi
[ -f "$ROOT/web/build/index.js" ] || die "web/build/index.js is missing; run npm run build in web/."

# The mock API. It serves fixtures and contacts nothing.
log=$(mktemp)
(cd "$ROOT" && PYTHONPATH=api:. MOH_MOCK_MODE=true \
    exec "$PYTHON" -m uvicorn app.main:app --host 127.0.0.1 --port "$PORT") >"$log" 2>&1 &
api_pid=$!
# Stop the API whatever happens to the audit, and by its pid: matching on the
# command line would match this script's own shell. Then wait for it, so that
# when this script returns the port is free and nothing is left running —
# uvicorn takes a moment to shut down gracefully after SIGTERM.
trap 'kill "$api_pid" 2>/dev/null || true; wait "$api_pid" 2>/dev/null || true; rm -f "$log"' EXIT INT TERM

i=0
until "$PYTHON" -c "import urllib.request,sys; urllib.request.urlopen('$API_URL/api/v1/healthz', timeout=2)" 2>/dev/null; do
    i=$((i + 1))
    if [ "$i" -ge 30 ] || ! kill -0 "$api_pid" 2>/dev/null; then
        cat "$log" >&2
        die "the mock API did not answer on $API_URL/api/v1/healthz."
    fi
    sleep 1
done
echo "a11y: mock API up on $API_URL"

cd "$ROOT/web"
MOH_API_URL=$API_URL npm run a11y
