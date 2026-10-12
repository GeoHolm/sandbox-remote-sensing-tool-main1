# ==============================================================================
# climate.R -- Daily gridMET weather for a field, and workable field-work dates
#
# Port of python/fieldrs/climate.py; keep the two in step. The module docstring
# there carries the full reasoning; the short version:
#
# WHERE THE DATA COMES FROM
# gridMET (Abatzoglou 2013), a 4 km daily surface meteorology grid for CONUS,
# 1979 to about two days ago, read through the CSIP climate service at Colorado
# State: one point (the field centroid) and a date range in, a daily table out.
#
# WHY WORKABLE DATES
# NDVI dates the canopy, not the planter or the combine, and lands within about
# two weeks. Field work does not happen on a rain day, so within that window a
# rain day is the least likely answer. The final date is the NDVI estimate
# moved, when it falls on an unworkable day, to the last workable day before it
# (a farmer acts ahead of the forecast), at most FORECAST_DAYS earlier; failing
# that, the first workable day after. It never leaves its own window.
#
# A day is unworkable when its rain exceeds DRY_PR_MM, when it is within
# HEAVY_RAIN_WET_DAYS after a day of HEAVY_RAIN_MM or more (wet soil), and --
# with the wind check on -- when its gridMET daily-mean wind reaches the limit.
# gridMET has no gusts, so the wind limit applies to the daily mean.
# ==============================================================================

GRIDMET_URL <- Sys.getenv(
  "GRIDMET_URL", unset = "https://csip.engr.colostate.edu:9088/csip-climate/d/gridmet/2.0")

DRY_PR_MM           <- 0.0    # a day is rain-free at or below this (mm)
WIND_MAX_KMH        <- 30.0   # daily-mean wind limit when the wind check is on (~20 mph)
GRIDMET_OUTPUTS     <- c("pr", "vs")
FORECAST_DAYS       <- 5      # how far ahead a farmer can plan from a forecast
FORECAST_EVENTS     <- c("planting", "seeding", "harvest", "termination")
HEAVY_RAIN_MM       <- 25.0   # one inch: too wet to get in tomorrow
HEAVY_RAIN_WET_DAYS <- 1
GRIDMET_FIRST_YEAR  <- 1979
GRIDMET_SETTLE_DAYS <- 60     # a year is cached for good this long into the next
GRIDMET_TRIES       <- 3
GRIDMET_BACKOFF     <- c(2, 5)

#' (lon, lat) of the field centroid, taken in an equal-area projection.
field_centroid <- function(aoi) {
  g <- sf::st_union(sf::st_geometry(sf::st_transform(aoi, 5070)))
  p <- sf::st_coordinates(sf::st_transform(sf::st_centroid(g), 4326))
  c(lon = unname(p[1, "X"]), lat = unname(p[1, "Y"]))
}

