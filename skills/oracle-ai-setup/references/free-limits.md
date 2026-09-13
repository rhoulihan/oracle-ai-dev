# Oracle AI Database 26ai Free — limits & gotchas

- 2 CPU threads, 2 GB RAM (SGA+PGA), 12 GB user data (ORA-12954 at the cap).
- One instance per host/container (ORA-00442).
- Image `container-registry.oracle.com/database/free:latest` == 23.26.2.0.0; no tag contains the brand string.
- Image **variant** matters: `slim` (gvenzl) and `-lite` builds strip Oracle Text —
  `ORA-29833` on any text/search index. `faststart` is orthogonal (boot speed, not
  content). Free itself supports Text; the packaging removes it, which is easy to misread
  as a product limit.
- Warm cold-start ~11s (image ships a healthcheck). First-time build (empty volume) ~10 min.
- Vector: IVF indexes build with zero config; HNSW needs `VECTOR_MEMORY_SIZE` set (within the ~2GB cap).

## Oracle Version Notes
23ai was rebranded to Oracle AI Database 26ai in Oct 2025; the code line stays 23.26.x.
