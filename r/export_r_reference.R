# ==============================================================================
# export_r_reference.R -- Dump every field's R results for cross-checking
#
#   Rscript export_r_reference.R
#
# Writes outputs/r_reference/*.csv, which compare_implementations.py diffs the
# Python port against. Reads only from the cache, so it is fast and cannot
# accidentally change what it is meant to be a reference for.
# ==============================================================================

source("pipeline.R")

OUT <- "outputs/r_reference"
dir.create(OUT, recursive = TRUE, showWarnings = FALSE)

files <- sort(list.files(FIELDS_DIR, pattern = "[.]geojson$", full.names = TRUE))
yrs   <- 2020:(as.integer(format(Sys.Date(), "%Y")) - 1)
win   <- analysis_window(2020, as.integer(format(Sys.Date(), "%Y")))

phen_all <- cc_all <- hist_all <- adv_all <- res_all <- list()

for (p in files) {
  nm <- sub("[.]geojson$", "", basename(p))
  cat(nm, "... ")
  aoi <- load_field(p)

  st <- cdl_stack(aoi, yrs, only_cached = TRUE)
  ts <- extract_field_series(aoi, win$start, win$end, indices = "ndvi",
                             only_cached = TRUE)
  if (is.null(st) || is.null(ts)) { cat("NOT CACHED\n"); next }

  hist  <- cdl_history_from_stack(st)
  crops <- crop_lookup(hist)
  phen  <- phenology_all_years(ts, crops)
  cc    <- cover_crop_all_years(ts, phen, crops)
  adv   <- cdl_split_advice(st)

  hist_all[[nm]] <- cbind(field = nm, hist)
  if (!is.null(phen)) {
    phen_all[[nm]] <- cbind(field = nm, n_obs_total = nrow(ts),
      phen[, c("year","crop","planting_est","harvest_est","season_days",
               "peak_ndvi","confidence")])
  }
  if (!is.null(cc)) {
    cc_all[[nm]] <- cbind(field = nm,
      cc[, c("winter","n_obs","max_ndvi","green_days","verdict")])
  }
  # Residue is warmed separately, so a field without it is skipped rather
  # than failing the whole export.
  rts <- armor_series(aoi, c(2020, as.integer(format(Sys.Date(), "%Y"))),
                      only_cached = TRUE)
  if (!is.null(rts)) {
    res <- armor_all_years(rts, phen)
    if (!is.null(res)) {
      res_all[[nm]] <- cbind(field = nm,
        res[, c("year","window_start","window_end","n_obs","armor","armor_lo",
                "armor_hi","f_pv","f_npv","f_bs","min_ndti","note")])
    }
  }

  adv_all[[nm]] <- data.frame(
    field = nm, verdict = adv$verdict, frac = round(adv$frac, 4),
    area_ha = round(adv$area_ha, 2), biggest_ha = round(adv$biggest_ha, 2),
    mean_pct = adv$mean_pct, stringsAsFactors = FALSE)
  cat("ok\n")
}

wr <- function(lst, name) {
  if (!length(lst)) return(invisible())
  df <- do.call(rbind, lst); rownames(df) <- NULL
  utils::write.csv(df, file.path(OUT, name), row.names = FALSE)
  cat(sprintf("  %-18s %d rows\n", name, nrow(df)))
}
cat("\nwritten to ", OUT, "/\n", sep = "")
wr(hist_all, "cdl_history.csv")
wr(phen_all, "phenology.csv")
wr(cc_all,   "covercrop.csv")
wr(adv_all,  "boundary.csv")
wr(res_all,  "soil_armor.csv")
