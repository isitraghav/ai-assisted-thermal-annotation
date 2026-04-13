# /// script
# requires-python = ">=3.11"
# dependencies = ["geopandas>=0.14"]
# ///
import geopandas as gpd
gdf = gpd.read_file('1775925810686-report.geojson')
print("Report GeoJSON Columns:", gdf.columns.tolist())
print(gdf.head(1).to_dict('records'))
