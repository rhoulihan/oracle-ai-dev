# In-database agents with Select AI

Select AI runs NL2SQL, RAG, and agent workflows inside the database.

## One-time install on Free
The `DBMS_CLOUD` family (which Select AI builds on) is **not preinstalled** on the
Free/on-prem image. Install it once with the scripts shipped with the database
since RU 23.7 (the `enable-select-ai` configurator wraps this), then create an AI
profile pointing at a provider.

## Capabilities (RU-gated)
- NL2SQL (on-prem since 23.7).
- Select AI RAG, feedback, auto object selection, synthetic data, and the
  `DBMS_CLOUD_AI_AGENT` in-database agent framework (23.26.1+).
- Providers: Anthropic, Google, Ollama, OpenAI-compatible, and private LLMs
  (23.26.1+). Encode the RU floor in the skill's version notes.

## Provider profile
Create a profile with `DBMS_CLOUD_AI.CREATE_PROFILE` (credential + model), then
`SELECT AI 'natural language question'`.

## When to prefer client-side
For most app agents, the client-side path (see `client-side.md`) is simpler on
Free. Reach for in-database Select AI when the logic belongs next to the data or
you want NL2SQL inside the DB.

## Oracle Version Notes
Select AI NL2SQL requires 23.7+; the agent framework and most providers require
23.26.1+. Not all features work identically on Free vs Autonomous.

Wiring the OCI credential by hand through the APEX screen is more forgiving
than it looks. In APEX 26.1.4's OCI/Generative AI credential setup, pasting
the entire downloaded OCI API key file into the 'OCI Private Key' field —
including the BEGIN/END PEM armor and the trailing bare OCI_API_KEY line the
OCI console appends after the footer — succeeds and Test Connection returns
'Connection Succeeded'. APEX strips the armor internally, so the commonly
documented advice to manually strip the header/footer before pasting is
unnecessary.

Do not expect the APEX-side assistant to double as a code reader. The APEX
Assistant embedded in SQL Commands only authors/generates SQL — it cannot
explain or summarize a pasted PL/SQL block. Asking it to 'explain' a pasted
block instead returns a newly generated query reflecting whatever is currently
in the SQL editor pane (e.g. a reformat of an existing query already there),
confirming it reads the live editor contents rather than the pasted text.

## Sources
- Select AI (DBMS_CLOUD_AI) documentation — https://docs.oracle.com/en-us/iaas/autonomous-database-serverless/doc/select-ai.html
- On-prem/Free install path — RU-gated; verify against your release notes.
