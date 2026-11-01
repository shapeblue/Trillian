#!/bin/bash
# remediate-smoke-setup.sh: prepare a Trillian environment for the remediate
# apply smoke and run it (remediate: docs/internal/apply-smoke.md, section 7.5).
#
# Runs on the Marvin VM through Trillian's post-deploy hook:
#
#   build_marvin=yes post_deploy_script=remediate-smoke-setup.sh
#   post_deploy_script_args=--version=0.1.0            optional; default latest
#
# The hook writes /marvin/post-deploy/trillian-env.sh (API URL and keys, DB,
# management and KVM host addresses and passwords) and sources it first. To run
# it again by hand on the Marvin VM:
#
#   /marvin/post-deploy/run.sh                          same arguments as the build
#   cd /marvin/post-deploy && . ./trillian-env.sh && ./remediate-smoke-setup.sh --bundle <url> [options]
#
# Options:
#   --version V         bundle remediate-smoke-V.tar.gz from the staging server
#                       (default: remediate-smoke-latest.tar.gz, or the newest
#                       remediate-smoke-<v>.tar.gz listed there when it is missing)
#                       Every option also takes the --opt=value form, which needs
#                       no spaces (Jenkins ANY_OTHER_OPTS splits on spaces).
#   --bundle URL        any other bundle URL (or REMEDIATE_BUNDLE_URL)
#   --no-smoke          prepare and check the lab, do not run the smoke
#   --only LIST         smoke -only LIST (comma separated runbooks)
#   --from RUNBOOK      smoke -from RUNBOOK
#   --all               smoke -all (every runbook in the tree, listed or not)
#   --skip-prepare      do not run lab -prepare
#   --dir DIR           working directory (default /marvin/remediate)
#   --wait-minutes N    how long to wait for the zone to be ready (default 90)
#
# The bundle is a tarball built from remediate/product and published on the
# staging server (TRILLIAN_STAGING_SERVER, Trillian's stagingserverip) under
# /remediate/, so the Marvin VM needs no git checkout and no git credentials:
#
#   GOOS=linux GOARCH=amd64 CGO_ENABLED=0 go build -o bin/remediate-cli ./cmd/remediate-cli
#   tar czf remediate-smoke-<version>.tar.gz bin/remediate-cli runbooks catalogue \
#       supported-versions.yaml scripts/smoke-lab-hosts.sh
#   (on macOS: COPYFILE_DISABLE=1 tar --no-xattrs --no-mac-metadata czf ..., or the
#   Apple file attributes come along and GNU tar warns about each file)
#   then on the staging server, in its web root's remediate/ directory:
#   ln -sfn remediate-smoke-<version>.tar.gz remediate-smoke-latest.tar.gz
#
# What it does, in order:
#   1. unpacks the bundle into <dir>/release
#   2. makes an SSH key, records the host keys of every management server and
#      KVM host, and installs the key on them with their root passwords
#   3. waits until every KVM host is Up, both system VMs run and a featured KVM
#      template is ready
#   4. works out the lab section (one KVM cluster per distribution family) from
#      listHosts and each host's /etc/os-release
#   5. writes <dir>/env.yaml
#   6. check-schema, scripts/smoke-lab-hosts.sh --apply, lab -prepare, lab
#   7. estate (the base record), then smoke, unless --no-smoke
#
# Results are in <dir>/results/<time>/ (and <dir>/results/latest). Exit code:
# the smoke's (0 passed, 1 some failed, 2 lab unreadable or left dirty), or the
# lab check's with --no-smoke; 3 setup failed; 4 the zone never became ready.

set -uo pipefail

BUNDLE_URL=${REMEDIATE_BUNDLE_URL:-}
VERSION=latest
SMOKE=1
ONLY=""
FROM=""
ALL=0
PREPARE=1
DIR=/marvin/remediate
WAIT_MIN=90

while [ $# -gt 0 ]; do
  case "$1" in
    --*=*) set -- "${1%%=*}" "${1#*=}" "${@:2}"; continue ;;
    --version) VERSION=$2; shift 2 ;;
    --bundle) BUNDLE_URL=$2; shift 2 ;;
    --no-smoke) SMOKE=0; shift ;;
    --only) ONLY=$2; shift 2 ;;
    --from) FROM=$2; shift 2 ;;
    --all) ALL=1; shift ;;
    --skip-prepare) PREPARE=0; shift ;;
    --dir) DIR=$2; shift 2 ;;
    --wait-minutes) WAIT_MIN=$2; shift 2 ;;
    -h|--help) sed -n '2,/^$/p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option $1" >&2; exit 3 ;;
  esac
