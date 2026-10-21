# ==============================================================================
# sar.R -- Sentinel-1 radar backscatter over a field, and radar-bracketed
#          operation dates
#
# Port of python/fieldrs/sar.py; keep the two in step. The module docstring
# there carries the full reasoning and what was found on the test fields.
#
# PROTOTYPE. Nothing here is calibrated against grower-reported operation dates.
#
# C-band backscatter from bare soil depends on how rough the surface is and how
# wet it is. Field operations change roughness, and harvest removes a canopy,
# which drops VH. Wetting brightens VV just as roughening does, so VV is
# regressed per orbit on an antecedent precipitation index from gridMET and the
# residual is used (moisture_adjust()); frozen dates are dropped.
#
# Data: Planetary Computer sentinel-1-rtc, terrain-corrected gamma0, 10 m,
# linear power. Different orbits see the field at different incidence angles;
# once the per-orbit offset is removed they are read as one series.
# ==============================================================================

S1_COLLECTION <- "sentinel-1-rtc"
S1_NODATA     <- -32768
S1_EDGE_M     <- 10    # pixels kept only if their centre is this far inside

# --- provisional detection constants (first guesses on one Iowa field) -------
SAR_API_DECAY        <- 0.7    # antecedent precipitation index decay per day
SAR_FROZEN_C         <- 1.0    # 3-day mean air temperature at or below: frozen
SAR_BARE_NDVI        <- 0.30   # bare field: nearest optical NDVI below this
SAR_PLANT_FROM       <- "04-01"
# A winter crop is sown the autumn before its harvest year, so its sowing is
# searched from 1 August of that autumn (the winter model's sowing search), not
# from 1 April -- which left the span empty for every wheat year.
.plant_from <- function(p, y) {
  st <- if ("season_type" %in% names(p)) p$season_type else ""
  if (!is.na(st) && startsWith(st, "winter"))
    as.Date(sprintf("%d-%s", y - 1, WINTER_SOW_SEARCH[1]))
  else as.Date(sprintf("%d-%s", y, SAR_PLANT_FROM))
}
SAR_PLANT_AFTER_D    <- 7
SAR_HARVEST_BEFORE_D <- 14
SAR_HARVEST_AFTER_D  <- 28
SAR_GRIDMET          <- c("pr", "vs", "tmmn", "tmmx")
SAR_SUPPORT_Z        <- 2.0    # a step "supports" a narrowing at this many robust SDs
SAR_CONFLICT_DZ      <- 1.0    # a step outside the window this much stronger: conflict

.db <- function(x) 10 * log10(x)

# ---------------------------------------------------------------- extract ---

#' Field statistics for one acquisition, VV and VH, in dB. NULL when the scene
#' does not cover at least 80% of the field.
s1_read_item <- function(item, aoi) {
  out <- list()
  for (pol in c("vv", "vh")) {
    href <- item$assets[[pol]]$href
    if (is.null(href)) return(NULL)
    r <- terra::rast(paste0("/vsicurl/", href))
    geom <- sf::st_transform(sf::st_union(sf::st_geometry(aoi)), terra::crs(r))
    win <- terra::ext(terra::vect(sf::st_buffer(geom, 30)))
    if (is.null(terra::intersect(win, terra::ext(r)))) return(NULL)
    r <- terra::crop(r, win, snap = "out")
    inner <- sf::st_buffer(geom, -S1_EDGE_M)
    poly <- if (all(sf::st_is_empty(inner))) geom else inner
    inside <- !is.na(terra::values(terra::rasterize(terra::vect(poly), r, field = 1)))[, 1]
    arr <- terra::values(r)[, 1]
    ok <- inside & !is.na(arr) & arr != S1_NODATA & is.finite(arr) & arr > 0
    n_field <- sum(inside)
    if (n_field == 0 || sum(ok) < 0.8 * n_field) return(NULL)
    v <- arr[ok]
    # Averaged in linear power, then converted: the mean of dB is biased low.
    out[[paste0(pol, "_db")]]        <- .db(mean(v))
    out[[paste0(pol, "_median_db")]] <- .db(stats::median(v))
    out[[paste0(pol, "_p10_db")]]    <- .db(unname(stats::quantile(v, 0.10)))
    out[[paste0(pol, "_p90_db")]]    <- .db(unname(stats::quantile(v, 0.90)))
    out$n_pixels <- sum(ok)
  }
  out$vh_vv_db <- out$vh_db - out$vv_db
  out
}

#' Worker: one (date, orbit) group -> one row, trying its slices in order.
s1_read_group <- function(job, aoi, root) {
  suppressPackageStartupMessages({ library(sf); library(terra) })
  if (!exists("s1_read_item", mode = "function")) source(file.path(root, "R", "sar.R"))
  for (it in job$items) {
    r <- tryCatch(s1_read_item(it, aoi), error = function(e) NULL)
    if (!is.null(r)) {
      return(data.frame(date = job$date, orbit = job$orbit,
                        platform = toupper(it$properties$platform %||% ""),
                        scene_id = it$id, as.data.frame(r), stringsAsFactors = FALSE))
    }
  }
  NULL
}

