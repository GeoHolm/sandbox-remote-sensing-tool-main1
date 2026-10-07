# ==============================================================================
# phenology.R -- Planting and harvest dates from the NDVI curve
#
# WHAT THIS IS
# NDVI cannot see a planter or a combine. What it sees is the canopy: bare soil
# before emergence, green-up as the canopy closes, senescence as the crop dries
# down, and residue after the field is cleared. Planting and harvest are then
# inferred from those transitions.
#
# HOW GOOD IS IT
# Published work using Sentinel-2/Landsat green-up against reported planting
# dates for US corn and soy generally lands within about two weeks. That is the
# honest resolution of this method and it is what the functions below report.
# The offsets in CROP_LAGS are literature-typical starting values, not
# calibrated against your own records -- if Field to Market has member-reported
# planting dates, regressing these estimates against them is the single highest
# value next step, and would turn a +/- 14 day window into something tighter.
#
# THE COVER CROP COMPLICATION
# A cover-cropped field has a bimodal NDVI curve: a spring cover crop peak, a
# dip when it is terminated and the cash crop goes in, then the cash crop peak.
# Anchoring the baseline on "spring NDVI" would read the cover crop as an early
# cash crop. Everything below anchors instead on the trough immediately before
# the cash crop peak, which is bare soil in both cases.
# ==============================================================================

# Days from planting to the point where NDVI has risen 20% of the way to peak.
# Emergence is earlier than this; the canopy has to cover enough soil for the
# signal to move.
CROP_LAGS <- c(
  Corn          = 21,
  Soybeans      = 18,
  `Winter Wheat` = 0,   # planted the previous autumn; green-up is regrowth
  Cotton        = 24,
  Sorghum       = 20,
  Rice          = 20,
  default       = 20
)

# --- applicability limits -----------------------------------------------------
# This model assumes an annual row crop: bare soil, green-up, peak, senescence,
# residue. Two common systems break that assumption, and both are detectable
# from the curve itself.
#
# A perennial stand -- alfalfa, and other multi-cut forage -- is green all year
# and has no planting to find. The tempting test is "NDVI never reaches bare
# soil", but that alone does not work: a heavily cover-cropped Maryland corn
# field bottoms out at 0.31 and the alfalfa pivot at 0.33, which is not a gap
# you can put a threshold in. What does separate them is how much of the year
# is green. Across this library the alfalfa years sit above NDVI 0.50 for
# 86-95% of the year, while every genuine row crop year -- including the
# cover-cropped ones -- stays at or below 72%, because residue and the shoulder
# seasons pull the curve down even when a cover crop is present.
PERENNIAL_MIN_NDVI   <- 0.30    # never reaches bare soil
PERENNIAL_GREEN_FRAC <- 0.80    # ...and is green for most of the year

# Negative NDVI is open water, not vegetation. Flooded rice reaches -0.60 at the
# annual minimum. Dates can still be estimated, but the flood confuses the
# baseline, so they are reported with the reason attached.
WATER_NDVI <- 0.05

#' Does the annual-row-crop model apply to this season's curve?
#'
#' @param year_min   Minimum of the smoothed curve over the year.
#' @param green_frac Share of the year the curve sits above NDVI 0.50.
#' @return list(applies, note). A note with applies = TRUE is a caveat worth
#'   surfacing rather than a reason to withhold the estimate.
applicability <- function(year_min, green_frac) {
  if (year_min > PERENNIAL_MIN_NDVI && green_frac >= PERENNIAL_GREEN_FRAC) {
    return(list(applies = FALSE, note = sprintf(
      paste0("not an annual row crop -- NDVI never drops below %.2f and stays ",
             "above 0.50 for %d%% of the year, so there is no bare-soil period ",
             "to measure planting from (perennial or multi-cut, e.g. alfalfa)"),
      year_min, round(100 * green_frac))))
  }
  if (year_min < WATER_NDVI) {
    return(list(applies = TRUE, note = sprintf(
      paste0("standing water in the off-season (NDVI reaches %.2f); flooded ",
             "rice or a wet fallow shifts the baseline, so treat the dates as ",
             "indicative"), year_min)))
  }
  list(applies = TRUE, note = NULL)
}

