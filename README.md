# Redraft

A tiny **macOS** tool that fixes or improves text **in any input field**. Select your text,
press a hotkey, and the selection is replaced in place with a cleaned-up version. Local-first,
no app integration — it works in Slack, Mail, browsers, editors, anywhere you can select text.
Built-in, LanguageTool, and Ollama providers stay on your machine; Agent/Custom providers are
explicit opt-ins and may send text to the CLI or cloud account you configure.

- **⌥⌘F — Fix only:** deterministic typo/grammar fixes. No tone change.
- **⌥⌘I — Improve writing:** clearer, professional, polite, friendly.

It's a thin [Hammerspoon](https://www.hammerspoon.org/) Spoon (trigger + menu-bar) backed by a
small local **Python engine** (`redraft`, installed into an isolated venv). A menu-bar icon (✦)
shows status and lets you start/stop and switch providers.

## Install

From a local checkout (the supported path today):

```bash
bash install.sh
```

> The hosted `curl … | bash` one-liner isn't live yet (the repo isn't published). Once it is,
> point `REDRAFT_GIT` at the repo (or edit the raw URL) and it works the same:
> `REDRAFT_GIT=https://github.com/<you>/redraft.git bash install.sh`, or
> `/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/<you>/redraft/HEAD/install.sh)"`.

The installer (idempotent — safe to re-run, cleanly replaces older/broken installs), with your
consent:
1. Installs **Homebrew**, **Hammerspoon**, and **uv** if missing.
2. Uses **uv** to create a venv at `~/.local/share/redraft/venv` with a **compatible Python**
   (uv downloads a managed 3.12/3.13 if your system Python is incompatible) and installs the
   **`redraft` engine** into it.
3. Drops the **Redraft Spoon** into `~/.hammerspoon/Spoons/` and adds one managed block to
   `~/.hammerspoon/init.lua` — your other config is preserved.
4. Runs an **interactive setup** — pick your **Fix** provider (Built-in / LanguageTool / Custom)
   and **Improve** provider (Ollama / Agent / Custom / Skip). For server-backed choices (LanguageTool,
   Ollama) it installs them and registers an **on-demand** local server (see below).

**Two manual steps after install:** open Hammerspoon → **Reload Config**, and grant it
**Accessibility** permission (System Settings → Privacy & Security → Accessibility) — one-time,
personal, not IT. Then select text → ⌥⌘F / ⌥⌘I.

## How it works

```
selection ─⌘C→ Spoon (Lua) ─→ <venv>/bin/python3 -m redraft --mode … ─→ {revised}  ─⌘V→ replaces it
```

The engine auto-protects high-signal technical spans — `` `code` ``, [markdown](links), URLs,
emails, `$ENV` vars, file paths (`./x`, `~/x`, `/a/b`), version strings (`v1.2.3`), `@mentions`,
and `#channels` — behind a token invariant; if a provider can't preserve them the change is
**refused** and your text is left untouched. The patterns are sigil-anchored so ordinary prose
(`and/or`, `12/25/2024`, `3.14`, a markdown `# Heading`) is never swept up; other plaintext
(`p95`, `POST /v1/foo`) isn't auto-protected — wrap it in backticks. No server/daemon — the engine
runs as a short-lived subprocess per keystroke.

## Providers (pick per mode, from the menu or config)

| Provider | Modes | Needs | Notes |
|---|---|---|---|
| `embedded` | Fix (default) | nothing | built-in, zero-setup: curated typo/contraction map, `i`→`I`, sentence caps, whitespace/punctuation tidies. Opt-in spelling via the `nlp` extra + `embedded.spell=true` (off by default — see note) |
| `languagetool` | Fix | a local LanguageTool server | broader deterministic grammar/spell |
| `ollama` | Improve | [Ollama](https://ollama.com) + a model | local LLM tone/clarity rewrite |
| `agent` | Improve | an authenticated agent CLI (Claude / Codex / Gemini / Copilot) | **external/cloud-capable opt-in**; auto-detected; pick one or `auto` (see below) |
| `command` | Fix or Improve | any CLI you configure | shell out to any locally-installed CLI; data flow depends on that command |

> **Opt-in spelling (off by default):** `embedded` ships a hand-curated typo map that's always on
> and safe. A broader dictionary spell-checker is available via the `nlp` extra + `embedded.spell=true`,
> but it's **off by default** because dictionary checkers "correct" unrecognized-but-valid words
> (e.g. `webhook`→`rebook`) — a meaning change Fix mode shouldn't make. Enable it only if you want
> wider coverage and accept that trade-off.

### Agent CLIs (Claude / Codex / Gemini / Copilot)

The `agent` provider hands the Improve rewrite to an AI CLI you already have — no command strings
to write. This is an **external/cloud-capable opt-in**: those CLIs usually require an account and may
send selected text to their provider. At install time Redraft detects which are present and lets you pick your preferred one
(default: the first detected), or `auto` (first available, in the order claude → codex → gemini →
copilot). Switch anytime from the menu: **Improve → Agent → ⟨tool⟩** (or **Auto**).

**Install one later and it just works:** the menu's **Improve → Agent → Rescan agents** (or
**Reload config**) re-detects through your login shell, so a newly-installed Gemini becomes
selectable without reinstalling Redraft. The binary is resolved live (PATH + common install dirs),
so it keeps working even though the engine runs with a minimal PATH.

