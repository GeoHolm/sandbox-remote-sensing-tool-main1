# ==============================================================================
# thumbnails.R -- Contact sheets: every scene in a period, side by side
#
# Picking one scene at a time from a list of several hundred is no way to look
# at imagery. A month or a quarter rendered as a grid shows the field changing,
# and shows at a glance which dates were actually usable.
#
# Scenes are read in parallel and returned as plain numeric arrays rather than
# SpatRasters, because arrays cross process boundaries and terra objects do not.
# The whole grid is cached, so flipping back to a period you have already looked
# at is instant.
# ==============================================================================

#' Scene row numbers falling in a given period.
#'
#' @param period "month" or "quarter".
#' @param key    "2024-06" for a month, "2024-Q2" for a quarter.
scenes_in_period <- function(scenes, key, period = "month") {
  d <- scenes$table$date
  tag <- if (period == "quarter") {
    sprintf("%s-Q%d", format(d, "%Y"), (as.integer(format(d, "%m")) - 1) %/% 3 + 1)
  } else {
    format(d, "%Y-%m")
  }
  hit <- scenes$table[tag == key, ]
  if (!nrow(hit)) return(integer(0))

  # Overlapping tiles put the same date in the table twice. On a contact sheet
  # that is just a confusing duplicate cell, so keep the clearer one.
  hit <- hit[order(hit$date, hit$cloud), ]
  hit$i[!duplicated(hit$date)]
}

#' Every period present in a scene table, newest first.
available_periods <- function(scenes, period = "month") {
  d <- scenes$table$date
  tag <- if (period == "quarter") {
    sprintf("%s-Q%d", format(d, "%Y"), (as.integer(format(d, "%m")) - 1) %/% 3 + 1)
  } else {
    format(d, "%Y-%m")
  }
  sort(unique(tag), decreasing = TRUE)
}

#' The cache key scene_grid() uses, and whether that entry exists.
#'
#' The app shows the user, before they press the button, whether a quarter is
#' already on disk. That promise is only worth making if it is computed from
#' the same key the read itself uses -- an indicator that says "instant" and
#' then takes a minute is worse than no indicator.
grid_cache_key <- function(aoi, ids, view, max_px = 180) {
  cache_key(aoi, ids, view, max_px, "grid_v1")
}

grid_cached <- function(aoi, ids, view, max_px = 180) {
  file.exists(cache_path(grid_cache_key(aoi, ids, view, max_px), "grid"))
}

#' Read a set of scenes as small arrays ready for a contact sheet.
#'
#' @param view    "rgb", "fc" (false colour) or "ndvi".
#' @param max_px  Longest edge of each thumbnail; scenes are aggregated down to
#'                this, which keeps a 30-scene quarter to a few MB.
#' @return List of per-scene entries with `arr`, `date`, `cloud`, `valid`.
scene_grid <- function(scenes, idx, view = "rgb", max_px = 180,
                       workers = 6, refresh = FALSE, progress = NULL) {

  if (!length(idx)) return(list())

  ids <- scenes$table$id[idx]
  key <- grid_cache_key(scenes$aoi, ids, view, max_px)
  hit <- if (refresh) NULL else cache_get(key, "grid")
  if (!is.null(hit)) return(hit)

  # An index view is evaluated from the registry rather than a hardcoded
  # switch, and the spec travels with the job: the worker sources imagery.R
  # only, so it cannot look INDICES up for itself.
  spec <- if (view %in% INDEX_VIEWS) {
    sp <- get(view, INDICES)
    f  <- sp$fn
    if (identical(environment(f), globalenv())) environment(f) <- baseenv()
    list(fn = f, bands = sp$bands)
  } else NULL
  bands <- if (!is.null(spec)) spec$bands else
    switch(view, fc = c("green", "red", "nir"), c("blue", "green", "red"))

  feats <- sign_subset(scenes, idx)
  jobs <- lapply(seq_along(idx), function(k) list(
    item  = feats[[k]],
    date  = scenes$table$date[idx[k]],
    cloud = scenes$table$cloud[idx[k]]
  ))

  root <- normalizePath(".", winslash = "/")
  use_parallel <- ensure_workers(min(workers, length(jobs)))

  chunk <- if (use_parallel) min(workers, length(jobs)) else 1L
  chunks <- split(seq_along(jobs), ceiling(seq_along(jobs) / chunk))
  res <- list()

  for (k in seq_along(chunks)) {
    part <- if (use_parallel) {
      furrr::future_map(jobs[chunks[[k]]], grid_one_scene,
                        aoi = scenes$aoi, view = view, max_px = max_px, root = root,
                        spec = spec, bands = bands,
                        .options = furrr::furrr_options(seed = TRUE))
    } else {
      lapply(jobs[chunks[[k]]], grid_one_scene,
             aoi = scenes$aoi, view = view, max_px = max_px, root = root,
             spec = spec, bands = bands)
    }
    res <- c(res, part)
    if (!is.null(progress)) {
      done <- max(chunks[[k]])
      progress(done, length(jobs), sprintf("Loading scene %d of %d", done, length(jobs)))
    }
  }

  res <- Filter(function(x) identical(x$status, "ok"), res)

  # An index view must produce a 2-D matrix and a colour view a 3-D array.
  # Getting this wrong is silent and self-perpetuating: "armor" was once
  # missing from INDEX_VIEWS, so every scene fell through to the RGB branch,
  # the sheet rendered reflectance, and the wrong arrays were cached under the
  # armor key -- where they then survived the fix and had to be hunted down by
  # hand. Refuse to cache a mismatch.
  if (length(res)) {
    nd <- length(dim(res[[1]]$arr))
    want <- if (view %in% INDEX_VIEWS) 2L else 3L
    if (!identical(as.integer(nd), want)) {
      stop(sprintf(paste0("view '%s' produced a %d-D array but %d-D was expected. ",
                          "If this is a new index view, add it to INDEX_VIEWS ",
                          "and give it an entry in view_scale()."),
                   view, nd, want), call. = FALSE)
    }
  }

  cache_put(key, res, "grid")
  res
}

