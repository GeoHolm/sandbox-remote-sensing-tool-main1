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
# PROVENANCE -- read METHODS.md before quoting these as literature values.
# 0.30 has a traceable chain of use in the cover crop remote sensing work
# (Hively 2015, southeastern Pennsylvania; KC 2021, Maumee watershed) but the
# number has not been verified against either primary text, and those studies
# apply it to a seasonal field average rather than to single observations the
# way this module does. 0.35 and 0.25 have no source at all. This comment used
# to say the thresholds were Corn Belt values; the lineage is Mid-Atlantic.
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

    # A winter cash crop occupies the off-season: it is sown in the autumn, so
    # there is no gap before it to look for a cover crop in. Caught here,
    # before the window is built from its (autumn) planting date -- which would
    # close the window and drop the winter -- whether CDL names it or the
    # season model read it from the curve because CDL is not out yet.
    stype <- if (nrow(p) == 1 && "season_type" %in% names(p)) p$season_type else ""
    if (startsWith(stype, "winter")) {
      d <- ts[ts$index == index & ts$date >= win_start & ts$date <= win_end, ]
      sown <- p$planting_est
      when <- if (!is.na(sown)) paste0(" sown about ", format(sown, "%d %b %Y")) else ""
      src <- if (!is.null(next_crop) && !is.na(next_crop))
        sprintf("CDL records %s for %d", next_crop, fall_year + 1)
      else sprintf(paste0("CDL for %d is not published yet; the NDVI curve ",
                          "shows an autumn emergence, a spring peak and an ",
                          "early-summer senescence -- a winter grain"), fall_year + 1)
      return(cc_row(fall_year, win_start, win_end, nrow(d),
                    if (nrow(d)) max(d$mean) else NA,
                    if (nrow(d)) mean(d$mean) else NA,
                    if (nrow(d)) d$date[which.max(d$mean)] else NA,
                    NA, "winter cash crop, not a cover crop",
                    paste0(src, when, ". The green signal is that crop.")))
    }
    if (nrow(p) == 1 && !is.na(p$planting_est)) win_end <- p$planting_est - 3
  }
  if (win_end <= win_start) return(NULL)

  d <- ts[ts$index == index & ts$date >= win_start & ts$date <= win_end, ]

  # A winter leading into a hay year is that perennial stand establishing (or
  # regrowing), not a cover crop sown to be terminated: on the Washington pivot
  # the autumn 2024 green-up after the potato harvest is the 2025 alfalfa going
  # in. Known from the crop sequence, so it needs no minimum of observations. A
  # winter after an established perennial year is left to the "perennial stand"
  # rule below.
  if (!is.null(phen) && nrow(phen) && (fall_year + 1) %in% forage_years(phen) &&
      !cc_perennial(phen, fall_year)) {
    return(cc_row(fall_year, win_start, win_end, nrow(d),
                  if (nrow(d)) max(d$mean) else NA,
                  if (nrow(d)) mean(d$mean) else NA,
                  if (nrow(d)) d$date[which.max(d$mean)] else NA,
                  NA, "perennial stand establishing -- not a cover crop",
                  cc_establishing_note(phen, fall_year, next_crop)))
  }

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
  if (!is.null(phen) && cc_perennial(phen, fall_year)) {
    return(cc_row(fall_year, win_start, win_end, nrow(d), max_ndvi, mean_ndvi,
                  peak_date, green_days,
                  "perennial stand -- off-season cover not applicable",
                  sprintf(paste0("The season analysis found no bare-soil ",
                                 "period for %d, so this field carries a ",
                                 "perennial or multi-cut stand. Winter ",
                                 "greenness is that stand, not a cover crop ",
                                 "sown after harvest."), fall_year)))
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

  nxt <- if (!is.null(phen) && "season_type" %in% names(phen))
    phen[phen$year == fall_year + 1, ] else NULL
  no_cdl <- is.null(next_crop) || is.na(next_crop)
  if (!is.null(nxt) && nrow(nxt) == 1 && startsWith(nxt$season_type, "fallow") &&
      verdict %in% c("likely cover crop", "possible cover crop")) {
    notes <- paste0(notes, sprintf(paste0(
      " %d is a fallow year, so green growth after the summer harvest is more ",
      "often volunteer grain or weeds than a planted cover -- unless a cover ",
      "crop was sown into the fallow."), fall_year + 1))
  } else if (no_cdl && verdict != "no cover crop detected") {
    notes <- paste0(notes, sprintf(paste0(
      " CDL for %d is not published yet, and a winter grain sown in the autumn ",
      "would look much the same until its spring peak and summer harvest show ",
      "-- check again then."), fall_year + 1))
  }

  cc_row(fall_year, win_start, win_end, nrow(d), max_ndvi, mean_ndvi,
         peak_date, green_days, verdict, paste0(notes, water_note))
}

