# ==============================================================================
# extract.R -- Multi-year field statistics, in parallel
#
# The season-at-a-time loop in timeseries.R is fine for one year. Phenology and
# cover crop detection need several years of year-round observations, which is
# several hundred HTTP reads -- about 2.3 s each, so ~20 minutes sequentially.
#
# Each read is network-bound rather than CPU-bound, so running them across
# processes is close to linear: 8 workers turns that into a few minutes. The
# result is cached, so any given field pays the cost once.
# ==============================================================================

#' Year-round index statistics for a field over several years.
#'
#' @param aoi       sf field boundary.
#' @param start,end "YYYY-MM-DD". Defaults cover 2020 to today.
#' @param indices   Registered index names.
#' @param max_cloud Scene-level cloud cutoff. Kept loose on purpose -- winter
#'                  scenes are often flagged cloudy over the tile while the
#'                  field itself is clear, and the off-season observations are
#'                  exactly what cover crop detection needs.
#' @param min_valid Minimum fraction of clear field pixels to keep a scene.
#' @param workers   Parallel processes. 1 forces sequential.
#' @param progress  Optional function(done, total, msg) for a Shiny progress bar.
#' @return Long data frame: one row per scene per index.
extract_field_series <- function(aoi,
                                 start   = "2020-01-01",
                                 end     = as.character(Sys.Date()),
                                 indices = "ndvi",
                                 max_cloud = 70,
                                 min_valid = 0.75,
                                 workers   = 8,
                                 refresh   = FALSE,
                                 only_cached = FALSE,
                                 progress  = NULL) {

  key <- cache_key(aoi, start, end, indices, max_cloud, min_valid, "field_series_v3")
  hit <- if (refresh) NULL else cache_get(key, "series")
  if (!is.null(hit)) {
    if (!is.null(progress)) progress(1, 1, "Loaded from cache")
    message(sprintf("  Cached: %d observations.", nrow(hit)))
    return(hit)
  }
  # Used by the app to open a pre-warmed field instantly: a miss returns NULL
  # rather than silently starting several hundred scene reads.
  if (only_cached) return(NULL)

  bands  <- bands_for(indices)
  scenes <- search_scenes(aoi, start, end, max_cloud = max_cloud, limit = 5000)
  groups <- scene_groups(scenes)    # ranked candidates per date, chosen up front
  signed <- sign_scenes(scenes)
  n      <- length(groups)

  # Index functions are re-homed in baseenv() before being shipped to workers.
  # They only do arithmetic on the band list, so they need nothing from the
  # global environment -- and this keeps the serialised payload tiny.
  specs <- lapply(indices, function(nm) {
    s <- get(nm, INDICES)
    f <- s$fn
    # An index defined at the top level closes over the global environment,
    # which would be serialised whole to every worker -- re-home those. An
    # index deliberately given its own small environment keeps it: armor.R's
    # unmixing carries a precomputed endmember inverse that the worker needs
    # and cannot look up, and blanking it was silently turning every scene
    # into a "failed to read".
    if (identical(environment(f), globalenv())) environment(f) <- baseenv()
    list(name = nm, fn = f, bands = s$bands)
  })

  root <- normalizePath(".", winslash = "/")
  jobs <- lapply(groups, function(idx) list(
    items = signed$features[idx],
    date  = scenes$table$date[idx[1]],
    ids   = scenes$table$id[idx],
    cloud = scenes$table$cloud[idx]
  ))

  use_parallel <- ensure_workers(workers)

  message(sprintf("  Extracting %d dates%s...", n,
                  if (use_parallel) sprintf(" across %d workers", workers) else " sequentially"))

  # Chunked so the Shiny progress bar advances without needing progressr.
  chunk_size <- if (use_parallel) workers * 2L else 1L
  chunks <- split(seq_len(n), ceiling(seq_len(n) / chunk_size))
  results <- vector("list", length(chunks))

  for (k in seq_along(chunks)) {
    idx <- chunks[[k]]

    # Planetary Computer signatures last about an hour. A long run would
    # otherwise start failing partway through, and because a failed read is
    # caught per scene it would look like cloud rather than an error.
    if (as.numeric(difftime(Sys.time(), scenes$cache$signed_at, units = "mins")) > 25) {
      signed <- sign_scenes_force(scenes)
      for (j in seq_along(groups)) jobs[[j]]$items <- signed$features[groups[[j]]]
    }

    results[[k]] <- if (use_parallel) {
      furrr::future_map(jobs[idx], extract_one_scene,
                        aoi = aoi, specs = specs, min_valid = min_valid, root = root,
                        .options = furrr::furrr_options(seed = TRUE))
    } else {
      lapply(jobs[idx], extract_one_scene,
             aoi = aoi, specs = specs, min_valid = min_valid, root = root)
    }
    if (!is.null(progress)) {
      done <- max(idx)
      progress(done, n, sprintf("Reading imagery: scene %d of %d", done, n))
    }
  }

  outcomes <- unlist(results, recursive = FALSE)
  status   <- vapply(outcomes, function(o) o$status, character(1))
  rows     <- lapply(outcomes[status == "ok"], `[[`, "rows")

  n_err <- sum(status == "error")
  if (n_err > 0) {
    first_msg <- outcomes[status == "error"][[1]]$msg
    warning(sprintf("%d of %d scenes failed to read and were dropped. First error: %s",
                    n_err, n, first_msg), call. = FALSE)
  }

  if (!length(rows)) {
    stop("No scenes passed the quality filter between ", start, " and ", end,
         ".\n  ", sum(status == "cloudy"), " were too cloudy over the field and ",
         n_err, " failed to read.",
         "\n  Try raising max_cloud or lowering min_valid.", call. = FALSE)
  }

  out <- do.call(rbind, rows)

  # One date can yield several scenes: neighbouring Sentinel-2 tiles overlap,
  # and a field near a tile seam appears in both. Left alone these become
  # duplicate x values in the phenology spline and double-weight those dates.
  # Keep the scene that saw the most of the field, breaking ties on cloud.
  n_raw <- nrow(out)
  out <- out[order(out$index, out$date, -out$valid_frac, out$cloud), ]
  out <- out[!duplicated(out[, c("index", "date")]), ]
  n_dup <- n_raw - nrow(out)

  rownames(out) <- NULL
  out$year <- as.integer(format(out$date, "%Y"))
  out$doy  <- as.integer(format(out$date, "%j"))

  message(sprintf("  Kept %d of %d dates (%d observations%s).",
                  length(unique(out$date)), n, nrow(out),
                  if (n_dup) sprintf(", %d same-date duplicates dropped", n_dup) else ""))

  cache_put(key, out, "series")
  out
}

