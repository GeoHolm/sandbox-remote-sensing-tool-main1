# ==============================================================================
# aoi.R -- Field boundaries (the "upload a field" step)
# ==============================================================================

#' Load a field boundary from any common vector format.
#'
#' Accepts .geojson, .json, .shp, .gpkg, .kml, .kmz(unzipped). Cleans it up and
#' always hands back polygons in EPSG:4326, which is what the STAC search wants.
#'
#' @param path   Path to the boundary file.
#' @param id_col Optional column to use as the field identifier.
#' @return An sf data frame of POLYGON/MULTIPOLYGON in EPSG:4326, with an
#'         `area_ha` column added.
load_field <- function(path, id_col = NULL) {
  if (!file.exists(path)) stop("Boundary file not found: ", path, call. = FALSE)

  aoi <- sf::st_read(path, quiet = TRUE)
  if (nrow(aoi) == 0) stop("Boundary file contains no features: ", path, call. = FALSE)

  # KML/GPS exports often carry a Z (elevation) or M dimension that breaks
  # downstream geometry ops. Drop it.
  aoi <- sf::st_zm(aoi, drop = TRUE, what = "ZM")

  # Hand-drawn and GIS-exported boundaries are frequently self-intersecting.
  if (!all(sf::st_is_valid(aoi))) {
    message("  Fixing invalid geometry in boundary...")
    aoi <- sf::st_make_valid(aoi)
  }

  gt <- as.character(sf::st_geometry_type(aoi))
  if (!all(gt %in% c("POLYGON", "MULTIPOLYGON"))) {
    stop("Boundary must be polygons, got: ", paste(unique(gt), collapse = ", "),
         call. = FALSE)
  }

  if (is.na(sf::st_crs(aoi))) {
    warning("Boundary has no CRS defined; assuming EPSG:4326 (lon/lat).")
    sf::st_crs(aoi) <- 4326
  }
  aoi <- sf::st_transform(aoi, 4326)

  # Area is measured in CONUS Albers (EPSG:5070), an equal-area projection.
  aoi$area_ha <- as.numeric(sf::st_area(sf::st_transform(aoi, 5070))) / 1e4

  if (!is.null(id_col)) {
    if (!id_col %in% names(aoi)) stop("Column not found in boundary: ", id_col, call. = FALSE)
    aoi$field_id <- as.character(aoi[[id_col]])
  } else if (!"field_id" %in% names(aoi)) {
    aoi$field_id <- sprintf("field_%02d", seq_len(nrow(aoi)))
  }

  message(sprintf("  Loaded %d field(s), %.1f ha total.", nrow(aoi), sum(aoi$area_ha)))

  tiny <- aoi$area_ha < 1
  if (any(tiny)) {
    warning(sum(tiny), " field(s) under 1 ha. At Sentinel-2's 10 m pixels that is ",
            "fewer than ~100 pixels -- treat the statistics with caution.")
  }
  big <- aoi$area_ha > 50000
  if (any(big)) {
    warning(sum(big), " field(s) over 50,000 ha. Downloads will be slow; ",
            "consider Earth Engine for areas this size (see R/gee.R).")
  }

  aoi
}

#' Bounding box of an AOI as c(xmin, ymin, xmax, ymax) in lon/lat, with a buffer.
#'
#' The buffer matters: without it you can clip away the edge pixels of the field.
field_bbox <- function(aoi, buffer_m = 200) {
  albers  <- sf::st_transform(sf::st_union(aoi), 5070)
  buffered <- sf::st_buffer(albers, buffer_m)
  as.numeric(sf::st_bbox(sf::st_transform(buffered, 4326)))
}

#' Interactive leaflet map of the field(s) over satellite basemap.
#' Handy for eyeballing that a boundary actually landed where you expected.
# A boundary must describe ONE field, and the app enforces that on every path.
#
# The reason is not tidiness. Everything downstream averages an index over
# whatever the boundary contains, so two fields in one boundary produce a season
# curve that is a blend of two crops and a planting date belonging to neither --
# the same failure the CDL boundary check exists to catch, except self-inflicted.
#
# Negligible parts are dropped rather than refused. Real boundary files are full
# of them: example_field_covercrop.geojson is a MULTIPOLYGON whose second part is
# 0.00 ha sitting 200 m away, a digitising artifact and not a second field.
# Refusing that file would be pedantry.
FIELD_SLIVER_HA   <- 0.05    # absolute floor: below this is not a field
FIELD_SLIVER_FRAC <- 0.005   # ...or under 0.5% of the largest part