done

log() { printf '%s %s\n' "$(date +%H:%M:%S)" "$*"; }
die() { log "FAILED: $*"; exit "${2:-3}"; }

for v in TRILLIAN_API_URL TRILLIAN_API_KEY TRILLIAN_SECRET_KEY TRILLIAN_DB_HOST TRILLIAN_DB_ROOT_PASSWORD \
         TRILLIAN_MGMT_IPS TRILLIAN_MGMT_PASSWORD TRILLIAN_KVM_IPS TRILLIAN_KVM_PASSWORD; do
  [ -n "${!v:-}" ] || die "$v is not set; source /marvin/post-deploy/trillian-env.sh first"
done
if [ -z "$BUNDLE_URL" ]; then
  [ -n "${TRILLIAN_STAGING_SERVER:-}" ] || die "no staging server in trillian-env.sh: pass --bundle <url>"
  BUNDLE_BASE="http://$TRILLIAN_STAGING_SERVER/remediate"
  BUNDLE_URL="$BUNDLE_BASE/remediate-smoke-$VERSION.tar.gz"
fi
for c in curl tar python3 ssh ssh-keygen ssh-keyscan ssh-copy-id ssh-agent sshpass timeout; do
  command -v "$c" >/dev/null || die "$c is not installed on this VM"
done

mkdir -p "$DIR" && chmod 700 "$DIR"
exec 9>"$DIR/.lock"
flock -n 9 || die "another remediate-smoke-setup.sh is running in $DIR"

RUN_ID=$(date +%Y%m%d-%H%M%S)
RES="$DIR/results/$RUN_ID"
mkdir -p "$RES"
ln -sfn "$RES" "$DIR/results/latest"
SUMMARY="$RES/SUMMARY.txt"
note() { log "$*"; printf '%s\n' "$*" >> "$SUMMARY"; }
note "remediate smoke on Trillian environment ${TRILLIAN_ENV_NAME:-?} (CloudStack ${TRILLIAN_CS_VERSION:-?}), run $RUN_ID"

################################################################################
# CloudStack API helper (signed requests; no cmk profile needed)
CSAPI="$DIR/csapi.py"
cat > "$CSAPI" <<'PY'
"""csapi.py: the few CloudStack calls remediate-smoke-setup.sh needs.

  csapi.py ready <kvm host count>   prints what the zone is still waiting for; exit 0 when ready
  csapi.py hosts                    prints "name ip cluster" per KVM Routing host
"""
import base64, hashlib, hmac, json, os, sys, urllib.parse, urllib.request

def call(command, **params):
    params.update(command=command, response="json", apikey=os.environ["TRILLIAN_API_KEY"])
    # Java's URLEncoder leaves * unencoded, and the server signs what it decodes
    query = "&".join("%s=%s" % (k, urllib.parse.quote(str(v), safe="*"))
                     for k, v in sorted(params.items(), key=lambda kv: kv[0].lower()))
    digest = hmac.new(os.environ["TRILLIAN_SECRET_KEY"].encode(), query.lower().encode(), hashlib.sha1).digest()
    url = "%s?%s&signature=%s" % (os.environ["TRILLIAN_API_URL"], query,
                                  urllib.parse.quote(base64.b64encode(digest).decode(), safe=""))
    with urllib.request.urlopen(url, timeout=60) as r:
        body = json.loads(r.read().decode())
    return next(iter(body.values()))

def items(command, key, **params):
    # One page (default.page.size, 500) is plenty for a lab
    return call(command, **params).get(key, [])

def ready(expected):
    waiting = []
    hosts = items("listHosts", "host", type="Routing", hypervisor="KVM")
    up = [h for h in hosts if h.get("state") == "Up"]
    if len(up) < expected:
        waiting.append("KVM hosts Up: %d of %d" % (len(up), expected))
    vms = items("listSystemVms", "systemvm")
    for kind in ("secondarystoragevm", "consoleproxy"):
        ok = [v for v in vms if v.get("systemvmtype") == kind and v.get("state") == "Running"
              and v.get("agentstate", "Up") == "Up"]
        if not ok:
            waiting.append("%s not Running with its agent Up" % kind)
    tmpl = items("listTemplates", "template", templatefilter="featured", hypervisor="KVM")
    if not [t for t in tmpl if t.get("isready")]:
        waiting.append("no featured KVM template ready")
    print("; ".join(waiting) if waiting else "ready")
    return 0 if not waiting else 1

