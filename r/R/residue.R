# ==============================================================================
# residue.R -- Crop residue and tillage intensity from SWIR indices
#
# WHAT THE SIGNAL IS
# Crop residue and bare soil are both bright in the shortwave infrared, but
# residue contains cellulose and lignin, which absorb near 2100 nm. NDTI --
# (SWIR16 - SWIR22) / (SWIR16 + SWIR22) -- picks up the resulting slope
# difference, so a field left in heavy residue reads higher than one that has
# been ploughed clean.
#
# WHY THIS REPORTS INDICES AND NOT A TILLAGE CLASS
# Two things measured on this field library, not taken from the literature:
#
#   1. Soil moisture moves NDTI more than tillage does. On the Iowa field,
#      18 and 20 May 2024 gave NDTI 0.035 and 0.138 with NDVI flat at 0.18 --
#      a four-fold swing from rain, two days apart, with no change in residue.
#      A single date is not usable, which is why everything here is computed
#      over a window and the minimum is reported next to the median.
#   2. NDTI does not separate residue from green vegetation, because a green
#      canopy absorbs strongly in the SWIR too. Dates greener than
#      RESIDUE_GREEN_MAX are screened out and counted separately.
#
# Published field-level accuracy for multispectral tillage classification is
# roughly 73-80%, against >90% for hyperspectral CAI, which Sentinel-2 cannot
# compute. Calibrating against residue line-transect measurements is what turns
# any of this into a class. Until then: numbers, not verdicts.
# ==============================================================================

# Above this NDVI the surface is green cover and NDTI is reading canopy rather
# than residue. Same threshold the cover crop module calls "sustained green".
RESIDUE_GREEN_MAX <- 0.30

# Fewer clear, non-green observations than this and a minimum is just the
# noisiest of very few numbers.
RESIDUE_MIN_OBS <- 3

# The span the warmed series covers. Wider than any single residue window so
# one extraction serves every year, and fixed rather than derived from
# phenology so the cache key cannot move when a planting date shifts by a day.
RESIDUE_SPAN <- c("03-01", "06-30")

RESIDUE_INDICES <- c("ndvi", "ndti", "ndsvi", "ndi7")

# --- provisional reference bands ---------------------------------------------
# Breakpoints for reading min_ndti, drawn on the plot and deliberately NOT
# written into any output table. They are derived from this library's own
# distribution across 64 seasons -- p33 and p75 rounded to 0.05 and 0.09 -- and
# express rank within these eleven fields. They are not crop residue cover, and
# nothing here converts them to one.
#
# What would replace them: line-transect residue measurements on 30-50 fields
# spanning the range, fitted as CRC ~ min_ndti and inverted at the CTIC class
# boundaries (conventional <15% cover, reduced 15-30%, conservation >30%).
# Published minNDTI regressions reach R2 ~ 0.89 but RMSD ~ 10.6 percentage
# points of cover -- comparable to the width of the reduced class -- so even a
# calibrated model flips fields near a boundary.
#
# Stratify before trusting any single cut: spring residue is the PREVIOUS
# crop's, and across this library the median min_ndti runs Corn 0.078,
# Peanuts 0.067, Soybeans 0.066, Cotton 0.062, Rice 0.051, double-crop 0.014.
# One global threshold would call corn ground well-armoured and double-crop
# ground bare on crop alone, whatever the management.
RESIDUE_BREAKS <- c(low = 0.05, high = 0.09)
# Deliberately pale. A first attempt used the full-strength BrBG tints and the
# bands dominated the panel -- a field sitting in the lowest band still read as
# mostly teal, which is the opposite of what the chart should say.
RESIDUE_BAND_COLS <- c("#fbf2de", "#fafafa", "#e8f5f2")
RESIDUE_BAND_LABS <- c("less residue", "intermediate", "more residue")

