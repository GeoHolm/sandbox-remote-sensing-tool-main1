# ==============================================================================
# app.R -- Field remote sensing explorer
#
#   shiny::runApp()
#
# Upload a field boundary, see what satellite data exists for it, and read the
# management story back out of the NDVI record: crop rotation, planting and
# harvest windows, and off-season cover.
# ==============================================================================

library(shiny)
library(bslib)
library(leaflet)
library(leaflet.extras)   # draw toolbar; see R/draw.R
library(DT)

source("pipeline.R")

# Start the worker pool now rather than on the first press of "Show imagery".
# It costs about two seconds here and saves the same two seconds on every
# contact sheet for the rest of the session. Sized for the Imagery tab; a cold
# field extraction asks for 8 and grows the pool once, on demand.
ensure_workers(6)

YEAR_MIN <- 2020

# Loose on purpose: the contact sheet is meant to show what the satellite
# actually collected, including the passes that turned out to be unusable.
IMG_MAX_CLOUD <- 90

# Human labels for the shipped boundaries, in the order they should appear.
# Anything in data/fields/ that is not listed still shows up, labelled from its
# filename -- dropping a new boundary in is all it takes to add it.
# Short tile captions for the shipped boundaries, in the order they should
# appear. Kept terse on purpose: a tile in a 320 px sidebar is about 145 px
# wide, so anything longer than three or four words wraps to a third line and
# pushes the grid out of alignment. Anything in data/fields/ that is not listed
# still shows up, captioned from its filename -- dropping a new boundary in is
# all it takes to add it.
# The field library manifest: data/fields/library.csv.
#
# These labels used to live here as a constant, which meant adding a boundary
# required editing the application. That is the step that turns "add a field
# whenever we run one" into "add a field when someone has an afternoon", so the
# names and the one-line description of what each field demonstrates now sit
# beside the boundaries themselves. r/add_field.R writes a row; nothing here
# changes.
#
# A boundary with no row still appears, labelled from its filename. The library
# is meant to keep working when the manifest falls behind.
LIBRARY_CSV <- file.path(FIELDS_DIR, "library.csv")

read_library_manifest <- function() {
  empty <- data.frame(stem = character(0), label = character(0),
                      shows = character(0), added = character(0),
                      stringsAsFactors = FALSE)
  if (!file.exists(LIBRARY_CSV)) return(empty)
  m <- tryCatch(utils::read.csv(LIBRARY_CSV, stringsAsFactors = FALSE),
                error = function(e) NULL)
  if (is.null(m) || !"stem" %in% names(m)) return(empty)
  for (col in c("label", "shows", "added")) {
    if (!col %in% names(m)) m[[col]] <- ""
  }
  m[, c("stem", "label", "shows", "added")]
}

#' The demo library, annotated from the warmed cache where one exists.
#'
#' warm_cache.R writes outputs/demo_library.csv with the crops each field
#' actually grew, so the captions report CDL rather than anything hand-typed
#' and cannot drift from the data.
#'
#' @return Data frame of path, stem, label and crops, in display order.
demo_library <- function() {
  files <- list.files(FIELDS_DIR, pattern = "[.]geojson$", full.names = TRUE)
  if (!length(files)) {
    return(data.frame(path = character(0), stem = character(0),
                      label = character(0), crops = character(0)))
  }
  stems <- tools::file_path_sans_ext(basename(files))

  # Manifest order is tile order, so a curated sequence survives; anything not
  # listed sorts after, rather than disappearing.
  man <- read_library_manifest()
  ord   <- order(match(stems, man$stem, nomatch = nrow(man) + 1L), stems)
  files <- files[ord]; stems <- stems[ord]

  i     <- match(stems, man$stem)
  labs  <- ifelse(!is.na(i) & nzchar(man$label[i]), man$label[i],
                  gsub("[-_]", " ", stems))
  shows <- ifelse(!is.na(i), man$shows[i], "")
  shows[is.na(shows)] <- ""

  meta <- tryCatch(utils::read.csv("outputs/demo_library.csv", stringsAsFactors = FALSE),
                   error = function(e) NULL)
  crops <- rep("", length(files))
  if (!is.null(meta) && all(c("file", "crops") %in% names(meta))) {
    m <- meta[match(basename(files), meta$file), ]
    crops <- ifelse(is.na(m$crops), "", m$crops)
  }

  data.frame(path = unname(files), stem = stems, label = unname(labs),
             crops = unname(crops), shows = unname(shows),
             stringsAsFactors = FALSE)
}

EXAMPLE_FIELDS <- demo_library()

#' Shorten a CDL rotation for a tile caption.
#'
#' A long rotation -- "Dbl Crop WinWht/Corn/Dbl Crop Triticale/Corn" -- is
#' wider than the tile. Truncate for display and keep the full string as the
#' hover title, so nothing is actually lost.
short_crops <- function(x, max_chars = 26) {
  if (!nzchar(x)) return("")
  if (nchar(x) <= max_chars) return(x)
  paste0(substr(x, 1, max_chars - 1), "…")
}

#' The example-field picker, as a two-across grid of tiles.
#'
#' Each tile is a plain button that sets one Shiny input rather than being an
#' actionButton of its own: eleven separate inputs would need eleven observers
#' to do one job.
#'

#' The field library as a gallery of cards.
#'
#' The sidebar tiles were fine at eleven fields and will not be at forty: a
#' 320 px column turns into a scroll tunnel. This lives in the Field tab, where
#' there is room to show what each field actually demonstrates rather than only
#' its name -- which is the thing that keeps a growing library a teaching set
#' instead of a list.
field_gallery <- function(lib, active = NULL, query = "") {
  if (!nrow(lib)) return(helpText("No boundaries found in data/fields/."))

  if (nzchar(query)) {
    hay <- tolower(paste(lib$label, lib$crops, lib$shows))
    # Every word has to appear somewhere, so "georgia cotton" narrows rather
    # than widening the way an OR would.
    words <- strsplit(tolower(trimws(query)), " ", fixed = TRUE)[[1]]
    words <- words[nzchar(words)]
    hit <- Reduce(`&`, lapply(words, function(w) grepl(w, hay, fixed = TRUE)))
    lib <- lib[hit, , drop = FALSE]
  }
  if (!nrow(lib)) {
    return(div(class = "text-muted small p-2",
               "No field matches that. Clear the filter to see them all."))
  }

  div(class = "field-gallery",
    lapply(seq_len(nrow(lib)), function(i) {
      tags$button(
        type = "button",
        class = paste("fg-card", if (identical(lib$stem[i], active)) "active"),
        onclick = sprintf(
          "Shiny.setInputValue('example_pick', '%s', {priority: 'event'})",
          lib$stem[i]),
        span(class = "fg-name", lib$label[i]),
        if (nzchar(lib$crops[i])) span(class = "fg-crop", short_crops(lib$crops[i], 40)),
        if (!is.null(lib$shows) && nzchar(lib$shows[i]))
          span(class = "fg-shows", lib$shows[i])
      )
    })
  )
}

#' datatable() with a CSV download button attached.
#'
#' Every table in the app goes through this rather than DT::datatable directly,
#' so the export exists everywhere without eight near-identical option blocks
#' and without refactoring each table into a data reactive. The CSV is produced
#' by DataTables from the rendered rows, so what downloads is exactly what is on
#' screen -- including the column names and the rounding -- which a separate
#' handler reading the underlying frame would quietly get wrong.
dt_dl <- function(data, ..., options = list(), filename) {
  options$dom <- paste0("B", options$dom %||% "t")
  options$buttons <- list(list(
    extend = "csv", text = "Download CSV", filename = filename,
    className = "btn btn-sm btn-outline-secondary"))
  DT::datatable(data, ..., extensions = "Buttons", options = options)
}

#' A card header with a PNG download button on the right.
#'
#' Plots are base R drawn into a device, so unlike the tables there is nothing
#' client-side to export -- the handler has to redraw them. dl_header() is the
#' UI half and dl_plot() in the server is the other.
dl_header <- function(title, id) {
  card_header(div(
    class = "d-flex justify-content-between align-items-center",
    span(title),
    downloadButton(paste0("dl_", id), "PNG",
                   class = "btn btn-sm btn-outline-secondary py-0")))
}

# ------------------------------------------------------------------- upload ---

#' Turn a Shiny fileInput data frame into an sf field boundary.
#'
#' Handles the three ways people actually supply boundaries: a single GeoJSON /
#' KML / GeoPackage, a zipped shapefile, or a multi-file shapefile selection.
#' The last one needs the sidecar files restored to their original names, since
#' Shiny stores uploads under generated ones and GDAL matches .shp to .dbf/.shx
#' by name.
read_upload <- function(inp) {
  if (is.null(inp) || !nrow(inp)) return(NULL)
  dir <- file.path(tempdir(), paste0("upload_", as.integer(Sys.time())))
  dir.create(dir, showWarnings = FALSE, recursive = TRUE)

  for (i in seq_len(nrow(inp))) {
    file.copy(inp$datapath[i], file.path(dir, inp$name[i]), overwrite = TRUE)
  }

  zips <- list.files(dir, pattern = "\\.zip$", full.names = TRUE, ignore.case = TRUE)
  for (z in zips) utils::unzip(z, exdir = dir)

  cand <- list.files(dir, pattern = "\\.(shp|geojson|json|gpkg|kml)$",
                     full.names = TRUE, recursive = TRUE, ignore.case = TRUE)
  if (!length(cand)) {
    stop("No boundary file found. Upload a .geojson, .kml, .gpkg, or a zipped shapefile.")
  }
  # Prefer a shapefile when both are present -- a zip usually carries one.
  shp <- grep("\\.shp$", cand, value = TRUE, ignore.case = TRUE)
  load_field(if (length(shp)) shp[1] else cand[1])
}

#' The confirmation dialog for a hand-drawn boundary.
#'
#' Shows what CDL saw inside the polygon before anything expensive runs, so the
#' decision to spend one to three minutes on a read is made with the crop
#' history already on screen. The verdict and the maps are outputs rather than
#' literals, so redrawing refreshes them.
draw_modal <- function(aoi, adv) {
  n  <- if (is.null(adv) || is.null(adv$per_year)) 6 else nrow(adv$per_year)
  nr <- ceiling(n / 3)
  modalDialog(
    title = sprintf("Drawn boundary -- %.1f ha", sum(aoi$area_ha)),
    size = "l",
    uiOutput("draw_verdict"),
    div(class = "text-muted small mb-2",
        "One map per year, clipped to what you drew, coloured by CDL crop ",
        "class. A boundary that is one management unit shows one colour ",
        "filling it every year."),
    plotOutput("draw_matrix", height = min(900, 120 + nr * 240)),
    footer = tagList(
      # An actionButton rather than modalButton: dismissing the dialog has to
      # also wipe the shape off the map, or the next drawing sits beside it.
      actionButton("draw_discard", "Redraw"),
      actionButton("draw_confirm", "Use this field", class = "btn-primary")
    ),
    easyClose = FALSE
  )
}

