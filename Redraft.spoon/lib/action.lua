return function(obj, ctx)
  local clipboard = ctx.clipboard
  local focus = ctx.focus
  local ui = ctx.ui

  local function decodeJson(s)
    if not s or #s == 0 then return nil end
    local a = s:find("{", 1, true)
    if not a then return nil end
    local b
    for i = #s, a, -1 do
      if s:sub(i, i) == "}" then
        b = i
        break
      end
    end
    if not b then return nil end
    local ok, data = pcall(hs.json.decode, s:sub(a, b))
    if ok and type(data) == "table" then return data end
    return nil
  end

  function obj:redraft(mode)
    if not self.enabled then return end
    if not hs.fs.attributes(ctx.VENV_PY) then
      return ui.notify("Redraft: engine not installed — run install.sh", "error")
    end
    local saved = clipboard.snapshot()
    local before = hs.pasteboard.changeCount()
    local frontApp = hs.application.frontmostApplication()
    local focusSnapshot = focus.snapshot(frontApp)
    hs.eventtap.keyStroke({ "cmd" }, "c", 0)

    hs.timer.doAfter(ctx.SETTLE, function()
      if hs.pasteboard.changeCount() == before then return ui.notify("Redraft: nothing selected", "error") end
      local text = hs.pasteboard.getContents()
      if not text or text == "" then
        clipboard.restore(saved)
        return ui.notify("Redraft: empty selection", "error")
      end

      clipboard.setTextQuiet("")
      clipboard.ensurePrivateTmpDir()
      local infile = ctx.TMP_DIR .. "/sel-" .. hs.host.uuid()
      local fh = io.open(infile, "w")
      if not fh then
        clipboard.restore(saved)
        return ui.notify("Redraft: temp file error", "error")
      end
      clipboard.chmod("600", infile)
      fh:write(text)
      fh:close()

      local bundle = frontApp and frontApp:bundleID()
      local engineArgs = { "-m", "redraft", "--mode", mode, "--input", infile }
      if bundle and bundle ~= "" then
        engineArgs[#engineArgs + 1] = "--app"
        engineArgs[#engineArgs + 1] = bundle
      end

      self._tasks = self._tasks or {}
      local task
      task = hs.task.new(ctx.VENV_PY, function(code, stdout, stderr)
        self._tasks[task] = nil
        self:stopSpinner()
        os.remove(infile)
        local data = decodeJson(stdout)
        if type(data) ~= "table" then
          clipboard.restore(saved)
          local full = (stderr and #stderr > 0) and stderr or ("no output, exit " .. tostring(code))
          return ui.notify("Redraft: engine error — " .. full:sub(1, 160), "error", full)
        end
        if data.error or type(data.revised) ~= "string" then
          clipboard.restore(saved)
          local full = tostring(data.error or "no result")
          return ui.notify("Redraft: " .. full:sub(1, 160), "error", full)
        end
        if not focus.stillCurrent(focusSnapshot) then
          clipboard.restore(saved)
          return ui.notify("Redraft: focus changed — skipped (your text is unchanged)", "error")
        end

        self._lastResult = {
          revised = data.revised,
          change_notes = data.change_notes,
          risk_flags = data.risk_flags,
          mode = mode,
          provider = data.provider,
          command = data.command,
          prompt = data.prompt,
          raw = data.raw,
        }
        clipboard.setTextQuiet(data.revised)
        hs.eventtap.keyStroke({ "cmd" }, "v", 0)
        hs.timer.doAfter(ctx.SETTLE, function()
          clipboard.restore(saved)
          ui.notifyResult(data, mode)
        end)
      end, engineArgs)

      if not task then
        os.remove(infile)
        clipboard.restore(saved)
        return ui.notify("Redraft: could not create task", "error")
      end
      self._tasks[task] = true
      if mode == "improve" then self:startSpinner() end
      if not task:start() then
        self._tasks[task] = nil
        self:stopSpinner()
        os.remove(infile)
        clipboard.restore(saved)
        ui.notify("Redraft: could not launch engine — check " .. ctx.VENV_PY, "error")
      end
    end)
  end
end
