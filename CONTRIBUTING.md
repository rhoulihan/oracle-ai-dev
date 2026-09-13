# Contributing to oracle-ai-dev

We welcome your contributions! There are multiple ways to contribute.

## Opening issues

For bugs or enhancement requests, please file a GitHub issue unless it's
security related. When filing a bug remember that the better written the bug is,
the more likely it is to be fixed. If you think you've found a security
vulnerability, do not raise a GitHub issue and follow the instructions in our
[security policy](./SECURITY.md).

## Contributing code

We welcome your code contributions. Before submitting code via a pull request,
you will need to have signed the
[Oracle Contributor Agreement][OCA] (OCA) and your commits need to include the
following line using the name and e-mail address you used to sign the OCA:

```text
Signed-off-by: Your Name <you@example.org>
```

This can be automatically added to pull requests by committing with `--sign-off`
or `-s`, e.g.

```text
git commit --signoff
```

Only pull requests from committers that can be verified as having signed the OCA
can be accepted.

## Pull request process

1. Ensure there is an issue created to track and discuss the fix or enhancement
   you intend to submit.
1. Fork this repository.
1. Create a branch in your fork to implement the changes. We recommend using
   the issue number as part of your branch name, e.g. `1234-fixes`.
1. Ensure that any documentation is updated with the changes that are required
   by your change.
1. Ensure that any samples are updated if the base image has been changed.
1. Ensure the Tier-1 checks pass locally: `pytest -q` and
   `shellcheck assets/**/*.sh scripts/*.sh`.
1. Submit the pull request. *Do not leave the pull request blank*. Explain
   exactly what your changes are meant to do and provide simple steps on how to
   validate your changes. Ensure that you reference the issue you created as
   well.
1. We will assign the pull request to 2-3 people for review before it is merged.

## Code of conduct

Follow the [Golden Rule](https://en.wikipedia.org/wiki/Golden_Rule). If you'd
like more specific guidelines, see the [Code of Conduct](./CODE_OF_CONDUCT.md).

## License

This project is licensed under the Universal Permissive License (UPL) 1.0. By
contributing you agree that your contributions will be licensed under the same
terms.

[OCA]: https://oca.opensource.oracle.com

## Content contributions and confidentiality

Skill content ships publicly. Hard rules, enforced by review and lint:

- **No PII or customer-identifiable information** — no person, company, product,
  engagement, or codename references; generalized phrasings only ("a
  financial-services PoC", "an insurance carrier's assessment").
- **Round distinctive figures.** Exact constants fingerprint their source — if a
  number exists verbatim anywhere public, ship it rounded (`~0.83 s`, `~20K`).
- **A ban must not teach what it bans** — guardrail prose never spells non-GA
  syntax or pre-release feature names.
- Follow `skills/oracle-data-modeling/references/claims-guardrails.md` for the
  never-claim/always-say list; it is normative for all skills.
- Maintainers: install the confidential register at
  `~/.oracle-ai-dev/confidential-register.txt` (or set
  `ORACLE_AI_DEV_CONFIDENTIAL_REGISTER`) so the lint gates your releases; the
  register itself must never be committed or shared.

## Rules must be enforced or labeled

**Any reference file written in RULE/CHECK form must either cite the code that
enforces it, or carry an explicit `> Advisory:` marker.** Prose in validator
form gets TRUSTED as a validator — readers (human and agent) assume the CHECKs
gate something, so a rulebook that enforces nothing is worse than no rulebook.
Cite the enforcing path (`tooling/...`, `tests/...`) next to the rules, or say
plainly that they are judgment. `tests/test_rule_provenance.py` fails the build
otherwise, and also fails on citations of paths that do not exist.
