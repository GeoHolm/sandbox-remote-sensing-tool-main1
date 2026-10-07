# ==============================================================================
# cdl_split.R -- Is this boundary one management unit?
#
# Everything downstream averages NDVI over whatever the boundary contains. If a
# boundary spans two fields that are farmed differently, the season curve is a
# blend of two crops and the planting date belongs to neither. CDL can catch
# that without any field visit: if the same sub-area disagrees with the rest of
# the boundary year after year, it is being managed separately.
#
# The test is persistence, not disagreement in any single year. One year's
# disagreement is usually classification noise along the edges; the same block
# disagreeing in four years out of six is a second field.
# ==============================================================================

# A flagged region has to be this big to be worth acting on, as a share of the
# field and in absolute terms. Below this it is edge noise or a farmstead.
SPLIT_MIN_FRAC <- 0.12
SPLIT_MIN_HA   <- 2.0
SPLIT_PERSIST  <- 0.6   # fraction of years a pixel must disagree

#' Assess whether a boundary should be split or trimmed.
#'
#' @param st Multi-layer SpatRaster from cdl_stack().
#' @return A list with `verdict`, `headline`, `detail`, per-year stats and a
#'         raster flagging the persistent minority area.
cdl_split_advice <- function(st) {
  years <- as.integer(sub("cdl_", "", names(st)))
  n_yr  <- terra::nlyr(st)
  px_ha <- prod(terra::res(st)) / 1e4

  per_year <- do.call(rbind, lapply(names(st), function(nm) {
    s <- cdl_summary(st[[nm]])
    data.frame(year = as.integer(sub("cdl_", "", nm)),
               dominant = s$crop[1], pct = s$pct[1],
               n_classes = nrow(s),
               noncrop_pct = sum(s$pct[!s$is_crop]),
               stringsAsFactors = FALSE)
  }))

  # --- where does the field disagree with itself, and how often? ------------
  #
  # Done on the value matrix rather than with terra::app() across layers: the
  # per-layer rasters come back from app() without values materialised, and
  # stacking them yields an all-NA result that silently reports no disagreement
  # at all, however split the boundary actually is.
  vals <- terra::values(st)                    # ncell x nyear, class codes
  doms <- vapply(seq_len(n_yr), function(k) {
    tb <- table(vals[, k])
    if (!length(tb)) NA_integer_ else as.integer(names(tb)[which.max(tb)])
  }, integer(1))

  dis <- vapply(seq_len(n_yr), function(k) {
    ifelse(is.na(vals[, k]), NA_real_, as.numeric(vals[, k] != doms[k]))
  }, numeric(nrow(vals)))

  obs        <- rowSums(!is.na(dis))
  persist_v  <- ifelse(obs > 0, rowSums(dis, na.rm = TRUE) / pmax(obs, 1), NA_real_)

  persist <- st[[1]]
  terra::values(persist) <- persist_v
  names(persist) <- "persist"

  flag_v  <- ifelse(!is.na(persist_v) & persist_v >= SPLIT_PERSIST, 1, NA_real_)
  flagged <- st[[1]]
  terra::values(flagged) <- flag_v
  names(flagged) <- "flagged"

  n_flag  <- sum(!is.na(flag_v))
  n_field <- sum(!is.na(persist_v))
  frac    <- if (n_field == 0) 0 else n_flag / n_field
  area_ha <- n_flag * px_ha

  # Largest contiguous block, so a scatter of stray pixels does not look like
  # a second field.
  biggest_ha <- 0
  if (n_flag > 0) {
    pat <- terra::patches(flagged, directions = 8, zeroAsNA = TRUE)
    tb  <- table(terra::values(pat))
    if (length(tb)) biggest_ha <- max(as.integer(tb)) * px_ha
  }

  # What is actually in the flagged area, and is it farmland at all?
  flag_classes <- NULL
  if (n_flag > 0) {
    v <- as.vector(vals[!is.na(flag_v), , drop = FALSE])
    v <- v[!is.na(v)]
    if (length(v)) {
      tb <- sort(table(v), decreasing = TRUE)
      flag_classes <- data.frame(
        code = as.integer(names(tb)),
        crop = cdl_name(as.integer(names(tb))),
        pct  = round(100 * as.numeric(tb) / sum(tb), 1),
        row.names = NULL, stringsAsFactors = FALSE
      )
      flag_classes$is_crop <- !flag_classes$code %in% CDL_NONCROP
    }
  }

  noncrop_share <- if (is.null(flag_classes)) 0 else
    sum(flag_classes$pct[!flag_classes$is_crop])

  mean_pct <- round(mean(per_year$pct, na.rm = TRUE), 1)
  big_enough <- frac >= SPLIT_MIN_FRAC && biggest_ha >= SPLIT_MIN_HA

  if (!big_enough) {
    verdict  <- "single unit"
    headline <- sprintf("Looks like one management unit -- %.0f%% of the boundary is the dominant crop on average.",
                        mean_pct)
    detail   <- "No sub-area disagrees with the rest of the field persistently enough to suggest a second unit. Any year-to-year variation is at the scale of edge pixels, which is normal for a 30 m product on a field boundary."
  } else if (noncrop_share >= 60) {
    verdict  <- "trim"
    headline <- sprintf("Consider trimming the boundary -- %.1f ha (%.0f%%) is persistently not cropland.",
                        area_ha, frac * 100)
    detail   <- sprintf("The flagged area is mostly %s. That is farmstead, road, water or woodland inside the boundary rather than a second field. It drags the field NDVI down all season and flattens the seasonal signal; clipping it out is worth more than splitting.",
                        paste(utils::head(flag_classes$crop[!flag_classes$is_crop], 2), collapse = " and "))
  } else {
    verdict  <- "split"
    headline <- sprintf("Consider splitting this boundary -- %.1f ha (%.0f%%) is farmed differently, in most years.",
                        area_ha, frac * 100)
    top <- utils::head(flag_classes[flag_classes$is_crop, ], 2)
    detail <- sprintf("A contiguous block of about %.1f ha carries a different crop from the rest of the boundary in at least %.0f%% of years -- mostly %s. Averaging NDVI across both means the season curve is a blend of two crops, and the planting and harvest dates belong to neither. Splitting the boundary along that line would make every number on the other tabs sharper.",
                      biggest_ha, SPLIT_PERSIST * 100,
                      paste(top$crop, collapse = " and "))
  }

  list(verdict = verdict, headline = headline, detail = detail,
       per_year = per_year, flag_classes = flag_classes,
       frac = frac, area_ha = area_ha, biggest_ha = biggest_ha,
       mean_pct = mean_pct, n_years = n_yr, years = years,
       persist = persist, flagged = flagged)
}

