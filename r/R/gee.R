# ==============================================================================
# gee.R -- OPTIONAL Google Earth Engine backend
#
# The rest of this pipeline needs no account and reads imagery directly from
# cloud storage. That is the right tool for field-scale work and you may never
# need this file.
#
# Earth Engine earns its keep when you outgrow that:
#   - hundreds or thousands of fields at once
#   - state or national scale summaries
#   - long archives (Landsat back to 1984)
#   - heavy compositing (annual cloud-free mosaics, harmonic fits)
# because the computation happens on Google's servers and only the answer
# comes back.
#
# Cost: free for noncommercial use, which includes registered nonprofits.
# Registration is per Google Cloud project and approval is not instant.
#
# NOTE: unlike the rest of this repo, the functions below have not been run
# end-to-end here, because doing so needs your own Earth Engine account.
# Treat them as a tested-shape starting point, not verified code.
# ==============================================================================

#' One-time Earth Engine setup. Read the output; it is a checklist, not a script.
gee_setup <- function() {
  cat("
Earth Engine setup, in order:

 1. Register for noncommercial access (free for nonprofits):
      https://code.earthengine.google.com/register
    Choose 'Unpaid usage' -> 'Nonprofit'. You will attach it to a Google Cloud
    project; create one if you have none. Note the PROJECT ID, not the name.

 2. Approval takes anywhere from minutes to a few days. Wait for the email.

 3. Install the R package and its Python side:
      install.packages('rgee')
      rgee::ee_install()            # builds a Python env with earthengine-api
    Restart R afterwards.

 4. Authenticate and initialise once:
      rgee::ee_Initialize(project = 'your-project-id', drive = TRUE)
    A browser window will ask you to sign in and paste back a token.

 5. Check it took:
      gee_check()

If ee_install() fights you on Windows, the usual fix is to point reticulate at
a clean Python first:
      reticulate::install_miniconda()
      rgee::ee_install()
")
  invisible(NULL)
}

#' Is Earth Engine usable in this session?
gee_check <- function() {
  if (!requireNamespace("rgee", quietly = TRUE)) {
    message("rgee is not installed. Run gee_setup() for the checklist.")
    return(invisible(FALSE))
  }
  ok <- tryCatch({
    n <- rgee::ee$Number(1)$getInfo()
    identical(n, 1L) || identical(n, 1)
  }, error = function(e) {
    message("rgee is installed but not initialised: ", conditionMessage(e))
    message("Run: rgee::ee_Initialize(project = 'your-project-id')")
    FALSE
  })
  if (isTRUE(ok)) message("Earth Engine is live.")
  invisible(ok)
}

# Fail early and clearly rather than deep inside a reticulate call.
gee_require <- function() {
  if (!requireNamespace("rgee", quietly = TRUE)) {
    stop("This function needs the 'rgee' package. Run gee_setup().", call. = FALSE)
  }
  invisible(TRUE)
}

#' Convert an sf field boundary to an Earth Engine geometry.
gee_geom <- function(aoi) {
  gee_require()
  rgee::sf_as_ee(sf::st_transform(sf::st_union(aoi), 4326))
}

#' Server-side index time series for one or many fields.
#'
#' The whole reduction runs on Google's side; what comes back is a small table.
#' This is the operation that makes Earth Engine worth the setup -- the same
#' query over 5,000 fields costs you no extra bandwidth.
#'
#' @param aoi       sf object, one or many polygons.
#' @param start,end "YYYY-MM-DD".
#' @param index     "ndvi", "evi2", "ndmi" or "gcvi".
#' @param max_cloud Scene-level cloud cutoff, percent.
#' @param scale     Reduction scale in metres; 10 is Sentinel-2 native.
#' @return Data frame of date and mean index per feature.
gee_index_timeseries <- function(aoi, start, end, index = "ndvi",
                                 max_cloud = 60, scale = 10) {
  gee_require()
  ee <- rgee::ee
  geom <- gee_geom(aoi)

  # S2_SR_HARMONIZED already undoes the 2022 reflectance offset shift, so
  # values are comparable across the whole archive without extra handling.
  coll <- ee$ImageCollection("COPERNICUS/S2_SR_HARMONIZED")$
    filterBounds(geom)$
    filterDate(start, end)$
    filter(ee$Filter$lt("CLOUDY_PIXEL_PERCENTAGE", max_cloud))

  mask_scl <- function(img) {
    scl <- img$select("SCL")
    keep <- scl$eq(4)$Or(scl$eq(5))$Or(scl$eq(6))$Or(scl$eq(7))
    img$updateMask(keep)$divide(10000)$copyProperties(img, list("system:time_start"))
  }

  band_of <- list(
    ndvi = c("B8", "B4"), evi2 = c("B8", "B4"),
    ndmi = c("B8", "B11"), gcvi = c("B8", "B3")
  )
  if (!index %in% names(band_of)) {
    stop("gee_index_timeseries() supports: ", paste(names(band_of), collapse = ", "),
         call. = FALSE)
  }
  bs <- band_of[[index]]

  add_index <- function(img) {
    v <- switch(index,
      ndvi = img$normalizedDifference(bs),
      ndmi = img$normalizedDifference(bs),
      evi2 = img$expression("2.5*(N-R)/(N+2.4*R+1)",
               list(N = img$select(bs[1]), R = img$select(bs[2]))),
      gcvi = img$select(bs[1])$divide(img$select(bs[2]))$subtract(1)
    )
    img$addBands(v$rename(index))
  }

  coll <- coll$map(mask_scl)$map(add_index)$select(index)

  reduce_one <- function(img) {
    stats <- img$reduceRegions(
      collection = geom,
      reducer    = ee$Reducer$mean(),
      scale      = scale
    )
    stats$map(function(f) f$set("date", img$date()$format("YYYY-MM-dd")))
  }

  fc <- ee$FeatureCollection(coll$map(reduce_one))$flatten()
  out <- rgee::ee_as_sf(fc, maxFeatures = 20000)

  out <- sf::st_drop_geometry(out)
  names(out)[names(out) == "mean"] <- index
  out <- out[!is.na(out[[index]]), ]
  out$date <- as.Date(out$date)
  out[order(out$date), ]
}

#' USDA CDL crop type for a field, via Earth Engine.
#' The local get_cdl() in R/cropland.R does the same thing without an account;
#' use this one when you are already inside an Earth Engine workflow.
gee_cdl <- function(aoi, year) {
  gee_require()
  ee <- rgee::ee
  img <- ee$ImageCollection("USDA/NASS/CDL")$
    filterDate(sprintf("%d-01-01", year), sprintf("%d-12-31", year))$
    first()$
    select("cropland")

  fc <- img$reduceRegions(
    collection = gee_geom(aoi),
    reducer    = ee$Reducer$mode(),
    scale      = 30
  )
  out <- sf::st_drop_geometry(rgee::ee_as_sf(fc))
  out$crop <- cdl_name(as.integer(out$mode))
  out
}