#' Reduce a boundary to a single field, or refuse it.
#'
#' Splits multi-part geometry, drops slivers, and errors when more than one
#' substantive field remains. Returns one row, with the number of dropped
#' slivers in the "dropped" attribute.
single_field <- function(aoi) {
  if (is.null(aoi) || !nrow(aoi)) stop("Boundary is empty.", call. = FALSE)

  parts <- suppressWarnings(sf::st_cast(sf::st_make_valid(aoi), "POLYGON"))
  ha <- as.numeric(sf::st_area(sf::st_transform(parts, 5070))) / 1e4
  parts <- parts[order(-ha), ]
  ha <- sort(ha, decreasing = TRUE)

  keep <- ha >= max(FIELD_SLIVER_HA, FIELD_SLIVER_FRAC * ha[1])
  if (sum(keep) > 1) {
    stop(sprintf(paste0("This boundary contains %d separate fields (%s ha). ",
                        "Load or draw one field at a time -- everything here ",
                        "averages over whatever the boundary contains, so two ",
                        "fields give a season curve belonging to neither."),
                 sum(keep),
                 paste(sprintf("%.1f", ha[keep]), collapse = ", ")),
         call. = FALSE)
  }

  out <- parts[1, , drop = FALSE]
  out$area_ha <- ha[1]
  attr(out, "dropped") <- length(ha) - 1L
  out
}

# Satellite imagery with labels on top: state lines, place names and major
# roads. Imagery alone is disorienting -- a field is a rectangle of dirt among
# other rectangles of dirt, and there is nothing to say which county it is in.
#
# Esri's two reference layers are transparent overlays published for exactly
# this. They are not in leaflet's `providers` list in this version, so they go
# in by URL. Tile order is {z}/{y}/{x} for ArcGIS REST, not the {z}/{x}/{y} most
# other tile servers use -- swapped, the map silently serves the wrong tiles.
ESRI_REF <- c(
  places = paste0("https://server.arcgisonline.com/ArcGIS/rest/services/",
                  "Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}"),
  roads  = paste0("https://server.arcgisonline.com/ArcGIS/rest/services/",
                  "Reference/World_Transportation/MapServer/tile/{z}/{y}/{x}")
)

#' Hybrid basemap: Esri imagery with boundaries, places and transportation.
#'
#' Not a layer control. There is one basemap and it always carries labels --
#' toggling was never the point, being able to tell where you are was.
basemap_hybrid <- function(m = leaflet::leaflet()) {
  # Explicit zIndex: all tile layers share one pane, so without it the draw
  # order is whatever the browser settles on and the labels can end up buried.
  m <- leaflet::addProviderTiles(
    m, "Esri.WorldImagery", group = "Satellite",
    options = leaflet::providerTileOptions(zIndex = 1))
  m <- leaflet::addTiles(
    m, urlTemplate = ESRI_REF[["places"]], attribution = NULL,
    options = leaflet::tileOptions(zIndex = 2))
  leaflet::addTiles(
    m, urlTemplate = ESRI_REF[["roads"]], attribution = NULL,
    options = leaflet::tileOptions(zIndex = 3))
}

preview_field <- function(aoi) {
  if (!requireNamespace("leaflet", quietly = TRUE)) {
    stop("Package 'leaflet' is required for preview_field(). Run setup.R.", call. = FALSE)
  }
  bb <- as.numeric(sf::st_bbox(aoi))
  leaflet::leaflet(aoi) |>
    basemap_hybrid() |>
    leaflet::addPolygons(
      fill = FALSE, color = "#ffe100", weight = 3,
      label = ~sprintf("%s -- %.1f ha", field_id, area_ha)
    ) |>
    leaflet::fitBounds(bb[1], bb[2], bb[3], bb[4])
}