#' One row per Sentinel-1 acquisition over the field, start to end (cached).
#'
#' Acquisitions are deduplicated per (date, relative orbit): adjacent slices of
#' one pass overlap, so the same overpass can appear twice in the catalog.
s1_series <- function(aoi, start, end, workers = 8, only_cached = FALSE,
                      refresh = FALSE) {
  key <- cache_key(aoi, start, end, "s1_series_v1")
  hit <- if (refresh) NULL else cache_get(key, "s1")
  if (!is.null(hit)) return(hit)
  if (only_cached) return(NULL)

  items <- stac_search_retry(field_bbox(aoi), start, end, 500, S1_COLLECTION)
  if (!rstac::items_length(items)) return(NULL)
  items <- rstac::items_sign(items, sign_fn = rstac::sign_planetary_computer())
  feats <- items$features
  date  <- as.Date(substr(vapply(feats, function(f) f$properties$datetime, ""), 1, 10))
  orbit <- vapply(feats, function(f) as.integer(f$properties[["sat:relative_orbit"]] %||% NA), 1L)
  covers <- tryCatch({
    fp <- rstac::items_as_sfc(items)
    lengths(sf::st_covers(fp, sf::st_union(sf::st_transform(aoi, 4326)))) > 0
  }, error = function(e) rep(FALSE, length(feats)))
  grp <- split(seq_along(feats), paste(date, orbit))
  jobs <- lapply(grp, function(idx) {
    idx <- idx[order(!covers[idx])]          # slices covering the field first
    list(items = feats[idx], date = date[idx[1]], orbit = orbit[idx[1]])
  })
  root <- normalizePath(".", winslash = "/")
  use_parallel <- ensure_workers(workers)
  message(sprintf("  Reading %d Sentinel-1 acquisitions%s...", length(jobs),
                  if (use_parallel) sprintf(" across %d workers", workers) else ""))
  rows <- if (use_parallel) {
    furrr::future_map(jobs, s1_read_group, aoi = aoi, root = root,
                      .options = furrr::furrr_options(seed = TRUE))
  } else lapply(jobs, s1_read_group, aoi = aoi, root = root)
  rows <- Filter(Negate(is.null), rows)
  if (!length(rows)) return(NULL)
  df <- do.call(rbind, rows)
  df <- df[order(df$date, df$orbit), ]
  rownames(df) <- NULL
  cache_put(key, df, "s1")
}

# ----------------------------------------------------------------- detect ---

#' NDVI on the nearest optical observation, within 10 days, or NA.
.ndvi_at <- function(ndvi, day) {
  if (is.null(ndvi) || !nrow(ndvi)) return(NA_real_)
  gap <- as.numeric(ndvi$date - day)
  i <- which.min(abs(gap))
  if (abs(gap[i]) <= 10) ndvi$mean[i] else NA_real_
}

#' Add the moisture, freeze and greenness state of each acquisition.
#'
#' Acquisitions over CONUS are at about 00:06 UTC, i.e. the evening before
#' locally, so weather is read for the UTC date minus one day. Adds api_mm,
#' tmean3_c, frozen, ndvi, bare, vh_c (orbit-centred VH) and vv_adj (see
#' moisture_adjust()).
#' @param ndvi Data frame with date and mean (the field's NDVI observations).
s1_context <- function(s1, weather, ndvi) {
  days <- seq(min(weather$date), max(weather$date), by = 1)
  w <- weather[match(days, weather$date), ]
  pr <- w$pr_mm; pr[is.na(pr)] <- 0
  # pandas ewm(alpha = 1 - k, adjust = False): y0 = x0, y_t = k y_{t-1} + (1-k) x_t
  k <- SAR_API_DECAY
  api <- numeric(length(pr)); api[1] <- pr[1]
  for (t in seq_along(pr)[-1]) api[t] <- k * api[t - 1] + (1 - k) * pr[t]
  api <- api / (1 - k)
  tm <- (w$tmmx_degc + w$tmmn_degc) / 2
  tmean3 <- as.numeric(stats::filter(tm, rep(1 / 3, 3), sides = 1))
  local <- match(s1$date - 1, days)
  s1$api_mm   <- api[local]
  s1$tmean3_c <- tmean3[local]
  s1$frozen   <- !is.na(s1$tmean3_c) & s1$tmean3_c <= SAR_FROZEN_C
  s1$ndvi     <- vapply(seq_len(nrow(s1)), function(i) .ndvi_at(ndvi, s1$date[i]), 0)
  s1$bare     <- !is.na(s1$ndvi) & s1$ndvi < SAR_BARE_NDVI
  s1$vh_c     <- s1$vh_db - stats::ave(s1$vh_db, s1$orbit, FUN = stats::median)
  moisture_adjust(s1)
}

