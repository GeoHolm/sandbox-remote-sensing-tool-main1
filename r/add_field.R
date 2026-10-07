# ==============================================================================
# add_field.R -- Put a boundary into the demo library, end to end.
#
# From the R console (RStudio), which is where most of this work happens:
#
#   source("r/add_field.R")
#   add_field("validation/boundaries/40464_2020.geojson",
#             stem  = "mitchell-ga",
#             label = "Georgia - Mitchell Co.",
#             shows = "conservation till with a cover crop")
#   library_status()
#
# Or from a shell -- the Terminal tab, not the Console:
#
#   Rscript r/add_field.R <boundary> --label "Georgia - Tift Co." \
#                                    --shows "conservation till, cover cropped"
#   Rscript r/add_field.R --status
#
# Copies the boundary in, records it in data/fields/library.csv, warms every
# cache the app reads, cuts its CDL clips, and prints what to commit.
#
# WHY THIS EXISTS
# Adding a field used to mean editing app.R to add a label, then running two
# more scripts that each re-walked the whole library. Five steps, one of them in
# application code, is enough friction to stop a habit forming -- and the point
# of the library is that it keeps growing as real fields get run.
#
# Everything is cached per field, so re-running on an existing field is cheap
# and safe. Nothing is overwritten unless you ask.
# ==============================================================================

# Remember where the caller actually is, BEFORE moving to r/.
# Without it a relative boundary path -- which is how anyone will type it --
# resolves against r/ instead of the caller's directory and the script reports
# the file does not exist. It does; it is just being looked for in the wrong
# place, which is the least helpful possible error.
INVOKED_FROM <- getwd()

local({
  # Match add_field.R specifically, not any --file=. Sourcing this from another
  # script run under Rscript leaves --file= pointing at THAT script, and a
  # generic match then changes to its directory and fails to find pipeline.R.
  a <- commandArgs(trailingOnly = FALSE)
  f <- sub("^--file=", "", a[grep("^--file=.*add_field[.]R$", a)])
  if (length(f)) {
    setwd(dirname(normalizePath(f[1], winslash = "/")))   # run with Rscript
  } else if (file.exists("pipeline.R")) {
    invisible(NULL)                                       # already in r/
  } else if (file.exists(file.path("r", "pipeline.R"))) {
    setwd("r")                                            # sourced from the repo root
  } else {
    stop("Could not find the pipeline. Run this from the repository root or ",
         "from r/.", call. = FALSE)
  }
})
suppressMessages(source("pipeline.R"))

#' Resolve a user-supplied path against the directory they called from.
from_invocation <- function(path) {
  if (file.exists(path)) return(path)
  alt <- file.path(INVOKED_FROM, path)
  if (file.exists(alt)) return(alt)
  path
}

LIB <- file.path(FIELDS_DIR, "library.csv")

read_manifest <- function() {
  if (!file.exists(LIB)) {
    return(data.frame(stem = character(0), label = character(0),
                      shows = character(0), added = character(0),
                      stringsAsFactors = FALSE))
  }
  utils::read.csv(LIB, stringsAsFactors = FALSE)
}

#' What the manifest and the boundary files say about each other.
library_status <- function() {
  files <- list.files(FIELDS_DIR, pattern = "[.]geojson$")
  man   <- read_manifest()
  stems <- tools::file_path_sans_ext(files)
  cat(sprintf("library: %d boundaries, %d manifest rows\n\n",
              length(stems), nrow(man)))
  missing <- setdiff(stems, man$stem)
  orphan  <- setdiff(man$stem, stems)
  if (length(missing))
    cat("  boundaries with no manifest row (labelled from filename):\n",
        paste0("    ", missing, collapse = "\n"), "\n", sep = "")
  if (length(orphan))
    cat("  manifest rows with no boundary file:\n",
        paste0("    ", orphan, collapse = "\n"), "\n", sep = "")
  if (!length(missing) && !length(orphan))
    cat("  manifest and boundaries agree.\n")
  invisible(list(boundaries = stems, manifest = man$stem,
                 missing = missing, orphan = orphan))
}

