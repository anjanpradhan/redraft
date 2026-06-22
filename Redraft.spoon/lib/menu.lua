return function(obj, ctx)
  local notify = function(...)
    return ctx.ui.notify(...)
  end

  function obj:bindHotkeys()
    self:unbindHotkeys()
    local hk = self.config.hotkeys
    self._hotkeys = {
      hs.hotkey.bind(hk.fix.mods, hk.fix.key, function()
        self:redraft("fix")
      end),
      hs.hotkey.bind(hk.improve.mods, hk.improve.key, function()
        self:redraft("improve")
      end),
    }
  end

  function obj:unbindHotkeys()
    for _, h in ipairs(self._hotkeys or {}) do
      h:delete()
    end
    self._hotkeys = nil
  end

  local SPINNER_FRAMES = { "⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏" }

  function obj:startSpinner()
    if not self.menubar or self._spinnerTimer then return end
    local i = 0
    self._spinnerTimer = hs.timer.new(0.1, function()
      i = (i % #SPINNER_FRAMES) + 1
      if self.menubar then self.menubar:setTitle(SPINNER_FRAMES[i]) end
    end)
    self._spinnerTimer:start()
  end

  function obj:stopSpinner()
    if self._spinnerTimer then
      self._spinnerTimer:stop()
      self._spinnerTimer = nil
      self:refreshMenu()
    end
  end

  function obj:menu()
    local c = self.config
    local function prov(kind, name)
      return {
        title = ctx.LABELS[name] or name,
        checked = (c[kind .. "Provider"] == name),
        fn = function()
          self:setProvider(kind, name)
        end,
      }
    end

    local agents = self._agents or {}
    local agentTool = (c.agent and c.agent.tool) or "auto"
    local agentItems = {
      {
        title = "Auto (first installed)",
        checked = (c.improveProvider == "agent" and agentTool == "auto"),
        fn = function()
          self:setAgent("auto")
        end,
      },
      { title = "-" },
    }
    for _, t in ipairs(ctx.AGENT_TOOLS) do
      local found = agents[t]
      agentItems[#agentItems + 1] = {
        title = (t:gsub("^%l", string.upper)) .. (found and "" or "  — not found"),
        checked = (c.improveProvider == "agent" and agentTool == t),
        disabled = not found,
        fn = function()
          self:setAgent(t)
        end,
      }
    end
    agentItems[#agentItems + 1] = { title = "-" }
    agentItems[#agentItems + 1] = {
      title = "Rescan agents",
      fn = function()
        self:detectAgents()
        self:refreshMenu()
        notify("Redraft: rescanned agents")
      end,
    }

    local improveOff = (c.improveProvider == nil or c.improveProvider == "none")
    local improveItems = {}
    if improveOff then improveItems[#improveItems + 1] = { title = "(not configured)", disabled = true } end
    improveItems[#improveItems + 1] = prov("improve", "ollama")
    improveItems[#improveItems + 1] = {
      title = "Agent CLI (external: Claude/Codex/Gemini/Copilot)",
      checked = (c.improveProvider == "agent"),
      menu = agentItems,
    }
    improveItems[#improveItems + 1] = prov("improve", "command")
    if not improveOff then
      improveItems[#improveItems + 1] = { title = "-" }
      improveItems[#improveItems + 1] = {
        title = "Turn off",
        fn = function()
          self:setProvider("improve", "none")
        end,
      }
    end

    local improveLabel
    if c.improveProvider == "agent" then
      if agentTool == "auto" then
        local a = self:autoAgent()
        improveLabel = "Agent CLI (external auto" .. (a and (" → " .. a) or "") .. ")"
      else
        improveLabel = "Agent CLI (external " .. agentTool .. ")"
      end
    else
      improveLabel = ctx.LABELS[c.improveProvider] or "Off"
    end

    local items = {
      { title = (self.enabled and "◆  Redraft — running" or "◇  Redraft — paused"), disabled = true },
      { title = "-" },
      {
        title = self.enabled and "Pause Redraft" or "Resume Redraft",
        fn = function()
          if self.enabled then
            self:stop()
          else
            self:start()
          end
        end,
      },
      {
        title = "Restart",
        fn = function()
          self:restart()
        end,
      },
      { title = "-" },
      {
        title = "Fix:  " .. (ctx.LABELS[c.fixProvider] or c.fixProvider),
        menu = {
          prov("fix", "embedded"),
          prov("fix", "languagetool"),
          prov("fix", "command"),
        },
      },
      { title = "Improve:  " .. improveLabel, menu = improveItems },
    }

    local curStyle = c.improveStyle or "friendly"
    local styleItems = {}
    for _, s in ipairs(ctx.STYLES) do
      styleItems[#styleItems + 1] = {
        title = ctx.STYLE_LABELS[s],
        checked = (curStyle == s),
        fn = function()
          self:setImproveStyle(s)
        end,
      }
    end
    items[#items + 1] = { title = "Improve style:  " .. (ctx.STYLE_LABELS[curStyle] or curStyle), menu = styleItems }

    local server = {}
    local function serverItem(kind, provider)
      if c[kind .. "Provider"] ~= provider or not ctx.service.plist(provider) then return end
      local svc = ctx.SERVICES[provider]
      local starting = (self._svcStarting or {})[provider]
      local up = ctx.service.running(provider)
      local status = starting and "◐ starting…" or (up and "● running" or "○ stopped")
      server[#server + 1] = {
        title = svc.name .. ":  " .. status,
        menu = {
          {
            title = "Start",
            disabled = starting or up,
            fn = function()
              self:serviceControl(provider, "start")
            end,
          },
          {
            title = "Stop",
            disabled = not (starting or up),
            fn = function()
              self:serviceControl(provider, "stop")
            end,
          },
          {
            title = "Restart",
            disabled = starting,
            fn = function()
              self:serviceControl(provider, "restart")
            end,
          },
        },
      }
    end
    serverItem("fix", "languagetool")
    serverItem("improve", "ollama")
    if #server > 0 then
      items[#items + 1] = { title = "-" }
      for _, it in ipairs(server) do
        items[#items + 1] = it
      end
    end

    local tail = {
      { title = "-" },
      {
        title = "Show last result…",
        disabled = (self._lastResult == nil),
        fn = function()
          self:showResult()
        end,
      },
      {
        title = "Edit config…",
        fn = function()
          hs.execute("open '" .. ctx.CONFIG_PATH .. "'")
        end,
      },
      {
        title = "Reload config",
        fn = function()
          self:loadConfig()
          self:refreshMenu()
          notify("Redraft: config reloaded")
        end,
      },
      {
        title = "About Redraft",
        fn = function()
          self:showAbout()
        end,
      },
      { title = "-" },
      {
        title = "Quit Redraft",
        fn = function()
          self:quit()
        end,
      },
      { title = "-" },
      { title = "⌨  ⌥⌘F Fix  ·  ⌥⌘I Improve", disabled = true },
    }
    for _, it in ipairs(tail) do
      items[#items + 1] = it
    end
    return items
  end

  function obj:refreshMenu()
    if not self.menubar then return end
    if self._spinnerTimer then return end
    self.menubar:setTitle(self.enabled and "◆" or "◇")
    self.menubar:setTooltip(self.enabled and "Redraft: running" or "Redraft: stopped")
    self.menubar:setMenu(function()
      return self:menu()
    end)
  end

  function obj:start()
    self:loadConfig()
    if not self.menubar then self.menubar = hs.menubar.new() end
    self:bindHotkeys()
    self.enabled = true
    self:refreshMenu()
    -- Once per Hammerspoon session (a true launch): bring selected backends up to a healthy state.
    -- hs.reload() rebuilds the Lua VM so the flag resets; menu Restart also checks explicitly below.
    if not self._bootChecked then
      self._bootChecked = true
      self:ensureSelectedServices()
    end
    return self
  end

  function obj:stop()
    self:cancelActiveRedraft()
    self:unbindHotkeys()
    self.enabled = false
    self:refreshMenu()
    return self
  end

  function obj:restart()
    self:cancelActiveRedraft()
    self:unbindHotkeys()
    self:loadConfig()
    self:bindHotkeys()
    self.enabled = true
    self:refreshMenu()
    self:ensureSelectedServices()
    notify("Redraft: restarted")
    return self
  end

  function obj:quit()
    self:cancelActiveRedraft()
    self:unbindHotkeys()
    self.enabled = false
    if self._spinnerTimer then
      self._spinnerTimer:stop()
      self._spinnerTimer = nil
    end
    if self._resultView then
      pcall(function()
        self._resultView:delete()
      end)
      self._resultView = nil
    end
    if self.menubar then
      self.menubar:delete()
      self.menubar = nil
    end
    notify("Redraft: quit — reload Hammerspoon config to start it again")
    return self
  end
end
