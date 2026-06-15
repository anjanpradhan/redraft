# Redraft dev tasks — single entry point for Python + Lua.
# Assumes the toolchain is already installed: uv (Python) and `brew install luacheck stylua` (Lua).
LUA_SRC := Redraft.spoon
# Override to verify without writing, e.g. CI: `make lua STYLUA_FLAGS=--check`
STYLUA_FLAGS ?=

.DEFAULT_GOAL := help
.PHONY: help lua py test check

help:   ## List targets
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | sort | \
	  awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-8s\033[0m %s\n",$$1,$$2}'

lua:    ## Lua: format (stylua) + lint (luacheck)
	stylua $(STYLUA_FLAGS) $(LUA_SRC)
	luacheck $(LUA_SRC)

py:     ## Python: pre-commit suite (validates + autofixes)
	uv run pre-commit run --all-files

test:   ## Python: run tests
	uv run pytest

check: py lua test   ## Format, lint, and test everything