#' One gridMET request through the CSIP service. Stops with a message rather
#' than returning anything that should not be cached.
#'
#' The request is what the Python csip client sends: a multipart POST whose
#' `param` part is a JSON document {metainfo: {mode: "sync"}, parameter: [...]}.
gridmet_request <- function(lon, lat, start, end, outputs = GRIDMET_OUTPUTS,
                            timeout = 60) {
  body <- list(
    metainfo = list(mode = "sync"),
    parameter = list(
      list(name = "location", value = list(type = "Point", coordinates = c(lon, lat))),
      list(name = "outputs", value = as.list(outputs)),
      list(name = "units", value = "metric"),
      list(name = "output_type", value = "geojson"),
      list(name = "start_date", value = start),
      list(name = "end_date", value = end)))
  tmp <- tempfile(fileext = ".json")
  on.exit(unlink(tmp), add = TRUE)
  writeLines(jsonlite::toJSON(body, auto_unbox = TRUE, digits = NA), tmp)

  resp <- NULL
  for (attempt in seq_len(GRIDMET_TRIES)) {
    resp <- tryCatch(
      httr::POST(GRIDMET_URL,
                 body = list(param = httr::upload_file(tmp, type = "application/json")),
                 encode = "multipart", httr::timeout(timeout)),
      error = function(e) e)
    transient <- inherits(resp, "error") ||
      httr::status_code(resp) %in% c(429, 500, 502, 503, 504)
    if (!transient || attempt == GRIDMET_TRIES) break
    Sys.sleep(GRIDMET_BACKOFF[attempt])
  }
  if (inherits(resp, "error"))
    stop("gridMET service unreachable: ", conditionMessage(resp), call. = FALSE)
  if (httr::status_code(resp) != 200)
    stop(sprintf("gridMET service unreachable: HTTP %d (%s)",
                 httr::status_code(resp), GRIDMET_URL), call. = FALSE)

  js <- jsonlite::fromJSON(httr::content(resp, as = "text", encoding = "UTF-8"),
                           simplifyVector = FALSE)
  status <- js$metainfo$status %||% ""
  if (identical(status, "Failed"))
    stop("gridMET service failed: ", js$metainfo$error %||% "no message", call. = FALSE)
  if (!identical(status, "Finished"))
    stop("gridMET service did not finish: status ", status, call. = FALSE)

  data <- NULL
  for (r in js$result) if (identical(r$name, "data")) data <- r$value
  if (is.null(data) || length(data) < 2)
    stop(sprintf(paste0("gridMET returned no days for (%.4f, %.4f) %s to %s. ",
                        "gridMET covers CONUS land only, 1979 to about two days ago."),
                 lon, lat, start, end), call. = FALSE)

  header <- unlist(data[[1]])
  rows <- data[-1]
  # "pr (mm)" -> "pr_mm", "vs (m/s)" -> "vs_ms", "tmmx (degC)" -> "tmmx_degc"
  nm <- vapply(header[-1], function(h) {
    var <- tolower(sub(" \\(.*$", "", h))
    unit <- if (grepl("\\(", h)) gsub("[^a-z0-9]+", "", tolower(sub("^[^(]*\\(", "", h))) else ""
    if (nzchar(unit)) paste0(var, "_", unit) else var
  }, character(1))
  df <- data.frame(date = as.Date(vapply(rows, function(r) as.character(r[[1]]), character(1))),
                   stringsAsFactors = FALSE)
  for (j in seq_along(nm)) {
    df[[nm[j]]] <- suppressWarnings(as.numeric(vapply(rows, function(r) {
      v <- r[[j + 1]]; if (is.null(v)) NA_character_ else as.character(v)
    }, character(1))))
  }
  df <- df[!is.na(df$date), ]
  for (v in outputs) {
    col <- names(df)[sub("_.*$", "", names(df)) == v][1]
    if (is.na(col) || all(is.na(df[[col]])))
      stop(sprintf("gridMET returned no values for '%s' (%s to %s) -- unknown variable or no coverage.",
                   v, start, end), call. = FALSE)
  }
  rownames(df) <- NULL
  df
}

#' Daily gridMET at the field centroid, start to end inclusive.
#'
#' Fetched one calendar year per request. Settled years are cached for good;
#' the current year -- and the previous one, until GRIDMET_SETTLE_DAYS into
#' the new year -- is cached per day. A year that fails is skipped, and
#' attr(, "errors") maps year -> message; stops only when every year failed.
gridmet_daily <- function(aoi, start, end, outputs = GRIDMET_OUTPUTS, timeout = 60) {
  ll <- field_centroid(aoi)
  today <- Sys.Date()
  s <- as.Date(start); e <- min(as.Date(end), today)
  parts <- list(); errors <- list()
  for (y in max(as.integer(format(s, "%Y")), GRIDMET_FIRST_YEAR):as.integer(format(e, "%Y"))) {
    ys <- as.Date(sprintf("%d-01-01", y)); ye <- min(as.Date(sprintf("%d-12-31", y)), today)
    settled <- today >= as.Date(sprintf("%d-01-01", y + 1)) + GRIDMET_SETTLE_DAYS
    stamp <- if (settled) "final" else format(today)
    key <- sprintf("%.4f_%.4f_%d_%s_%s", ll[["lon"]], ll[["lat"]], y,
                   paste(outputs, collapse = "-"), stamp)
    df <- cache_get(key, "gridmet")
    if (is.null(df)) {
      df <- tryCatch(gridmet_request(ll[["lon"]], ll[["lat"]], format(ys), format(ye),
                                     outputs, timeout),
                     error = function(err) { errors[[as.character(y)]] <<- conditionMessage(err); NULL })
      if (is.null(df)) next
      cache_put(key, df, "gridmet")
    }
    parts[[length(parts) + 1]] <- df
  }
  if (!length(parts)) {
    if (length(errors)) stop("no gridMET data for any year: ", errors[[1]], call. = FALSE)
    return(data.frame(date = as.Date(character(0))))
  }
  out <- do.call(rbind, parts)
  out <- out[out$date >= s & out$date <= e, ]
  if ("vs_ms" %in% names(out)) out$wind_kmh <- round(out$vs_ms * 3.6, 1)
  rownames(out) <- NULL
  attr(out, "errors") <- errors
  out
}

