# ==============================================================================
# run_demo.R -- End-to-end walkthrough on one Iowa field.
#
#   source("run_demo.R")
#
# Swap FIELD for your own boundary file and rerun. Everything else works the
# same. Plots are written to outputs/.
# ==============================================================================

source("pipeline.R")

FIELD  <- file.path(FIELDS_DIR, "example_field.geojson")
YEAR   <- 2024
START  <- sprintf("%d-04-01", YEAR)
END    <- sprintf("%d-10-31", YEAR)

# ---- 1. The field -----------------------------------------------------------

message("\n[1] Field boundary")
field <- load_field(FIELD)
print(field[, c("field_id", "area_ha")])

# In RStudio, this opens an interactive satellite map:
#   preview_field(field)

# ---- 2. What crop is it? ----------------------------------------------------

message("\n[2] USDA Cropland Data Layer")
cdl <- get_cdl(field, YEAR)
print(cdl_summary(cdl))
message(sprintf("  Dominant crop: %s", dominant_crop(cdl)$crop))

save_plot("01_cdl.png", plot_cdl(cdl))

# ---- 3. Find imagery --------------------------------------------------------

message("\n[3] Sentinel-2 scene search")
scenes <- search_scenes(field, START, END, max_cloud = 40)
print(scenes)

# ---- 4. Look at one clear scene ---------------------------------------------

message("\n[4] Loading the clearest mid-season scene")

# Pick the least cloudy scene in July/August -- peak canopy for corn and soy.
mid <- scenes$table[format(scenes$table$date, "%m") %in% c("07", "08"), ]
pick <- if (nrow(mid)) mid$i[which.min(mid$cloud)] else which.min(scenes$table$cloud)

# clip = FALSE keeps the surroundings, so you can see the field in context.
img_ctx <- load_scene(scenes, pick, bands = c("blue", "green", "red", "nir"),
                      clip = FALSE, buffer_m = 600)
save_plot("02_rgb_context.png", {
  plot_rgb(img_ctx)
  add_field(field, img_ctx)
})
save_plot("03_false_colour.png", {
  plot_false_colour(img_ctx)
  add_field(field, img_ctx)
})

# Now clipped to the field for the actual analysis.
img <- load_scene(scenes, pick, bands = c("blue", "green", "red", "nir"))
message(sprintf("  Scene %s, %.0f%% of field pixels clear.",
                attr(img, "date"), valid_fraction(img) * 100))

# ---- 5. NDVI ----------------------------------------------------------------

message("\n[5] NDVI")
ndvi <- compute_index(img, "ndvi")
save_plot("04_ndvi.png", plot_index(ndvi))
save_plot("05_ndvi_hist.png", plot_index_hist(ndvi))

v <- values(ndvi); v <- v[!is.na(v)]
message(sprintf("  NDVI mean %.3f  sd %.3f  range %.3f-%.3f",
                mean(v), sd(v), min(v), max(v)))

# ---- 6. Compare several indices on the same day -----------------------------

message("\n[6] Comparing indices")
print(list_indices())

to_compare <- c("ndvi", "evi2", "savi", "gcvi")
img_multi  <- load_scene(scenes, pick, bands = bands_for(to_compare))

save_plot("06_index_comparison.png", {
  op <- par(mfrow = c(2, 2), mar = c(2, 2, 3, 4)); on.exit(par(op))
  for (nm in to_compare) plot_index(compute_index(img_multi, nm))
}, width = 1600, height = 1400)

# ---- 7. Season-long time series ---------------------------------------------

message("\n[7] NDVI time series across the season")
ts <- index_timeseries(scenes, index = "ndvi", min_valid = 0.8)
save_plot("07_ndvi_timeseries.png", plot_timeseries(ts))
save_timeseries(ts, "ndvi_timeseries.csv")

print(head(ts[, c("date", "mean", "sd", "valid_frac")], 10))

message("\nDone. See outputs/")
