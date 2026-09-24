#!/bin/sh
# Runs inside the pgbackup container: one verified dump now, then every 24 hours; keeps KEEP_DAYS days.
set -eu
while true; do
  file="/backups/career-agent-$(date -u +%Y%m%d-%H%M%S).dump"
  if pg_dump --format=custom --file="$file.part" && pg_restore --list "$file.part" > /dev/null; then
    mv "$file.part" "$file"
    echo "backup ok: $file"
  else
    rm -f "$file.part"
    echo "backup FAILED" >&2
  fi
  find /backups -name 'career-agent-*.dump' -mtime +"${KEEP_DAYS:-14}" -delete
  sleep 86400
done
