# Contract changes

`docs/contract.md` is frozen with the scoring code (`docs/freeze.json`). A change to the rules, or
to any frozen file, is logged here first with its reason, then the freeze is cut again with
`scripts/freeze.py`. Results compare only between runs with the same freeze.

## Public v1

The rules as Layer2C Lab 029 ran them. Section 8 says plainly that no model hearing ships in this
release; no rule changed.

## Public v1: header provenance corrected (2026-10-24)

The header said Layer2C Lab 029 ran under these rules. The scoring rules match byte for byte, but
section 10 doesn't: it was written after that lab's runs to describe the analysis actually
implemented. The header now says so. No scoring rule changed; the contract's hash changed.