#' VV with the rain-driven part and the orbit offset taken out.
#'
#' Per orbit, VV on bare unfrozen dates is regressed on log(1 + API) and the
#' residual kept as vv_adj. PROVISIONAL, and fitted per field. The fit is
#' stored in attr(, "moisture_fit"). Orbits with fewer than 10 such dates get
#' no fit and vv_adj stays NA.
moisture_adjust <- function(s1) {
  s1$vv_adj <- NA_real_
  fits <- list()
  for (o in sort(unique(s1$orbit))) {
    g <- which(s1$orbit == o)
    f <- g[s1$bare[g] & !s1$frozen[g] & !is.na(s1$api_mm[g]) & !is.na(s1$vv_db[g])]
    if (length(f) < 10) next
    x <- log1p(s1$api_mm[f]); y <- s1$vv_db[f]
    cf <- stats::coef(stats::lm(y ~ x))
    fits[[as.character(o)]] <- list(intercept = round(cf[[1]], 3), slope = round(cf[[2]], 3),
                                    r = round(stats::cor(x, y), 3), n = length(f))
    s1$vv_adj[g] <- s1$vv_db[g] - (cf[[1]] + cf[[2]] * log1p(s1$api_mm[g]))
  }
  attr(s1, "moisture_fit") <- fits
  s1
}

#' Consecutive unfrozen acquisitions, orbits merged, with the change.
#' The operation, if any, happened between date_a and date.
s1_intervals <- function(ctx) {
  m <- ctx[!ctx$frozen & !is.na(ctx$vv_adj), ]
  m <- m[order(m$date, m$orbit), ]        # date, then orbit -- same as sar.py
  n <- nrow(m)
  if (n < 2) return(m[0, ])
  m$date_a    <- c(as.Date(NA), m$date[-n])
  m$d_vv_adj  <- c(NA, diff(m$vv_adj))
  m$d_vh      <- c(NA, diff(m$vh_c))
  m$bare_both <- m$bare & c(FALSE, m$bare[-n])
  out <- m[-1, ]
  # Two orbits can pass on the same day (Akron sits under four). A same-day
  # "interval" is the residual between two orbits, not a change on the ground.
  out <- out[out$date > out$date_a, ]
  rownames(out) <- NULL
  out
}

.phen_col <- function(p, name, fallback) if (name %in% names(p)) p[[name]] else p[[fallback]]

#' Radar-bracketed planting and harvest candidates, one row per event.
#'
#' Planting: the largest drop in moisture-adjusted VV while bare. Harvest: the
#' largest drop in VH. in_ndvi_window is a consistency check, not validation.
s1_events <- function(ctx, phen) {
  iv <- s1_intervals(ctx)
  rows <- list()
  for (i in seq_len(nrow(phen))) {
    p <- phen[i, ]; y <- p$year
    specs <- list()
    if (!is.na(p$planting_lo)) {
      lo <- .plant_from(p, y); hi <- p$planting_hi + SAR_PLANT_AFTER_D
      specs[[length(specs) + 1]] <- list(event = "planting", col = "d_vv_adj",
        w = iv[iv$date_a >= lo & iv$date <= hi & iv$bare_both, ],
        nlo = p$planting_lo, nhi = p$planting_hi, nest = .phen_col(p, "planting_date", "planting_est"))
    }
    if (!is.na(p$harvest_lo)) {
      lo <- p$harvest_lo - SAR_HARVEST_BEFORE_D; hi <- p$harvest_hi + SAR_HARVEST_AFTER_D
      specs[[length(specs) + 1]] <- list(event = "harvest", col = "d_vh",
        w = iv[iv$date_a >= lo & iv$date <= hi, ],
        nlo = p$harvest_lo, nhi = p$harvest_hi, nest = .phen_col(p, "harvest_date", "harvest_est"))
    }
    for (sp in specs) {
      w <- sp$w[!is.na(sp$w[[sp$col]]) & sp$w[[sp$col]] < 0, ]
      row <- data.frame(year = y, crop = p$crop, event = sp$event,
                        ndvi_lo = sp$nlo, ndvi_date = as.Date(sp$nest), ndvi_hi = sp$nhi,
                        s1_from = as.Date(NA), s1_to = as.Date(NA), signal = sp$col,
                        step_db = NA_real_, n_intervals = nrow(w), in_ndvi_window = NA,
                        stringsAsFactors = FALSE)
      if (nrow(w)) {
        e <- w[which.min(w[[sp$col]]), ]
        row$s1_from <- e$date_a; row$s1_to <- e$date
        row$step_db <- round(e[[sp$col]], 2)
        row$in_ndvi_window <- e$date >= sp$nlo && e$date_a <= sp$nhi
      }
      rows[[length(rows) + 1]] <- row
    }
  }
  if (!length(rows)) return(data.frame())
  do.call(rbind, rows)
}