# Worker: one scene -> one small array.
grid_one_scene <- function(job, aoi, view, max_px, root, spec = NULL, bands = NULL) {
  suppressPackageStartupMessages({ library(sf); library(terra) })
  if (!exists("scene_from_item", mode = "function")) {
    source(file.path(root, "R", "imagery.R"))
  }

  tryCatch({
    img <- scene_from_item(job$item, aoi, bands = bands,
                           mask_clouds = TRUE, clip = TRUE, buffer_m = 30)

    n_field <- attr(img, "n_field")
    vals    <- terra::values(img[[1]])
    valid   <- if (is.null(n_field) || n_field == 0) 0 else
                 min(1, sum(!is.na(vals)) / n_field)

    # Aggregate down before returning -- a contact sheet cell is ~180 px, so
    # shipping full resolution back would be wasted memory and cache.
    f <- ceiling(max(dim(img)[1:2]) / max_px)
    if (f > 1) img <- terra::aggregate(img, fact = f, fun = "mean", na.rm = TRUE)

    arr <- if (!is.null(spec)) {
      b <- stats::setNames(lapply(spec$bands, function(n) img[[n]]), spec$bands)
      terra::as.matrix(spec$fn(b), wide = TRUE)
    } else {
      ord <- if (view == "fc") c("nir", "red", "green") else c("red", "green", "blue")
      terra::as.array(img[[ord]])
    }

    list(status = "ok", date = job$date, cloud = job$cloud,
         valid = valid, arr = arr)
  }, error = function(e) {
    list(status = "error", date = job$date, msg = conditionMessage(e))
  })
}

# --------------------------------------------------------------- rendering ---

#' Fixed reflectance range for a contact sheet, by view.
#'
#' Deliberately fixed rather than fitted to the data. Both obvious adaptive
#' options are wrong here:
#'
#'   - Per-band percentiles equalise the channels. Soil reflects more red than
#'     blue, which is exactly why it looks brown; rescaling each band onto its
#'     own range cancels that and renders bare ground a washed-out mauve.
#'   - A single pooled percentile keeps the ratios but is set by whichever band
#'     is brightest, crushing blue and turning everything orange.
#'
#' A constant range applied identically to all three bands preserves the ratios
#' and keeps every cell on the same scale, so a date really is comparable with
#' the date beside it. 0-0.3 reflectance is the usual choice for Sentinel-2 true
#' colour; near-infrared runs brighter, so false colour gets more headroom.
grid_limits <- function(view = "rgb") {
  switch(view, fc = c(0, 0.45), c(0, 0.30))
}

