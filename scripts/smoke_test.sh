#!/usr/bin/env bash
# Smoke test for a running CampusRide instance.
# Usage: scripts/smoke_test.sh <BASE_URL>
set -euo pipefail
BASE_URL="${1:-http://localhost:8000}"
echo "Smoke test against ${BASE_URL}"
# /health
code=$(curl -s -o /tmp/cr_health -w "%{http_code}" "${BASE_URL}/health")
echo "  GET /health -> ${code}"
test "${code}" = "200" || { echo "  /health did not return 200"; cat /tmp/cr_health; exit 1; }
grep -Eq '"ok"[[:space:]]*:[[:space:]]*true' /tmp/cr_health || { echo "  /health did not report ok"; cat /tmp/cr_health; exit 1; }
# /  (home page renders)
code=$(curl -s -o /tmp/cr_home -w "%{http_code}" "${BASE_URL}/")
echo "  GET / -> ${code}"
test "${code}" = "200" || { echo "  / did not return 200"; exit 1; }
grep -q "CampusRide" /tmp/cr_home || { echo "  home page missing title"; exit 1; }
# CSP header present
curl -sI "${BASE_URL}/" | grep -i "content-security-policy" >/dev/null || { echo "  CSP header missing"; exit 1; }
# 404 page
code=$(curl -s -o /tmp/cr_404 -w "%{http_code}" "${BASE_URL}/does-not-exist")
echo "  GET /does-not-exist -> ${code}"
test "${code}" = "404" || { echo "  404 page did not return 404"; exit 1; }
# Member pages redirect to login (none required yet, but unknown member page returns 404 with no info leak)
code=$(curl -s -o /tmp/cr_unknown -w "%{http_code}" "${BASE_URL}/trips")
echo "  GET /trips (unauthenticated) -> ${code}"
test "${code}" = "404" -o "${code}" = "302" || { echo "  unexpected unauth response"; exit 1; }
echo "OK"
