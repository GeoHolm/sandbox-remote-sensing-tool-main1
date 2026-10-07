# Re-derive spring armor for the four grower-confirmed Georgia fields and
# compare against the figures quoted in data/fields/library.csv and in deck
# slide 12. Cache only -- nothing here touches the archive.

suppressMessages(source("r/pipeline.R"))

CLAIMS <- data.frame(
  stem  = c("mitchell-ga-conservation", "mitchell-ga-conventional",
            "screven-ga-notill-bare", "jefferson-ga-conv-cover"),
  year  = c(2020L, 2020L, 2020L, 2021L),
  claim = c(0.649, 0.508, 0.480, 0.649),
  what  = c("no-till + cover", "conventional, no cover",
            "no-till, no cover", "conventional + cover"),
  stringsAsFactors = FALSE
)

YEARS <- c(2020L, as.integer(format(Sys.Date(), "%Y")))
win   <- analysis_window(YEARS[1], YEARS[2])
cat(sprintf("analysis window: %s to %s\n\n", win$start, win$end))

out <- list()
for (i in seq_len(nrow(CLAIMS))) {
  stem <- CLAIMS$stem[i]
  aoi  <- load_field(file.path(FIELDS_DIR, paste0(stem, ".geojson")))

  yrs   <- YEARS[1]:(YEARS[2] - 1L)
  cdlst <- cdl_stack(aoi, yrs, only_cached = TRUE)
  crops <- if (is.null(cdlst)) NULL else crop_lookup(cdl_history_from_stack(cdlst))
  ts    <- extract_field_series(aoi, win$start, win$end, indices = "ndvi",
                                only_cached = TRUE)
  if (is.null(ts)) { cat(stem, ": NDVI series not cached\n"); next }
  phen <- phenology_all_years(ts, crops)

  ats <- armor_series(aoi, YEARS, only_cached = TRUE)
  if (is.null(ats)) { cat(stem, ": armor series not cached\n"); next }
  res <- armor_all_years(ats, phen, "spring")

  r <- res[res$year == CLAIMS$year[i], ]
  p <- phen[phen$year == CLAIMS$year[i], ]
  out[[stem]] <- data.frame(
    field = stem, what = CLAIMS$what[i], year = CLAIMS$year[i],
    claimed = CLAIMS$claim[i], now = r$armor,
    delta = round(r$armor - CLAIMS$claim[i], 3),
    f_pv = r$f_pv, f_npv = r$f_npv, f_bs = r$f_bs, n_obs = r$n_obs,
    w_start = as.character(r$window_start), w_end = as.character(r$window_end),
    w_source = r$window_source,
    planting = as.character(p$planting_est), conf = p$confidence,
    stringsAsFactors = FALSE
  )
}

tab <- do.call(rbind, out)
cat("\n==== spring armor, claimed vs now ====\n")
print(tab[, c("field", "year", "claimed", "now", "delta", "n_obs",
              "w_start", "w_end", "w_source")], row.names = FALSE)
cat("\n==== fractions and the phenology driving the window ====\n")
print(tab[, c("field", "what", "f_pv", "f_npv", "f_bs", "planting", "conf")],
      row.names = FALSE)

cat("\n==== does the 2x2 story still hold? ====\n")
cover <- tab$now[tab$field %in% c("mitchell-ga-conservation", "jefferson-ga-conv-cover")]
bare  <- tab$now[tab$field %in% c("mitchell-ga-conventional", "screven-ga-notill-bare")]
notil <- tab$now[tab$field %in% c("mitchell-ga-conservation", "screven-ga-notill-bare")]
conv  <- tab$now[tab$field %in% c("mitchell-ga-conventional", "jefferson-ga-conv-cover")]
cat(sprintf("  cover-cropped mean  %.3f   vs  no cover crop mean %.3f   gap %+.3f\n",
            mean(cover), mean(bare), mean(cover) - mean(bare)))
cat(sprintf("  conservation till   %.3f   vs  conventional till  %.3f   gap %+.3f\n",
            mean(notil), mean(conv), mean(notil) - mean(conv)))
cat(sprintf("  no-till/no-cover (%.3f) below conventional/no-cover (%.3f)? %s\n",
            tab$now[tab$field == "screven-ga-notill-bare"],
            tab$now[tab$field == "mitchell-ga-conventional"],
            tab$now[tab$field == "screven-ga-notill-bare"] <
              tab$now[tab$field == "mitchell-ga-conventional"]))

utils::write.csv(tab, "armor_recheck.csv", row.names = FALSE)
cat("\nwritten: armor_recheck.csv\n")