crop_lag <- function(crop) {
  if (is.null(crop) || is.na(crop)) return(unname(CROP_LAGS[["default"]]))
  if (crop %in% names(CROP_LAGS)) unname(CROP_LAGS[[crop]]) else unname(CROP_LAGS[["default"]])
}

#' Estimate season markers for one crop year.
#'
#' @param ts    Long series from extract_field_series().
#' @param year  Calendar year.
#' @param crop  CDL crop name, used only to pick the planting lag.
#' @param index Index to work from; NDVI is the usual choice.
#' @return One-row data frame, or NULL when the year has too little data.
estimate_phenology <- function(ts, year, crop = NULL, index = "ndvi",
                               peak_window = c("06-01", "09-15")) {

  d <- ts[ts$index == index &
          ts$date >= as.Date(sprintf("%d-01-01", year)) &
          ts$date <= as.Date(sprintf("%d-12-31", year)), ]
  if (nrow(d) < 10) return(NULL)

  curve <- tryCatch(daily_series(d, index), error = function(e) NULL)
  if (is.null(curve)) return(NULL)
  curve <- curve[!is.na(curve$value), ]
  if (nrow(curve) < 60) return(NULL)

  # --- cash crop peak -------------------------------------------------------
  pw <- as.Date(sprintf("%d-%s", year, peak_window))
  inpk <- curve[curve$date >= pw[1] & curve$date <= pw[2], ]
  if (nrow(inpk) < 10) return(NULL)
  peak_i    <- which.max(inpk$value)
  peak_val  <- inpk$value[peak_i]
  peak_date <- inpk$date[peak_i]

  # A field that never greens up had no summer crop -- fallow, or a failure.
  if (peak_val < 0.45) {
    return(phen_row(year, crop, peak_date, peak_val, NA, NA, NA, NA, NA, NA,
                    NA, NA, NA, nrow(d), NA, "no summer crop detected"))
  }

  # Does the annual-row-crop model apply at all? Returning a confident-looking
  # planting date for a permanently green field is worse than returning none.
  ap <- applicability(min(curve$value, na.rm = TRUE),
                      mean(curve$value >= 0.50, na.rm = TRUE))
  if (!ap$applies) {
    return(phen_row(year, crop, peak_date, peak_val, NA, NA, NA, NA, NA, NA,
                    NA, NA, NA, nrow(d), NA, ap$note))
  }

  # --- trough before the peak: bare soil at planting ------------------------
  #
  # Take the LAST near-minimum before the peak, not the global one. On a
  # cover-cropped field the curve dips twice before the cash crop: once in
  # winter dormancy and again when the cover is terminated. The global minimum
  # can be the winter dip, in which case the spring cover crop green-up gets
  # read as crop emergence -- which produced a February planting date for corn
  # before this was fixed. The termination dip is the one that means "bare soil,
  # about to plant", and it is always the later of the two.
  pre <- curve[curve$date >= as.Date(sprintf("%d-03-01", year)) &
               curve$date <= peak_date - 20, ]
  if (nrow(pre) < 10) return(NULL)

  gmin  <- min(pre$value)
  near  <- which(pre$value <= gmin + 0.06)
  base_i    <- near[length(near)]
  baseline  <- pre$value[base_i]
  base_date <- pre$date[base_i]

  amp <- peak_val - baseline
  if (amp < 0.2) return(NULL)

  thr_up <- baseline + 0.20 * amp

  # --- green-up: first sustained crossing on the rising limb ----------------
  rise <- curve[curve$date >= base_date & curve$date <= peak_date, ]
  gi   <- which(rise$value >= thr_up)[1]
  if (is.na(gi)) return(NULL)
  greenup_date <- rise$date[gi]

  lag  <- crop_lag(crop)
  plant_est <- greenup_date - lag

  # --- senescence: the drop off the falling limb ----------------------------
  #
  # Anchored on the post-peak minimum, not on the spring baseline. Assuming the
  # curve returns to where it started fails wherever something green follows the
  # cash crop: on a cover-cropped cotton field NDVI falls after defoliation and
  # then climbs again, never reaching the spring floor, so a spring-anchored
  # threshold reported no harvest at all for five seasons running.
  #
  # The drop has to be a real one. In a season still under way the curve has
  # barely come off its peak, and without this guard the shallow dip would be
  # read as an early harvest.
  fall <- curve[curve$date >= peak_date, ]
  harvest_est <- NA
  if (nrow(fall) >= 10) {
    post_trough <- min(fall$value)
    if ((peak_val - post_trough) >= 0.35 * amp) {
      thr_down <- post_trough + 0.20 * (peak_val - post_trough)
      hi <- which(fall$value <= thr_down)[1]
      if (!is.na(hi)) harvest_est <- fall$date[hi]
    }
  }

  # --- uncertainty from actual observation density --------------------------
  # A threshold crossing sitting in the middle of a three-week cloud gap is a
  # guess. Widen the window to reflect that rather than quoting a flat +/- 14.
  gap_plant   <- nearest_gap(d$date, greenup_date)
  gap_harvest <- if (is.na(harvest_est)) NA else nearest_gap(d$date, harvest_est)

  win_plant   <- max(14, ceiling(gap_plant))
  win_harvest <- if (is.na(gap_harvest)) NA else max(14, ceiling(gap_harvest))

  conf <- if (is.na(gap_harvest)) "low -- no clear senescence"
          else if (max(gap_plant, gap_harvest) <= 10) "high"
          else if (max(gap_plant, gap_harvest) <= 20) "medium"
          else "low -- sparse imagery near transitions"

  # A caveat from the applicability check rides along with the estimate, and
  # caps the confidence -- standing water at the baseline is a bigger source of
  # error than a few days of cloud.
  if (!is.null(ap$note)) {
    conf <- if (grepl("^high|^medium", conf)) paste0("low -- ", ap$note)
            else paste0(conf, "; ", ap$note)
  }

  phen_row(year, crop, peak_date, peak_val,
           greenup_date, plant_est, plant_est - win_plant, plant_est + win_plant,
           harvest_est,
           if (is.na(harvest_est)) NA else harvest_est - win_harvest,
           if (is.na(harvest_est)) NA else harvest_est + win_harvest,
           baseline, amp, nrow(d),
           if (is.na(harvest_est)) NA else as.integer(harvest_est - greenup_date),
           conf)
}

