return function(_ctx)
  local M = {}

  -- Read an AX attribute defensively; nil on any failure (mirrors focus.lua's attr()).
  local function attr(elem, name)
    if not elem then return nil end
    local ok, value = pcall(function()
      return elem:attributeValue(name)
    end)
    return ok and value or nil
  end

  -- The system-wide focused UI element via the Accessibility API. Uses hs.axuielement (the full
  -- AX API), not hs.uielement (focus.lua's module, which lacks the richer methods). Reading other
  -- apps' AX trees needs no new permission beyond the Accessibility grant already used for
  -- keystrokes. Returns nil when the module or attribute is unavailable.
  function M.focusedElement()
    if not (hs.axuielement and hs.axuielement.systemWideElement) then return nil end
    local ok, elem = pcall(function()
      return hs.axuielement.systemWideElement():attributeValue("AXFocusedUIElement")
    end)
    return ok and elem or nil
  end

  -- True for password fields — we must never read or copy their contents.
  function M.isSecure(elem)
    return attr(elem, "AXSubrole") == "AXSecureTextField"
  end

  -- Read the current selection via AXSelectedText. Three outcomes for the caller:
  --   nil          -> attribute unsupported (or non-string) -> fall back to ⌘C
  --   ""           -> supported, but nothing selected
  --   non-empty    -> the selection (read without touching the pasteboard, so no history leak)
  function M.read(elem)
    local value = attr(elem, "AXSelectedText")
    if type(value) ~= "string" then return nil end
    return value
  end

  return M
end
