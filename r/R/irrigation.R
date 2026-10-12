# ==============================================================================
# irrigation.R -- Irrigated or not, from USGS irrigated-agriculture maps
#
# Port of python/fieldrs/irrigation.py; keep the two in step.
#
# WHAT THE MAPS ARE
# Binary CONUS rasters, 1 = irrigated agriculture, in the CDL's own projection
# (EPSG:5070): 2002 and 2007 at 50 m, 2012 and 2017 at 30 m. Read in place from
# a local folder, one small window per field, exactly as the local CDL is.
#
# THE LIMITS
# At field level single maps are not reliable -- the Central Valley field reads
# 98-100% irrigated in 2002-2012 and 9.6% in 2017; a Kansas field named rainfed
# reads ~60% in 2007 and 2012 only. So every year also carries
# `irrigated_maps` -- in how many of the maps the field is irrigated -- and one
# map disagreeing with the rest is visible rather than silently believed.
#
# There is a map every five years and none after 2017. A CDL year is given the
# nearest map at or before it, and says which one. Before 2002 there is nothing.
#
# Point IRRIGATION_DIR at the folder; files are found by the year in their name
# (irri17_30lzw.tif -> 2017).
# ==============================================================================

IRRIGATION_DIR_DEFAULT <- "/mnt/cephfs/csip-data/csip-lamps/GIS_analysis_data"
IRRIGATION_NAME_RE <- "^irri([0-9]{2})_[0-9]+[A-Za-z0-9_]*[.]tif$"

# Share of the field (%) mapped irrigated for each label.
IRRIGATED_PCT <- 50.0
PARTLY_PCT    <- 10.0

irrigation_dir <- function() Sys.getenv("IRRIGATION_DIR", unset = IRRIGATION_DIR_DEFAULT)

#' Map year -> raster path, for every irrigation map in the folder.
irrigation_map_files <- function() {
  d <- irrigation_dir()
  if (!dir.exists(d)) return(character(0))
  f <- list.files(d)
  f <- f[grepl(IRRIGATION_NAME_RE, f, ignore.case = TRUE)]
  if (!length(f)) return(character(0))
  yrs <- 2000L + as.integer(sub(IRRIGATION_NAME_RE, "\\1", f, ignore.case = TRUE))
  out <- stats::setNames(file.path(d, f), yrs)
  out[order(yrs)]
}

#' Share (%) of the field's pixels mapped irrigated, and the pixel count.
#'
#' Pixels count when their centre is inside the boundary, as in the Python
#' port; a field smaller than a pixel takes the pixel under its centroid.
irrigated_pct <- function(aoi, path) {
  r <- terra::rast(path)
  v <- terra::vect(sf::st_transform(sf::st_union(sf::st_geometry(aoi)), terra::crs(r)))
  vals <- terra::extract(r, v, ID = FALSE)[[1]]
  if (!length(vals)) vals <- terra::extract(r, terra::centroids(v), ID = FALSE)[[1]]
  vals[is.na(vals)] <- 0
  n <- length(vals)
  c(pct = if (n) 100 * sum(vals == 1) / n else NA_real_, n = n)
}

irrigation_label <- function(pct) {
  if (is.null(pct) || is.na(pct)) return(NA_character_)
  if (pct >= IRRIGATED_PCT) "irrigated" else if (pct >= PARTLY_PCT) "partly irrigated"
  else "not irrigated"
}

#' Irrigated share of the field in every available map year (cached).
irrigation_history <- function(aoi) {
  files <- irrigation_map_files()
  if (!length(files)) return(NULL)
  key <- cache_key(aoi, "irrigation_v1", names(files))
  hit <- cache_get(key, "irrig")
  if (!is.null(hit)) return(hit)
  rows <- lapply(names(files), function(y) {
    x <- irrigated_pct(aoi, files[[y]])
    data.frame(map_year = as.integer(y), irrigated_pct = round(x[["pct"]], 1),
               irrigated = irrigation_label(x[["pct"]]), n_pixels = as.integer(x[["n"]]),
               resolution_m = if (as.integer(y) < 2012) 50L else 30L,
               stringsAsFactors = FALSE)
  })
  cache_put(key, do.call(rbind, rows), "irrig")
}

#' Irrigation columns on the CDL rotation table, one map per CDL year.
#'
#' Each year gets the nearest map at or before it: irrigated, irrigated_pct and
#' irrigation_map (the map year it came from), plus irrigated_maps, e.g.
#' "3 of 4": how many maps, of all years, show the field irrigated.
irrigation_add_to_history <- function(history, irr) {
  if (is.null(history) || is.null(irr) || !nrow(irr)) return(history)
  pick <- vapply(history$year, function(y) {
    prior <- irr$map_year[irr$map_year <= y]
    if (length(prior)) max(prior) else NA_integer_
  }, integer(1))
  i <- match(pick, irr$map_year)
  history$irrigated      <- irr$irrigated[i]
  history$irrigated_pct  <- irr$irrigated_pct[i]
  history$irrigation_map <- pick
  history$irrigated_maps <- sprintf("%d of %d", sum(irr$irrigated_pct >= IRRIGATED_PCT),
                                    nrow(irr))
  history
}
