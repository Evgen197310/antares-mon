#!/usr/bin/env bash
# -----------------------------------------------------------------------------
#  mikrotik-discover.sh
#
#  Подключается по SSH к каждому MikroTik из mikrotik.router_access_ips
#  Берёт /system identity и все активные IPv4 адреса интерфейсов
#  Обновляет:
#    - /etc/rsyslog.d/mikrotik_map.txt (ip|IDENTITY)  -> paths.mikrotik_map_short
#    - /var/lib/mikrotik/full_map.csv (identity,ip,mask,interface,flags) -> paths.mikrotik_map
# -----------------------------------------------------------------------------
set -euo pipefail

CONF="/etc/infra/config.json"

ROUTERS=($(jq -r '.mikrotik.router_access_ips[]' "$CONF"))
SSH_USER=$(jq -r '.mikrotik.ssh_user' "$CONF")
SSH_KEY=$(jq -r '.mikrotik.ssh_key' "$CONF")
MAP_FILE=$(jq -r '.paths.mikrotik_map_short' "$CONF")
FULL_FILE=$(jq -r '.paths.mikrotik_map' "$CONF")
FULL_DIR=$(dirname "$FULL_FILE")
SSH_OPTS=(-i "$SSH_KEY" -o BatchMode=yes -o ConnectTimeout=5 -o StrictHostKeyChecking=accept-new)

mkdir -p "$FULL_DIR"

TMP_MAP="$(mktemp)"
TMP_CSV="$(mktemp)"

for host in "${ROUTERS[@]}"; do
  identity=$(ssh "${SSH_OPTS[@]}" "$SSH_USER@$host" ':put [/system identity get name]' 2>/dev/null | tr -d '\r\n' || true)
  [[ -z $identity ]] && { echo "WARN: $host — identity не получен" >&2; continue; }

  raw=$(ssh "${SSH_OPTS[@]}" "$SSH_USER@$host" '/ip address print detail without-paging where disabled=no' 2>/dev/null || true)
  [[ -z $raw ]] && { echo "WARN: $host ($identity) — адресов нет" >&2; continue; }

  awk -v id="$identity" -v map="$TMP_MAP" -v csv="$TMP_CSV" '
      /address=/ {
          flag = "-";
          for (i = 1; i <= 3; i++) if ($i ~ /^[A-Z]$/) flag = $i;
          match($0, /address=([0-9.]+)\/([0-9]+)/, a); ip=a[1]; mask=a[2];
          match($0, /interface=([[:alnum:]._-]+)/, b); intf=b[1];
          if (ip != "") {
              printf "%s|%s\n", ip, id >> map;
              printf "%s,%s,%s,%s,%s\n", id, ip, mask, intf, flag >> csv;
          }
      }
  ' <<< "$raw"
done

sort -u "$TMP_MAP" > "$MAP_FILE"
sort -u "$TMP_CSV" > "$FULL_FILE"

echo "✓ $(wc -l <"$MAP_FILE") IP-строк → $MAP_FILE"
echo "✓ $(wc -l <"$FULL_FILE") строк  → $FULL_FILE"

rm -f "$TMP_MAP" "$TMP_CSV"
