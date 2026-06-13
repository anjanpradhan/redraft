#!/bin/bash
# Redraft uninstaller - removes the Spoon and the managed init.lua block. Leaves Hammerspoon and
# Homebrew alone. Asks before removing your config.
set -euo pipefail

HS_DIR="$HOME/.hammerspoon"
SPOON_DIR="$HS_DIR/Spoons/Redraft.spoon"
INIT="$HS_DIR/init.lua"
VENV_PARENT="$HOME/.local/share/redraft"
CFG_DIR="$HOME/.config/redraft"
MARK_START="-- >>> redraft (managed - do not edit) >>>"
MARK_END="-- <<< redraft (managed) <<<"

info() { printf '  %s\n' "$1"; }
ask() { local p="$1" a=""; if [ -r /dev/tty ]; then printf '%s' "$p" >/dev/tty; read -r a </dev/tty || true; fi; printf '%s' "$a"; }

printf '\033[1m%s\033[0m\n' "Redraft - uninstalling"

# Stop any managed servers BEFORE removing their plists, or they keep running until logout.
UID_NUM="$(id -u)"
for label in com.redraft.languagetool com.redraft.ollama; do
  if launchctl bootout "gui/$UID_NUM/$label" >/dev/null 2>&1; then info "Stopped $label"; fi
done

rm -rf "$SPOON_DIR" && info "Removed $SPOON_DIR"
rm -rf "$VENV_PARENT" && info "Removed $VENV_PARENT (venv, agents, logs, LanguageTool)"

if [ -f "$INIT" ]; then
  tmp="$(mktemp)"
  awk -v s="$MARK_START" -v e="$MARK_END" '
    $0==s {skip=1; next} $0==e {skip=0; next} skip!=1 {print}
  ' "$INIT" > "$tmp"
  # Only our own legacy unmarked lines (exact whole-line match) — never a user's own references.
  grep -v -F -x -e 'hs.loadSpoon("Redraft")' -e 'spoon.Redraft:start()' "$tmp" > "$tmp.2" || true
  cat "$tmp.2" > "$INIT"; rm -f "$tmp" "$tmp.2"   # write through (preserve symlinked init.lua)
  info "Cleaned managed block from init.lua"
fi

if [ -d "$CFG_DIR" ]; then
  case "$(ask "Remove config at $CFG_DIR? [y/N] ")" in
    [yY]*) rm -rf "$CFG_DIR"; info "Removed $CFG_DIR" ;;
    *) info "Kept $CFG_DIR" ;;
  esac
fi

command -v hs >/dev/null 2>&1 && hs -c 'hs.reload()' >/dev/null 2>&1 || true
echo
info "Done. Reload Hammerspoon if it didn't auto-reload."
