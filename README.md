# takflow

`takflow`(`tak` from task/takler + `flow`)is the unified workflow-generation
framework for the MCV numerical weather prediction model and the related CMA
post-processing systems. It abstracts the generic layers currently duplicated
across `mcv-workflow`, `cma-gfs-post-workflow`, and `cma-meso-1km-post-workflow`,
absorbs `light-ecflow` as a serialization backend, and defines the **job-run
resource description contract** (`jobspec`) consumed by the Go `orvix` project.

See `../TAKFLOW_DESIGN.md` for the full design.

## Status

Phase 0 — package skeleton + the `jobspec` contract + orvix conformance harness.

Implemented so far:

- `takflow.spec.jobspec` — the canonical contract: `jobspec.schema.json` (the
  single source of truth, vendored by orvix) + `VERSION`.
- `takflow.jobspec` — `ResourceSpec` (flat, 1:1 with the contract),
  `TaskResource` (app-friendly high-level model that compiles down), and
  `to_orvix_directives()` (renders `#ORVIX` directive lines).
- `takflow.config.workload` — generic `BaseWorkload` / `SlurmWorkload` /
  `ShellWorkload` (the subset `TaskResource` needs).
- Conformance harness under `src/takflow/spec/jobspec/conformance/`.

## Install (dev)

```bash
cd framework/takflow
pip install -e ".[dev]"
```

## Conformance test against orvix

The conformance test renders sample `ResourceSpec` cases to `#ORVIX` scripts,
pipes them through `orvix generate --scheduler X`, and diffs against goldens.
It needs an `orvix` binary; point to it with `ORVIX_BIN` or put it on `PATH`:

```bash
ORVIX_BIN=/path/to/orvix pytest tests/test_conformance.py
```

If no `orvix` binary is found, the conformance test is skipped (not failed).
