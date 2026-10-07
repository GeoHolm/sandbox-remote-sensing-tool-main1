# ==============================================================================
# armor.R -- Soil armor: how much of the surface is covered, by anything
#
# WHAT CHANGED AND WHY
# This supersedes the minimum-NDTI approach. NDTI measures crop residue, which
# is only half of soil armor: a field under a living cover crop or a perennial
# stand is protected just as well as one under stubble, and NDTI scores it as
# though it were bare. On this library that error was not subtle -- the
# Washington alfalfa pivot, a permanent stand and the best-protected soil here,
# ranked last of eleven fields. It now ranks first.
#
# HOW IT WORKS
# Each pixel is placed in NDVI-DFI space and decomposed into three fractions
# that sum to one:
#
#   fPV   photosynthetic vegetation -- living green cover
#   fNPV  non-photosynthetic vegetation -- residue, stubble, litter
#   fBS   bare soil
#
# Soil armor is 1 - fBS: cover from any source. NDVI alone cannot do this,
# because residue and bare soil look nearly identical to it. DFI is what
# separates them -- see the endmembers below, where NPV and BS differ by 0.05
# in NDVI and by 22 in DFI.
#
# DFI = 100 * (1 - SWIR2/SWIR1) * (Red/NIR), Cao et al. (2010). The first term
# is the lignocellulose absorption near 2100 nm that residue has and soil does
# not; the second suppresses green canopy.
#
# WHAT IS STILL NOT CALIBRATED
# The endmembers are derived from this library's own pixels, not from measured
# cover. The fractions are therefore internally consistent and comparable
# between these fields, but they are not validated cover percentages. Ground
# truth -- line transects scoring green cover, residue and bare separately --
# is what would turn fBS into a defensible number.
# ==============================================================================

# Triangle vertices in (NDVI, DFI), from 65,555 cloud-free pixels across six
# fields spanning permanent green, heavy residue and clean tilled soil.
#
# Water and deep shadow were excluded first, and that mattered: as NIR
# collapses, DFI's Red/NIR term explodes, so the highest-DFI pixels in the raw
# pool were flooded rice and cloud shadow rather than residue. Left in, they
# put the NPV vertex at NDVI -0.02, which is not a surface any crop field has.
ARMOR_ENDMEMBERS <- rbind(
  PV  = c(ndvi = 0.961, dfi =  1.212),   # pure living canopy
  NPV = c(ndvi = 0.232, dfi = 25.642),   # pure residue
  BS  = c(ndvi = 0.183, dfi =  3.296)    # clean bare soil
)

# Below this NDVI the pixel is water or deep shadow, where DFI is meaningless.
# Masked rather than mixed, so it drops out of the field average instead of
# corrupting it.
ARMOR_WATER_NDVI <- 0.05

#' Per-pixel cover fractions from a loaded scene.
#'
#' @param b Named list of reflectance rasters: red, nir, swir16, swir22.
#' @return List of three rasters (pv, npv, bs), each 0-1, summing to 1.
cover_fractions <- function(b) {
  ndvi <- (b$nir - b$red) / (b$nir + b$red)
  dfi  <- 100 * (1 - b$swir22 / b$swir16) * (b$red / b$nir)

  # One 3x3 inverse, applied as raster algebra -- the alternative, solving
  # per pixel in a loop, is thousands of times slower for the same answer.
  A <- rbind(ARMOR_ENDMEMBERS[, "ndvi"], ARMOR_ENDMEMBERS[, "dfi"], c(1, 1, 1))
  Ai <- solve(A)

  f <- lapply(1:3, function(i) Ai[i, 1] * ndvi + Ai[i, 2] * dfi + Ai[i, 3])

  # Spectral variability puts roughly one pixel in eight just outside the
  # triangle. Clamp and renormalise rather than discard: a pixel at -0.03 is a
  # pure endmember with noise on it, not a measurement failure.
  f <- lapply(f, function(x) terra::clamp(x, 0, 1, values = TRUE))
  s <- f[[1]] + f[[2]] + f[[3]]
  f <- lapply(f, function(x) x / s)

  bad <- ndvi < ARMOR_WATER_NDVI
  f <- lapply(f, function(x) terra::mask(x, bad, maskvalues = TRUE))
  stats::setNames(f, c("pv", "npv", "bs"))
}

