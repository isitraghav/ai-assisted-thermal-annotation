# /// script
# requires-python = ">=3.11"
# dependencies = ["geopandas>=0.14"]
# ///
import geopandas as gpd
gdf_all = gpd.read_file('folder1/partial.shp')
gdf_anom = gpd.read_file('1775925810686-report.geojson')
joined = gpd.sjoin(gdf_all, gdf_anom, how="left", predicate="intersects")
print([c for c in joined.columns if 'name' in c.lower()])
