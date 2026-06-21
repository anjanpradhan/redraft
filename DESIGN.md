# Redraft — Design

A tiny **macOS** tool that fixes or improves text **in any input field**. Select text, press a
hotkey, and the selection is replaced in place with a cleaned-up version. Local-first, no app
integration. Built-in, LanguageTool, and Ollama providers stay on your machine; Agent/Custom are
explicit opt-ins and may send text to the CLI or cloud account you configure.

- **Fix only (⌥⌘F)** — deterministic typo/grammar fixes; no tone change.
- **Improve writing (⌥⌘I)** — clearer, professional, polite, friendly.

> The name is deliberate: Redraft *proposes* a redraft that replaces your selection in place — you
> accept it by keeping it or undo (⌘Z) to revert; it never claims the result is "correct" or "better."

## Architecture: thin Spoon + Python engine

Two layers, split for maintainability:

```
selection ─⌘C→ Redraft.spoon (Lua: hotkeys, menu-bar, enable/disable)
                 │  hs.task → <venv>/bin/python3 -m redraft --mode fix --input <tmpfile>
                 ▼
            Python engine (the `redraft` package) → reads ~/.config/redraft/config.json
                 │  protect → optional embedded pre-fix for Improve → provider → invariant → restore
                 ▼  prints {revised, change_notes, risk_flags} | {error}  (JSON on stdout)
            Spoon ─⌘V→ replaces selection
```

- **Hammerspoon Spoon** = thin trigger + UI only: global hotkeys, copy/paste-replace, menu-bar
  (status, pause/resume + restart, provider switch with the active provider shown inline,
  on-demand server Start/Stop/Restart via `launchctl`, edit/reload config). Must be Hammerspoon —
  that's where macOS global hotkeys + selection access live. `init.lua` is the entrypoint; focused
  modules under `Redraft.spoon/lib/` own clipboard, focus, UI, config, services, action, and menu code.
- **Python engine** = all logic (protection, token invariant, embedded fixer, five providers,
  config). A proper **`src/redraft` package** built with hatchling, typed, **stdlib-only at
  runtime** (no third-party runtime deps), and **unit-tested with pytest**. This is where
  enhancement happens.
- **venv + console script.** The installer creates an isolated venv at
  `~/.local/share/redraft/venv` and **pip-installs the package** into it, exposing the
  `redraft` console script. The Spoon runs the engine via the venv's **`python3 -m redraft`** per
  keystroke as a short-lived **subprocess** (launching the binary directly is more robust under
  `hs.task` than relying on the console-script shebang; selection handed over via a temp file).
  No server/daemon, no port.

## Why this split

An earlier all-in-Lua Spoon fused trigger and logic into one untyped, untestable, Lua-pattern-
limited file. Moving the engine to a Python package makes the logic typed, unit-testable, and
enhanceable, with standard tooling (uv, ruff, pytest, pre-commit, tox); Hammerspoon stays a
minimal, low-risk trigger. Cost: a second runtime (Python via Homebrew) and a wheel build at
install time.

## Engine ↔ Spoon contract

- Spoon runs `<venv>/bin/python3 -m redraft --mode {fix|improve} --input <file> [--app <bundle>]`
  (selection in the file; `--app` is the frontmost app's bundle id, selecting a per-app provider
  profile; the `redraft` console script is the equivalent entry point).
- Engine stdout: `{"revised","change_notes","risk_flags","provider","mode"}` on success (plus
  optional `command`/`prompt`/`raw` for shell/LLM providers — resolved command display, full prompt
  sent, and raw model/CLI response), or `{"error": "..."}` (exit 1) on failure. On any error the Spoon posts a macOS Notification Center
  notification (all status/success/errors go there via `hs.notify`, newest replacing the previous)
  and leaves the selection untouched (restoring the clipboard). The **success** notification
  surfaces the result: subtitle `Fixed`/`Improved · <provider>`, body a bounded change summary
  (up to 3 `change_notes`), with any `risk_flags` led by a `⚠`. The Spoon also guards on the
  engine binary being absent ("run install.sh").

## Review pipeline (engine)

