#!/usr/bin/env bash
# Destroys one environment's two pipeline apps, the Fly app and the DigitalOcean app, and checks
# both are gone (#32, #51). Its one argument names the environment, and the app names are built
# from it alone, so a run stops only that environment's apps. Used by teardown (rehearsal) and
# Night Close (the store it closed).
set -euo pipefail

if [ "$#" -ne 1 ] || { [ "$1" != rehearsal ] && [ "$1" != night ]; }; then
  echo "usage: shutdown.sh <rehearsal|night>" >&2
  exit 2
fi
fly_app="toronto-election-$1-fly"
do_app="toronto-election-$1-do"

# Each list is captured first: a failed call stops the script instead of reading as no app.
apps=$(flyctl apps list --json)
if jq -e --arg app "$fly_app" 'any(.[]; .Name == $app)' <<< "$apps" > /dev/null; then
  flyctl apps destroy "$fly_app" --yes
fi
apps=$(flyctl apps list --json)
jq -e --arg app "$fly_app" 'all(.[]; .Name != $app)' <<< "$apps" > /dev/null

apps=$(doctl apps list -o json)
for id in $(jq -r --arg app "$do_app" '.[]? | select(.spec.name == $app) | .id' <<< "$apps"); do
  doctl apps delete "$id" --force
done
apps=$(doctl apps list -o json)
jq -e --arg app "$do_app" '[.[]? | select(.spec.name == $app)] | length == 0' <<< "$apps" > /dev/null

echo "Destroyed \`$fly_app\` on Fly and \`$do_app\` on DigitalOcean."
