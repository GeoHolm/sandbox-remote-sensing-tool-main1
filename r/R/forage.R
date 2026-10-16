# ==============================================================================
# forage.R -- Cutting dates for alfalfa and other hay, from NDVI, radar and
#             weather
#
# Port of python/fieldrs/forage.py; keep the two in step. The module docstring
# there carries the reasoning and what was found on the Washington pivot.
#
# PROTOTYPE. Nothing here is checked against grower-reported cutting dates.
#
# An established alfalfa stand is never planted or harvested in the row-crop
# sense, so the season model correctly refuses to date it. The operation that
# matters is the cutting. NDVI finds each cut (a drop of at least CUT_DROP from
# a stand above CUT_STAND_MIN), dated around the first scene at least halfway
# down to the trough. Radar VH narrows the bracket when a drop inside it stands
# out from noise; rain days are struck out. A drop to bare soil is tillage,
# reseeding or removal, not a hay cut, and is labelled as such.
# ==============================================================================

FORAGE_CROPS <- c("Alfalfa", "Other Hay/Non Alfalfa", "Clover/Wildflowers", "Vetch")

CUT_SEASON      <- c("04-01", "11-15")
CUT_STAND_MIN   <- 0.60
CUT_DROP        <- 0.20
CUT_ONSET       <- 0.10
CUT_TROUGH_DAYS <- 21
CUT_RISE        <- 0.06
CUT_REGROW      <- 0.15
CUT_REGROW_DAYS <- 45
CUT_BARE_NDVI   <- 0.20

#' Years read as hay: CDL says a forage crop, or -- for a year CDL has not
#' published yet -- the previous year was forage and the stand looks perennial.
forage_years <- function(phen) {
  if (is.null(phen) || !nrow(phen)) return(integer(0))
  # A blank label is a missing one (CDL not published for that year yet).
  crops <- ifelse(!is.na(phen$crop) & nzchar(phen$crop), phen$crop, NA_character_)
  crop_of <- function(y) { c <- crops[phen$year == y]; if (length(c)) c[1] else NA }
  out <- integer(0)
  for (i in seq_len(nrow(phen))) {
    crop <- crops[i]; y <- phen$year[i]
    if (!is.na(crop) && crop %in% FORAGE_CROPS) {
      out <- c(out, y)
    } else if (is.na(crop) && isTRUE(crop_of(y - 1) %in% FORAGE_CROPS) &&
               grepl("not an annual row crop", phen$confidence[i], fixed = TRUE)) {
      out <- c(out, y)
    }
  }
  out
}

#' Cuts in one year's clear NDVI observations.
#' @param ndvi Data frame with date and mean.
ndvi_cuts <- function(ndvi, year) {
  lo <- as.Date(sprintf("%d-%s", year, CUT_SEASON[1]))
  hi <- as.Date(sprintf("%d-%s", year, CUT_SEASON[2]))
  nd <- ndvi[!is.na(ndvi$mean), ]; nd <- nd[order(nd$date), ]
  s <- nd[nd$date >= lo & nd$date <= hi, ]
  after <- nd[nd$date > lo, ]
  v <- s$mean; t <- s$date; n <- length(v)
  cuts <- list(); i <- 1L
  while (i < n) {
    if (v[i] < CUT_STAND_MIN) { i <- i + 1L; next }
    # Walk to the last observation still at the stand level.
    j <- i
    while (j + 1L <= n && v[j + 1L] > v[j] - CUT_ONSET) j <- j + 1L
    if (j + 1L > n) break
    high <- v[j]
    if (high < CUT_STAND_MIN) { i <- j + 1L; next }
    # The trough is the FIRST low after the drop: follow the decline until NDVI
    # rises clearly (regrowth) or the window ends.
    end <- t[j] + CUT_TROUGH_DAYS
    k <- j + 1L
    while (k + 1L <= n && t[k + 1L] <= end && v[k + 1L] < min(v[(j + 1L):k]) + CUT_RISE)
      k <- k + 1L
    wv <- v[(j + 1L):k]; wt <- t[(j + 1L):k]
    if (high - min(wv) < CUT_DROP) { i <- j + 1L; next }
    trough <- min(wv); t_date <- wt[which.min(wv)]
    # Date the cut by the first scene at least halfway down to the trough.
    half <- high - 0.5 * (high - trough)
    fall <- which(t > t[j] & t <= t_date & v <= half)
    onset <- t[fall[1]]
    last_high <- max(t[t < onset])
    later <- after$mean[after$date > t_date & after$date <= t_date + CUT_REGROW_DAYS]
    regrew <- length(later) > 0 && max(later) - trough >= CUT_REGROW
    cuts[[length(cuts) + 1L]] <- list(year = as.integer(year), ndvi_from = last_high,
      ndvi_to = onset, ndvi_stand = round(high, 3), ndvi_trough = round(trough, 3),
      trough_date = t_date, regrowth = regrew)
    i <- sum(t <= t_date) + 1L       # continue after the trough
  }
  for (k in seq_along(cuts)) cuts[[k]]$cut <- k
  cuts
}

