#!/usr/bin/env bash
# Nginx hardening smoke test (HTTP)
set -euo pipefail

HOST="${1:-51.21.152.197}"
PORT="${2:-80}"
URL="http://$HOST:$PORT"

echo "=== NGINX smoke test for $URL ==="

case_do() { echo -e "\n--- $1 ---"; shift; echo "Command: $*"; "$@"; }

# 1) GET /
case_do "GET /" curl -s -o /dev/null -w "%{http_code}\n" "$URL/"

# 2) GET /robots.txt
case_do "GET /robots.txt" curl -s -o /dev/null -w "%{http_code}\n" "$URL/robots.txt"

# 3) GET /favicon.ico (200 jeśli jest, 404 jeśli brak)
case_do "GET /favicon.ico" curl -s -o /dev/null -w "%{http_code}\n" "$URL/favicon.ico"

# 4) 404 dla nieistniejącego
case_do "GET /no_such_file.html" curl -s -o /dev/null -w "%{http_code}\n" "$URL/no_such_file.html"

# 5) PUT → 444 (curl: Empty reply)
case_do "PUT / (expect 444/empty)" bash -lc "curl -v -X PUT '$URL/' 2>&1 | grep -E 'Empty reply|HTTP' || true"

# 6) CONNECT → 444 (curl: Empty reply)
case_do "CONNECT / (expect 444/empty)" bash -lc "curl -v -X CONNECT '$URL/' 2>&1 | grep -E 'Empty reply|HTTP' || true"

# 7) Rate limit
echo -e "\n--- Rate limit (15 req in parallel) ---"
for i in $(seq 1 15); do curl -s -o /dev/null -w "%{http_code} " "$URL/" & done; wait; echo
echo "=== DONE ==="

