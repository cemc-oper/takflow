# Vendored jobspec contract — do not edit

This directory is a **read-only vendored copy** of the jobspec contract owned
by the [`cemc-oper/orvix`](https://github.com/cemc-oper/orvix) repository
(`spec/jobspec/` there), pinned to the orvix git ref recorded in
[`ORVIX_VERSION`](./ORVIX_VERSION).

Vendored artifacts: `jobspec.schema.json`, `VERSION`, `conformance/vectors/`,
`conformance/golden/`. The Python modules (`__init__.py`, `conformance/__init__.py`)
are takflow-owned harness code, not vendored content.

To change the contract (schema, vectors, goldens), change it in orvix — bump
`VERSION` there per the semantic-version rules — then re-vendor:

```bash
python scripts/sync_jobspec.py --orvix-ref <new-orvix-ref>
```

CI fails if this copy drifts from orvix @ the pinned ref
(`scripts/sync_jobspec.py --check`).
