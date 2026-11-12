"""
Prepared figures for the notebook.

This file defines the notebook figures. Add or change figures here to show results
from your own model.


What is in this file, from top to bottom
----------------------------------------
plot_maps()            Shows supply, reachability, one group's contacts and contact counts.
plot_results()         Shows the water need met, the groups without a point and the repairs.
plot_comparison()      Compares two runs, for example before and after a change.
"""

import matplotlib.pyplot as plt  # Matplotlib draws the figures.
import networkx as nx  # NetworkX draws the social contacts of one group.
from matplotlib.lines import Line2D  # Line2D draws the symbols in the legends.
from matplotlib.collections import LineCollection  # LineCollection draws many pipes at once.


def plot_maps(model):
    """Show supply, reachability and social contacts without drawing every social link."""
    infrastructure = model.infrastructure
    social_graph = model.social_graph
    if social_graph.number_of_nodes() == 0:
        raise ValueError("The social graph must contain groups before plotting")

    # Choose an example group with about four contacts to keep the figure readable.
    # This uses no random numbers, so plotting does not change the simulation.
    example_group = None
    closest_degree_difference = None
    contact_counts = []
    for group, degree in social_graph.degree():  # A group's degree is its number of contacts.
        contact_counts.append(degree)
        difference = abs(degree - 4)
        if closest_degree_difference is None or difference < closest_degree_difference:
            example_group = group
            closest_degree_difference = difference
    example_home = example_group.home_junction

    centre_east, centre_north = infrastructure.info["centre_utm32n"]
    point_east_km = []
    point_north_km = []
    supply_colours = []
    reach_colours = []
    for point_name in infrastructure.water_points:
        east_m, north_m = infrastructure.coordinates[point_name]
        # Convert metres from the centre to km.
        point_east_km.append((east_m - centre_east) / 1000)
        point_north_km.append((north_m - centre_north) / 1000)
        if infrastructure.current_point_flow_litres_per_hour[point_name] > 0:
            supply_colours.append("#007ca7")  # Blue means the point has some supply.
        else:
            supply_colours.append("#d75c2b")  # Orange means the point has no supply.
        if point_name in example_group.reachable_point_distances_m:
            reach_colours.append("#007ca7")  # Blue means group R can walk to the point.
        else:
            reach_colours.append("#c4ccd2")  # Grey means the point is beyond reach.
    home_east, home_north = infrastructure.coordinates[example_home]
    home_east_km = (home_east - centre_east) / 1000
    home_north_km = (home_north - centre_north) / 1000
    point_size = 25
    if len(point_east_km) > 100:  # Use smaller dots when the map has many points.
        point_size = 9

    # The figure has 2 x 2 panels and one shared title. The top-right panel is axes[0, 1].
    figure, axes = plt.subplots(2, 2, figsize=(12, 9))
    figure.suptitle(f"{model.network_name}: networks at day {model.elapsed_days:g}", fontsize=14)

    # The maps use real coordinates. Red marks broken pipes. An intact pipe can still
    # be dry if damage elsewhere cuts it off from every source.
    other_links = []
    broken_links = []
    broken_pipes = set(infrastructure.broken_pipes)
    for start, end, link_name in infrastructure.water_graph.edges(keys=True):
        start_east, start_north = infrastructure.coordinates[start]
        end_east, end_north = infrastructure.coordinates[end]
        segment = [  # Each segment stores one pipe's start and end in km.
            ((start_east - centre_east) / 1000, (start_north - centre_north) / 1000),
            ((end_east - centre_east) / 1000, (end_north - centre_north) / 1000),
        ]
        if link_name in broken_pipes:
            broken_links.append(segment)
        else:
            other_links.append(segment)
    # LineCollection groups pipes by colour. add_collection places them on the panel.
    axes[0, 0].add_collection(LineCollection(other_links, colors="#bac5cd", linewidths=0.45))
    axes[0, 0].add_collection(  # The broken pipes are drawn in red.
        LineCollection(broken_links, colors="#bd5745", linewidths=0.7, alpha=0.75)
    )
    # Use zorder=3 to draw points on top of the pipes.
    axes[0, 0].scatter(point_east_km, point_north_km, c=supply_colours, s=point_size, zorder=3)
    axes[0, 0].set_title(f"Where is water available?\n{len(broken_pipes):,} broken pipes")
    axes[0, 0].legend(
        handles=[  # With no data, Line2D draws only the legend symbol.
            Line2D([], [], color="#bd5745", label="Broken pipe"),
            Line2D([], [], marker="o", color="#007ca7", linestyle="", label="Point: some supply"),
            Line2D([], [], marker="o", color="#d75c2b", linestyle="", label="Point: no supply"),
        ],
        fontsize=8,
        loc="center left",
        bbox_to_anchor=(1.03, 0.5),  # Place the legend just right of the panel, halfway up.
        frameon=False,  # The legend has no box around it.
    )

    # Keep pipes faint in this panel because groups walk in straight lines.
    axes[0, 1].add_collection(
        LineCollection(other_links + broken_links, colors="#dde3e7", linewidths=0.4)
    )
    axes[0, 1].scatter(point_east_km, point_north_km, c=reach_colours, s=point_size, zorder=3)
    axes[0, 1].set_title(
        f"Which points can group R reach?\n"
        f"Profile {example_group.profile}: straight-line walk up to "
        f"{example_group.walking_distance_m:,.0f} m"
    )
    axes[0, 1].legend(
        handles=[
            Line2D([], [], marker="o", color="#007ca7", linestyle="", label="Reachable point"),
            Line2D([], [], marker="o", color="#c4ccd2", linestyle="", label="Beyond reach"),
            Line2D(
                [], [], marker="*", color="#202f3a", linestyle="", label="Home of example group R"
            ),
        ],
        fontsize=8,
        loc="center left",
        bbox_to_anchor=(1.03, 0.5),
        frameon=False,
    )
    for axis in axes[0]:  # axes[0] contains the two top-row maps.
        axis.scatter([home_east_km], [home_north_km], marker="*", s=100, color="#202f3a", zorder=4)
        axis.annotate(  # The label R appears 5 points above and to the right of the star.
            "R", (home_east_km, home_north_km), xytext=(5, 5), textcoords="offset points"
        )
        axis.autoscale()  # Fit the view to the pipes; add_collection does not do this.
        axis.set_aspect("equal")  # One km has the same length on both axes.
        axis.set_anchor("W")  # Place the map on the left (west) side of the panel.
        axis.set_xlabel("East of centre (km)")
        axis.set_ylabel("North of centre (km)")
    # Use the same extent for both maps so they can be compared.
    x_limits = axes[0, 0].get_xlim()
    y_limits = axes[0, 0].get_ylim()
    axes[0, 1].set_xlim(x_limits)
    axes[0, 1].set_ylim(y_limits)

    # Draw up to eight real contacts. Their positions keep the drawing readable
    # and do not show where the groups live.
    contacts = list(social_graph.neighbors(example_group))
    shown_contacts = contacts[:8]
    shown_nodes = [example_group] + shown_contacts
    local_graph = social_graph.subgraph(shown_nodes)  # Keep only these groups and their links.
    # The shell layout places R in the centre with its contacts on a surrounding ring.
    positions = nx.shell_layout(local_graph, nlist=[[example_group], shown_contacts])
    labels = {}
    for index, contact in enumerate(shown_contacts):
        labels[contact] = f"C{index + 1}"  # The contacts are named C1, C2 and so on.
    nx.draw_networkx_edges(local_graph, positions, ax=axes[1, 0], edge_color="#aebbc5", width=1.2)
    nx.draw_networkx_nodes(  # The contacts are light circles.
        local_graph,
        positions,
        nodelist=shown_contacts,
        node_color="#dbeaf1",
        edgecolors="#007ca7",
        node_size=650,
        ax=axes[1, 0],
    )
    nx.draw_networkx_nodes(  # Group R is a larger dark circle.
        local_graph,
        positions,
        nodelist=[example_group],
        node_color="#007ca7",
        node_size=800,
        ax=axes[1, 0],
    )
    nx.draw_networkx_labels(local_graph, positions, labels=labels, font_size=10, ax=axes[1, 0])
    nx.draw_networkx_labels(  # Use white text so the label is readable on the dark node.
        local_graph,
        positions,
        labels={example_group: "R"},
        font_color="white",
        font_size=10,
        ax=axes[1, 0],
    )
    axes[1, 0].set_title("Who can R learn from?")
    axes[1, 0].set_axis_off()  # Hide the axes in the contact diagram.
    axes[1, 0].text(
        0.5,
        -0.04,
        f"R is a group at {example_home}. The panel shows {len(shown_contacts)} of its "
        f"{len(contacts)} contacts.\n"
        f"It draws {len(shown_nodes)} of {len(social_graph):,} groups at schematic positions.",
        ha="center",
        va="top",
        # The x and y coordinates are measured as fractions of the panel.
        transform=axes[1, 0].transAxes,
        fontsize=9,
    )

    # The bars show how contact counts vary across the whole social network.
    # Every group in the supplied network has at least two contacts. The first bar
    # counts groups with two or fewer, since a network you build can have fewer.
    counts = [0, 0, 0, 0]  # Each count gives one bar in the chart.
    for degree in contact_counts:
        if degree <= 2:
            counts[0] += 1
        elif degree <= 4:
            counts[1] += 1
        elif degree <= 9:
            counts[2] += 1
        else:
            counts[3] += 1
    percentages = []
    for count in counts:
        percentages.append(100 * count / len(contact_counts))
    bars = axes[1, 1].bar(["2 or fewer", "3–4", "5–9", "10+"], percentages, color="#007ca7")
    # bar_label writes each percentage above its bar. The format %% prints a percent sign.
    axes[1, 1].bar_label(bars, fmt="%.1f%%", padding=3, fontsize=9)
    axes[1, 1].set_ylim(0, 100)
    axes[1, 1].set_title("How many contacts do groups have?")
    axes[1, 1].set_xlabel("Number of direct contacts")
    axes[1, 1].set_ylabel("Groups (%)")
    axes[1, 1].text(
        0.5,
        -0.22,
        f"All {len(contact_counts):,} groups; maximum {max(contact_counts)} contacts.\n"
        "The model generates the social network. It does not come from observed contacts.",
        ha="center",
        va="top",
        transform=axes[1, 1].transAxes,
        fontsize=9,
    )
    # The rect setting leaves room for the title.
    figure.tight_layout(rect=(0, 0.02, 1, 0.96), h_pad=2.5)
    return figure


