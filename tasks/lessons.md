
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

## ng-init captures a reference; never replace an object the widgets bind to (2026-09-10)

Alice's 2x8 TargetGridROIBuilder grid started as one full-arena ROI. The device was
blameless: it was handed `n_rows=1, n_cols=1, fills 0.9` -- the class defaults -- and
built exactly that. The shared `option-argument.html` partial receives its arguments map
through `ng-init="argModel = selected_options.tracking[name]['arguments']"`, which
evaluates once, while `updateUserOptions()` re-seeded the group by assigning a *new*
object. Every widget on screen kept writing to the orphan; the payload carried the
defaults. Before the partial was factored out, each input bound the full path
`selected_options.tracking[name]['arguments'][arg.name]`, re-resolved every digest, so
the replacement had been harmless.

**Why:** the failure is silent and looks like a device bug. Nothing errors, the form shows
the typed values, and the numbers are lost between the last keystroke and the POST.

**How to apply:** when a template captures an object once (`ng-init`, a closure, a
destructured binding), controller code must mutate that object in place -- clear the keys
and re-seed -- never rebind it. When a value the user typed reaches a backend as its
default, suspect object identity before suspecting the backend, and reproduce by measuring
the geometry the defaults would produce against the screenshot.
