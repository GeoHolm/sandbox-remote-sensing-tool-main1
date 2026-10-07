# Conventions for this repository

## American English

Use American English in all prose, documentation, comments and commit messages:
color, normalize, center, analyze, catalog, gray, meter, behavior, labeled.

**The exception is existing code identifiers, which are British-spelled and must
not be renamed:** `CDL_COLOURS`, `cdl_colour_map`, `plot_false_colour`,
`Recolour`, `recolouring`. Documentation referring to them keeps their spelling.
Renaming them would break `r/app.R` and anything written against the package,
for no benefit. A spelling pass must skip anything inside backticks.

Comments in `r/R/*.R` and `python/fieldrs/*.py` are still British in places.
That is known, not an oversight — converting them safely needs a guard listing
the identifiers above.

## Before changing a constant

Numbers in this pipeline are load-bearing and most were fitted on eleven fields.
`METHODS.md` documents every formula and says which constants are provisional;
the root `README.md` records what has been validated against ground truth and
what has not. Read the relevant section before adjusting a threshold, and say in
the commit message what evidence moved it.