def hosts():
    for h in sorted(items("listHosts", "host", type="Routing", hypervisor="KVM"), key=lambda h: h["name"]):
        print(h["name"], h.get("ipaddress", ""), h.get("clustername", ""))
    return 0

if __name__ == "__main__":
    try:
        if sys.argv[1] == "ready":
            sys.exit(ready(int(sys.argv[2])))
        if sys.argv[1] == "hosts":
            sys.exit(hosts())
    except Exception as e:  # the API not up yet reads as "not ready", not a crash
        print("API: %s" % e)
        sys.exit(2)
    sys.exit("usage: csapi.py ready <n> | hosts")
PY

################################################################################
# 1. The bundle
REL="$DIR/release"
if [ "$VERSION" = latest ] && [ -n "${BUNDLE_BASE:-}" ] && ! curl -fsIL -o /dev/null "$BUNDLE_URL"; then
  # No remediate-smoke-latest.tar.gz: take the newest versioned bundle in the listing
  newest=$(curl -fsSL "$BUNDLE_BASE/" | grep -o 'remediate-smoke-[0-9][A-Za-z0-9._+-]*\.tar\.gz' \
           | sed 's/^remediate-smoke-//; s/\.tar\.gz$//' | sort -uV \
           | awk '/-/ { pre = $0; next } { rel = $0 } END { print (rel != "" ? rel : pre) }')
  [ -n "$newest" ] || die "no $BUNDLE_URL and no remediate-smoke-<version>.tar.gz listed in $BUNDLE_BASE/"
  log "no remediate-smoke-latest.tar.gz; using the newest listed, $newest"
  BUNDLE_URL="$BUNDLE_BASE/remediate-smoke-$newest.tar.gz"
fi
log "fetching $BUNDLE_URL"
curl -fsSL --retry 3 -o "$DIR/bundle.tar.gz" "$BUNDLE_URL" || die "could not download $BUNDLE_URL"
rm -rf "$REL" && mkdir -p "$REL"
tar_quiet=""
tar --version 2>/dev/null | grep -q GNU && tar_quiet="--warning=no-unknown-keyword"
tar $tar_quiet -xzf "$DIR/bundle.tar.gz" -C "$REL" || die "could not unpack the bundle"
idx=$(find "$REL" -maxdepth 3 -path '*/catalogue/index.yaml' | head -1)
[ -n "$idx" ] || die "the bundle has no catalogue/index.yaml"
REL=$(cd "$(dirname "$idx")/.." && pwd)
CLI="$REL/bin/remediate-cli"
[ -x "$CLI" ] || chmod +x "$CLI" 2>/dev/null
[ -x "$CLI" ] && [ -d "$REL/runbooks" ] || die "the bundle needs bin/remediate-cli and runbooks/"
"$CLI" -h >/dev/null 2>&1 || [ $? -le 2 ] || die "bin/remediate-cli does not run here (built for linux/amd64?)"
note "bundle: $BUNDLE_URL"

################################################################################
# 2. SSH: a key of our own, every host's key recorded, our key installed
KEY="$DIR/ssh/id_ed25519"
KNOWN=/root/.ssh/known_hosts
mkdir -p "$DIR/ssh" /root/.ssh && chmod 700 "$DIR/ssh" /root/.ssh
[ -f "$KEY" ] || ssh-keygen -q -t ed25519 -N '' -C "remediate-smoke@${TRILLIAN_ENV_NAME:-trillian}" -f "$KEY" \
  || die "could not create an SSH key"
touch "$KNOWN" && chmod 600 "$KNOWN"

wait_ssh() {  # wait_ssh <ip>: up to 10 minutes for port 22
  local _
  for _ in $(seq 1 60); do
    timeout 5 bash -c "</dev/tcp/$1/22" 2>/dev/null && return 0
    sleep 10
  done
  return 1
}

