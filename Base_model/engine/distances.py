"""
Straight-line walking distances.

You are not expected to change this file. The model calls it through engine/infrastructure.py.
Groups walk in straight lines. The model does not represent roads, closures or travel time.


What is in this file, from top to bottom
----------------------------------------
straight_line_distance_m()   Returns the distance between two map positions, in metres.
distances_to_water_points()  Lists the water points within a given distance of each junction.
"""

import math  # The math module calculates one distance.

import numpy as np  # NumPy calculates many distances at once.


def straight_line_distance_m(position_a, position_b):
    """Return the straight-line distance between two (east, north) positions, in metres."""
    # For example, positions (0, 0) and (300, 400) are sqrt(300**2 + 400**2) = 500 m apart.
    east_a, north_a = position_a
    east_b, north_b = position_b
    return math.hypot(east_a - east_b, north_a - north_b)  # hypot(x, y) is sqrt(x**2 + y**2).


def distances_to_water_points(coordinates, home_junctions, water_points, maximum_distance_m):
    """Return {home junction: {water point: distance in metres}} for points within reach."""
    distances = {}
    for junction_name in home_junctions:
        distances[junction_name] = {}

    # NumPy calculates distances from all homes to one point at once.
    # Each row in home_positions stores one home's (east, north) coordinates.
    home_positions = np.array([coordinates[name] for name in home_junctions])
    for point_name in water_points:
        # NumPy subtracts the position of the point from every row at once.
        differences = home_positions - np.array(coordinates[point_name])
        # With axis=1, NumPy sums the values within each row.
        point_distances_m = np.sqrt(np.sum(differences**2, axis=1))
        for row_number, junction_name in enumerate(home_junctions):
            # The distance is a plain Python number.
            distance_m = float(point_distances_m[row_number])
            if distance_m <= maximum_distance_m:
                distances[junction_name][point_name] = distance_m
    return distances
