"""fieldrs -- field-scale remote sensing from free, open imagery.

A Python port of the R pipeline in the parent directory. Same data sources,
same algorithms, same cache semantics; written to be lifted into a platform
rather than run as an app.

Typical use::

    from fieldrs import analyze_field
    result = analyze_field("field.geojson", years=(2020, 2026))
    print(result.summary)
"""

from .aoi import field_bounds, geometry_from_geojson, load_field, single_field
from .armor import (ARMOR_NA_COLOR, ARMOR_RAMP, ARMOR_RANGE, armor_all_years,
                    armor_band, armor_colors, armor_rgb, armor_series,
                    armor_summary, cover_fractions, veg_palette)
from .cache import analysis_window, cache_clear
from .catalog import catalog_availability, catalog_summary
from .climate import (field_centroid, gridmet_daily, rain_free_phenology,
                      weather_free_events, weather_free_phenology)
from .covercrop import cover_crop_all_years, detect_cover_crop
from .cdl_split import cdl_split_advice
from .cropland import cdl_history_from_stack, cdl_stack, cdl_summary, crop_lookup
from .extract import extract_field_series
from .imagery import (dedupe_scenes, pc_identify, read_scene, scene_groups,
                      search_scenes, stac_search_retry)
from .indices import add_index, bands_for, compute_index, list_indices
from .phenology import daily_series, estimate_phenology, phenology_all_years
from .pipeline import FieldResult, analyze_field, apply_rain_check

__all__ = [
    "analyze_field", "FieldResult", "apply_rain_check",
    "load_field", "field_bounds", "geometry_from_geojson", "single_field",
    "analysis_window", "cache_clear",
    "catalog_availability", "catalog_summary",
    "search_scenes", "stac_search_retry", "pc_identify",
    "dedupe_scenes", "scene_groups", "read_scene",
    "extract_field_series",
    "add_index", "bands_for", "compute_index", "list_indices",
    "cdl_stack", "cdl_summary", "cdl_history_from_stack", "crop_lookup",
    "cdl_split_advice",
    "daily_series", "estimate_phenology", "phenology_all_years",
    "detect_cover_crop", "cover_crop_all_years",
    "field_centroid", "gridmet_daily", "rain_free_phenology",
    "weather_free_events", "weather_free_phenology",
    "armor_series", "armor_summary", "armor_all_years", "armor_band",
    "cover_fractions",
    "armor_colors", "armor_rgb", "veg_palette",
    "ARMOR_RAMP", "ARMOR_RANGE", "ARMOR_NA_COLOR",
]

__version__ = "0.1.0"