phen_row <- function(year, crop, peak_date, peak_val, greenup, plant, plant_lo,
                     plant_hi, harvest, harvest_lo, harvest_hi, baseline, amp,
                     n_obs, season_days, conf) {
  data.frame(
    year = year, crop = crop %||% NA_character_,
    planting_est = as.Date(plant), planting_lo = as.Date(plant_lo),
    planting_hi = as.Date(plant_hi),
    greenup_date = as.Date(greenup),
    peak_date = as.Date(peak_date), peak_ndvi = round(peak_val, 3),
    harvest_est = as.Date(harvest), harvest_lo = as.Date(harvest_lo),
    harvest_hi = as.Date(harvest_hi),
    season_days = season_days,
    baseline_ndvi = round(baseline, 3), amplitude = round(amp, 3),
    n_obs = n_obs, confidence = conf,
    stringsAsFactors = FALSE, row.names = NULL
  )
}

# Largest observation gap straddling a date -- how blind we are at that moment.
nearest_gap <- function(obs_dates, at) {
  before <- obs_dates[obs_dates <= at]
  after  <- obs_dates[obs_dates >= at]
  if (!length(before) || !length(after)) return(60)
  as.numeric(min(after) - max(before))
}

#' Run estimate_phenology() across every year present in the series.
#'
#' @param crops Optional named vector, year -> crop name, from CDL.
phenology_all_years <- function(ts, crops = NULL, index = "ndvi") {
  years <- sort(unique(as.integer(format(ts$date, "%Y"))))
  rows <- lapply(years, function(y) {
    crop <- if (!is.null(crops) && as.character(y) %in% names(crops))
      unname(crops[[as.character(y)]]) else NULL
    estimate_phenology(ts, y, crop, index)
  })
  rows <- Filter(Negate(is.null), rows)
  if (!length(rows)) return(NULL)
  do.call(rbind, rows)
}

