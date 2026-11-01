#!/bin/bash
# remediate-smoke-setup.sh: fetch the remediate smoke bundle from the staging
# server and run the remediate apply smoke on this environment with it.
#
# Runs on the Marvin VM through Trillian's post-deploy hook (products/remediate.yml):
#
#   build_marvin=yes post_deploy_script=remediate-smoke-setup.sh
#   post_deploy_script_args=--version=0.1.0            optional; default latest
#
# Everything about remediate (SSH keys on the hosts, waiting for the zone,
# env.yaml, lab -prepare, the smoke, the results) is in the bundle's
# scripts/trillian-smoke.sh, kept and versioned in the remediate repository
# with the CLI and runbooks it drives (make smoke-bundle there; its
# docs/internal/apply-smoke.md section 7.6). This script only downloads the
# bundle, unpacks it and hands over. The hook sources
# /marvin/post-deploy/trillian-env.sh first; the TRILLIAN_* variables there are
# what the bundle's script reads. Run it again with /marvin/post-deploy/run.sh.
#
# Options (each also takes the --opt=value form, which needs no spaces, as
# Jenkins ANY_OTHER_OPTS splits on spaces):
#   --version V     remediate-smoke-V.tar.gz from http://<staging server>/remediate/
#                   (default: remediate-smoke-latest.tar.gz, or the newest
#                   remediate-smoke-<v>.tar.gz listed there when it is missing)
#   --bundle URL    any other bundle URL (or REMEDIATE_BUNDLE_URL)
#   --dir DIR       working directory (default /marvin/remediate); the bundle
#                   unpacks into DIR/release
#   anything else goes to the bundle's scripts/trillian-smoke.sh (--no-smoke,
#   --only, --from, --all, --skip-prepare, --wait-minutes; see its --help)
#
# Exit code: trillian-smoke.sh's (0 passed, 1 some failed, 2 the lab was left
# dirty, 3 setup failed, 4 the zone never became ready); 3 also when the bundle
# could not be fetched or unpacked.

set -uo pipefail

BUNDLE_URL=${REMEDIATE_BUNDLE_URL:-}
VERSION=latest
DIR=/marvin/remediate
PASS=()

while [ $# -gt 0 ]; do
  case "$1" in
    --*=*) set -- "${1%%=*}" "${1#*=}" "${@:2}"; continue ;;
    --version) VERSION=$2; shift 2 ;;
    --bundle) BUNDLE_URL=$2; shift 2 ;;
    --dir) DIR=$2; shift 2 ;;
    -h|--help) sed -n '2,/^$/p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) PASS+=("$1"); shift ;;
  esac
done

log() { printf '%s %s\n' "$(date +%H:%M:%S)" "$*"; }
die() { log "FAILED: $*"; exit 3; }

for c in curl tar flock; do
  command -v "$c" >/dev/null || die "$c is not installed on this VM"
done
if [ -z "$BUNDLE_URL" ]; then
  [ -n "${TRILLIAN_STAGING_SERVER:-}" ] || die "no TRILLIAN_STAGING_SERVER (source /marvin/post-deploy/trillian-env.sh), or pass --bundle <url>"
  BUNDLE_BASE="http://$TRILLIAN_STAGING_SERVER/remediate"
  BUNDLE_URL="$BUNDLE_BASE/remediate-smoke-$VERSION.tar.gz"
fi

mkdir -p "$DIR" && chmod 700 "$DIR"
# Held from here through the smoke (the bundle's script inherits it), so a
# second run cannot replace the bundle under one that is using it
exec 9>"$DIR/.lock"
flock -n 9 || die "another remediate smoke is running in $DIR"

if [ "$VERSION" = latest ] && [ -n "${BUNDLE_BASE:-}" ] && ! curl -fsIL -o /dev/null "$BUNDLE_URL"; then
  # No remediate-smoke-latest.tar.gz: the newest release listed, else the newest pre-release
  newest=$(curl -fsSL "$BUNDLE_BASE/" | grep -o 'remediate-smoke-[0-9][A-Za-z0-9._+-]*\.tar\.gz' \
           | sed 's/^remediate-smoke-//; s/\.tar\.gz$//' | sort -uV \
           | awk '/-/ { pre = $0; next } { rel = $0 } END { print (rel != "" ? rel : pre) }')
  [ -n "$newest" ] || die "no $BUNDLE_URL and no remediate-smoke-<version>.tar.gz listed in $BUNDLE_BASE/"
  log "no remediate-smoke-latest.tar.gz; using the newest listed, $newest"
  BUNDLE_URL="$BUNDLE_BASE/remediate-smoke-$newest.tar.gz"
fi
log "fetching $BUNDLE_URL"
curl -fsSL --retry 3 -o "$DIR/bundle.tar.gz" "$BUNDLE_URL" || die "could not download $BUNDLE_URL"

REL="$DIR/release"
rm -rf "$REL" && mkdir -p "$REL"
tar_quiet=""
tar --version 2>/dev/null | grep -q GNU && tar_quiet="--warning=no-unknown-keyword"
tar $tar_quiet -xzf "$DIR/bundle.tar.gz" -C "$REL" || die "could not unpack $BUNDLE_URL"
idx=$(find "$REL" -maxdepth 3 -path '*/catalogue/index.yaml' | head -1)
[ -n "$idx" ] || die "$BUNDLE_URL has no catalogue/index.yaml: not a remediate smoke bundle"
REL=$(cd "$(dirname "$idx")/.." && pwd)
RUN="$REL/scripts/trillian-smoke.sh"
[ -f "$RUN" ] || die "$BUNDLE_URL has no scripts/trillian-smoke.sh; rebuild it with make smoke-bundle in remediate"
[ -f "$REL/VERSION" ] && log "bundle version $(cat "$REL/VERSION")"

export REMEDIATE_BUNDLE_URL=$BUNDLE_URL REMEDIATE_SMOKE_LOCKED=1
exec bash "$RUN" --dir "$DIR" ${PASS[@]+"${PASS[@]}"}
