"""
Public water points.

You are not expected to change this file. The model calls it through engine/infrastructure.py.
The method WaterAccessModel.open_water_point adds a point during a run.

Public water points are assumed additions to the supplied network. Examples include
tanks or standpipes that a city sets up after damage. Each point draws water from the
pipes at its junction.


What is in this file, from top to bottom
----------------------------------------
place_water_points()      Chooses junctions for water points in each district.
add_water_point_demand()  Adds one point's flow to the demand at its junction.
"""

LITRES_PER_HOUR_IN_ONE_M3_PER_SECOND = 3_600_000  # WNTR works in cubic metres per second.


def place_water_points(resident_data, water_points_per_district, random_generator):
    """Return the junctions selected for public water points."""
    # Each district with residents gets up to water_points_per_district points.
    # If it has fewer junctions, each junction gets one point.
    water_points = []
    for district in sorted(resident_data["district"].unique()):
        district_rows = resident_data[resident_data["district"] == district]
        candidates = list(district_rows["junction"])
        point_count = min(len(candidates), water_points_per_district)
        water_points.extend(random_generator.sample(candidates, point_count))
    return water_points


def add_water_point_demand(water_network, junction_name, nominal_point_flow_litres_per_hour):
    """Add one water point's flow to its junction's demand and return the total."""
    # A junction's demand is the flow its users take from the pipes. The model adds the
    # point's flow to this demand. EPANET therefore treats the point as drawing the full
    # flow, whether or not groups collect the water.
    # For example, 900 litres per hour is 900 / 3,600,000 = 0.00025 cubic metres per second.
    junction = water_network.get_node(junction_name)
    point_flow_m3_per_second = (
        nominal_point_flow_litres_per_hour / LITRES_PER_HOUR_IN_ONE_M3_PER_SECOND
    )
    # WNTR stores a junction's base demand in demand_timeseries_list[0].base_value.
    junction.demand_timeseries_list[0].base_value += point_flow_m3_per_second
    return junction.demand_timeseries_list[0].base_value
