# ==============================================================================
# catalog.R -- What data exists for this field, and when
#
# Metadata only: these are catalogue queries, not pixel reads, so the whole
# 2020-to-present sweep across every source takes seconds. That makes it a good
# opening view -- it answers "how much do we actually have to work with for a
# given field" before anyone waits on an extraction.
# ==============================================================================

#' The sources queried for the availability timeline.
#'
#' All are free and open, and none needs an account. Ordered coarse-to-fine so
#' the timeline reads sensibly top to bottom.
CATALOG_SOURCES <- list(
  list(id = "sentinel-2-l2a", label = "Sentinel-2 L2A", kind = "Optical",
       res = "10 m", revisit = "~5 days",
       note = "Primary workhorse. Red/NIR for NDVI, SCL for cloud masking."),
  list(id = "landsat-c2-l2", label = "Landsat 8/9", kind = "Optical",
       res = "30 m", revisit = "~8 days (two sats)",
       note = "Coarser but the archive runs back to 1982 -- the route to long baselines."),
  list(id = "hls2-s30", label = "HLS Sentinel-2", kind = "Optical",
       res = "30 m", revisit = "~5 days",
       note = "NASA harmonised product; Sentinel-2 resampled to the Landsat grid."),
  list(id = "hls2-l30", label = "HLS Landsat", kind = "Optical",
       res = "30 m", revisit = "~8 days",
       note = "Landsat side of the harmonised pair. Combine the two for a dense series."),
  list(id = "sentinel-1-rtc", label = "Sentinel-1 radar", kind = "Radar",
       res = "10 m", revisit = "~12 days",
       note = "Sees through cloud. Independent of the weather that thins optical winter coverage."),
  list(id = "modis-13Q1-061", label = "MODIS NDVI 16-day", kind = "Composite",
       res = "250 m", revisit = "16 days",
       note = "Too coarse for one field, but a consistent 2000-present reference."),
  list(id = "naip", label = "NAIP aerial", kind = "Aerial",
       res = "0.6 m", revisit = "2-3 years",
       note = "Sub-metre true colour + NIR. Good for showing leadership what a field looks like.")
)

#' Every acquisition over the field, per source.
#'
#' @return Data frame of source, label, kind, date and cloud (NA where the
#'         source does not report it, e.g. radar).
catalog_availability <- function(aoi, start = "2020-01-01",
                                 end = as.character(Sys.Date()),
                                 sources = CATALOG_SOURCES,
                                 refresh = FALSE, only_cached = FALSE,
                                 progress = NULL) {

  key <- cache_key(aoi, start, end, vapply(sources, `[[`, "", "id"), "catalog_v1")
  hit <- if (refresh) NULL else cache_get(key, "catalog")
  if (!is.null(hit)) return(hit)
  if (only_cached) return(NULL)

  bbox <- field_bbox(aoi)
  rows <- list()

  for (k in seq_along(sources)) {
    src <- sources[[k]]
    if (!is.null(progress)) progress(k, length(sources), paste("Querying", src$label))

    got <- tryCatch({
      it <- rstac::stac(PC_STAC) |>
        rstac::stac_search(
          collections = src$id, bbox = bbox,
          datetime = paste0(start, "T00:00:00Z/", end, "T23:59:59Z"),
          limit = 500
        ) |>
        rstac::post_request() |>
        rstac::items_fetch()
      it$features
    }, error = function(e) NULL)

    if (is.null(got) || !length(got)) next

    dts <- vapply(got, function(f) {
      d <- f$properties[["datetime"]]
      if (is.null(d)) d <- f$properties[["start_datetime"]]
      if (is.null(d)) NA_character_ else substr(d, 1, 10)
    }, character(1))

    cld <- vapply(got, function(f) {
      v <- f$properties[["eo:cloud_cover"]]
      if (is.null(v)) NA_real_ else as.numeric(v)
    }, numeric(1))

    ok <- !is.na(dts)
    if (!any(ok)) next

    rows[[length(rows) + 1]] <- data.frame(
      source = src$id, label = src$label, kind = src$kind,
      res = src$res, date = as.Date(dts[ok]), cloud = cld[ok],
      stringsAsFactors = FALSE
    )
  }

  # CDL is annual and comes from CropScape rather than STAC, so it is added by
  # hand. It is published for year Y in the first months of Y+1.
  yrs <- seq(as.integer(substr(start, 1, 4)), as.integer(substr(end, 1, 4)))
  last_cdl <- as.integer(format(Sys.Date(), "%Y")) - 1
  yrs <- yrs[yrs <= last_cdl]
  if (length(yrs)) {
    rows[[length(rows) + 1]] <- data.frame(
      source = "usda-cdl", label = "USDA CDL", kind = "Crop type",
      res = "30 m", date = as.Date(sprintf("%d-07-01", yrs)), cloud = NA_real_,
      stringsAsFactors = FALSE
    )
  }

  out <- if (length(rows)) do.call(rbind, rows) else data.frame()
  if (nrow(out)) out <- out[order(out$label, out$date), ]
  rownames(out) <- NULL

  cache_put(key, out, "catalog")
  out
}

