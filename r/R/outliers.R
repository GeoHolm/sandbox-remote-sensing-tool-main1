# ==============================================================================
# outliers.R -- Suspect NDVI observations: flagged, never removed
#
# Port of python/fieldrs/outliers.py; keep the two in step. The docstring there
# records why nothing is deleted (on the library, deleting spikes removed hay-cut
# troughs and open water on the rice field, and moved planting dates).
#
# The test is despike()'s (extract.R), so the two cannot disagree about what a
# spike is: more than SPIKE_NDVI off the nearest reading on both sides, same
# direction, within SPIKE_DAYS; or, November-March only, off a steady run of at
# least two readings on the one side that has neighbours.
#
# Never flagged: open water (below CC_WATER_NDVI and either negative or next
# to another water reading within SPIKE_DAYS), and anything inside the
# cutting season (CUT_SEASON) of a year read as hay -- a dip there is a cut and
# a peak is the regrown stand between cuts.
# ==============================================================================

#' `ts` with suspect (logical) and suspect_reason added to the `index` rows.
#' Nothing is removed.
flag_outliers <- function(ts, phen = NULL, index = "ndvi") {
  ts$suspect <- FALSE
  ts$suspect_reason <- NA_character_
  sel <- which(ts$index == index)
  sel <- sel[order(ts$date[sel])]
  if (length(sel) < 3) return(ts)
  v <- ts$mean[sel]; t <- as.numeric(ts$date[sel])
  month <- as.integer(format(ts$date[sel], "%m"))
  md <- format(ts$date[sel], "%m-%d")
  yr <- as.integer(format(ts$date[sel], "%Y"))
  hay <- forage_years(phen)
  jump <- SPIKE_NDVI; days <- SPIKE_DAYS
  for (k in seq_along(sel)) {
    before <- rev(which(seq_along(sel) < k & t[k] - t <= days))
    after  <- which(seq_along(sel) > k & t - t[k] <= days)
    reason <- NA_character_
    if (length(before) && length(after)) {
      dp <- v[k] - v[before[1]]; dn <- v[k] - v[after[1]]
      if (dp > jump && dn > jump) reason <- "spike above both neighbours"
      else if (dp < -jump && dn < -jump) reason <- "dip below both neighbours"
    } else if (month[k] %in% SPIKE_WINTER_MONTHS) {
      side <- if (length(before)) before else after
      if (length(side) >= 2) {
        ref <- v[side]
        if (max(ref) - min(ref) <= jump / 2 && abs(v[k] - stats::median(ref)) > jump)
          reason <- "winter reading off a steady run of neighbours"
      }
    }
    if (is.na(reason)) next
    # Open water is real when negative (water absorbs NIR; snow and cloud sit
    # around zero) or part of a flooded run -- a neighbour within SPIKE_DAYS
    # also below CC_WATER_NDVI. A lone near-zero dip is not water.
    if (v[k] < CC_WATER_NDVI &&
        (v[k] < 0 || any(v[-k][abs(t[-k] - t[k]) <= days] < CC_WATER_NDVI))) next
    if (yr[k] %in% hay && md[k] >= CUT_SEASON[1] && md[k] <= CUT_SEASON[2]) next
    ts$suspect[sel[k]] <- TRUE
    ts$suspect_reason[sel[k]] <- reason
  }
  ts
}
