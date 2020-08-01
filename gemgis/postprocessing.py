"""
Contributors: Arthur Endlein Correia, Alexander Jüstel, Florian Wellmann

GemGIS is a Python-based, open-source geographic information processing library.
It is capable of preprocessing spatial data such as vector data (shape files, geojson files, geopackages),
raster data, data obtained from WMS services or XML/KML files.
Preprocessed data can be stored in a dedicated Data Class to be passed to the geomodeling package GemPy
in order to accelerate to model building process.

GemGIS is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

GemGIS is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License (LICENSE.md) for more details.

"""

from matplotlib import pyplot as plt
from shapely import geometry
import geopandas as gpd
import numpy as np
import matplotlib.patches as mpatches
from matplotlib.colors import ListedColormap
import sys
import os
from typing import List, Union
from gemgis import gemgis
try:
    import gempy as gp
except ModuleNotFoundError:
    sys.path.append('../../../gempy-master')
    import gempy as gp


def extract_lithologies(geo_model, extent, crs):
    shape = geo_model._grid.topography.values_2d[:, :, 2].shape

    block = geo_model.solutions.geological_map[1][-1]

    fig, ax = plt.subplots(figsize=(10, 8))

    level = geo_model.solutions.scalar_field_at_surface_points[-1][
        np.where(geo_model.solutions.scalar_field_at_surface_points[-1] != 0)
    ]

    contours = ax.contourf(
        block.reshape(shape).T,
        0,
        levels=[block.min() - 1] + sorted(level) + [block.max() + 1],
        origin="lower",
        extent=extent,
    )
    plt.close()
    # https://gis.stackexchange.com/a/246861/15374
    fm = []
    geo = []
    for col, fm_name in zip(
            contours.collections,
            geo_model.surfaces.df.sort_values(by="order_surfaces", ascending=False).surface):

        # Loop through all polygons that have the same intensity level
        for contour_path in col.get_paths():
            # Create the polygon for this intensity level
            # The first polygon in the path is the main one, the following ones are "holes"
            for ncp, cp in enumerate(contour_path.to_polygons()):
                x = cp[:, 0]
                y = cp[:, 1]
                new_shape = geometry.Polygon([(i[0], i[1]) for i in zip(x, y)])
                if ncp == 0:
                    poly = new_shape
                else:
                    # Remove the holes if there are any
                    poly = poly.difference(new_shape)
                    # Can also be left out if you want to include all rings

            # do something with polygon
            fm.append(fm_name)
            geo.append(poly)

    lith = gpd.GeoDataFrame({"formation": fm}, geometry=geo, )
    lith.crs = crs

    return lith


def extract_borehole(geo_model: gp.core.model.Project,
                     geo_data: gemgis.GemPyData,
                     loc: List[Union[int, float]],
                     **kwargs):
    """
    Extracting a borehole at a provided location from a recalculated GemPy Model
    Args:
        geo_model: gp.core.model.Project - previously calculated GemPy Model
        geo_data: gemgis.GemPyData - GemGIS GemPy Data class used to calculate the previous model
        loc: list of x and y point pair representing the well location
    Kwargs:
        zmax: int/float indicating the maximum depth of the well, default is minz of the previous model
        res: int indicating the resolution of the model in z-direction

    Returns:

    """

    # Checking if geo_model is a GemPy geo_model
    if not isinstance(geo_model, gp.core.model.Project):
        raise TypeError('geo_model must be a GemPy geo_model')

    # Checking if geo_data is a GemGIS GemPy Data Class
    if not isinstance(geo_data, gemgis.GemPyData):
        raise TypeError('geo_data must be a GemPy Data object')

    # Checking if loc is of type list
    if not isinstance(loc, list):
        raise TypeError('Borehole location must be provided as a list of a x- and y- coordinate')

    # Checking if elements of loc are of type int or float
    if not all(isinstance(n, (int, float)) for n in loc):
        raise TypeError('Location values must be provided as integers or floats')

    # Selecting DataFrame columns and create deep copy of DataFrame
    orientations_df = geo_model.orientations.df[['X', 'Y', 'Z', 'surface', 'dip', 'azimuth', 'polarity']].copy(deep=True)

    interfaces_df = geo_model.surface_points.df[['X', 'Y', 'Z', 'surface']].copy(deep=True)

    # Creating formation column
    orientations_df['formation'] = orientations_df['surface']
    interfaces_df['formation'] = interfaces_df['surface']

    # Deleting surface column
    del orientations_df['surface']
    del interfaces_df['surface']

    # Getting maximum depth and resolution
    zmax = kwargs.get('zmax', geo_model.grid.regular_grid.extent[5])
    res = kwargs.get('res', geo_model.grid.regular_grid.resolution[2])

    # Checking if zmax is of type int or floar
    if not isinstance(zmax, (int,float)):
        raise TypeError('Maximum depth must be of type int or float')

    # Checking if res is of type int
    if not isinstance(res, (int, float, np.int32)):
        raise TypeError('Resolution must be of type int')

    # Creating variable for maximum depth
    z = geo_model.grid.regular_grid.extent[5] - zmax

    # Prevent printing
    sys.stdout = open(os.devnull, 'w')

    # Create GemPy Model
    well_model = gp.create_model('Well_Model')

    # Initiate Data for GemPy Model
    gp.init_data(well_model,
                 extent=[loc[0] - 5, loc[0] + 5, loc[1] - 5, loc[1] + 5, geo_model.grid.regular_grid.extent[4],
                         geo_model.grid.regular_grid.extent[5] - z],
                 resolution=[5, 5, res],
                 orientations_df=orientations_df.dropna(),
                 surface_points_df=interfaces_df.dropna(),
                 default_values=False)

    # Map Stack to surfaces
    gp.map_stack_to_surfaces(well_model,
                             geo_data.stack,
                             remove_unused_series=True)

    # Add Basement surface
    well_model.add_surfaces('basement')

    # Change colors of surfaces
    well_model.surfaces.colors.change_colors(geo_data.surface_colors)

    # Set Interpolator
    gp.set_interpolator(well_model,
                        compile_theano=True,
                        theano_optimizer='fast_run', dtype='float64',
                        update_kriging=False,
                        verbose=[])

    # Compute Model
    sol = gp.compute_model(well_model, compute_mesh=False)

    # Reshape lith_bloc
    well = sol.lith_block.reshape(well_model.grid.regular_grid.resolution[0],
                                  well_model.grid.regular_grid.resolution[1],
                                  well_model.grid.regular_grid.resolution[2])

    # Select colors for plotting
    color_dict = well_model.surfaces.colors.colordict
    cols = list(
        color_dict.values())  # a selection needs to be made as soon as faults are present or not all layers are present

    # Create Plot
    plt.figure(figsize=(3, 10))
    plt.imshow(np.round(well.T[:, 1]),
               cmap=ListedColormap(cols),
               extent=(0,
                       (well_model.grid.regular_grid.extent[5] - well_model.grid.regular_grid.extent[4]) / 8,
                       well_model.grid.regular_grid.extent[4],
                       well_model.grid.regular_grid.extent[5]),
               )

    # Set legend handles
    patches = [
        mpatches.Patch(color=cols[i], label="{formation}".format(formation=well_model.surfaces.df.surface.to_list()[i]))
        for i in range(len(well_model.surfaces.df.surface.to_list()))]

    # Remove xticks
    plt.tick_params(axis='x', labelsize=0, length=0)

    # Set ylabel
    plt.ylabel('Depth [m]')

    # Set legend
    plt.legend(handles=patches, bbox_to_anchor=(3, 1))

    return sol

# TODO: Create function to export qml layer from surface_color_dict
