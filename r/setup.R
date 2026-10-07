# ==============================================================================
# setup.R -- Run this once.
#
#   source("setup.R")
#
# Installs the handful of packages the pipeline needs and checks that GDAL can
# read cloud-hosted imagery over HTTP, which is the one thing that tends to be
# broken on a fresh machine.
# ==============================================================================

REQUIRED <- c(
  "sf",      # vector data: field boundaries
  "terra",   # raster data: imagery, indices
  "rstac",   # searching the satellite catalogue
  "leaflet", # interactive field map
  "leaflet.extras", # draw toolbar for tracing a boundary by hand
  "shiny",   # the app
  "bslib",   # app theming
  "DT",      # sortable tables in the app
  "digest",  # stable cache keys
  "future",  # parallel imagery reads
  "furrr"    # ...and the map over them
)

missing_pkgs <- REQUIRED[!vapply(REQUIRED, requireNamespace, logical(1), quietly = TRUE)]

if (length(missing_pkgs)) {
  message("Installing: ", paste(missing_pkgs, collapse = ", "))
  install.packages(missing_pkgs, repos = "https://cloud.r-project.org")
} else {
  message("All required packages already installed.")
}

still_missing <- REQUIRED[!vapply(REQUIRED, requireNamespace, logical(1), quietly = TRUE)]
if (length(still_missing)) {
  stop("Failed to install: ", paste(still_missing, collapse = ", "))
}

# --- check the real path end to end ------------------------------------------
#
# This runs the same three steps the pipeline does -- search the catalogue, sign
# the asset URL, stream a window of pixels -- rather than poking a hardcoded
# file. If this passes, the pipeline will work.

message("\nChecking catalogue access and cloud raster streaming...")

ok <- tryCatch({
  items <- rstac::stac("https://planetarycomputer.microsoft.com/api/stac/v1") |>
    rstac::stac_search(
      collections = "sentinel-2-l2a",
      bbox        = c(-93.735, 42.035, -93.723, 42.043),
      datetime    = "2024-08-01T00:00:00Z/2024-08-02T23:59:59Z",
      limit       = 1
    ) |>
    rstac::post_request()

  if (length(items$features) == 0) stop("catalogue returned no scenes")
  message("  Catalogue reachable.")

  signed <- rstac::items_sign(items, sign_fn = rstac::sign_planetary_computer())
  href   <- signed$features[[1]]$assets$B04$href
  r      <- terra::rast(paste0("/vsicurl/", href))

  # Read a small window only -- this is the byte-range read the pipeline relies on.
  win <- terra::ext(r)
  win <- terra::ext(win$xmin, win$xmin + 500, win$ymin, win$ymin + 500)
  v   <- terra::values(terra::crop(r, win))
  length(v) > 0
}, error = function(e) {
  message("  FAILED: ", conditionMessage(e))
  FALSE
})

if (isTRUE(ok)) {
  message("  OK -- streamed a window of live Sentinel-2 imagery.")
} else {
  message("  Could not stream imagery. Most often this is a corporate proxy or\n",
          "  firewall blocking HTTPS range requests, which the pipeline needs.\n",
          "  Worth checking with IT before debugging the R side.")
}

cat("\nGDAL version: ", terra::gdal(), "\n", sep = "")
cat("PROJ version: ", as.character(terra::gdal(lib = "proj")), "\n", sep = "")
cat("\nSetup complete. Next:  source(\"run_demo.R\")\n")
