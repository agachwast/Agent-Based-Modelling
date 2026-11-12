"""
The set-up steps and helpers of the model.

This file defines the longer set-up tasks and calculations used by WaterAccessModel
in model.py. Keeping them here lets model.py show the parameters, set-up order and step
sequence. Edit these functions to change how groups are created and linked, or which
results the model records.


What is in this file, from top to bottom
----------------------------------------
check_parameters()                        Stops the model if an input would produce invalid results.
create_groups()                           Splits the residents into profiles and groups.
link_social_network()                     Links the groups in an assumed social network.
set_up_data_collection()                  Tells Mesa which results to record.
calculate_groups_without_point_percent()  Returns the percentage of groups without a point.
calculate_water_need_met_percent()        Returns the percentage of one profile's need met.
open_water_point()                        Adds a public water point during a run.

Each function receives the model as model. Lines that use Mesa have comments starting
with "Mesa:".
"""

import networkx as nx  # NetworkX creates the social network.

from mesa.datacollection import DataCollector  # Mesa: DataCollector records results in tables.

from model.agents import ResidentGroup  # ResidentGroup is the agent defined in agents.py.


def check_parameters(model):
    """Stop with a clear message if an input would produce invalid results."""
    # The supplied tests cover step lengths of 1, 6 and 24 hours.
    if model.time_step_hours not in (1, 6, 24):
        raise ValueError("time_step_hours must be 1, 6 or 24.")
    # A whole number of days gives a whole number of steps.
    if model.simulation_days <= 0 or model.simulation_days != int(model.simulation_days):
        raise ValueError("simulation_days must be a positive whole number.")
    if model.people_per_group <= 0:  # The model divides by the group size.
        raise ValueError("people_per_group must be larger than 0.")
    if not 0 <= model.broken_pipe_fraction <= 1:
        raise ValueError("broken_pipe_fraction must be between 0 and 1.")
    # The recovery time must be greater than 0 because the repair schedule divides by it.
    if model.recovery_days is not None and model.recovery_days <= 0:
        raise ValueError("recovery_days must be larger than 0, or None.")
    # Each district must have at least 1 water point, with a whole number of points.
    if model.water_points_per_district < 1 or model.water_points_per_district != int(
        model.water_points_per_district
    ):
        raise ValueError("water_points_per_district must be a whole number of 1 or more.")
    # A switch must be True or False. The text "False" would count as True.
    for parameter_name, value in (
        ("share_information", model.share_information),
        ("collect_group_data", model.collect_group_data),
    ):
        if not isinstance(value, bool):
            raise ValueError(f"{parameter_name} must be True or False.")
    # Profile fractions must add up to 1 so that every resident belongs to a profile.
    total_fraction = 0
    for profile_name in model.profiles:
        total_fraction += model.profiles[profile_name]["fraction"]
    if abs(total_fraction - 1) > 0.000001:
        raise ValueError("profiles must have fractions that add up to 1.")


def create_groups(model):
    """Divide residents at each junction into profiles, then divide each profile into groups."""
    # The number of groups per profile is round(residents / people_per_group), with
    # at least one group. For example, a junction with 47 residents has
    # round(47 * 0.25) = 12 elderly residents and 35 other residents. A target of
    # 10 people per group gives one elderly group of 12 and four other groups of 8.75.
    # Group populations are averages, so they can be decimal numbers. A junction with
    # 3 elderly residents has one elderly group of 3. The last profile receives the
    # remaining residents, keeping the total population unchanged.
    longest_walking_distance_m = 0
    for profile_name in model.profiles:
        walking_distance_m = model.profiles[profile_name]["walking_distance_m"]
        longest_walking_distance_m = max(longest_walking_distance_m, walking_distance_m)
    # The infrastructure lists points within this distance of each junction.
    distances_by_junction = model.infrastructure.distances_to_water_points(
        longest_walking_distance_m
    )

    last_profile_name = list(model.profiles)[-1]
    junction_data = model.infrastructure.resident_data
    for junction, residents, district in zip(
        junction_data["junction"], junction_data["population"], junction_data["district"]
    ):
        remaining_residents = residents
        for profile_name in model.profiles:
            settings = model.profiles[profile_name]
            if profile_name == last_profile_name:
                profile_residents = remaining_residents
            else:
                profile_residents = min(
                    remaining_residents, round(residents * settings["fraction"])
                )
            remaining_residents -= profile_residents

            # No group is created for a profile with no residents at this junction.
            if profile_residents == 0:
                continue

            number_of_groups = max(1, round(profile_residents / model.people_per_group))
            for group_number in range(number_of_groups):
                # Each group stores points within its profile's walking distance in its own
                # dictionary. The function open_water_point can add points to that dictionary later.
                reachable_points = {}
                for point_name in distances_by_junction[junction]:
                    distance_m = distances_by_junction[junction][point_name]
                    if distance_m <= settings["walking_distance_m"]:
                        reachable_points[point_name] = distance_m

                ResidentGroup(  # Mesa: Creating a ResidentGroup adds it to the model.
                    model,
                    cell=model.water_space[junction],  # Mesa: This selects the junction's cell.
                    home_junction=junction,
                    population=profile_residents / number_of_groups,
                    district=district,
                    profile=profile_name,
                    walking_distance_m=settings["walking_distance_m"],
                    reachable_point_distances_m=reachable_points,
                )