# Registered from inside a local() so each function carries its own small
# environment holding the endmember inverse. Extraction workers get that
# environment with the function; they cannot reach back into this session.
local({
  Ai  <- solve(rbind(ARMOR_ENDMEMBERS[, "ndvi"], ARMOR_ENDMEMBERS[, "dfi"], c(1, 1, 1)))
  wat <- ARMOR_WATER_NDVI
  BANDS <- c("red", "nir", "swir16", "swir22")

  mk <- function(which) {
    force(which)
    function(b) {
      ndvi <- (b$nir - b$red) / (b$nir + b$red)
      dfi  <- 100 * (1 - b$swir22 / b$swir16) * (b$red / b$nir)
      f <- lapply(1:3, function(i) Ai[i, 1] * ndvi + Ai[i, 2] * dfi + Ai[i, 3])
      f <- lapply(f, function(x) terra::clamp(x, 0, 1, values = TRUE))
      s <- f[[1]] + f[[2]] + f[[3]]
      terra::mask(f[[which]] / s, ndvi < wat, maskvalues = TRUE)
    }
  }
  add_index("f_pv",  mk(1), bands = BANDS, range = c(0, 1),
            desc = "Living green cover fraction (NDVI-DFI unmixing).")
  add_index("f_npv", mk(2), bands = BANDS, range = c(0, 1),
            desc = "Residue / non-photosynthetic cover fraction.")
  add_index("f_bs",  mk(3), bands = BANDS, range = c(0, 1),
            desc = "Bare soil fraction. Soil armor is 1 - this.")
  local({
    bs <- mk(3)
    add_index("armor", function(b) 1 - bs(b), bands = BANDS, range = c(0, 1),
              desc = "Soil armor: fraction of surface covered, living or residue.")
  })
  add_index("dfi", function(b) 100 * (1 - b$swir22 / b$swir16) * (b$red / b$nir),
            bands = BANDS, range = c(-5, 45),
            desc = "Dead Fuel Index (Cao 2010). Non-photosynthetic material.")
})

# NDTI rides along because the bands are already fetched and it remains the
# residue-specific number the literature is built on. It is reported, not
# used as the headline.
ARMOR_INDICES <- c("ndvi", "ndti", "dfi", "f_pv", "f_npv", "f_bs")
# The whole calendar year, not just the pre-planting window.
#
# The extraction was spring-only because it was a second pass over four extra
# bands and nobody wanted to pay for autumn. The cost is real -- about 40 s per
# field-year cold against 13 s for the spring window -- but the spring-only view
# could not show fall tillage, cover crop establishment, or how much residue
# actually survived the winter, which is most of what the off-season is for.
#
# The SUMMARY STATISTIC is unchanged. armor_summary() still filters to the
# pre-planting window from residue_window(), so the per-season table and every
# number the validation scored mean exactly what they did before. Only the
# chart got wider.
ARMOR_SPAN    <- c("01-01", "12-31")
ARMOR_MIN_OBS <- 3

#' Spring index series for the armor window, one extraction per year.
armor_series <- function(aoi, years = c(2020, as.integer(format(Sys.Date(), "%Y"))),
                         workers = 8, only_cached = FALSE, refresh = FALSE,
                         progress = NULL) {
  yrs <- seq.int(years[1], years[2])
  parts <- vector("list", length(yrs))
  for (i in seq_along(yrs)) {
    y <- yrs[i]
    df <- extract_field_series(
      aoi, sprintf("%d-%s", y, ARMOR_SPAN[1]), sprintf("%d-%s", y, ARMOR_SPAN[2]),
      indices = ARMOR_INDICES, workers = workers,
      only_cached = only_cached, refresh = refresh)
    if (is.null(df)) { if (only_cached) return(NULL) else next }
    parts[[i]] <- df
    if (!is.null(progress)) progress(i, length(yrs), sprintf("Armor year %d", y))
  }
  parts <- Filter(Negate(is.null), parts)
  if (!length(parts)) return(NULL)
  out <- do.call(rbind, parts)
  out[order(out$index, out$date), ]
}

