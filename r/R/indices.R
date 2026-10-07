# ==============================================================================
# indices.R -- Spectral indices
#
# This is the "try a different algorithm" surface. Every index is just a
# function of a named list of reflectance bands. To add your own, call
# add_index() -- nothing else in the pipeline needs to change.
# ==============================================================================

#' Registry of indices. Each entry: fn, bands it needs, plotting range, blurb.
INDICES <- new.env(parent = emptyenv())

#' Register a spectral index.
#'
#' @param name  Short name, e.g. "ndvi".
#' @param fn    Function of one argument `b`, a named list of SpatRasters.
#' @param bands Character vector of band names the function needs.
#' @param range Plotting range, c(min, max).
#' @param desc  One-line description.
add_index <- function(name, fn, bands, range = c(-1, 1), desc = "") {
  assign(name, list(fn = fn, bands = bands, range = range, desc = desc),
         envir = INDICES)
  invisible(name)
}

#' Data frame of every registered index.
list_indices <- function() {
  nm <- sort(ls(INDICES))
  data.frame(
    index = nm,
    bands = vapply(nm, function(n) paste(get(n, INDICES)$bands, collapse = ", "),
                   character(1)),
    desc  = vapply(nm, function(n) get(n, INDICES)$desc, character(1)),
    row.names = NULL, stringsAsFactors = FALSE
  )
}

#' Which bands do these indices need between them?
#' Feed the result to load_scene(bands = ...) so you fetch each band once.
bands_for <- function(indices) {
  unknown <- setdiff(indices, ls(INDICES))
  if (length(unknown)) {
    stop("Unknown index/indices: ", paste(unknown, collapse = ", "),
         "\n  Registered: ", paste(sort(ls(INDICES)), collapse = ", "), call. = FALSE)
  }
  unique(unlist(lapply(indices, function(n) get(n, INDICES)$bands)))
}

#' Compute an index from a loaded scene.
#'
#' @param img   SpatRaster from load_scene(), values as reflectance.
#' @param index Name of a registered index.
#' @return Single-layer SpatRaster named after the index.
compute_index <- function(img, index = "ndvi") {
  if (!exists(index, envir = INDICES, inherits = FALSE)) {
    stop("Unknown index: ", index,
         "\n  Registered: ", paste(sort(ls(INDICES)), collapse = ", "), call. = FALSE)
  }
  spec <- get(index, INDICES)

  missing_bands <- setdiff(spec$bands, names(img))
  if (length(missing_bands)) {
    stop(sprintf("Index '%s' needs band(s) not loaded: %s\n  Scene has: %s",
                 index, paste(missing_bands, collapse = ", "),
                 paste(names(img), collapse = ", ")), call. = FALSE)
  }

  b <- stats::setNames(lapply(spec$bands, function(n) img[[n]]), spec$bands)
  out <- spec$fn(b)
  names(out) <- index
  attr(out, "date")     <- attr(img, "date")
  attr(out, "scene_id") <- attr(img, "scene_id")
  attr(out, "n_field")  <- attr(img, "n_field")
  attr(out, "range")    <- spec$range
  out
}

# --------------------------------------------------------- built-in indices ---

add_index(
  "ndvi", function(b) (b$nir - b$red) / (b$nir + b$red),
  bands = c("nir", "red"), range = c(-0.2, 1),
  desc = "Normalised Difference Vegetation Index. The workhorse. Saturates over dense canopy."
)

add_index(
  "evi2", function(b) 2.5 * (b$nir - b$red) / (b$nir + 2.4 * b$red + 1),
  bands = c("nir", "red"), range = c(-0.2, 1.2),
  desc = "Two-band EVI. Keeps responding after NDVI saturates; no blue band needed."
)

add_index(
  "ndwi", function(b) (b$green - b$nir) / (b$green + b$nir),
  bands = c("green", "nir"), range = c(-1, 1),
  desc = "McFeeters NDWI. Surface water; positive over open water."
)

add_index(
  "ndmi", function(b) (b$nir - b$swir16) / (b$nir + b$swir16),
  bands = c("nir", "swir16"), range = c(-1, 1),
  desc = "Normalised Difference Moisture Index. Canopy water content / drought stress."
)

# --- residue and tillage -----------------------------------------------------
# These three are the multispectral indices evaluated in Sonmez & Slater (2016).
# They are registered because the bands are already fetched and the arithmetic
# is trivial -- not because any of them is calibrated here. Two things to know
# before building on them:
#
#   1. Soil moisture moves NDTI more than tillage does. On the Iowa field,
#      18 and 20 May 2024 gave NDTI 0.035 and 0.138 with NDVI flat at 0.18 --
#      a four-fold swing from rain, with no change in residue. Single-date
#      NDTI is not usable; the validated approach is multitemporal (minNDTI
#      over the residue window, Zheng et al. 2013).
#   2. None of them separates residue from green vegetation. NDTI reads high
#      over a cover crop because green canopy absorbs in the SWIR. Restrict to
#      dates with low NDVI, which is what residue_window() in phenology.R is
#      for.
#
# The hyperspectral index the paper found best, CAI, cannot be computed from
# Sentinel-2: it needs three narrow bands inside the 2000-2200 nm cellulose
# feature, and B12 is one 180 nm-wide band covering the whole of it.

add_index(
  "ndti", function(b) (b$swir16 - b$swir22) / (b$swir16 + b$swir22),
  bands = c("swir16", "swir22"), range = c(-0.2, 0.6),
  desc = "Normalised Difference Tillage Index. Crop residue cover -- relevant to conservation tillage."
)

add_index(
  "ndi7", function(b) (b$nir - b$swir22) / (b$nir + b$swir22),
  bands = c("nir", "swir22"), range = c(-1, 1),
  desc = "Normalised Difference Index 7. Residue against bare soil; reported alongside NDTI."
)

add_index(
  "ndsvi", function(b) (b$swir16 - b$red) / (b$swir16 + b$red),
  bands = c("swir16", "red"), range = c(-1, 1),
  desc = "Normalised Difference Senescent Vegetation Index. Standing senesced material."
)

add_index(
  "ndre", function(b) (b$nir - b$rededge1) / (b$nir + b$rededge1),
  bands = c("nir", "rededge1"), range = c(-0.2, 1),
  desc = "Normalised Difference Red Edge. More sensitive than NDVI in dense mid-season canopy."
)

add_index(
  "savi", function(b) 1.5 * (b$nir - b$red) / (b$nir + b$red + 0.5),
  bands = c("nir", "red"), range = c(-0.2, 1.2),
  desc = "Soil Adjusted Vegetation Index (L=0.5). Damps soil background at low cover."
)

add_index(
  "gcvi", function(b) (b$nir / b$green) - 1,
  bands = c("nir", "green"), range = c(0, 12),
  desc = "Green Chlorophyll Vegetation Index. Tracks leaf chlorophyll; used in yield models."
)

# ----------------------------------------------------------------------------
# Adding your own looks like this:
#
#   add_index("my_index",
#     fn    = function(b) (b$nir - b$swir22) / (b$nir + b$swir22),
#     bands = c("nir", "swir22"),
#     range = c(-1, 1),
#     desc  = "Something I want to test")
#
# Then it works everywhere: compute_index(img, "my_index"),
# index_timeseries(scenes, index = "my_index"), and so on.
# ----------------------------------------------------------------------------