#' Plot one year's curve with the inferred markers drawn on.
plot_phenology <- function(ts, year, phen = NULL, crop = NULL, index = "ndvi") {
  d <- ts[ts$index == index &
          ts$date >= as.Date(sprintf("%d-01-01", year)) &
          ts$date <= as.Date(sprintf("%d-12-31", year)), ]
  if (nrow(d) < 5) { graphics::plot.new(); graphics::title("Not enough data"); return(invisible()) }

  curve <- tryCatch(daily_series(d, index), error = function(e) NULL)
  if (is.null(phen)) phen <- estimate_phenology(ts, year, crop, index)

  graphics::par(mar = c(4, 4, 3, 1))
  graphics::plot(d$date, d$mean, type = "n", ylim = c(0, 1),
                 xlab = "", ylab = toupper(index),
                 main = sprintf("%d%s", year,
                                if (!is.null(crop) && !is.na(crop)) paste0("  |  ", crop) else ""))
  graphics::grid(col = "grey92")

  if (!is.null(phen) && !is.na(phen$planting_est)) {
    graphics::rect(phen$planting_lo, -1, phen$planting_hi, 2,
                   col = grDevices::adjustcolor("#2c7fb8", 0.13), border = NA)
    if (!is.na(phen$harvest_est)) {
      graphics::rect(phen$harvest_lo, -1, phen$harvest_hi, 2,
                     col = grDevices::adjustcolor("#d95f0e", 0.13), border = NA)
    }
  }

  if (!is.null(curve)) graphics::lines(curve$date, curve$value, col = "#01665e", lwd = 2)
  graphics::points(d$date, d$mean, pch = 19, col = "#01665e", cex = 0.75)

  if (!is.null(phen) && !is.na(phen$planting_est)) {
    graphics::abline(v = phen$planting_est, col = "#2c7fb8", lwd = 2, lty = 2)
    graphics::text(phen$planting_est, 0.97, " planting", col = "#2c7fb8", adj = 0, cex = 0.8)
    if (!is.na(phen$harvest_est)) {
      graphics::abline(v = phen$harvest_est, col = "#d95f0e", lwd = 2, lty = 2)
      graphics::text(phen$harvest_est, 0.97, " harvest", col = "#d95f0e", adj = 0, cex = 0.8)
    }
  }
  invisible(phen)
}

