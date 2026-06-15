return function(obj, ctx)
  local M = {}
  local _uid

  local function notify(...)
    return ctx.ui.notify(...)
  end

  local function currentUID()
    if not _uid then _uid = (hs.execute("/usr/bin/id -u") or ""):gsub("%s+", "") end
    return _uid
  end

  function M.plist(provider)
    local svc = ctx.SERVICES[provider]
    if not svc then return nil end
    local p = ctx.LAUNCHD_DIR .. "/" .. svc.label .. ".plist"
    return hs.fs.attributes(p) and p or nil
  end

  function M.running(provider)
    local svc = ctx.SERVICES[provider]
    if not svc then return false end
    local _, ok = hs.execute("/bin/launchctl print gui/" .. currentUID() .. "/" .. svc.label .. " >/dev/null 2>&1")
    return ok == true
  end

  function M.healthURL(provider)
    local svc = ctx.SERVICES[provider]
    if not svc then return nil end
    local cfg = (type(obj.config) == "table") and obj.config[svc.configKey] or nil
    local base = (type(cfg) == "table" and type(cfg.url) == "string" and cfg.url ~= "" and cfg.url) or svc.defaultURL
    return base:gsub("/+$", "") .. svc.healthPath
  end

  -- One-shot, non-blocking HTTP probe. cb(true) iff the endpoint answers 200; cb(false) on any
  -- non-200 or transport error (asyncGet reports connection-refused as a negative status).
  function M.checkHealth(provider, cb)
    local url = M.healthURL(provider)
    if not url then return cb(false) end
    hs.http.asyncGet(url, nil, function(status)
      cb(status == 200)
    end)
  end

  -- Poll until healthy or bootTimeout elapses (counted in ~1s attempts, no wall-clock dependency).
  -- The timer is tracked per-provider so stop() can cancel an in-flight wait.
  function obj:waitHealthy(provider, onDone)
    local svc = ctx.SERVICES[provider]
    if not svc then return onDone(false) end
    self._svctimers = self._svctimers or {}
    if self._svctimers[provider] then self._svctimers[provider]:stop() end
    local attempts, maxAttempts = 0, math.max(1, math.floor(svc.bootTimeout))
    local function finish(ok)
      if self._svctimers[provider] then
        self._svctimers[provider]:stop()
        self._svctimers[provider] = nil
      end
      onDone(ok)
    end
    self._svctimers[provider] = hs.timer.doEvery(1, function()
      attempts = attempts + 1
      M.checkHealth(provider, function(ok)
        if ok then
          finish(true)
        elseif attempts >= maxAttempts then
          finish(false)
        end
      end)
    end)
  end

  function obj:serviceControl(provider, action)
    local svc = ctx.SERVICES[provider]
    local plist = M.plist(provider)
    if not (svc and plist) then return notify("Redraft: server not installed — run install.sh", "error") end
    local uid = currentUID()
    local target = "gui/" .. uid .. "/" .. svc.label
    local steps = (action == "stop") and { { "bootout", target } }
      or { { "bootout", target }, { "bootstrap", "gui/" .. uid, plist } }

    self._svcStarting = self._svcStarting or {}
    self._svctimers = self._svctimers or {}

    if action == "stop" then
      if self._svctimers[provider] then
        self._svctimers[provider]:stop()
        self._svctimers[provider] = nil
      end
      self._svcStarting[provider] = nil
      self:refreshMenu()
    else
      self._svcStarting[provider] = true
      self:refreshMenu()
    end

    self._svctasks = self._svctasks or {}
    local function runStep(i)
      local t
      t = hs.task.new("/bin/launchctl", function(code)
        self._svctasks[t] = nil
        if i ~= #steps then return runStep(i + 1) end
        if action == "stop" then
          self:refreshMenu()
          notify("Redraft: " .. svc.name .. " stop" .. (code == 0 and " ✓" or (" failed (" .. code .. ")")))
        elseif code ~= 0 then
          self._svcStarting[provider] = nil
          self:refreshMenu()
          notify("Redraft: " .. svc.name .. " " .. action .. " failed (" .. code .. ")", "error")
        else
          -- launchd accepted the job; don't claim "running" until HTTP actually answers.
          self:waitHealthy(provider, function(ok)
            self._svcStarting[provider] = nil
            self:refreshMenu()
            if ok then
              notify("Redraft: " .. svc.name .. " ready ✓")
            else
              notify("Redraft: " .. svc.name .. " did not become healthy in " .. svc.bootTimeout .. "s", "error")
            end
          end)
        end
      end, steps[i])
      if not t then
        self._svcStarting[provider] = nil
        self:refreshMenu()
        return notify("Redraft: could not run launchctl", "error")
      end
      self._svctasks[t] = true
      if not t:start() then
        self._svctasks[t] = nil
        self._svcStarting[provider] = nil
        self:refreshMenu()
        notify("Redraft: could not run launchctl", "error")
      end
    end
    runStep(1)
  end

  -- On launch, bring the *selected* backends up to a healthy state. A backend already serving is
  -- left untouched (silent no-op); only a down/unhealthy one is (re)started, which then waits on health.
  function obj:ensureSelectedServices()
    local function check(kind, provider)
      if self.config[kind .. "Provider"] ~= provider or not M.plist(provider) then return end
      M.checkHealth(provider, function(ok)
        if not ok then self:serviceControl(provider, "start") end
      end)
    end
    check("fix", "languagetool")
    check("improve", "ollama")
  end

  return M
end
