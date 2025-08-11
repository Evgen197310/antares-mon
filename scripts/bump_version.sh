#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FILE="$ROOT/VERSION"
PART="${1:-patch}" # patch|minor|major
TAG="${TAG:-true}" # TAG=false чтобы не создавать git tag

if [[ ! -f "$FILE" ]]; then
  echo "2.0" > "$FILE"
fi

VER="$(tr -d ' \n\r' < "$FILE")"
# Поддержка форматов 2.1 и 2.1.3
if [[ "$VER" =~ ^([0-9]+)\.([0-9]+)(\.[0-9]+)?$ ]]; then
  MAJ="${BASH_REMATCH[1]}"
  MIN="${BASH_REMATCH[2]}"
  PAT="${BASH_REMATCH[3]#.}"
else
  echo "Некорректный VERSION: '$VER'"; exit 1
fi
PAT="${PAT:-0}"

case "$PART" in
  major) MAJ=$((MAJ+1)); MIN=0; PAT=0;;
  minor) MIN=$((MIN+1)); PAT=0;;
  patch) PAT=$((PAT+1));;
  *) echo "Использование: $0 [major|minor|patch]"; exit 1;;
esac

NEW="$MAJ.$MIN"
# Если хотите хранить патч-версию, раскомментируйте следующую строку:
# NEW="$MAJ.$MIN.$PAT"

echo "$NEW" > "$FILE"
# mtime файла VERSION = время релиза
touch "$FILE"

# Зафиксируем изменения
if git rev-parse --git-dir > /dev/null 2>&1; then
  git add "$FILE"
  git commit -m "chore(version): bump to $NEW" || true
  if [[ "$TAG" == "true" ]]; then
    git tag -f "v$NEW" || true
  fi
else
  echo "Внимание: не git-репозиторий, пропускаю commit/tag"
fi

echo "Новая версия: $NEW"