array_to_raster <- function(arr, lim, gamma = 0.8) {
  ch <- lapply(1:3, function(k) {
    x <- (arr[, , k] - lim[1]) / (lim[2] - lim[1])
    x[x < 0] <- 0; x[x > 1] <- 1
    x^gamma
  })
  na <- is.na(ch[[1]]) | is.na(ch[[2]]) | is.na(ch[[3]])
  for (k in 1:3) ch[[k]][na] <- 0.92          # masked pixels read as pale grey
  out <- grDevices::rgb(ch[[1]], ch[[2]], ch[[3]])
  grDevices::as.raster(matrix(out, nrow = nrow(ch[[1]])))
}

#' Pale straw to dark brown. Deliberately not the NDVI ramp: that one ends in
#' teal, which reads as green canopy, and NDTI's high end means the opposite --
#' dry residue lying on the surface.
residue_palette <- function(n = 100) {
  grDevices::colorRampPalette(
    c("#f7f7f7", "#f6e8c3", "#d8b365", "#8c510a", "#543005")
  )(n)
}

#' Views that are a single index rather than three reflectance bands.
INDEX_VIEWS <- c("ndvi", "ndti", "armor")

#' Fixed colour scale per index view.
#'
#' Fixed, not per-scene: the whole point of a contact sheet is that two dates
#' are comparable, and a per-scene stretch makes a dry April look like a wet
#' one. NDTI gets a much tighter range than NDVI because that is the range it
#' actually occupies -- across this field library, bare ground sits between
#' about 0.00 and 0.20.
view_scale <- function(view) {
  switch(view,
    ndvi  = list(range = c(-0.2, 1.0), pal = veg_palette(100)),
    ndti  = list(range = c(0, 0.25),   pal = residue_palette(100)),
    # Brown to teal reads correctly without a legend: bare soil is brown,
    # covered ground is green, which is what the numbers mean.
    armor = list(range = c(0, 1),      pal = veg_palette(100)),
    NULL)
}

matrix_to_raster <- function(m, range = c(-0.2, 1), pal = veg_palette(100)) {
  i <- round((m - range[1]) / diff(range) * (length(pal) - 1)) + 1
  i[i < 1] <- 1; i[i > length(pal)] <- length(pal)
  out <- matrix(pal[i], nrow = nrow(m))
  out[is.na(m)] <- "#ececec"
  grDevices::as.raster(out)
}

#' Draw a contact sheet.
#'
#' @param g    Result of scene_grid().
#' @param view Same view it was built with.
plot_scene_grid <- function(g, view = "rgb", ncol = NULL, title = NULL) {
  if (!length(g)) {
    graphics::plot.new()
    graphics::title("No scenes in this period")
    return(invisible())
  }

  n  <- length(g)
  nc <- ncol %||% min(6, ceiling(sqrt(n) * 1.3))
  nr <- ceiling(n / nc)

  is_index <- view %in% INDEX_VIEWS
  lim <- if (!is_index) grid_limits(view) else NULL
  sc  <- if (is_index) view_scale(view) else NULL

  op <- graphics::par(mfrow = c(nr, nc), mar = c(1.6, 0.4, 1.8, 0.4),
                      oma = c(0, 0, if (is.null(title)) 0 else 2.4, 0))
  on.exit(graphics::par(op), add = TRUE)

  for (s in g) {
    ras <- if (is_index) matrix_to_raster(s$arr, sc$range, sc$pal)
           else array_to_raster(s$arr, lim)
    graphics::plot.new()
    graphics::plot.window(c(0, 1), c(0, 1), asp = 1)
    graphics::rasterImage(ras, 0, 0, 1, 1, interpolate = FALSE)
    graphics::box(col = "grey85")
    graphics::title(main = format(s$date, "%d %b"), cex.main = 0.95, line = 0.5)
    graphics::mtext(sprintf("%.0f%% clear  |  tile %.0f%% cloud",
                            s$valid * 100, s$cloud),
                    side = 1, line = 0.4, cex = 0.55, col = "grey35")
  }
  if (!is.null(title)) {
    graphics::mtext(title, outer = TRUE, cex = 1.05, font = 2, line = 0.6)
  }
  invisible(n)
}
