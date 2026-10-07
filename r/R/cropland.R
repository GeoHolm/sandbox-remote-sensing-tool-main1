# ==============================================================================
# cropland.R -- USDA Cropland Data Layer (CDL)
#
# The CDL is USDA NASS's annual 30 m crop-type map of the US. It tells you what
# was actually planted in each field each year, which is what turns a generic
# NDVI curve into "this is the corn signal".
#
# Source: the CropScape web service at George Mason University, which clips the
# national layer to your bounding box on demand. No account needed. It is a
# public service and is occasionally slow -- hence the generous timeout.
# ==============================================================================

CROPSCAPE_URL <- "https://nassgeodata.gmu.edu/axis2/services/CDLService/GetCDLFile"

#' Fetch the Cropland Data Layer for a field.
#'
#' @param aoi   sf object from load_field().
#' @param year  Calendar year. CDL runs 2008-present and is published each
#'              January/February for the previous season.
#' @param clip  Mask to the exact field polygon.
#' @return A categorical SpatRaster of CDL class codes (30 m, EPSG:5070).
get_cdl <- function(aoi, year, clip = TRUE, timeout = 180) {
  # Prefer the local bulk store when one is present -- see cdl_local.R. Not for
  # better numbers (the two agree on 346 of 347 field-years) but because
  # CropScape throttles and times out, and reading a file does not.
  if (cdl_use_local()) {
    hit <- tryCatch(get_cdl_local(aoi, year, clip = clip), error = function(e) NULL)
    if (!is.null(hit)) return(hit)
    # That year is not downloaded; the API can still answer for it.
  }

  bb <- sf::st_bbox(sf::st_buffer(sf::st_transform(sf::st_union(aoi), 5070), 100))

  url <- sprintf("%s?year=%d&bbox=%f,%f,%f,%f", CROPSCAPE_URL, year,
                 bb[["xmin"]], bb[["ymin"]], bb[["xmax"]], bb[["ymax"]])

  message(sprintf("  Requesting CDL %d from CropScape...", year))
  old <- options(timeout = timeout); on.exit(options(old), add = TRUE)

  xml <- tryCatch(paste(readLines(url, warn = FALSE), collapse = ""),
                  error = function(e) {
                    stop("CropScape request failed: ", conditionMessage(e),
                         "\n  The service is sometimes down. Try again shortly.",
                         call. = FALSE)
                  })

  tif_url <- sub(".*<returnURL>(.*?)</returnURL>.*", "\\1", xml)
  if (identical(tif_url, xml) || !nzchar(tif_url)) {
    stop("Could not parse a GeoTIFF URL from the CropScape response.\n",
         "  Response was: ", substr(xml, 1, 300),
         "\n  Most often this means CDL has no data for ", year,
         " yet, or the area is outside the US.", call. = FALSE)
  }

  dest <- file.path(tempdir(), basename(tif_url))
  utils::download.file(tif_url, dest, mode = "wb", quiet = TRUE)

  r <- terra::rast(dest)
  names(r) <- paste0("cdl_", year)

  if (clip) {
    poly <- terra::project(terra::vect(sf::st_union(aoi)), terra::crs(r))
    # touches = FALSE keeps only cells whose CENTRE is inside the boundary.
    # The default pulls in every cell the polygon so much as clips, which at
    # 30 m is a lot of edge: on a 17 ha field it returned 233 cells (21.0 ha)
    # for a field of 17.2 ha -- 22% too many, and those extra cells carry the
    # neighbouring field's crop. That inflates every CDL area figure and biases
    # the boundary check towards "split".
    r <- terra::mask(terra::crop(r, poly), poly, touches = FALSE)
  }
  r
}

