# ==============================================================================
# cdl_check.R -- Does the NDVI curve contradict the CDL label? A per-season flag
#
# Port of python/fieldrs/cdl_check.py; keep the two in step. The module
# docstring there carries the full reasoning; the short version:
#
# Crops cannot be told apart by how green they get (corn, soybeans, rice and
# peanuts all peak at NDVI 0.85-0.93), so the curve cannot say which crop it
# was. It can say when the label cannot be right, and that is all this reports.
# CDL stays the label; ground truth decides which was wrong.
#
# Rules, first that applies wins, each giving cdl_flag_kind = "contradicts":
#   winter grain label, no spring canopy; fallow label, a summer canopy;
#   summer row-crop label, no summer canopy; annual label, green all year;
#   hay label, an annual curve with a bare-soil period; summer row-crop label
#   planted before 1 March or harvested before 1 July.
# A dominant crop under MIXED_PCT of the field gives "mixed".
# ==============================================================================

SUMMER_ROW_CROPS <- c("Corn", "Soybeans", "Cotton", "Peanuts", "Rice", "Sorghum",
                      "Sunflower", "Dry Beans")
SUMMER_EARLIEST_PLANTING <- "03-01"
SUMMER_EARLIEST_HARVEST  <- "07-01"
MIXED_PCT <- 75

.cdl_flag_one <- function(crop, conf, stype, year, plant, harv, pct) {
  none <- c(NA_character_, NA_character_)
  if (is.na(crop) || !nzchar(crop)) return(none)
  conf <- if (is.na(conf)) "" else conf
  stype <- if (is.na(stype)) "" else stype
  say <- function(text) c("contradicts", sprintf("CDL says %s, but %s", crop, text))
  if (crop %in% WINTER_CROPS && startsWith(conf, "no winter crop"))
    return(say("there is no spring canopy -- failed, not sown, or a CDL error"))
  if (crop %in% FALLOW_CROPS && grepl("NDVI shows a summer canopy", conf, fixed = TRUE))
    return(say("a summer canopy grew -- weeds, a crop, or a CDL error"))
  if (crop %in% SUMMER_ROW_CROPS && startsWith(conf, "no summer crop"))
    return(say("there is no summer canopy -- failed, not planted, or a CDL error"))
  if (!crop %in% FORAGE_CROPS && !crop %in% FALLOW_CROPS &&
      startsWith(conf, "not an annual row crop"))
    return(say("the field is green all year -- a perennial or hay stand, or a CDL error"))
  if (crop %in% FORAGE_CROPS && stype == "summer" && !is.na(plant))
    return(say(paste0("the curve has a bare-soil period and a single season -- ",
                      "reseeded, rotated, or a CDL error")))
  if (crop %in% SUMMER_ROW_CROPS && stype == "summer") {
    if (!is.na(plant) && plant < as.Date(sprintf("%d-%s", year, SUMMER_EARLIEST_PLANTING)))
      return(say(sprintf(paste0("the season starts %s -- too early for it; a winter ",
                                "or spring grain's calendar"), format(plant, "%d %b"))))
    if (!is.na(harv) && harv < as.Date(sprintf("%d-%s", year, SUMMER_EARLIEST_HARVEST)))
      return(say(sprintf(paste0("the season ends %s -- too early for it; a winter ",
                                "or spring grain's calendar"), format(harv, "%d %b"))))
  }
  if (!is.na(pct) && pct < MIXED_PCT)
    return(c("mixed", sprintf(paste0("CDL %s covers only %.0f%% of the field -- the ",
                                     "curve blends what grows in the boundary and ",
                                     "cannot confirm the label"), crop, pct)))
  none
}

#' `phen` with cdl_flag_kind ("contradicts", "mixed" or NA) and cdl_flag (the
#' reason) added. `history` supplies the dominant-crop share for the mixed
#' check; without it only contradictions are reported.
cdl_check <- function(phen, history = NULL) {
  if (is.null(phen) || !nrow(phen)) return(phen)
  pct <- if (!is.null(history) && "pct" %in% names(history))
    history$pct[match(phen$year, history$year)] else rep(NA_real_, nrow(phen))
  stype <- if ("season_type" %in% names(phen)) phen$season_type else rep("summer", nrow(phen))
  res <- vapply(seq_len(nrow(phen)), function(i)
    .cdl_flag_one(phen$crop[i], phen$confidence[i], stype[i], phen$year[i],
                  as.Date(phen$planting_est[i]), as.Date(phen$harvest_est[i]), pct[i]),
    character(2))
  phen$cdl_flag_kind <- res[1, ]
  phen$cdl_flag      <- res[2, ]
  phen
}
