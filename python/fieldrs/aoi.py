"""Field boundaries: the "upload a field" step."""

from __future__ import annotations

import warnings
from pathlib import Path

import geopandas as gpd
from shapely.geometry import shape

# Equal-area projection for the conterminous US. Areas measured in lon/lat are
# meaningless, so every area figure goes through this.
EQUAL_AREA = 5070


def load_field(path: str | Path, id_col: str | None = None) -> gpd.GeoDataFrame:
    """Read a field boundary from any common vector format.

    Accepts GeoJSON, Shapefile, GeoPackage or KML, and always hands back
    polygons in EPSG:4326 with an ``area_ha`` column.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Boundary file not found: {path}")

    aoi = gpd.read_file(path)
    if len(aoi) == 0:
        raise ValueError(f"Boundary file contains no features: {path}")

    # KML and GPS exports often carry a Z dimension that breaks later geometry
    # operations. Drop it.
    if aoi.geometry.has_z.any():
        aoi["geometry"] = aoi.geometry.force_2d()

    if not aoi.geometry.is_valid.all():
        aoi["geometry"] = aoi.geometry.make_valid()

    kinds = set(aoi.geom_type)
    if not kinds <= {"Polygon", "MultiPolygon"}:
        raise ValueError(f"Boundary must be polygons, got: {', '.join(sorted(kinds))}")

    if aoi.crs is None:
        warnings.warn("Boundary has no CRS; assuming EPSG:4326 (lon/lat).")
        aoi = aoi.set_crs(4326)
    aoi = aoi.to_crs(4326)

    aoi["area_ha"] = aoi.to_crs(EQUAL_AREA).area / 1e4

    if id_col is not None:
        if id_col not in aoi.columns:
            raise ValueError(f"Column not found in boundary: {id_col}")
        aoi["field_id"] = aoi[id_col].astype(str)
    elif "field_id" not in aoi.columns:
        aoi["field_id"] = [f"field_{i:02d}" for i in range(1, len(aoi) + 1)]

    total = float(aoi["area_ha"].sum())
    if (aoi["area_ha"] < 1).any():
        warnings.warn(
            "Field under 1 ha. At Sentinel-2's 10 m pixels that is fewer than "
            "~100 pixels; treat the statistics with caution."
        )
    if (aoi["area_ha"] > 50000).any():
        warnings.warn("Field over 50,000 ha. Downloads will be slow.")

    aoi.attrs["area_ha"] = total
    return aoi


# What counts as a sliver rather than a field.
#
# Hand-drawn and exported boundaries routinely carry specks: a stray vertex, a
# donut left by a clip, a second ring a few square metres across. Those should
# be dropped silently. Two real fields in one boundary should not be, because
# everything downstream averages over whatever the boundary contains and two
# fields give a season curve belonging to neither.
FIELD_SLIVER_HA = 0.05      # absolute floor: below this is not a field
FIELD_SLIVER_FRAC = 0.005   # ...or under 0.5% of the largest part


def single_field(aoi: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Reduce a boundary to a single field, or refuse it.

    Splits multi-part geometry, drops slivers, and raises when more than one
    substantive field is left. Returns one row, with the number of dropped
    slivers in ``.attrs["dropped"]``.
    """
    if aoi is None or len(aoi) == 0:
        raise ValueError("Boundary is empty.")

    parts = aoi.copy()
    if not parts.geometry.is_valid.all():
        parts["geometry"] = parts.geometry.make_valid()
    parts = parts.explode(index_parts=False, ignore_index=True)
    parts = parts[parts.geom_type.isin(["Polygon", "MultiPolygon"])]
    if len(parts) == 0:
        raise ValueError("Boundary contains no polygons.")

    parts["area_ha"] = parts.to_crs(EQUAL_AREA).area / 1e4
    parts = parts.sort_values("area_ha", ascending=False).reset_index(drop=True)
    ha = parts["area_ha"].to_numpy()

    keep = ha >= max(FIELD_SLIVER_HA, FIELD_SLIVER_FRAC * ha[0])
    if int(keep.sum()) > 1:
        sizes = ", ".join(f"{v:.1f}" for v in ha[keep])
        raise ValueError(
            f"This boundary contains {int(keep.sum())} separate fields "
            f"({sizes} ha). Load one field at a time -- everything here "
            "averages over whatever the boundary contains, so two fields give "
            "a season curve belonging to neither."
        )

    out = parts.iloc[[0]].copy()
    out.attrs = dict(aoi.attrs)
    out.attrs["dropped"] = len(ha) - 1
    out.attrs["area_ha"] = float(ha[0])
    return out