def plot_results(model):
    """Plot results over time, leaving out the starting-state row."""
    # iloc[1:] excludes the starting-state row.
    data = model.datacollector.get_model_vars_dataframe().iloc[1:]
    figure, axes = plt.subplots(1, 3, figsize=(14, 4))  # This creates three panels in one row.
    axes[0].plot(data["Time (days)"], data["Water need met (%)"], color="#202f3a", label="all")
    # Draw one dashed line per profile so the profiles can be compared.
    for profile_name in model.profiles:
        axes[0].plot(
            data["Time (days)"],
            data[f"Water need met, {profile_name} (%)"],
            linestyle="--",
            label=profile_name,
        )
    axes[0].legend(frameon=False)  # The legend uses the label of each line.
    axes[0].set_title("Water need met")
    axes[0].set_ylabel("Water need met (%)")
    axes[0].set_ylim(0, 105)
    axes[1].plot(data["Time (days)"], data["Groups without a point (%)"], color="#007ca7")
    axes[1].set_title("Groups without a point")
    axes[1].set_ylabel("Groups without a point (%)")
    axes[1].set_ylim(0, 105)
    axes[2].plot(data["Time (days)"], data["Broken pipes"], color="#d75c2b")
    axes[2].set_title("Broken pipes")
    axes[2].set_ylabel("Broken pipes at the end of the step")
    axes[2].set_ylim(bottom=0)  # Only the lower limit is fixed.
    for axis in axes:
        axis.set_xlabel("Time (days)")
        axis.grid(alpha=0.2)  # The value alpha=0.2 makes the grid faint.
    figure.tight_layout()  # Keep titles and labels from overlapping.
    return figure


