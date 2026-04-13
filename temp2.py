# /// script
# requires-python = ">=3.11"
# dependencies = ["geopandas>=0.14"]
# ///
import geopandas as gpd
gdf = gpd.read_file('folder1/annotations.geojson')
print("Annotations GeoJSON:")
print(gdf.head(2).to_dict('records'))