#' Per local day: could equipment have been in the field? The same rules as
#' the rain check in climate.R, plus not frozen. Named logical, by date.
#'
#' @param rules The rain check's settings as a list (dry_mm, wind_max_kmh,
#'   heavy_mm, wet_days), as apply_rain_check() takes them. Anything left out is
#'   the climate.R default; wind is only checked when given.
workable_days <- function(weather, rules = NULL) {
  r <- utils::modifyList(list(dry_mm = DRY_PR_MM, wind_max_kmh = NULL,
                              heavy_mm = HEAVY_RAIN_MM, wet_days = HEAVY_RAIN_WET_DAYS),
                         rules %||% list())
  days <- seq(min(weather$date), max(weather$date), by = 1)
  w <- weather[match(days, weather$date), ]
  pr <- w$pr_mm
  ok <- ifelse(is.na(pr), 0, pr) <= r$dry_mm
  if (!is.null(r$wind_max_kmh) && "wind_kmh" %in% names(w))
    ok <- ok & !(!is.na(w$wind_kmh) & w$wind_kmh >= r$wind_max_kmh)
  if (!is.null(r$heavy_mm)) {
    for (k in seq_len(r$wet_days)) {
      prev <- c(rep(NA, k), utils::head(pr, -k))
      ok <- ok & !(!is.na(prev) & prev >= r$heavy_mm)
    }
  }
  if (all(c("tmmx_degc", "tmmn_degc") %in% names(w))) {
    tm <- (w$tmmx_degc + w$tmmn_degc) / 2
    ok <- ok & !is.na(tm) & tm > SAR_FROZEN_C
  }
  stats::setNames(ok, format(days))
}

.robust_sd <- function(x) {
  x <- x[!is.na(x)]
  if (length(x) >= 10) 1.4826 * stats::median(abs(x - stats::median(x))) else NA_real_
}

.work_on <- function(work, days) {
  v <- work[format(days)]; !is.na(v) & v
}

# --------------------------------------------------------- soil wetness ---
#
# Port of python/fieldrs/sar.py soil_wetness() / moisture_days(). Soil moisture,
# not the day's rain, decides whether a field can be worked, so planting and
# harvest days are chosen on a daily wetness estimate first and on the day's
# weather second. Wetness is log(1 + API), corrected on bare unfrozen
# acquisitions by r^2 of the VV residual over the fit's slope; the correction
# fades at the API's daily decay until the next acquisition.

#' A day is dry enough at or below this quantile of the field's own
#' April-November unfrozen days. A first cut, not fitted.
SAR_DRY_Q <- 0.5
SAR_DRY_MONTHS <- 4:11

#' Daily soil wetness for the field, from gridMET rain and Sentinel-1 VV.
#' Columns date, pr_mm, wind_kmh (when present), api_mm, wet_rain, wet_radar,
#' wet, anchored, frozen, dry; the threshold in attr(, "wet_threshold").
soil_wetness <- function(ctx, weather) {
  days <- seq(min(weather$date), max(weather$date), by = 1)
  w <- weather[match(days, weather$date), ]
  pr0 <- w$pr_mm; pr0[is.na(pr0)] <- 0
  k <- SAR_API_DECAY
  api <- numeric(length(pr0)); api[1] <- pr0[1]
  for (t in seq_along(pr0)[-1]) api[t] <- k * api[t - 1] + (1 - k) * pr0[t]
  api <- api / (1 - k)
  tm <- (w$tmmx_degc + w$tmmn_degc) / 2
  tmean3 <- as.numeric(stats::filter(tm, rep(1 / 3, 3), sides = 1))
  out <- data.frame(date = days, pr_mm = w$pr_mm)
  if ("wind_kmh" %in% names(w)) out$wind_kmh <- w$wind_kmh
  out$api_mm <- api
  out$wet_rain <- log1p(api)
  out$frozen <- !is.na(tmean3) & tmean3 <= SAR_FROZEN_C

  fits <- attr(ctx, "moisture_fit")
  gain <- unlist(lapply(fits, function(f) if (f$slope > 0) f$r^2 / f$slope else NULL))
  a <- ctx[ctx$bare & !ctx$frozen & as.character(ctx$orbit) %in% names(gain) &
             !is.na(ctx$vv_adj), ]
  anchor <- if (nrow(a)) tapply(a$vv_adj * gain[as.character(a$orbit)],
                                format(a$date - 1), mean) else numeric(0)
  corr <- numeric(length(days)); cc <- 0
  key <- format(days)
  for (i in seq_along(days)) {
    cc <- if (key[i] %in% names(anchor)) anchor[[key[i]]] else cc * k
    corr[i] <- cc
  }
  out$wet_radar <- corr
  out$wet <- out$wet_rain + out$wet_radar
  out$anchored <- key %in% names(anchor)
  season <- out$wet[as.integer(format(days, "%m")) %in% SAR_DRY_MONTHS & !out$frozen]
  thr <- if (length(season)) unname(stats::quantile(season, SAR_DRY_Q)) else NA_real_
  out$dry <- !is.na(thr) & out$wet <= thr & !out$frozen
  attr(out, "wet_threshold") <- round(thr, 3)
  out
}

