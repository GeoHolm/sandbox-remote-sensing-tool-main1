# ==============================================================================
# covercrop.R -- Off-season green cover from NDVI
#
# WHAT THE SIGNAL IS
# After a corn or soybean harvest an Iowa field is crop residue: NDVI settles
# around 0.10-0.25 and stays there until spring. A planted cover crop -- cereal
# rye being the common one -- establishes in autumn, goes near-dormant over
# winter, and greens up again in March/April before termination. On the NDVI
# curve that shows up as a distinct off-season hump above the residue floor.
#
# WHAT IT IS NOT
# NDVI sees green, not intent. It cannot by itself separate a planted cover
# crop from volunteer grain, winter annual weeds, or a grassed waterway inside
# the boundary. Those all look like modest winter greenness. This module
# therefore reports evidence and names the confounders rather than asserting a
# practice, and the thresholds below are literature-typical starting points
# that should be calibrated against known cover-cropped fields before anyone
# leans on the output.
#
# Snow is handled upstream: the SCL mask drops snow-covered pixels, so snowy
# dates disappear from the record rather than reading as bare soil. That is the
# right behaviour, but it thins winter coverage -- which is why `n_obs` is
# reported alongside every call.
# ==============================================================================

# NDVI floor for crop residue, and the level sustained green has to reach.
CC_RESIDUE_MAX <- 0.25
CC_GREEN_MIN   <- 0.30
CC_STRONG      <- 0.35

# Open water reads as negative NDVI. Rice ground is commonly flooded through the
# winter -- for waterfowl habitat and to rot down residue -- and you cannot see
# a cover crop under water. Reporting "no cover crop detected" there would be
# misleading: nothing was detectable either way.
CC_WATER_NDVI  <- 0.05
CC_WATER_SHARE <- 0.25      # share of window observations under water