trust_host() {  # trust_host <ip> <root password>
  local ip=$1
  wait_ssh "$ip" || { note "  $ip: no SSH after 10 minutes"; return 1; }
  ssh-keygen -q -R "$ip" -f "$KNOWN" >/dev/null 2>&1
  ssh-keyscan -T 10 -t ed25519,ecdsa,rsa "$ip" 2>/dev/null >> "$KNOWN"
  ssh-keygen -F "$ip" -f "$KNOWN" >/dev/null || { note "  $ip: ssh-keyscan returned nothing"; return 1; }
  if ! ssh -n -i "$KEY" -o BatchMode=yes -o ConnectTimeout=10 "root@$ip" true 2>/dev/null; then
    SSHPASS=$2 sshpass -e ssh-copy-id -i "$KEY.pub" -o ConnectTimeout=10 "root@$ip" >/dev/null 2>&1
  fi
  ssh -n -i "$KEY" -o BatchMode=yes -o ConnectTimeout=10 "root@$ip" true 2>/dev/null \
    || { note "  $ip: key login refused after ssh-copy-id"; return 1; }
  log "  $ip: host key recorded, key installed"
}

log "SSH to the management servers and KVM hosts"
ssh_fail=0
for ip in $TRILLIAN_MGMT_IPS; do trust_host "$ip" "$TRILLIAN_MGMT_PASSWORD" || ssh_fail=1; done
for ip in $TRILLIAN_KVM_IPS; do trust_host "$ip" "$TRILLIAN_KVM_PASSWORD" || ssh_fail=1; done
[ $ssh_fail = 0 ] || die "SSH could not be set up on every host (see above)"

eval "$(ssh-agent -s)" >/dev/null
trap 'ssh-agent -k >/dev/null 2>&1' EXIT
ssh-add -q "$KEY" 2>/dev/null || die "could not add the key to ssh-agent"

################################################################################
# 3. The zone ready: hosts Up, system VMs running, a template to deploy
want=$(echo $TRILLIAN_KVM_IPS | wc -w)
log "waiting up to $WAIT_MIN minutes for the zone ($want KVM hosts)"
deadline=$(( $(date +%s) + WAIT_MIN * 60 ))
last=""
while :; do
  state=$(python3 "$CSAPI" ready "$want")
  [ "$state" = ready ] && break
  [ "$state" != "$last" ] && log "  waiting: $state" && last=$state
  [ "$(date +%s)" -lt $deadline ] || die "the zone was not ready after $WAIT_MIN minutes: $state" 4
  sleep 30
done
note "zone ready"

################################################################################
# 4. The lab section: one cluster per family, from what CloudStack and the
#    hosts themselves say
family() {  # family <ip>: el, ubuntu, debian, suse or unknown
  ssh -n -i "$KEY" -o BatchMode=yes -o ConnectTimeout=10 "root@$1" \
    '. /etc/os-release; echo "$ID $ID_LIKE"' 2>/dev/null | awk '{
      if ($1 == "ubuntu") print "ubuntu";
      else if ($1 == "debian") print "debian";
      else if ($0 ~ /suse|sles/) print "suse";
      else if ($0 ~ /rhel|fedora|centos|ol|rocky|almalinux/) print "el";
      else print "unknown" }'
}

python3 "$CSAPI" hosts > "$RES/hosts.txt" || die "listHosts failed: $(cat "$RES/hosts.txt")"
: > "$RES/families.txt"
while read -r name ip cluster; do
  [ -n "$name" ] || continue
  printf '%s %s %s %s\n' "$(family "$ip")" "$cluster" "$name" "$ip" >> "$RES/families.txt"
done < "$RES/hosts.txt"