#' Every cut in every forage year, with radar and weather narrowing.
#'
#' @param ndvi    Data frame with date and mean.
#' @param ctx     s1_context() output, or NULL.
#' @param weather Daily gridMET, or NULL.
forage_cuts <- function(ndvi, phen, ctx = NULL, weather = NULL) {
  cols <- c("year", "crop", "cut", "kind", "ndvi_from", "ndvi_to", "ndvi_days",
            "ndvi_stand", "ndvi_trough", "regrowth", "s1_from", "s1_to",
            "step_db", "z", "basis", "refined_lo", "refined_hi", "span_days",
            "candidate_days", "note")
  empty <- data.frame(matrix(ncol = length(cols), nrow = 0, dimnames = list(NULL, cols)))
  years <- forage_years(phen)
  if (is.null(ndvi) || !nrow(ndvi) || !length(years)) return(empty)

  # VH from every orbit, each centred on its own median. Unlike s1_intervals()
  # this does not need the VV moisture fit, which an irrigated stand that is
  # never bare usually cannot get.
  iv <- NULL; sd <- NA_real_
  if (!is.null(ctx) && nrow(ctx)) {
    m <- ctx[!ctx$frozen, ]; m <- m[order(m$date, m$orbit), ]   # same as forage.py
    nn <- nrow(m)
    if (nn >= 2) {
      iv <- data.frame(date_a = m$date[-nn], date = m$date[-1], d_vh = diff(m$vh_c))
      iv <- iv[iv$date > iv$date_a, ]               # no same-day orbit pairs
      md <- format(iv$date, "%m-%d")
      sd <- .robust_sd(iv$d_vh[md >= CUT_SEASON[1] & md <= CUT_SEASON[2]])
    }
  }
  work <- if (!is.null(weather) && nrow(weather)) workable_days(weather) else NULL

  rows <- list()
  for (y in years) {
    for (c in ndvi_cuts(ndvi, y)) {
      lo <- c$ndvi_from; hi <- c$ndvi_to
      bare <- c$ndvi_trough < CUT_BARE_NDVI
      notes <- character(0)
      if (bare) notes <- c(notes, paste0("fell to bare soil: tillage, reseeding or ",
                                         "stand removal rather than a hay cut"))
      if (!c$regrowth) notes <- c(notes, paste0("no regrowth after: last cut of the ",
                                                "season, or the stand removed"))
      row <- list(year = y, crop = phen$crop[match(y, phen$year)], cut = c$cut,
                  kind = if (bare) "to bare soil" else "cut", ndvi_from = lo,
                  ndvi_to = hi, ndvi_days = as.integer(hi - lo),
                  ndvi_stand = c$ndvi_stand, ndvi_trough = c$ndvi_trough,
                  regrowth = c$regrowth, s1_from = as.Date(NA), s1_to = as.Date(NA),
                  step_db = NA_real_, z = NA_real_, basis = "NDVI only")
      # The cut happened after the last high scene and on or before the first low one.
      days <- seq(lo + 1, hi, by = 1)
      if (!is.null(iv) && !is.na(sd) && sd > 0) {
        over <- which(iv$date - 1 >= min(days) & iv$date_a <= max(days) &
                      !is.na(iv$d_vh) & iv$d_vh < 0)
        if (length(over)) {
          e <- iv[over[which.min(iv$d_vh[over])], ]
          z <- -e$d_vh / sd
          row$s1_from <- e$date_a; row$s1_to <- e$date
          row$step_db <- round(e$d_vh, 2); row$z <- round(z, 2)
          if (z >= SAR_SUPPORT_Z) {
            nar <- days[days >= e$date_a & days <= e$date - 1]
            if (length(nar)) { days <- nar; row$basis <- "NDVI + radar" }
          }
        }
      }
      if (!is.null(work)) {
        dry <- days[.work_on(work, days)]
        if (length(dry)) {
          days <- dry; row$basis <- paste0(row$basis, " + weather")
        } else {
          notes <- c(notes, "no rain-free day in the bracket")
        }
      }
      row$refined_lo <- min(days); row$refined_hi <- max(days)
      row$span_days <- as.integer(max(days) - min(days)) + 1L
      row$candidate_days <- length(days)
      row$note <- if (length(notes)) paste(notes, collapse = "; ") else NA_character_
      rows[[length(rows) + 1L]] <- as.data.frame(row, stringsAsFactors = FALSE)
    }
  }
  if (!length(rows)) return(empty)
  do.call(rbind, rows)[, cols]
}