#' Worker: one scene -> one row per index.
#'
#' Runs in a separate R process, so it re-sources the imagery code rather than
#' relying on anything being present in the worker's environment.
#'
#' Returns a status rather than just NULL, because "the field was under cloud"
#' and "the read failed" need to be told apart -- silently treating a network
#' failure as cloud would quietly thin the series with no sign anything was
#' wrong.
extract_one_scene <- function(job, aoi, specs, min_valid, root) {
  suppressPackageStartupMessages({
    library(sf); library(terra)
  })
  if (!exists("scene_from_item", mode = "function")) {
    source(file.path(root, "R", "imagery.R"))
  }

  bands    <- unique(unlist(lapply(specs, `[[`, "bands")))
  last_err <- NULL

  # Walk this date's candidate scenes in preference order. Metadata cannot tell
  # you whether a tile actually holds pixels over the field -- a STAC footprint
  # is the whole 110 km tile, but a granule can be only partly filled. Taking
  # the first candidate and stopping silently lost 19 dates on a field sitting
  # where four tiles overlap. Usually the first one works, so this costs nothing.
  for (k in seq_along(job$items)) {
    res <- tryCatch({
      img <- scene_from_item(job$items[[k]], aoi, bands = bands,
                             mask_clouds = TRUE, clip = TRUE)

      n_field <- attr(img, "n_field")
      vals    <- terra::values(img[[1]])
      vf      <- if (is.null(n_field) || n_field == 0) 0 else
                   min(1, sum(!is.na(vals)) / n_field)

      # NOTE: no return() here. Inside a tryCatch expression, return() exits
      # the enclosing function, not the tryCatch -- which made the worker hand
      # back a bare NULL with no $status and broke the caller's vapply.
      if (vf < min_valid) {
        NULL                              # fall through to the next candidate
      } else {

      parts <- lapply(specs, function(sp) {
        b <- stats::setNames(lapply(sp$bands, function(nm) img[[nm]]), sp$bands)
        v <- terra::values(sp$fn(b))
        v <- v[!is.na(v) & is.finite(v)]
        if (!length(v)) return(NULL)
        data.frame(
          date       = job$date,
          index      = sp$name,
          mean       = mean(v),
          median     = stats::median(v),
          sd         = stats::sd(v),
          p10        = unname(stats::quantile(v, 0.10)),
          p90        = unname(stats::quantile(v, 0.90)),
          n_pixels   = length(v),
          valid_frac = vf,
          cloud      = job$cloud[k],
          scene_id   = job$ids[k],
          stringsAsFactors = FALSE
        )
      })
      parts <- Filter(Negate(is.null), parts)
      if (!length(parts)) NULL else do.call(rbind, parts)
      }
    }, error = function(e) {
      last_err <<- conditionMessage(e)
      NULL
    })
    if (!is.null(res)) return(list(status = "ok", rows = res))
  }

  if (is.null(last_err)) list(status = "cloudy", rows = NULL)
  else list(status = "error", rows = NULL, msg = last_err)
}

#' Daily-interpolated index series, which the phenology and cover crop code
#' both build on.
#'
#' Satellite observations are irregular -- cloud decides when you get one. A
#' smooth daily curve makes threshold crossings well defined, at the cost of
#' inventing detail between observations. Gaps longer than `max_gap` days are
#' left as NA rather than bridged, so a two-month winter hole never turns into
#' a confident-looking line.
daily_series <- function(ts, index = "ndvi", spar = 0.35, max_gap = 45) {
  d <- ts[ts$index == index, ]
  d <- d[order(d$date), ]
  if (nrow(d) < 8) {
    stop("Only ", nrow(d), " observations for '", index,
         "'; need at least 8 to smooth.", call. = FALSE)
  }

  x <- as.numeric(d$date)
  grid <- seq(min(x), max(x), by = 1)

  fit <- stats::smooth.spline(x, d$mean, spar = spar)
  y   <- stats::predict(fit, grid)$y

  # Blank out stretches with no supporting observation.
  gap <- vapply(grid, function(g) min(abs(g - x)), numeric(1))
  y[gap > max_gap / 2] <- NA_real_

  data.frame(
    date     = as.Date(grid, origin = "1970-01-01"),
    value    = y,
    observed = grid %in% x,
    row.names = NULL
  )
}