#' Per day: the heavy rain (mm, date) that leaves the soil too wet, if any.
wet_soil <- function(weather, heavy_mm = HEAVY_RAIN_MM, wet_days = HEAVY_RAIN_WET_DAYS) {
  out <- data.frame(date = weather$date, wet_mm = NA_real_, wet_on = as.Date(NA))
  if (is.null(heavy_mm) || is.na(heavy_mm) || wet_days <= 0 || !"pr_mm" %in% names(weather))
    return(out)
  pr <- stats::setNames(weather$pr_mm, format(weather$date))
  for (k in wet_days:1) {                 # nearest last, so it wins
    prev <- pr[format(weather$date - k)]
    hit <- !is.na(prev) & prev >= heavy_mm
    out$wet_mm[hit] <- prev[hit]
    out$wet_on[hit] <- weather$date[hit] - k
  }
  out
}

#' Field-work day for an event estimated at `est`, within [lo, hi].
#'
#' A workable `est` stays put. Otherwise the date moves to the last workable
#' day before it, at most `max_lead` days earlier; failing that, to the first
#' workable day after; failing that too, to the earlier day beyond the forecast.
#' @return list(date, note); date is NA when the window has no weather data or
#'   no workable day at all.
workable_day_before <- function(est, lo, hi, weather, dry_mm = DRY_PR_MM,
                                wind_max_kmh = NULL, max_lead = NULL,
                                heavy_mm = HEAVY_RAIN_MM,
                                wet_days = HEAVY_RAIN_WET_DAYS) {
  if (is.null(est) || is.na(est)) return(list(date = as.Date(NA), note = ""))
  est <- as.Date(est)
  lo <- if (is.null(lo) || is.na(lo)) est else as.Date(lo)
  hi <- if (is.null(hi) || is.na(hi)) est else as.Date(hi)
  wind <- !is.null(wind_max_kmh) && !is.na(wind_max_kmh)
  cols <- if (wind) c("pr_mm", "wind_kmh") else "pr_mm"
  if (!all(cols %in% names(weather)))
    return(list(date = as.Date(NA), note = "no gridMET data for window"))
  wet <- if ("wet_mm" %in% names(weather)) weather[, c("date", "wet_mm", "wet_on")]
         else wet_soil(weather, heavy_mm, wet_days)
  sel <- weather$date >= lo & weather$date <= hi & stats::complete.cases(weather[, cols, drop = FALSE])
  w <- weather[sel, , drop = FALSE]
  if (!nrow(w)) return(list(date = as.Date(NA), note = "no gridMET data for window"))
  ok <- w$pr_mm <= dry_mm
  if (wind) ok <- ok & w$wind_kmh < wind_max_kmh
  wmm <- wet$wet_mm[match(w$date, wet$date)]
  ok <- ok & is.na(wmm)
  good <- w$date[ok]
  what <- if (wind) "rain-free and calm" else "rain-free"
  if (!length(good)) return(list(date = as.Date(NA),
                                 note = sprintf("no %s day in window (%d d)", what, nrow(w))))
  if (est %in% good) return(list(date = est, note = what))

  # Why the estimate itself was not workable.
  ahead <- character(0); why <- character(0)
  i <- match(est, w$date)
  if (!is.na(i)) {
    if (w$pr_mm[i] > dry_mm) { why <- c(why, sprintf("%.1f mm", w$pr_mm[i])); ahead <- c(ahead, "rain") }
    if (wind && w$wind_kmh[i] >= wind_max_kmh) {
      why <- c(why, sprintf("%.0f km/h mean wind", w$wind_kmh[i])); ahead <- c(ahead, "wind")
    }
    why <- if (length(why)) paste0(paste(why, collapse = ", "), " on estimate") else ""
    j <- match(est, wet$date)
    if (!is.na(j) && !is.na(wet$wet_mm[j])) {
      soil <- sprintf("soil wet after %.0f mm on %s", wet$wet_mm[j], format(wet$wet_on[j], "%m-%d"))
      why <- if (nzchar(why)) paste0(why, "; ", soil) else soil
      if (!"rain" %in% ahead) ahead <- c(ahead, "rain")
    }
  } else {
    why <- "no data on estimate"; ahead <- "weather"
  }
  ahead <- paste(ahead, collapse = " and ")

  before <- good[good < est]; after <- good[good > est]
  near <- if (is.null(max_lead)) before else before[before >= est - max_lead]
  if (length(near)) {
    best <- max(near)
    return(list(date = best, note = sprintf("moved %+d d, ahead of %s (%s)",
                                            as.integer(best - est), ahead, why)))
  }
  if (length(after)) {
    best <- min(after)
    reason <- if (length(before)) sprintf("no %s day within the %s-day forecast before it", what, max_lead)
              else sprintf("no %s day before it in window", what)
    return(list(date = best, note = sprintf("moved %+d d, after %s -- %s (%s)",
                                            as.integer(best - est), ahead, reason, why)))
  }
  best <- max(before)
  list(date = best, note = sprintf(
    "moved %+d d, ahead of %s -- beyond the %s-day forecast, but no %s day after it in window (%s)",
    as.integer(best - est), ahead, max_lead, what, why))
}

