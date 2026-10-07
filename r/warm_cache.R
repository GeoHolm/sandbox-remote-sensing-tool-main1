# ==============================================================================
# warm_cache.R -- Pre-compute the demo library
#
#   Rscript warm_cache.R
#
# Runs the full analysis for every boundary in data/fields/ so the app can open
# any of them instantly. Everything lands in cache/, keyed on field geometry
# plus the analysis window.
#
# Re-run monthly: analysis_window() ends at the start of the current month, so
# the cache stays valid for the rest of it and then needs pulling forward.
# ==============================================================================

source("pipeline.R")

YEARS <- c(2020, as.integer(format(Sys.Date(), "%Y")))
win   <- analysis_window(YEARS[1], YEARS[2])
cdl_years <- YEARS[1]:(as.integer(format(Sys.Date(), "%Y")) - 1)

files <- sort(list.files(FIELDS_DIR, pattern = "[.]geojson$", full.names = TRUE))
cat(sprintf("\nWarming %d fields, window %s -> %s\n\n", length(files), win$start, win$end))

rows <- list()
t_all <- Sys.time()

for (p in files) {
  nm <- basename(p)
  cat(strrep("-", 70), "\n", nm, "\n", sep = "")
  t0 <- Sys.time()

  r <- tryCatch({
    field <- load_field(p)

    catalog_availability(field, win$start, win$end)
    st    <- cdl_stack(field, cdl_years)
    hist  <- cdl_history_from_stack(st)
    adv   <- cdl_split_advice(st)
    ts    <- extract_field_series(field, win$start, win$end,
                                  indices = "ndvi", workers = 8)
    phen  <- phenology_all_years(ts, crop_lookup(hist))
    cc    <- cover_crop_all_years(ts, phen, crop_lookup(hist))

    # The Soil armor tab reads its own bands over its own window, so it needs
    # its own warm-up. Spring only -- see ARMOR_SPAN in R/armor.R.
    rts   <- armor_series(field, YEARS, workers = 8)
    res   <- if (is.null(rts)) NULL else armor_all_years(rts, phen)

    crops <- paste(unique(stats::na.omit(hist$crop)), collapse = "/")
    cc_hit <- if (is.null(cc)) 0 else sum(grepl("likely|small grain", cc$verdict))

    data.frame(
      file = nm, area_ha = round(sum(field$area_ha), 1),
      obs = nrow(ts), seasons = if (is.null(phen)) 0 else nrow(phen),
      crops = crops, boundary = adv$verdict,
      cover_winters = cc_hit,
      mins = round(as.numeric(difftime(Sys.time(), t0, units = "mins")), 1),
      stringsAsFactors = FALSE
    )
  }, error = function(e) {
    cat("  FAILED: ", conditionMessage(e), "\n", sep = "")
    data.frame(file = nm, area_ha = NA, obs = NA, seasons = NA, crops = NA,
               boundary = paste("ERROR:", conditionMessage(e)),
               cover_winters = NA,
               mins = round(as.numeric(difftime(Sys.time(), t0, units = "mins")), 1),
               stringsAsFactors = FALSE)
  })
  rows[[length(rows) + 1]] <- r
  cat(sprintf("  done in %.1f min\n", r$mins))
}

out <- do.call(rbind, rows)
cat("\n", strrep("=", 70), "\nSUMMARY\n", sep = "")
print(out, row.names = FALSE)
cat(sprintf("\nTotal %.1f min. Cache: %d files, %.1f MB\n",
            as.numeric(difftime(Sys.time(), t_all, units = "mins")),
            length(list.files("cache")),
            sum(file.size(list.files("cache", full.names = TRUE))) / 1e6))
utils::write.csv(out, "outputs/demo_library.csv", row.names = FALSE)