def link_social_network(model):
    """Create the assumed social network and assign contacts to each group."""
    # The social network is independent of the pipes and grows one group at a time.
    # Each new group links to two existing groups, favouring those with more contacts.
    # This is called preferential attachment and gives a few groups many contacts.
    # These contacts are not measured data.
    # Mesa: NetworkX uses Mesa's random generator, so the same seed gives the same network.
    numbered_graph = nx.barabasi_albert_graph(len(model.groups), 2, seed=model.random)
    # The model replaces node numbers 0, 1, 2 and so on with the groups themselves.
    group_list = list(model.groups)  # The list() function turns the set into a numbered list.
    node_to_group = {}
    for node_number in range(len(group_list)):
        node_to_group[node_number] = group_list[node_number]
    model.social_graph = nx.relabel_nodes(numbered_graph, node_to_group)
    # Each group's neighbours in the social network become its contacts.
    for group in model.groups:  # Mesa: The loop visits every group in the set.
        group.contacts = list(model.social_graph.neighbors(group))


def set_up_data_collection(model):
    """Return a Mesa DataCollector for model results and optional group records."""
    # Each key names a column. Its value names the attribute to read.
    # Mesa calls each entry a reporter.
    model_reporters = {
        "Time (days)": "elapsed_days",
        "Water need met (%)": "water_need_met_percent",
        "Groups without a point (%)": "groups_without_point_percent",
        "Broken pipes": "broken_pipe_count",
    }
    # Each profile gets a result column showing the percentage of its water need met.
    # Mesa: A reporter can use [function, [values]] to call a function with those values.
    # Here, the call is calculate_water_need_met_percent(model, "elderly").
    for profile_name in model.profiles:
        model_reporters[f"Water need met, {profile_name} (%)"] = [
            calculate_water_need_met_percent,
            [model, profile_name],
        ]

    # Mesa: agenttype_reporters record one row per group at each step.
    # Use get_agenttype_vars_dataframe(ResidentGroup) to read these records.
    group_reporters = {}
    if model.collect_group_data:
        group_reporters = {
            "Home junction": "home_junction",
            "Profile": "profile",
            "Population": "population",
            "Chosen point": "chosen_water_point",
            "Need (litres)": "water_need_litres",
            "Home water (litres)": "home_water_litres",
            "Collected water (litres)": "collected_water_litres",
            "Unmet water (litres)": "unmet_water_litres",
            "Known point": "known_water_point",
        }
    # Mesa: DataCollector reads these values whenever collect() is called.
    return DataCollector(
        model_reporters=model_reporters,
        agenttype_reporters={ResidentGroup: group_reporters},
    )


def calculate_groups_without_point_percent(model):
    """Return the percentage of groups without a known water point."""
    # For example, 300 groups without a point out of 3,000 groups give 10%.
    without_point = 0
    for group in model.groups:  # Mesa: The loop visits every group in the set.
        if group.known_water_point is None:
            without_point += 1
    return 100 * without_point / len(model.groups)


def calculate_water_need_met_percent(model, profile_name):
    """Return the percentage of water need met for one resident profile."""
    # For example, elderly groups that need 400 litres and lack 100 litres give
    # 100 * (1 - 100 / 400) = 75%.
    needed = 0.0
    unmet = 0.0
    for group in model.groups:  # Mesa: The loop visits every group in the set.
        if group.profile == profile_name:
            needed += group.water_need_litres
            unmet += group.unmet_water_litres
    if needed == 0:  # No water is needed before the first step, so the model reports 0.
        return 0.0
    return 100 * (1 - unmet / needed)


def open_water_point(model, junction_name):
    """Add a public water point during a run."""
    # The infrastructure adds the point and calculates the water supply again.
    model.infrastructure.open_water_point(junction_name)
    # The new point starts supplying water next step. It has no water in this step.
    model.available_water_litres[junction_name] = 0.0
    model.remaining_water_litres[junction_name] = 0.0
    model.requested_water_litres[junction_name] = 0.0
    # The point becomes reachable for each group within walking distance.
    # The supplied rules do not announce new points. Contacts report only points they
    # have visited. Your agent must set known_water_point for the groups it informs,
    # for example group.known_water_point = junction_name.
    for group in model.groups:  # Mesa: The loop visits every group in the set.
        distance_m = model.infrastructure.distance_m(group.home_junction, junction_name)
        if distance_m <= group.walking_distance_m:
            group.reachable_point_distances_m[junction_name] = distance_m