#' Assess off-season green cover for the winter following `fall_year`.
#'
#' The window runs from that autumn's harvest to the next spring's planting,
#' taken from the phenology table when available and falling back to fixed
#' Iowa-typical dates when not.
#'
#' @param ts        Series from extract_field_series().
#' @param fall_year Year of the autumn the window starts in.
#' @param phen      Optional phenology table, used to bound the window.
#' @param next_crop Optional CDL crop for fall_year + 1, to flag winter cash crops.
#' @return One-row data frame of evidence and a verdict.
detect_cover_crop <- function(ts, fall_year, phen = NULL, next_crop = NULL,
                              index = "ndvi") {

  # --- window ---------------------------------------------------------------
  win_start <- as.Date(sprintf("%d-10-15", fall_year))
  win_end   <- as.Date(sprintf("%d-05-10", fall_year + 1))

  if (!is.null(phen)) {
    h <- phen[phen$year == fall_year, ]
    if (nrow(h) == 1 && !is.na(h$harvest_est)) win_start <- h$harvest_est + 7
    p <- phen[phen$year == fall_year + 1, ]
    if (nrow(p) == 1 && !is.na(p$planting_est)) win_end <- p$planting_est - 3
  }
  if (win_end <= win_start) return(NULL)

  d <- ts[ts$index == index & ts$date >= win_start & ts$date <= win_end, ]

  if (nrow(d) < 4) {
    return(cc_row(fall_year, win_start, win_end, nrow(d), NA, NA, NA, NA,
                  "insufficient data",
                  sprintf("Only %d clear observations in the window; winter cloud and snow often leave too little to judge.", nrow(d))))
  }

  max_ndvi  <- max(d$mean)
  mean_ndvi <- mean(d$mean)
  peak_date <- d$date[which.max(d$mean)]
  n_green   <- sum(d$mean >= CC_GREEN_MIN)

  # Days of sustained green, from the smoothed curve, gaps left as NA.
  #
  # The spline is fitted to the window plus a margin, never to the whole
  # multi-year record: one smoothing parameter cannot represent six annual
  # cycles at once, and fitting globally would flatten exactly the off-season
  # hump we are trying to measure.
  green_days <- NA_integer_
  local_ts <- ts[ts$index == index &
                 ts$date >= win_start - 45 & ts$date <= win_end + 45, ]
  curve <- tryCatch(daily_series(local_ts, index, spar = 0.5),
                    error = function(e) NULL)
  if (!is.null(curve)) {
    w <- curve[curve$date >= win_start & curve$date <= win_end & !is.na(curve$value), ]
    if (nrow(w)) green_days <- sum(w$value >= CC_GREEN_MIN)
  }

  # --- applicability ---------------------------------------------------------
  # A perennial is green all year, so "off-season cover" is not a meaningful
  # question -- what is green in January is the same stand that was green in
  # July, not a cover crop sown after harvest.
  if (!is.null(phen)) {
    h <- phen[phen$year == fall_year, ]
    if (nrow(h) == 1 && grepl("not an annual row crop", h$confidence[1])) {
      return(cc_row(fall_year, win_start, win_end, nrow(d), max_ndvi, mean_ndvi,
                    peak_date, green_days,
                    "perennial stand -- off-season cover not applicable",
                    sprintf(paste0("The season analysis found no bare-soil ",
                                   "period for %d, so this field carries a ",
                                   "perennial or multi-cut stand. Winter ",
                                   "greenness is that stand, not a cover crop ",
                                   "sown after harvest."), fall_year)))
    }
  }

  # Standing water: if much of the window is flooded there may be nothing to
  # see, which is a different answer from "bare ground". But only call it
  # undetectable when no real green showed up -- a window reaching 0.64 plainly
  # did detect something, whatever was under water earlier.
  n_water <- sum(d$mean < CC_WATER_NDVI)
  flooded <- (n_water / nrow(d)) >= CC_WATER_SHARE
  if (flooded && max_ndvi < CC_STRONG) {
    return(cc_row(fall_year, win_start, win_end, nrow(d), max_ndvi, mean_ndvi,
                  peak_date, green_days,
                  "off-season flooded -- cover crop not detectable",
                  sprintf(paste0("%d of %d observations are open water (NDVI ",
                                 "below %.2f), typical of rice ground held ",
                                 "flooded over winter, and nothing green rose ",
                                 "above %.2f. A cover crop could not have been ",
                                 "seen under water, so this is 'unknown', not ",
                                 "'none'."),
                          n_water, nrow(d), CC_WATER_NDVI, CC_STRONG)))
  }
  water_note <- if (flooded) {
    sprintf(paste0(" Note: %d of %d observations are open water, so part of ",
                   "this window was flooded and any earlier establishment ",
                   "would have been hidden."), n_water, nrow(d))
  } else ""

  # --- verdict --------------------------------------------------------------
  winter_cash <- !is.null(next_crop) && !is.na(next_crop) &&
    grepl("Winter Wheat|Triticale|Rye|Barley|Canola|Dbl Crop", next_crop)

  # A cash crop going in after roughly 10 June, on the back of a strong spring
  # green-up, is the signature of double cropping after a small grain rather
  # than of a cover crop that was terminated. CDL often still labels the field
  # by the summer crop alone, so the crop name will not catch this.
  late_planting <- NA_integer_
  if (!is.null(phen)) {
    p <- phen[phen$year == fall_year + 1, ]
    if (nrow(p) == 1 && !is.na(p$planting_est)) {
      late_planting <- as.integer(format(p$planting_est, "%j"))
    }
  }
  double_crop <- !is.na(late_planting) && late_planting > 161 && max_ndvi >= CC_STRONG

  if (winter_cash) {
    verdict <- "winter cash crop, not a cover crop"
    notes   <- sprintf("CDL records %s for %d, which is a harvested winter crop. The green signal is that crop.",
                       next_crop, fall_year + 1)
  } else if (double_crop) {
    verdict <- "green cover -- cover crop or small grain"
    notes   <- sprintf("Off-season NDVI peaks at %.2f on %s, but the next cash crop does not go in until %s. That late planting after a strong spring green-up is equally consistent with a harvested small grain followed by double-crop soybeans. Needs the grower record to separate.",
                       max_ndvi, format(peak_date, "%d %b"),
                       format(as.Date(late_planting - 1, origin = sprintf("%d-01-01", fall_year + 1)), "%d %b"))
  } else if (max_ndvi >= CC_STRONG && n_green >= 2) {
    verdict <- "likely cover crop"
    notes   <- sprintf("Off-season NDVI peaks at %.2f on %s with %d observations above %.2f -- well clear of the %.2f residue ceiling.",
                       max_ndvi, format(peak_date, "%d %b"), n_green, CC_GREEN_MIN, CC_RESIDUE_MAX)
  } else if (max_ndvi >= CC_GREEN_MIN) {
    verdict <- "possible cover crop"
    notes   <- sprintf("Off-season NDVI reaches %.2f, above residue but not sustained (%d observation(s) above %.2f). Volunteer grain or winter weeds look like this too.",
                       max_ndvi, n_green, CC_GREEN_MIN)
  } else {
    verdict <- "no cover crop detected"
    notes   <- sprintf("Off-season NDVI stays at or below %.2f, consistent with bare soil and crop residue.",
                       max_ndvi)
  }

  cc_row(fall_year, win_start, win_end, nrow(d), max_ndvi, mean_ndvi,
         peak_date, green_days, verdict, paste0(notes, water_note))
}

