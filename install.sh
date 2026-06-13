#!/bin/bash
# Redraft installer - generic macOS text fixer (thin Hammerspoon Spoon + Python engine).
#
#   /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/<you>/redraft/HEAD/install.sh)"
#
# Idempotent: safe to re-run; cleanly replaces older/broken installs. With consent, installs
# Homebrew, Hammerspoon, and uv if missing. Uses uv to create an isolated venv with a Python
# matching the project's requires-python (uv downloads a managed interpreter if the system one
# is incompatible, e.g. 3.14), then installs the `redraft` engine into it (the Spoon runs it via
# the venv's `python -m redraft`). Wires one managed block into ~/.hammerspoon/init.lua and runs
# interactive provider configuration (Fix + Improve), setting up on-demand local servers
# (LanguageTool / Ollama) as launchd agents when chosen.
# Note: install builds the wheel + may download a Python, so it needs network / your package index.
#
# Every auto-install command (Homebrew, Hammerspoon, uv, git, JDK, Ollama) is replaceable: at the
# interactive prompt press Enter to accept the default, type a replacement, or 'n' to skip; or set
# the matching env var to run non-interactively, e.g. REDRAFT_JAVA_INSTALL="brew install --cask temurin".
set -euo pipefail

REDRAFT_GIT="${REDRAFT_GIT:-https://github.com/your-org/redraft.git}"

HS_DIR="$HOME/.hammerspoon"
SPOONS_DIR="$HS_DIR/Spoons"
SPOON_DIR="$SPOONS_DIR/Redraft.spoon"
INIT="$HS_DIR/init.lua"
DATA_DIR="$HOME/.local/share/redraft"
VENV_DIR="$DATA_DIR/venv"
LAUNCHD_DIR="$DATA_DIR/launchd"   # on-demand agents (NOT ~/Library/LaunchAgents -> no login autostart)
LOG_DIR="$DATA_DIR/logs"
LT_DIR="$DATA_DIR/languagetool"
LT_VERSION="6.6"
LT_URL="https://languagetool.org/download/LanguageTool-$LT_VERSION.zip"
CFG_DIR="$HOME/.config/redraft"
CFG="$CFG_DIR/config.json"
MARK_START="-- >>> redraft (managed - do not edit) >>>"
MARK_END="-- <<< redraft (managed) <<<"

SRC_ROOT=""
TMP_CLONE=""
EMBEDDED_SPELL=""

bold() { printf '\033[1m%s\033[0m\n' "$1"; }
info() { printf '  %s\n' "$1"; }
warn() { printf '\033[33m  %s\033[0m\n' "$1"; }
die()  { printf '\033[31mError: %s\033[0m\n' "$1" >&2; exit 1; }
cleanup() { [ -n "$TMP_CLONE" ] && rm -rf "$TMP_CLONE"; }
trap cleanup EXIT

ask() {
  local prompt="$1" ans=""
  if [ -r /dev/tty ]; then printf '%s' "$prompt" >/dev/tty; read -r ans </dev/tty || true; fi
  printf '%s' "$ans"
}
confirm() { case "$(ask "$1 [y/N] ")" in [yY]*) return 0;; *) return 1;; esac; }
interactive() { [ -r /dev/tty ]; }

# brew_install LABEL DEFAULT_CMD [OVERRIDE] [required]
# Runs a dependency-install command the user can replace. Precedence:
#   - OVERRIDE non-empty (e.g. $REDRAFT_JAVA_INSTALL) -> run it (no prompt)
#   - interactive          -> show DEFAULT; Enter accepts it, typed text replaces it, 'n' skips
#   - non-interactive      -> run DEFAULT only when 'required', else skip
# Echoes the chosen command and runs it via `sh -c`. Returns non-zero if skipped or it fails.
brew_install() {
  local label="$1" default="$2" override="${3:-}" required="${4:-}" cmd=""
  if [ -n "$override" ]; then
    cmd="$override"
  elif interactive; then
    local ans
    ans="$(ask "Install $label?  default: $default
  [Enter] run default · type a replacement command · 'n' to skip: ")"
    case "$ans" in
      n | N | no | NO) cmd="" ;;
      "") cmd="$default" ;;
      *) cmd="$ans" ;;
    esac
  elif [ -n "$required" ]; then
    cmd="$default"
  fi
  [ -n "$cmd" ] || { info "Skipped installing $label."; return 1; }
  bold "Installing $label: $cmd"
  sh -c "$cmd"
}