#' Which provisional band a min_ndti value falls in.
#'
#' Provided so the number is in code rather than only in a README. Not called
#' by residue_summary() on purpose -- the tables report measurements, not
#' classes, until there is ground truth behind the cuts.
residue_band <- function(x) {
  cut(x, breaks = c(-Inf, RESIDUE_BREAKS, Inf),
      labels = RESIDUE_BAND_LABS, right = FALSE)
}

#' Spring index series for the residue window, one extraction per year.
#'
#' Deliberately not the year-round series. NDTI is only interpretable on bare
#' ground, so reading the whole year would cost several times as much to throw
#' most of it away -- and it would re-read every scene the NDVI series already
#' covers, because the cache key includes the index list.
#'
#' @return Long data frame as extract_field_series(), or NULL if only_cached
#'   and any year is missing.
residue_series <- function(aoi, years = c(2020, as.integer(format(Sys.Date(), "%Y"))),
                           workers = 8, only_cached = FALSE, refresh = FALSE,
                           progress = NULL) {
  yrs <- seq.int(years[1], years[2])
  parts <- vector("list", length(yrs))
  for (i in seq_along(yrs)) {
    y <- yrs[i]
    df <- extract_field_series(
      aoi, sprintf("%d-%s", y, RESIDUE_SPAN[1]), sprintf("%d-%s", y, RESIDUE_SPAN[2]),
      indices = RESIDUE_INDICES, workers = workers,
      only_cached = only_cached, refresh = refresh
    )
    if (is.null(df)) {
      if (only_cached) return(NULL)
      next
    }
    parts[[i]] <- df
    if (!is.null(progress)) progress(i, length(yrs), sprintf("Residue year %d", y))
  }
  parts <- Filter(Negate(is.null), parts)
  if (!length(parts)) return(NULL)
  out <- do.call(rbind, parts)
  out[order(out$index, out$date), ]
}

