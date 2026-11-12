"""
The behaviour rules of the resident groups.

This file defines what a group does during a step. Edit these functions to change its
decisions. ResidentGroup in agents.py calls one function per rule. The model in model.py
calls the rules in the order shown below during each step.


What is in this file, from top to bottom
----------------------------------------
find_nearest_point()  Returns the nearest water point within walking distance.
choose_water_point()  The group uses home water and walks to its known point if it needs more.
collect_water()       The group takes water at the point and forgets the point if it was empty.
learn_from_contacts() A group without a known point learns about one from a social contact.
observe_city()        The municipality records the share of groups without a known point.

The rules are deliberately naive. A group knows one point and accepts every contact
report. It cannot see queues and forgets a point after one visit without water.

Each function receives the group as group. The attribute group.model refers to the shared
model. Lines that use Mesa have comments starting with "Mesa:".
"""


def find_nearest_point(point_distances_m):
    """Return the nearest point from {point: metres}, or None if the dictionary is empty."""
    nearest_point = None
    shortest_distance_m = None
    for point_name in point_distances_m:
        distance_m = point_distances_m[point_name]
        # This point is closer.
        if shortest_distance_m is None or distance_m < shortest_distance_m:
            shortest_distance_m = distance_m
            nearest_point = point_name
    return nearest_point


def choose_water_point(group):
    """Use home water first, then walk to the known point if more water is needed."""
    group.move_to(group.home_cell)  # Mesa: The group starts every step at home.

    # Water need is people * litres per person per day * hours / 24.
    # For example, 10 people need 10 * 15 * 6 / 24 = 37.5 litres in a six-hour step.
    group.water_need_litres = (
        group.population
        # Mesa: group.model gives access to the shared model.
        * group.model.water_need_litres_per_person_per_day
        * group.model.time_step_hours
        / 24
    )
    # The group receives its water need multiplied by its home junction's supply fraction.
    # For example, a fraction of 0.6 supplies 37.5 * 0.6 = 22.5 litres at home.
    group.home_water_litres = (
        group.water_need_litres
        * group.model.infrastructure.home_supply_fraction[group.home_junction]
    )
    # In this example, 37.5 - 22.5 litres remain unmet.
    group.unmet_water_litres = group.water_need_litres - group.home_water_litres
    group.collected_water_litres = 0.0  # The group clears the previous step's visit.
    group.chosen_water_point = None

    # If the group still needs water, it walks to its known point within this step.
    # Amounts below 0.000001 litres count as zero because they result from rounding.
    if group.unmet_water_litres > 0.000001 and group.known_water_point is not None:
        group.chosen_water_point = group.known_water_point
        # Mesa: The group moves to the water point.
        group.move_to(group.model.water_space[group.chosen_water_point])


def collect_water(group):
    """Collect the water still needed, up to the amount left at the chosen point."""
    if group.chosen_water_point is None:  # A group staying home does not collect water at a point.
        return

    point_name = group.chosen_water_point
    # The point records all requested water, even if requests exceed its supply.
    # This total resets to zero each step and appears in the water-point figure.
    group.model.requested_water_litres[point_name] += group.unmet_water_litres

    # The group collects the water it still needs, up to the amount left at the point.
    # For example, min(15, 8) = 8 litres. Groups collect in a random order. If the point is
    # overcrowded, groups later in the order may get no water.
    group.collected_water_litres = min(
        group.unmet_water_litres, group.model.remaining_water_litres[point_name]
    )
    # Collection reduces both the water left at the point and the group's unmet need.
    group.model.remaining_water_litres[point_name] -= group.collected_water_litres
    group.unmet_water_litres -= group.collected_water_litres

    # After an empty visit, the group forgets the point. It stays home until a contact
    # reports another point.
    if group.collected_water_litres <= 0.000001:
        group.known_water_point = None


def learn_from_contacts(group):
    """Let a group without a known point learn about one from a social contact."""
    # A group with a known point does not ask contacts for another.
    if group.known_water_point is not None:
        return

    # Each contact reports where it collected water in the last step. A group cannot
    # pass on a newly learned point in the same exchange because it has not visited it.
    reported_points = []
    for contact in group.contacts:
        # The contact collected water in the last step.
        if contact.collected_water_litres > 0.000001:
            point_name = contact.chosen_water_point
            if point_name in group.reachable_point_distances_m:  # The group can walk there.
                reported_points.append(point_name)

    # The group accepts one randomly chosen report, without information about queues.
    # Two reports of the same point make it twice as likely to be chosen as one report.
    if len(reported_points) > 0:
        # Mesa: group.random uses the model's random-number generator. The seed therefore
        # determines this choice.
        group.known_water_point = group.random.choice(reported_points)


def observe_city(municipality):
    """Let the municipality record the percentage of groups without a known water point."""
    # The model calculates this percentage just before the municipality observes it.
    # Recording the observation does not change the run.
    municipality.observed_groups_without_point_percent = (
        municipality.model.groups_without_point_percent
    )
