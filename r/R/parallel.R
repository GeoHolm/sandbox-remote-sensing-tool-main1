# ==============================================================================
# parallel.R -- One worker pool, held open
#
# future::plan(multisession) starts fresh R subprocesses, which on Windows
# costs about two seconds. scene_grid() and extract_field_series() each used to
# set a plan on entry and restore the old one on exit, so every press of "Show
# imagery" paid that spin-up again before a single byte was read -- and then
# threw the workers away.
#
# The pool is started once and left up for the life of the session. It only
# ever grows: a call asking for fewer workers than are already running uses the
# ones that exist rather than restarting the pool at a smaller size, so the
# 6-worker contact sheet and the 8-worker extraction share one pool instead of
# tearing each other's down.
# ==============================================================================

#' How many workers this machine will actually allow.
#'
#' parallelly::availableCores() honours cgroup CPU limits, which is what makes
#' this safe to deploy. A laptop reports 8 or more and the pool runs at full
#' size; a shinyapps.io instance reports 1, and six R subprocesses each loading
#' sf and terra would exhaust a 1 GB container before the app served a page.
#' Capping here rather than at each call site means no caller has to know
#' where it is running.
#'
#' Override with R_FIELDRS_WORKERS to force a size either way.
worker_budget <- function() {
  env <- suppressWarnings(as.integer(Sys.getenv("R_FIELDRS_WORKERS", "")))
  if (!is.na(env) && env >= 1) return(env)
  n <- tryCatch(as.integer(parallelly::availableCores()), error = function(e) 1L)
  if (is.na(n) || n < 1L) 1L else n
}

#' Ensure a parallel backend with at least `workers` processes is running.
#'
#' @param workers Requested pool size, capped at what the machine allows.
#'   1 or less forces sequential execution.
#' @return TRUE if parallel execution is available, FALSE to run sequentially.
ensure_workers <- function(workers = 6) {
  workers <- min(workers, worker_budget())
  if (workers <= 1) return(FALSE)
  if (!requireNamespace("future", quietly = TRUE) ||
      !requireNamespace("furrr", quietly = TRUE)) return(FALSE)

  running <- tryCatch(future::nbrOfWorkers(), error = function(e) 0)
  if (inherits(future::plan(), "multisession") &&
      is.finite(running) && running >= workers) {
    return(TRUE)
  }

  # Not "once per session": the pool is replaced whenever a caller asks for more
  # workers than are running, which the log made confusing by claiming otherwise
  # both times. Say which it is, because tearing down a live pool and starting a
  # larger one costs several seconds mid-run.
  message(sprintf("  %s %d worker processes...",
                  if (is.finite(running) && running > 0)
                    sprintf("Replacing %d with", running) else "Starting",
                  workers))
  future::plan(future::multisession, workers = workers)
  TRUE
}