cc_row <- function(year, ws, we, n_obs, mx, mn, pk, gd, verdict, notes) {
  data.frame(
    winter       = sprintf("%d-%s", year, substr(year + 1, 3, 4)),
    fall_year    = year,
    window_start = ws, window_end = we,
    n_obs        = n_obs,
    max_ndvi     = if (is.na(mx)) NA_real_ else round(mx, 3),
    mean_ndvi    = if (is.na(mn)) NA_real_ else round(mn, 3),
    peak_date    = as.Date(pk),
    green_days   = gd,
    verdict      = verdict,
    notes        = notes,
    stringsAsFactors = FALSE, row.names = NULL
  )
}

#' Run cover crop detection across every winter in the series.
cover_crop_all_years <- function(ts, phen = NULL, crops = NULL, index = "ndvi") {
  years <- sort(unique(as.integer(format(ts$date, "%Y"))))
  years <- utils::head(years, -1)   # last year has no following spring yet
  rows <- lapply(years, function(y) {
    nc <- if (!is.null(crops) && as.character(y + 1) %in% names(crops))
      unname(crops[[as.character(y + 1)]]) else NULL
    detect_cover_crop(ts, y, phen, nc, index)
  })
  rows <- Filter(Negate(is.null), rows)
  if (!length(rows)) return(NULL)
  do.call(rbind, rows)
}

