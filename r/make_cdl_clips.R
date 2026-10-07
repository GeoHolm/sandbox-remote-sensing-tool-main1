# ==============================================================================
# make_cdl_clips.R -- Pre-clip CDL for the demo library so the deployed app
# never calls CropScape.
#
#   Rscript make_cdl_clips.R
#
# WHY
# The Shiny app on shinyapps.io cannot carry the local CDL store: the national
# rasters run to about 25 GB against a bundle limit and a 1 GB instance. But a
# single field's clip is a few kilobytes, and the demo library is eleven fields,
# so every field-year the app can show fits in the bundle easily.
#
# Each clip is written under the same geometry hash the rest of the cache uses,
# so the reader finds it without knowing which field it came from.
#
# WHAT THIS DOES NOT COVER
# Boundaries a visitor uploads. Those have no pre-made clip, no national store
# to fall back to on shinyapps.io, and so still go to CropScape -- which is
# exactly as unreliable as it was. Fixing that needs the national rasters
# converted to COGs and hosted somewhere the app can range-read, which is the
# production path described in pitch/IMPLEMENTATION-ESTIMATE.md, not something
# a demo bundle can solve.
#
# Re-run when a field is added to data/fields/ or a new CDL year is published.
# ==============================================================================

# Rscript has no calling frame, so sys.frame()$ofile -- which works under
# source() -- errors here. The --file= argument is the portable way.
local({
  a <- commandArgs(trailingOnly = FALSE)
  f <- sub("^--file=", "", a[grep("^--file=", a)])
  if (length(f)) setwd(dirname(normalizePath(f[1], winslash = "/")))
})
suppressMessages(source("pipeline.R"))

OUT <- file.path(PIPELINE_DIR, "cdl_clips")
dir.create(OUT, showWarnings = FALSE, recursive = TRUE)

years <- cdl_available_years()
if (!length(years)) {
  stop("No local CDL store found at ", cdl_root(),
       "\n  Run: python python/download_cdl.py", call. = FALSE)
}

fields <- list.files(FIELDS_DIR, pattern = "[.]geojson$", full.names = TRUE)
cat(sprintf("%d fields x %d years (%d-%d) -> %s\n\n",
            length(fields), length(years), min(years), max(years), OUT))

n_made <- n_skip <- n_fail <- 0L
for (f in fields) {
  aoi <- load_field(f)
  made <- 0L
  for (y in years) {
    dest <- file.path(OUT, sprintf("%s_%d.tif", cache_key(aoi, "cdlclip"), y))
    if (file.exists(dest)) { n_skip <- n_skip + 1L; next }
    ok <- tryCatch({
      # clip = TRUE so the stored raster is already masked to the field and the
      # app does no geometry work at read time.
      r <- get_cdl_local(aoi, y, clip = TRUE)
      terra::writeRaster(r, dest, overwrite = TRUE,
                         datatype = "INT1U", gdal = c("COMPRESS=DEFLATE"))
      TRUE
    }, error = function(e) {
      cat(sprintf("   %s %d: %s\n", basename(f), y, conditionMessage(e)))
      FALSE
    })
    if (ok) { made <- made + 1L; n_made <- n_made + 1L } else n_fail <- n_fail + 1L
  }
  cat(sprintf("  %-34s %d new\n", basename(f), made))
}

sz <- sum(file.info(list.files(OUT, full.names = TRUE))$size, na.rm = TRUE)
cat(sprintf("\n%d written, %d already present, %d failed\n", n_made, n_skip, n_fail))
cat(sprintf("%d clips, %.1f MB total\n",
            length(list.files(OUT, pattern = "[.]tif$")), sz / 1e6))
if (n_fail) quit(status = 1)
