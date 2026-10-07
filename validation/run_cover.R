# Cover crop validation: the pipeline's off-season verdict against the survey.
#
#   Rscript validation/run_cover.R
#
# ASSUMPTION, stated because it is not verifiable from the data we kept:
# a survey row for crop year Y is taken to describe the cover crop grown in the
# winter BEFORE that crop, so fall_year = Y - 1 and the window is
# Oct 15 (Y-1) -> May 10 (Y). The 82 shared winters in the repeat-field subset
# disagree on only 18, too few to settle it empirically.
#
# Phenology is NOT computed here -- it would need a full growing-season series
# per field, roughly doubling the run. The window therefore keeps its fixed
# ends rather than being trimmed to harvest and planting. That matters most for
# late-harvested cotton, which can still be standing on 15 October and would
# read as winter green. This is why the raw series is written out: the window
# start can be moved and every threshold re-tested offline, for free.

setwd("C:/Users/EricCoronel/Documents/GitHub/sandbox-remote-sensing-tool/r")
suppressMessages(source("pipeline.R"))

OUT  <- "../validation/cover.csv"
RAW  <- "../validation/cover_series.csv"

truth <- utils::read.csv("../validation/truth.csv", stringsAsFactors = FALSE)
cdl   <- utils::read.csv("../validation/cdl.csv", stringsAsFactors = FALSE)
# CDL's label for crop year Y is the "next crop" for the winter ending in Y.
next_crop <- stats::setNames(cdl$cdl_crop, cdl$key)

done <- if (file.exists(OUT)) utils::read.csv(OUT, stringsAsFactors = FALSE)$key else character(0)
todo <- truth[!truth$key %in% done, ]
cat(sprintf("to score: %d of %d (%d already done)\n\n", nrow(todo), nrow(truth), length(done)))

t0 <- Sys.time()
for (i in seq_len(nrow(todo))) {
  r <- todo[i, ]
  fy <- r$year - 1L

  row <- tryCatch({
    aoi <- load_field(file.path("../validation/boundaries", paste0(r$key, ".geojson")))
    ts  <- extract_field_series(aoi, sprintf("%d-10-15", fy),
                                sprintf("%d-05-10", fy + 1L),
                                indices = "ndvi", workers = 8)
    if (is.null(ts) || !nrow(ts)) stop("no observations")

    # Raw series first, so a failure later still leaves the expensive part on disk.
    raw <- data.frame(key = r$key, fall_year = fy,
                      date = as.character(ts$date), ndvi = round(ts$mean, 4),
                      stringsAsFactors = FALSE)
    utils::write.table(raw, RAW, sep = ",", row.names = FALSE,
                       col.names = !file.exists(RAW), append = file.exists(RAW))

    cc <- detect_cover_crop(ts, fy, phen = NULL,
                            next_crop = unname(next_crop[r$key]))
    if (is.null(cc)) stop("detector returned NULL")
    cbind(data.frame(key = r$key, stringsAsFactors = FALSE), cc)
  }, error = function(e) {
    cat(sprintf("   %s ERR: %s\n", r$key, conditionMessage(e)))
    # Same columns as cc_row(), or write.table(append=) silently misaligns
    # the file from this row on.
    cbind(data.frame(key = r$key, stringsAsFactors = FALSE),
          cc_row(fy, as.Date(sprintf("%d-10-15", fy)),
                 as.Date(sprintf("%d-05-10", fy + 1L)), 0L,
                 NA, NA, NA, NA_integer_, "ERROR", conditionMessage(e)))
  })

  utils::write.table(row, OUT, sep = ",", row.names = FALSE,
                     col.names = !file.exists(OUT), append = file.exists(OUT))

  if (i %% 25 == 0) {
    el <- as.numeric(difftime(Sys.time(), t0, units = "mins"))
    cat(sprintf("  %d/%d  %.1f min elapsed, ~%.0f min left\n",
                i, nrow(todo), el, el / i * (nrow(todo) - i)))
    utils::flush.console()
  }
}
cat(sprintf("\nCOVER RUN DONE in %.1f min\n",
            as.numeric(difftime(Sys.time(), t0, units = "mins"))))
