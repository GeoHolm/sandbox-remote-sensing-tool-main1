# ==============================================================================
# cache.R -- Disk cache for extraction results
#
# A six-year NDVI history over one field means several hundred HTTP reads. That
# is fine to wait for once and intolerable to wait for twice, so every
# expensive result is keyed on the field geometry plus the query and written to
# cache/ as an RDS.
#
# The key includes the geometry itself, so editing a boundary invalidates it
# correctly while re-uploading the same file does not.
# ==============================================================================

# Overwritten by pipeline.R with a path anchored to that file's directory, so
# the cache does not follow the working directory around. Kept relative here
# only so this module still works if sourced on its own.
CACHE_DIR <- "cache"

#' Stable key for a field + query combination.
#'
#' Coordinates are rounded to ~1 m before hashing so that trivial float noise
#' from a re-export of the same boundary still hits the same cache entry, while
#' a genuinely edited boundary gets a new one.
cache_key <- function(aoi, ...) {
  geom <- sf::st_geometry(sf::st_transform(sf::st_union(aoi), 5070))
  crd  <- round(sf::st_coordinates(geom)[, 1:2], 0)
  substr(digest::digest(list(coords = crd, args = list(...)), algo = "xxhash64"), 1, 16)
}

#' The analysis window for a year range.
#'
#' The end date is floored to the first of the current month rather than being
#' "today". Cache keys include the window, so an end date of today would produce
#' a new key every day: a demo library warmed on Monday would be cold on
#' Tuesday and quietly re-read several hundred scenes per field.
#'
#' The cost is that the current month's imagery is excluded. Against a six-year
#' series whose final season is incomplete anyway, that changes nothing material,
#' and it makes a pre-warmed library reliable for the rest of the month. Re-warm
#' monthly to pull the window forward.
analysis_window <- function(year_from, year_to) {
  month_start <- as.Date(format(Sys.Date(), "%Y-%m-01"))
  list(
    start = sprintf("%d-01-01", year_from),
    end   = as.character(min(month_start, as.Date(sprintf("%d-12-31", year_to))))
  )
}

cache_path <- function(key, tag = "obj") {
  if (!dir.exists(CACHE_DIR)) dir.create(CACHE_DIR, recursive = TRUE)
  file.path(CACHE_DIR, sprintf("%s_%s.rds", tag, key))
}

#' Read a cached value, or NULL if absent.
cache_get <- function(key, tag = "obj") {
  p <- cache_path(key, tag)
  if (!file.exists(p)) return(NULL)
  tryCatch(readRDS(p), error = function(e) NULL)
}

cache_put <- function(key, value, tag = "obj") {
  saveRDS(value, cache_path(key, tag))
  invisible(value)
}

#' Run `fn()` unless a cached result exists.
#'
#' @param refresh Force recomputation and overwrite the cache entry.
cached <- function(key, fn, tag = "obj", refresh = FALSE) {
  if (!refresh) {
    hit <- cache_get(key, tag)
    if (!is.null(hit)) {
      message("  (cached)")
      return(hit)
    }
  }
  val <- fn()
  cache_put(key, val, tag)
  val
}

#' What is in the cache right now.
cache_list <- function() {
  if (!dir.exists(CACHE_DIR)) return(data.frame())
  f <- list.files(CACHE_DIR, pattern = "\\.rds$", full.names = TRUE)
  if (!length(f)) return(data.frame())
  data.frame(
    file     = basename(f),
    size_kb  = round(file.size(f) / 1024, 1),
    modified = file.mtime(f),
    row.names = NULL
  )
}

cache_clear <- function() {
  if (dir.exists(CACHE_DIR)) unlink(list.files(CACHE_DIR, full.names = TRUE))
  message("Cache cleared.")
}