Each tool's invocation lives in config as an **editable command template** — the installer seeds
`agent.commands` with sensible defaults, so when a CLI changes a flag you just edit the line (no
code change). `{bin}` is substituted with the resolved binary path. `{prompt_file}` is a temporary
mode-0600 file containing the full prompt and is used for CLIs that can read stdin; `{prompt_arg}`
is the explicit argv fallback for CLIs that require a prompt argument. `agent.bins.<tool>`
optionally pins a binary path.

```jsonc
"improveProvider": "agent",
"agent": {
  "tool": "auto",                 // or "claude" | "codex" | "gemini" | "copilot"
  "timeoutMs": 120000,
  "bins":     { "gemini": "/opt/homebrew/bin/gemini" },   // optional path hints
  "commands": {                   // seeded defaults — edit the flags freely ({bin} = the CLI path)
    "claude":  "{bin} -p < {prompt_file}",
    "codex":   "{bin} exec --skip-git-repo-check -s read-only - < {prompt_file}",
    "gemini":  "{bin} -p \"\" < {prompt_file}",
    "copilot": "{bin} -p {prompt_arg}"
  }
}
```

Must be **pre-authenticated** (run the CLI once in your terminal to log in), must be acceptable for
the selected text's data policy, and must preserve the `{{R:n}}` tokens. Agents are best for
**Improve**, not Fix (keep Fix on `embedded`/`languagetool`).

## Menu-bar

The ◆ (running) / ◇ (paused) icon menu:
- **Pause/Resume** the hotkeys, **Restart** (reloads config *and* rebinds hotkeys — use after
  changing a hotkey).
- **Fix:** / **Improve:** submenus — the title shows the active provider; pick another to switch.
  Improve shows `(not configured)` until you set it, and a `Turn off` once configured.
- **Improve style:** **Slack — friendly** (default) or **Email — formal** — the writing voice used
  for Improve, independent of which Improve provider you picked.
- **Fix before Improve** optionally runs the conservative built-in Fix pass before an Improve
  provider. It is off by default and is useful when you want agents/models to see cleaner input.
- **Server controls** appear only for a selected server-backed provider (LanguageTool / Ollama):
  **Start / Stop / Restart** with a live ● running / ○ stopped indicator.
- **Show last result…** reopens the most recent result in a copyable window (see below).
- **Edit config…**, **Reload config**, **Quit Redraft**.

During a slow **Improve** run the icon animates a spinner (⠋⠙⠹…) so you can see it's working, then
settles back to ◆. Clicking a **success notification** opens a small **copyable result window** — a
titled, bordered panel with per-section Copy buttons — showing the text that replaced your selection,
the change notes and any risk flags, and (for `agent`/`command`/`ollama` providers) the **agent's
raw response**, plus collapsible **Command** and **Prompt** sections (the resolved command display
and full prompt sent, `{{R:n}}` tokens and all). Clicking an **error notification** opens the full error text
the same way. Neither opens Hammerspoon's config.

**Pause vs Quit:** Pause just disables the hotkeys (the icon stays). **Quit Redraft** fully tears
it down — unbinds the hotkeys and removes the menu-bar icon (managed servers keep running). It does
*not* quit Hammerspoon; bring Redraft back with Hammerspoon's **Reload Config**.

### Local servers (LanguageTool / Ollama)

