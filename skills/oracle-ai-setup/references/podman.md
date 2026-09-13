# Running Oracle AI Database Free under Podman

Podman is a drop-in for this stack — required on hosts where docker is not
permitted (e.g. corporate-managed laptops). Everything below is field-verified
on macOS/Apple silicon (podman 6.x) against 26ai Free images; Linux is the
easy case.

## Machine setup (macOS)

```bash
brew install podman
podman machine init --cpus 4 --memory 6144 --disk-size 40
podman machine start
```

- The DATABASE container wants ~4 GB; give the machine headroom above that
  (6 GB works). Free itself caps at 2 CPU / 2 GB SGA+PGA regardless.
- 40 GB disk is comfortable for image + volume; first-time builds are
  disk-hungry.

## Compose vs direct run

`podman compose` delegates to an external provider (podman-compose or
docker-compose) — it is NOT built in. If no provider is installed, skip
compose and run directly; the compose profiles map 1:1:

```bash
podman run -d --name oracle-ai-dev \
  -p 1521:1521 -p 8080:8080 -p 27017:27017 \
  -e ORACLE_PWD=devpassword \
  container-registry.oracle.com/database/free:latest
```

Healthchecks baked into the image still run; `podman ps` shows
`(healthy)` when the DATABASE is up.

## Registry TLS trap (corporate networks)

Behind TLS-intercepting proxies, docker.io pulls can fail with a misleading
`x509: certificate has expired or is not yet valid` surfacing from a
CloudFront blob URL — while other registries work. Observed with
`docker.io/gvenzl/oracle-free`; the same image pulled cleanly from ghcr.io.
Workaround — pull from an alternate registry, retag to the expected name,
and never re-pull:

```bash
podman pull ghcr.io/gvenzl/oracle-free:<tag>   # non-slim tag — slim strips Oracle Text
podman tag ghcr.io/gvenzl/oracle-free:<tag> docker.io/gvenzl/oracle-free:<tag>
podman build --pull=never ...   # or podman run with the local tag
```

`container-registry.oracle.com` pulls are anonymous and were unaffected.

## Apple silicon (aarch64)

- Oracle's registry and gvenzl images are multi-arch — the container runs
  **native aarch64**, no emulation.
- Custom Dockerfiles that hardcode x86_64 yum baseurls fail on aarch64 with
  misleading dependency errors (e.g. installing mongosh from an el8 x86_64
  repo: `nothing provides libpthread.so.0(GLIBC_2.12)(64bit)`). Make repo
  URLs arch-aware: `baseurl=.../$(uname -m)/`.

## Readiness: three different "up" signals

1. **Container healthy** ≠ init done. First-boot init scripts
   (`/container-entrypoint-initdb.d`) run before the log prints
   `DATABASE IS READY TO USE`. Heavy init (in-database ONNX embedding runs
   ~55 rows/s single-threaded on Free; large index builds) can exhaust a
   default healthcheck window — raise `retries` if init grows.
2. **Wait loop** (macOS has no `timeout` by default):
   ```bash
   until [[ "$(podman logs oracle-ai-dev 2>&1)" == *"DATABASE IS READY TO USE"* ]]; do sleep 20; done
   ```
   Capture-then-match, not `| grep -q` — `grep -q` exits on first match, the producer
   takes SIGPIPE, and under `set -o pipefail` the condition never succeeds, so the
   loop spins forever after the database is already up.
3. **DB-ready ≠ ORDS/Mongo-API-ready.** ORDS installs itself into the
   database for minutes after DB-ready; connections to 27017 in that window
   get `ECONNREFUSED`. Retry or use the verify scripts, which block until
   the API actually serves.

## Tooling compatibility

- Scripts that hardcode `docker exec ...` break; support a
  `CONTAINER_ENGINE` env (default docker) and pass `podman` on restricted
  hosts.
- In-container SQL exec pattern:
  ```bash
  podman exec oracle-ai-dev bash -c "sqlplus -s user/pwd@localhost:1521/FREEPDB1 <<'EOF'
  ...
  EOF"
  ```
  Escape `$` (e.g. JSON path expressions like `'\$[*]'`) when the heredoc
  passes through the outer double-quoted `bash -c` string.

## Lifecycle

```bash
podman rm -f oracle-ai-dev          # discard container (volume survives if named)
podman machine stop                 # reclaim the VM's memory
```