#' Trapezoidal average of `y` over the dates `x`.
#'
#' Falls back to the plain mean when the dates collapse to a single instant,
#' which cannot happen with real scenes but keeps the function total.
time_weighted <- function(x, y) {
  x <- as.numeric(x)
  if (length(y) < 2 || diff(range(x)) == 0) return(mean(y))
  sum(diff(x) * (utils::head(y, -1) + utils::tail(y, -1)) / 2) / diff(range(x))
}

#' Soil armor over one season's pre-planting window.
#'
#' Time-weighted, not the median, and not the minimum.
#'
#' Minimum was right for NDTI, where a single wet morning could quadruple the
#' reading and the lowest value was the least moisture-contaminated. A cover
#' fraction is a different quantity, so this started as a median -- but the
#' cross-implementation check caught that being fragile. On the Georgia field
#' in 2026 the two implementations saw 7 and 8 observations of a steeply
#' falling series, and the one extra date moved the median from 0.59 to 0.72.
#'
#' A trapezoidal average over the observation dates is the right answer anyway:
#' soil is exposed to erosion over *time*, so the quantity that matters is the
#' average cover through the window, not the middle value of however many
#' scenes happened to be clear. It is also barely moved by one extra
#' observation in an already-sampled stretch.
#'
#' Always returns a row, with the reason in `note` when there is nothing to say.
armor_summary <- function(ts, phen, year, season = c("spring", "full")) {
  season <- match.arg(season)

  row <- function(w = NULL, n_obs = 0L, ...) {
    base <- list(year = as.integer(year), season = season,
                 window_start  = if (is.null(w)) as.Date(NA) else w$start,
                 window_end    = if (is.null(w)) as.Date(NA) else w$end,
                 window_source = if (is.null(w)) NA_character_ else w$source,
                 n_obs = n_obs)
    fill <- list(armor = NA_real_, armor_lo = NA_real_, armor_hi = NA_real_,
                 f_pv = NA_real_, f_npv = NA_real_, f_bs = NA_real_,
                 min_ndti = NA_real_, ndvi_med = NA_real_, note = NA_character_)
    extra <- list(...); fill[names(extra)] <- extra
    as.data.frame(c(base, fill), stringsAsFactors = FALSE)
  }

  w <- residue_window(phen, year, season)
  if (is.null(w)) {
    return(row(note = paste0(
      "no window: planting falls at or before the start of the window, so ",
      "there is no pre-planting period to measure.")))
  }

  d <- ts[ts$date >= w$start & ts$date <= w$end, ]
  wide <- if (nrow(d)) {
    x <- stats::reshape(d[, c("date", "index", "mean")], idvar = "date",
                        timevar = "index", direction = "wide")
    names(x) <- sub("^mean[.]", "", names(x))
    x
  } else d[0, ]
  need <- c("f_pv", "f_npv", "f_bs")
  if (!all(need %in% names(wide))) {
    return(row(w, note = "cover fractions not present in this series."))
  }
  wide <- wide[stats::complete.cases(wide[, need]), ]
  n_obs <- nrow(wide)

  if (n_obs < ARMOR_MIN_OBS) {
    return(row(w, n_obs, note = sprintf(
      "only %d usable observation(s) in the window; too few to summarise.", n_obs)))
  }

  wide <- wide[order(wide$date), ]
  a <- 1 - wide$f_bs
  note <- if (!identical(w$source, "phenology"))
    "window ends fall back to fixed dates; phenology had no estimate." else NA_character_

  row(w, n_obs,
      armor    = round(time_weighted(wide$date, a), 3),
      armor_lo = round(min(a), 3),
      armor_hi = round(max(a), 3),
      f_pv     = round(time_weighted(wide$date, wide$f_pv), 3),
      f_npv    = round(time_weighted(wide$date, wide$f_npv), 3),
      f_bs     = round(time_weighted(wide$date, wide$f_bs), 3),
      min_ndti = if ("ndti" %in% names(wide)) round(min(wide$ndti, na.rm = TRUE), 4) else NA_real_,
      ndvi_med = if ("ndvi" %in% names(wide)) round(stats::median(wide$ndvi, na.rm = TRUE), 3) else NA_real_,
      note = note)
}