When you pick LanguageTool or Ollama, the installer registers an **on-demand launchd agent** under
`~/.local/share/redraft/launchd/` — deliberately **not** in `~/Library/LaunchAgents`, so nothing
auto-starts at login. You start it when you want it (installer prompt, or the menu's Start), it
restarts on crash while running, and stays down across reboots until you start it again. For
LanguageTool the installer downloads the official server (~200MB) and **honors your existing Java**
(mise / asdf / jenv / sdkman / system, Java 17+); only if none is found does it offer
`brew install openjdk@17`. Let Redraft manage these servers — don't also run
`brew services start ollama`, or two managers will fight over the port.

#### Choosing an Ollama model

Improve is a short-text rewrite (tone/grammar/clarity on a selection), so a small instruct model
is plenty — no need for an 8B. Ollama loads the model **on demand** and unloads it after idle
(`keep_alive`, default 5 min), so it only occupies memory during the few seconds of a rewrite, not
while you work. On Apple Silicon it runs on the GPU/Metal, so it won't fight your IDEs for CPU. Set
the model at the installer's "Ollama model" prompt or via `ollama.model` in the config. The default
is `llama3.2:3b` (already 4-bit `q4_K_M`).

| Model | ~Q4 RAM | Notes |
|---|---|---|
| `llama3.2:3b` | ~2–3.5 GB | **Recommended default.** Best-balanced, most-tested small model; good at following rewrite/tone instructions. |
| `qwen2.5:3b` | ~2–3.5 GB | Strong alternative — often edges out Llama 3.2 3B on instruction-following at the same footprint. Worth A/B-ing on your actual prompts. |
| `gemma3:4b` | ~3–4 GB | Slightly bigger but notably good at text cleanup/rewriting; pick this if 3B output quality disappoints. |
| `qwen2.5:1.5b` / `llama3.2:1b` | ~1–1.5 GB | Fallback if 16 GB feels cramped. Noticeably weaker phrasing, but fine for grammar/light tidy-ups. |

## Configure

`~/.config/redraft/config.json` (read by both the engine and the Spoon):

```jsonc
{
  "hotkeys": { "fix": {"mods":["cmd","alt"],"key":"F"}, "improve": {"mods":["cmd","alt"],"key":"I"} },
  "fixProvider": "embedded",
  "improveProvider": "ollama",        // or "agent", "command", or "none"
  "improve": { "preFix": false },      // optional embedded Fix pass before Improve
  "ollama": { "url": "http://localhost:11434", "model": "llama3.2:3b" },
  "command": { "cmd": "ollama run llama3.2:3b", "timeoutMs": 60000 },
  "languagetool": { "url": "http://localhost:8081", "language": "en-US" }
}
```

Edit it (then **Reload config** from the menu), or flip providers from the menu directly.

Using `command` for **both** Fix and Improve? Give each its own CLI with `command.fixCmd` /
`command.improveCmd` — they override the shared `command.cmd`:

```jsonc
"command": { "fixCmd": "my-linter", "improveCmd": "ollama run llama3.2:3b", "timeoutMs": 60000 }
```

### Per-app provider profiles

Want a different provider in some apps — e.g. the local-only built-in Fix in Slack, but
LanguageTool in your editor? Add a `profiles` map keyed by the app's **bundle id**. A profile may
set `fixProvider` and/or `improveProvider`; anything it leaves out falls back to the top-level
provider. The Spoon passes the frontmost app automatically.

```jsonc
"profiles": {
  "com.tinyspeck.slackmacgap": { "fixProvider": "embedded" },          // built-in only in Slack
  "com.microsoft.VSCode":      { "fixProvider": "languagetool" }       // grammar in the editor
}
```

Find a bundle id with `osascript -e 'id of app "Slack"'`. Edit profiles in config.json (menu →
**Edit config…** → **Reload config**); there's no menu editor — the frontmost app while the menu is
open is Hammerspoon, not the app you were typing in.

### Tuning the prompts

The instructions sent to the LLM providers (`ollama`/`agent`/`command`) are **editable templates**.
The installer drops them in `~/.config/redraft/`:

- `fix-prompt.txt` — Fix mode.
- `friendly-prompt.txt` — Improve, **Slack — friendly** style (default).
- `formal-prompt.txt` — Improve, **Email — formal** style.

`improveStyle` (config or the **Improve style** menu) picks `friendly`/`formal`. Edit a file and it
takes effect on the next run — no reload needed. Each template must keep the `{{R:n}}` token rule
and the `Respond ONLY as JSON …` line (the model's output is parsed as JSON, and the token invariant
rejects anything that drops a protected span). The message is spliced in wherever you put
`<message>`. Delete a file to fall back to the built-in default (bundled with the engine).

### Notifications

Redraft posts status/success/errors to Notification Center. Silence any category via
`config.notifications` (all default `true`):

```jsonc
"notifications": { "fix": false, "improve": true, "status": true, "error": true }
```

- `fix` / `improve` — the success toast per mode (the result is still stashed; reopen it with the
  menu's **Show last result…**).
- `status` — pause/resume, provider switch, reload, server start/stop, etc.
- `error` — failures (keep this on unless you have a reason not to).

## Develop

Standard [uv](https://docs.astral.sh/uv/) project:

```bash
uv sync                     # .venv + dev/test groups + editable install of redraft
uv run pytest               # tests
uv run pre-commit run -a    # validate-pyproject, typos, ruff check+format, hooks
uv run tox                  # 3.12 / 3.13 matrix
# try the engine directly:
echo 'i think teh `api` is definately down' | .venv/bin/redraft --mode fix --input /dev/stdin
```

Engine source is `src/redraft/` (stdlib-only at runtime); tests in `tests/`.

## Troubleshooting

Redraft posts status, success, and errors to **macOS Notification Center** (title "Redraft"); each
new notification replaces the previous one. Here's what each message means.

| Alert | Fix |
|---|---|
| Hotkey does nothing at all | Grant **Accessibility** to Hammerspoon (System Settings → Privacy & Security → Accessibility). After a Hammerspoon update, toggle it off/on — or remove and re-add it — to refresh the permission. |
| No status/error notifications | Redraft reports everything via **Notification Center**. Allow **Hammerspoon** in System Settings → Notifications. |
| `engine not installed — run install.sh` | The venv is missing/moved; re-run the installer. |
| `nothing selected` / `empty selection` | Select text first. A few apps block synthetic ⌘C — try clicking into the field again. |
| `<mode> provider not configured` | Pick a provider in the menu (**Fix:** / **Improve:**). |
| `cannot reach LanguageTool` / `cannot reach Ollama` | Start the server from the menu (server submenu → **Start**), or check it's installed. |
| `engine error — …` | The provider failed; the reason is in the notification itself (the engine runs per-keystroke and doesn't log). If it names a server, try **Restart** from the menu and check the server logs below. |
| `focus changed — skipped` | You switched apps, windows, or focused fields while a slow Improve was running, so Redraft declined to paste into the wrong place. Your text is untouched — re-run it. |
| Changed a hotkey but it didn't take effect | Use **Restart** in the menu (plain *Reload config* doesn't rebind hotkeys). |
| Wrong text pasted / styling lost | Redraft works on plain text; rich formatting is whatever the target app re-applies. |

Server logs (LanguageTool/Ollama) live at `~/.local/share/redraft/logs/`. The active config is at
`~/.config/redraft/config.json` (menu → **Edit config…**).

## Reinstall / uninstall

- **Reinstall / upgrade:** re-run the install one-liner — it cleanly replaces the venv-installed
  engine, the Spoon, and the managed `init.lua` block, including older layouts. If a config already
  exists it first asks **"Reuse your last setup?"** (Enter = yes), which covers **all** prior
  choices — it restores enhanced spelling if it was on and re-runs setup for any server-backed
  provider (prompting to start LanguageTool/Ollama); answer `n` to re-pick. Either way your config
  is **merged** (provider keys updated, everything else preserved). A legacy
  `~/.hammerspoon/apps/redraft.lua`, if found, is moved to a timestamped backup instead of deleted.
- **Uninstall:** `bash uninstall.sh` — stops the managed servers, then removes the Spoon, the data
  dir (venv, agents, logs, LanguageTool download), and the managed block; asks before deleting your
  config. It also **offers to remove the Homebrew deps the installer actually installed** (recorded
  in `install-manifest.tsv`) — each behind a `[y/N]` prompt, with Homebrew itself offered last and
  only with a warning. Anything you already had is left untouched.

## Requirements & notes

- macOS + Hammerspoon + uv (installer handles them). **uv provisions a compatible Python
  (3.12/3.13) automatically** — your system Python can be anything (e.g. 3.14). The engine has
  **no required Python runtime dependencies**; default/local providers do not call the network at
  runtime, while Agent/Custom follow the CLI you opt into. Install-time network is uv (Python +
  wheel build) + Homebrew casks.
- Accessibility permission for Hammerspoon (to copy/paste the selection).
- Works on **plain text** (whatever the selection yields); it doesn't preserve rich styling
  beyond what the target app re-interprets. Improve quality depends on the local model.

### Customizing dependency installs

Every auto-install command is **replaceable** — Redraft never hardcodes a vendor. At each
interactive prompt you can press **Enter** to run the default, **type a replacement command**, or
**`n`** to skip. For unattended (`curl | bash`) installs, set the matching env var instead:

| Dependency | Default | Override env var |
|---|---|---|
| Homebrew | official bootstrap | `REDRAFT_BREW_INSTALL` |
| Hammerspoon | `brew install --cask hammerspoon` | `REDRAFT_HAMMERSPOON_INSTALL` |
| uv | `brew install uv` | `REDRAFT_UV_INSTALL` |
| git | `brew install git` | `REDRAFT_GIT_INSTALL` |
| JDK (for LanguageTool) | `brew install openjdk@17` | `REDRAFT_JAVA_INSTALL` |
| Ollama | `brew install ollama` | `REDRAFT_OLLAMA_INSTALL` |

Example — use **Temurin** instead of openjdk: type `brew install --cask temurin` at the JDK prompt,
or `REDRAFT_JAVA_INSTALL="brew install --cask temurin" bash install.sh`. Redraft then auto-detects
**any** JDK 17+ (via mise/asdf/jenv/sdkman or `/usr/libexec/java_home`) — **including versions you've
installed but not activated** — so the vendor doesn't matter and you rarely need this at all.

Design rationale: [DESIGN.md](DESIGN.md).