# The season model found no bare-soil period in `year`.
cc_perennial <- function(phen, year) {
  h <- phen[phen$year == year, ]
  nrow(h) == 1 && grepl("not an annual row crop", h$confidence[1], fixed = TRUE)
}

cc_establishing_note <- function(phen, fall_year, next_crop) {
  y <- fall_year + 1
  crop <- if (!is.null(next_crop) && !is.na(next_crop) &&
              next_crop %in% FORAGE_CROPS) next_crop else NA
  what <- if (!is.na(crop)) sprintf("CDL records %s for %d", crop, y)
    else sprintf(paste0("%d reads as a hay year (CDL not published yet, %d was ",
                        "forage and %d shows no bare-soil period)"), y, fall_year, y)
  seed <- .phen_value(phen, y, "establishment_est")
  when <- if (!is.na(seed))
    sprintf(paste0("The curve dates the stand's seeding to about %s, so the ",
                   "green-up after the %d harvest is that stand establishing"),
            format(seed, "%d %b %Y"), fall_year)
  else sprintf(paste0("No stand seeding date could be read from the curve, but ",
                      "green leading into %d is that stand establishing or ",
                      "regrowing"), y)
  paste0(what, ", a perennial or multi-cut forage. ", when, ", not a cover crop ",
         "sown to be terminated before a cash crop. No cover seeding or ",
         "termination dates are given.")
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
# --- seeding and termination dates -------------------------------------------
# Inferred the same way the cash crop dates are: from where the curve turns, not
# from anything that sees the drill or the sprayer. The lags and thresholds are
# literature-typical starting values, set by eye against the cover-cropped
# fields in data/fields/ -- none is fitted to recorded seeding or termination
# dates. Treat the dates as low-to-medium confidence until they are.
# Port of python/fieldrs/covercrop.py; keep the two in step.
#
# Seeding: after the cash harvest the curve falls to a trough (residue), then
# rises as the cover establishes. The 20% point of that rise, minus the time a
# small grain takes to emerge and cover enough soil to move NDVI, is seeding.
# A cover sown into the standing crop is already green at harvest and has no
# post-harvest trough to date from; a late-sown one may show nothing until
# spring. Both are reported, not guessed.
#
# Termination: before the cash crop the curve falls from the cover's last
# spring hump to bare soil. The midpoint of that decline, minus the lag between
# spraying and browning, is termination.
COVER_SEED_LAG      <- 14      # days: seeding to the 20% point of the fall rise
COVER_TERM_LAG      <- 7       # days: termination to the midpoint of the decline
COVER_TROUGH_SEARCH <- c(-7, 45)   # days around cash harvest to find the trough
COVER_FALL_SEARCH   <- 100     # days after the trough to find the fall peak
COVER_SEED_MAX      <- 90      # fall rise must start within this many days of harvest
COVER_SEED_LAST     <- "01-31" # ...and by this date; later is spring regrowth
COVER_MIN_RISE      <- 0.08    # NDVI rise that counts as establishment
COVER_PEAK_SEARCH   <- 100     # days before the pre-plant trough to find the last hump
COVER_MIN_DROP      <- 0.10    # NDVI fall that counts as termination

# Verdicts for which the green signal is (or may be) a cover crop.
COVER_DATED_VERDICTS <- c("likely cover crop", "possible cover crop",
                          "green cover -- cover crop or small grain")

.phen_value <- function(phen, year, col) {
  if (is.null(phen) || !nrow(phen) || !col %in% names(phen)) return(as.Date(NA))
  r <- phen[phen$year == year, ]
  if (nrow(r) != 1) return(as.Date(NA))
  as.Date(r[[col]])
}

#' Seeding and termination estimates for one off-season.
#'
#' @param cc One row from detect_cover_crop().
#' @return One-row data frame: seeding_est/lo/hi, termination_est/lo/hi,
#'   cover_days, dates_confidence, dates_note. Dates are NA where the curve
#'   does not support one, with the reason in dates_note. Only winters whose
#'   verdict is a (possible) cover crop are dated.
cover_crop_dates <- function(ts, cc, phen = NULL, index = "ndvi") {
  out <- data.frame(seeding_est = as.Date(NA), seeding_lo = as.Date(NA),
                    seeding_hi = as.Date(NA), termination_est = as.Date(NA),
                    termination_lo = as.Date(NA), termination_hi = as.Date(NA),
                    cover_days = NA_integer_, dates_confidence = NA_character_,
                    dates_note = NA_character_, stringsAsFactors = FALSE)
  if (!cc$verdict %in% COVER_DATED_VERDICTS) return(out)
  y <- as.integer(cc$fall_year)
  notes <- character(0)
  harvest  <- .phen_value(phen, y, "harvest_est")
  planting <- .phen_value(phen, y + 1, "planting_est")
  greenup  <- .phen_value(phen, y + 1, "greenup_date")
  ws <- as.Date(cc$window_start); we <- as.Date(cc$window_end)

  # The cash crop's green-up closes the off-season; without one, a month past
  # the window end stands in for it.
  seg_end <- if (!is.na(greenup)) greenup else if (!is.na(planting)) planting + 21 else we + 30
  anchor <- if (!is.na(harvest)) harvest else ws
  seg_start <- anchor + COVER_TROUGH_SEARCH[1]
  d <- ts[ts$index == index & ts$date >= seg_start - 45 & ts$date <= seg_end + 45, ]
  curve <- tryCatch(daily_series(d, index), error = function(e) NULL)
  if (is.null(curve)) { out$dates_note <- "too few observations to date"; return(out) }
  curve <- curve[!is.na(curve$value) & curve$date >= seg_start & curve$date <= seg_end, ]
  if (nrow(curve) < 30) { out$dates_note <- "too few observations to date"; return(out) }
  gaps <- numeric(0)

  # --- seeding ---------------------------------------------------------------
  tr <- curve[curve$date >= anchor + COVER_TROUGH_SEARCH[1] &
              curve$date <= anchor + COVER_TROUGH_SEARCH[2], ]
  seed <- as.Date(NA)
  if (nrow(tr)) {
    ti <- which.min(tr$value); t_val <- tr$value[ti]; t_date <- tr$date[ti]
    fall <- curve[curve$date >= t_date & curve$date <= t_date + COVER_FALL_SEARCH, ]
    rise <- if (nrow(fall)) max(fall$value) - t_val else 0
    if (rise >= COVER_MIN_RISE && max(fall$value) >= CC_GREEN_MIN) {
      cross <- fall$date[which(fall$value >= t_val + 0.20 * rise)[1]]
      last <- min(anchor + COVER_SEED_MAX, as.Date(sprintf("%d-%s", y + 1, COVER_SEED_LAST)))
      if (cross <= last) {
        seed <- cross - COVER_SEED_LAG
        if (!is.na(harvest) && seed < harvest) {
          seed <- harvest
          notes <- c(notes, paste0("fall rise starts at harvest -- seeded at harvest, ",
                                   "or interseeded into the standing crop (not separable)"))
        }
        gaps <- c(gaps, nearest_gap(d$date, cross))
      } else {
        notes <- c(notes, paste0("fall rise too late to be establishment -- seeding not ",
                                 "dated (late-sown, or green-up only in spring)"))
      }
    } else {
      notes <- c(notes, paste0("no fall green-up after harvest -- seeding not dated ",
                               "(late-sown, or established only in spring)"))
    }
  } else {
    notes <- c(notes, "no post-harvest trough -- seeding not dated")
  }

  # --- termination -----------------------------------------------------------
  term <- as.Date(NA)
  pre <- curve[curve$date >= seg_end - 120, ]
  if (!is.na(seed)) pre <- pre[pre$date > seed, ]
  if (nrow(pre)) {
    fi <- which.min(pre$value); fl_val <- pre$value[fi]; fl_date <- pre$date[fi]
    hump <- curve[curve$date >= fl_date - COVER_PEAK_SEARCH & curve$date < fl_date, ]
    # The hump has to be the cover: after it was sown, and inside the
    # off-season window -- never the tail of the cash crop before it.
    hump <- hump[hump$date >= ws, ]
    if (!is.na(seed)) hump <- hump[hump$date > seed, ]
    if (nrow(hump)) {
      pi <- which.max(hump$value); pk_val <- hump$value[pi]; pk_date <- hump$date[pi]
      drop <- pk_val - fl_val
      if (fl_val < CC_WATER_NDVI) {
        # The fall ends in open water: a flooded field, not a terminated cover.
        notes <- c(notes, paste0("decline ends in standing water -- flooding, not ",
                                 "termination; not dated"))
      } else if (drop >= COVER_MIN_DROP && pk_val >= CC_GREEN_MIN) {
        mid <- fl_val + 0.5 * drop
        dec <- curve[curve$date > pk_date & curve$date <= fl_date & curve$value <= mid, ]
        cross <- dec$date[1]
        term <- max(cross - COVER_TERM_LAG, pk_date)
        gaps <- c(gaps, nearest_gap(d$date, cross))
        if (!is.na(planting) && term > planting)
          notes <- c(notes, "terminated after cash planting -- planted green")
      } else {
        notes <- c(notes, paste0("no clear spring decline -- termination not dated ",
                                 "(cover ran into the cash crop, or too little green)"))
      }
    }
  }
  if (is.na(term) && !any(grepl("termination", notes)))
    notes <- c(notes, "termination not dated")
  if (startsWith(cc$verdict, "green cover"))
    notes <- c(notes, paste0("if this was a small grain rather than a cover, these ",
                             "are its planting and harvest"))

  win <- function(gap) max(14, ceiling(gap))
  gi <- 1L
  if (!is.na(seed)) {
    w <- win(gaps[gi]); gi <- gi + 1L
    out$seeding_est <- seed; out$seeding_lo <- seed - w; out$seeding_hi <- seed + w
    if (!is.na(harvest)) out$seeding_lo <- max(out$seeding_lo, harvest)
  }
  if (!is.na(term)) {
    w <- win(gaps[gi])
    out$termination_est <- term; out$termination_lo <- term - w
    out$termination_hi <- term + w
  }
  if (!is.na(seed) && !is.na(term)) out$cover_days <- as.integer(term - seed)
  # Never "high": nothing here is fitted to recorded dates yet.
  if (length(gaps)) {
    out$dates_confidence <- if (max(gaps) <= 14 && cc$verdict == "likely cover crop")
      "medium" else "low"
  }
  if (length(notes)) out$dates_note <- paste(notes, collapse = "; ")
  out
}

#' Run cover crop detection across every winter in the series.
#'
#' Each winter also gets seeding / termination estimates -- see
#' cover_crop_dates().
cover_crop_all_years <- function(ts, phen = NULL, crops = NULL, index = "ndvi") {
  # Stand seeding dates, quoted in the note for a winter leading into a hay
  # year -- unless the caller has added them already.
  if (!is.null(phen) && nrow(phen) && !"establishment_est" %in% names(phen))
    phen <- stand_establishment(ts, phen, index)
  years <- sort(unique(as.integer(format(ts$date, "%Y"))))
  years <- utils::head(years, -1)   # last year has no following spring yet
  rows <- lapply(years, function(y) {
    nc <- if (!is.null(crops) && as.character(y + 1) %in% names(crops))
      unname(crops[[as.character(y + 1)]]) else NULL
    r <- detect_cover_crop(ts, y, phen, nc, index)
    if (is.null(r)) return(NULL)
    cbind(r, cover_crop_dates(ts, r, phen, index))
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
  else if (grepl("establishing", v)) "stand establishing"
  else if (grepl("^perennial", v)) "perennial stand"
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
