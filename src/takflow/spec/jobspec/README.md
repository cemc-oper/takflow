# Vendored jobspec contract — do not edit

This directory is a **read-only vendored copy** of the jobspec contract owned
by the [`cemc-oper/orvix`](https://github.com/cemc-oper/orvix) repository
(`spec/jobspec/` there), pinned to the orvix full commit recorded in
[`ORVIX_VERSION`](./ORVIX_VERSION).

Vendored artifacts: `jobspec.schema.json`, `VERSION`, `conformance/vectors/`,
`conformance/golden/`. The Python modules (`__init__.py`, `conformance/__init__.py`)
are takflow-owned harness code, not vendored content.

To change the contract (schema, vectors, goldens), change it in orvix — bump
`VERSION` there per the semantic-version rules — resolve the target ref to a full
commit, then re-vendor:

```bash
git -C <orvix-repo> rev-parse '<tag-or-ref>^{commit}'
python scripts/sync_jobspec.py --orvix-ref <full-40-character-commit>
```

Pass the resolved commit, not a tag or short SHA: the script preserves the input
ref verbatim, while CI requires a full commit in `ORVIX_VERSION`. If the output
contains `(stale)`, upstream deletions still have local copies and the sync is
not complete; handle and review those deletions explicitly, then run `--check`.
CI fails if this copy drifts from orvix @ the pinned commit
(`scripts/sync_jobspec.py --check`).
