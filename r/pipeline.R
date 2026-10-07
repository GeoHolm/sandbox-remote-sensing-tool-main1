# ==============================================================================
# pipeline.R -- Load the whole toolkit.
#
#   source("pipeline.R")
#
# Put this at the top of any analysis script.
# ==============================================================================

suppressPackageStartupMessages({
  library(sf)
  library(terra)
})

# Where this file lives, which is not necessarily where you are standing.
#
# Everything used to resolve against the working directory. list.files("R")
# found nothing when this was sourced from the repo root, so the toolkit loaded
# zero functions and the first call failed with "could not find function"
# rather than anything pointing at the cwd. The Python side had the sharper
# version of the same bug: its cache directory was relative too, so running
# from the wrong place created a second, empty cache and silently re-downloaded
# everything -- and a cache miss looks exactly like a cold field, so nothing
# said why. Anchor to the file instead.
PIPELINE_DIR <- local({
  # source() records the path it is reading in the calling frame.
  #
  # Walk the frames from the INSIDE out. When one sourced file sources another
  # -- add_field.R sourcing this -- every enclosing source() has left an $ofile
  # behind, and taking the first match picks the outermost: the caller, not
  # this file. Worse, that path was recorded relative to the caller's working
  # directory, which this file has usually already changed, so it fails to
  # normalize, PIPELINE_DIR lands somewhere wrong, the R/ loop below finds
  # nothing, and the first missing function is reported instead of the cause.
  for (i in rev(seq_len(sys.nframe()))) {
    f <- sys.frame(i)$ofile
    if (!is.null(f) && file.exists(f)) {
      return(dirname(normalizePath(f, winslash = "/")))
    }
  }
  normalizePath(".", winslash = "/")     # sourced some other way; assume cwd
})

# Order matters, so it is stated rather than left to the alphabet. Modules that
# register something at load time -- armor.R calls add_index() -- must come
# after the module defining the registry, and "armor" sorts before "indices".
local({
  files <- list.files(file.path(PIPELINE_DIR, "R"), pattern = "\\.R$",
                      full.names = TRUE)
  # A marker for Shiny, not a module -- see R/_disable_autoload.R.
  files <- files[basename(files) != "_disable_autoload.R"]
  # Ordered by basename, not by set-differencing full paths. The path form can
  # differ between how list.files() builds one and how file.path() does --
  # separators, case, a UNC or symlinked prefix -- and when it does, the
  # set-difference silently degrades to plain alphabetical. That puts armor.R
  # before indices.R and fails with "could not find function add_index".
  head <- c("cache.R", "indices.R")
  ord  <- order(match(basename(files), head, nomatch = length(head) + 1L),
                basename(files))
  for (f in files[ord]) source(f)
})

# Anchored for the same reason, and overridable so a caller can point
# somewhere else without editing the source.
CACHE_DIR <- Sys.getenv("FIELDRS_CACHE",
                        unset = file.path(PIPELINE_DIR, "cache"))

# The boundary library is shared with the Python port, so it sits one level up
# at the repo root rather than inside either implementation.
FIELDS_DIR <- file.path(dirname(PIPELINE_DIR), "data", "fields")
if (!dir.exists(FIELDS_DIR)) FIELDS_DIR <- file.path(PIPELINE_DIR, "data", "fields")

terraOptions(progress = 0)   # quiet per-operation progress bars

# Say who we are to Planetary Computer before the first request goes out.
pc_identify()

message("Remote sensing pipeline loaded.")
message("  load_field()      read a field boundary")
message("  search_scenes()   find Sentinel-2 scenes")
message("  load_scene()      pull one scene as reflectance")
message("  compute_index()   NDVI and friends -- see list_indices()")
message("  plot_rgb()        true-colour composite")
message("  index_timeseries()  season-long trajectory")
message("  get_cdl()         USDA crop type for the field")
