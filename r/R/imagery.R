# ==============================================================================
# imagery.R -- Find and load Sentinel-2 surface reflectance over a field
#
# Source: Microsoft Planetary Computer's STAC API. Sentinel-2 L2A there is free
# and needs no account. Imagery is read straight from cloud-optimised GeoTIFFs
# over HTTP, so only the pixels covering your field are ever transferred.
# ==============================================================================

PC_STAC <- "https://planetarycomputer.microsoft.com/api/stac/v1"

# How this client identifies itself to Planetary Computer.
#
# Until now it sent nothing, which makes it anonymous traffic indistinguishable
# from a scraper. Identified clients are the ones a service throttles last and
# contacts first, and the cost of saying who we are is zero. PC accepts
# X-PC-Request-Entity for exactly this -- it is in the CORS allow-list on their
# STAC API -- and GDAL sends the user agent on every COG range read, which is
# where nearly all the volume actually goes.
PC_CLIENT <- "field-to-market-remote-sensing/1.0 (+https://fieldtomarket.org)"

#' Announce this client to Planetary Computer, once per session.
#'
#' Called from pipeline.R at load. Safe to call repeatedly.
pc_identify <- function() {
  terra::setGDALconfig("GDAL_HTTP_USERAGENT", PC_CLIENT)
  # Read requests go out through GDAL; rstac's go through httr. Both need it.
  options(HTTPUserAgent = PC_CLIENT)
  invisible(PC_CLIENT)
}

# Friendly name -> Sentinel-2 asset key on Planetary Computer.
S2_BANDS <- c(
  coastal  = "B01", blue     = "B02", green    = "B03", red    = "B04",
  rededge1 = "B05", rededge2 = "B06", rededge3 = "B07",
  nir      = "B08", nir08    = "B8A", swir16   = "B11", swir22 = "B12",
  scl      = "SCL"
)

# Native ground sample distance, metres. Used to pick the reference grid.
S2_RES <- c(
  coastal = 60, blue = 10, green = 10, red = 10,
  rededge1 = 20, rededge2 = 20, rededge3 = 20,
  nir = 10, nir08 = 20, swir16 = 20, swir22 = 20, scl = 20
)

# Scene Classification Layer classes worth keeping. 4 = vegetation,
# 5 = bare soil, 6 = water, 7 = unclassified. Everything else is cloud,
# cloud shadow, cirrus, snow or sensor noise.
SCL_KEEP_DEFAULT <- c(4, 5, 6, 7)

SCL_LABELS <- c(
  "0" = "no data", "1" = "saturated/defective", "2" = "dark area",
  "3" = "cloud shadow", "4" = "vegetation", "5" = "bare soil",
  "6" = "water", "7" = "unclassified", "8" = "cloud medium prob",
  "9" = "cloud high prob", "10" = "thin cirrus", "11" = "snow/ice"
)

`%||%` <- function(a, b) if (is.null(a)) b else a

# ------------------------------------------------------------------ search ---

#' The cache key search_scenes() uses for a given query.
#'
#' Exposed so a caller can ask whether a catalogue is already on disk without
#' running the search. Sharing one key function is what stops the question and
#' the answer drifting apart.
scenes_cache_key <- function(aoi, start, end, max_cloud = 60, limit = 500) {
  cache_key(aoi, start, end, max_cloud, limit, "catalog_scenes_v1")
}

#' Search Sentinel-2 scenes covering a field.
#'
#' @param aoi       sf object from load_field().
#' @param start,end Date strings, "YYYY-MM-DD".
#' @param max_cloud Scene-level cloud cover cutoff, percent. This is cloud over
#'                  the whole 110 km tile, not over your field -- a 60 percent
#'                  cloudy scene can still be perfectly clear above one field,
#'                  so do not set this too tight.
#' @return A `s2_scenes` object: `$table` for the scene list, plus the internals
#'         that load_scene() needs.
# How often the catalogue is asked again before giving up, and how long to wait
# between attempts.
#
# Planetary Computer's STAC endpoint rate-limits, and when it does it answers
# with an HTML error page rather than JSON. rstac then fails with "HTTP content
# type response 'text/html' not defined for this operation", which says nothing
# about what happened or what to do about it. Left unguarded, one such reply
# killed a six-year soil armor run that had already read three years -- the
# request that failed was the fourth in quick succession, which is exactly when
# a throttle fires.
STAC_TRIES   <- 4L
STAC_BACKOFF <- c(2, 6, 15)     # seconds before attempts 2, 3 and 4