#' Final field-work dates for each <event>_est / _lo / _hi.
#'
#' Adds, per event: <event>_date (final date), _shift_d, _pr_mm, _wind_kmh and
#' _weather_note. `not_before` optionally raises an event's window start per
#' row (named list event -> vector of dates, one per row). The estimate columns
#' are never modified.
weather_free_events <- function(df, weather, events, dry_mm = DRY_PR_MM,
                                wind_max_kmh = NULL, not_before = NULL,
                                forecast_days = FORECAST_DAYS,
                                heavy_mm = HEAVY_RAIN_MM,
                                wet_days = HEAVY_RAIN_WET_DAYS) {
  if (is.null(df) || !nrow(df)) return(df)
  wx <- if (is.null(weather)) NULL else {
    ws <- wet_soil(weather, heavy_mm, wet_days)
    cbind(weather, ws[, c("wet_mm", "wet_on")])
  }
  at <- function(day, col) {
    if (is.null(wx) || !col %in% names(wx) || is.na(day)) return(NA_real_)
    v <- wx[[col]][match(day, wx$date)]
    if (length(v) && !is.na(v)) v else NA_real_
  }
  for (ev in events) {
    n <- nrow(df)
    finals <- rep(as.Date(NA), n); shifts <- rep(NA_integer_, n)
    prs <- rep(NA_real_, n); winds <- rep(NA_real_, n); notes <- rep(NA_character_, n)
    floor <- not_before[[ev]]
    for (i in seq_len(n)) {
      est <- df[[paste0(ev, "_est")]][i]
      if (is.na(est)) next
      lo <- df[[paste0(ev, "_lo")]][i]
      if (!is.null(floor) && !is.na(floor[i])) lo <- if (is.na(lo)) floor[i] else max(as.Date(lo), floor[i])
      r <- if (is.null(wx)) list(date = as.Date(NA), note = "gridMET unavailable")
           else workable_day_before(est, lo, df[[paste0(ev, "_hi")]][i], wx, dry_mm,
                                    wind_max_kmh,
                                    if (ev %in% FORECAST_EVENTS) forecast_days else NULL,
                                    heavy_mm, wet_days)
      final <- if (is.na(r$date)) as.Date(est) else r$date
      finals[i] <- final; shifts[i] <- as.integer(final - as.Date(est))
      prs[i] <- at(final, "pr_mm"); winds[i] <- at(final, "wind_kmh"); notes[i] <- r$note
    }
    df[[paste0(ev, "_date")]] <- finals
    df[[paste0(ev, "_shift_d")]] <- shifts
    df[[paste0(ev, "_pr_mm")]] <- prs
    df[[paste0(ev, "_wind_kmh")]] <- winds
    df[[paste0(ev, "_weather_note")]] <- notes
  }
  df
}