#' Per local day: dry enough soil, then weather fit for `event`. Planting
#' tolerates light rain (only heavy_mm or more is ruled out); harvest needs a
#' rain-free day (at most dry_mm). Wind only when wind_max_kmh is given. Named
#' logical, by date, like workable_days().
moisture_days <- function(wet, event, rules = NULL) {
  r <- utils::modifyList(list(dry_mm = DRY_PR_MM, wind_max_kmh = NULL,
                              heavy_mm = HEAVY_RAIN_MM), rules %||% list())
  pr <- wet$pr_mm; pr[is.na(pr)] <- 0
  ok <- wet$dry
  if (event == "planting") {
    if (!is.null(r$heavy_mm)) ok <- ok & pr < r$heavy_mm
  } else {
    ok <- ok & pr <= r$dry_mm
  }
  if (!is.null(r$wind_max_kmh) && "wind_kmh" %in% names(wet))
    ok <- ok & !(!is.na(wet$wind_kmh) & wet$wind_kmh >= r$wind_max_kmh)
  stats::setNames(ok, format(wet$date))
}

#' Narrow each NDVI planting and harvest window with radar, soil moisture and
#' weather.
#'
#' Inside each window the strongest radar drop is scored as z over the field's
#' robust interval-to-interval SD. Days are chosen on soil moisture first
#' (soil_wetness(), moisture_days()): from that interval when z >=
#' SAR_SUPPORT_Z ("radar + moisture"), else from the whole window
#' ("moisture"). Where no day is dry enough the rain check's workable days are
#' used ("radar + weather" / "weather only"), then the window ("NDVI only").
#' moist_days counts window days that passed the moisture test.
#' conflict: a step more than SAR_CONFLICT_DZ stronger sits in
#' the wider search span outside the window. Read span_days, not
#' candidate_days, as how far the date is pinned down. `rules` are the weather
#' settings of the rain check (see workable_days()). When `phen` carries the
#' rain check's final dates, weather_date reports them and
#' weather_date_in_window whether they fall in the narrowed window.
s1_refine <- function(ctx, phen, weather, rules = NULL) {
  iv <- s1_intervals(ctx)
  work <- workable_days(weather, rules)
  wet <- soil_wetness(ctx, weather)
  moist <- list(planting = moisture_days(wet, "planting", rules),
                harvest = moisture_days(wet, "harvest", rules))
  sd <- list(d_vv_adj = .robust_sd(iv$d_vv_adj[iv$bare_both]), d_vh = .robust_sd(iv$d_vh))
  rows <- list()
  for (i in seq_len(nrow(phen))) {
    p <- phen[i, ]; y <- p$year
    for (event in c("planting", "harvest")) {
      lo <- p[[paste0(event, "_lo")]]; hi <- p[[paste0(event, "_hi")]]
      if (is.na(lo) || is.na(hi)) next
      col <- if (event == "planting") "d_vv_adj" else "d_vh"
      pool <- if (event == "planting") iv[iv$bare_both, ] else iv
      span <- if (event == "planting")
        c(.plant_from(p, y), hi + SAR_PLANT_AFTER_D)
      else c(lo - SAR_HARVEST_BEFORE_D, hi + SAR_HARVEST_AFTER_D)
      first <- pool$date_a; last <- pool$date - 1
      neg <- !is.na(pool[[col]]) & pool[[col]] < 0
      in_i <- which(last >= lo & first <= hi & neg)
      wide_i <- setdiff(which(first >= span[1] & last <= span[2] & neg), in_i)

      win_days <- seq(lo, hi, by = 1)
      mok <- moist[[event]]
      win_work <- win_days[.work_on(work, win_days)]
      win_moist <- win_days[.work_on(mok, win_days)]
      row <- list(year = y, crop = p$crop, event = event, ndvi_lo = lo, ndvi_hi = hi,
                  ndvi_days = length(win_days), workable_days = length(win_work),
                  moist_days = length(win_moist),
                  s1_from = as.Date(NA), s1_to = as.Date(NA), step_db = NA_real_,
                  z = NA_real_, basis = NA_character_, refined_lo = as.Date(NA),
                  refined_hi = as.Date(NA), span_days = NA_integer_,
                  candidate_days = NA_integer_, conflict = FALSE,
                  conflict_from = as.Date(NA), conflict_to = as.Date(NA),
                  note = NA_character_)
      take <- function(row, d, basis) {
        row$basis <- basis; row$refined_lo <- min(d); row$refined_hi <- max(d)
        row$candidate_days <- length(d); row
      }
      best_z <- NA_real_; picked <- as.Date(character(0))
      ok_sd <- !is.na(sd[[col]]) && sd[[col]] > 0
      if (length(in_i) && ok_sd) {
        e <- pool[in_i[which.min(pool[[col]][in_i])], ]
        best_z <- -e[[col]] / sd[[col]]
        row$s1_from <- e$date_a; row$s1_to <- e$date
        row$step_db <- round(e[[col]], 2); row$z <- round(best_z, 2)
        if (best_z >= SAR_SUPPORT_Z) {
          step <- seq(max(lo, e$date_a), min(hi, e$date - 1), by = 1)
          d_m <- step[.work_on(mok, step)]; d_w <- step[.work_on(work, step)]
          if (length(d_m)) {
            row <- take(row, d_m, "radar + moisture"); picked <- d_m
          } else if (length(d_w)) {
            row <- take(row, d_w, "radar + weather"); picked <- d_w
            row$note <- "no dry-enough day in the radar interval"
          } else {
            row$note <- "radar step stands out but its interval has no workable day inside the window"
          }
        }
      }
      if (is.na(row$basis) && length(win_moist)) {
        row <- take(row, win_moist, "moisture"); picked <- win_moist
      } else if (is.na(row$basis) && length(win_work)) {
        row <- take(row, win_work, "weather only"); picked <- win_work
        if (is.na(row$note)) row$note <- "no dry-enough day in window"
      }
      if (is.na(row$basis)) {
        row$refined_lo <- lo; row$refined_hi <- hi; row$candidate_days <- length(win_days)
        row$basis <- "NDVI only"
        if (is.na(row$note)) row$note <- "no workable day in window"
      }
      row$span_days <- as.integer(row$refined_hi - row$refined_lo) + 1L
      # One date to set beside the weather-checked one: the candidate day
      # nearest the NDVI estimate, the earlier on a tie. "NDVI only" keeps the
      # estimate. Same rule as sar.py.
      est <- as.Date(p[[paste0(event, "_est")]])
      row$ndvi_est <- est
      row$moist_date <- if (length(picked) && !is.na(est))
        picked[order(abs(as.integer(picked - est)), picked)][1] else est
      row$moist_shift_d <- if (is.na(row$moist_date) || is.na(est)) NA_integer_
                           else as.integer(row$moist_date - est)
      wd <- if (paste0(event, "_date") %in% names(p)) as.Date(p[[paste0(event, "_date")]])
            else as.Date(NA)
      row$weather_date <- wd
      row$weather_date_in_window <- if (is.na(wd)) NA
                                    else wd >= row$refined_lo && wd <= row$refined_hi
      if (length(wide_i) && ok_sd) {
        out_z <- -min(pool[[col]][wide_i]) / sd[[col]]
        if (out_z >= SAR_SUPPORT_Z && (is.na(best_z) || out_z - best_z > SAR_CONFLICT_DZ)) {
          o <- pool[wide_i[which.min(pool[[col]][wide_i])], ]
          row$conflict <- TRUE
          row$conflict_from <- o$date_a; row$conflict_to <- o$date
          msg <- sprintf("stronger step outside window: %s to %s, z %.1f",
                         format(o$date_a, "%m-%d"), format(o$date, "%m-%d"), out_z)
          row$note <- if (is.na(row$note)) msg else paste0(row$note, "; ", msg)
        }
      }
      rows[[length(rows) + 1]] <- as.data.frame(row, stringsAsFactors = FALSE)
    }
  }
  out <- if (length(rows)) do.call(rbind, rows) else data.frame()
  attr(out, "noise_sd_db") <- lapply(sd, function(v) round(v, 2))
  attr(out, "wet_threshold") <- attr(wet, "wet_threshold")
  out
}

