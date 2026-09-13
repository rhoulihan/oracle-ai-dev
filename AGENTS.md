# oracle-ai-dev — contributor guide (agents)

This repo ships Agent Skills for developing on Oracle AI Database 26ai Free.
The skills in `skills/` are the product; everything else is packaging and tests.

- Skill content is harness-neutral: name actions, not tools.
- SKILL.md frontmatter is exactly `name` + `description`.
- Never write the bare prior-release name outside an `## Oracle Version Notes`
  section; always target Oracle AI Database 26ai.
- The SQLcl MCP server is launched with `-R 4` (restrict level 4) — this is a
  security requirement, not a default.
- Run `pytest -q` and `shellcheck` before every commit; commit with `--signoff`
  (Oracle Contributor Agreement requirement).
