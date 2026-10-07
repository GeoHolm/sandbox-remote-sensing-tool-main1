# Turn off Shiny's automatic sourcing of R/.
#
# Shiny 1.5+ treats an R/ directory beside app.R as package-like and sources
# every file in it, alphabetically, before app.R runs. This project uses R/ as
# a plain module directory and loads it through pipeline.R, which orders the
# files deliberately -- indices.R has to come before armor.R, because armor.R
# registers indices at load time.
#
# With autoloading on, Shiny got there first, sourced armor.R fourth and failed
# with "could not find function add_index" before app.R executed a single line.
# Under Rscript the same code loaded fine, which made it look like a Shiny bug
# rather than a load-order one.
#
# The presence of this file is the documented way to disable that behaviour;
# its contents are never run.