# ------------------------------------------------------------------ plots ---

# One colour per class across every year, so a crop keeps its colour from panel
# to panel. Familiar CDL colours where we have them, generated ones otherwise.
cdl_colour_map <- function(st) {
  codes <- sort(unique(stats::na.omit(unlist(lapply(names(st), function(nm)
    terra::values(st[[nm]]))))))
  codes <- as.integer(codes)
  cols  <- stats::setNames(grDevices::hcl.colors(max(length(codes), 2), "Set 3"),
                           as.character(codes))
  known <- intersect(names(CDL_COLOURS), as.character(codes))
  cols[known] <- CDL_COLOURS[known]
  cols
}

#' Every year's CDL as a matrix of maps with one shared legend.
plot_cdl_matrix <- function(st, ncol = 3, min_pct = 1) {
  nms <- names(st)
  n   <- length(nms)
  nc  <- min(ncol, n)
  nr  <- ceiling(n / nc)
  cols <- cdl_colour_map(st)

  # Row-major, so the years read left to right then down: 2020-21-22 on top,
  # 2023-24-25 underneath. Filling column-wise would interleave them.
  # 0 leaves a cell empty; the extra row holds one shared legend.
  m <- matrix(c(seq_len(n), rep(0, nr * nc - n)), nrow = nr, ncol = nc,
              byrow = TRUE)
  m <- rbind(m, rep(n + 1, nc))
  graphics::layout(m, heights = c(rep(1, nr), 0.42))
  op <- graphics::par(mar = c(0.6, 0.6, 2.4, 0.6))
  on.exit({ graphics::par(op); graphics::layout(1) }, add = TRUE)

  present <- integer(0)
  for (nm in nms) {
    lyr <- st[[nm]]
    s   <- cdl_summary(lyr)
    present <- union(present, s$code[s$pct >= min_pct])

    # Recolour as a flat vector in cell order, THEN reshape once.
    #
    # Doing the no-data fill after the reshape silently scrambles it: the
    # matrix is filled byrow = TRUE, but `ras[logical_vector] <- x` indexes
    # column-major, so the grey mask lands in the wrong cells. On a tall narrow
    # field (28x15 here) that corrupted 55% of the image while leaving the
    # class colours themselves correct -- the map looked plausible and was wrong.
    v  <- as.vector(terra::values(lyr))
    cv <- cols[as.character(v)]
    cv[is.na(v)] <- "#f2f2f2"
    ras <- matrix(cv, nrow = terra::nrow(lyr), byrow = TRUE)

    graphics::plot.new()
    graphics::plot.window(c(0, 1), c(0, 1), asp = terra::nrow(lyr) / terra::ncol(lyr))
    graphics::rasterImage(grDevices::as.raster(ras), 0, 0, 1, 1, interpolate = FALSE)
    graphics::box(col = "grey80")
    graphics::title(main = sprintf("%s  -  %s (%.0f%%)",
                                   sub("cdl_", "", nm), s$crop[1], s$pct[1]),
                    cex.main = 1.0, line = 0.6)
  }

  present <- sort(present)
  graphics::par(mar = c(0, 0, 0, 0))
  graphics::plot.new()
  graphics::legend("center", horiz = FALSE, ncol = min(4, length(present)),
                   bty = "n", pch = 15, pt.cex = 1.8, cex = 0.85,
                   col = unname(cols[as.character(present)]),
                   legend = cdl_name(present))
  invisible(present)
}

#' Map of the area flagged as persistently different.
plot_cdl_split <- function(adv) {
  pal <- grDevices::colorRampPalette(c("#f7f7f7", "#fdd49e", "#d7301f"))(100)
  graphics::par(mar = c(1, 1, 3, 4))
  terra::plot(adv$persist, col = pal, range = c(0, 1),
              main = sprintf("Share of years each pixel differs from the field's dominant crop  (%d-%d)",
                             min(adv$years), max(adv$years)),
              cex.main = 0.95, axes = FALSE)
  if (sum(!is.na(terra::values(adv$flagged))) > 0) {
    bound <- terra::as.polygons(adv$flagged, dissolve = TRUE)
    terra::plot(bound, add = TRUE, border = "#d7301f", lwd = 2)
  }
  invisible(adv)
}
