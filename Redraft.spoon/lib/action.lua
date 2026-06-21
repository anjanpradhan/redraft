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

  function obj:cancelActiveRedraft()
    local run = self._activeRun
    if not run then return end
    self._activeRun = nil
    if run.task then
      if self._tasks then self._tasks[run.task] = nil end
      pcall(function()
        local ok, running = pcall(function()
          return run.task:isRunning()
        end)
        if (not ok) or running then run.task:terminate() end
      end)
    end
    if run.infile then
      os.remove(run.infile)
      run.infile = nil
    end
    if run.saved then clipboard.restore(run.saved) end
    self:stopSpinner()
  end

  function obj:redraft(mode)
    if not self.enabled then return end
    if self._activeRun then return ui.notify("Redraft: already working", "status") end
    if not hs.fs.attributes(ctx.VENV_PY) then
      return ui.notify("Redraft: engine not installed — run install.sh", "error")
    end
    local run = {}
    self._activeRun = run
    local function current()
      return self._activeRun == run
    end
    local function clearRun()
      if current() then self._activeRun = nil end
    end
    local function cleanupFile()
      if run.infile then
        os.remove(run.infile)
        run.infile = nil
      end
    end
    local function fail(message, detail)
      cleanupFile()
      clipboard.restore(run.saved)
      clearRun()
      return ui.notify(message, "error", detail)
    end
    local saved = clipboard.snapshot()
    run.saved = saved
    local before = hs.pasteboard.changeCount()
    local frontApp = hs.application.frontmostApplication()
    local focusSnapshot = focus.snapshot(frontApp)
    hs.eventtap.keyStroke({ "cmd" }, "c", 0)

    hs.timer.doAfter(ctx.SETTLE, function()
      if not current() or not self.enabled then return end
      if hs.pasteboard.changeCount() == before then
        clearRun()
        return ui.notify("Redraft: nothing selected", "error")
      end
      local text = hs.pasteboard.getContents()
      if not text or text == "" then return fail("Redraft: empty selection") end

      clipboard.setTextQuiet("")
      clipboard.ensurePrivateTmpDir()
      local infile = ctx.TMP_DIR .. "/sel-" .. hs.host.uuid()
      run.infile = infile
      local fh = io.open(infile, "w")
      if not fh then return fail("Redraft: temp file error") end
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
        if not current() then
          cleanupFile()
          return
        end
        self:stopSpinner()
        cleanupFile()
        local data = decodeJson(stdout)
        if type(data) ~= "table" then
          local full = (stderr and #stderr > 0) and stderr or ("no output, exit " .. tostring(code))
          return fail("Redraft: engine error — " .. full:sub(1, 160), full)
        end
        if data.error or type(data.revised) ~= "string" then
          local full = tostring(data.error or "no result")
          return fail("Redraft: " .. full:sub(1, 160), full)
        end
        if not focus.stillCurrent(focusSnapshot) then
          return fail("Redraft: focus changed — skipped (your text is unchanged)")
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
          if not current() then return end
          clipboard.restore(saved)
          clearRun()
          ui.notifyResult(data, mode)
        end)
      end, engineArgs)

      if not task then return fail("Redraft: could not create task") end
      run.task = task
      self._tasks[task] = true
      if mode == "improve" then self:startSpinner() end
      if not task:start() then
        self._tasks[task] = nil
        run.task = nil
        self:stopSpinner()
        fail("Redraft: could not launch engine — check " .. ctx.VENV_PY)
      end
    end)
  end
end