[ "$(uname -s)" = "Darwin" ] || die "Redraft is macOS-only."

ensure_brew() {
  command -v brew >/dev/null 2>&1 && return
  for p in /opt/homebrew/bin/brew /usr/local/bin/brew; do
    [ -x "$p" ] && eval "$("$p" shellenv)" && return
  done
  warn "Homebrew is not installed."
  if [ -n "${REDRAFT_BREW_INSTALL:-}" ]; then
    bold "Installing Homebrew: $REDRAFT_BREW_INSTALL"; sh -c "$REDRAFT_BREW_INSTALL"
  elif interactive && confirm "Install Homebrew now?"; then
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  fi
  for p in /opt/homebrew/bin/brew /usr/local/bin/brew; do
    [ -x "$p" ] && eval "$("$p" shellenv)" && break
  done
  command -v brew >/dev/null 2>&1 || die "Homebrew is required. See https://brew.sh and re-run."
}

ensure_hammerspoon() {
  [ -d "/Applications/Hammerspoon.app" ] && { info "Hammerspoon present."; return; }
  brew_install "Hammerspoon" "brew install --cask hammerspoon" "${REDRAFT_HAMMERSPOON_INSTALL:-}" required \
    || warn "Hammerspoon not installed — Redraft needs it to run."
}

ensure_uv() {
  command -v uv >/dev/null 2>&1 && return
  for p in /opt/homebrew/bin/uv /usr/local/bin/uv; do [ -x "$p" ] && return; done
  brew_install "uv" "brew install uv" "${REDRAFT_UV_INSTALL:-}" required || die "uv is required."
}

resolve_source() {
  local self dir; self="${BASH_SOURCE[0]:-$0}"
  dir="$(cd "$(dirname "$self")" 2>/dev/null && pwd || true)"
  if [ -n "$dir" ] && [ -f "$dir/pyproject.toml" ] && [ -d "$dir/Redraft.spoon" ]; then
    SRC_ROOT="$dir"; info "Source: local checkout ($dir)"
  else
    command -v git >/dev/null 2>&1 \
      || brew_install "git" "brew install git" "${REDRAFT_GIT_INSTALL:-}" required \
      || die "git is required for remote install."
    TMP_CLONE="$(mktemp -d)"
    git clone --depth 1 "$REDRAFT_GIT" "$TMP_CLONE" >/dev/null 2>&1 || die "git clone failed (set REDRAFT_GIT)."
    SRC_ROOT="$TMP_CLONE"; info "Source: $REDRAFT_GIT"
  fi
  [ -f "$SRC_ROOT/pyproject.toml" ] || die "no pyproject.toml in source."
  [ -d "$SRC_ROOT/Redraft.spoon" ] || die "no Redraft.spoon in source."
}

create_venv() {
  # uv provisions a Python matching the project's requires-python (downloading a managed one if
  # the system Python is incompatible, e.g. 3.14). Respects .python-version when present.
  local pyreq; pyreq="$(cat "$SRC_ROOT/.python-version" 2>/dev/null || echo 3.12)"
  bold "Creating Python $pyreq venv at $VENV_DIR (uv)..."
  rm -rf "$VENV_DIR"; mkdir -p "$(dirname "$VENV_DIR")"
  uv venv --python "$pyreq" "$VENV_DIR" \
    || die "uv could not provision Python $pyreq for the venv."
}

install_engine() {
  bold "Installing the engine into the venv..."
  uv pip install --python "$VENV_DIR/bin/python" "$SRC_ROOT" \
    || die "engine install failed (needs the build backend from your package index)."
  [ -x "$VENV_DIR/bin/redraft" ] || die "engine installed but the 'redraft' entry point is missing."
  info "Installed redraft -> $VENV_DIR/bin/redraft"
}