#' Break a field down by CDL class.
#'
#' @return Data frame of class code, name, pixel count, hectares and percent,
#'         sorted by area.
cdl_summary <- function(cdl) {
  v <- terra::values(cdl)
  v <- v[!is.na(v)]
  if (length(v) == 0) stop("No CDL pixels inside the field.", call. = FALSE)

  tab <- as.data.frame(table(v), stringsAsFactors = FALSE)
  names(tab) <- c("code", "n_pixels")
  tab$code <- as.integer(tab$code)

  px_area_ha <- prod(terra::res(cdl)) / 1e4   # 30 x 30 m = 0.09 ha
  tab$crop    <- cdl_name(tab$code)
  tab$area_ha <- round(tab$n_pixels * px_area_ha, 2)
  tab$pct     <- round(100 * tab$n_pixels / sum(tab$n_pixels), 1)
  tab$is_crop <- !tab$code %in% CDL_NONCROP

  tab <- tab[order(-tab$n_pixels), c("code", "crop", "n_pixels", "area_ha", "pct", "is_crop")]
  rownames(tab) <- NULL
  tab
}

#' The single dominant crop in a field, as a one-row data frame.
dominant_crop <- function(cdl) {
  cdl_summary(cdl)[1, ]
}

#' Every year's CDL for a field, on one aligned grid.
#'
#' This is the primitive the rest of the CDL code builds on -- the rotation
#' table and the boundary advice both read it, so a field costs one CropScape
#' round trip per year and no more.
#'
#' SpatRasters cannot be saved to RDS directly, so the cache holds a packed
#' copy (terra::wrap) and unpacks it on the way out.
#'
#' @return Multi-layer SpatRaster, one layer per year, named cdl_YYYY.
cdl_stack <- function(aoi, years = NULL, refresh = FALSE, only_cached = FALSE,
                      progress = NULL) {
  if (is.null(years)) {
    years <- 2020:(as.integer(format(Sys.Date(), "%Y")) - 1)
  }
  key <- cache_key(aoi, years, "cdl_stack_v2")
  hit <- if (refresh) NULL else cache_get(key, "cdlstack")
  if (!is.null(hit)) return(terra::unwrap(hit))
  if (only_cached) return(NULL)

  layers <- list()
  ref <- NULL
  missing   <- integer(0)
  transient <- FALSE          # service failed, as opposed to "no CDL that year"
  for (k in seq_along(years)) {
    y <- years[k]
    if (!is.null(progress)) progress(k, length(years), sprintf("USDA CDL %d", y))
    err <- NULL
    r <- tryCatch(get_cdl(aoi, y),
                  error = function(e) { err <<- conditionMessage(e); NULL })
    if (is.null(r)) {
      missing <- c(missing, y)
      # Two very different failures. "No CDL published for that year yet" will
      # not change if you retry in a minute; a request that timed out will.
      # Only the second one means the whole service is unreachable -- and if it
      # is, the remaining years will each sit through their own 180 s timeout
      # for nothing. One field over six years is eighteen minutes of the app
      # looking hung. Stop at the first one.
      if (!is.null(err) && grepl("request failed", err, fixed = TRUE)) {
        transient <- TRUE
        message(sprintf("  CropScape is not responding (%d). Skipping the remaining years.", y))
        break
      }
      next
    }

    # CropScape clips each request independently, so grids can differ by a
    # pixel. Snap everything to the first year so the years can be compared
    # pixel for pixel. Classes are categorical: nearest neighbour only.
    if (is.null(ref)) ref <- r else r <- terra::resample(r, ref, method = "near")
    names(r) <- sprintf("cdl_%d", y)
    layers[[length(layers) + 1]] <- r
  }
  if (!length(layers)) {
    stop("CropScape returned no CDL for ", paste(range(years), collapse = "-"),
         ". The service may be down, or the field may be outside the US.",
         call. = FALSE)
  }

  out <- terra::rast(layers)

  if (length(missing)) {
    warning(sprintf(
      "CDL is missing for %s. The rotation, crop labels and the boundary check all cover %d of %d years.%s",
      paste(missing, collapse = ", "), length(layers), length(years),
      if (transient) " CropScape was unreachable, so this result is NOT cached -- run it again when the service is back."
      else " Most likely those years are not published yet."), call. = FALSE)
  }

  # A partial stack caused by an outage must not be cached. It would be
  # indistinguishable from a complete one on every later run, and the field
  # would carry a permanently truncated rotation with nothing to say why.
  # A year that simply is not published yet is different -- retrying soon
  # changes nothing, so that result is worth keeping.
  if (!transient) cache_put(key, terra::wrap(out), "cdlstack")
  out
}