#' Add a boundary to the demo library and warm everything the app reads.
#'
#' @param src   Path to a boundary file, relative to wherever you are.
#' @param label Name on the gallery card. Defaults to the stem, de-punctuated.
#' @param shows One line on what the field demonstrates. The gallery filter
#'   searches it, so it is worth writing properly rather than leaving blank.
#' @param stem  Library key and filename. Defaults to the source filename,
#'   which is usually wrong for a boundary called something like 40464_2020.
#' @param force Replace a boundary already in the library.
#' @return TRUE if everything warmed, FALSE otherwise, invisibly.
add_field <- function(src, label = NULL, shows = "", stem = NULL,
                      force = FALSE) {
  src <- from_invocation(src)
  if (!file.exists(src)) {
    stop("No such file: ", src, "\n  Looked in ", INVOKED_FROM,
         " and in ", getwd(), ".", call. = FALSE)
  }
  stem <- if (is.null(stem)) tools::file_path_sans_ext(basename(src)) else stem
  # Remember whether a label was actually given. Defaulting it and then writing
  # it back unconditionally meant re-running on an existing field -- which this
  # script positively encourages, since it is idempotent -- silently replaced a
  # curated label with the de-punctuated stem. It did exactly that to
  # "Georgia - Mitchell Co. (no-till)".
  label_given <- !is.null(label) && nzchar(label)
  label <- if (label_given) label else gsub("[-_]", " ", stem)
  dest  <- file.path(FIELDS_DIR, paste0(stem, ".geojson"))

  # --- 1. validate before copying --------------------------------------------
  # single_field() is the same rule the app enforces, so a boundary that would
  # be refused in the UI never reaches the library.
  aoi <- single_field(load_field(src))
  cat(sprintf("\n%s\n  %.2f ha, %s\n", stem, sum(aoi$area_ha),
              as.character(sf::st_geometry_type(aoi))))
  if (attr(aoi, "dropped") > 0L)
    cat(sprintf("  %d sliver(s) dropped\n", attr(aoi, "dropped")))

  if (file.exists(dest) && !force) {
    cat("  boundary already in the library; leaving it alone",
        " (force = TRUE to replace)\n", sep = "")
  } else {
    # Write the cleaned single-field geometry rather than copying the original:
    # what the library holds should be what the app would analyse.
    out <- aoi[, intersect(c("field_id", "area_ha"), names(aoi)), drop = FALSE]
    unlink(dest)
    sf::st_write(sf::st_transform(out, 4326), dest, driver = "GeoJSON",
                 quiet = TRUE)
    cat("  written to ", dest, "\n", sep = "")
  }

  # --- 2. manifest row -------------------------------------------------------
  man <- read_manifest()
  if (stem %in% man$stem) {
    if (label_given) man$label[man$stem == stem] <- label
    if (nzchar(shows)) man$shows[man$stem == stem] <- shows
    cat("  manifest row ", if (label_given || nzchar(shows)) "updated"
        else "left as it is", "\n", sep = "")
  } else {
    man <- rbind(man, data.frame(stem = stem, label = label, shows = shows,
                                 added = as.character(Sys.Date()),
                                 stringsAsFactors = FALSE))
    cat("  manifest row added\n")
  }
  utils::write.csv(man, LIB, row.names = FALSE)

  # --- 3. warm the caches ----------------------------------------------------
  cat("\nwarming (cached years return instantly)\n")
  YEARS <- c(2020, as.integer(format(Sys.Date(), "%Y")))
  t0 <- Sys.time()

  step <- function(what, expr) {
    s <- Sys.time()
    ok <- tryCatch({ force(expr); TRUE },
                   error = function(e) { cat("   ", what, "FAILED:",
                                             conditionMessage(e), "\n"); FALSE })
    cat(sprintf("  %-22s %s  %.1f min\n", what, if (ok) "ok" else "--",
                as.numeric(difftime(Sys.time(), s, units = "mins"))))
    ok
  }

  win <- analysis_window(YEARS[1], YEARS[2])

  # The order and the set both matter. run_analysis() in app.R asks for the
  # availability catalogue FIRST and returns NULL the moment anything is
  # missing, so a field warmed without it reads as entirely cold however much
  # else is cached -- which is exactly what happened the first time this ran.
  # Keep this list in step with run_analysis().
  ok <- c(
    avail  = step("availability catalog",
                  catalog_availability(aoi, win$start, win$end)),
    cdl    = step("CDL stack", cdl_stack(aoi, YEARS[1]:(YEARS[2] - 1L))),
    series = step("NDVI series",
                  extract_field_series(aoi, win$start, win$end,
                                       indices = "ndvi", workers = 6)),
    armor  = step("soil armor", armor_series(aoi, YEARS, workers = 6))
  )

  # --- 4. CDL clips, so a fresh clone works without the national store -------
  clip_ok <- step("CDL clips", {
    dir.create(file.path(PIPELINE_DIR, "cdl_clips"), showWarnings = FALSE)
    for (y in cdl_available_years()) {
      d <- file.path(PIPELINE_DIR, "cdl_clips",
                     sprintf("%s_%d.tif", cache_key(aoi, "cdlclip"), y))
      if (!file.exists(d)) {
        terra::writeRaster(get_cdl_local(aoi, y, clip = TRUE), d,
                           overwrite = TRUE, datatype = "INT1U",
                           gdal = c("COMPRESS=DEFLATE"))
      }
    }
  })

  cat(sprintf("\ndone in %.1f min\n",
              as.numeric(difftime(Sys.time(), t0, units = "mins"))))
  cat("\ncommit:\n",
      "  git add data/fields/ r/cache/ r/cdl_clips/\n",
      "  git commit -m \"Add ", stem, " to the demo library\"\n", sep = "")

  if (!all(ok, clip_ok)) {
    cat("\nSomething did not warm. The field is in the library but will read ",
        "cold in the app; run it again to finish.\n", sep = "")
    return(invisible(FALSE))
  }
  invisible(TRUE)
}

# --------------------------------------------------------------------- CLI ---
# Only when run with Rscript. Sourced from the R console this file just defines
# add_field() and library_status() and does nothing else, which is what makes
# the console path work at all.
if (!interactive() &&
    any(grepl("^--file=.*add_field[.]R$", commandArgs(FALSE)))) {
  .args  <- commandArgs(trailingOnly = TRUE)
  .getop <- function(flag, default = NULL) {
    i <- match(flag, .args)
    if (is.na(i) || i == length(.args)) default else .args[i + 1L]
  }
  if ("--status" %in% .args) {
    library_status()
    quit(status = 0)
  }
  if (!length(.args) || is.na(.args[1]) || startsWith(.args[1], "--")) {
    stop("Usage: Rscript r/add_field.R <boundary.geojson> --label \"...\" ",
         "--shows \"...\"\n       Rscript r/add_field.R --status",
         call. = FALSE)
  }
  .ok <- add_field(.args[1], label = .getop("--label"),
                   shows = .getop("--shows", ""), stem = .getop("--stem"),
                   force = "--force" %in% .args)
  quit(status = if (isTRUE(.ok)) 0 else 1)
}
