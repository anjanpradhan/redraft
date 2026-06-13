return function()
  local M = {}

  local function appPid(app)
    local ok, pid = pcall(function() return app and app:pid() end)
    return ok and pid or nil
  end

  local function windowId(win)
    local ok, wid = pcall(function() return win and win:id() end)
    return ok and wid or nil
  end

  local function focusedElement()
    if not (hs.uielement and hs.uielement.focusedElement) then return nil end
    local ok, elem = pcall(function() return hs.uielement.focusedElement() end)
    return ok and elem or nil
  end

  local function attr(elem, name)
    if not elem then return nil end
    local ok, value = pcall(function() return elem:attributeValue(name) end)
    return ok and value or nil
  end

  local function attrText(value)
    if value == nil then return "" end
    if type(value) ~= "table" then return tostring(value) end
    local parts = {}
    for k, v in pairs(value) do parts[#parts + 1] = tostring(k) .. "=" .. tostring(v) end
    table.sort(parts)
    return table.concat(parts, ",")
  end

  local function elementSignature(elem)
    if not elem then return nil end
    local names = {
      "AXRole", "AXSubrole", "AXIdentifier", "AXDOMIdentifier", "AXTitle",
      "AXDescription", "AXPosition", "AXSize", "AXSelectedTextRange",
    }
    local parts = {}
    local hasValue = false
    for _, name in ipairs(names) do
      local value = attr(elem, name)
      if value ~= nil then hasValue = true end
      parts[#parts + 1] = name .. "=" .. attrText(value)
    end
    return hasValue and table.concat(parts, "\31") or nil
  end

  function M.snapshot(app)
    local win = hs.window.focusedWindow()
    local elem = focusedElement()
    return {
      pid = appPid(app),
      window = windowId(win),
      element = elem,
      signature = elementSignature(elem),
    }
  end

  function M.stillCurrent(snapshot)
    if not snapshot then return true end
    local curApp = hs.application.frontmostApplication()
    if snapshot.pid and appPid(curApp) ~= snapshot.pid then return false end

    if snapshot.window then
      local curWindow = hs.window.focusedWindow()
      if windowId(curWindow) ~= snapshot.window then return false end
    end

    if snapshot.element then
      local elem = focusedElement()
      if not elem then return false end
      if elem == snapshot.element then return true end
      return snapshot.signature ~= nil and elementSignature(elem) == snapshot.signature
    end

    return true
  end

  return M
end