# --------------------------------------------------------------- one call ---

#' Everything the radar view needs for one field.
#'
#' @param ts   The field's optical series (extract_field_series()), for NDVI.
#' @param phen The field's phenology table: the radar is read against its
#'             planting and harvest windows.
#' @return list(s1, ctx, weather, ndvi, events, refined, cuts, orbits), or NULL
#'   when only_cached and nothing is cached, or no acquisitions cover the field.
#'   Weather comes from gridMET, so a field outside CONUS stops with an error.
s1_analysis <- function(aoi, start, end, ts, phen, only_cached = FALSE, workers = 8,
                        rules = NULL) {
  s1 <- s1_series(aoi, start, end, workers = workers, only_cached = only_cached)
  if (is.null(s1) || !nrow(s1)) return(NULL)
  ndvi <- if (is.null(ts)) NULL else {
    d <- ts[ts$index == "ndvi", c("date", "mean")]; d[order(d$date), ]
  }
  weather <- gridmet_daily(aoi, start, end, outputs = SAR_GRIDMET)
  ctx <- s1_context(s1, weather, ndvi)
  has_phen <- !is.null(phen) && nrow(phen)
  events  <- if (has_phen) s1_events(ctx, phen) else data.frame()
  refined <- if (has_phen) s1_refine(ctx, phen, weather, rules) else data.frame()
  cuts <- forage_cuts(ndvi, phen, ctx, weather, rules)
  list(s1 = s1, ctx = ctx, weather = weather, ndvi = ndvi,
       wetness = soil_wetness(ctx, weather), events = events,
       refined = refined, cuts = cuts, orbits = sort(unique(s1$orbit)))
}

# ------------------------------------------------------------------ plot ---

S1_EVENT_COLOUR <- c(planting = "#2c7fb8", harvest = "#d95f0e")   # as plot_phenology()