#' armor_summary() for every year the series covers.
armor_all_years <- function(ts, phen, season = c("spring", "full")) {
  season <- match.arg(season)
  if (is.null(ts) || !nrow(ts)) return(NULL)
  years <- sort(unique(as.integer(format(ts$date, "%Y"))))
  out <- do.call(rbind, lapply(years, function(y) armor_summary(ts, phen, y, season)))
  rownames(out) <- NULL
  out
}

#' Which band a soil armor value falls in.
ARMOR_BREAKS <- c(low = 0.40, high = 0.75)
ARMOR_LABELS <- c("mostly bare", "partly covered", "well covered")
armor_band <- function(x) {
  cut(x, breaks = c(-Inf, ARMOR_BREAKS, Inf), labels = ARMOR_LABELS, right = FALSE)
}

#' Cover fractions through the spring window, one panel per year.
#'
#' A stacked view: living cover on the bottom, residue above it, bare soil as
#' the gap to the top. The eye reads the white band as exposed soil, which is
#' the quantity that matters.
plot_armor <- function(ts, res, phen = NULL) {
  years <- sort(unique(res$year))
  nc <- min(4, length(years)); nr <- ceiling(length(years) / nc)
  op <- graphics::par(mfrow = c(nr, nc), mar = c(2.6, 3.0, 2.0, 0.6),
                      mgp = c(1.8, 0.5, 0), tcl = -0.25, cex.axis = 0.75)
  on.exit(graphics::par(op), add = TRUE)

  w <- stats::reshape(ts[, c("date", "index", "mean")], idvar = "date",
                      timevar = "index", direction = "wide")
  names(w) <- sub("^mean[.]", "", names(w))
  w <- w[order(w$date), ]

  for (y in years) {
    r  <- res[res$year == y, ]
    xr <- c(as.Date(sprintf("%d-01-01", y)), as.Date(sprintf("%d-12-31", y)))
    d  <- w[as.integer(format(w$date, "%Y")) == y &
              !is.na(w$f_bs) & w$date >= xr[1] & w$date <= xr[2], ]

    plot(NA, xlim = xr, ylim = c(0, 1), xlab = "", ylab = "cover fraction",
         main = sprintf("%d%s", y, if (is.na(r$armor)) "  (no reading)"
                                   else sprintf("   armor %.2f", r$armor)),
         cex.main = 0.9, xaxt = "n")
    # Every second month: twelve labels across a quarter-width panel collide.
    graphics::axis.Date(1, at = seq(xr[1], xr[2], by = "2 months"), format = "%b")

    if (nrow(d) > 1) {
      # Bare soil is the unfilled space at the top, so the white gap is the
      # thing being measured rather than something to infer from a legend.
      graphics::polygon(c(d$date, rev(d$date)), c(d$f_pv, rep(0, nrow(d))),
                        col = "#5ab4ac", border = NA)
      graphics::polygon(c(d$date, rev(d$date)),
                        c(d$f_pv + d$f_npv, rev(d$f_pv)),
                        col = "#d8b365", border = NA)
      graphics::lines(d$date, d$f_pv + d$f_npv, col = "grey30", lwd = 1.2)
      graphics::points(d$date, d$f_pv + d$f_npv, pch = 19, cex = 0.5, col = "grey20")
    }
    # The reported number still comes from the pre-planting window alone, so
    # shade it: without that the eye reads the annual average off a chart whose
    # headline figure describes one slice of it.
    if (!is.na(r$window_start)) {
      graphics::rect(r$window_start, 0, r$window_end, 1,
                     col = grDevices::rgb(0, 0, 0, 0.05), border = NA)
      graphics::abline(v = c(r$window_start, r$window_end), col = "grey35",
                       lty = 2, lwd = 1)
    }
    if (identical(y, years[1])) {
      graphics::legend("bottomleft", bty = "n", cex = 0.62, horiz = TRUE,
                       fill = c("#5ab4ac", "#d8b365", "white"),
                       legend = c("living", "residue", "bare"))
    }
    graphics::box()
  }
  invisible(years)
}