#' The whole record on one figure, optionally split across stacked panels.
#'
#' A season at a time hides the thing the multi-year record is actually good at
#' showing: the rotation, how planting date moves year to year, and whether
#' anything is growing between seasons. Splitting into chunks keeps the x-axis
#' readable when six or seven years would otherwise be squeezed into one strip.
#'
#' The smoothed curve is fitted per year, never across the whole span -- one
#' smoothing parameter cannot represent seven annual cycles, and fitting
#' globally would flatten every peak.
#'
#' @param panels Number of stacked panels. 1 puts everything on one axis;
#'               2 gives roughly three-year chunks over a 2020-present record.
plot_phenology_timeline <- function(ts, phen = NULL, index = "ndvi", panels = 2,
                                    shade_offseason = TRUE) {

  d <- ts[ts$index == index, ]
  if (nrow(d) < 10) {
    graphics::plot.new(); graphics::title("Not enough data"); return(invisible())
  }

  years  <- sort(unique(as.integer(format(d$date, "%Y"))))
  panels <- max(1, min(panels, length(years)))
  groups <- split(years, ceiling(seq_along(years) / ceiling(length(years) / panels)))

  op <- graphics::par(mfrow = c(length(groups), 1),
                      mar = c(2.6, 4, 2.2, 1), oma = c(0, 0, 0, 0))
  on.exit(graphics::par(op), add = TRUE)

  for (grp in groups) {
    from <- as.Date(sprintf("%d-01-01", min(grp)))
    to   <- as.Date(sprintf("%d-12-31", max(grp)))
    dd   <- d[d$date >= from & d$date <= to, ]

    graphics::plot(c(from, to), c(0, 1), type = "n", xaxt = "n",
                   xlab = "", ylab = toupper(index),
                   main = if (length(grp) == 1) as.character(grp)
                          else sprintf("%d - %d", min(grp), max(grp)))
    graphics::axis.Date(1, at = seq(from, to, by = "3 months"), format = "%b %y",
                        cex.axis = 0.75)
    graphics::grid(nx = NA, ny = NULL, col = "grey93")

    # Off-season shading: everything outside an estimated growing season.
    if (shade_offseason && !is.null(phen)) {
      for (y in grp) {
        p <- phen[phen$year == y, ]
        if (nrow(p) != 1 || is.na(p$planting_est)) next
        prev <- phen[phen$year == y - 1, ]
        left <- if (nrow(prev) == 1 && !is.na(prev$harvest_est)) prev$harvest_est else
          as.Date(sprintf("%d-11-01", y - 1))
        graphics::rect(max(left, from), -1, p$planting_est, 2,
                       col = grDevices::adjustcolor("#5ab4ac", 0.10), border = NA)
      }
    }

    for (y in grp) {
      dy <- dd[format(dd$date, "%Y") == as.character(y), ]
      if (nrow(dy) >= 8) {
        cur <- tryCatch(daily_series(dy, index), error = function(e) NULL)
        if (!is.null(cur)) graphics::lines(cur$date, cur$value, col = "#01665e", lwd = 1.8)
      }
      graphics::abline(v = as.Date(sprintf("%d-01-01", y)), col = "grey80", lty = 3)

      if (is.null(phen)) next
      p <- phen[phen$year == y, ]
      if (nrow(p) != 1) next
      if (!is.na(p$planting_est)) {
        graphics::abline(v = p$planting_est, col = "#2c7fb8", lwd = 1.6, lty = 2)
      }
      if (!is.na(p$harvest_est)) {
        graphics::abline(v = p$harvest_est, col = "#d95f0e", lwd = 1.6, lty = 2)
      }
      if (!is.na(p$crop)) {
        graphics::text(as.Date(sprintf("%d-07-01", y)), 0.045, p$crop,
                       cex = 0.72, col = "grey25")
      }
    }

    graphics::points(dd$date, dd$mean, pch = 19, col = "#01665e", cex = 0.42)
  }

  graphics::legend("bottomright", bty = "n", horiz = TRUE, cex = 0.72,
                   lty = c(2, 2, NA), lwd = c(1.6, 1.6, 8), pch = c(NA, NA, NA),
                   col = c("#2c7fb8", "#d95f0e", grDevices::adjustcolor("#5ab4ac", 0.10)),
                   legend = c("planting", "harvest", "off-season"))
  invisible(groups)
}