#' Crop rotation history: the dominant CDL crop for each year.
#'
#' @return Data frame of year, crop, percent of field, and purity.
cdl_history <- function(aoi, years = NULL, refresh = FALSE, progress = NULL) {
  cdl_history_from_stack(cdl_stack(aoi, years, refresh = refresh,
                                   progress = progress))
}

#' Rotation table from an already-fetched stack, so callers that need both the
#' rasters and the summary pay for CropScape once.
cdl_history_from_stack <- function(st) {
  rows <- lapply(names(st), function(nm) {
    s <- cdl_summary(st[[nm]])
    data.frame(year = as.integer(sub("cdl_", "", nm)),
               crop = s$crop[1], pct = s$pct[1], is_crop = s$is_crop[1],
               n_classes = nrow(s), stringsAsFactors = FALSE)
  })
  out <- do.call(rbind, rows)
  rownames(out) <- NULL
  out
}

#' Named vector of year -> crop, the shape phenology and cover crop code want.
crop_lookup <- function(hist) {
  v <- stats::setNames(hist$crop, as.character(hist$year))
  v[!is.na(v)]
}

#' Boolean mask of cropland pixels, for excluding roads, farmsteads and water
#' from field statistics.
cropland_mask <- function(cdl) {
  terra::app(cdl, function(v) ifelse(v %in% CDL_NONCROP | is.na(v), NA, 1))
}

#' Plot a CDL raster with a legend of the classes actually present.
plot_cdl <- function(cdl, main = NULL) {
  s <- cdl_summary(cdl)
  s <- s[s$pct >= 0.5, ]
  if (is.null(main)) main <- sub("_", " ", toupper(names(cdl)[1]))

  cols <- stats::setNames(
    grDevices::hcl.colors(nrow(s), "Set 2"),
    as.character(s$code)
  )
  known <- intersect(names(CDL_COLOURS), as.character(s$code))
  cols[known] <- CDL_COLOURS[known]

  terra::plot(cdl, type = "classes", col = unname(cols),
              levels = s$crop, main = main, plg = list(cex = 0.75))
}

#' Look up CDL class names from codes.
cdl_name <- function(code) {
  nm <- CDL_CLASSES[as.character(code)]
  ifelse(is.na(nm), paste0("class ", code), nm)
}

# ------------------------------------------------------------ class tables ---