1. **Protect** — replace high-signal technical spans with opaque `{{R:n}}` tokens: `inline code`,
   `[markdown](links)`, URLs, emails, `$ENV` vars, file paths (`./x`, `~/x`, multi-segment
   `/a/b`), version strings (`v1.2.3` / bare 3-part `1.2.3`), `@mentions`, `#channels`, and any
   literal `{{R:n}}` the user typed (so a user's own brace-token round-trips instead of colliding).
   Every pattern is **sigil-anchored** (a backtick, `http`, the `@…\.` email shape, `$`, a leading
   `./`/`../`/`~/` or a ≥2-segment `/abs` path off a word boundary, a `v`-prefix or 3+ dotted parts,
   `@`/`#`) so prose is never swept up — `and/or`, `12/25/2024`, `3.14`, a markdown `# Heading`.
2. **Provider** — run the mode's provider on the protected projection.
3. **Invariant** — a per-review **multiset** check: each token id appears exactly once (order may
   change), no unknown ids. Violation → reject (the user's text is left unchanged).
4. **Restore** — expand tokens back to their original spans.

The safety net that lets a small/local model be used without risking corruption of code/links.
`src/redraft/protect.py` + `src/redraft/engine.py`.

## Providers (config-selectable per mode)

| Provider | Modes | Impl | Notes |
|---|---|---|---|
| `embedded` | Fix (default) | pure Python (`providers/embedded.py`) | curated typo/contraction map, `i`→`I`, abbreviation-aware sentence caps, whitespace/punct tidies; edits only text between tokens. Optional `pyspellchecker` spelling is **opt-in / off by default** (`embedded.spell`) |
| `languagetool` | Fix | `urllib` → local LanguageTool server | broader deterministic grammar/spell; skips matches overlapping tokens |
| `ollama` | Improve | `urllib` → Ollama `/api/chat` (JSON schema) | local LLM tone/clarity rewrite |
| `agent` | Improve | an authenticated agent CLI (claude/codex/gemini/copilot) | **external/cloud-capable opt-in**; `tool=auto` or a pick; binary resolved live (PATH + known dirs) so a later-installed agent works; templates/bins overridable |
| `command` | Fix or Improve | `subprocess` → a configured CLI | shell out to any local CLI; data flow depends on that command; stdin/prompt-file prompt → stdout JSON |

`ReviewResult` + the `Provider` protocol are in `base.py`; the shared LLM-provider helpers
(`build_prompt`, `extract_json`, `build_result`) are in `prompt.py`. **Prompts are config-tunable
templates**: `build_prompt(mode, text, config)` splices the protected text into a template's
`<message>` slot, choosing `fix` for Fix and — for Improve — `config.improveStyle` (`friendly` =
Slack, default · `formal` = email). Each template resolves from a user file
(`<config>/<key>-prompt.txt`) → the bundled default (`src/redraft/prompts/<key>-prompt.txt`,
shipped as package data, seeded to the config dir by the installer) → a minimal fallback; the
token rule + JSON envelope live in the template (the multiset invariant still rejects bad output).
CLI-shelling providers
(`command`, `agent`) share `providers/_shell.py` (`run`: sh -c with prompt on stdin or a
mode-0600 `{prompt_file}`; `{prompt_arg}` is the explicit argv fallback → JSON → validated result);
selection is `pick_provider` (`providers/__init__.py`) and enforces each provider's supported
modes. Adding a provider = one
module + one registry line. Unformatted technical plaintext identifiers (`p95`, bare HTTP verbs like
`POST`) are *not* auto-protected — wrap them in backticks. API-style paths such as `/v1/foo` are
protected by the path rule.

## Trigger & menu-bar (Spoon)

- Hotkeys from config (default ⌥⌘F / ⌥⌘I); `redraft(mode)` = capture focused app/window/AX element
  → copy → run engine (async via `hs.task`, so Hammerspoon never freezes during a slow Improve) →
  paste only if focus still matches, restore the original clipboard payload. Our
  clipboard writes are tagged transient/auto-generated (nspasteboard.org), so compliant clipboard
  managers don't log the revised text or the restore as history entries. (The app's own `⌘C` of the
  selection can't be tagged — that's the one entry that may still appear.) The copied selection is
  **cleared from the clipboard immediately after it's read** (a transient empty write), so the text
  doesn't linger on the pasteboard while the engine runs; the original clipboard is restored at the end
  via Hammerspoon's all-data pasteboard API, with text as a compatibility fallback. The selection
  hand-off file is written under a private
  `~/.local/share/redraft/tmp` directory (`0700`, file `0600`). During an Improve run the
  menu-bar title animates a braille **spinner** (Fix is instant, so it doesn't).
- Needs Hammerspoon **Accessibility** permission (one-time) to synthesize ⌘C/⌘V.
- **Notifications** (`hs.notify`) carry a category — `fix`/`improve` (success), `status`, `error` —
  and `config.notifications` can silence any (e.g. `{"fix": false}` mutes Fix toasts but keeps
  errors). All have a click callback so a click never falls back to Hammerspoon's default
  (open-console); a **success** notification's click opens a copyable **result modal** (`hs.webview`:
  a titled/bordered panel with per-section Copy — the revised text, change notes, risk flags, and —
  for shell/LLM providers — the agent's **raw** response plus collapsible **command** and **prompt**
  panes, all carried in the engine's output JSON). An **error** click opens the full error text in
  the same modal. The result is stashed regardless of muting, so **Show last result…** reopens it.
- Menu-bar (`hs.menubar`): ◆ running / ◇ paused header; **Pause/Resume** (enable/disable hotkeys)
  and **Restart** (reload config *and* rebind hotkeys). **Fix:** / **Improve:** submenus show the
  active provider in their title and write `config.json` on switch; Improve shows `(not configured)`
  until set and a `Turn off` once set. An **Improve style** submenu switches `improveStyle` between
  **Slack — friendly** and **Email — formal** (applies to whichever Improve provider is active).
  **Fix before Improve** toggles `improve.preFix`, an opt-in embedded Fix pass before an Improve
  provider. For a selected server-backed provider (LanguageTool/Ollama)
  with an installed launchd plist, a **server submenu** offers **Start/Stop/Restart** (via `launchctl`,
  with a live ●/○ status). **Show last result…**, **Edit/Reload config**, and **Quit** (full
  teardown — unbind hotkeys + remove the menu-bar icon; servers left running; restored via
  Hammerspoon's Reload Config). Pause only disables hotkeys; Quit removes the icon entirely.

## Config

`~/.config/redraft/config.json`, read by the engine and the Spoon (the Spoon also writes it on a
provider switch, preserving other keys): `fixProvider`, `improveProvider`,
`improveStyle` (`friendly`|`formal`), `improve{preFix}`, `hotkeys`,
`embedded{spell}`, `ollama{url,model}`, `agent{tool,timeoutMs,bins,commands}` (tool =
auto|claude|codex|gemini|copilot; `commands` are per-tool shell templates **seeded by the installer
from `agent.default_commands()` and editable in config** — `{bin}` = resolved CLI path,
`{prompt_file}` = mode-0600 prompt file, `{prompt_arg}` = prompt argv fallback; `bins` optionally
pins a path),
`command{cmd,fixCmd,improveCmd,timeoutMs}` (per-mode commands override the shared `cmd`),
`languagetool{url,language}`, `profiles` (per-app overrides keyed by the frontmost app's
**bundle id** — each value may set `fixProvider`/`improveProvider`, falling back to the top-level
keys; the Spoon passes the active app via `redraft --app <bundle>`, edited in config.json only),
and `notifications{fix,improve,status,error}` (Spoon-only; each `false` silences that category).
Engine defaults are in `src/redraft/config.py`.

## Develop / tooling

Standard uv-managed Python project:

```bash
uv sync                        # create .venv, install dev+test groups, install redraft editable
uv run pytest                  # tests (pytest)
uv run pre-commit run -a       # validate-pyproject, typos, ruff check+format, hooks
uv run tox                     # 3.12 / 3.13 matrix
```

`pyproject.toml` (hatchling, `packages=["src/redraft"]`, console script `redraft=redraft.cli:main`,
ruff/pytest/tox config) · `.pre-commit-config.yaml` · `_typos.toml` (the fix-map/examples are
deliberate misspellings) · `.python-version` (3.12).

## Install / reinstall / uninstall

`install.sh` (the `curl … | bash` one-liner): with consent installs **Homebrew → Hammerspoon →
uv**. Every auto-install command is **user-replaceable** (interactive: Enter/accept, type a
replacement, or skip; or a `REDRAFT_*_INSTALL` env var) — so e.g. Temurin can stand in for
`openjdk@17` with no vendor logic in the installer; Java resolution then detects any JDK 17+. **uv creates the venv with a Python matching `requires-python`** — downloading a managed
3.12/3.13 if the system Python is incompatible (e.g. 3.14), so the user needn't change their
system Python or the project's version pin — then installs the engine into it (`redraft` console
script). It copies the **Spoon** (local checkout, else `git clone`), wires one **managed block**
into `~/.hammerspoon/init.lua` (idempotent; strips legacy lines/files), and runs **interactive
provider config**: choose the **Fix** provider (Built-in / LanguageTool / Custom) and **Improve**
provider (Ollama / Agent / Custom / Skip; Agent is warned as external/cloud-capable before it is
enabled). The enhanced-spelling prompt controls both package install and `embedded.spell`; on
reinstall it defaults to the previous spelling setting so an opted-in setup remains opted in. It
then offers **"Reuse your last setup?"**
(Enter = yes) for a quiet, prompt-free re-run; declining drops into the interactive prompts,
**pre-filled from the existing config** (Enter keeps each). Config is **merge-written** (via the
venv Python) so re-runs update only the provider keys and never clobber other settings. Re-running
cleanly replaces older/broken installs.

**Server-backed providers (LanguageTool, Ollama)** are managed as **on-demand launchd agents**
written to `~/.local/share/redraft/launchd/` — intentionally *not* `~/Library/LaunchAgents`, so
they never auto-start at login (`RunAtLoad`+`KeepAlive` apply only once you bootstrap them; they
restart on crash while running, stay down across reboots). The menu's Start/Stop/Restart maps to
`launchctl bootstrap`/`bootout`/`kickstart -k`. LanguageTool runs from the official server jar
under a **host Java resolved honoring mise/asdf/jenv/sdkman/system (Java 17+)** — *installed*
versions, not just the active one, probed via each manager's CLI **and** an install-dir glob so
detection survives CLI changes — baked as an absolute path into the plist (launchd has no shell
shims); `brew install openjdk@17` is the fallback. Plists are emitted with `plistlib` (correct XML escaping), config with `json` — never
string interpolation. `uninstall.sh` boots out the agents, then removes the Spoon, the data dir
(venv, agents, logs, LanguageTool), and the managed block (asks before deleting config); leaves
Hammerspoon/Homebrew/Java/Ollama alone.

## Privacy & safety

- Local-first at runtime: the engine has no required Python runtime deps. The default embedded
  provider makes no network calls; LanguageTool/Ollama talk to localhost services you opt into.
  Agent/Custom providers execute a CLI you configure and may use that CLI's cloud account or
  credentials. (The one-time *install* fetches the build backend + Homebrew casks.)
- Correctness is enforced in code (invariant + refuse-on-violation), not just prompts.

## Limitations (v1)

- **Plain text only** — works on whatever the selection yields; doesn't preserve rich styling.
- **Embedded Fix is conservative by design.** It runs a curated typo/contraction map, `i`→`I`,
  abbreviation-aware sentence capitalization, and whitespace/punctuation tidies — all zero-dep and
  deterministic. It does **not** collapse doubled words/numbers (that deleted legitimate content
  like `had had` / `5 5`). **Spell-correction is opt-in and OFF by default** (`embedded.spell`):
  the optional `nlp` extra adds **`pyspellchecker`**, but a dictionary-based checker will "correct"
  unrecognized-but-valid words (`webhook`→`rebook`, `rebase`→`debase`) which violates the
  no-meaning-change contract. When enabled, the gate is hardened — single-edit-distance only,
  the candidate must be a reasonably common word, plus the jargon allowlist and lowercase/ASCII/
  length filters — but it remains a heuristic, hence off by default.
  *Why not spaCy / HF+ONNX:* spaCy is analysis (no correction) and embeddings are representations
  (no generation); a neural seq2seq corrector is generative (meaning-drift, overlaps Improve),
  heavy (model download — offline/registry-hostile), and needs a warm daemon (breaks the
  per-keystroke subprocess model). Grammar lives in `languagetool`; neural rewrite in `ollama`.
- **Improve quality = the local model** you choose.
- **macOS-only trigger** (Hammerspoon); the engine itself is portable Python.

## Project layout

| Path | Role |
|---|---|
| `src/redraft/` | engine package: `protect`, `engine`, `config`, `base`, `prompt`, `cli`, `providers/`, `prompts/` (bundled `*-prompt.txt` templates) |
| `tests/` | pytest suite (no Hammerspoon needed) |
| `Redraft.spoon/init.lua` + `Redraft.spoon/lib/` | thin Hammerspoon trigger + menu-bar modules (calls `<venv>/bin/python3 -m redraft`) |
| `pyproject.toml` · `.pre-commit-config.yaml` · `_typos.toml` · `.python-version` | tooling |
| `install.sh` / `uninstall.sh` | installer / uninstaller |
| `README.md` | usage |
