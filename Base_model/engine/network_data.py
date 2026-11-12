"""
Load one map package.

You are not expected to change this file. The model calls it through engine/infrastructure.py.

This file loads one map from the networks folder. It reads the water network from
water.inp, residents per junction from resident_units.csv and data sources from info.json.
It also builds the pipe graph and reads the map coordinates.


What is in this file, from top to bottom
----------------------------------------
find_network_folder()   Returns the folder of one map and stops if the map does not exist.
read_map_sources()      Reads info.json, which lists the map size and the data sources.
read_resident_data()    Reads the table of residents per junction.
read_water_network()    Reads water.inp into a WNTR water network.
build_pipe_graph()      Builds a NetworkX graph with every pipe, pump and valve.
read_coordinates()      Reads the map position of every junction, reservoir and tank.
"""

import json  # The json module reads info.json.
import warnings  # The warnings module hides known WNTR warnings.
from pathlib import Path  # Path builds file paths.

import networkx as nx  # NetworkX stores the pipe graph.
import pandas as pd  # pandas stores the resident table.
import wntr  # WNTR (Water Network Tool for Resilience) reads EPANET water networks.

# These are the four maps in the networks folder.
NETWORK_NAMES = ["turin_2x2", "turin_4x4", "turin_6x6", "turin_full"]


def find_network_folder(network_name):
    """Return the folder of one map, for example networks/turin_2x2."""
    # The folder path is relative to this file, so it works on any computer.
    network_folder = Path(__file__).resolve().parents[1] / "networks" / network_name
    if not (network_folder / "water.inp").is_file():
        raise ValueError(
            f"Unknown network '{network_name}'. Choose from {', '.join(NETWORK_NAMES)}."
        )
    return network_folder


def read_map_sources(network_folder):
    """Return the map size and data sources stored in info.json."""
    with open(network_folder / "info.json") as source_file:
        return json.load(source_file)


def read_resident_data(network_folder):
    """Return a table with one row per junction: its residents and its district."""
    return pd.read_csv(network_folder / "resident_units.csv")


def read_water_network(network_folder):
    """Return the water network from water.inp as a WNTR model."""
    with warnings.catch_warnings():  # The two filters below apply only inside this block.
        # A pump curve gives a pump's flow at each pressure. Some curves in the files are
        # unused, so this filter hides WNTR's warning about them.
        warnings.filterwarnings("ignore", message="Not all curves were used.*")
        # The headloss formula calculates pressure lost through friction in a pipe.
        # The file already uses the Darcy-Weisbach formula. This filter hides WNTR's
        # warning that it sets this formula.
        warnings.filterwarnings("ignore", message="Changing the headloss formula.*")
        return wntr.network.WaterNetworkModel(str(network_folder / "water.inp"))


def build_pipe_graph(water_network):
    """Return a graph of every pipe, pump and valve, and the original status of each link."""
    # The graph represents junctions, reservoirs and tanks as nodes. Pipes, pumps
    # and valves form the links. Some pumps have a bypass pipe between the same two
    # junctions. On turin_full, some valves also have a bypass. There are 2 such
    # locations on turin_2x2 and 41 on turin_full. The bypass pipe is usually closed.
    # A NetworkX MultiGraph can store two or more links between the same nodes.
    water_graph = nx.MultiGraph()
    water_graph.add_nodes_from(water_network.node_name_list)

    # Each link is Open or Closed in the file. The hydraulic calculation temporarily
    # closes broken pipes, then restores their original status. Each edge uses its
    # link name as the key to distinguish links between the same nodes.
    original_link_status = {}
    for link_name, link in water_network.links():
        original_link_status[link_name] = link.initial_status
        water_graph.add_edge(link.start_node_name, link.end_node_name, key=link_name)
    return water_graph, original_link_status


def read_coordinates(water_network):
    """Return {node name: (east, north)} in metres."""
    # UTM zone 32N is a standard coordinate grid for northern Italy, measured in metres.
    # Distances between points can therefore be calculated directly from their coordinates.
    coordinates = {}
    for node_name, node in water_network.nodes():
        coordinates[node_name] = node.coordinates
    return coordinates