#' Sentinel-1 backscatter against NDVI phenology, one panel per year.
#'
#' Port of python/fieldrs/viz.py plot_s1(). Moisture-adjusted VV and
#' orbit-centred VH (dB) on the left axis with NDVI scaled onto it (x 10 - 6),
#' daily rain on the right. Shading: NDVI planting (blue) and harvest (orange)
#' windows in plot_phenology()'s colours, with its dashed NDVI estimate and
#' solid weather-checked date; hay cut brackets (purple) and drops to bare soil
#' (grey). Bars along
#' the top: the radar interval used to narrow an NDVI window (hollow: a stronger step outside the window). Bars
#' along the bottom: windows and cuts narrowed by radar and weather.
plot_s1 <- function(res, phen = NULL, title = NULL, cover = NULL) {
  ctx <- res$ctx; w <- res$weather; nd <- res$ndvi
  ev <- res$events; ref <- res$refined; cuts <- res$cuts
  years <- sort(unique(as.integer(format(ctx$date, "%Y"))))
  op <- graphics::par(mfrow = c(length(years), 1), mar = c(2.2, 3.4, 1.8, 3.4),
                      oma = c(0, 0, if (is.null(title)) 3.2 else 4.6, 0))
  on.exit(graphics::par(op), add = TRUE)
  span <- function(a, b, col, y0 = -7, y1 = 7)
    graphics::rect(a, y0, b, y1, col = col, border = NA)
  for (y in years) {
    from <- as.Date(sprintf("%d-01-01", y)); to <- as.Date(sprintf("%d-12-31", y))
    graphics::plot(c(from, to), c(-7, 7), type = "n", xaxt = "n", xlab = "",
                   ylab = "dB", cex.axis = 0.8)
    graphics::axis.Date(1, at = seq(from, to, by = "month"), format = "%b", cex.axis = 0.75)
    p <- if (is.null(phen)) NULL else phen[phen$year == y, ]
    crop <- if (!is.null(p) && nrow(p) && !is.na(p$crop[1]) && nzchar(p$crop[1])) p$crop[1]
            else "crop not yet in CDL"
    lab <- sprintf("%d · %s", y, crop)
    # Every season's windows and intervals in every panel, clipped by the plot
    # region: a winter crop's sowing (autumn before its harvest year) belongs to
    # next year's season but falls in this year's panel.
    # Same windows, colours and date lines as plot_phenology(), so the two tabs
    # read alike: dashed is the NDVI estimate, solid the weather-checked date
    # when the rain check is on.
    if (!is.null(phen) && nrow(phen)) {
      for (i in seq_len(nrow(phen))) {
        for (what in c("planting", "harvest")) {
          lo <- phen[[paste0(what, "_lo")]][i]
          if (is.na(lo)) next
          colour <- S1_EVENT_COLOUR[[what]]
          span(lo, phen[[paste0(what, "_hi")]][i], grDevices::adjustcolor(colour, 0.13))
          est <- phen[[paste0(what, "_est")]][i]
          fin <- if (paste0(what, "_date") %in% names(phen)) phen[[paste0(what, "_date")]][i] else NA
          if (!is.na(est))
            graphics::abline(v = est, col = colour, lty = 2, lwd = if (is.na(fin)) 1.6 else 1.2)
          if (!is.na(fin)) graphics::abline(v = fin, col = colour, lwd = 2.2)
        }
      }
    }
    if (!is.null(cuts) && nrow(cuts)) {
      cy <- cuts[cuts$year == y, ]
      for (i in seq_len(nrow(cy))) {
        bare <- cy$kind[i] == "to bare soil"
        span(cy$ndvi_from[i], cy$ndvi_to[i],
             grDevices::adjustcolor(if (bare) "grey50" else "purple", 0.12))
        span(cy$refined_lo[i], cy$refined_hi[i] + 1, if (bare) "grey40" else "purple",
             -7, -6.1)
      }
      n_cut <- sum(cy$kind == "cut")
      if (n_cut) lab <- sprintf("%s · %d cut%s", lab, n_cut, if (n_cut != 1) "s" else "")
    }
    # Top band: only the radar interval that actually narrowed a window, so it
    # always overlaps its NDVI window; a stronger step outside the window
    # (refined$conflict) is drawn hollow. The wider search in res$events feeds
    # the agreement metrics, not the chart.
    if (!is.null(ref) && nrow(ref)) {
      ru <- ref[startsWith(ref$basis, "radar"), ]    # all seasons; plot clips
      for (i in seq_len(nrow(ru)))
        span(ru$s1_from[i], ru$s1_to[i], S1_EVENT_COLOUR[[ru$event[i]]], 6.1, 7)
      rc <- ref[ref$conflict, ]
      for (i in seq_len(nrow(rc)))
        graphics::rect(rc$conflict_from[i], 6.1, rc$conflict_to[i], 7, col = NA,
                       border = S1_EVENT_COLOUR[[rc$event[i]]], lty = 2, lwd = 1.2)
    }
    wet <- res$wetness
    if (!is.null(wet) && nrow(wet)) {
      # Runs of dry-enough days (soil_wetness()) as a tan strip just above the
      # narrowed-window bars.
      wy <- wet[as.integer(format(wet$date, "%Y")) == y, ]
      rl <- rle(wy$dry); ends <- cumsum(rl$lengths); starts <- ends - rl$lengths + 1
      for (j in which(rl$values))
        span(wy$date[starts[j]], wy$date[ends[j]] + 1, "#c9a66b", -6.1, -5.6)
    }
    if (!is.null(ref) && nrow(ref)) {
      ry <- ref[startsWith(ref$basis, "radar"), ]     # all seasons; plot clips
      for (i in seq_len(nrow(ry))) span(ry$refined_lo[i], ry$refined_hi[i] + 1, "black", -7, -6.1)
    }
    graphics::abline(h = 0, col = "grey70", lwd = 0.5)
    g <- ctx[as.integer(format(ctx$date, "%Y")) == y, ]; g <- g[order(g$date), ]
    ok <- g[!g$frozen, ]
    graphics::lines(ok$date, ok$vh_c, col = grDevices::adjustcolor("forestgreen", 0.7), lwd = 0.9)
    graphics::lines(ok$date, ok$vv_adj, col = "#1f77b4", lwd = 0.9, type = "o", pch = 16, cex = 0.45)
    fz <- g[g$frozen, ]
    graphics::points(fz$date, fz$vv_adj, pch = 4, col = "grey50", cex = 0.7)
    if (!is.null(nd)) {
      n <- nd[as.integer(format(nd$date, "%Y")) == y, ]
      graphics::lines(n$date, n$mean * 10 - 6, col = "darkgreen", lwd = 1.6)
    }
    draw_seeding(phen, cover, from, to, windows = TRUE)
    if (!is.null(p) && nrow(p) && "stand" %in% names(p) && identical(p$stand[1], "established"))
      lab <- paste(lab, "\u00b7 established stand")
    graphics::mtext(lab, side = 3, adj = 0, line = 0.3, cex = 0.75)
    if (!is.null(w) && "pr_mm" %in% names(w)) {
      wy <- w[as.integer(format(w$date, "%Y")) == y, ]
      graphics::par(new = TRUE)
      graphics::plot(wy$date, wy$pr_mm, type = "h", col = grDevices::adjustcolor("#17becf", 0.4),
                     xlim = c(from, to), ylim = c(0, 90), axes = FALSE, xlab = "", ylab = "")
      graphics::axis(4, cex.axis = 0.7)
      graphics::mtext("rain mm", side = 4, line = 2.2, cex = 0.6)
    }
  }
  graphics::par(fig = c(0, 1, 0, 1), oma = c(0, 0, 0, 0), mar = c(0, 0, 0, 0), new = TRUE)
  graphics::plot(0, 0, type = "n", bty = "n", xaxt = "n", yaxt = "n")
  # The title takes the top ~0.3 inch; the legend sits under it.
  inset <- if (is.null(title)) 0.02 else 0.32 / graphics::par("din")[2]
  graphics::legend("top", inset = c(0, inset), ncol = 4, bty = "n", cex = 0.75,
    legend = c("VV, moisture-adjusted (dB)", "VH, orbit-centred (dB)", "NDVI × 10 − 6",
               "frozen (dropped)", "NDVI planting window", "NDVI harvest window",
               "NDVI estimate (dashed)", "weather-checked date (solid)",
               "radar interval used (top)", "stronger radar step outside window", "soil dry enough (radar + rain)",
               "narrowed: radar + moisture (bottom)", "hay cut (purple)",
               "stand seeding (green)", "cover crop seeding / termination (dotted)"),
    col = c("#1f77b4", "forestgreen", "darkgreen", "grey50",
            grDevices::adjustcolor(S1_EVENT_COLOUR[["planting"]], 0.3),
            grDevices::adjustcolor(S1_EVENT_COLOUR[["harvest"]], 0.3), "grey30", "grey30",
            S1_EVENT_COLOUR[["harvest"]], "grey30", "#c9a66b", "black", "purple",
            STAND_COLOUR, COVER_SEED_COLOUR),
    lwd = c(1, 1, 1.6, NA, NA, NA, 1.2, 2.2, NA, 1.2, NA, NA, NA, 1.6, 1.8),
    lty = c(1, 1, 1, NA, NA, NA, 2, 1, NA, 2, NA, NA, NA, 2, 3),
    pch = c(16, NA, NA, 4, 15, 15, NA, NA, 15, NA, 15, 15, 15, NA, NA),
    pt.cex = c(0.6, NA, NA, 0.8, 1.6, 1.6, NA, NA, 1.4, NA, 1.4, 1.4, 1.4, NA, NA))
  if (!is.null(title)) graphics::mtext(title, side = 3, line = -1.1, cex = 0.9, font = 2)
  invisible()
}