#' Ask the STAC catalogue, retrying transient failures.
#'
#' The search is a read, so repeating it is safe. Anything already extracted is
#' cached per year, so even a final failure loses only the year in flight.
stac_search_retry <- function(bbox, start, end, limit) {
  for (i in seq_len(STAC_TRIES)) {
    res <- tryCatch(
      rstac::stac(PC_STAC) |>
        rstac::stac_search(
          collections = "sentinel-2-l2a",
          bbox        = bbox,
          datetime    = paste0(start, "T00:00:00Z/", end, "T23:59:59Z"),
          limit       = min(limit, 500)
        ) |>
        rstac::post_request() |>
        rstac::items_fetch(),
      error = function(e) e)

    if (!inherits(res, "error")) return(res)

    msg <- sub("
.*", "", conditionMessage(res))
    if (i == STAC_TRIES) {
      stop("The Sentinel-2 catalogue did not answer after ", STAC_TRIES,
           " attempts.
  Last error: ", msg,
           "
  A reply in HTML rather than data means Planetary Computer ",
           "rate-limited the request or is down. It is not a problem with this ",
           "field.
  Everything already read is cached, so running again ",
           "resumes rather than starting over.", call. = FALSE)
    }
    # Their own Retry-After wins over our guess when they send one: a service
    # under load knows better than a hard-coded schedule, and ignoring it is
    # how a polite retry turns into hammering.
    wait <- STAC_BACKOFF[min(i, length(STAC_BACKOFF))]
    hinted <- suppressWarnings(as.numeric(
      sub(".*[Rr]etry-?[Aa]fter[^0-9]*([0-9]+).*", "\1",
          conditionMessage(res))))
    if (!is.na(hinted) && hinted > 0 && hinted <= 120) wait <- hinted
    # %g, not %d: STAC_BACKOFF holds doubles, and sprintf("%d", 2) is an error
    # in R, not a coercion. With %d the retry path fell over on its own logging
    # the first time it was needed -- a handler that breaks exactly when it is
    # reached is worse than none.
    message(sprintf("  Catalogue request failed (%s). Retrying in %gs (%d of %d)...",
                    msg, wait, i + 1L, STAC_TRIES))
    Sys.sleep(wait)
  }
}

search_scenes <- function(aoi, start, end, max_cloud = 60, limit = 500,
                          refresh = FALSE) {

  # Cached to disk like every other network result. This was the one call in
  # the app that always went out to the network: the Imagery tab re-paged the
  # whole catalogue on every app restart, about 9 s and 1,179 scenes over a
  # six-year window, before it could read a single thumbnail.
  #
  # The key carries the literal end date rather than being floored to the
  # month the way analysis_window() does. That is deliberate and the trade is
  # the opposite way round here: a stale month would hide the newest
  # acquisitions from the one tab whose job is showing what was collected. At
  # day granularity a past-year range caches indefinitely and the current year
  # re-queries once a day, which still removes the cost from every restart.
  key <- scenes_cache_key(aoi, start, end, max_cloud, limit)
  hit <- if (refresh) NULL else cache_get(key, "scenes")
  if (!is.null(hit)) {
    message(sprintf("  Cached catalogue: %d scenes, %s to %s.",
                    nrow(hit$table), min(hit$table$date), max(hit$table$date)))
    # A fresh signing environment, never the cached one -- Planetary Computer
    # signatures last about an hour and these entries outlive that by weeks.
    return(structure(
      list(items = hit$items, table = hit$table, aoi = aoi,
           cache = new.env(parent = emptyenv())),
      class = "s2_scenes"
    ))
  }

  bbox <- field_bbox(aoi)

  message(sprintf("  Searching Sentinel-2, %s to %s...", start, end))
  items <- stac_search_retry(bbox, start, end, limit)

  n_found <- rstac::items_length(items)
  if (n_found == 0) {
    stop("No Sentinel-2 scenes found for that area and date range.\n",
         "  Sentinel-2 data starts 2015-06; coverage is best from 2017 onward.",
         call. = FALSE)
  }

  cloud <- vapply(items$features,
                  function(f) as.numeric(f$properties[["eo:cloud_cover"]] %||% NA_real_),
                  numeric(1))
  keep <- which(is.na(cloud) | cloud <= max_cloud)
  if (length(keep) == 0) {
    stop(sprintf("Found %d scenes but none under %.0f%% cloud. Raise max_cloud.",
                 n_found, max_cloud), call. = FALSE)
  }
  items$features <- items$features[keep]

  tbl <- data.frame(
    i     = seq_along(items$features),
    id    = vapply(items$features, function(f) f$id, character(1)),
    date  = as.Date(substr(vapply(items$features,
              function(f) f$properties[["datetime"]], character(1)), 1, 10)),
    cloud = round(cloud[keep], 1),
    epsg  = vapply(items$features,
              function(f) as.integer(f$properties[["proj:epsg"]] %||% NA_integer_), integer(1)),
    stringsAsFactors = FALSE
  )
  ord <- order(tbl$date)
  tbl <- tbl[ord, ]
  items$features <- items$features[ord]
  tbl$i <- seq_len(nrow(tbl))
  rownames(tbl) <- NULL

  message(sprintf("  Found %d scenes (%d under %.0f%% cloud), %s to %s.",
                  n_found, nrow(tbl), max_cloud, min(tbl$date), max(tbl$date)))

  cache_put(key, list(items = items, table = tbl), "scenes")

  structure(
    list(items = items, table = tbl, aoi = aoi,
         cache = new.env(parent = emptyenv())),
    class = "s2_scenes"
  )
}

print.s2_scenes <- function(x, ...) {
  cat(sprintf("<s2_scenes> %d scenes over %.1f ha\n",
              nrow(x$table), sum(x$aoi$area_ha)))
  print(utils::head(x$table, 20))
  if (nrow(x$table) > 20) cat(sprintf("... and %d more\n", nrow(x$table) - 20))
  invisible(x)
}

# Planetary Computer asset URLs are signed and the signature expires after about
# an hour. Re-sign lazily so long time-series loops do not die halfway through.
sign_scenes <- function(scenes) {
  age <- if (is.null(scenes$cache$signed_at)) Inf else
    as.numeric(difftime(Sys.time(), scenes$cache$signed_at, units = "mins"))
  if (age > 30) return(sign_scenes_force(scenes))
  scenes$cache$signed
}

#' Drop same-date duplicate scenes before anything is read.
#'
#' Sentinel-2 tiles overlap, and adjacent orbits revisit on the same day, so one
#' calendar date can appear in the catalogue several times. A field sitting near
#' a tile corner is the bad case: one 15 ha field in Clinton County, Iowa
#' returned 4,682 scenes for 366 distinct dates.
#'
#' The extraction already removed duplicates, but only after reading them --
#' four times more imagery fetched than kept, and a 20 minute wait instead of
#' five. Choosing up front costs one metadata comparison.
#'
#' Preference order per date: a footprint that fully covers the field beats one
#' that clips it (a partly-covering scene would be discarded later for too few
#' valid pixels, losing the date entirely), then lowest scene cloud.
scene_groups <- function(scenes) {
  tbl <- scenes$table

  covers <- tryCatch({
    fp   <- rstac::items_as_sfc(scenes$items)
    poly <- sf::st_union(sf::st_transform(scenes$aoi, 4326))
    lengths(sf::st_covers(fp, poly)) > 0
  }, error = function(e) rep(NA, nrow(tbl)))
  if (length(covers) != nrow(tbl)) covers <- rep(NA, nrow(tbl))

  ord  <- order(tbl$date, -as.integer(covers %in% TRUE), tbl$cloud)
  tbl2 <- tbl[ord, ]
  groups <- split(tbl2$i, as.character(tbl2$date))
  groups <- groups[order(as.Date(names(groups)))]

  n_extra <- nrow(tbl) - length(groups)
  if (n_extra > 0) {
    message(sprintf(
      "  %d duplicate same-date scenes deferred (used only if the preferred one has no data).",
      n_extra))
  }
  groups
}

#' Best single scene per date. Kept for callers that want one row per date.
dedupe_scenes <- function(scenes) {
  keep <- vapply(scene_groups(scenes), `[`, integer(1), 1L)
  keep <- sort(unname(keep))
  scenes$items$features <- scenes$items$features[keep]
  tbl <- scenes$table[keep, ]
  tbl$i <- seq_len(nrow(tbl))
  rownames(tbl) <- NULL
  scenes$table <- tbl
  scenes$cache$signed_at <- NULL   # signatures were built for the old ordering
  scenes
}

#' Re-sign now, regardless of age. Long extractions call this to stay ahead of
#' the expiry rather than discovering it as a wall of failed reads.
#' Sign just the scenes that are about to be read.
#'
#' items_sign() rewrites every asset href on every feature it is given. Over a
#' six-year catalogue that is 823 features and about 23 s -- more than the
#' actual imagery read it precedes. A contact sheet only ever touches one
#' quarter, so signing the whole catalogue to look at 16 scenes was the largest
#' single cost in the Imagery tab.
#'
#' Signatures last about an hour and this slice is read immediately, so unlike
#' sign_scenes() there is nothing worth holding in the session cache.
#'
#' @param idx Row numbers into scenes$table.
#' @return The signed features, in the order given.
sign_subset <- function(scenes, idx) {
  sub <- scenes$items
  sub$features <- sub$features[idx]
  rstac::items_sign(sub, sign_fn = rstac::sign_planetary_computer())$features
}

sign_scenes_force <- function(scenes) {
  scenes$cache$signed <- rstac::items_sign(
    scenes$items, sign_fn = rstac::sign_planetary_computer()
  )
  scenes$cache$signed_at <- Sys.time()
  scenes$cache$signed
}

# -------------------------------------------------------------------- load ---

#' Load one scene, clipped to the field, as surface reflectance.
#'
#' @param scenes      Result of search_scenes().
#' @param i           Row number from `scenes$table`.
#' @param bands       Friendly band names, e.g. c("blue","green","red","nir").
#' @param mask_clouds Set cloud/shadow pixels to NA using the SCL band.
#' @param clip        Mask to the exact field polygon (FALSE keeps the bbox,
#'                    which is useful for seeing the field in its surroundings).
#' @param buffer_m    Extra margin around the field, metres.
#' @return A SpatRaster with one named layer per band, values as reflectance
#'         (0-1), plus `date` and `scene_id` attributes.
load_scene <- function(scenes, i = 1, bands = c("blue", "green", "red", "nir"),
                       mask_clouds = TRUE, clip = TRUE, buffer_m = 100,
                       scl_keep = SCL_KEEP_DEFAULT) {

  if (i < 1 || i > nrow(scenes$table)) {
    stop("i must be between 1 and ", nrow(scenes$table), call. = FALSE)
  }

  signed <- sign_scenes(scenes)
  img <- scene_from_item(signed$features[[i]], scenes$aoi, bands,
                         mask_clouds, clip, buffer_m, scl_keep)

  attr(img, "date")     <- scenes$table$date[i]
  attr(img, "scene_id") <- scenes$table$id[i]
  img
}

#' Build a scene raster from a signed STAC item.
#'
#' Split out from load_scene() so that parallel workers can call exactly the
#' same code path -- a STAC item is a plain list and crosses process boundaries
#' fine, whereas an s2_scenes object carries an environment that does not.
scene_from_item <- function(item, aoi, bands = c("blue", "green", "red", "nir"),
                            mask_clouds = TRUE, clip = TRUE, buffer_m = 100,
                            scl_keep = SCL_KEEP_DEFAULT) {

  unknown <- setdiff(bands, names(S2_BANDS))
  if (length(unknown)) {
    stop("Unknown band(s): ", paste(unknown, collapse = ", "),
         "\n  Available: ", paste(names(S2_BANDS), collapse = ", "), call. = FALSE)
  }

  needed <- unique(c(bands, if (mask_clouds) "scl"))

  # Read the finest-resolution band first; it defines the output grid.
  ref_band <- needed[which.min(S2_RES[needed])]
  ref <- read_band(item, ref_band, aoi, buffer_m)

  layers <- list()
  layers[[ref_band]] <- ref
  for (b in setdiff(needed, ref_band)) {
    r <- read_band(item, b, aoi, buffer_m)
    # Coarser bands (20 m SWIR, SCL) get resampled onto the 10 m grid. SCL is
    # categorical, so it must use nearest neighbour -- never interpolate classes.
    method <- if (b == "scl") "near" else "bilinear"
    layers[[b]] <- terra::resample(r, ref, method = method)
  }

  img <- terra::rast(layers)
  names(img) <- c(ref_band, setdiff(needed, ref_band))

  # Digital numbers -> surface reflectance. From processing baseline 04.00
  # (Jan 2022) ESA added a -1000 offset to the stored values; skipping this
  # shifts NDVI by a few hundredths, which is enough to matter.
  offset <- boa_offset(item)
  refl_bands <- setdiff(names(img), "scl")

  out <- list()
  for (b in refl_bands) out[[b]] <- (img[[b]] + offset) / 10000

  if (mask_clouds) {
    valid <- terra::app(img[["scl"]], function(v) ifelse(v %in% scl_keep, 1, NA))
    for (b in refl_bands) out[[b]] <- terra::mask(out[[b]], valid)
  }
  if ("scl" %in% bands) out[["scl"]] <- img[["scl"]]

  res <- terra::rast(out)
  names(res) <- names(out)

  if (clip) {
    poly <- terra::project(terra::vect(sf::st_union(aoi)), terra::crs(res))
    res  <- terra::crop(res, terra::ext(poly), snap = "out")
    # Rasterise the polygon separately so we know how many pixels the field has
    # regardless of cloud. Without this, "percent clear" would be measured
    # against the bounding box and would never reach 100% on a non-square field.
    footprint <- terra::rasterize(poly, res[[1]], field = 1)
    res       <- terra::mask(res, footprint)
    n_field   <- sum(!is.na(terra::values(footprint)))
  } else {
    n_field <- terra::ncell(res)
  }

  res <- res[[bands]]
  attr(res, "n_field") <- n_field
  res
}

# Read one band over the field's window only. The /vsicurl driver reads the
# relevant COG tiles over HTTP rather than the whole 110 km scene.
read_band <- function(item, band, aoi, buffer_m) {
  href <- item$assets[[ S2_BANDS[[band]] ]]$href
  if (is.null(href)) stop("Band not present in scene: ", band, call. = FALSE)

  r   <- terra::rast(paste0("/vsicurl/", href))
  win <- terra::project(terra::vect(sf::st_union(aoi)), terra::crs(r))
  win <- terra::buffer(win, buffer_m)
  terra::crop(r, terra::ext(win), snap = "out")
}

# Bottom-of-atmosphere additive offset for the scene's processing baseline.
boa_offset <- function(item) {
  bl <- suppressWarnings(as.numeric(item$properties[["s2:processing_baseline"]]))
  if (is.na(bl)) return(0)
  if (bl >= 4) -1000 else 0
}

#' Fraction of field pixels that survived cloud masking, 0-1.
#'
#' Measured against the field footprint, not the bounding box, so a completely
#' clear scene reads 1.0 whatever shape the field is. Use it to throw away
#' scenes where the field itself was under cloud -- the scene-level cloud
#' percentage from the catalogue covers a whole 110 km tile and says little
#' about any one field.
valid_fraction <- function(img) {
  v     <- terra::values(img[[1]])
  denom <- attr(img, "n_field") %||% length(v)
  if (is.null(denom) || denom == 0) return(0)
  min(1, sum(!is.na(v)) / denom)
}