#' Residue indices over one season's pre-planting window.
#'
#' `min_ndti` is the headline number: the minimum across the window is the
#' statistic the minNDTI literature validates, because any single date is at
#' the mercy of whatever the soil moisture was that morning.
residue_summary <- function(ts, phen, year, season = c("spring", "full")) {
  season <- match.arg(season)

  # Every year gets a row, including the ones with nothing to report. Returning
  # NULL for those made the Soil armor table silently shorter than the Summary
  # table for the same field, and "this year is absent" is indistinguishable
  # from "this year was never computed". The reason belongs in the row.
  row <- function(w = NULL, n_obs = 0L, n_bare = 0L, n_green = 0L,
                  ndvi_max = NA_real_, ...) {
    base <- list(
      year = as.integer(year), season = season,
      window_start  = if (is.null(w)) as.Date(NA) else w$start,
      window_end    = if (is.null(w)) as.Date(NA) else w$end,
      window_source = if (is.null(w)) NA_character_ else w$source,
      n_obs = n_obs, n_bare = n_bare, n_green = n_green, ndvi_max = ndvi_max)
    fill <- list(min_ndti = NA_real_, median_ndti = NA_real_, max_ndti = NA_real_,
                 min_ndti_date = as.Date(NA), median_ndsvi = NA_real_,
                 median_ndi7 = NA_real_, note = NA_character_)
    extra <- list(...)
    fill[names(extra)] <- extra
    as.data.frame(c(base, fill), stringsAsFactors = FALSE)
  }

  w <- residue_window(phen, year, season)
  if (is.null(w)) {
    return(row(note = paste0(
      "no window: planting falls at or before the start of the window, so ",
      "there is no pre-planting period to measure. Common on fields that go ",
      "in during the first days of March.")))
  }

  d <- ts[ts$date >= w$start & ts$date <= w$end, ]
  wide <- if (nrow(d)) {
    x <- stats::reshape(d[, c("date", "index", "mean")], idvar = "date",
                        timevar = "index", direction = "wide")
    names(x) <- sub("^mean[.]", "", names(x))
    if (all(c("ndti", "ndvi") %in% names(x)))
      x[!is.na(x$ndti) & !is.na(x$ndvi), ] else x[0, ]
  } else d[0, ]

  n_obs <- nrow(wide)
  if (!n_obs) {
    return(row(w, note = paste0(
      "no usable observations: the window exists but no clear scene inside it ",
      "carried both NDTI and NDVI.")))
  }

  bare     <- wide[wide$ndvi < RESIDUE_GREEN_MAX, ]
  n_green  <- n_obs - nrow(bare)
  ndvi_max <- round(max(wide$ndvi), 3)

  if (nrow(bare) < RESIDUE_MIN_OBS) {
    why <- if (n_green == 0)
      sprintf("only %d non-green observation(s) in the window", nrow(bare))
    else
      sprintf("%d of %d observations were green (NDVI at or above %.2f), leaving %d",
              n_green, n_obs, RESIDUE_GREEN_MAX, nrow(bare))
    return(row(w, n_obs, nrow(bare), n_green, ndvi_max,
               note = sprintf("not enough bare ground to read: %s.", why)))
  }

  note <- NA_character_
  if (n_green > 0) {
    note <- sprintf(paste0("%d of %d observations screened out as green cover; ",
                           "NDTI reads canopy, not residue, on those dates."),
                    n_green, n_obs)
  }
  if (!identical(w$source, "phenology")) {
    extra <- "window ends fall back to fixed dates; phenology had no estimate."
    note <- if (is.na(note)) extra else paste0(note, " Also, ", extra)
  }

  row(w, n_obs, nrow(bare), n_green, ndvi_max,
      min_ndti      = round(min(bare$ndti), 4),
      median_ndti   = round(stats::median(bare$ndti), 4),
      max_ndti      = round(max(bare$ndti), 4),
      min_ndti_date = bare$date[which.min(bare$ndti)],
      median_ndsvi  = if ("ndsvi" %in% names(bare)) round(stats::median(bare$ndsvi), 4) else NA_real_,
      median_ndi7   = if ("ndi7"  %in% names(bare)) round(stats::median(bare$ndi7), 4)  else NA_real_,
      note = note)
}

#' residue_summary() for every year the series covers.
residue_all_years <- function(ts, phen, season = c("spring", "full")) {
  season <- match.arg(season)
  if (is.null(ts) || !nrow(ts)) return(NULL)
  years <- sort(unique(as.integer(format(ts$date, "%Y"))))
  rows <- lapply(years, function(y) residue_summary(ts, phen, y, season))
  rows <- Filter(Negate(is.null), rows)
  if (!length(rows)) return(NULL)
  out <- do.call(rbind, rows)
  rownames(out) <- NULL
  out
}

