# ==============================================================================
# draw.R -- Support for boundaries traced by hand on the app's map.
#
# Pure helpers only: geometry, guards and wording. The Shiny wiring lives in
# app.R, so pipeline.R can source this file without needing shiny installed.
#
# WHY A CHECK BEFORE A RUN
# A traced boundary is the worst kind the pipeline sees. Validation against 347
# Georgia field-years measured it: where CDL assigned under 60% of a boundary to
# a single crop, the pipeline agreed with the grower's reported crop 12.9% of
# the time. Above 75% it was 88.7%. Someone sketching from memory over satellite
# imagery will sometimes take in a headland, a turn row, or half the next field,
# and nothing downstream can recover from that -- the season curve becomes a
# blend of two crops and the planting date belongs to neither.
#
# Reading CDL for a drawn polygon costs well under a second from the local store
# (see cdl_local.R). The full pipeline costs one to three minutes. So the CDL
# check runs first, the result is shown, and the expensive read happens only
# once the user has seen what they drew and said go.
# ==============================================================================

# Sentinel-2 read time scales with area, and the demo library tops out at 173 ha.
# Without a ceiling a single drag can enqueue a county and hang the app in front
# of an audience.
DRAW_MAX_HA <- 500
DRAW_MIN_HA <- 0.5      # below this there are too few 10 m pixels to average

# CDL is CONUS only. Catching this here gives a sentence instead of a failure
# several minutes into a read.
DRAW_CONUS <- c(xmin = -125, ymin = 24, xmax = -66, ymax = 50)

# Purity bands, from the validation run. These are measured, not chosen.
DRAW_PURITY_GOOD <- 75
DRAW_PURITY_POOR <- 60

#' Build an sf polygon from a leaflet.extras draw event.
#'
#' The event carries GeoJSON-shaped nested lists: coordinates[[ring]][[pt]] is
#' a two-element list of lng, lat. Returns NULL for anything that is not a
#' polygon or rectangle, which is what the toolbar is limited to anyway.
drawn_to_sf <- function(feature) {
  if (is.null(feature) || is.null(feature$geometry)) return(NULL)
  g <- feature$geometry
  if (!identical(tolower(g$type), "polygon")) return(NULL)

  rings <- lapply(g$coordinates, function(ring) {
    m <- do.call(rbind, lapply(ring, function(pt) as.numeric(unlist(pt)[1:2])))
    # Leaflet does not repeat the closing vertex; sf requires it.
    if (!identical(m[1, ], m[nrow(m), ])) m <- rbind(m, m[1, , drop = FALSE])
    m
  })
  if (!length(rings) || nrow(rings[[1]]) < 4) return(NULL)

  poly <- sf::st_polygon(rings)
  aoi  <- sf::st_sf(field_id = "drawn",
                    geometry = sf::st_sfc(poly, crs = 4326))
  # A traced ring is often self-intersecting where the hand crossed over.
  if (!all(sf::st_is_valid(aoi))) aoi <- sf::st_make_valid(aoi)
  aoi$area_ha <- as.numeric(sf::st_area(sf::st_transform(aoi, 5070))) / 1e4
  aoi
}

#' Is this drawing something the pipeline can actually work on?
#'
#' Returns NULL when fine, or a one-sentence reason when not.
drawn_problem <- function(aoi) {
  if (is.null(aoi) || !nrow(aoi)) {
    return("That shape did not come through as a polygon. Try drawing it again.")
  }
  ha <- sum(aoi$area_ha)
  if (ha > DRAW_MAX_HA) {
    return(sprintf(paste0("That boundary is %.0f ha. The limit here is %d ha -- ",
                          "above that a single field read takes long enough to ",
                          "stall the app. Draw one field rather than a block of ",
                          "them."), ha, DRAW_MAX_HA))
  }
  if (ha < DRAW_MIN_HA) {
    return(sprintf(paste0("That boundary is %.2f ha, which is only a handful of ",
                          "10 m pixels. Draw the whole field."), ha))
  }
  bb <- as.numeric(sf::st_bbox(aoi))
  if (bb[1] < DRAW_CONUS[["xmin"]] || bb[3] > DRAW_CONUS[["xmax"]] ||
      bb[2] < DRAW_CONUS[["ymin"]] || bb[4] > DRAW_CONUS[["ymax"]]) {
    return(paste0("That boundary is outside the continental US. The USDA ",
                  "Cropland Data Layer does not cover it, so crop type and ",
                  "every check built on it would be unavailable."))
  }
  NULL
}

#' Plain-English verdict on a drawn boundary, from its CDL history.
#'
#' `per_year` is the data frame cdl_split_advice() returns; `pct` on it is the
#' share of the boundary the dominant crop covers that year.
#'
#' Returns level ("good", "fair", "poor"), a headline and a detail sentence.
drawn_verdict <- function(per_year) {
  if (is.null(per_year) || !nrow(per_year)) {
    return(list(level = "poor", headline = "No crop data for this boundary",
                detail = paste0("CDL returned nothing inside it. That usually ",
                                "means the polygon fell on water, woodland or ",
                                "developed ground rather than cropland.")))
  }
  worst <- min(per_year$pct, na.rm = TRUE)
  typ   <- stats::median(per_year$pct, na.rm = TRUE)
  crops <- paste(unique(per_year$dominant), collapse = ", ")

  if (typ >= DRAW_PURITY_GOOD) {
    list(level = "good",
         headline = sprintf("Looks like one field (%.0f%% one crop)", typ),
         detail = sprintf(paste0("CDL assigns a median %.0f%% of this boundary ",
                                 "to a single crop each year, worst year %.0f%%. ",
                                 "Boundaries this clean matched the grower's own ",
                                 "answer 88.7%% of the time in validation. ",
                                 "Rotation seen: %s."), typ, worst, crops))
  } else if (typ >= DRAW_PURITY_POOR) {
    list(level = "fair",
         headline = sprintf("Mixed -- %.0f%% one crop", typ),
         detail = sprintf(paste0("A median %.0f%% of this boundary is one crop, ",
                                 "worst year %.0f%%. That is borderline: part of ",
                                 "a neighbouring field or a headland is probably ",
                                 "inside the line. Results will be a blend. ",
                                 "Rotation seen: %s."), typ, worst, crops))
  } else {
    list(level = "poor",
         headline = sprintf("Two fields, not one (%.0f%% one crop)", typ),
         detail = sprintf(paste0("Only a median %.0f%% of this boundary carries ",
                                 "a single crop, worst year %.0f%%. Boundaries ",
                                 "this mixed agreed with the grower's reported ",
                                 "crop just 12.9%% of the time in validation. ",
                                 "The season curve would be two crops averaged ",
                                 "together and the planting date would belong to ",
                                 "neither. Redraw around one management unit. ",
                                 "Crops seen: %s."), typ, worst, crops))
  }
}