#' Per-source summary: how many acquisitions, how often, how many usable.
catalog_summary <- function(avail) {
  if (!nrow(avail)) return(data.frame())
  sp <- split(avail, avail$label)
  out <- lapply(names(sp), function(lb) {
    d <- sp[[lb]][order(sp[[lb]]$date), ]
    gaps <- as.numeric(diff(d$date))
    data.frame(
      Source      = lb,
      Type        = d$kind[1],
      Resolution  = d$res[1],
      Acquisitions = nrow(d),
      `Clear (<20% cloud)` = if (all(is.na(d$cloud))) NA_integer_ else sum(d$cloud < 20, na.rm = TRUE),
      `Median gap (days)` = if (length(gaps)) round(stats::median(gaps), 1) else NA_real_,
      First = format(min(d$date), "%Y-%m-%d"),
      Last  = format(max(d$date), "%Y-%m-%d"),
      check.names = FALSE, stringsAsFactors = FALSE
    )
  })
  res <- do.call(rbind, out)
  res[order(-res$Acquisitions), ]
}

#' Timeline: one row per source, one mark per acquisition.
#'
#' Optical sources are shaded by cloud cover, which makes the winter thinning
#' obvious -- and makes the case for radar in the same glance.
plot_catalog_timeline <- function(avail, title = NULL) {
  if (!nrow(avail)) {
    graphics::plot.new(); graphics::title("No acquisitions found"); return(invisible())
  }
  ord <- c("NAIP aerial", "USDA CDL", "MODIS NDVI 16-day", "Sentinel-1 radar",
           "HLS Landsat", "HLS Sentinel-2", "Landsat 8/9", "Sentinel-2 L2A")
  labs <- intersect(ord, unique(avail$label))
  labs <- c(labs, setdiff(unique(avail$label), labs))

  graphics::par(mar = c(4, 11, 3, 2))
  graphics::plot(range(avail$date), c(0.5, length(labs) + 0.5), type = "n",
                 yaxt = "n", xlab = "", ylab = "",
                 main = title %||% "Data available for this field")
  graphics::axis(2, at = seq_along(labs), labels = labs, las = 1, cex.axis = 0.85)
  graphics::abline(h = seq_along(labs), col = "grey93")
  graphics::grid(nx = NULL, ny = NA, col = "grey93")

  ramp <- grDevices::colorRamp(c("#01665e", "#d8b365"))

  for (k in seq_along(labs)) {
    d  <- avail[avail$label == labs[k], ]
    cl <- d$cloud
    na <- is.na(cl)

    # A source can report cloud for some acquisitions and not others -- MODIS
    # does. Substituting before the ramp and recolouring after keeps those rows
    # on the plot; feeding NA straight to colorRamp() errors out and loses the
    # whole timeline.
    cl[na] <- 0
    col <- grDevices::rgb(ramp(pmin(pmax(cl, 0), 100) / 100), maxColorValue = 255)
    col[na] <- "#2c7fb8"

    graphics::points(d$date, rep(k, nrow(d)), pch = 124, col = col, cex = 1.1)
  }

  graphics::legend("topleft", bty = "n", horiz = TRUE, cex = 0.75, pch = 124,
                   col = c("#01665e", "#d8b365", "#2c7fb8"),
                   legend = c("clear", "cloudy", "no cloud metric (radar/annual)"))
  invisible(labs)
}