# --- residue window -----------------------------------------------------------
# Residue and tillage indices are read between one crop's harvest and the next
# crop's planting, when the surface is bare soil or residue rather than canopy.
# Choosing that window is the part the phenology table can already answer, and
# getting it wrong is a common reason field-level residue estimates disagree
# with what is on the ground.
#
# Nothing here computes a tillage class. The indices this window is meant for
# are registered in indices.R but are uncalibrated, and the published
# field-level accuracy for multispectral tillage classification is around
# 73-80% -- roughly one field in four misclassified. Residue line-transect
# ground truth comes before any verdict.

RESIDUE_HARVEST_LAG <- 7    # days after harvest before residue settles
RESIDUE_PLANT_LEAD  <- 3    # stop before planting disturbs the surface

#' The bare-soil / residue window before a season's planting.
#'
#' @param phen   Phenology table from phenology_all_years().
#' @param year   Crop year whose pre-planting window is wanted.
#' @param season "spring" (default) starts no earlier than 1 March, which is
#'   the window minNDTI-style methods use and which excludes autumn tillage and
#'   most of the snow season. "full" runs from the previous harvest, so it also
#'   covers fall tillage -- at the cost of a much longer window over which soil
#'   moisture varies far more.
#' @return list(start, end, n_days, year, season, source, note), or NULL when
#'   the window is empty or the dates are unusable. `source` is "phenology"
#'   when both ends came from the table, "partial" when one did, "fallback"
#'   when neither -- a caller reporting numbers should say which.
#'
#' @examples
#' w <- residue_window(phen, 2024)
#' d <- ts[ts$index == "ndti" & ts$date >= w$start & ts$date <= w$end, ]
residue_window <- function(phen, year, season = c("spring", "full")) {
  season <- match.arg(season)
  year   <- as.integer(year)

  from_phen <- 0L
  start <- NA
  end   <- NA

  if (!is.null(phen) && nrow(phen)) {
    h <- phen[phen$year == year - 1L, ]
    if (nrow(h) == 1 && !is.na(h$harvest_est)) {
      start <- as.Date(h$harvest_est) + RESIDUE_HARVEST_LAG
      from_phen <- from_phen + 1L
    }
    p <- phen[phen$year == year, ]
    if (nrow(p) == 1 && !is.na(p$planting_est)) {
      end <- as.Date(p$planting_est) - RESIDUE_PLANT_LEAD
      from_phen <- from_phen + 1L
    }
  }

  # Same fallback dates the cover crop module uses, so the two agree on what
  # "the off-season" means when phenology could not pin it down.
  if (is.na(start)) start <- as.Date(sprintf("%d-10-15", year - 1L))
  if (is.na(end))   end   <- as.Date(sprintf("%d-05-10", year))

  if (season == "spring") {
    start <- max(start, as.Date(sprintf("%d-03-01", year)))
  }
  if (end <= start) return(NULL)

  list(
    start   = start,
    end     = end,
    n_days  = as.integer(end - start),
    year    = year,
    season  = season,
    source  = c("fallback", "partial", "phenology")[from_phen + 1L],
    note    = if (from_phen < 2L)
      "one or both ends fall back to fixed dates; phenology had no estimate"
      else NULL
  )
}

#' residue_window() for every year the series covers.
residue_windows <- function(phen, years = NULL, season = c("spring", "full")) {
  season <- match.arg(season)
  if (is.null(years)) {
    if (is.null(phen) || !nrow(phen)) return(NULL)
    years <- sort(unique(phen$year))
  }
  rows <- lapply(years, function(y) {
    w <- residue_window(phen, y, season)
    if (is.null(w)) return(NULL)
    data.frame(year = w$year, season = w$season, start = w$start, end = w$end,
               n_days = w$n_days, source = w$source,
               stringsAsFactors = FALSE)
  })
  rows <- Filter(Negate(is.null), rows)
  if (!length(rows)) return(NULL)
  out <- do.call(rbind, rows)
  rownames(out) <- NULL
  out
}

`%||%` <- function(a, b) if (is.null(a)) b else a