install_spoon() {
  bold "Installing the Redraft Spoon..."
  rm -rf "$SPOON_DIR"; mkdir -p "$SPOONS_DIR"
  cp -R "$SRC_ROOT/Redraft.spoon" "$SPOONS_DIR/"
  info "Spoon -> $SPOON_DIR"
}

# Seed the editable prompt templates into the config dir (cp -n preserves user edits on re-runs).
# The engine reads these if present, else falls back to the copies bundled in the package.
seed_prompts() {
  local src="$SRC_ROOT/src/redraft/prompts"
  [ -d "$src" ] || return 0
  mkdir -p "$CFG_DIR"
  cp -n "$src/"*.txt "$CFG_DIR/" 2>/dev/null || true
  info "Prompt templates -> $CFG_DIR (edit *-prompt.txt to tune; friendly = Slack, formal = email)"
}

# Return "true" / "false" / "" for the current embedded spell setting.
current_embedded_spell() {
  [ -f "$CFG" ] || return 0
  "$VENV_DIR/bin/python" - "$CFG" <<'PY'
import json, sys
try:
    cfg = json.load(open(sys.argv[1]))
    value = cfg.get("embedded", {}).get("spell")
except Exception:
    value = None
if value is True:
    print("true")
elif value is False:
    print("false")
PY
}

# Optional 'nlp' extra: better spelling for the embedded Fix provider. Engine works without it.
offer_nlp() {
  local current choice=""
  current="$(current_embedded_spell || true)"
  if interactive; then
    local prompt="Install enhanced spelling (pyspellchecker, ~7MB)? [y/N] "
    [ "$current" = "true" ] && prompt="Install enhanced spelling (pyspellchecker, ~7MB)? [Y/n] "
    case "$(ask "$prompt")" in
      [yY]*) choice="y" ;;
      [nN]*) choice="n" ;;
      *) [ "$current" = "true" ] && choice="y" ;;
    esac
  elif [ "$current" = "true" ]; then
    choice="y"
  fi
  if [ "$choice" = "y" ]; then
    bold "Installing enhanced spelling..."
    uv pip install --python "$VENV_DIR/bin/python" pyspellchecker \
      && { EMBEDDED_SPELL="true"; info "Enhanced spelling installed and enabled in config."; } \
      || { EMBEDDED_SPELL="false"; warn "Could not install pyspellchecker; embedded Fix uses the built-in typo map."; }
  elif [ "$choice" = "n" ]; then
    EMBEDDED_SPELL="false"
    info "Enhanced spelling disabled (embedded Fix uses the built-in typo map)."
  else
    info "Skipped enhanced spelling (preserving existing config; new installs default to off)."
  fi
}

wire_init() {
  bold "Wiring ~/.hammerspoon/init.lua..."
  mkdir -p "$HS_DIR"; touch "$INIT"
  local tmp; tmp="$(mktemp)"
  awk -v s="$MARK_START" -v e="$MARK_END" '
    $0==s {skip=1; next} $0==e {skip=0; next} skip!=1 {print}
  ' "$INIT" > "$tmp"
  # Remove ONLY our own legacy unmarked lines (exact, whole-line, fixed-string match) so a user's
  # own line that merely mentions spoon.Redraft is never touched.
  grep -v -F -x -e 'hs.loadSpoon("Redraft")' -e 'spoon.Redraft:start()' "$tmp" > "$tmp.2" || true
  mv "$tmp.2" "$tmp"
  { echo ""; echo "$MARK_START"; echo 'hs.loadSpoon("Redraft")'; echo 'spoon.Redraft:start()'; echo "$MARK_END"; } >> "$tmp"
  cat "$tmp" > "$INIT"; rm -f "$tmp"   # write through (preserve a symlinked init.lua + its perms)
  if [ -f "$HS_DIR/apps/redraft.lua" ] && grep -qi redraft "$HS_DIR/apps/redraft.lua" 2>/dev/null; then
    local backup="$HS_DIR/apps/redraft.lua.redraft-backup.$(date +%Y%m%d%H%M%S)"
    mv "$HS_DIR/apps/redraft.lua" "$backup"
    info "Moved legacy apps/redraft.lua -> $backup"
  fi
}

