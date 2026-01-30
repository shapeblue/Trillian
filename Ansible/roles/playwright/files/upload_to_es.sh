#!/bin/bash
#
# upload_to_es.sh - simple uploader for Playwright results JSON
#

ES_HOST="${PLAYWRIGHT_ES_HOST:-elk.lab.lon}"
ES_INDEX="${PLAYWRIGHT_ES_INDEX:-playwright-results}"
FILE="$1"

if [ -z "$FILE" ]; then
    echo "Usage: $0 <json-file>"
    exit 1
fi

if [ ! -f "$FILE" ]; then
    echo "File $FILE not found"
    exit 1
fi

if command -v curl >/dev/null 2>&1; then
    echo "Uploading $FILE to $ES_HOST:9200/$ES_INDEX/external"
    curl -s -XPOST "$ES_HOST:9200/$ES_INDEX/external?pretty" \
        -H 'Content-Type: application/json' \
        -d @"$FILE" || true
else
    echo "curl not available, skipping upload"
fi
