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
                     n_obs, season_days, conf, season_type = "summer") {
  data.frame(
    year = year, crop = crop %||% NA_character_, season_type = season_type,
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

# --- winter crops and fallow ---------------------------------------------------
# A winter small grain is sown in autumn, emerges, overwinters, greens up again
# in spring, peaks in May-June and is harvested in early summer. The summer
# model above looks for a June-September peak and reads spring green-up as
# planting, so for these crops it misses seasons and puts "planting" in April.
# Checked on two wheat-fallow fields near Akron, Colorado, where the summer
# model dated 3 of 6 wheat seasons, all with April-May "planting" dates.
#
# Season `year` is the HARVEST year; sowing is in the autumn before it.
# Port of python/fieldrs/phenology.py; keep the two in step.
WINTER_CROPS <- c("Winter Wheat", "Rye", "Triticale")
FALLOW_CROPS <- c("Fallow/Idle Cropland")

WINTER_PEAK_WINDOW <- c("03-15", "06-30")   # spring canopy peak, harvest year
WINTER_SOW_SEARCH  <- c("08-01", "10-31")   # bare-soil trough before emergence, prior year
WINTER_FALL_LAST   <- "12-15"               # emergence must show by then; later is spring
WINTER_FALL_MIN_RISE <- 0.08                # NDVI rise that counts as emergence
WINTER_SOW_LAG     <- 14                    # days, sowing to the 20% point of the fall rise
WINTER_SOW_EARLIEST <- "08-15"

# A fallow period is the field between one harvest and the next sowing. Green
# growth inside it is weeds or volunteer grain, which fallow exists to control.
FALLOW_GREEN <- 0.30

.ymd <- function(y, md) as.Date(sprintf("%d-%s", as.integer(y), md))

#' Season markers for a winter crop harvested in `year`.
#'
#' `planting_est` is autumn SOWING (in year - 1), from the rise out of the
#' bare-soil trough as the crop emerges, less WINTER_SOW_LAG. `greenup_date` is
#' spring green-up, `harvest_est` the senescence after the spring peak.
#' @return One-row data frame, or NULL if the crop year is too sparse.
estimate_winter_phenology <- function(ts, year, crop = NULL, index = "ndvi") {
  d <- ts[ts$index == index & ts$date >= .ymd(year - 1, "07-01") &
          ts$date <= .ymd(year, "10-31"), ]
  if (nrow(d) < 10) return(NULL)
  curve <- tryCatch(daily_series(d, index), error = function(e) NULL)
  if (is.null(curve)) return(NULL)
  curve <- curve[!is.na(curve$value), ]
  inpk <- curve[curve$date >= .ymd(year, WINTER_PEAK_WINDOW[1]) &
                curve$date <= .ymd(year, WINTER_PEAK_WINDOW[2]), ]
  if (nrow(inpk) < 10) return(NULL)
  pk <- which.max(inpk$value)
  peak_val <- inpk$value[pk]; peak_date <- inpk$date[pk]
  n_obs <- sum(d$date >= .ymd(year - 1, "08-01"))

  blank <- function(conf) phen_row(year, crop, peak_date, peak_val, NA, NA, NA,
                                   NA, NA, NA, NA, NA, NA, n_obs, NA, conf,
                                   season_type = "winter")
  if (peak_val < 0.45) return(blank("no winter crop detected"))
  # Same perennial test as the summer model, over the crop year: alfalfa's
  # regrowth after a cutting can otherwise pass for autumn emergence.
  cy <- curve[curve$date >= .ymd(year - 1, "08-01"), ]
  ap <- applicability(min(cy$value), mean(cy$value >= 0.50))
  if (!ap$applies) return(blank(ap$note))

  notes <- character(0)
  gaps  <- numeric(0)

  # Sowing: trough in late summer / autumn, then the emergence rise.
  sow <- NA
  tr <- curve[curve$date >= .ymd(year - 1, WINTER_SOW_SEARCH[1]) &
              curve$date <= .ymd(year - 1, WINTER_SOW_SEARCH[2]), ]
  if (!nrow(tr)) {
    notes <- c(notes, "no autumn imagery -- sowing not dated")
  } else {
    t_i <- which.min(tr$value)
    t_val <- tr$value[t_i]; t_date <- tr$date[t_i]
    fall <- curve[curve$date >= t_date & curve$date <= .ymd(year - 1, "12-31"), ]
    rise <- if (nrow(fall)) max(fall$value) - t_val else 0
    if (rise >= WINTER_FALL_MIN_RISE) {
      cross <- fall$date[which(fall$value >= t_val + 0.20 * rise)[1]]
      if (cross <= .ymd(year - 1, WINTER_FALL_LAST)) {
        sow <- max(cross - WINTER_SOW_LAG, .ymd(year - 1, WINTER_SOW_EARLIEST))
        gaps <- c(gaps, nearest_gap(d$date, cross))
      } else {
        notes <- c(notes, "autumn emergence too late to see -- sowing not dated")
      }
    } else {
      notes <- c(notes, paste0("no autumn emergence visible -- sowing not dated ",
                               "(dry autumn, late sowing, or snow)"))
    }
  }

  # Spring green-up: rise from the late-winter low to the peak.
  greenup <- NA; baseline <- NA; amp <- NA
  pre <- curve[curve$date >= .ymd(year, "01-01") & curve$date <= peak_date - 20, ]
  if (nrow(pre) >= 10) {
    gmin <- min(pre$value)
    near <- which(pre$value <= gmin + 0.06)
    baseline <- pre$value[near[length(near)]]
    base_date <- pre$date[near[length(near)]]
    amp <- peak_val - baseline
    up <- curve[curve$date >= base_date & curve$date <= peak_date &
                curve$value >= baseline + 0.20 * amp, ]
    if (amp >= 0.10 && nrow(up)) greenup <- up$date[1]
  }

  # Harvest: senescence after the spring peak.
  harvest <- NA
  after <- curve[curve$date >= peak_date & curve$date <= .ymd(year, "09-30"), ]
  if (nrow(after) >= 10) {
    trough <- min(after$value)
    drop <- peak_val - trough
    if (drop >= 0.20) {
      down <- after[after$value <= trough + 0.20 * drop, ]
      if (nrow(down)) {
        harvest <- down$date[1]
        gaps <- c(gaps, nearest_gap(d$date, harvest))
      }
    }
  }

  win <- function(gap) max(14, ceiling(gap))
  gi <- 1L
  plo <- phi <- hlo <- hhi <- NA
  if (!is.na(sow)) { w <- win(gaps[gi]); gi <- gi + 1L; plo <- sow - w; phi <- sow + w }
  if (!is.na(harvest)) { w <- win(gaps[gi]); hlo <- harvest - w; hhi <- harvest + w }
  conf <- if (is.na(harvest)) paste(c("low -- no clear senescence", notes), collapse = "; ")
          else if (is.na(sow)) paste0("low -- ", paste(notes, collapse = "; "))
          else if (max(gaps) <= 10) "high"
          else if (max(gaps) <= 20) "medium"
          else "low -- sparse imagery near transitions"

  phen_row(year, crop, peak_date, peak_val, greenup, sow, plo, phi,
           harvest, hlo, hhi, baseline, amp, n_obs,
           if (is.na(harvest) || is.na(greenup)) NA else as.integer(harvest - greenup),
           conf, season_type = "winter")
}

#' With no crop label, does the curve read as a winter crop?
#'
#' Only when the winter model resolves autumn emergence (sowing), a spring
#' canopy and its harvest, and the summer model either found no crop or only
#' caught that same canopy's tail at the start of its June window. Autumn
#' emergence is the deciding evidence: a spring-sown crop in the South can peak
#' in early June too, but it has nothing green the autumn before. A perennial
#' the summer model refused stays refused.
looks_winter <- function(summer, winter) {
  if (is.null(winter) || is.na(winter$harvest_est) || is.na(winter$planting_est) ||
      winter$peak_ndvi < 0.45) return(FALSE)
  if (!is.null(summer) && startsWith(summer$confidence, "not an annual row crop"))
    return(FALSE)
  if (is.null(summer) || is.na(summer$planting_est)) return(TRUE)
  tail <- summer$peak_date <= .ymd(summer$year, "06-10")
  tail && summer$peak_ndvi <= winter$peak_ndvi + 0.02
}

#' Fallow start / end / days and green growth, for every fallow row.
fallow_periods <- function(phen, ts, index = "ndvi") {
  is_fallow <- startsWith(phen$season_type, "fallow")
  if (!any(is_fallow)) return(phen)
  phen$fallow_start <- as.Date(NA); phen$fallow_end <- as.Date(NA)
  phen$fallow_days <- NA_integer_; phen$fallow_max_ndvi <- NA_real_
  phen$fallow_green_days <- NA_integer_
  for (i in which(is_fallow)) {
    y <- phen$year[i]
    prev <- phen[phen$year == y - 1, ]; nxt <- phen[phen$year == y + 1, ]
    start <- if (nrow(prev)) prev$harvest_est else as.Date(NA)
    end   <- if (nrow(nxt)) nxt$planting_est else as.Date(NA)
    phen$fallow_start[i] <- start; phen$fallow_end[i] <- end
    if (!is.na(start) && !is.na(end)) phen$fallow_days[i] <- as.integer(end - start)
    lo <- if (is.na(start)) .ymd(y, "01-01") else start
    hi <- if (is.na(end)) .ymd(y, "12-31") else end
    d <- ts[ts$index == index & ts$date >= lo - 45 & ts$date <= hi + 45, ]
    c <- tryCatch(daily_series(d, index), error = function(e) NULL)
    if (!is.null(c)) {
      c <- c[!is.na(c$value) & c$date >= lo & c$date <= hi, ]
      if (nrow(c)) phen$fallow_max_ndvi[i] <- round(max(c$value), 3)
      phen$fallow_green_days[i] <- sum(c$value >= FALLOW_GREEN)
      if (phen$fallow_green_days[i] > 0) {
        phen$confidence[i] <- sprintf(
          "%s; green growth during fallow on %d days -- weeds or volunteer grain",
          phen$confidence[i], phen$fallow_green_days[i])
      }
    }
  }
  phen
}

#' Season markers for every year present in the series.
#'
#' The CDL crop picks the model: winter crops (WINTER_CROPS) get
#' estimate_winter_phenology(), fallow years (FALLOW_CROPS) a fallow row with
#' the fallow period, everything else the summer model. A year with no CDL
#' label yet is read from the curve -- see looks_winter(). `season_type` says
#' which: summer, winter, winter (from curve), fallow, fallow (from curve).
#'
#' @param crops Optional named vector, year -> crop name, from CDL.
phenology_all_years <- function(ts, crops = NULL, index = "ndvi") {
  years <- sort(unique(as.integer(format(ts$date, "%Y"))))
  rows <- lapply(years, function(y) {
    crop <- if (!is.null(crops) && as.character(y) %in% names(crops))
      unname(crops[[as.character(y)]]) else NULL
    if (!is.null(crop) && is.na(crop)) crop <- NULL
    if (!is.null(crop) && crop %in% WINTER_CROPS) {
      return(estimate_winter_phenology(ts, y, crop, index))
    }
    if (!is.null(crop) && crop %in% FALLOW_CROPS) {
      r <- estimate_phenology(ts, y, crop, index)
      if (!is.null(r) && !is.na(r$planting_est)) {
        r$confidence <- paste0(r$confidence, "; CDL says fallow but NDVI shows a ",
                               "summer canopy -- weeds, or a CDL error")
        return(r)
      }
      if (is.null(r)) r <- phen_row(y, crop, NA, NA, NA, NA, NA, NA, NA, NA, NA,
                                    NA, NA, NA, NA, "")
      r$season_type <- "fallow"; r$confidence <- "fallow (CDL)"
      return(r)
    }
    if (is.null(crop)) {
      summer <- estimate_phenology(ts, y, NULL, index)
      winter <- estimate_winter_phenology(ts, y, NULL, index)
      if (looks_winter(summer, winter)) {
        winter$season_type <- "winter (from curve)"
        winter$confidence <- paste0(winter$confidence, "; no CDL for this year -- ",
                                    "winter crop read from the NDVI curve")
        return(winter)
      }
      if (!is.null(summer) && is.na(summer$planting_est) &&
          startsWith(summer$confidence, "no summer crop") &&
          (is.null(winter) || is.na(winter$harvest_est))) {
        # Neither a summer nor a winter canopy: fallow, or idle.
        summer$season_type <- "fallow (from curve)"
        summer$confidence <- paste0("no crop in the NDVI and no CDL yet -- fallow ",
                                    "or idle, read from the curve")
        return(summer)
      }
      return(summer)
    }
    estimate_phenology(ts, y, crop, index)
  })
  rows <- Filter(Negate(is.null), rows)
  if (!length(rows)) return(NULL)
  fallow_periods(do.call(rbind, rows), ts, index)
}

plot_phenology <- function(ts, year, phen = NULL, crop = NULL, index = "ndvi",
                           weather = NULL, wind_max_kmh = NULL) {
  # A winter crop's season starts in the autumn before its harvest year.
  winter <- !is.null(phen) && nrow(phen) && "season_type" %in% names(phen) &&
    startsWith(phen$season_type[1], "winter")
  lo <- if (winter) as.Date(sprintf("%d-08-01", year - 1)) else as.Date(sprintf("%d-01-01", year))
  hi <- if (winter) as.Date(sprintf("%d-10-31", year)) else as.Date(sprintf("%d-12-31", year))
  d <- ts[ts$index == index & ts$date >= lo & ts$date <= hi, ]
  if (nrow(d) < 5) { graphics::plot.new(); graphics::title("Not enough data"); return(invisible()) }

  curve <- tryCatch(daily_series(d, index), error = function(e) NULL)
  if (is.null(phen)) phen <- estimate_phenology(ts, year, crop, index)

  title <- if (winter) sprintf("%d-%s", year - 1, substr(year, 3, 4)) else as.character(year)
  if (!is.null(crop) && !is.na(crop) && nzchar(crop)) title <- paste0(title, "  |  ", crop)
  if (!is.null(phen) && "season_type" %in% names(phen) && phen$season_type[1] != "summer")
    title <- sprintf("%s  (%s)", title, phen$season_type[1])

  graphics::par(mar = c(4, 4, 3, 4))
  graphics::plot(c(lo, hi), c(0, 1), type = "n", xlab = "", ylab = toupper(index), main = title)
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

  # Daily rain hanging from the top on its own axis; with a wind limit, grey
  # ticks along the bottom on days at or over it.
  if (!is.null(weather) && "pr_mm" %in% names(weather) && nrow(weather)) {
    w <- weather[weather$date >= lo & weather$date <= hi, ]
    if (nrow(w)) {
      if (!is.null(wind_max_kmh) && "wind_kmh" %in% names(w)) {
        windy <- w$date[!is.na(w$wind_kmh) & w$wind_kmh >= wind_max_kmh]
        graphics::points(windy, rep(0.012, length(windy)), pch = "|", col = "#777777", cex = 0.8)
      }
      top <- max(w$pr_mm, 1, na.rm = TRUE) * 3
      graphics::par(new = TRUE)
      graphics::plot(w$date, w$pr_mm, type = "h", lwd = 2, col = grDevices::adjustcolor("#6a8caf", 0.45),
                     xlim = c(lo, hi), ylim = c(top, 0), axes = FALSE, xlab = "", ylab = "")
      graphics::axis(4, col.axis = "#6a8caf", cex.axis = 0.75)
      graphics::mtext("rain (mm/day)", side = 4, line = 2.4, col = "#6a8caf", cex = 0.75)
      graphics::par(new = TRUE)
      graphics::plot(c(lo, hi), c(0, 1), type = "n", axes = FALSE, xlab = "", ylab = "")
    }
  }

  # NDVI estimates dashed; weather-checked final dates solid beside them.
  if (!is.null(phen)) {
    for (ev in c("planting", "harvest")) {
      colour <- if (ev == "planting") "#2c7fb8" else "#d95f0e"
      est <- phen[[paste0(ev, "_est")]][1]
      if (is.null(est) || is.na(est)) next
      fin <- if (paste0(ev, "_date") %in% names(phen)) phen[[paste0(ev, "_date")]][1] else NA
      graphics::abline(v = est, col = colour, lwd = if (is.na(fin)) 2 else 1.5, lty = 2)
      if (!is.na(fin)) graphics::abline(v = fin, col = colour, lwd = 2.5)
      graphics::text(if (is.na(fin)) est else fin, 0.03, paste0(" ", ev), col = colour,
                     adj = 0, cex = 0.8)
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
    # A winter crop was sown the autumn before: its spring is canopy, not a
    # pre-planting period -- even when the sowing date itself is unknown.
    cur <- phen[phen$year == year, ]
    if (nrow(cur) == 1 && "season_type" %in% names(cur) &&
        startsWith(as.character(cur$season_type), "winter")) return(NULL)
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
