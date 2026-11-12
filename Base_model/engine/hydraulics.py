"""
The hydraulic calculation with EPANET.

You are not expected to change this file. The model calls it through engine/infrastructure.py.

EPANET is a standard program for water networks. It calculates each junction's pressure
and received flow for the current pipe damage. WNTR (Water Network Tool for Resilience)
runs EPANET from Python.


What is in this file, from top to bottom
----------------------------------------
set_hydraulic_options()      Sets how EPANET handles low pressure and searches for a result.
find_supplied_nodes()        Finds the nodes that working pipes still link to a source.
calculate_supply_fractions() Runs EPANET and returns the supply fraction of each junction.
"""

import math  # The math module checks whether EPANET returned valid numbers.
import os  # The os module reads the optional setting SEN1211_TEMP_DIR.
import tempfile  # The tempfile module makes a temporary folder for the solver files.
import warnings  # The warnings module hides known WNTR warnings.
from pathlib import Path  # Path builds file paths.

import networkx as nx  # NetworkX finds the connected parts of the network.
import wntr  # WNTR runs EPANET from Python.
from wntr.network import LinkStatus  # LinkStatus names the Open and Closed states of a link.


def set_hydraulic_options(water_network):
    """Set the EPANET options for a pressure-dependent calculation at one moment."""
    # With pressure-dependent demand (PDD), pressure determines the flow a junction
    # receives. Between 0 m and 20 m, the supplied fraction is (pressure / 20) ** 0.5.
    # For example, 5 m of pressure gives (5 / 20) ** 0.5 = 0.5.
    options = water_network.options.hydraulic
    options.demand_model = "PDD"
    options.minimum_pressure = 0.0  # A junction receives nothing at 0 m of pressure.
    options.required_pressure = 20.0  # A junction receives its full flow at 20 m or more.
    options.pressure_exponent = 0.5  # This is the power 0.5 in the formula above.

    # EPANET finds flows through repeated trials: up to 200, then 10 more if needed.
    # If the flows still have not settled, the model stops with an error.
    options.trials = 200
    options.unbalanced = "CONTINUE"
    options.unbalanced_value = 10

    # With a duration of 0, EPANET calculates flow at the start of the day using the
    # current broken pipes. It does not simulate changes in flow during the day.
    water_network.options.time.duration = 0


def find_supplied_nodes(water_network, water_graph, original_link_status, broken_pipes):
    """Return the nodes that working links still connect to a reservoir or tank."""
    # Reservoirs and tanks supply the network. A connected part of a graph contains
    # nodes joined by links. This copy keeps only working links. A connected part
    # without a source receives no water.
    working_graph = water_graph.copy()
    broken_pipe_names = set(broken_pipes)
    for link_name, link in water_network.links():
        if link_name in broken_pipe_names or original_link_status[link_name] == LinkStatus.Closed:
            working_graph.remove_edge(link.start_node_name, link.end_node_name, key=link_name)

    sources = set(water_network.reservoir_name_list + water_network.tank_name_list)
    supplied_nodes = set()
    for connected_part in nx.connected_components(working_graph):
        if connected_part.intersection(sources):  # The part contains at least one source.
            supplied_nodes.update(connected_part)
    return supplied_nodes


def calculate_supply_fractions(
    water_network, water_graph, original_link_status, broken_pipes, base_demand_m3_per_second
):
    """Run EPANET and return {junction: fraction of its requested flow that it receives}."""
    supplied_nodes = find_supplied_nodes(
        water_network, water_graph, original_link_status, broken_pipes
    )
    broken_pipe_names = set(broken_pipes)

    try:  # The finally block restores the network after these temporary changes.
        # EPANET treats broken pipes as closed links. Links cut off from a source are
        # also closed, and isolated junctions have no demand. Otherwise, these isolated
        # parts can prevent EPANET from finding a result.
        for link_name, link in water_network.links():
            if (
                link_name in broken_pipe_names
                or link.start_node_name not in supplied_nodes
                or link.end_node_name not in supplied_nodes
            ):
                link.initial_status = LinkStatus.Closed
        for junction_name in base_demand_m3_per_second:
            if junction_name not in supplied_nodes:
                water_network.get_node(junction_name).demand_timeseries_list[0].base_value = 0.0

        # EPANET writes solver files to a temporary folder. Python removes the folder
        # afterwards, even if the calculation fails.
        with tempfile.TemporaryDirectory(
            prefix="sen1211_", dir=os.environ.get("SEN1211_TEMP_DIR")
        ) as solver_directory:
            with warnings.catch_warnings():  # This hides the warning about unused pump curves.
                warnings.filterwarnings("ignore", message="Not all curves were used.*")
                simulator = wntr.sim.EpanetSimulator(water_network)
                results = simulator.run_sim(  # This call runs EPANET once.
                    file_prefix=str(Path(solver_directory) / "snapshot"),
                    convergence_error=True,  # WNTR raises an error if the trials do not settle.
                )
            delivered_m3_per_second = results.node["demand"].iloc[0]  # This is the flow at time 0.
    finally:
        # This restores the original links and demands, even if EPANET failed.
        # The next calculation therefore starts from the same network.
        for link_name, link in water_network.links():
            link.initial_status = original_link_status[link_name]
        for junction_name, base_demand in base_demand_m3_per_second.items():
            water_network.get_node(junction_name).demand_timeseries_list[
                0
            ].base_value = base_demand

    # The supply fraction is delivered flow divided by requested flow. EPANET
    # calculates requested flow by multiplying base demand by the network file's
    # demand pattern. At the start of the day, that multiplier is 0.96. The method
    # at(0) returns the requested flow at time 0. For example, a junction requesting
    # 0.001 m3/s and receiving 0.0006 m3/s has a supply fraction of 0.6.
    supply_fractions = {}
    for junction_name in base_demand_m3_per_second:
        supply_fraction = 0.0
        junction = water_network.get_node(junction_name)
        requested_m3_per_second = junction.demand_timeseries_list[0].at(0)
        if junction_name in supplied_nodes and requested_m3_per_second > 0:
            delivered = float(delivered_m3_per_second[junction_name])
            if not math.isfinite(delivered):  # A flow that is not a finite number is invalid.
                raise RuntimeError(f"EPANET gave no valid flow at junction {junction_name}")
            supply_fraction = min(1.0, max(0.0, delivered / requested_m3_per_second))
        supply_fractions[junction_name] = supply_fraction
    return supply_fractions
