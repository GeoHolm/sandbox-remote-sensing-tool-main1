# ==============================================================================
# timeseries.R -- Index trajectory over a season
# ==============================================================================

#' Build a per-scene index time series for a field.
#'
#' Loads every scene in turn, computes the index, and reduces it to field-level
#' statistics. Scenes where too much of the field was under cloud are dropped.
#'
#' @param scenes    Result of search_scenes().
#' @param index     Registered index name, or a vector of them.
#' @param min_valid Minimum fraction of unmasked field pixels to keep a scene.
#'                  0.8 is a sensible default -- below that the mean is being
#'                  driven by whichever corner happened to be clear.
#' @param quiet     Suppress per-scene progress.
#' @return A data frame: one row per scene per index.
index_timeseries <- function(scenes, index = "ndvi", min_valid = 0.8, quiet = FALSE) {

  bands <- bands_for(index)
  n     <- nrow(scenes$table)
  rows  <- list()

  for (i in seq_len(n)) {
    date <- scenes$table$date[i]
    if (!quiet) message(sprintf("  [%2d/%2d] %s ", i, n, date), appendLF = FALSE)

    img <- tryCatch(
      load_scene(scenes, i, bands = bands, mask_clouds = TRUE, clip = TRUE),
      error = function(e) {
        if (!quiet) message("failed: ", conditionMessage(e))
        NULL
      }
    )
    if (is.null(img)) next

    vf <- valid_fraction(img)
    if (vf < min_valid) {
      if (!quiet) message(sprintf("skipped (%.0f%% clear)", vf * 100))
      next
    }

    for (idx_name in index) {
      idx <- compute_index(img, idx_name)
      v   <- terra::values(idx)
      v   <- v[!is.na(v)]
      if (length(v) == 0) next

      rows[[length(rows) + 1]] <- data.frame(
        date        = date,
        index       = idx_name,
        mean        = mean(v),
        median      = stats::median(v),
        sd          = stats::sd(v),
        p10         = unname(stats::quantile(v, 0.10)),
        p90         = unname(stats::quantile(v, 0.90)),
        n_pixels    = length(v),
        valid_frac  = vf,
        scene_cloud = scenes$table$cloud[i],
        scene_id    = scenes$table$id[i],
        stringsAsFactors = FALSE
      )
    }
    if (!quiet) message(sprintf("ok (%.0f%% clear)", vf * 100))
  }

  if (length(rows) == 0) {
    stop("No scenes passed the cloud filter. Try lowering min_valid or ",
         "widening the date range.", call. = FALSE)
  }

  out <- do.call(rbind, rows)
  out <- out[order(out$index, out$date), ]
  rownames(out) <- NULL

  message(sprintf("  Kept %d of %d scenes.", length(unique(out$date)), n))
  out
}

#' Plot an index time series with a shaded within-field spread.
#'
#' The ribbon is the 10th-90th percentile across pixels. A wide ribbon means
#' the field is not uniform -- which is usually the interesting part.
plot_timeseries <- function(ts, index = NULL, main = NULL) {
  if (!is.null(index)) ts <- ts[ts$index == index, ]
  idx_names <- unique(ts$index)

  if (length(idx_names) > 1) {
    return(plot_timeseries_multi(ts, main))
  }

  nm <- idx_names[1]
  if (is.null(main)) main <- sprintf("%s over time", toupper(nm))

  ylim <- range(c(ts$p10, ts$p90), na.rm = TRUE)
  graphics::plot(ts$date, ts$mean, type = "n", ylim = ylim,
                 xlab = "", ylab = toupper(nm), main = main)
  graphics::grid(col = "grey90")
  graphics::polygon(c(ts$date, rev(ts$date)), c(ts$p10, rev(ts$p90)),
                    col = grDevices::adjustcolor("#5ab4ac", 0.25), border = NA)
  graphics::lines(ts$date, ts$mean, col = "#01665e", lwd = 2)
  graphics::points(ts$date, ts$mean, pch = 19, col = "#01665e", cex = 0.8)
  graphics::legend("topleft", bty = "n", lwd = c(2, 8), cex = 0.85,
                   col = c("#01665e", grDevices::adjustcolor("#5ab4ac", 0.25)),
                   legend = c("field mean", "10th-90th pct across pixels"))
  invisible(ts)
}

# Several indices on one panel, each rescaled to 0-1 so they are comparable.
plot_timeseries_multi <- function(ts, main = NULL) {
  idx_names <- unique(ts$index)
  cols <- grDevices::hcl.colors(length(idx_names), "Dark 3")
  if (is.null(main)) main <- "Indices over time (each scaled to 0-1)"

  graphics::plot(range(ts$date), c(0, 1), type = "n",
                 xlab = "", ylab = "scaled value", main = main)
  graphics::grid(col = "grey90")
  for (k in seq_along(idx_names)) {
    d <- ts[ts$index == idx_names[k], ]
    rng <- range(d$mean, na.rm = TRUE)
    y <- if (diff(rng) > 0) (d$mean - rng[1]) / diff(rng) else rep(0.5, nrow(d))
    graphics::lines(d$date, y, col = cols[k], lwd = 2)
    graphics::points(d$date, y, col = cols[k], pch = 19, cex = 0.7)
  }
  graphics::legend("topleft", bty = "n", lwd = 2, col = cols,
                   legend = toupper(idx_names), cex = 0.85)
  invisible(ts)
}

#' Write a time series to CSV in outputs/.
save_timeseries <- function(ts, filename = "timeseries.csv", dir = "outputs") {
  if (!dir.exists(dir)) dir.create(dir, recursive = TRUE)
  path <- file.path(dir, filename)
  utils::write.csv(ts, path, row.names = FALSE)
  message("  Saved ", path)
  invisible(path)
}
