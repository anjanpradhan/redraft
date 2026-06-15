return function(obj, ctx)
  local M = {}
  local _notif = { fix = true, improve = true, status = true, error = true }
  local _lastNotif

  function M.setNotifications(config)
    local n = (type(config) == "table") and config or {}
    for _, cat in ipairs({ "fix", "improve", "status", "error" }) do
      _notif[cat] = (n[cat] ~= false)
    end
  end

  local function send(fields, cat, onClick)
    if cat and _notif[cat] == false then return end
    if _lastNotif then pcall(function()
      _lastNotif:withdraw()
    end) end
    fields.title = "Redraft"
    fields.withdrawAfter = 0
    _lastNotif = hs.notify.new(function(n)
      if onClick and n:activationType() == hs.notify.activationTypes.contentsClicked then onClick() end
    end, fields)
    _lastNotif:send()
  end

  function M.notify(msg, cat, detail)
    cat = cat or "status"
    local text = (tostring(msg):gsub("^Redraft:?%s*", ""))
    local onClick
    if cat == "error" then
      obj._lastError = detail or text
      onClick = function()
        obj:showText("Redraft — Error", obj._lastError)
      end
    end
    send({ informativeText = text }, cat, onClick)
  end

  function M.notifyResult(data, mode)
    local outcome = (mode == "improve") and "Improved" or "Fixed"
    local subtitle = outcome .. (data.provider and (" · " .. data.provider) or "")
    local notes = (type(data.change_notes) == "table") and data.change_notes or {}
    local flags = (type(data.risk_flags) == "table") and data.risk_flags or {}
    local body

    if #notes == 0 then
      body = "no changes needed"
    else
      local shown = {}
      for i = 1, math.min(3, #notes) do
        shown[i] = tostring(notes[i])
      end
      body = #notes .. ((#notes == 1) and " change: " or " changes: ") .. table.concat(shown, "; ")
      if #notes > 3 then body = body .. " …" end
    end
    if #flags > 0 then body = "⚠ " .. table.concat(flags, "; ") .. "  ·  " .. body end

    send({ subTitle = subtitle, informativeText = body }, mode, function()
      obj:showResult()
    end)
  end

  local function htmlEscape(s)
    return (
      tostring(s or ""):gsub("&", "&amp;"):gsub("<", "&lt;"):gsub(">", "&gt;"):gsub('"', "&quot;"):gsub("'", "&#39;")
    )
  end

  local function listHtml(items)
    if type(items) ~= "table" or #items == 0 then return "" end
    local out = {}
    for _, it in ipairs(items) do
      out[#out + 1] = "<li>" .. htmlEscape(it) .. "</li>"
    end
    return "<ul>" .. table.concat(out) .. "</ul>"
  end

  local function copyBtn(id)
    return '<button class="copy" onclick="window.webkit.messageHandlers.redraft.postMessage('
      .. "document.getElementById('"
      .. id
      .. "').value);this.textContent='Copied ✓';\">Copy</button>"
  end

  local function field(label, id, text, cls, collapsed)
    local hdr = '<div class="fhdr"><span class="lbl">' .. label .. "</span>" .. copyBtn(id) .. "</div>"
    local ta = '<textarea id="'
      .. id
      .. '" readonly class="'
      .. (cls or "small")
      .. '">'
      .. htmlEscape(text)
      .. "</textarea>"
    if collapsed then return "<details><summary>" .. label .. "</summary>" .. hdr .. ta .. "</details>" end
    return '<div class="field">' .. hdr .. ta .. "</div>"
  end

  local MODAL_STYLE = [[<style>
    :root {
      color-scheme: light dark;
      --bg:#fff; --fg:#1d1d1f; --muted:#86868b; --line:#e4e4e7; --field:#f5f5f7; --accent:#0a84ff; --warn:#c0392b;
    }
    @media (prefers-color-scheme: dark) {
      :root { --bg:#1e1e20; --fg:#e8e8ea; --muted:#9a9aa0; --line:#3a3a3d; --field:#2a2a2c; }
    }
    html { box-sizing: border-box; min-height: 100vh; border: 1px solid #8888; }
    *, *::before, *::after { box-sizing: inherit; }
    body { margin: 0; background: var(--bg); color: var(--fg);
           font: 13px/1.5 -apple-system, system-ui, "Segoe UI", sans-serif; }
    header { position: sticky; top: 0; z-index: 1; display: flex; align-items: center; gap: 8px;
             padding: 12px 16px; background: var(--bg); border-bottom: 1px solid var(--line); }
    .badge { font-size: 11px; font-weight: 700; color: #fff; background: var(--accent);
             padding: 2px 9px; border-radius: 999px; letter-spacing: .02em; }
    .badge.err { background: var(--warn); }
    .title { font-weight: 600; } .prov { color: var(--muted); margin-left: auto; font-size: 12px; }
    .field { margin: 14px 16px; } .fhdr { display: flex; align-items: center; margin-bottom: 6px; }
    .lbl { font-size: 11px; font-weight: 700; letter-spacing: .04em; text-transform: uppercase; color: var(--muted); }
    .copy { margin-left: auto; font: 11px system-ui; padding: 3px 11px; cursor: pointer;
            color: var(--fg); background: var(--field); border: 1px solid var(--line); border-radius: 6px; }
    .copy:hover { border-color: var(--accent); color: var(--accent); }
    textarea { width: 100%; background: var(--field); color: var(--fg); border: 1px solid var(--line);
               border-radius: 8px; padding: 9px 11px; resize: vertical;
               font: 12px/1.45 ui-monospace, SFMono-Regular, Menlo, monospace; }
    textarea.main { height: 150px; } textarea.small { height: 74px; }
    .warn { color: var(--warn); font-weight: 600; margin: 12px 16px; }
    ul { margin: 6px 0; padding-left: 20px; } li { margin: 3px 0; } .muted { color: var(--muted); }
    details { margin: 10px 16px; border: 1px solid var(--line); border-radius: 8px; padding: 8px 12px; }
    details > summary { cursor: pointer; font-size: 11px; font-weight: 700; letter-spacing: .04em;
                        text-transform: uppercase; color: var(--muted); list-style-position: inside; }
    details[open] > summary { margin-bottom: 8px; }
  </style>]]

  function obj:_openModal(title, bodyHtml)
    if self._resultView then
      pcall(function()
        self._resultView:delete()
      end)
      self._resultView = nil
    end
    local html = '<!DOCTYPE html><html><head><meta charset="utf-8">'
      .. MODAL_STYLE
      .. "</head><body>"
      .. bodyHtml
      .. "</body></html>"
    local sf = hs.screen.mainScreen():frame()
    local w, h = 540, 380
    local rect = { x = sf.x + (sf.w - w) / 2, y = sf.y + (sf.h - h) / 3, w = w, h = h }
    local ucc
    pcall(function()
      ucc = hs.webview.usercontent.new("redraft")
      ucc:setCallback(function(m)
        if m and m.body then hs.pasteboard.setContents(tostring(m.body)) end
      end)
    end)
    self._resultView = (ucc and hs.webview.new(rect, {}, ucc) or hs.webview.new(rect))
      :windowStyle({ "titled", "closable", "resizable" })
      :windowTitle(title)
      :closeOnEscape(true)
      :deleteOnClose(true)
      :shadow(true)
      :allowTextEntry(true)
      :level(hs.drawing.windowLevels.modalPanel)
      :html(html)
    self._resultView:show():bringToFront(true)
    hs.timer.doAfter(0.05, function()
      local win = self._resultView and self._resultView:hswindow()
      if win then win:focus() end
    end)
  end

  function obj:showResult()
    local r = self._lastResult
    if not r then return M.notify("Redraft: no result yet", "status") end
    local outcome = (r.mode == "improve") and "Improved" or "Fixed"
    local p = {
      ('<header><span class="badge">%s</span><span class="title">Redraft</span><span class="prov">%s</span></header>'):format(
        htmlEscape(outcome),
        htmlEscape(r.provider or "?")
      ),
    }
    p[#p + 1] = field("Replaced with", "out", r.revised, "main")
    if type(r.risk_flags) == "table" and #r.risk_flags > 0 then
      p[#p + 1] = '<p class="warn">⚠ ' .. htmlEscape(table.concat(r.risk_flags, "; ")) .. "</p>"
    end
    if type(r.change_notes) == "table" and #r.change_notes > 0 then
      p[#p + 1] = '<div class="field"><div class="fhdr"><span class="lbl">Changes</span></div>'
        .. listHtml(r.change_notes)
        .. "</div>"
    end
    if r.raw and r.raw ~= "" then p[#p + 1] = field("Agent response", "raw", r.raw, "small") end
    if r.command then p[#p + 1] = field("Command", "cmd", r.command, "small", true) end
    if r.prompt then p[#p + 1] = field("Prompt sent", "prompt", r.prompt, "small", true) end
    self:_openModal("Redraft — " .. outcome, table.concat(p))
  end

  function obj:showText(title, text)
    local header = '<header><span class="badge err">Error</span><span class="title">Redraft</span></header>'
    self:_openModal(title, header .. field("Details", "t", text, "main"))
  end

  function obj:showAbout()
    local body = (
      '<header><span class="badge">About</span><span class="title">Redraft</span>'
      .. '<span class="prov">v%s</span></header>'
    ):format(htmlEscape(obj.version)) .. '<div class="field">' .. "<p>Fix or improve selected text in any macOS input field — local-first. Select text, press " .. "a hotkey, and the selection is replaced in place.</p>" .. '<p class="h">Hotkeys</p><p>⌥⌘F — Fix only  ·  ⌥⌘I — Improve writing</p>' .. ('<p class="muted">Thin Hammerspoon Spoon + local Python engine · %s · %s license</p>'):format(
      htmlEscape(ctx.author or obj.author),
      htmlEscape(ctx.license or obj.license)
    ) .. "</div>"
    self:_openModal("About Redraft", body)
  end

  return M
end