#' Residue indices through the spring window, one panel per year.
#'
#' Shows what the number is made of: every observation, the window it was taken
#' over, and which dates were thrown out for being green. A reader who can see
#' that four of seven points were screened will treat the minimum accordingly.
plot_residue <- function(ts, res, phen = NULL) {
  years <- sort(unique(res$year))
  n  <- length(years)
  nc <- min(4, n); nr <- ceiling(n / nc)

  # One scale for every panel, driven by the values actually inside the
  # windows. A fixed 0-0.45 axis left the data squashed into the bottom fifth
  # and gave most of the panel to the top reference band, which reads as
  # reassurance the numbers do not support.
  inwin <- unlist(lapply(years, function(y) {
    r <- res[res$year == y, ]
    if (is.na(r$window_start)) return(numeric(0))
    d <- ts[ts$index == "ndti" & ts$date >= r$window_start &
              ts$date <= r$window_end, ]
    d$mean
  }))
  hi <- max(c(inwin, RESIDUE_BREAKS + 0.04), na.rm = TRUE)
  lo <- min(c(inwin, 0), na.rm = TRUE)
  ylim <- c(lo - 0.02, hi + 0.02)
  op <- graphics::par(mfrow = c(nr, nc), mar = c(2.6, 3.0, 2.0, 0.6),
                      mgp = c(1.8, 0.5, 0), tcl = -0.25, cex.axis = 0.75)
  on.exit(graphics::par(op), add = TRUE)

  for (y in years) {
    r <- res[res$year == y, ]
    d <- ts[as.integer(format(ts$date, "%Y")) == y, ]
    nd <- d[d$index == "ndti", ]
    nv <- d[d$index == "ndvi", ]
    xr <- c(as.Date(sprintf("%d-03-01", y)), as.Date(sprintf("%d-06-30", y)))

    plot(NA, xlim = xr, ylim = ylim, xlab = "", ylab = "NDTI",
         main = sprintf("%d%s", y,
                        if (!is.na(r$min_ndti)) sprintf("   min %.3f", r$min_ndti)
                        else if (is.na(r$window_start)) "  (no window)"
                        else if (r$n_obs == 0) "  (no observations)"
                        else "  (no bare ground)"),
         cex.main = 0.9, xaxt = "n")
    graphics::axis.Date(1, at = seq(xr[1], xr[2], by = "month"), format = "%b")

    # Provisional reference bands, behind everything. Drawn rather than
    # tabulated so a reader sees where a field sits without the app asserting
    # a class it cannot yet defend.
    edges <- c(-1, RESIDUE_BREAKS, 2)
    for (k in seq_len(3)) {
      graphics::rect(xr[1] - 400, edges[k], xr[2] + 400, edges[k + 1],
                     col = RESIDUE_BAND_COLS[k], border = NA)
    }
    graphics::abline(h = RESIDUE_BREAKS, col = "grey65", lty = 3, lwd = 0.9)

    # The window is marked by its edges rather than a second wash -- shading on
    # top of shading made it impossible to tell which one meant what.
    if (!is.na(r$window_start)) {
      graphics::abline(v = c(r$window_start, r$window_end), col = "grey45",
                       lty = 2, lwd = 1)
    }

    if (nrow(nd)) {
      # Three states, because "which points made the number" is the question a
      # reader has. Filled means used; anything else was excluded, and the two
      # reasons for exclusion look different.
      inwin    <- if (is.na(r$window_start)) rep(FALSE, nrow(nd)) else
                    nd$date >= r$window_start & nd$date <= r$window_end
      is_green <- nd$date %in% nv$date[nv$mean >= RESIDUE_GREEN_MAX]
      graphics::points(nd$date[!inwin], nd$mean[!inwin], pch = 20,
                       col = "grey82", cex = 0.7)
      graphics::points(nd$date[inwin & is_green], nd$mean[inwin & is_green],
                       pch = 1, col = "grey55", cex = 0.9)
      graphics::points(nd$date[inwin & !is_green], nd$mean[inwin & !is_green],
                       pch = 19, col = "#8c510a", cex = 0.9)
    }
    # Only across the window -- the minimum is a property of the window, and a
    # line running the width of the panel invites reading it against points
    # that were never part of it.
    if (!is.na(r$min_ndti)) {
      graphics::segments(r$window_start, r$min_ndti, r$window_end, r$min_ndti,
                         col = "#8c510a", lty = 2, lwd = 1.4)
    }
    # On every panel, not just the first. A reader scanning the 2024 panel
    # should not have to look back at 2020 to find out which band is which.
    at <- c(mean(c(ylim[1], RESIDUE_BREAKS[1])), mean(RESIDUE_BREAKS),
            mean(c(RESIDUE_BREAKS[2], ylim[2])))
    graphics::text(xr[2], at, RESIDUE_BAND_LABS, adj = c(1, 0.5),
                   cex = 0.68, font = 2, col = "grey30")
    graphics::box()
  }
  invisible(years)
}
