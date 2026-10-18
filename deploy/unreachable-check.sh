#!/usr/bin/env bash
# Fails a deploy whose `flyctl deploy` output skipped a Machine on an unreachable host (#111).
# Fly carries on without it, and the Machine comes back on the old image once its host does: on
# Oct 16 a Mock Feed Machine ran beside its replacement for about 40 hours. Takes the deploy's
# captured output and the app name.
set -euo pipefail

if [ "$#" -ne 2 ]; then
  echo "usage: unreachable-check.sh <deploy log> <app>" >&2
  exit 2
fi
ids=$(sed -n 's/.*Skipped lease for unreachable machine \([0-9a-f]*\).*/\1/p' "$1" | sort -u)
[ -z "$ids" ] && exit 0
for id in $ids; do
  echo "::error::Fly skipped Machine $id on an unreachable host; it will come back on the old image."
  echo "Remove it: flyctl machine destroy $id -a $2 --force"
done
exit 1
