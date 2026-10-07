# ==============================================================================
# plotting.R -- Look at the imagery
# ==============================================================================

#' Percentile stretch a band to 0-255 for display.
#'
#' Raw reflectance is mostly dark values, so a straight linear map to 0-255
#' gives a near-black image. Clipping at the 2nd/98th percentile is what makes
#' satellite RGB look like a photograph.
#'
#' @param gamma Tone curve applied after the stretch. Below 1 lifts the mid
#'              tones. Dense summer canopy is genuinely very dark in true
#'              colour, so without this a healthy field reads as near-black.
#'              Display only -- it never touches the values you analyse.
stretch_band <- function(r, q = c(0.02, 0.98), gamma = 0.8) {
  v  <- terra::values(r)
  v  <- v[!is.na(v)]
  if (length(v) == 0) return(r * 0)
  lim <- stats::quantile(v, probs = q, na.rm = TRUE)
  if (diff(lim) <= 0) lim <- range(v)
  if (diff(lim) <= 0) return(r * 0)
  out <- (r - lim[1]) / (lim[2] - lim[1])
  out <- terra::clamp(out, 0, 1, values = TRUE)
  terra::clamp(out^gamma * 255, 0, 255, values = TRUE)
}

#' Draw a field boundary over a plotted raster.
#'
#' Reprojects the boundary to the image CRS first. Boundaries are normally in
#' lon/lat while Sentinel-2 is in UTM, and terra will not reproject on the fly
#' for an `add = TRUE` layer -- the outline just silently fails to appear.
add_field <- function(field, img = NULL, col = "yellow", lwd = 2) {
  v <- terra::vect(sf::st_union(field))
  if (!is.null(img)) v <- terra::project(v, terra::crs(img))
  terra::plot(v, add = TRUE, border = col, lwd = lwd)
  invisible(v)
}

#' True-colour RGB composite.
#'
#' @param img SpatRaster containing at least red, green, blue.
#' @param q   Stretch percentiles.
plot_rgb <- function(img, q = c(0.02, 0.98), gamma = 0.8, main = NULL, ...) {
  need <- c("red", "green", "blue")
  missing_bands <- setdiff(need, names(img))
  if (length(missing_bands)) {
    stop("RGB needs band(s): ", paste(missing_bands, collapse = ", "),
         "\n  Load them with load_scene(bands = c(\"blue\",\"green\",\"red\",\"nir\"))",
         call. = FALSE)
  }
  if (is.null(main)) {
    main <- sprintf("True colour  |  %s", attr(img, "date") %||% "")
  }
  rgb <- terra::rast(lapply(need, function(b) stretch_band(img[[b]], q, gamma)))
  terra::plotRGB(rgb, r = 1, g = 2, b = 3, scale = 255, main = main, ...)
}

#' False-colour infrared composite (NIR-red-green).
#'
#' Healthy vegetation glows red. Good for spotting crop stress and field
#' patterns that true colour hides.
plot_false_colour <- function(img, q = c(0.02, 0.98), gamma = 0.8, main = NULL, ...) {
  need <- c("nir", "red", "green")
  missing_bands <- setdiff(need, names(img))
  if (length(missing_bands)) {
    stop("False colour needs band(s): ", paste(missing_bands, collapse = ", "),
         call. = FALSE)
  }
  if (is.null(main)) {
    main <- sprintf("False colour (NIR)  |  %s", attr(img, "date") %||% "")
  }
  rgb <- terra::rast(lapply(need, function(b) stretch_band(img[[b]], q, gamma)))
  terra::plotRGB(rgb, r = 1, g = 2, b = 3, scale = 255, main = main, ...)
}

#' Colour ramp for vegetation indices: brown (bare) through to dark green.
veg_palette <- function(n = 100) {
  grDevices::colorRampPalette(
    c("#8c510a", "#d8b365", "#f6e8c3", "#c7eae5", "#5ab4ac", "#01665e")
  )(n)
}

#' Map a computed index.
#'
#' @param idx   Single-layer SpatRaster from compute_index().
#' @param range Colour range; defaults to the index's registered range.
plot_index <- function(idx, range = NULL, main = NULL, palette = veg_palette(100), ...) {
  nm <- names(idx)[1]
  if (is.null(range)) range <- attr(idx, "range") %||% c(-1, 1)
  if (is.null(main)) {
    main <- sprintf("%s  |  %s", toupper(nm), attr(idx, "date") %||% "")
  }
  terra::plot(idx, col = palette, range = range, main = main, ...)
}

#' Histogram of index values inside the field, with the mean marked.
plot_index_hist <- function(idx, main = NULL, ...) {
  nm <- names(idx)[1]
  v  <- terra::values(idx)
  v  <- v[!is.na(v)]
  if (length(v) == 0) stop("No valid pixels to plot.", call. = FALSE)
  if (is.null(main)) {
    main <- sprintf("%s distribution  |  %s", toupper(nm), attr(idx, "date") %||% "")
  }
  graphics::hist(v, breaks = 40, col = "#5ab4ac", border = "white",
                 main = main, xlab = toupper(nm), ...)
  graphics::abline(v = mean(v), col = "#8c510a", lwd = 2, lty = 2)
  graphics::legend("topleft", bty = "n",
                   legend = sprintf("mean %.3f\nsd %.3f\nn %d", mean(v), stats::sd(v), length(v)))
}

#' Save whatever the plotting expression draws to a PNG in outputs/.
#'
#' @param expr Plotting code, e.g. save_plot("rgb.png", plot_rgb(img)).
save_plot <- function(filename, expr, dir = "outputs", width = 1400, height = 1200, res = 150) {
  if (!dir.exists(dir)) dir.create(dir, recursive = TRUE)
  path <- file.path(dir, filename)
  grDevices::png(path, width = width, height = height, res = res)
  on.exit(grDevices::dev.off(), add = TRUE)
  force(expr)
  message("  Saved ", path)
  invisible(path)
}