# ----------------------------------------------------------------------- ui ---

ui <- page_navbar(
  title = "Field Remote Sensing Explorer",
  theme = bs_theme(version = 5, bootswatch = "flatly",
                   primary = "#01665e", base_font = font_google("Inter")),
  id = "nav",

  # Panels scroll normally instead of being flex fill containers. Left fillable,
  # bslib sizes cards to the viewport and lets their contents run past the box:
  # tables and helper paragraphs end up drawn on top of each other.
  fillable = FALSE,

  header = tags$head(tags$style(HTML("
    /* htmlwidgets draws output messages absolutely positioned over the widget.
       While a table is waiting on the analysis its container collapses to
       height 0, so the 'press Run analysis' message has nothing to sit on and
       paints straight over the caption underneath. Put it back in normal flow
       so it takes up space like any other block. */
    .htmlwidgets-error {
      position: static !important;
      height: auto !important;
      padding: 0.25rem 0 0.5rem 0;
    }

    /* Example-field picker. Two across at a 320 px sidebar leaves each tile
       about 145 px, which fits a two-word place name and a truncated crop
       rotation. Equal-height rows come free with grid. */
    .field-gallery {
      display: grid;
      /* auto-fill rather than a fixed count: the card stays readable from a
         laptop to a wide monitor without a breakpoint for each. */
      grid-template-columns: repeat(auto-fill, minmax(15rem, 1fr));
      gap: 0.6rem;
    }
    .fg-card {
      display: block;
      text-align: left;
      padding: 0.7rem 0.8rem;
      border: 1px solid var(--bs-border-color);
      border-left: 3px solid var(--bs-border-color);
      border-radius: 0.375rem;
      background: var(--bs-body-bg);
      color: inherit;
      transition: border-color .12s, background-color .12s;
    }
    .fg-card:hover { border-color: var(--bs-primary); background: var(--bs-tertiary-bg); }
    .fg-card:focus-visible { outline: 2px solid var(--bs-primary); outline-offset: 1px; }
    .fg-card.active {
      border-color: var(--bs-primary);
      border-left-color: var(--bs-primary);
      background: var(--bs-tertiary-bg);
    }
    .fg-card .fg-name {
      display: block; font-weight: 600; font-size: 0.9rem; line-height: 1.25;
    }
    .fg-card .fg-crop {
      display: block; font-size: 0.75rem; margin-top: 0.15rem;
      color: var(--bs-secondary-color);
    }
    .fg-card .fg-shows {
      display: block; font-size: 0.78rem; margin-top: 0.4rem; line-height: 1.35;
      color: var(--bs-secondary-color);
    }
    .imagery-timing.alert-warning,
    .imagery-timing.alert-warning strong { color: #3d2c00; }
    .imagery-timing.alert-success,
    .imagery-timing.alert-success strong { color: #0a332b; }
    .imagery-timing.alert-secondary,
    .imagery-timing.alert-secondary strong { color: #2b2f33; }
    .imagery-timing-tag {
      display: inline-block;
      background: #fff;
      font-weight: 700;
      font-size: 0.68rem;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      padding: 0.1rem 0.45rem;
      border-radius: 0.25rem;
      margin-right: 0.35rem;
    }
    .alert-warning  > .imagery-timing-tag { color: #8a5000; }
    .alert-success  > .imagery-timing-tag { color: #0a5f4e; }
    .alert-secondary > .imagery-timing-tag { color: #2b2f33; }
  "))),

  sidebar = sidebar(
    width = 320,
    h5("Your field"),
    fileInput("boundary", NULL, multiple = TRUE, buttonLabel = "Browse...",
              placeholder = "No boundary chosen",
              accept = c(".geojson", ".json", ".kml", ".gpkg",
                         ".zip", ".shp", ".shx", ".dbf", ".prj")),
    helpText("GeoJSON, KML, GeoPackage, or a zipped shapefile. ",
             "For a loose shapefile select the .shp, .shx, .dbf and .prj together."),
    div(class = "text-muted small mb-2",
        HTML("Or <strong>draw one</strong> with the polygon tool on the Field ",
             "map. The crop history is checked before anything else runs.")),

    hr(),
    uiOutput("current_field"),
    sliderInput("years", "Years", min = YEAR_MIN,
                max = as.integer(format(Sys.Date(), "%Y")),
                value = c(YEAR_MIN, as.integer(format(Sys.Date(), "%Y"))),
                sep = "", step = 1),
    actionButton("run", "Run analysis", class = "btn-primary w-100"),
    div(class = "mt-2", uiOutput("clear_ui")),
    hr(),
    uiOutput("status"),
    hr(),
    downloadButton("dl_summary", "Download summary CSV",
                   class = "btn-outline-secondary btn-sm w-100")
  ),

  # ---- 1. field -------------------------------------------------------------
  nav_panel(
    "Field",
    layout_columns(
      col_widths = c(7, 5),
      card(card_header("Boundary"), leafletOutput("map", height = 460)),
      card(card_header("Crop rotation (USDA CDL)"),
           card_body(fillable = FALSE,
             DTOutput("tbl_rotation"),
             div(class = "text-muted small mt-2",
                 "Dominant crop per year, with the share of the field it covers. ",
                 "A low share means the boundary spans more than one management unit.")))
    ),
    card(card_header("Field summary"), uiOutput("field_stats")),
    card(
      card_header(
        div(class = "d-flex justify-content-between align-items-center",
            uiOutput("gallery_header", inline = TRUE),
            div(style = "width: 15rem;",
                textInput("gallery_q", NULL, placeholder = "Filter: crop, state, practice",
                          width = "100%")))),
      card_body(
        fillable = FALSE,
        uiOutput("field_gallery_ui"),
        div(class = "text-muted small mt-2",
            "Pre-computed — these open straight from the cache. Each card says ",
            "what the field demonstrates; ", tags$code("r/add_field.R"),
            " adds another."))
    )
  ),

  # ---- 2. CDL ---------------------------------------------------------------
  nav_panel(
    "CDL",
    card(
      card_header("Is this one field?"),
      card_body(fillable = FALSE,
        uiOutput("cdl_advice"),
        DTOutput("tbl_cdl_year"))
    ),
    card(
      dl_header("Crop type by year (USDA CDL, 30 m)", "plot_cdl_matrix"),
      card_body(fillable = FALSE,
        uiOutput("cdl_matrix_ui"),
        div(class = "text-muted small mt-2",
            "One map per year, clipped to the boundary, coloured by CDL class. ",
            "Grey is developed or road, pale green is grass/pasture. A boundary ",
            "that is one management unit shows one colour filling it every year."))
    ),
    card(
      dl_header("Where the boundary disagrees with itself", "plot_cdl_split"),
      card_body(fillable = FALSE,
        plotOutput("plot_cdl_split", height = 460),
        div(class = "text-muted small mt-2",
            "Share of years each pixel carried a different crop from the ",
            "boundary's dominant crop that year. Pale means it agrees every ",
            "year. A persistent red block outlined in red is a sub-area being ",
            "farmed separately -- one red year is classification noise, five is ",
            "a second field."))
    )
  ),

  # ---- 3. data availability -------------------------------------------------
  nav_panel(
    "Data availability",
    card(
      dl_header("Every acquisition over this field", "plot_timeline"),
      card_body(fillable = FALSE,
         plotOutput("plot_timeline", height = 420),
         div(class = "p-2 text-muted small",
             "Catalogue metadata only, so this is fast. Optical marks are shaded ",
             "by scene cloud cover. The density is the point -- Sentinel-2 alone ",
             "has looked at this field over a thousand times since 2020, and ",
             "radar adds a stream that weather cannot interrupt. The table below ",
             "gives the exact counts."))),
    card(card_header("By source"),
         card_body(fillable = FALSE, DTOutput("tbl_catalog"))),
    card(card_header("What each source is for"), uiOutput("source_notes"))
  ),

  # ---- 4. imagery -----------------------------------------------------------
  nav_panel(
    "Imagery",
    card(
      card_header("Pick a quarter"),
      card_body(
        fillable = FALSE,
        layout_columns(
          col_widths = breakpoints(sm = 12, md = c(4, 5, 3)),
          uiOutput("period_picker"),
          radioButtons("view", "View",
                       c("True colour" = "rgb", "False colour (NIR)" = "fc",
                         "NDVI" = "ndvi", "Soil armor" = "armor"),
                       selected = "rgb", inline = TRUE),
          div(class = "d-flex align-items-end h-100",
              actionButton("show_imagery", "Show imagery",
                           class = "btn-primary w-100"))
        ),
        # The one place in the app that does real work while someone waits.
        # The wait is stated before the button is pressed, and stated for the
        # exact quarter and view selected rather than in general -- see
        # output$imagery_cost.
        uiOutput("imagery_cost"),
        div(class = "text-muted small mt-2",
            "Every acquisition in the quarter, on one sheet. Grey means the ",
            "pixel was masked as cloud, shadow or snow, so a grey cell is a ",
            "date the satellite passed over but saw nothing usable. All cells ",
            "share one fixed brightness scale, so dates really are comparable ",
            "with each other. Nothing is read until you press the button, and ",
            "once a quarter has been read it stays cached for good.",
            tags$br(),
            tags$strong("The Soil armor view is per-pixel cover."),
            " Each pixel is unmixed into living green, crop residue and bare ",
            "soil, and the sheet shows ", tags$strong("1 − bare soil"),
            " on a six-stop scale: dark brown at 0, tan, cream around the ",
            "halfway mark, then pale teal to dark teal at 1. Brown is exposed ",
            "ground; teal is covered by something. Unlike the other views it ",
            "answers a management question directly, and it is the one view ",
            "where a summer quarter and a spring quarter mean the same thing.",
            tags$br(),
            tags$strong("It shows how much cover, not what kind."),
            " The three fractions are collapsed into one number before ",
            "colouring, so a pixel that is half living and half bare renders ",
            "identically to one that is half residue and half bare — both are ",
            "cream. For the living-versus-residue split, read the ",
            tags$strong("Soil armor"), " tab, which reports them as separate ",
            "columns and stacks them in the per-season plot.")
      )
    ),
    card(dl_header("Contact sheet", "plot_grid"),
         card_body(fillable = FALSE, uiOutput("grid_ui")))
  ),

  # ---- 5. season ------------------------------------------------------------
  nav_panel(
    "Season analysis",
    card(
      dl_header("Planting and harvest windows", "plot_phen"),
      card_body(fillable = FALSE,
         layout_columns(
           col_widths = breakpoints(sm = 12, md = 6),
           radioButtons("phen_view", "View",
                        c("Whole record, split" = "split",
                          "Whole record, one axis" = "all",
                          "Single season" = "one"),
                        selected = "split", inline = TRUE),
           uiOutput("year_picker")
         ),
         uiOutput("phen_ui"),
         div(class = "text-muted small",
             "Dashed lines are the estimated planting (blue) and harvest ",
             "(orange) dates; shading is the off-season between them. NDVI sees ",
             "the canopy, not the planter -- these are inferred from green-up ",
             "and senescence and are good to roughly two weeks. Each season is ",
             "smoothed on its own, never across years."))),
    card(card_header("Season markers, all years"),
         card_body(fillable = FALSE, DTOutput("tbl_phen")))
  ),

  # ---- 6. cover crops -------------------------------------------------------
  nav_panel(
    "Cover crops",
    card(
      dl_header("Off-season green cover, every winter", "plot_cc"),
      card_body(fillable = FALSE,
         uiOutput("cc_ui"),
         div(class = "text-muted small mt-2",
             "One panel per winter on a shared October-to-June axis. The lower ",
             "dotted line is the residue ceiling (0.25) and the upper one is ",
             "sustained green (0.30); a winter that stays below both is bare ",
             "ground."))),
    card(card_header("All winters"),
         card_body(fillable = FALSE, DTOutput("tbl_cc"))),
    card(card_header("How to read this"),
         div(class = "p-3",
             p(strong("The signal: "),
               "bare residue sits around 0.10-0.25 NDVI all winter. A planted ",
               "cover crop establishes in autumn and greens up again in early ",
               "spring, showing as a hump above that floor."),
             p(strong("The caveat: "),
               "NDVI sees green, not intent. Volunteer grain, winter annual ",
               "weeds and a grassed waterway inside the boundary all look ",
               "similar. Treat a verdict as evidence to check, not a finding."),
             p(strong("Before relying on it: "),
               "calibrate the thresholds against fields where the practice is ",
               "known. That turns this from suggestive into defensible.")))
  ),

  # ---- 7. soil armor --------------------------------------------------------
  nav_panel(
    "Soil armor",
    card(
      card_header("Off-season soil cover"),
      card_body(
        fillable = FALSE,
        div(class = "alert alert-warning imagery-timing py-2 px-3 mb-3 small",
            span(class = "imagery-timing-tag", "Exploratory"),
            tags$strong("These fractions are not calibrated cover ",
                        "percentages."),
            " The three endmembers were derived from this library's own pixels, ",
            "so the numbers are consistent and comparable between these fields ",
            "but are not validated against measured cover. Shortwave ",
            "reflectance also moves with soil moisture. Read the spread across ",
            "the window, not a single date, and calibrate against line ",
            "transects — scoring green, residue and bare separately — before ",
            "reporting anything."),
        layout_columns(
          col_widths = breakpoints(sm = 12, md = c(5, 4, 3)),
          div(class = "text-muted small",
              "How much of the surface is protected between harvest and the ",
              "next planting — by ", tags$strong("anything"), ", living cover ",
              "or crop residue. Each pixel is split into living green, residue ",
              "and bare soil; ", tags$strong("armor = 1 − bare soil."),
              " Needs its own pass over the shortwave infrared, so it runs ",
              "only when you ask."),
          div(class = "text-muted small",
              tags$strong("Charts: whole calendar years."),
              tags$br(),
              "The imagery pass now runs 1 Jan to 31 Dec, so fall tillage, ",
              "cover crop establishment and overwinter residue loss are all ",
              "visible. The ", tags$strong("reported figure is still the ",
              "pre-planting window"), " — shaded on each panel — so the per-",
              "season table means what it always did."),
          div(class = "d-flex align-items-end h-100",
              actionButton("run_residue", "Run soil armor analysis",
                           class = "btn-primary w-100"))
        ),
        uiOutput("residue_cost")
      )
    ),
    card(dl_header("Calendar year, with the pre-planting window shaded", "plot_armor"),
         card_body(fillable = FALSE,
            uiOutput("residue_ui"),
            div(class = "text-muted small mt-2",
                "Teal is living cover, tan is crop residue, and the white gap ",
                "to the top is ", tags$strong("bare soil"), " — the quantity ",
                "being measured. One panel per calendar year; the shaded band ",
                "between the dashed lines is the pre-planting window the ",
                "headline armor figure is averaged over. ",
                "Nothing is screened out any more: a green date is cover, not ",
                "an obstacle, which is the whole reason this replaced minimum ",
                "NDTI."))),
    card(card_header("Per season"),
         card_body(fillable = FALSE, DTOutput("tbl_residue"))),
    card(card_header("How to read this"),
         div(class = "p-3",
             p(strong("The signal: "),
               "residue holds cellulose and lignin, which absorb near 2100 nm. ",
               "The Dead Fuel Index compares Sentinel-2 B11 (1610 nm) against ",
               "B12 (2190 nm) to pick that up, and NDVI measures green. ",
               "Together they place every pixel in a triangle whose corners are ",
               "pure living cover, pure residue and clean bare soil — so each ",
               "pixel resolves into three fractions that sum to one."),
             p(strong("Why not just residue: "),
               "this replaced a minimum-NDTI metric that measured residue only. ",
               "A field under a living cover crop or a perennial stand is ",
               "protected just as well as one under stubble, and the old metric ",
               "scored it as bare — the Washington alfalfa pivot, the ",
               "best-covered soil in this library, ranked last of eleven. ",
               strong("Armor counts cover from any source.")),
             p(strong("The confounders: "),
               "shortwave reflectance moves with soil moisture, so read the ",
               "window rather than a single date. Water and deep shadow are ",
               "masked out entirely — as near-infrared collapses the index ",
               "breaks down, and flooded ground would otherwise read as heavy ",
               "residue."),
             p(strong("What is not calibrated: "),
               "the three corners were fitted from this library's own pixels, ",
               "so the fractions are comparable between these fields but are ",
               "not validated cover percentages. Ground truth here means line ",
               "transects scoring green, residue and bare separately — which ",
               "validates all three fractions at once.")))
  ),

  # ---- 8. summary -----------------------------------------------------------
  nav_panel(
    "Summary",
    card(card_header("Management history inferred from satellite"),
         card_body(fillable = FALSE,
           DTOutput("tbl_summary"),
           div(class = "text-muted small mt-2",
               "One row per season. Everything here is derived from free, public ",
               "imagery with no field visit and no grower input.",
               tags$br(),
               tags$strong("Soil armor is provisional and uncalibrated"),
               " — the fraction of the surface covered by anything, living or ",
               "residue, over the window from the previous crop's harvest to ",
               "this season's planting. The endmembers come from this ",
               "library's own pixels, so it is comparable between these fields ",
               "but is not a validated cover percentage. It fills ",
               "automatically for pre-computed fields; for a new upload, run ",
               "the Soil armor tab first."))),
    card(card_header("Take the whole session away"),
         card_body(fillable = FALSE,
           p(class = "mb-2",
             "One zip holding everything above: the charts as images, every ",
             "table as CSV, the raw per-date measurements behind them, the ",
             "field boundary, and a written briefing. It is built to be ",
             "uploaded to an AI assistant and turned into a slide deck or a ",
             "short report — the briefing tells the assistant what each number ",
             "means and, more to the point, what it is ",
             tags$strong("not"), " allowed to claim from it."),
           downloadButton("dl_bundle", "Download report pack (ZIP)",
                          class = "btn-primary"),
           div(class = "text-muted small mt-2",
               "Takes a few seconds to build. Charts from tabs you have not ",
               "run are left out rather than shipped blank — run every tab ",
               "first for the full set."))),
    card(card_header("Method and limits"), uiOutput("method_note"))
  )
)

# ------------------------------------------------------------------- server ---

server <- function(input, output, session) {

  # Every analysis-dependent output routes through this so an un-run app shows
  # an instruction rather than a blank card.
  need_run <- function(x, what = "analysis") {
    validate(need(!is.null(x) && (!is.data.frame(x) || nrow(x) > 0),
                  sprintf("Press “Run analysis” to build the %s for this field.", what)))
  }

  rv <- reactiveValues(field = NULL, ts = NULL, phen = NULL, cc = NULL,
                       hist = NULL, avail = NULL, cdlst = NULL, cdladv = NULL,
                       msg = NULL, pick = NULL, grid_tick = 0L, residue_tick = 0L)

  # Re-rendered rather than static so the loaded field shows as the active
  # tile, including when an upload clears the highlight.

  #' Load one boundary and drop whatever the last one produced.
  #'
  #' Results belong to a field; leaving the previous field's numbers on screen
  #' under a new field's name is worse than showing nothing.
  # Every path into the app -- example tile, upload, drawing -- ends here, so
  # this is the one place the single-field rule has to hold.
  set_field <- function(f, pick = NULL) {
    one <- try(single_field(f), silent = TRUE)
    if (inherits(one, "try-error")) {
      showModal(modalDialog(
        title = "One field at a time",
        div(class = "alert alert-warning", role = "alert",
            conditionMessage(attr(one, "condition"))),
        easyClose = TRUE, footer = modalButton("Close")))
      return(invisible(FALSE))
    }
    dropped <- attr(one, "dropped") %||% 0L
    f <- one
    rv$field <- f
    rv$pick  <- pick
    rv$ts <- rv$phen <- rv$cc <- rv$hist <- rv$avail <- NULL
    rv$cdlst <- rv$cdladv <- NULL
    rv$msg <- if (dropped > 0L) {
      sprintf(paste0("Boundary reduced to its one substantive field; %d ",
                     "sliver(s) under %.2f ha were dropped."),
              dropped, FIELD_SLIVER_HA)
    } else NULL
    clear_drawings()
    try_cached(f)
    invisible(TRUE)
  }

  # Leaflet.draw owns its shapes, so the only way to remove them from R is to
  # take the toolbar away with clearFeatures and put it straight back.
  clear_drawings <- function() {
    leafletProxy("map") |>
      leaflet.extras::removeDrawToolbar(clearFeatures = TRUE) |>
      leaflet.extras::addDrawToolbar(
        polylineOptions = FALSE, circleOptions = FALSE,
        markerOptions = FALSE, circleMarkerOptions = FALSE,
        editOptions = FALSE,
        polygonOptions = leaflet.extras::drawPolygonOptions(
          shapeOptions = leaflet.extras::drawShapeOptions(
            color = "#31c4b0", weight = 3, fillOpacity = 0.15)),
        rectangleOptions = leaflet.extras::drawRectangleOptions(
          shapeOptions = leaflet.extras::drawShapeOptions(
            color = "#31c4b0", weight = 3, fillOpacity = 0.15)))
  }

  # Shown only when there is something to clear.
  output$field_gallery_ui <- renderUI({
    field_gallery(EXAMPLE_FIELDS, rv$pick, input$gallery_q %||% "")
  })

  output$gallery_header <- renderUI({
    n <- nrow(EXAMPLE_FIELDS)
    q <- input$gallery_q %||% ""
    shown <- if (nzchar(q)) {
      hay <- tolower(paste(EXAMPLE_FIELDS$label, EXAMPLE_FIELDS$crops,
                           EXAMPLE_FIELDS$shows))
      w <- strsplit(tolower(trimws(q)), " ", fixed = TRUE)[[1]]
      w <- w[nzchar(w)]
      sum(Reduce(`&`, lapply(w, function(x) grepl(x, hay, fixed = TRUE))))
    } else n
    tags$span("Field library",
              tags$span(class = "text-muted small ms-2",
                        if (shown == n) sprintf("%d fields", n)
                        else sprintf("%d of %d", shown, n)))
  })

  # The sidebar no longer lists the library -- it says what is loaded and points
  # at where to change it, which is all it needs at this width.
  output$current_field <- renderUI({
    if (is.null(rv$field)) {
      div(class = "text-muted small",
          tags$strong("No field loaded."), tags$br(),
          "Pick one from the library on the ", tags$strong("Field"),
          " tab, upload a boundary, or draw one on the map.")
    } else {
      lab <- EXAMPLE_FIELDS$label[match(rv$pick, EXAMPLE_FIELDS$stem)]
      div(class = "small",
          div(class = "text-muted", "Loaded"),
          tags$strong(if (length(lab) && !is.na(lab)) lab else "Your boundary"),
          div(class = "text-muted mt-1",
              sprintf("%.1f ha", sum(rv$field$area_ha))),
          div(class = "text-muted mt-1",
              "Change it in the library on the ", tags$strong("Field"), " tab."))
    }
  })

  output$clear_ui <- renderUI({
    req(rv$field)
    tagList(
      downloadButton("dl_boundary", "Download boundary (GeoJSON)",
                     class = "btn-outline-secondary btn-sm w-100"),
      div(class = "mt-2",
          actionButton("clear_field", "Clear field",
                       class = "btn-outline-secondary btn-sm w-100"))
    )
  })

  observeEvent(input$clear_field, {
    rv$field <- rv$pick <- NULL
    rv$ts <- rv$phen <- rv$cc <- rv$hist <- rv$avail <- NULL
    rv$cdlst <- rv$cdladv <- rv$msg <- NULL
    rv$draw_field <- rv$draw_st <- rv$draw_adv <- NULL
    clear_drawings()
  })

  # Dismissing the confirmation without using the drawing has to remove it, or
  # the next attempt leaves two shapes on the map.
  observeEvent(input$draw_discard, {
    removeModal()
    rv$draw_field <- rv$draw_st <- rv$draw_adv <- NULL
    clear_drawings()
  })

  # Nothing is loaded at startup. Opening on a preloaded Iowa field made the
  # app look like it had already answered a question nobody asked, and the
  # first thing a visitor did was work out how to get rid of it.

  # One input for all eleven tiles -- they set example_pick from the browser
  # rather than each being an actionButton with its own observer.
  observeEvent(input$example_pick, {
    i <- match(input$example_pick, EXAMPLE_FIELDS$stem)
    req(!is.na(i))
    f <- try(load_field(EXAMPLE_FIELDS$path[i]), silent = TRUE)
    if (inherits(f, "try-error")) {
      showNotification("Could not load that example field.", type = "error")
      return()
    }
    set_field(f, EXAMPLE_FIELDS$stem[i])
  })

  observeEvent(input$boundary, {
    f <- try(read_upload(input$boundary), silent = TRUE)
    if (inherits(f, "try-error")) {
      showNotification(paste("Could not read boundary:", conditionMessage(attr(f, "condition"))),
                       type = "error", duration = 10)
      return()
    }
    # An uploaded boundary can already be in the cache -- the demo library
    # fields are ordinary GeoJSON, and the key is the geometry, not the path.
    # pick = NULL clears the tile highlight: what is loaded is the upload now,
    # even if it happens to be a copy of one of the examples.
    hit <- set_field(f, NULL)
    showNotification(
      sprintf("Loaded %d field(s), %.1f ha.%s", nrow(f), sum(f$area_ha),
              if (isTRUE(hit)) " Cached results restored." else " Press Run analysis."),
      type = "message")
  })

  # ---- the analysis run ----------------------------------------------------

  # One code path, two callers: the button computes, and selecting a field tries
  # the same thing with only_cached = TRUE. Keeping them in one function is what
  # guarantees the pre-warmed library is keyed identically to what the button
  # would produce -- otherwise a warmed field would silently miss and re-read.
  run_analysis <- function(field, years, only_cached = FALSE, stage = NULL) {
    st <- function(a, b) if (is.null(stage)) NULL else stage(a, b)
    win <- analysis_window(years[1], years[2])
    yrs <- years[1]:min(years[2], as.integer(format(Sys.Date(), "%Y")) - 1)

    avail <- catalog_availability(field, win$start, win$end,
                                  only_cached = only_cached, progress = st(0.02, 0.15))
    if (only_cached && is.null(avail)) return(NULL)

    cdlst <- if (length(yrs) > 0) {
      cdl_stack(field, yrs, only_cached = only_cached, progress = st(0.15, 0.30))
    } else NULL
    if (only_cached && length(yrs) > 0 && is.null(cdlst)) return(NULL)

    ts <- extract_field_series(field, win$start, win$end, indices = "ndvi",
                               workers = 8, only_cached = only_cached,
                               progress = st(0.30, 0.90))
    if (is.null(ts)) return(NULL)

    hist  <- if (is.null(cdlst)) NULL else cdl_history_from_stack(cdlst)
    crops <- if (is.null(hist)) NULL else crop_lookup(hist)
    phen  <- phenology_all_years(ts, crops)
    cc    <- cover_crop_all_years(ts, phen, crops)
    adv   <- if (is.null(cdlst)) NULL else
               tryCatch(cdl_split_advice(cdlst), error = function(e) NULL)

    list(avail = avail, cdlst = cdlst, hist = hist, cdladv = adv,
         ts = ts, phen = phen, cc = cc)
  }

  apply_result <- function(res, note) {
    rv$avail <- res$avail; rv$cdlst <- res$cdlst; rv$hist <- res$hist
    rv$cdladv <- res$cdladv; rv$ts <- res$ts; rv$phen <- res$phen; rv$cc <- res$cc
    rv$msg <- sprintf("%d observations, %d seasons.%s",
                      nrow(res$ts), if (is.null(res$phen)) 0 else nrow(res$phen),
                      if (nzchar(note)) paste0(" ", note) else "")
  }

  # Selecting a field opens it straight away when the library has been warmed.
  # Silent on a miss: the field still loads, the user just presses Run.
  try_cached <- function(field) {
    yrs <- isolate(input$years)
    if (is.null(field) || is.null(yrs)) return(FALSE)
    res <- tryCatch(run_analysis(field, yrs, only_cached = TRUE),
                    error = function(e) NULL)
    if (is.null(res)) return(FALSE)
    apply_result(res, "Loaded from cache.")
    TRUE
  }

  # Results belong to a year range. Moving the slider invalidates them, so drop
  # what is on screen rather than leave 2020-2026 numbers under a 2022-2024
  # label, and try the cache again in case that range happens to be warmed too.
  observeEvent(input$years, {
    req(rv$field)
    rv$ts <- rv$phen <- rv$cc <- rv$hist <- rv$avail <- NULL
    rv$cdlst <- rv$cdladv <- NULL
    rv$msg <- NULL
    try_cached(rv$field)
  }, ignoreInit = TRUE)

  observeEvent(input$run, {
    req(rv$field)
    withProgress(message = "Analysing field", value = 0, {
      # Each stage owns a slice of the 0-1 bar, so the sub-progress from a
      # long-running stage maps into its own band rather than restarting.
      stage <- function(from, to) {
        function(done, total, msg) {
          setProgress(value = from + (to - from) * min(1, done / max(total, 1)),
                      detail = msg)
        }
      }
      res <- run_analysis(rv$field, input$years, only_cached = FALSE, stage = stage)
      setProgress(1, detail = "Done")
      apply_result(res, "")
    })
    showNotification("Analysis complete.", type = "message")
  })

  output$status <- renderUI({
    if (is.null(rv$field)) return(div(class = "text-muted small", "No field loaded."))
    tagList(
      div(class = "small",
          strong(sprintf("%.1f ha", sum(rv$field$area_ha))), br(),
          if (!is.null(rv$msg)) span(class = "text-success", rv$msg)
          else span(class = "text-muted", "Press Run analysis.")
      )
    )
  })

  # ---- 1. field ------------------------------------------------------------

  output$map <- renderLeaflet({
    # Renders with no field too, so the draw tool is usable the moment the app
    # opens rather than only after something has been loaded.
    base <- if (is.null(rv$field)) {
      leaflet::leaflet() |>
        basemap_hybrid() |>
        leaflet::setView(-96.5, 39.5, zoom = 4)
    } else {
      preview_field(rv$field)
    }
    # Polygon and rectangle only. The other shapes leaflet.extras offers -- a
    # circle, a marker -- are not boundaries, and edit/remove controls act on
    # the displayed field layer, which is not the drawing.
    base |>
      leaflet.extras::addDrawToolbar(
        polylineOptions = FALSE, circleOptions = FALSE,
        markerOptions = FALSE, circleMarkerOptions = FALSE,
        editOptions = FALSE,
        polygonOptions = leaflet.extras::drawPolygonOptions(
          shapeOptions = leaflet.extras::drawShapeOptions(
            color = "#31c4b0", weight = 3, fillOpacity = 0.15)),
        rectangleOptions = leaflet.extras::drawRectangleOptions(
          shapeOptions = leaflet.extras::drawShapeOptions(
            color = "#31c4b0", weight = 3, fillOpacity = 0.15)))
  })

  # ---- drawn boundaries ------------------------------------------------------
  #
  # Reading CDL for a drawn polygon is well under a second from the local store,
  # while the full pipeline is one to three minutes. So the crop history is
  # fetched and shown first, and the expensive read waits for a confirmation.
  # See R/draw.R for why a traced boundary in particular earns this check.
  observeEvent(input$map_draw_new_feature, {
    aoi <- drawn_to_sf(input$map_draw_new_feature)
    bad <- drawn_problem(aoi)
    if (!is.null(bad)) {
      showModal(modalDialog(
        title = "That boundary will not work",
        div(class = "alert alert-warning", role = "alert", bad),
        easyClose = TRUE, footer = modalButton("Close")))
      return()
    }

    rv$draw_field <- aoi
    rv$draw_st <- rv$draw_adv <- NULL

    st <- withProgress(
      message = "Reading crop history for the drawn boundary...", value = 0.5,
      tryCatch(cdl_stack(aoi, seq(input$years[1], min(input$years[2],
                                  as.integer(format(Sys.Date(), "%Y")) - 1L))),
               error = function(e) e))

    if (inherits(st, "error")) {
      showModal(modalDialog(
        title = "Could not read crop history",
        div(class = "alert alert-warning", role = "alert",
            conditionMessage(st)),
        easyClose = TRUE, footer = modalButton("Close")))
      return()
    }

    rv$draw_st  <- st
    rv$draw_adv <- tryCatch(cdl_split_advice(st), error = function(e) NULL)
    showModal(draw_modal(aoi, rv$draw_adv))
  })

  # The verdict text and the maps are rendered into the modal, so they update
  # with each new drawing rather than being baked into the dialog when it opens.
  output$draw_verdict <- renderUI({
    req(rv$draw_adv)
    v <- drawn_verdict(rv$draw_adv$per_year)
    cls <- switch(v$level, good = "alert alert-success",
                  fair = "alert alert-warning", "alert alert-warning")
    div(class = cls, role = "alert",
        h5(class = "alert-heading mb-2", v$headline),
        p(class = "mb-0 small", v$detail))
  })

  output$draw_matrix <- renderPlot({
    req(rv$draw_st)
    plot_cdl_matrix(rv$draw_st)
  })

  observeEvent(input$draw_confirm, {
    removeModal()
    req(rv$draw_field)
    # No attempt to hand the already-read stack over to the CDL tab. set_field()
    # clears that state deliberately, and working around it meant the tab could
    # be populated from one boundary while rv$field held another. Re-reading CDL
    # from the local store costs about half a second -- it was only ever worth
    # optimising when that meant a CropScape round trip.
    set_field(rv$draw_field, NULL)
  })

  output$field_stats <- renderUI({
    req(rv$field)
    f <- rv$field
    bb <- round(as.numeric(sf::st_bbox(f)), 5)
    div(class = "p-3",
        # Responsive: four across on a wide screen, two on a laptop, one on a
        # phone. Fixed quarter-widths wrap the numbers mid-word when the
        # sidebar is open on a smaller display.
        layout_columns(
          col_widths = breakpoints(sm = 6, md = 6, lg = 3),
          value_box(title = "Area", value = sprintf("%.1f ha", sum(f$area_ha)),
                    theme = "primary"),
          value_box(title = "Fields", value = as.character(nrow(f))),
          value_box(title = "Clear obs.",
                    value = if (is.null(rv$ts)) "--" else as.character(nrow(rv$ts))),
          value_box(title = "Seasons",
                    value = if (is.null(rv$phen)) "--" else as.character(nrow(rv$phen)))
        ),
        p(class = "text-muted small mt-2",
          sprintf("Bounding box: %.5f, %.5f to %.5f, %.5f", bb[1], bb[2], bb[3], bb[4])))
  })

  output$tbl_rotation <- renderDT({
    need_run(rv$hist, "crop rotation")
    dt_dl(rv$hist[, c("year", "crop", "pct", "n_classes")],
          filename = dl_name("crop-rotation"),
              colnames = c("Year", "Dominant crop", "% of field", "Classes present"),
              rownames = FALSE, options = list(dom = "t", pageLength = 10))
  })

  # ---- 2. CDL --------------------------------------------------------------

  output$cdl_advice <- renderUI({
    need_run(rv$cdladv, "CDL boundary check")
    a <- rv$cdladv
    cls <- switch(a$verdict,
                  split = "alert alert-warning",
                  trim  = "alert alert-warning",
                  "alert alert-success")
    div(
      div(class = cls, role = "alert",
          h5(class = "alert-heading mb-2", a$headline),
          p(class = "mb-0 small", a$detail)),
      if (!is.null(a$flag_classes) && nrow(a$flag_classes)) {
        div(class = "text-muted small mb-3",
            strong("What is in the flagged area: "),
            paste(sprintf("%s %.0f%%", a$flag_classes$crop, a$flag_classes$pct)[
              seq_len(min(4, nrow(a$flag_classes)))], collapse = ", "))
      }
    )
  })

  output$tbl_cdl_year <- renderDT({
    need_run(rv$cdladv, "CDL boundary check")
    p <- rv$cdladv$per_year
    dt_dl(
      filename = dl_name("cdl-by-year"),
      data.frame(Year = p$year, `Dominant crop` = p$dominant,
                 `% of field` = p$pct, `Classes present` = p$n_classes,
                 `Non-crop %` = round(p$noncrop_pct, 1), check.names = FALSE),
      rownames = FALSE, options = list(dom = "t", pageLength = 12))
  })

  output$cdl_matrix_ui <- renderUI({
    n  <- if (is.null(rv$cdlst)) 6 else terra::nlyr(rv$cdlst)
    nr <- ceiling(n / 3)
    plotOutput("plot_cdl_matrix", height = min(1300, 140 + nr * 300))
  })

  output$plot_cdl_matrix <- renderPlot({
    need_run(rv$cdlst, "CDL maps")
    plot_cdl_matrix(rv$cdlst)
  })

  output$plot_cdl_split <- renderPlot({
    need_run(rv$cdladv, "CDL boundary check")
    plot_cdl_split(rv$cdladv)
  })

  # ---- 3. availability -----------------------------------------------------

  output$plot_timeline <- renderPlot({
    need_run(rv$avail, "data availability timeline")
    plot_catalog_timeline(rv$avail)
  })

  output$tbl_catalog <- renderDT({
    need_run(rv$avail, "source summary")
    dt_dl(catalog_summary(rv$avail), rownames = FALSE,
          filename = dl_name("data-availability"),
              options = list(dom = "t", pageLength = 15))
  })

  output$source_notes <- renderUI({
    div(class = "p-3",
        tags$ul(lapply(CATALOG_SOURCES, function(s) {
          tags$li(strong(s$label),
                  sprintf(" (%s, %s, %s) -- ", s$kind, s$res, s$revisit),
                  s$note)
        })),
        p(class = "text-muted small",
          "All free and open. None requires an account."))
  })

  # ---- 4. imagery ----------------------------------------------------------

  # A plain reactive already memoises until its dependencies change. Writing the
  # result back into rv$ would make this read and write the same value, which
  # invalidates itself in a loop.
  #
  # One definition of the imagery query, used by the search and by the cost
  # indicator below. If these two ever disagreed the indicator would be
  # looking up a different cache entry than the button writes.
  img_window <- reactive({
    list(start = sprintf("%d-01-01", input$years[1]),
         end   = min(as.character(Sys.Date()),
                     sprintf("%d-12-31", input$years[2])))
  })

  scenes_r <- reactive({
    req(rv$field)
    w <- img_window()
    search_scenes(rv$field, w$start, w$end, max_cloud = IMG_MAX_CLOUD)
  })

  # What pressing "Show imagery" will actually cost, worked out without
  # touching the network.
  #
  # The catalogue is only read from disk, never queried: without the scene ids
  # there is no grid key to look up, so a field whose catalogue is not cached
  # yet just reports the general first-load wait. Opening this tab has to stay
  # free -- that is the whole reason the quarter dropdown is built from the
  # calendar rather than from a search.
  imagery_cost <- reactive({
    req(rv$field, input$period_key, input$view)
    rv$grid_tick                        # re-check after a sheet is written
    w  <- img_window()
    sc <- cache_get(scenes_cache_key(rv$field, w$start, w$end, IMG_MAX_CLOUD),
                    "scenes")
    if (is.null(sc)) return(list(state = "unknown"))
    idx <- scenes_in_period(list(table = sc$table), input$period_key, "quarter")
    if (!length(idx)) return(list(state = "empty"))
    list(state = if (grid_cached(rv$field, sc$table$id[idx], input$view))
                   "cached" else "cold",
         n = length(idx))
  })

  output$imagery_cost <- renderUI({
    st <- imagery_cost()
    tag <- function(cls, label, ...) {
      div(class = paste("alert imagery-timing py-2 px-3 mt-3 mb-0 small", cls),
          span(class = "imagery-timing-tag", label), ...)
    }
    switch(st$state,
      cached = tag("alert-success", "Already loaded",
                   "This quarter in this view is on disk — it opens ",
                   tags$strong("instantly"), "."),
      empty  = tag("alert-secondary", "Nothing to show",
                   "No Sentinel-2 passes in this quarter."),
      cold   = tag("alert-warning", "First load",
                   tags$strong(sprintf("%d scenes", st$n)),
                   " to read from the satellite archive — ",
                   tags$strong("up to 90 seconds"),
                   ". After that this quarter and view reopen instantly. ",
                   "Switching to another view reads it again, because true ",
                   "colour, false colour and NDVI use different bands."),
      tag("alert-warning", "First load",
          "Reading a quarter for the first time takes ",
          tags$strong("up to 90 seconds"),
          ". After that it reopens instantly. Switching to another view ",
          "reads it again, because true colour, false colour and NDVI use ",
          "different bands.")
    )
  })
  outputOptions(output, "imagery_cost", suspendWhenHidden = FALSE)

  # Periods come from the calendar, not from a scene search. Deriving them from
  # the catalogue would make the dropdown wait on a query covering every year,
  # and would leave it empty on a tab Shiny had not rendered yet. A period with
  # no usable scenes simply says so when you pick it.
  output$period_picker <- renderUI({
    from <- as.Date(sprintf("%d-01-01", input$years[1]))
    to   <- min(Sys.Date(), as.Date(sprintf("%d-12-31", input$years[2])))
    mons <- seq(from, to, by = "month")
    ps <- rev(unique(sprintf("%s-Q%d", format(mons, "%Y"),
                             (as.integer(format(mons, "%m")) - 1) %/% 3 + 1)))
    selectInput("period_key", "Quarter", choices = ps, selected = ps[1],
                width = "100%")
  })
  # This one is cheap and every other output in the tab depends on it, so it
  # must not sit suspended waiting for the tab to be looked at.
  outputOptions(output, "period_picker", suspendWhenHidden = FALSE)

  # Gated on the button. A quarter is 20-30 scene reads, so firing on every
  # change of the quarter or the view would start work the user had not asked
  # for and could not cancel.
  grid_r <- eventReactive(input$show_imagery, {
    req(input$period_key, input$view)
    sc  <- scenes_r()
    idx <- scenes_in_period(sc, input$period_key, "quarter")
    validate(need(length(idx) > 0,
                  sprintf("No usable scenes in %s -- every pass was too cloudy, or the quarter is outside the archive.",
                          input$period_key)))

    withProgress(message = "Loading scenes", value = 0, {
      list(
        g      = scene_grid(sc, idx, view = input$view, workers = 6,
                            progress = function(d, t, m) {
                              setProgress(value = min(1, d / max(t, 1)), detail = m)
                            }),
        view   = input$view,
        period = input$period_key
      )
    })
  })

  # A freshly read sheet is now on disk, so the cost indicator has to look
  # again -- otherwise it keeps saying "up to 90 seconds" for a quarter that
  # will now open instantly.
  observeEvent(grid_r(), { rv$grid_tick <- rv$grid_tick + 1L })

  # Height has to follow the number of rows, otherwise a 30-scene quarter is
  # squeezed into the same box as a 4-scene one.
  output$grid_ui <- renderUI({
    if (input$show_imagery == 0) {
      return(div(class = "text-muted p-4",
                 "Pick a quarter and a view, then press ",
                 strong("Show imagery"), "."))
    }
    res <- grid_r()
    nc  <- min(6, max(1, ceiling(sqrt(length(res$g)) * 1.3)))
    nr  <- ceiling(length(res$g) / nc)
    plotOutput("plot_grid", height = min(1600, 90 + nr * 210))
  })

  output$plot_grid <- renderPlot({
    res <- grid_r()
    lbl <- c(rgb = "True colour", fc = "False colour (NIR)", ndvi = "NDVI",
             armor = "Soil armor (1 - bare soil)")[res$view]
    plot_scene_grid(res$g, res$view,
                    title = sprintf("%s  |  %s", lbl, res$period))
  })

  # ---- 5. season -----------------------------------------------------------

  output$year_picker <- renderUI({
    req(rv$phen)
    if (!identical(input$phen_view, "one")) return(NULL)
    selectInput("phen_year", "Season", choices = rv$phen$year,
                selected = max(rv$phen$year), width = "200px")
  })

  output$phen_ui <- renderUI({
    n <- if (is.null(rv$phen)) 1 else nrow(rv$phen)
    h <- switch(input$phen_view %||% "split",
                split = min(900, 260 * min(3, ceiling(n / 3))),
                all   = 380,
                420)
    plotOutput("plot_phen", height = h)
  })

  output$plot_phen <- renderPlot({
    need_run(rv$phen, "season analysis")
    req(rv$ts)
    switch(input$phen_view %||% "split",
      split = plot_phenology_timeline(rv$ts, rv$phen, panels = 2),
      all   = plot_phenology_timeline(rv$ts, rv$phen, panels = 1),
      {
        req(input$phen_year)
        y   <- as.integer(input$phen_year)
        row <- rv$phen[rv$phen$year == y, ]
        plot_phenology(rv$ts, y, phen = row,
                       crop = if (nrow(row)) row$crop else NULL)
      }
    )
  })

  output$tbl_phen <- renderDT({
    need_run(rv$phen, "season markers")
    p <- rv$phen
    out <- data.frame(
      Year = p$year, Crop = p$crop,
      Planting = fmt_win(p$planting_est, p$planting_lo, p$planting_hi),
      `Peak NDVI` = sprintf("%.2f (%s)", p$peak_ndvi, format(p$peak_date, "%d %b")),
      Harvest = fmt_win(p$harvest_est, p$harvest_lo, p$harvest_hi),
      `Season (days)` = p$season_days,
      Confidence = p$confidence,
      check.names = FALSE
    )
    dt_dl(out, rownames = FALSE, filename = dl_name("season-markers"),
          options = list(dom = "t", pageLength = 10))
  })

  # ---- 6. cover crops ------------------------------------------------------

  output$cc_ui <- renderUI({
    n  <- if (is.null(rv$cc)) 1 else nrow(rv$cc)
    nc <- min(3, max(1, n))
    nr <- ceiling(n / nc)
    plotOutput("plot_cc", height = min(1200, 60 + nr * 250))
  })

  output$plot_cc <- renderPlot({
    need_run(rv$cc, "cover crop assessment")
    req(rv$ts)
    plot_cover_crop_matrix(rv$ts, rv$cc)
  })

  output$tbl_cc <- renderDT({
    need_run(rv$cc, "cover crop assessment")
    c1 <- rv$cc
    dt_dl(
      filename = dl_name("cover-crops"),
      data.frame(Winter = c1$winter, `Clear obs` = c1$n_obs,
                 `Max NDVI` = c1$max_ndvi, `Green days` = c1$green_days,
                 Verdict = c1$verdict, check.names = FALSE),
      rownames = FALSE, options = list(dom = "t", pageLength = 10))
  })

  # ---- 7. soil armor -------------------------------------------------------

  # Its own extraction over its own bands, so like the Imagery tab it is gated
  # on a button rather than riding along with Run analysis. The warmed demo
  # library covers it, so for those fields this returns straight away.
  residue_r <- eventReactive(input$run_residue, {
    req(rv$field, rv$phen)
    yrs <- isolate(input$years)
    withProgress(message = "Reading shortwave infrared", value = 0, {
      ts <- armor_series(rv$field, yrs, workers = 8,
                           progress = function(d, t, m) {
                             setProgress(value = min(1, d / max(t, 1)), detail = m)
                           })
      validate(need(!is.null(ts), "No spring imagery found for this field."))
      list(ts = ts, res = armor_all_years(ts, rv$phen, "spring"))
    })
  })

  # Same idea as the Imagery tab's notice: say what it will cost before it is
  # pressed, computed from the cache rather than guessed.
  output$residue_cost <- renderUI({
    req(rv$field)
    warm <- !is.null(tryCatch(armor_series(rv$field, input$years, only_cached = TRUE),
                              error = function(e) NULL))
    if (warm) {
      div(class = "alert alert-success imagery-timing py-2 px-3 mb-0 small",
          span(class = "imagery-timing-tag", "Already loaded"),
          "The shortwave series for this field is cached — it runs ",
          tags$strong("instantly"), ".")
    } else {
      div(class = "alert alert-warning imagery-timing py-2 px-3 mb-0 small",
          span(class = "imagery-timing-tag", "First load"),
          "Not read yet. This is a second pass over the archive on four bands ",
          "and takes ", tags$strong("a few minutes"), " for a field this size. ",
          "It is cached afterwards.")
    }
  })
  outputOptions(output, "residue_cost", suspendWhenHidden = FALSE)

  output$residue_ui <- renderUI({
    if (input$run_residue == 0) {
      return(div(class = "text-muted p-4",
                 "Press ", strong("Run soil armor analysis"), " to read the ",
                 "shortwave infrared for this field."))
    }
    r <- residue_r()$res
    n  <- if (is.null(r)) 1 else nrow(r)
    nc <- min(4, max(1, n)); nr <- ceiling(n / nc)
    plotOutput("plot_armor", height = min(1200, 60 + nr * 240))
  })

  # A run writes the shortwave series to disk, so the Summary's cache-only
  # lookup has something to find. Without this nudge the column would stay
  # blank until the field or year range changed.
  observeEvent(residue_r(), { rv$residue_tick <- rv$residue_tick + 1L })

  output$plot_armor <- renderPlot({
    x <- residue_r()
    validate(need(!is.null(x$res), "No season had a readable residue window."))
    plot_armor(x$ts, x$res, rv$phen)
  })

  output$tbl_residue <- renderDT({
    if (input$run_residue == 0) {
      # DT::datatable directly: a CSV of the words "Press Run soil armor
      # analysis" is not something anyone wants a button for.
      return(DT::datatable(data.frame(` ` = "Press Run soil armor analysis.",
                                  check.names = FALSE),
                       rownames = FALSE, options = list(dom = "t")))
    }
    r <- residue_r()$res
    validate(need(!is.null(r), "No season had a readable residue window."))
    # Insights carries the provisional band first, then whatever qualifies it.
    # The band is the same cut the plot draws, so putting it here is not a new
    # claim -- but the wording keeps "provisional" attached to it, because a
    # bare word in a table column is exactly the thing that gets quoted out of
    # context.
    band <- as.character(armor_band(r$armor))
    lead <- ifelse(is.na(r$armor), "", sprintf("Provisional: %s.", band))
    insight <- trimws(paste(lead, ifelse(is.na(r$note), "", r$note)))

    dt_dl(
      filename = dl_name("soil-armor"),
      data.frame(
        Year = r$year,
        Window = ifelse(is.na(r$window_start), "—",
                        sprintf("%s to %s", format(r$window_start, "%d %b"),
                                format(r$window_end, "%d %b"))),
        `Clear obs` = r$n_obs,
        `Soil armor` = r$armor,
        `Range` = ifelse(is.na(r$armor), "",
                         sprintf("%.2f–%.2f", r$armor_lo, r$armor_hi)),
        `Living` = r$f_pv,
        `Residue` = r$f_npv,
        `Bare` = r$f_bs,
        Insights = insight,
        check.names = FALSE),
      rownames = FALSE, options = list(dom = "t", pageLength = 12))
  })

  # ---- 8. summary ----------------------------------------------------------

  # Read from cache only, so a pre-warmed field fills the Summary column with no
  # button press -- and an unwarmed one leaves it blank rather than starting a
  # second pass over the archive behind the user's back.
  residue_cached <- reactive({
    req(rv$field, rv$phen)
    rv$residue_tick
    ts <- tryCatch(armor_series(rv$field, input$years, only_cached = TRUE),
                   error = function(e) NULL)
    if (is.null(ts)) return(NULL)
    tryCatch(armor_all_years(ts, rv$phen, "spring"), error = function(e) NULL)
  })

  summary_tbl <- reactive({
    need_run(rv$phen, "summary")
    p <- rv$phen
    cc <- rv$cc
    res <- residue_cached()
    data.frame(
      Year = p$year,
      Crop = p$crop,
      `Planting (est.)` = format(p$planting_est, "%d %b"),
      `Harvest (est.)`  = format(p$harvest_est, "%d %b"),
      `Season (days)`   = p$season_days,
      `Peak NDVI`       = p$peak_ndvi,
      `Following winter` = vapply(p$year, function(y) {
        if (is.null(cc)) return(NA_character_)
        r <- cc[cc$fall_year == y, ]
        if (!nrow(r)) NA_character_ else r$verdict
      }, character(1)),
      # Deliberately labelled "before planting": the window that produced this
      # runs from the PREVIOUS crop's harvest to this season's planting, so the
      # residue measured is last year's crop, not this one's. Dropping the
      # qualifier would invite reading it as what this season left behind.
      `Soil armor before planting (provisional)` = vapply(p$year, function(y) {
        # NA only means "not computed". Once residue HAS been computed, a year
        # with no row gets a reason rather than a blank, and the reason is
        # worked out rather than assumed: residue_summary() returns nothing
        # both when the window collapses and when nothing fell inside it.
        if (is.null(res)) return(NA_character_)
        r <- res[res$year == y, ]
        if (!nrow(r)) {
          w <- residue_window(p, y, "spring")
          return(if (is.null(w)) "no window" else "no usable observations")
        }
        # When there is no number, say which kind of nothing it is -- the
        # reason is already in the row, so read it rather than flattening
        # every case to "not readable".
        if (is.na(r$armor)) {
          return(if (!is.na(r$note) && grepl("^no window", r$note)) "no window"
                 else if (!is.na(r$note) && grepl("^only ", r$note)) "too few clear dates"
                 else "not readable")
        }
        sprintf("%s (%.2f)", as.character(armor_band(r$armor)), r$armor)
      }, character(1)),
      Confidence = p$confidence,
      check.names = FALSE
    )
  })

  output$tbl_summary <- renderDT({
    dt_dl(summary_tbl(), rownames = FALSE,
          filename = dl_name("field-summary"),
              options = list(dom = "t", pageLength = 15))
  })

  output$method_note <- renderUI({
    div(class = "p-3",
        p(strong("Imagery: "), "Sentinel-2 L2A surface reflectance at 10 m, read ",
          "from Microsoft Planetary Computer. Clouds, shadow and snow removed ",
          "with the scene classification band; scenes keeping less than 75% of ",
          "field pixels are dropped."),
        p(strong("Crop type: "), "USDA Cropland Data Layer, 30 m, the dominant ",
          "class inside the boundary."),
        p(strong("Planting: "), "inferred from where the smoothed NDVI curve ",
          "crosses 20% of its seasonal amplitude on the rising limb, offset by ",
          "a crop-specific lag. Good to about two weeks; the quoted window ",
          "widens automatically where cloud left a gap near the transition."),
        p(strong("Harvest: "), "the drop off the falling limb, measured against ",
          "the lowest point after the peak rather than against spring. Where ",
          "something green follows the cash crop -- a cover crop, or a ratoon ",
          "flush -- NDVI never returns to the spring floor, and a ",
          "spring-anchored threshold reports no harvest at all. A season still ",
          "under way is left blank rather than guessed."),
        p(strong("Cover crops: "), "off-season NDVI above the residue floor. ",
          "Evidence, not proof -- see the Cover crops tab."),
        p(class = "text-muted small",
          strong("Not yet calibrated. "),
          "Every threshold here is a literature-typical starting value. ",
          "Validating against fields with known planting dates and known cover ",
          "crop use is what would make these numbers defensible."))
  })

  # A drawn boundary exists nowhere else. The cache is keyed on geometry and
  # stores results, not the outline, so without this a field traced on the map
  # is gone the moment it is cleared.
  # Downloads are named for what they contain, which field they came from and
  # when. Every table arrived as "table.csv" before this, so three fields'
  # worth of crop rotations overwrote each other in the download folder -- and
  # the whole point of the library is comparing fields.
  dl_name <- function(what) {
    who <- rv$pick %||% "field"
    sprintf("%s_%s_%s", what, who, Sys.Date())
  }

  # Redraw a plot into a PNG at print size. The on-screen render is sized to
  # the browser; this is sized for a document, which is what people actually do
  # with a downloaded chart.
  dl_plot <- function(id, fn, w = 11, h = 7) {
    output[[paste0("dl_", id)]] <- downloadHandler(
      filename = function() paste0(dl_name(gsub("^plot_", "", id)), ".png"),
      content = function(file) {
        grDevices::png(file, width = w, height = h, units = "in", res = 150)
        on.exit(grDevices::dev.off(), add = TRUE)
        # A download requested before the analysis has run would otherwise
        # produce a corrupt zero-byte PNG. Say so in the image instead.
        ok <- tryCatch({ fn(); TRUE }, error = function(e) FALSE)
        if (!ok) {
          graphics::par(mar = c(0, 0, 0, 0))
          graphics::plot.new()
          graphics::text(0.5, 0.5, "Run the analysis first.", cex = 1.4,
                         col = "grey40")
        }
      })
  }

  # One definition per chart, used by both the per-chart PNG buttons and the
  # LLM bundle. Defined once because two copies of a plot expression drift, and
  # the bundle would then ship a figure the app never showed.
  PLOTS <- list(
    "cdl-maps-by-year" = list(
      fn = function() plot_cdl_matrix(rv$cdlst), w = 12, h = 9, id = "plot_cdl_matrix",
      cap = "One CDL crop map per year, clipped to the field. One color filling it every year means one management unit."),
    "boundary-disagreement" = list(
      fn = function() plot_cdl_split(rv$cdladv), w = 10, h = 8, id = "plot_cdl_split",
      cap = "Where the boundary disagrees with itself. Pale agrees every year; a persistent red block is a second field."),
    "data-availability" = list(
      fn = function() plot_catalog_timeline(rv$avail), w = 12, h = 7, id = "plot_timeline",
      cap = "Every satellite acquisition over this field, by source. Shows what exists, before cloud filtering."),
    "imagery-contact-sheet" = list(
      fn = function() {
        res <- grid_r()
        lbl <- c(rgb = "True colour", fc = "False colour (NIR)", ndvi = "NDVI",
                 armor = "Soil armor (1 - bare soil)")[res$view]
        plot_scene_grid(res$g, res$view, title = sprintf("%s  |  %s", lbl, res$period))
      }, w = 13, h = 10, id = "plot_grid",
      cap = "Every clear scene in one quarter. The visual proof that the numbers come from real imagery."),
    "season-markers" = list(
      fn = function() {
        switch(input$phen_view %||% "split",
               split = plot_phenology_timeline(rv$ts, rv$phen, panels = 2),
               all   = plot_phenology_timeline(rv$ts, rv$phen, panels = 1),
               plot_phenology(rv$ts, as.integer(input$phen_year), rv$phen))
      }, w = 13, h = 8, id = "plot_phen",
      cap = "NDVI through each season with estimated planting and harvest marked. The green-up and senescence curve."),
    "cover-crop-winters" = list(
      fn = function() plot_cover_crop_matrix(rv$ts, rv$cc), w = 13, h = 9, id = "plot_cc",
      cap = "Every winter on a shared Oct-to-Jun axis. A hump above the residue floor is off-season green cover."),
    "soil-armor-by-year" = list(
      fn = function() { x <- residue_r(); plot_armor(x$ts, x$res, rv$phen) },
      w = 14, h = 8, id = "plot_armor",
      cap = "Cover fractions through each calendar year. Teal is living, tan is residue, white to the top is bare soil. The shaded band is the pre-planting window the headline figure averages over.")
  )

  for (nm in names(PLOTS)) {
    local({
      spec <- PLOTS[[nm]]
      dl_plot(spec$id, spec$fn, spec$w, spec$h)
    })
  }

  output$dl_boundary <- downloadHandler(
    filename = function() {
      stem <- rv$pick %||% "drawn-field"
      sprintf("%s_%s.geojson", stem, Sys.Date())
    },
    content = function(file) {
      f <- rv$field
      # Keep only what another tool can use. area_ha is ours and recomputed on
      # load; anything else came off whatever file was uploaded.
      keep <- intersect(c("field_id", "area_ha"), names(f))
      f <- f[, keep, drop = FALSE]
      # GeoJSON is WGS84 by definition. load_field() already transforms to 4326,
      # but stating it here means a future change upstream cannot silently write
      # projected coordinates into a file that claims to be lon/lat.
      f <- sf::st_transform(f, 4326)
      # st_write will not overwrite, and Shiny has already created the temp file.
      unlink(file)
      sf::st_write(f, file, driver = "GeoJSON", quiet = TRUE)
    }
  )

  output$dl_summary <- downloadHandler(
    filename = function() sprintf("field_summary_%s.csv", Sys.Date()),
    content = function(file) {
      s <- try(summary_tbl(), silent = TRUE)
      if (inherits(s, "try-error")) s <- data.frame(note = "Run the analysis first.")
      utils::write.csv(s, file, row.names = FALSE)
    }
  )

  # ---- report pack ---------------------------------------------------------
  #
  # One zip holding everything this session learned about the field: the
  # figures, the derived tables, the raw per-date series, the boundary, and a
  # README that frames all of it. It is meant to be handed to a chat assistant
  # and turned into a deck or a short report for people who will never see this
  # app.
  #
  # The README leads with the limits rather than burying them. Give a model a
  # column of soil armor values and ask for a PowerPoint and it will write
  # "conservation tillage detected" -- the exact overstatement this project's
  # validation work exists to refuse. Putting the caveats inside the pack means
  # the warning travels with the numbers, to readers who were never part of the
  # conversation that produced them.

  # Markdown table from a data frame, or a line saying why there is not one.
  md_table <- function(d) {
    if (is.null(d) || !NROW(d)) return("_Not produced in this session._\n")
    d <- as.data.frame(d)
    cell <- function(x) {
      x <- if (inherits(x, "Date")) format(x, "%Y-%m-%d") else as.character(x)
      ifelse(is.na(x), "", trimws(x))
    }
    body <- do.call(paste, c(lapply(d, cell), sep = " | "))
    paste0("| ", paste(names(d), collapse = " | "), " |\n",
           "|", paste(rep("---", ncol(d)), collapse = "|"), "|\n",
           paste0("| ", body, " |", collapse = "\n"), "\n")
  }

  cols <- function(d, want) {
    if (is.null(d) || !NROW(d)) return(NULL)
    d[, intersect(want, names(d)), drop = FALSE]
  }

  # Cover fractions from the cache only, never starting a fresh pass over the
  # archive. residue_r() is an eventReactive and throws until its button has
  # been pressed; residue_cached() returns only the per-year summary, not the
  # series the armor figure needs. This returns both, for whatever is warm.
  armor_pack <- function() {
    req(rv$field)
    rv$residue_tick
    ts <- tryCatch(armor_series(rv$field, input$years, only_cached = TRUE),
                   error = function(e) NULL)
    if (is.null(ts) || is.null(rv$phen)) return(NULL)
    list(ts = ts,
         res = tryCatch(armor_all_years(ts, rv$phen, "spring"),
                        error = function(e) NULL))
  }

  # `drawn` is the figures that actually came out, passed in rather than
  # assumed. Listing all seven unconditionally told the assistant to place a
  # contact sheet that was not in the zip, which is precisely the kind of
  # confident wrongness the briefing above spends four rules trying to prevent.
  bundle_md <- function(drawn = names(PLOTS)) {
    i <- match(rv$pick %||% "", EXAMPLE_FIELDS$stem)
    name  <- if (!is.na(i)) EXAMPLE_FIELDS$label[i] else "Uploaded or drawn boundary"
    shows <- if (!is.na(i)) EXAMPLE_FIELDS$shows[i] else ""
    if (is.na(shows)) shows <- ""

    bb  <- as.numeric(sf::st_bbox(sf::st_transform(rv$field, 4326)))
    ctr <- sf::st_coordinates(
      sf::st_centroid(sf::st_union(sf::st_transform(rv$field, 4326))))
    win <- analysis_window(input$years[1], input$years[2])
    ap  <- armor_pack()

    figs <- if (!length(drawn)) {
      "_No figures in this pack — no tab was run far enough to draw one._"
    } else {
      paste(vapply(drawn, function(n)
        sprintf("- `figures/%s.png` — %s", n, PLOTS[[n]]$cap),
        character(1)), collapse = "\n")
    }
    skipped <- setdiff(names(PLOTS), drawn)

    paste0(
"# Field report pack: ", name, "

Generated ", format(Sys.Date(), "%d %B %Y"), " by the Field to Market remote
sensing demonstration pipeline. Everything in this pack is derived from free
public satellite imagery. There was no field visit and no grower input.

## If you are an AI assistant reading this, start here

You have been handed this pack to build a slide deck or a short report for a
**non-technical audience**. Four rules, and they are not optional.

1. **Soil armor is a cover metric, not a tillage metric.** It measures how much
   of the ground is covered by anything at all — living plants or crop residue.
   Do not describe it as detecting tillage, no-till, or conservation practice.
   Checked against 347 farmer-reported field-years, almost all of its apparent
   tillage signal ran through cover-crop adoption instead.
2. **Cover crop verdicts are evidence, not findings.** The thresholds are Corn
   Belt values and they read badly in the South — 7.1% specificity against
   Georgia ground truth. Present them as indications, never as fact.
3. **Planting and harvest dates have never been validated** against a grower
   record anywhere. Present them as estimates, and carry the uncertainty window
   that comes with them.
4. **Do not invent accuracy figures.** If a number is not in this pack, it does
   not exist. Say so rather than estimating one.

Lead with the figures. They are the point of this pack and they are what a
non-technical audience will actually read. The tables are here so you can
caption the figures accurately, not to be reproduced wholesale onto slides.

## The field

| | |
|---|---|
| Name | ", name, " |
| Area | ", sprintf("%.1f ha (%.0f acres)", sum(rv$field$area_ha),
                   sum(rv$field$area_ha) * 2.47105), " |
| Centroid (lon, lat) | ", sprintf("%.5f, %.5f", ctr[1], ctr[2]), " |
| Bounding box | ", sprintf("%.5f, %.5f to %.5f, %.5f",
                            bb[1], bb[2], bb[3], bb[4]), " |
| Analysis window | ", as.character(win$start), " to ",
                      as.character(win$end), " |
| Clear observations | ",
  if (is.null(rv$ts)) "—" else length(unique(rv$ts$date)), " |
",
if (nzchar(shows))
  paste0("\n**What this field was chosen to show.** ", shows, "\n") else "",
"
## Is this one field?

", if (is.null(rv$cdladv)) "_Boundary check not run in this session._\n" else
     paste0("**", rv$cdladv$headline, "**\n\n", rv$cdladv$detail, "\n"), "
This matters more than it sounds. Every number below averages a measurement
across whatever the boundary contains, so a boundary holding two fields
produces a season curve belonging to neither of them.

## Crop rotation

", md_table(rv$hist), "
## Season markers

", md_table(cols(rv$phen, c("year", "crop", "planting_est", "planting_lo",
                            "planting_hi", "harvest_est", "harvest_lo",
                            "harvest_hi", "season_days", "peak_ndvi",
                            "n_obs", "confidence"))), "
Planting and harvest are estimates from the shape of the NDVI curve. The `_lo`
and `_hi` columns are the uncertainty window, and they are set by how long the
gaps between clear images were — not by how confident the method is.

## Cover crop, winter by winter

", md_table(cols(rv$cc, c("winter", "n_obs", "max_ndvi", "mean_ndvi",
                          "green_days", "verdict", "notes"))), "
## Soil armor before planting

", md_table(cols(ap$res, c("year", "window_start", "window_end", "n_obs",
                           "armor", "armor_lo", "armor_hi", "f_pv", "f_npv",
                           "f_bs", "note"))), "
Armor is one minus the bare soil fraction. `f_pv` is living cover, `f_npv` is
crop residue, `f_bs` is bare ground, and the three sum to one. The window runs
from the previous crop's harvest to this season's planting, so the residue
being measured belongs to **last** year's crop, not the one named in the row.

## Figures

", figs, "

## The rest of the pack

- `figures/` — the charts above, PNG at print resolution
- `tables/` — the tables above, as CSV
- `series/` — the raw per-date measurements the tables were summarized from
- `boundary.geojson` — the field outline, WGS84

A figure or table missing from the pack is one the app never produced in this
session, usually because that tab was not run. It is not a failure of the field,
and it is not something to work around by describing the chart from the numbers.
",
if (length(skipped))
  paste0("\nNot produced this session, so do not refer to them: ",
         paste(sprintf("`%s`", skipped), collapse = ", "), ".\n") else "",
"
## Method and provenance

Sentinel-2 L2A surface reflectance from Microsoft Planetary Computer: 10 m
pixels, revisited about every five days, cloud-masked with the scene
classification layer. Crop type from the USDA Cropland Data Layer at 30 m.
Every formula and every constant is written up in `METHODS.md` in the source
repository, github.com/Field-to-Market/sandbox-remote-sensing-tool.

This is a demonstration pipeline, not production software, and the constants
behind soil armor were fitted on eleven fields. Treat every number here as
provisional.
")
  }

  output$dl_bundle <- downloadHandler(
    filename = function() paste0(dl_name("field-report-pack"), ".zip"),
    content = function(file) {
      req(rv$field)
      root <- file.path(tempdir(), paste0("pack_", as.integer(Sys.time())))
      for (d in c("figures", "tables", "series")) {
        dir.create(file.path(root, d), recursive = TRUE, showWarnings = FALSE)
      }
      ap <- armor_pack()

      withProgress(message = "Building the report pack", value = 0, {
        # The armor figure normally comes from residue_r(), which throws until
        # the Soil armor tab's button has been pressed. In the pack we would
        # rather draw it from the cache than leave it out, so a pre-warmed
        # field yields a complete pack without touring the tabs first.
        fallback <- list("soil-armor-by-year" = function() {
          if (is.null(ap)) stop("no cached cover fractions")
          plot_armor(ap$ts, ap$res, rv$phen)
        })

        n <- length(PLOTS)
        drawn <- character(0)
        for (nm in names(PLOTS)) {
          incProgress(0.65 / n, detail = nm)
          dest <- file.path(root, "figures", paste0(nm, ".png"))
          draw <- function(f) {
            grDevices::png(dest, width = PLOTS[[nm]]$w, height = PLOTS[[nm]]$h,
                           units = "in", res = 150)
            on.exit(grDevices::dev.off(), add = TRUE)
            tryCatch({ f(); TRUE }, error = function(e) FALSE)
          }
          ok <- draw(PLOTS[[nm]]$fn)
          if (!ok && !is.null(fallback[[nm]])) ok <- draw(fallback[[nm]])
          # A figure whose tab was never run writes a blank or part-drawn PNG.
          # Drop it, so the pack holds only output the app really produced.
          if (!ok) unlink(dest) else drawn <- c(drawn, nm)
        }

        # Written only when there is something in it: an empty CSV in the pack
        # reads as "we measured nothing", which is a different claim from "we
        # did not measure".
        wr <- function(d, sub, nm) {
          if (!is.null(d) && NROW(d)) {
            utils::write.csv(d, file.path(root, sub, paste0(nm, ".csv")),
                             row.names = FALSE)
          }
        }

        incProgress(0.15, detail = "tables")
        wr(rv$hist, "tables", "crop-rotation")
        wr(rv$phen, "tables", "season-markers")
        wr(rv$cc, "tables", "cover-crops")
        wr(ap$res, "tables", "soil-armor")
        wr(rv$cdladv$per_year, "tables", "cdl-by-year")
        wr(tryCatch(catalog_summary(rv$avail), error = function(e) NULL),
           "tables", "data-availability")
        wr(tryCatch(summary_tbl(), error = function(e) NULL),
           "tables", "field-summary")

        incProgress(0.1, detail = "raw series")
        wr(rv$ts, "series", "ndvi-by-date")
        wr(ap$ts, "series", "cover-fractions-by-date")
        wr(rv$avail, "series", "acquisitions-by-source")

        incProgress(0.1, detail = "boundary and briefing")
        b <- rv$field[, intersect(c("field_id", "area_ha"), names(rv$field)),
                      drop = FALSE]
        sf::st_write(sf::st_transform(b, 4326),
                     file.path(root, "boundary.geojson"),
                     driver = "GeoJSON", quiet = TRUE)
        # Byte-wise, so the em dashes in the briefing survive whatever the
        # native encoding happens to be on the machine running the app.
        con <- file(file.path(root, "README.md"), open = "wb")
        writeBin(charToRaw(enc2utf8(bundle_md(drawn))), con)
        close(con)

        # zip::zipr rather than utils::zip: utils::zip shells out to a zip
        # executable, and there is not one on a stock Windows R install.
        unlink(file)
        zip::zipr(file, list.files(root, full.names = TRUE), recurse = TRUE)
      })
    }
  )

}

# Format an estimate with its uncertainty window.
fmt_win <- function(est, lo, hi) {
  ifelse(is.na(est), "--",
         sprintf("%s  (%s - %s)", format(est, "%d %b"),
                 format(lo, "%d %b"), format(hi, "%d %b")))
}

shinyApp(ui, server)