def field_bounds(aoi: gpd.GeoDataFrame, buffer_m: float = 200) -> tuple[float, float, float, float]:
    """Buffered lon/lat bounding box, as ``(minx, miny, maxx, maxy)``.

    The buffer matters: without it the edge pixels of the field get clipped away.
    """
    buffered = aoi.to_crs(EQUAL_AREA).geometry.union_all().buffer(buffer_m)
    g = gpd.GeoSeries([buffered], crs=EQUAL_AREA).to_crs(4326)
    return tuple(float(v) for v in g.total_bounds)


def field_geometry(aoi: gpd.GeoDataFrame):
    """The boundary as a single dissolved shapely geometry in EPSG:4326."""
    return aoi.to_crs(4326).geometry.union_all()


def geometry_from_geojson(obj: dict) -> gpd.GeoDataFrame:
    """Build a boundary from a parsed GeoJSON dict.

    Convenience for platform code that already holds the geometry in memory and
    should not have to round-trip it through a file.
    """
    if obj.get("type") == "FeatureCollection":
        geoms = [shape(f["geometry"]) for f in obj["features"]]
    elif obj.get("type") == "Feature":
        geoms = [shape(obj["geometry"])]
    else:
        geoms = [shape(obj)]
    aoi = gpd.GeoDataFrame(geometry=geoms, crs=4326)
    aoi["area_ha"] = aoi.to_crs(EQUAL_AREA).area / 1e4
    aoi["field_id"] = [f"field_{i:02d}" for i in range(1, len(aoi) + 1)]
    return aoi


# Extensions a boundary upload may carry. A shapefile arrives either zipped or
# as its loose parts, which must all be present and keep their original names --
# GDAL finds the .dbf/.shx/.prj next to the .shp by name.
UPLOAD_TYPES = ("geojson", "json", "kml", "gpkg", "zip", "shp", "shx", "dbf", "prj", "cpg")
_BOUNDARY_EXT = (".shp", ".geojson", ".json", ".gpkg", ".kml")


def read_upload(files) -> gpd.GeoDataFrame:
    """A field boundary from uploaded files.

    ``files`` is a list of ``(name, bytes)`` pairs -- one GeoJSON, KML or
    GeoPackage, a zipped shapefile, or the loose parts of a shapefile selected
    together. Port of the R app's ``read_upload()``: the files are written to a
    temporary folder under their own names, zips are unpacked, and a shapefile
    is preferred when a zip carries more than one kind of file.
    """
    import tempfile
    import zipfile

    if not files:
        raise ValueError("No file uploaded.")
    tmp = Path(tempfile.mkdtemp(prefix="upload_"))
    for name, data in files:
        (tmp / Path(name).name).write_bytes(data)
    for z in list(tmp.glob("*.zip")) + list(tmp.glob("*.ZIP")):
        with zipfile.ZipFile(z) as zf:
            zf.extractall(tmp)
    cand = sorted(p for p in tmp.rglob("*")
                  if p.suffix.lower() in _BOUNDARY_EXT and "__MACOSX" not in p.parts)
    if not cand:
        raise ValueError("No boundary file found. Upload a .geojson, .kml, .gpkg, "
                         "or a zipped shapefile.")
    shp = [p for p in cand if p.suffix.lower() == ".shp"]
    if shp and not shp[0].with_suffix(".dbf").exists() and not any(
            p.suffix.lower() == ".dbf" for p in shp[0].parent.iterdir()):
        raise ValueError("A shapefile needs its .shx and .dbf (and ideally .prj) "
                         "uploaded together with the .shp, or zipped.")
    return load_field(shp[0] if shp else cand[0])