#' Final planting and harvest dates -- weather_free_events() on the phenology
#' table. planting_est / harvest_est are left untouched.
weather_free_phenology <- function(phen, weather, dry_mm = DRY_PR_MM,
                                   wind_max_kmh = NULL, forecast_days = FORECAST_DAYS,
                                   heavy_mm = HEAVY_RAIN_MM,
                                   wet_days = HEAVY_RAIN_WET_DAYS) {
  weather_free_events(phen, weather, c("planting", "harvest"), dry_mm, wind_max_kmh,
                      forecast_days = forecast_days, heavy_mm = heavy_mm,
                      wet_days = wet_days)
}

.rain_cols <- function(events) {
  as.vector(outer(c("date", "shift_d", "pr_mm", "wind_kmh", "weather_note"), events,
                  function(c, ev) paste0(ev, "_", c)))
}

#' The weather date step on its own -- port of pipeline.apply_rain_check().
#'
#' Takes the phenology and cover crop tables and returns them with the final
#' dates added (rain-free when `rain_free`, the estimates otherwise), plus
#' season_days_final and cover_days_final. Nothing upstream changes, so a UI
#' toggling the check calls this on what it already has. A cover crop's
#' seeding window never opens before the cash crop's final harvest date.
#' @return list(phen, cc, weather, check).
apply_rain_check <- function(aoi, phen, cc, start, end, rain_free = TRUE,
                             dry_mm = DRY_PR_MM, wind_max_kmh = NULL,
                             forecast_days = FORECAST_DAYS,
                             heavy_mm = HEAVY_RAIN_MM,
                             wet_days = HEAVY_RAIN_WET_DAYS) {
  drop <- function(df, cols) if (is.null(df)) df else df[, setdiff(names(df), cols), drop = FALSE]
  phen <- drop(phen, c(.rain_cols(c("planting", "harvest")), "season_days_final"))
  cc   <- drop(cc, c(.rain_cols(c("seeding", "termination")), "cover_days_final"))
  weather <- NULL
  if (rain_free && !is.null(phen)) {
    weather <- tryCatch(gridmet_daily(aoi, start, end), error = function(e) {
      message("  gridMET unavailable, dates left as estimates: ", conditionMessage(e))
      NULL
    })
    phen <- weather_free_phenology(phen, weather, dry_mm, wind_max_kmh,
                                   forecast_days, heavy_mm, wet_days)
    if (!is.null(cc) && "seeding_est" %in% names(cc)) {
      harv <- phen$harvest_date[match(cc$fall_year, phen$year)]
      cc <- weather_free_events(cc, weather, c("seeding", "termination"), dry_mm,
                                wind_max_kmh, not_before = list(seeding = harv),
                                forecast_days = forecast_days,
                                heavy_mm = heavy_mm, wet_days = wet_days)
    }
  }
  if (!is.null(phen)) {
    p <- if ("planting_date" %in% names(phen)) phen$planting_date else phen$planting_est
    h <- if ("harvest_date" %in% names(phen)) phen$harvest_date else phen$harvest_est
    phen$season_days_final <- as.integer(as.Date(h) - as.Date(p))
  }
  if (!is.null(cc) && "seeding_est" %in% names(cc)) {
    s <- if ("seeding_date" %in% names(cc)) cc$seeding_date else cc$seeding_est
    t <- if ("termination_date" %in% names(cc)) cc$termination_date else cc$termination_est
    cc$cover_days_final <- as.integer(as.Date(t) - as.Date(s))
  }
  check <- if (rain_free && !is.null(phen))
    list(dry_mm = dry_mm, wind_max_kmh = wind_max_kmh, forecast_days = forecast_days,
         heavy_mm = heavy_mm, wet_days = wet_days) else NULL
  list(phen = phen, cc = cc, weather = weather, check = check)
}
