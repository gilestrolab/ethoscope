
## Do not diagnose a two-source discrepancy from code alone (2026-08-19)

Chasing "the updater says Up to Date but the device runs old code", I traced both fields
to their sources, found that the version string is snapshotted at process start while the
badge reflects the disk, and concluded that the services had been pulled without a
restart. It was a coherent story and it was wrong: the real cause was a frozen
`refs/remotes/origin/<branch>` making the device compare itself against a stale mirror of
itself. Only one of the 31 devices matched my theory.

**Why:** both explanations predicted the same visible table. Nothing in the code could
separate them -- only `origin_commit`, which the UI never displayed, could. I had access
to that value from the start and reasoned for several steps without asking for it.

**How to apply:** when two independently-sourced fields disagree, get the raw payload
before building a theory of *why*. One `curl` of the API that feeds the view settles in
seconds what code-reading cannot settle at all. Ask for it early; the user can usually
fetch what is behind an SSO wall in one command.