# For each family the cluster holding most of its hosts, and that cluster's hosts
LAB=$(awk '
  $1 != "unknown" { n[$1 SUBSEP $2]++; hosts[$1 SUBSEP $2] = hosts[$1 SUBSEP $2] " " $3; fams[$1] = 1 }
  END {
    split("el ubuntu debian suse", order, " ")
    print "lab:"; print "  clusters:"
    for (i = 1; i <= 4; i++) { f = order[i]; if (!(f in fams)) continue
      best = ""; for (k in n) { split(k, p, SUBSEP); if (p[1] == f && (best == "" || n[k] > n[best])) best = k }
      split(best, p, SUBSEP); cl[f] = p[2]; hl[f] = hosts[best]
      printf "    %s: \"%s\"\n", f, p[2] }
    print "  hosts:"
    for (i = 1; i <= 4; i++) { f = order[i]; if (!(f in fams)) continue
      m = split(substr(hl[f], 2), hs, " "); line = ""
      for (j = 1; j <= m; j++) line = line (j > 1 ? ", " : "") "\"" hs[j] "\""
      printf "    %s: [%s]\n", f, line }
  }' "$RES/families.txt")
note "KVM hosts (family cluster name ip):"
sed 's/^/  /' "$RES/families.txt" | tee -a "$SUMMARY"
for f in el ubuntu debian suse; do
  grep -q "^$f " "$RES/families.txt" || note "  no $f host: its scenarios will be reported not-run"
done
[ "$(grep -c '^el ' "$RES/families.txt")" -ge 2 ] || note "  fewer than two EL hosts: the HA kill scenario needs two"
grep -q '^unknown ' "$RES/families.txt" && note "  a host's distribution was not recognised and is left out"

################################################################################
# 5. env.yaml
yq() { printf '"%s"' "$(printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g')"; }
ENVF="$DIR/env.yaml"
umask 077
{
  echo "# Written by remediate-smoke-setup.sh for Trillian environment ${TRILLIAN_ENV_NAME:-?}. Holds credentials."
  echo "cloudstack:"
  echo "  url: $(yq "$TRILLIAN_API_URL")"
  echo "  apiKey: $(yq "$TRILLIAN_API_KEY")"
  echo "  secretKey: $(yq "$TRILLIAN_SECRET_KEY")"
  echo "database:"
  echo "  dsn: $(yq "root:${TRILLIAN_DB_ROOT_PASSWORD}@tcp(${TRILLIAN_DB_HOST}:3306)/cloud?parseTime=true&timeout=10s")"
  echo "ssh:"
  echo "  user: root"
  echo "  keyFile: $KEY"
  echo "  port: 22"
  echo "  knownHosts: $KNOWN"
  echo "managementServers:"
  for ip in $TRILLIAN_MGMT_IPS; do echo "  - $ip"; done
  printf '%s\n' "$LAB"
} > "$ENVF"
umask 022
note "env.yaml: $ENVF"

################################################################################
# 6. Lab checks and preparation; 7. the smoke. Run from the release, where
#    runbooks/ and catalogue/ are.
cd "$REL" || die "cannot enter $REL"
step() {  # step <name> <command...>: run, log to results, return its exit code
  local name=$1; shift
  log "== $name"
  "$@" > "$RES/$name.log" 2>&1
  local rc=$?
  tail -n 40 "$RES/$name.log"
  note "$name: exit $rc"
  return $rc
}

step check-schema "$CLI" check-schema -env "$ENVF"
if [ -f "$REL/scripts/smoke-lab-hosts.sh" ]; then
  step lab-hosts sh "$REL/scripts/smoke-lab-hosts.sh" "$ENVF" --apply
else
  note "lab-hosts: skipped, the bundle has no scripts/smoke-lab-hosts.sh"
fi
[ $PREPARE = 1 ] && step lab-prepare "$CLI" lab -env "$ENVF" -prepare -o "$RES/lab-prepare.yaml"
step lab "$CLI" lab -env "$ENVF" -o "$RES/lab.yaml"
lab_rc=$?

if [ $SMOKE = 0 ]; then
  note "smoke not run (--no-smoke); run it with: cd $REL && $CLI smoke -env $ENVF"
  exit $lab_rc
fi
[ $lab_rc = 0 ] || note "the lab check reports something missing; the smoke runs anyway and those scenarios fail at pick or prepare"

step estate "$CLI" estate -env "$ENVF" -o "$RES/base.yaml"
args=(smoke -env "$ENVF" -report "$RES/smoke-report.yaml")
[ -n "$ONLY" ] && args+=(-only "$ONLY")
[ -n "$FROM" ] && args+=(-from "$FROM")
[ $ALL = 1 ] && args+=(-all)
step smoke "$CLI" "${args[@]}"
smoke_rc=$?
case $smoke_rc in
  0) note "smoke: every scenario passed, or was plan-only or manual" ;;
  1) note "smoke: some scenarios failed; see $RES/smoke-report.yaml" ;;
  2) note "smoke: STOPPED, the lab could not be read or was left dirty. The lab is evidence: look before rerunning (--from)" ;;
esac
note "results: $RES"
exit $smoke_rc
