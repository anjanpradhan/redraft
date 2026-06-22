return function(obj, ctx)
  local notify = function(...)
    return ctx.ui.notify(...)
  end

  function obj:loadConfig()
    self.config = {}
    if hs.fs.attributes(ctx.CONFIG_PATH) then
      local ok, data = pcall(function()
        return hs.json.read(ctx.CONFIG_PATH)
      end)
      if ok and type(data) == "table" then self.config = data end
    end
    self.config.fixProvider = self.config.fixProvider or "embedded"
    self.config.improveProvider = self.config.improveProvider or "none"
    self.config.improveStyle = self.config.improveStyle or "friendly"

    local hk = self.config.hotkeys or {}
    hk.fix = hk.fix or { mods = { "cmd", "alt" }, key = "F" }
    hk.improve = hk.improve or { mods = { "cmd", "alt" }, key = "I" }
    self.config.hotkeys = hk

    ctx.ui.setNotifications(self.config.notifications)
    self:detectAgents()
  end

  function obj:detectAgents()
    self._agents = {}
    for _, t in ipairs(ctx.AGENT_TOOLS) do
      local out = hs.execute("command -v " .. t .. " 2>/dev/null", true) or ""
      out = out:gsub("%s+", "")
      self._agents[t] = (out ~= "") and out or false
    end
  end

  function obj:autoAgent()
    for _, t in ipairs(ctx.AGENT_TOOLS) do
      if (self._agents or {})[t] then return t end
    end
    return nil
  end

  function obj:setAgent(tool)
    self.config.improveProvider = "agent"
    self.config.agent = self.config.agent or {}
    self.config.agent.tool = tool
    if tool ~= "auto" and (self._agents or {})[tool] then
      self.config.agent.bins = self.config.agent.bins or {}
      self.config.agent.bins[tool] = self._agents[tool]
    end
    self:saveConfig()
    self:refreshMenu()
    notify("Redraft: improve → agent (" .. tool .. ")")
  end

  function obj:saveConfig()
    hs.fs.mkdir(ctx.HOME .. "/.config")
    hs.fs.mkdir(ctx.HOME .. "/.config/redraft")
    hs.json.write(self.config, ctx.CONFIG_PATH, true, true)
  end

  function obj:setProvider(kind, name)
    self.config[kind .. "Provider"] = name
    self:saveConfig()
    self:refreshMenu()
    notify("Redraft: " .. kind .. " → " .. (ctx.LABELS[name] or name))
  end

  function obj:setImproveStyle(style)
    self.config.improveStyle = style
    self:saveConfig()
    self:refreshMenu()
    notify("Redraft: improve style → " .. (ctx.STYLE_LABELS[style] or style))
  end
end