# The classes that cover essentially all US acreage, plus every non-crop class.
# Anything not listed falls back to "class <code>".
CDL_CLASSES <- c(
  "1" = "Corn", "2" = "Cotton", "3" = "Rice", "4" = "Sorghum", "5" = "Soybeans",
  "6" = "Sunflower", "10" = "Peanuts", "11" = "Tobacco", "12" = "Sweet Corn",
  "13" = "Pop/Orn Corn", "14" = "Mint", "21" = "Barley", "22" = "Durum Wheat",
  "23" = "Spring Wheat", "24" = "Winter Wheat", "25" = "Other Small Grains",
  "26" = "Dbl Crop WinWht/Soybeans", "27" = "Rye", "28" = "Oats", "29" = "Millet",
  "30" = "Speltz", "31" = "Canola", "32" = "Flaxseed", "33" = "Safflower",
  "34" = "Rape Seed", "35" = "Mustard", "36" = "Alfalfa",
  "37" = "Other Hay/Non Alfalfa", "38" = "Camelina", "39" = "Buckwheat",
  "41" = "Sugarbeets", "42" = "Dry Beans", "43" = "Potatoes", "44" = "Other Crops",
  "45" = "Sugarcane", "46" = "Sweet Potatoes", "47" = "Misc Vegs & Fruits",
  "48" = "Watermelons", "49" = "Onions", "50" = "Cucumbers", "51" = "Chick Peas",
  "52" = "Lentils", "53" = "Peas", "54" = "Tomatoes", "55" = "Caneberries",
  "56" = "Hops", "57" = "Herbs", "58" = "Clover/Wildflowers", "59" = "Sod/Grass Seed",
  "60" = "Switchgrass", "61" = "Fallow/Idle Cropland",
  "63" = "Forest", "64" = "Shrubland", "65" = "Barren", "66" = "Cherries",
  "67" = "Peaches", "68" = "Apples", "69" = "Grapes", "70" = "Christmas Trees",
  "71" = "Other Tree Crops", "72" = "Citrus", "74" = "Pecans", "75" = "Almonds",
  "76" = "Walnuts", "77" = "Pears",
  "81" = "Clouds/No Data", "82" = "Developed", "83" = "Water", "87" = "Wetlands",
  "88" = "Nonag/Undefined", "92" = "Aquaculture",
  "111" = "Open Water", "112" = "Perennial Ice/Snow",
  "121" = "Developed/Open Space", "122" = "Developed/Low Intensity",
  "123" = "Developed/Med Intensity", "124" = "Developed/High Intensity",
  "131" = "Barren", "141" = "Deciduous Forest", "142" = "Evergreen Forest",
  "143" = "Mixed Forest", "152" = "Shrubland", "176" = "Grass/Pasture",
  "190" = "Woody Wetlands", "195" = "Herbaceous Wetlands",
  "204" = "Pistachios", "205" = "Triticale", "206" = "Carrots",
  "207" = "Asparagus", "208" = "Garlic", "209" = "Cantaloupes", "210" = "Prunes",
  "211" = "Olives", "212" = "Oranges", "214" = "Broccoli", "216" = "Peppers",
  "217" = "Pomegranates", "218" = "Nectarines", "219" = "Greens", "220" = "Plums",
  "221" = "Strawberries", "222" = "Squash", "223" = "Apricots", "224" = "Vetch",
  "225" = "Dbl Crop WinWht/Corn", "226" = "Dbl Crop Oats/Corn", "227" = "Lettuce",
  "228" = "Dbl Crop Triticale/Corn",
  "229" = "Pumpkins", "236" = "Dbl Crop WinWht/Sorghum",
  "237" = "Dbl Crop Barley/Corn", "238" = "Dbl Crop WinWht/Cotton",
  "239" = "Dbl Crop Soybeans/Oats", "240" = "Dbl Crop Corn/Soybeans",
  "241" = "Dbl Crop", "242" = "Blueberries", "243" = "Cabbage",
  "244" = "Cauliflower", "245" = "Celery", "246" = "Radishes", "247" = "Turnips",
  "250" = "Cranberries", "254" = "Dbl Crop Barley/Soybeans"
)

# Classes that are not agricultural land.
CDL_NONCROP <- c(63, 64, 65, 81, 82, 83, 87, 88, 92, 111, 112,
                 121, 122, 123, 124, 131, 141, 142, 143, 152, 176, 190, 195)

# A few familiar CDL colours so plots of common crops look conventional.
CDL_COLOURS <- c(
  "1" = "#ffd300", "5" = "#267000", "24" = "#a57000", "36" = "#ffa5e2",
  "37" = "#a5f28c", "61" = "#bfbf77", "111" = "#4970a3", "121" = "#9c9c9c",
  "122" = "#9c9c9c", "123" = "#9c9c9c", "124" = "#9c9c9c",
  "141" = "#93cc93", "176" = "#e8ffbf", "190" = "#7fb2b2", "195" = "#7fb2b2"
)
