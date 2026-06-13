--- === Redraft ===
---
--- Generic macOS text fixer. Select text in any input field, press a hotkey, and the selection
--- is replaced in place with a cleaned-up version. Local-first; Agent/Custom providers follow the
--- external CLI you opt into.
---
---   ⌥⌘F = Fix only      ⌥⌘I = Improve writing
---
--- This Spoon is a thin trigger + menu-bar. All rewrite logic lives in the `redraft` Python engine,
--- installed into a dedicated venv by install.sh and called as a subprocess. Provider selection and
--- settings live in ~/.config/redraft/config.json (shared with the engine).

local obj = {}
obj.__index = obj

obj.name = "Redraft"
obj.version = "1.0.0"
obj.author = "Redraft"
obj.license = "MIT"

local HOME = os.getenv("HOME")
local ctx = {
  HOME = HOME,
  CONFIG_PATH = HOME .. "/.config/redraft/config.json",
  VENV_PY = HOME .. "/.local/share/redraft/venv/bin/python3",
  DATA_DIR = HOME .. "/.local/share/redraft",
  LAUNCHD_DIR = HOME .. "/.local/share/redraft/launchd",
  TMP_DIR = HOME .. "/.local/share/redraft/tmp",
  SETTLE = 0.15,

  LABELS = {
    embedded = "Built-in (instant)",
    languagetool = "LanguageTool (grammar)",
    ollama = "Ollama (local AI)",
    agent = "Agent CLI (external)",
    command = "Custom command…",
    none = "Off",
  },

  AGENT_TOOLS = { "claude", "codex", "gemini", "copilot" },
  STYLES = { "friendly", "formal" },
  STYLE_LABELS = { friendly = "Slack — friendly", formal = "Email — formal" },

  SERVICES = {
    languagetool = { label = "com.redraft.languagetool", name = "LanguageTool server" },
    ollama = { label = "com.redraft.ollama", name = "Ollama server" },
  },

  author = obj.author,
  license = obj.license,
}

local function spoonRoot()
  local src = debug.getinfo(1, "S").source
  local file = src:sub(1, 1) == "@" and src:sub(2) or ""
  return file:match("^(.*[/\\])") or ""
end

local ROOT = spoonRoot()
local function loadLib(name)
  local rel = "lib/" .. name .. ".lua"
  local path
  if hs and hs.spoons and hs.spoons.resourcePath then
    local ok, resource = pcall(hs.spoons.resourcePath, rel)
    if ok and resource then path = resource end
  end
  return dofile(path or (ROOT .. rel))
end

ctx.clipboard = loadLib("clipboard")(ctx)
ctx.focus = loadLib("focus")(ctx)
ctx.ui = loadLib("ui")(obj, ctx)
loadLib("config")(obj, ctx)
ctx.service = loadLib("services")(obj, ctx)
loadLib("action")(obj, ctx)
loadLib("menu")(obj, ctx)

return obj
