#!/bin/sh
# Install (or reinstall) a launchd job from deploy/launchd/ for the current user (macOS).
#   scripts/install_launchd.sh disruptions   # poll every 5 min
#   scripts/install_launchd.sh backup        # nightly copy of data/live (needs BACKUP_REMOTE)
# Works from an SSH session if the user is logged in on the Mac (gui domain); otherwise
# falls back to the user domain.
set -eu

name=${1:?usage: $0 disruptions|backup}
cd "$(dirname "$0")/.."
repo=$(pwd)
template="deploy/launchd/idf-crowding.$name.plist.in"
[ -f "$template" ] || { echo "no template $template" >&2; exit 1; }
uv_bin=$(command -v uv) || { echo "uv not found in PATH" >&2; exit 1; }

label="idf-crowding.$name"
plist="$HOME/Library/LaunchAgents/$label.plist"
mkdir -p logs "$HOME/Library/LaunchAgents"
sed -e "s|@REPO@|$repo|g" -e "s|@UV@|$uv_bin|g" -e "s|@PATH@|$PATH|g" "$template" > "$plist"

uid=$(id -u)
for domain in "gui/$uid" "user/$uid"; do
    launchctl bootout "$domain/$label" 2>/dev/null || true
    if launchctl bootstrap "$domain" "$plist" 2>/dev/null; then
        echo "loaded $label in $domain"
        launchctl print "$domain/$label" | grep -E "state|last exit code|run interval" || true
        exit 0
    fi
done
echo "could not load $plist (log in to the Mac once, then retry)" >&2
exit 1
