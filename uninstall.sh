#!/bin/bash
# Redraft uninstaller - removes the Spoon and the managed init.lua block. Offers to remove the
# Homebrew deps the installer actually installed (recorded in install-manifest.tsv) and your config.
set -euo pipefail

HS_DIR="$HOME/.hammerspoon"
SPOON_DIR="$HS_DIR/Spoons/Redraft.spoon"
INIT="$HS_DIR/init.lua"
VENV_PARENT="$HOME/.local/share/redraft"
MANIFEST="$VENV_PARENT/install-manifest.tsv"   # written by install.sh: LABEL<TAB>UNINSTALL_CMD
CFG_DIR="$HOME/.config/redraft"
MARK_START="-- >>> redraft (managed - do not edit) >>>"
MARK_END="-- <<< redraft (managed) <<<"

info() { printf '  %s\n' "$1"; }
warn() { printf '\033[33m  %s\033[0m\n' "$1"; }
bold() { printf '\033[1m%s\033[0m\n' "$1"; }
ask() { local p="$1" a=""; if [ -r /dev/tty ]; then printf '%s' "$p" >/dev/tty; read -r a </dev/tty || true; fi; printf '%s' "$a"; }

# Offer to remove ONLY the Homebrew deps the installer actually installed (recorded in MANIFEST).
# Must run BEFORE the manifest's directory is removed. Homebrew itself is offered last (and only
# with a hard warning) since uninstalling it removes every brew package, not just Redraft's.
remove_recorded_deps() {
  [ -f "$MANIFEST" ] || return 0
  # Make `brew` reachable even if it isn't on the uninstall shell's PATH.
  command -v brew >/dev/null 2>&1 || for p in /opt/homebrew/bin/brew /usr/local/bin/brew; do
    [ -x "$p" ] && eval "$("$p" shellenv)" && break
  done
  local label cmd hb_cmd=""
  while IFS=$'\t' read -r label cmd; do
    [ -n "$label" ] || continue
    if [ "$label" = "Homebrew" ]; then hb_cmd="$cmd"; continue; fi
    if [ -z "$cmd" ]; then
      info "Redraft installed '$label' (custom command) — remove it manually if unneeded."
      continue
    fi
    case "$(ask "Remove $label (installed by Redraft)? [y/N] ")" in
      [yY]*) bold "Removing $label: $cmd"; sh -c "$cmd" || warn "Could not remove $label (already gone?)." ;;
      *) info "Kept $label." ;;
    esac
  done < "$MANIFEST"
  if [ -n "$hb_cmd" ]; then
    warn "Removing Homebrew uninstalls ALL Homebrew packages, not just Redraft's."
    case "$(ask "Remove Homebrew (installed by Redraft)? [y/N] ")" in
      [yY]*) bold "Removing Homebrew"; sh -c "$hb_cmd" || warn "Could not remove Homebrew." ;;
      *) info "Kept Homebrew." ;;
    esac
  fi
}

printf '\033[1m%s\033[0m\n' "Redraft - uninstalling"

# Stop any managed servers BEFORE removing their plists, or they keep running until logout.
UID_NUM="$(id -u)"
for label in com.redraft.languagetool com.redraft.ollama; do
  if launchctl bootout "gui/$UID_NUM/$label" >/dev/null 2>&1; then info "Stopped $label"; fi
done

rm -rf "$SPOON_DIR" && info "Removed $SPOON_DIR"

# Offer to remove installer-added Homebrew deps while the manifest still exists (under VENV_PARENT).
remove_recorded_deps

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
