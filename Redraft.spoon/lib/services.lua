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

  function obj:serviceControl(provider, action)
    local svc = ctx.SERVICES[provider]
    local plist = M.plist(provider)
    if not (svc and plist) then return notify("Redraft: server not installed — run install.sh", "error") end
    local uid = currentUID()
    local target = "gui/" .. uid .. "/" .. svc.label
    local steps = (action == "stop")
        and { { "bootout", target } }
        or { { "bootout", target }, { "bootstrap", "gui/" .. uid, plist } }

    self._svctasks = self._svctasks or {}
    local function runStep(i)
      local t
      t = hs.task.new("/bin/launchctl", function(code)
        self._svctasks[t] = nil
        if i == #steps then
          self:refreshMenu()
          notify("Redraft: " .. svc.name .. " " .. action .. (code == 0 and " ✓" or (" failed (" .. code .. ")")))
        else
          runStep(i + 1)
        end
      end, steps[i])
      if not t then return notify("Redraft: could not run launchctl", "error") end
      self._svctasks[t] = true
      if not t:start() then
        self._svctasks[t] = nil
        notify("Redraft: could not run launchctl", "error")
      end
    end
    runStep(1)
  end

  return M
end