# --- Server-backed providers: on-demand launchd agents + Java resolution -----------------------

# True if $1 is a java binary reporting major version >= 17 (LanguageTool 6.x needs 17+).
java_ok() {
  local line maj
  line="$("$1" -version 2>&1 | head -1)" || return 1
  maj="$(printf '%s' "$line" | sed -E 's/.*version "([0-9]+).*/\1/')"
  [ -n "$maj" ] && [ "$maj" -ge 17 ] 2>/dev/null
}

# Print candidate `java` binary paths (one per line), active/preferred first, across every version
# manager — mise/asdf/jenv/sdkman — including *installed-but-not-active* versions (the mise case
# that prompted this), plus macOS java_home and the bare system java. Each manager is probed two
# ways: its CLI *and* a direct install-dir glob, so detection survives a manager's CLI changing.
# Unexpanded globs (no matches) stay literal and are skipped by resolve_java.
_java_candidates() {
  local m mise dir ver

  # mise: active, then each installed version (exact version string — fuzzy `java@21` misses
  # `temurin-21…`), then a data-dir glob fallback. Find the binary even if mise isn't on PATH.
  mise="$(command -v mise 2>/dev/null || true)"
  [ -n "$mise" ] || for m in "$HOME/.local/bin/mise" /opt/homebrew/bin/mise /usr/local/bin/mise; do
    [ -x "$m" ] && { mise="$m"; break; }
  done
  if [ -n "$mise" ]; then
    "$mise" which java 2>/dev/null || true
    for ver in $("$mise" ls --installed java 2>/dev/null | awk '$1=="java"{print $2}'); do
      dir="$("$mise" where "java@$ver" 2>/dev/null || true)"
      [ -n "$dir" ] && printf '%s\n%s\n' "$dir/bin/java" "$dir/Contents/Home/bin/java"
    done
  fi
  printf '%s\n' "${MISE_DATA_DIR:-$HOME/.local/share/mise}/installs/java"/*/bin/java

  # asdf: active, then installs glob (both common JDK layouts).
  if command -v asdf >/dev/null 2>&1; then
    dir="$(asdf where java 2>/dev/null || true)"; [ -n "$dir" ] && printf '%s\n' "$dir/bin/java"
  fi
  printf '%s\n' "${ASDF_DATA_DIR:-$HOME/.asdf}/installs/java"/*/bin/java \
                "${ASDF_DATA_DIR:-$HOME/.asdf}/installs/java"/*/Contents/Home/bin/java

  # jenv: active, then every registered version (symlinks under $JENV_ROOT/versions).
  if command -v jenv >/dev/null 2>&1; then jenv which java 2>/dev/null || true; fi
  printf '%s\n' "${JENV_ROOT:-$HOME/.jenv}/versions"/*/bin/java

  # sdkman: current, then every installed candidate.
  printf '%s\n' "${SDKMAN_DIR:-$HOME/.sdkman}/candidates/java/current/bin/java" \
                "${SDKMAN_DIR:-$HOME/.sdkman}/candidates/java"/*/bin/java

  # macOS java_home, then bare system java.
  if [ -x /usr/libexec/java_home ]; then
    dir="$(/usr/libexec/java_home -v 17 2>/dev/null || true)"
    [ -n "$dir" ] && printf '%s\n' "$dir/bin/java"
  fi
  command -v java 2>/dev/null || true
}

# Echo an absolute path to the first candidate that is a real Java 17+ binary; empty if none.
# launchd runs with a minimal env (no shell rc / shims), so we bake in the absolute path.
resolve_java() {
  local cands bin
  cands="$(_java_candidates || true)"
  while IFS= read -r bin; do
    [ -n "$bin" ] || continue
    case "$bin" in *'*'*) continue ;; esac   # skip globs that did not expand
    [ -x "$bin" ] && java_ok "$bin" && { printf '%s' "$bin"; return; }
  done <<EOF
$cands
EOF
  printf ''
}

# write_agent LABEL PROG ARG...  -> plist under LAUNCHD_DIR (RunAtLoad+KeepAlive, logs to LOG_DIR).
# Emitted via plistlib so paths with XML metacharacters are escaped correctly.
write_agent() {
  local label="$1"; shift
  mkdir -p "$LAUNCHD_DIR" "$LOG_DIR"
  "$VENV_DIR/bin/python" - "$LAUNCHD_DIR/$label.plist" "$label" "$LOG_DIR" "$@" <<'PY'
import plistlib, sys
plist, label, logdir, *args = sys.argv[1:]
with open(plist, "wb") as f:
    plistlib.dump({
        "Label": label,
        "ProgramArguments": args,
        "RunAtLoad": True,
        "KeepAlive": True,
        "StandardOutPath": f"{logdir}/{label}.out.log",
        "StandardErrorPath": f"{logdir}/{label}.err.log",
    }, f)
PY
  info "Agent: $LAUNCHD_DIR/$label.plist"
}

# Offer to bootstrap an agent now (on demand). It will NOT auto-start at login.
maybe_start() {
  local label="$1" name="$2" uid; uid="$(id -u)"
  if interactive && confirm "Start $name now?"; then
    launchctl bootout "gui/$uid/$label" >/dev/null 2>&1 || true
    if launchctl bootstrap "gui/$uid" "$LAUNCHD_DIR/$label.plist" 2>/dev/null; then
      info "$name started (on demand; will not auto-start at login)."
    else
      warn "Could not start $name now; start it from the Redraft menu."
    fi
  else
    info "$name registered; start it from the Redraft menu (or re-run) when needed."
  fi
}

setup_languagetool() {
  bold "Setting up LanguageTool grammar server..."
  mkdir -p "$LT_DIR"
  local jar="$LT_DIR/LanguageTool-$LT_VERSION/languagetool-server.jar"
  if [ ! -f "$jar" ]; then
    info "Downloading LanguageTool $LT_VERSION (~200MB)..."
    curl -fL --progress-bar "$LT_URL" -o "$LT_DIR/lt.zip" || { warn "Download failed; configure LanguageTool later."; return 1; }
    ( cd "$LT_DIR" && unzip -oq lt.zip ) || { warn "Could not unzip LanguageTool."; return 1; }
    rm -f "$LT_DIR/lt.zip"
  fi
  [ -f "$jar" ] || { warn "languagetool-server.jar missing after extract."; return 1; }
  local java; java="$(resolve_java)"
  if [ -z "$java" ]; then
    warn "No Java 17+ found (checked mise/asdf/jenv/sdkman/system)."
    # Default installs openjdk@17; replace at the prompt or via $REDRAFT_JAVA_INSTALL
    # (e.g. 'brew install --cask temurin'). resolve_java then auto-detects whatever was installed.
    if brew_install "Java (JDK 17+)" "brew install openjdk@17" "${REDRAFT_JAVA_INSTALL:-}"; then
      java="$(resolve_java)"
    fi
  fi
  [ -n "$java" ] && [ -x "$java" ] || { warn "LanguageTool needs Java 17+; set it up later once Java is available."; return 1; }
  info "Using Java: $java"
  # No --allow-origin: Redraft calls LanguageTool server-side (urllib), so CORS isn't needed; '*'
  # would let any local web page POST to the server.
  write_agent "com.redraft.languagetool" "$java" -cp "$jar" org.languagetool.server.HTTPServer --port 8081
  maybe_start "com.redraft.languagetool" "LanguageTool server"
}

setup_ollama() {
  local model="$1"
  if ! command -v ollama >/dev/null 2>&1; then
    brew_install "Ollama" "brew install ollama" "${REDRAFT_OLLAMA_INSTALL:-}" || warn "Ollama not installed."
  fi
  command -v ollama >/dev/null 2>&1 || { warn "Ollama unavailable; install it, then re-run to register the server."; return 1; }
  if interactive && confirm "Pull model '$model' now?"; then
    ollama pull "$model" || warn "Pull failed; run 'ollama pull $model' later."
  fi
  write_agent "com.redraft.ollama" "$(command -v ollama)" serve
  maybe_start "com.redraft.ollama" "Ollama server"
}

# --- Agent CLIs (Claude/Codex/Gemini/Copilot) ---------------------------------------------------

AGENT_TOOLS="claude codex gemini copilot"   # preference order
AGENT_TOOL="auto"
AGENT_BIN=""

# Print "tool|abspath" for each agent CLI found on the user's PATH, in preference order.
detect_agents() {
  local t p
  for t in $AGENT_TOOLS; do
    p="$(command -v "$t" 2>/dev/null || true)"
    [ -n "$p" ] && printf '%s|%s\n' "$t" "$p"
  done
}

# Choose the Improve agent: list detected ones, prompt for the preferred (default = $1, falling back
# to the first detected), and record an absolute-path hint (the engine runs with a minimal PATH).
setup_agent() {
  local want="${1:-auto}"
  AGENT_TOOL="auto"; AGENT_BIN=""
  local detected first names pick
  detected="$(detect_agents)"
  if [ -z "$detected" ]; then
    warn "No agent CLI found ($AGENT_TOOLS). Leaving tool=$want; install one and pick it from the Redraft menu."
    AGENT_TOOL="$want"; return 0
  fi
  names="$(printf '%s\n' "$detected" | cut -d'|' -f1 | tr '\n' ' ')"
  first="$(printf '%s\n' "$detected" | head -1 | cut -d'|' -f1)"
  # Default to the previously-configured tool if still detected (or 'auto'); else the first found.
  case " $names auto " in *" $want "*) ;; *) want="$first" ;; esac
  info "Detected agents: $names"
  pick="$(ask "Preferred agent [$want] (name, or 'auto'): ")"
  [ -n "$pick" ] || pick="$want"
  case " $AGENT_TOOLS auto " in
    *" $pick "*) ;;
    *) warn "Unknown agent '$pick'; using '$first'."; pick="$first" ;;
  esac
  AGENT_TOOL="$pick"
  [ "$pick" = "auto" ] || AGENT_BIN="$(printf '%s\n' "$detected" | awk -F'|' -v t="$pick" '$1==t{print $2; exit}')"
}

# --- Provider configuration (Fix + Improve), merge-written so re-runs don't clobber edits --------

# Emit shell-safe CUR_* assignments from the existing config so a reinstall pre-fills its defaults.
read_cfg() {
  [ -f "$CFG" ] || return 0
  "$VENV_DIR/bin/python" - "$CFG" <<'PY'
import json, shlex, sys
try:
    c = json.load(open(sys.argv[1]))
    c = c if isinstance(c, dict) else {}
except Exception:
    c = {}
def sub(k):
    v = c.get(k)
    return v if isinstance(v, dict) else {}
out = {
    "CUR_FIX": c.get("fixProvider", "embedded"),
    "CUR_IMPROVE": c.get("improveProvider", "none"),
    "CUR_MODEL": sub("ollama").get("model", "llama3.1:8b"),
    "CUR_FIXCMD": sub("command").get("fixCmd", ""),
    "CUR_IMPCMD": sub("command").get("improveCmd", ""),
    "CUR_AGENT": sub("agent").get("tool", "auto"),
}
for k, v in out.items():
    print(f"{k}={shlex.quote(str(v))}")
PY
}

configure_providers() {
  mkdir -p "$CFG_DIR"
  # Reuse the existing config as defaults on reinstall.
  local CUR_FIX="embedded" CUR_IMPROVE="none" CUR_MODEL="llama3.1:8b" CUR_FIXCMD="" CUR_IMPCMD="" CUR_AGENT="auto"
  eval "$(read_cfg)"
  local fix="$CUR_FIX" improve="$CUR_IMPROVE" model="$CUR_MODEL" fixcmd="$CUR_FIXCMD" impcmd="$CUR_IMPCMD"
  AGENT_TOOL="$CUR_AGENT"; AGENT_BIN=""

  # Quiet reinstall: when a config already exists, default to reusing it verbatim (Enter = reuse) —
  # no provider prompts, no server (re)setup. merge_config is idempotent and preserves keys, and any
  # launchd agents from the prior install stay registered (manage them from the menu). Type 'n' to
  # re-pick providers interactively.
  if interactive && [ -f "$CFG" ]; then
    case "$(ask "Reuse your last setup (Fix=$CUR_FIX, Improve=$CUR_IMPROVE)? [Y/n] ")" in
      [nN]*) ;;  # fall through to the interactive prompts below
      *) info "Reusing your last setup (Fix=$fix, Improve=$improve) — no changes to providers."
         merge_config "$fix" "$improve" "$model" "$fixcmd" "$impcmd" "${AGENT_TOOL:-auto}" "${AGENT_BIN:-}" "$EMBEDDED_SPELL"
         return 0 ;;
    esac
  fi

  if interactive; then
    bold "Choose providers"
    [ -f "$CFG" ] && info "(Press Enter to keep your current settings.)"
    local fixdef=1; case "$CUR_FIX" in languagetool) fixdef=2 ;; command) fixdef=3 ;; esac
    info "Fix (Opt+Cmd+F):  1) Built-in instant   2) LanguageTool grammar   3) Custom command"
    local ans; ans="$(ask "Fix provider [1/2/3] (default $fixdef): ")"; [ -n "$ans" ] || ans="$fixdef"
    case "$ans" in
      2) fix="languagetool"; setup_languagetool || warn "LanguageTool setup incomplete; finish it later." ;;
      3) fix="command"; local fc; fc="$(ask "Fix command [${CUR_FIXCMD:-none}]: ")"; fixcmd="${fc:-$CUR_FIXCMD}" ;;
      *) fix="embedded" ;;
    esac

    local impdef=4; case "$CUR_IMPROVE" in ollama) impdef=1 ;; agent) impdef=2 ;; command) impdef=3 ;; esac
    info "Improve writing (Opt+Cmd+I):  1) Ollama local AI   2) Agent CLI (external/cloud-capable)   3) Custom command   4) Skip"
    ans="$(ask "Improve provider [1/2/3/4] (default $impdef): ")"; [ -n "$ans" ] || ans="$impdef"
    case "$ans" in
      1) improve="ollama"
         local m; m="$(ask "Ollama model [$CUR_MODEL]: ")"; model="${m:-$CUR_MODEL}"
         setup_ollama "$model" || warn "Ollama setup incomplete; finish it later." ;;
      2) warn "Agent CLIs may send selected text to their provider/cloud account. Use only for text you can share with that tool."
         confirm "Use Agent CLI for Improve?" && { improve="agent"; setup_agent "$CUR_AGENT"; } || improve="none" ;;
      3) improve="command"; local ic; ic="$(ask "Improve command [${CUR_IMPCMD:-none}]: ")"; impcmd="${ic:-$CUR_IMPCMD}" ;;
      *) improve="none" ;;
    esac
  else
    info "Non-interactive: keeping existing configuration (Fix=$fix, Improve=$improve)."
  fi
  merge_config "$fix" "$improve" "$model" "$fixcmd" "$impcmd" "${AGENT_TOOL:-auto}" "${AGENT_BIN:-}" "$EMBEDDED_SPELL"
}

# Load existing config (if any), update only provider keys, write back — preserves other settings.
merge_config() {
  "$VENV_DIR/bin/python" - "$CFG" "$@" <<'PY'
import json, sys
path, fix, improve, model, fixcmd, impcmd, agent_tool, agent_bin, embedded_spell = sys.argv[1:10]
try:
    with open(path) as f:
        cfg = json.load(f)
    if not isinstance(cfg, dict):
        cfg = {}
except (FileNotFoundError, json.JSONDecodeError, OSError):
    cfg = {}
cfg.setdefault("hotkeys", {"fix": {"mods": ["cmd", "alt"], "key": "F"},
                           "improve": {"mods": ["cmd", "alt"], "key": "I"}})
cfg["fixProvider"] = fix
cfg["improveProvider"] = improve
cfg.setdefault("improveStyle", "friendly")  # Slack-friendly by default; "formal" = email tone
improve_cfg = cfg.get("improve")
if not isinstance(improve_cfg, dict):
    improve_cfg = {}
cfg["improve"] = improve_cfg
improve_cfg.setdefault("preFix", False)
emb = cfg.setdefault("embedded", {})
if embedded_spell in ("true", "false"):
    emb["spell"] = embedded_spell == "true"
emb.setdefault("spell", False)
ollama = cfg.setdefault("ollama", {"url": "http://localhost:11434"})
ollama.setdefault("url", "http://localhost:11434")
ollama["model"] = model
# Per-mode commands: Fix and Improve can use different CLIs (engine reads command.fixCmd /
# command.improveCmd, falling back to a shared command.cmd).
cmd = cfg.setdefault("command", {})
if fix == "command":
    cmd["fixCmd"] = fixcmd
if improve == "command":
    cmd["improveCmd"] = impcmd
cmd.setdefault("cmd", "")
cmd.setdefault("timeoutMs", 60000)
ag = cfg.setdefault("agent", {})
if "agent" in (fix, improve):
    ag["tool"] = agent_tool or "auto"
    if agent_bin:
        ag.setdefault("bins", {})[agent_tool] = agent_bin
ag.setdefault("tool", "auto")
ag.setdefault("timeoutMs", 120000)
# Materialize each agent's command template into config so users can edit flags (e.g. codex's
# --skip-git-repo-check) without touching code. setdefault preserves any edits on re-runs.
try:
    from redraft.providers.agent import default_commands, legacy_commands
    cmds = ag.setdefault("commands", {})
    legacy = legacy_commands()
    for _name, _tmpl in default_commands().items():
        if cmds.get(_name) in (None, legacy.get(_name)):
            cmds[_name] = _tmpl
except Exception:
    pass
cfg.setdefault("languagetool", {"url": "http://localhost:8081", "language": "en-US"})
# Notification categories (read by the Spoon): set any to false to silence that type. Seed from the
# engine's single source so the default lives in one place; setdefault preserves edits on re-runs.
try:
    from redraft.config import DEFAULTS as _ENGINE_DEFAULTS
    cfg.setdefault("notifications", dict(_ENGINE_DEFAULTS["notifications"]))
except Exception:
    pass
with open(path, "w") as f:
    json.dump(cfg, f, indent=2)
PY
  info "Wrote $CFG"
}

# Reload without stealing focus or re-launching a running Hammerspoon (re-activation can
# re-trigger the macOS Accessibility prompt even when it's already granted).
reload_hs() {
  if command -v hs >/dev/null 2>&1 && hs -c 'hs.reload()' >/dev/null 2>&1; then
    HS_RELOADED=1; return
  fi
  if pgrep -xq Hammerspoon; then
    HS_RELOADED=0 # running; user reloads from the menu
  else
    open -g -a Hammerspoon 2>/dev/null || true; HS_RELOADED=1
  fi
}

HS_RELOADED=0
bold "Redraft - installing"
ensure_brew
ensure_hammerspoon
ensure_uv
resolve_source
create_venv
install_engine
offer_nlp
install_spoon
wire_init
configure_providers
seed_prompts
reload_hs

echo
bold "Done."
if [ "$HS_RELOADED" != "1" ]; then
  info "* In Hammerspoon's menu, choose 'Reload Config' to pick up changes."
fi
info "* First run only: if macOS prompts, grant Hammerspoon Accessibility"
info "  (System Settings -> Privacy & Security -> Accessibility). Already granted? Nothing to do."
info "* Redraft reports status/errors in Notification Center. If you see none, allow Hammerspoon"
info "  in System Settings -> Notifications."
info "* Select text anywhere -> Opt+Cmd+F (fix) or Opt+Cmd+I (improve). The menu-bar icon controls it."
echo
info "Config: $CFG   -   Uninstall: bash uninstall.sh"
