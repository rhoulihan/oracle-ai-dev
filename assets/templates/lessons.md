# Lessons — measured facts from this project's work

Observations, not directives: what this project measured and what surprised it.
This file is its own ledger — `status:` tracks each entry's life.

- The ledger legend — `status: local | offered | submitted | declined`:
  `local` (captured here), `offered` (upstream offer made), `submitted` (sent
  upstream), `declined` (kept local by choice). Upstream contribution is not
  shipped yet, so entries stay `local`.
- The agent drafts an entry, shows it verbatim, and writes it only on approval.
- Nothing identifying: no person, customer, engagement, or codename; round
  distinctive constants.

<!-- contribution: never   # uncomment to opt this project out of any upstream offer -->

<!-- Example entry — copy the shape, delete the comment markers.

## duality-view-write-amplification-on-hot-cart
status: local
captured: 2026-01-15 · context: 26ai RU, duality vs single collection, write-hot
**Lesson.** A duality view over the cart aggregate pays a read-time join on
every write; the single collection did not.
**What happened.** Measured p50 write ~2.4x the collection's across 25 trials;
reads were inside the noise floor, so the read side did not pay it back.
**Apply.** For write-hot aggregates, measure the single collection before
proposing duality — do not assume the join is free.

-->
