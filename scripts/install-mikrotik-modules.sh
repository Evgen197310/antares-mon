#!/usr/bin/env bash
# Install MikroTik infrastructure modules from repository into /usr/local/bin
# Does not modify production beyond local machine when executed; intended for deployment steps.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

echo "[+] Installing scripts to /usr/local/bin"
install -Dm0755 "$ROOT_DIR/scripts/mikrotik-discover.sh" /usr/local/bin/mikrotik-discover.sh
install -Dm0755 "$ROOT_DIR/scripts/auto-rsyslog-rules-generate.sh" /usr/local/bin/auto-rsyslog-rules-generate.sh
install -Dm0755 "$ROOT_DIR/scripts/sync-lists.py" /usr/local/bin/sync-lists.py
install -Dm0755 "$ROOT_DIR/scripts/clear-addr.py" /usr/local/bin/clear-addr.py

echo "[+] Ensuring directories exist"
mkdir -p /var/lib/mikrotik /var/log/mikrotik

cat << 'EOF'
[OK] Scripts installed.
To run initial discovery & lists sync (optional, perform in maintenance window):
  /usr/local/bin/mikrotik-discover.sh && \
  /usr/local/bin/auto-rsyslog-rules-generate.sh && \
  systemctl restart rsyslog && \
  /usr/local/bin/sync-lists.py

To enable cron (append to root crontab):
  0 3 * * * /usr/local/bin/mikrotik-discover.sh && /usr/local/bin/auto-rsyslog-rules-generate.sh && systemctl restart rsyslog && /usr/local/bin/sync-lists.py >> /var/log/mikrotik_discover.log 2>&1
EOF