def plot_comparison(model_a, model_b, label_a="Run A", label_b="Run B"):
    """Plot the recorded results of two runs on the same axes."""
    # Use "Run A" and "Run B" when the call supplies no labels. The notebook passes
    # its own labels, such as "Sharing".
    figure, axes = plt.subplots(1, 2, figsize=(11, 4))  # This creates two panels in one row.
    for model, label, colour, line_style in [  # Each row specifies a run and its line style.
        (model_a, label_a, "#6c737b", "--"),
        (model_b, label_b, "#007ca7", "-"),
    ]:
        data = model.datacollector.get_model_vars_dataframe().iloc[1:]
        for axis, column in [  # Each pair specifies a panel and the column to plot.
            (axes[0], "Water need met (%)"),
            (axes[1], "Groups without a point (%)"),
        ]:
            axis.plot(
                data["Time (days)"],
                data[column],
                label=label,
                color=colour,
                linestyle=line_style,
            )
            axis.set_ylabel(column)
    axes[0].set_title("Water need met")
    axes[1].set_title("Groups without a point")
    for axis in axes:
        axis.set_ylim(0, 105)
        axis.set_xlabel("Time (days)")
        axis.grid(alpha=0.2)
    # Use panel 0's lines for one shared legend. With ncol=2, entries sit side by side.
    handles, labels = axes[0].get_legend_handles_labels()
    figure.legend(handles, labels, loc="upper center", ncol=2, frameon=False)
    # The rect setting leaves the top tenth for the legend.
    figure.tight_layout(rect=(0, 0, 1, 0.9))
    return figure
