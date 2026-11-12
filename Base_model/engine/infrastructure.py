"""
The water infrastructure that the model uses.

You are not expected to change this file. The model creates one Infrastructure object.
The methods below call the other engine files: network_data.py,
damage_and_repair.py, water_points.py, hydraulics.py and distances.py.


What you can read and call
--------------------------
home_supply_fraction[junction]      This is the fraction of the requested flow that a
                                    junction receives, from 0 to 1. For example, 0.6 means
                                    that the homes there get 60% of their water need.
current_point_flow_litres_per_hour  This is the current flow at each public water point.
broken_pipes                        This is the list of pipes that are still broken.
water_points                        This is the list of junctions with a public water point.
distance_m(junction_a, junction_b)  This method returns the straight-line distance in metres.
repair_pipe(pipe_name)              This method repairs a chosen pipe immediately. It requires
                                    recovery_days=None.
open_water_point(junction_name)     This method adds a public water point. Call it through
                                    WaterAccessModel.open_water_point, which also updates
                                    the groups.

Each call to repair_pipe or open_water_point runs EPANET again. EPANET treats each public
point as drawing its full flow, whether or not groups collect it. The water that groups
collect does not change the EPANET calculation.
"""

# Each engine file does one part of the work.
from engine import damage_and_repair, distances, hydraulics, network_data, water_points


class Infrastructure:
    """Store the water network, its broken pipes and its water supply."""

    def __init__(
        self,
        network_name,
        broken_pipe_fraction,
        recovery_days,
        water_points_per_district,
        nominal_point_flow_litres_per_hour,
        random_generator,
    ):
        """Load one map, break pipes, place water points and calculate the water supply."""
        # ---------------------------------------------------------------------------------
        # Attributes of the infrastructure (settable)
        # ---------------------------------------------------------------------------------

        self.recovery_days = recovery_days  # Repairs take this many days. None means no schedule.
        # Nominal flow is a water point's flow in litres per hour at full pressure
        # (20 m or more).
        self.nominal_point_flow_litres_per_hour = nominal_point_flow_litres_per_hour

        # ---------------------------------------------------------------------------------
        # Attributes of the infrastructure (derived or fixed)
        # ---------------------------------------------------------------------------------

        # The map folder is, for example, networks/turin_2x2.
        network_folder = network_data.find_network_folder(network_name)
        # This stores the map size and the data sources.
        self.info = network_data.read_map_sources(network_folder)
        # Each row records the population and district of a junction with residents.
        self.resident_data = network_data.read_resident_data(network_folder)
        # WNTR reads the water network from water.inp.
        self.water_network = network_data.read_water_network(network_folder)
        # The graph includes every pipe, pump and valve. The dictionary records whether
        # each link is open or closed in the file.
        self.water_graph, self.original_link_status = network_data.build_pipe_graph(
            self.water_network
        )
        # This dictionary stores each node's map coordinates in metres.
        self.coordinates = network_data.read_coordinates(self.water_network)
        # This list stores broken pipes in their scheduled repair order. The model's
        # random-number generator selects them, so the same seed breaks the same pipes.
        self.repair_order = damage_and_repair.choose_broken_pipes(
            self.water_network, broken_pipe_fraction, random_generator
        )
        self.broken_pipes = self.repair_order.copy()  # Repairs remove pipes from this list.
        self.completed_repairs = 0  # The schedule has repaired this many pipes so far.
        # The list stores the junctions with public water points.
        self.water_points = water_points.place_water_points(
            self.resident_data, water_points_per_district, random_generator
        )

        # This dictionary stores each junction's base demand in cubic metres per second.
        # The demand includes any water point at the junction.
        self.requested_node_flow_m3_per_second = {}
        for junction_name in self.water_network.junction_name_list:
            junction = self.water_network.get_node(junction_name)
            base_demand = junction.demand_timeseries_list[0].base_value
            if junction_name in self.water_points:
                base_demand = water_points.add_water_point_demand(
                    self.water_network, junction_name, nominal_point_flow_litres_per_hour
                )
            self.requested_node_flow_m3_per_second[junction_name] = base_demand

        self.hydraulic_calculations = 0  # The tests check this count of EPANET calculations.

        # EPANET options are set once. The first calculation describes the damaged network
        # at the start.
        hydraulics.set_hydraulic_options(self.water_network)
        self.calculate_water_supply()

    def distance_m(self, junction_a, junction_b):
        """Return the straight-line distance between two junctions, in metres."""
        return distances.straight_line_distance_m(
            self.coordinates[junction_a], self.coordinates[junction_b]
        )

    def distances_to_water_points(self, maximum_distance_m):
        """Return {home junction: {water point: distance in metres}} for points within reach."""
        # The model calls this method once during set-up and reuses the result.
        return distances.distances_to_water_points(
            self.coordinates,
            list(self.resident_data["junction"]),
            self.water_points,
            maximum_distance_m,
        )

    def advance_recovery(self, elapsed_days):
        """Complete the repairs scheduled up to this day."""
        if self.recovery_days is None:
            return
        completed_repairs = damage_and_repair.count_scheduled_repairs(
            len(self.repair_order), elapsed_days, self.recovery_days
        )
        if completed_repairs != self.completed_repairs:  # EPANET runs again only after a repair.
            self.completed_repairs = completed_repairs
            self.broken_pipes = self.repair_order[completed_repairs:]
            self.calculate_water_supply()

    def repair_pipe(self, pipe_name):
        """Repair one broken pipe now and update the water supply.

        Use this method only with recovery_days=None. Otherwise, the repair schedule
        would reset the list of broken pipes later. The method raises an error
        if a repair schedule is active.
        """
        if self.recovery_days is not None:
            raise ValueError("repair_pipe needs recovery_days=None in the model")
        if pipe_name not in self.broken_pipes:
            raise ValueError(f"Pipe {pipe_name} is not broken")
        self.broken_pipes.remove(pipe_name)
        self.calculate_water_supply()

    def open_water_point(self, junction_name):
        """Add a public water point at a junction and update the water supply.

        Use WaterAccessModel.open_water_point to also add the point to each group's
        reachable points when it is within walking distance. The supplied rules do not
        announce new points. Your agent must set known_water_point for groups it informs.
        """
        if junction_name in self.water_points:
            raise ValueError(f"Junction {junction_name} already has a water point")
        if junction_name not in self.requested_node_flow_m3_per_second:
            raise ValueError(f"Unknown junction {junction_name}")
        self.water_points.append(junction_name)
        self.requested_node_flow_m3_per_second[junction_name] = (
            water_points.add_water_point_demand(
                self.water_network, junction_name, self.nominal_point_flow_litres_per_hour
            )
        )
        self.calculate_water_supply()

    def calculate_water_supply(self):
        """Run EPANET for the current broken pipes and update the supply of homes and points."""
        # Homes and the water point at a junction receive the same supply fraction.
        # For example, 0.6 covers 60% of home water need and supplies the point with
        # 0.6 * 900 = 540 litres per hour.
        self.home_supply_fraction = hydraulics.calculate_supply_fractions(
            self.water_network,
            self.water_graph,
            self.original_link_status,
            self.broken_pipes,
            self.requested_node_flow_m3_per_second,
        )
        self.current_point_flow_litres_per_hour = {}
        for point_name in self.water_points:
            self.current_point_flow_litres_per_hour[point_name] = (
                self.nominal_point_flow_litres_per_hour * self.home_supply_fraction[point_name]
            )
        self.hydraulic_calculations += 1
