# Install

## Claude Code

```
/plugin marketplace add rhoulihan/oracle-ai-dev
/plugin install oracle-ai-dev@oracle-ai-dev-marketplace
```

## Codex

```
codex plugin marketplace add rhoulihan/oracle-ai-dev
# then install oracle-ai-dev from /plugins
```

## Requirements

- Docker (or Podman) for the database container.
- SQLcl on PATH (or set the `sqlcl_path` plugin config) for live database access
  via MCP. The bundled SQLcl MCP server launches with restrict level 4 (`-R 4`).

## Companion plugins

Optional, and recommended: the public **superpowers** plugin. Four of its skills
line up with how this plugin already works —

- **test-driven-development** — the red-first discipline for changes to
  generated code and to the benchmark harness.
- **verification-before-completion** — evidence before any "done" claim, which
  is what the verify scripts and plancheck already demand here.
- **systematic-debugging** — harness-first investigation when a measured number
  looks wrong.
- **brainstorming** — structured exploration before candidate models are
  proposed.

These are **soft dependencies**. The plugin detects them in the agent's own
skill list and invokes them if present; nothing here requires them and nothing
degrades without them. Every fallback is written out inline in
`skills/oracle-data-modeling/references/operating-principles.md` (§F), so the
agent runs the same discipline by hand when a companion is absent.

## After install

Ask the assistant to "set up Oracle AI Database in Docker" — the `oracle-ai-setup`
skill picks a compose profile, runs the configurators, and verifies the stack.

The first modeling use in a project runs a one-time operating-principles gap-fill —
it asks only about the principles your own `CLAUDE.md`/`AGENTS.md` do not already
cover, and records your choices in `.oracle-ai-dev/standards.md`.
