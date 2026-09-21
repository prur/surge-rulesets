# surge-rulesets

Generated Surge rule sets (data files; do not hand-edit).

- `node-reject-mirror.list` — mirror of the upstream node's CN-domain reject list, converted to Surge format.
  Purpose: client-side routing must never send domains that the node would reject.
  Regenerate with `NODE_SSH=<ssh-alias> python3 gen-mirror.py --push` (alias must exist in your local ssh config).

Verify the served copy matches the local file:

```
python3 gen-mirror.py --verify   # sha256(local) vs sha256(served by jsdelivr)
```