#' Every off-season on one figure, as small multiples.
#'
#' Each panel is put on a common Oct-to-Jun axis rather than its own window, so
#' the winters line up and can be read against each other: a cover-cropped year
#' and a bare one are obvious side by side in a way they never are when you have
#' to click through them one at a time.
plot_cover_crop_matrix <- function(ts, cc, index = "ndvi", ncol = NULL) {
  if (is.null(cc) || !nrow(cc)) {
    graphics::plot.new(); graphics::title("No off-season windows"); return(invisible())
  }

  n  <- nrow(cc)
  nc <- ncol %||% min(3, n)
  nr <- ceiling(n / nc)

  # Left margin has to hold the axis numbers and the label; at the default the
  # label is drawn into the neighbouring panel and gets clipped.
  op <- graphics::par(mfrow = c(nr, nc), mar = c(2.4, 4.0, 2.4, 1.0),
                      mgp = c(2.2, 0.6, 0), oma = c(0, 0, 0, 0))
  on.exit(graphics::par(op), add = TRUE)

  # Common axis: days since 1 October of the autumn the window starts in.
  ticks <- c(0, 61, 122, 182, 243)
  labs  <- c("Oct", "Dec", "Feb", "Apr", "Jun")

  for (k in seq_len(n)) {
    r   <- cc[k, ]
    ref <- as.Date(sprintf("%d-10-01", r$fall_year))

    d <- ts[ts$index == index &
            ts$date >= ref - 20 & ts$date <= ref + 260, ]
    x <- as.numeric(d$date - ref)

    tone <- verdict_tone(r$verdict)

    graphics::plot(c(-20, 260), c(0, 0.8), type = "n", xaxt = "n",
                   xlab = "", ylab = toupper(index), cex.axis = 0.8)
    graphics::axis(1, at = ticks, labels = labs, cex.axis = 0.8)

    graphics::rect(as.numeric(r$window_start - ref), -1,
                   as.numeric(r$window_end - ref), 2,
                   col = grDevices::adjustcolor(tone, 0.13), border = NA)
    graphics::abline(h = CC_RESIDUE_MAX, col = "#8c510a", lty = 3)
    graphics::abline(h = CC_GREEN_MIN,   col = "#01665e", lty = 3)

    if (nrow(d)) {
      graphics::lines(x, d$mean, col = "#01665e", lwd = 1.5)
      graphics::points(x, d$mean, pch = 19, col = "#01665e", cex = 0.6)
    }

    graphics::title(main = r$winter, cex.main = 1.05, line = 1.15)
    graphics::mtext(sprintf("%s  (max %.2f, n=%d)",
                            short_verdict(r$verdict), r$max_ndvi, r$n_obs),
                    side = 3, line = 0.15, cex = 0.62, col = tone)
  }
  invisible(n)
}

verdict_tone <- function(v) {
  if (grepl("^likely", v)) "#01665e"
  else if (grepl("small grain|possible", v)) "#b8860b"
  else if (grepl("winter cash", v)) "#7570b3"
  else "#8c510a"
}

short_verdict <- function(v) {
  if (grepl("^likely", v)) "likely cover crop"
  else if (grepl("small grain", v)) "cover crop or small grain"
  else if (grepl("^possible", v)) "possible"
  else if (grepl("winter cash", v)) "winter cash crop"
  else if (grepl("insufficient", v)) "insufficient data"
  else "none detected"
}

#' Plot one off-season window with the residue and green thresholds drawn on.
plot_cover_crop <- function(ts, cc, index = "ndvi") {
  if (is.null(cc) || nrow(cc) != 1) {
    graphics::plot.new(); graphics::title("No off-season window"); return(invisible())
  }
  pad <- 30
  d <- ts[ts$index == index &
          ts$date >= cc$window_start - pad & ts$date <= cc$window_end + pad, ]
  if (nrow(d) < 3) {
    graphics::plot.new(); graphics::title("Not enough off-season data"); return(invisible())
  }

  graphics::par(mar = c(4, 4, 3, 1))
  graphics::plot(d$date, d$mean, type = "n", ylim = c(0, 1),
                 xlab = "", ylab = toupper(index),
                 main = sprintf("Off-season %s  |  %s", cc$winter, cc$verdict))

  graphics::rect(cc$window_start, -1, cc$window_end, 2,
                 col = grDevices::adjustcolor("#5ab4ac", 0.10), border = NA)
  graphics::abline(h = CC_RESIDUE_MAX, col = "#8c510a", lty = 3)
  graphics::abline(h = CC_GREEN_MIN,   col = "#01665e", lty = 3)
  graphics::grid(col = "grey92")

  graphics::lines(d$date, d$mean, col = "#01665e", lwd = 1.5)
  graphics::points(d$date, d$mean, pch = 19, col = "#01665e", cex = 0.8)

  graphics::text(cc$window_start, CC_RESIDUE_MAX + 0.02, " residue ceiling",
                 adj = 0, cex = 0.7, col = "#8c510a")
  graphics::text(cc$window_start, CC_GREEN_MIN + 0.02, " sustained green",
                 adj = 0, cex = 0.7, col = "#01665e")
  invisible(cc)
}
