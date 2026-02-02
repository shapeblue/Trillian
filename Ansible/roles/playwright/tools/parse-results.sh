#!/bin/bash
#Copyright 2016 ShapeBlue
#
#Licensed under the Apache License, Version 2.0 (the "License");
#you may not use this file except in compliance with the License.
#You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
#Unless required by applicable law or agreed to in writing, software
#distributed under the License is distributed on an "AS IS" BASIS,
#WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#See the License for the specific language governing permissions and
#limitations under the License.

# parse-results.sh: Parse Playwright JSON results and generate summary

RESULTS_FILE="${1:?Usage: $0 <json-results-file> [summary-file]}"
SUMMARY_FILE="${2:-playwright-summary.txt}"

if [ ! -f "$RESULTS_FILE" ]; then
    echo "Error: Results file not found: $RESULTS_FILE"
    exit 1
fi

if ! command -v jq >/dev/null 2>&1; then
    echo "Error: jq is required to parse JSON results"
    exit 1
fi

# Extract test statistics from Playwright JSON report
TOTAL_TESTS=$(jq '.stats.expected' "$RESULTS_FILE" 2>/dev/null || echo 0)
PASSED_TESTS=$(jq '[.suites[]? | .tests[]? | select(.status == "passed")] | length' "$RESULTS_FILE" 2>/dev/null || echo 0)
FAILED_TESTS=$(jq '[.suites[]? | .tests[]? | select(.status == "failed")] | length' "$RESULTS_FILE" 2>/dev/null || echo 0)
SKIPPED_TESTS=$(jq '[.suites[]? | .tests[]? | select(.status == "skipped")] | length' "$RESULTS_FILE" 2>/dev/null || echo 0)
DURATION=$(jq '.stats.duration' "$RESULTS_FILE" 2>/dev/null || echo 0)

# Convert duration to seconds
DURATION_SECONDS=$((DURATION / 1000))

# Calculate percentages
if [ "$TOTAL_TESTS" -gt 0 ]; then
    PASS_RATE=$((PASSED_TESTS * 100 / TOTAL_TESTS))
else
    PASS_RATE=0
fi

# Generate summary
{
    echo "================================"
    echo "Playwright Test Summary"
    echo "================================"
    echo "Test Run Date: $(date --iso-8601=seconds)"
    echo ""
    echo "Test Results:"
    echo "  Total Tests: $TOTAL_TESTS"
    echo "  Passed: $PASSED_TESTS"
    echo "  Failed: $FAILED_TESTS"
    echo "  Skipped: $SKIPPED_TESTS"
    echo "  Pass Rate: ${PASS_RATE}%"
    echo ""
    echo "Duration: ${DURATION_SECONDS}s ($(($DURATION_SECONDS / 60))m $(($DURATION_SECONDS % 60))s)"
    echo ""
    
    if [ "$FAILED_TESTS" -gt 0 ]; then
        echo "Failed Tests:"
        jq -r '.suites[]? | select(.tests[]? | select(.status == "failed")) | .file' "$RESULTS_FILE" 2>/dev/null | while read -r file; do
            echo "  - $file"
        done
        echo ""
        echo "Status: FAILED"
        OVERALL_STATUS=1
    else
        echo "Status: PASSED"
        OVERALL_STATUS=0
    fi
    
    echo "================================"
} | tee "$SUMMARY_FILE"

exit $OVERALL_STATUS
