"""
Tests for the supplied water-access model and infrastructure.

Run these tests before and after each change. Add a test for every mechanism you
add or change.

A test sets up a specific situation, runs the relevant rule or model step, and checks
what happened. Each assert states something that must be true. If it is false, pytest
reports the test name and the assertion that failed. Read that test's set-up to see
which conditions produced the failure.

pytest.approx compares numbers while allowing small rounding differences. A block using
pytest.raises(ValueError) checks that an invalid action raises the expected error.
pytest.mark.parametrize runs the same test separately for each listed value. With two
such decorators, pytest checks every combination of their values.

Some tests set agent attributes directly to create a controlled situation, such as an
empty water point. These tests check individual rules. Other tests run the full model
and check recorded results. Passing these checks supports the behaviours tested here;
it does not establish that the model represents a real city accurately.


What is in this file, from top to bottom
----------------------------------------
Time and water accounting                   conservation (no water appears or disappears),
                                            duration and scheduled repairs
Group rules, profiles and reproducibility   the three rules, profiles, movement and seeds
Maps, infrastructure methods and figures    all four maps, infrastructure methods,
                                            invalid inputs and plots

Run from Base_model with: python -m pytest tests -q
To run one test, add -k and part of its name, for example:
python -m pytest tests -q -k empty_visit
"""

import math
from unittest.mock import patch  # patch temporarily replaces an object during a test.

import mesa
import pytest  # pytest finds the test functions and reports which checks pass or fail.

from model.agents import Municipality, ResidentGroup
from model.model import WaterAccessModel


def edge_ids(model):
    """Return social links as pairs of group IDs so two runs can be compared.

    Separate models contain different agent objects. Their IDs let the test compare
    which groups are connected without comparing the objects themselves."""
    pairs = set()
    for first_group, second_group in model.social_graph.edges():
        pairs.add((first_group.unique_id, second_group.unique_id))
    return pairs


def first_group_with_a_reachable_point(model):
    """Find a group that can walk to at least one water point.

    Tests use this helper when they need to arrange a visit or a contact report.
    It returns None if no group has a reachable point."""
    for group in model.groups:
        if len(group.reachable_point_distances_m) > 0:
            return group


# =========================================================================================
# Time and water accounting
# =========================================================================================


@pytest.mark.parametrize("time_step_hours", [1, 6, 24])
def test_duration_demand_and_scheduled_repairs_use_physical_time(time_step_hours):
    """Check that water demand and repairs follow days, not the number of steps.

    Run two days with each supported step length. Total need must equal population
    times 15 litres per day times two days. A ten-day repair schedule must complete
    the same fraction of repairs for each step length."""
    model = WaterAccessModel(
        time_step_hours=time_step_hours, simulation_days=2, recovery_days=10, rng=4
    )
    total_population = model.groups.agg("population", sum)  # Mesa: agg sums over all groups.
    initial_broken = len(model.infrastructure.repair_order)
    summed_need = 0.0
    for _ in range(model.number_of_steps):  # The name _ indicates that the loop number is unused.
        model.step()
        summed_need += model.groups.agg("water_need_litres", sum)
    assert model.elapsed_days == 2
    assert model.steps == 48 / time_step_hours  # Two days have 48 hours.
    assert not model.running
    assert summed_need == pytest.approx(total_population * 15 * 2)
    assert model.infrastructure.completed_repairs == math.floor(initial_broken * 2 / 10)


@pytest.mark.parametrize("time_step_hours", [1, 6, 24])
def test_each_step_conserves_public_water_and_group_need(time_step_hours):
    """Check the water balance after every step.

    Collected water plus water left at the points must equal public supply.
    For each group, home water, collected water and unmet need must add up to its
    total need. The small negative tolerance allows for floating-point rounding."""
    model = WaterAccessModel(time_step_hours=time_step_hours, simulation_days=1, rng=8)
    for step_number in range(model.number_of_steps):
        model.step()
        public_supply = sum(model.available_water_litres.values())
        public_remaining = sum(model.remaining_water_litres.values())
        collected = model.groups.agg("collected_water_litres", sum)
        assert collected + public_remaining == pytest.approx(public_supply)
        # The tolerance -1e-8 allows a tiny rounding remainder, not a water deficit.
        assert min(model.remaining_water_litres.values()) >= -1e-8
        for group in model.groups:
            assert group.unmet_water_litres >= -1e-8
            assert (
                group.home_water_litres + group.collected_water_litres + group.unmet_water_litres
            ) == pytest.approx(group.water_need_litres)
            assert group.collected_water_litres >= 0


def test_intact_network_has_no_meaningful_unmet_need():
    """Check that the intact default network meets more than 99.9% of water need.

    Run one day without broken pipes. This checks the default turin_2x2 network;
    it does not establish the same result for every map."""
    # With no broken pipes on turin_2x2, every home receives its full flow. This test
    # gives all groups a 1 km walking distance, independent of the elderly profile's limit.
    profiles = {"all": {"fraction": 1.0, "walking_distance_m": 1000}}
    model = WaterAccessModel(broken_pipe_fraction=0, profiles=profiles, simulation_days=1, rng=1)
    model.run_for(model.number_of_steps)
    assert model.water_need_met_percent > 99.9


def test_repair_schedule_reaches_full_recovery():
    """Check that the repair schedule finishes within recovery_days.

    Set both the run and recovery period to two days. At the end, no pipes should
    remain broken and the mean home-supply fraction should exceed its initial value."""
    model = WaterAccessModel(simulation_days=2, recovery_days=2, rng=2)
    supply_before = model.infrastructure.home_supply_fraction.values()
    mean_supply_before = sum(supply_before) / len(supply_before)
    model.run_for(model.number_of_steps)
    supply_after = model.infrastructure.home_supply_fraction.values()
    mean_supply_after = sum(supply_after) / len(supply_after)
    assert model.infrastructure.broken_pipes == []
    assert mean_supply_after > mean_supply_before


def test_fixed_broken_pipes_do_not_trigger_repeated_hydraulic_calculations():
    """Check that unchanged damage does not trigger repeated EPANET calculations.

    With recovery_days=None, there are no scheduled repairs. The initial hydraulic
    calculation should therefore be the only one during this two-day run."""
    model = WaterAccessModel(simulation_days=2, recovery_days=None, rng=2)
    model.run_for(model.number_of_steps)
    assert model.infrastructure.hydraulic_calculations == 1


# =========================================================================================
# Group rules, profiles and reproducibility
# =========================================================================================


def test_same_seed_reproduces_state_and_results():
    """Check that two models with the same seed reproduce the same run.

    Compare their repair order and social links before running them. Then compare
    the full model-result tables and recorded resident-group data."""
    first = WaterAccessModel(simulation_days=2, collect_group_data=True, rng=17)
    second = WaterAccessModel(simulation_days=2, collect_group_data=True, rng=17)
    assert first.infrastructure.repair_order == second.infrastructure.repair_order
    assert edge_ids(first) == edge_ids(second)
    first.run_for(first.number_of_steps)
    second.run_for(second.number_of_steps)
    assert first.datacollector.get_model_vars_dataframe().equals(
        second.datacollector.get_model_vars_dataframe()
    )
    assert first.datacollector.get_agenttype_vars_dataframe(ResidentGroup).equals(
        second.datacollector.get_agenttype_vars_dataframe(ResidentGroup)
    )


def test_runs_do_not_share_a_mutable_hydraulic_network():
    """Check that changing one model's network does not affect another model.

    Create two models with the same seed, but run only the first. The second must
    keep its original home supply and have no completed repairs."""
    first = WaterAccessModel(simulation_days=1, recovery_days=1, rng=4)
    second = WaterAccessModel(simulation_days=1, recovery_days=1, rng=4)
    second_supply = second.infrastructure.home_supply_fraction.copy()
    # A mutable object can change in place. If the models shared this network object,
    # repairs in one model would affect the other.
    assert first.infrastructure.water_network is not second.infrastructure.water_network
    first.run_for(first.number_of_steps)
    assert second.infrastructure.home_supply_fraction == second_supply
    assert second.infrastructure.completed_repairs == 0


def test_information_switch_does_not_change_initial_conditions():
    """Check that switching sharing off preserves the checked starting conditions.

    Use the same seed for both models. Compare repair order, public points, social
    links and each group's initial known point. These must match before any steps run."""
    sharing = WaterAccessModel(share_information=True, rng=19)
    isolated = WaterAccessModel(share_information=False, rng=19)
    assert sharing.infrastructure.repair_order == isolated.infrastructure.repair_order
    assert sharing.infrastructure.water_points == isolated.infrastructure.water_points
    assert edge_ids(sharing) == edge_ids(isolated)
    for first, second in zip(sharing.groups, isolated.groups):
        assert first.known_water_point == second.known_water_point


def test_each_group_starts_with_its_nearest_reachable_point():
    """Check how each group gets its first known point.

    A group with reachable points must know one at the minimum distance. A group
    with no reachable points must start with known_water_point set to None."""
    model = WaterAccessModel(rng=5)
    for group in model.groups:
        distances = group.reachable_point_distances_m
        if len(distances) == 0:
            assert group.known_water_point is None
        else:
            assert distances[group.known_water_point] == min(distances.values())


def test_an_empty_visit_forgets_the_point():
    """Check that a group forgets a point after collecting no water.

    Give the group a need of 10 litres and arrange a visit to an empty point.
    Call collect_water directly to test this rule without running a full step."""
    model = WaterAccessModel(rng=6)
    group = first_group_with_a_reachable_point(model)
    group.known_water_point = next(iter(group.reachable_point_distances_m))
    group.unmet_water_litres = 10.0
    group.chosen_water_point = group.known_water_point
    model.requested_water_litres[group.chosen_water_point] = 0.0
    model.remaining_water_litres[group.chosen_water_point] = 0.0
    group.collect_water()
    assert group.collected_water_litres == 0
    assert group.known_water_point is None


def test_learning_uses_only_direct_contacts_and_reachable_points():
    """Check who learns from one successful visit.

    Clear all previous knowledge and visits, then give one source group a successful
    visit. After one exchange, only its direct contacts that can reach the reported
    point should know it."""
    model = WaterAccessModel(rng=10)
    groups = model.groups.to_list()
    source = first_group_with_a_reachable_point(model)
    reachable_point = next(iter(source.reachable_point_distances_m))
    for group in groups:
        group.known_water_point = None
        group.chosen_water_point = None
        group.collected_water_litres = 0.0
    source.chosen_water_point = reachable_point
    source.collected_water_litres = 5.0
    direct_contacts = set(source.contacts)
    model.groups.do("learn_from_contacts")  # Mesa: do runs the rule for every group.
    for group in groups:
        expected = (
            group in direct_contacts and reachable_point in group.reachable_point_distances_m
        )
        assert (group.known_water_point == reachable_point) == expected


def test_a_group_with_a_point_does_not_listen():
    """Check that a group keeps its known point when a contact reports another.

    Find a listener that already knows a different point and can reach the reported
    one. Give its contact a successful visit, then check that the listener's choice
    remains unchanged after learning."""
    model = WaterAccessModel(rng=10)
    for group in model.groups:
        group.chosen_water_point = None
        group.collected_water_litres = 0.0
    # The test looks for a source group with a contact that knows a different point.
    listener = None
    for source in model.groups:
        for reported_point in source.reachable_point_distances_m:
            for contact in source.contacts:
                known_point = contact.known_water_point
                if known_point is not None and known_point != reported_point:
                    if reported_point in contact.reachable_point_distances_m:
                        listener = contact
                        break
            if listener is not None:
                break
        if listener is not None:
            break
    assert listener is not None
    source.chosen_water_point = reported_point
    source.collected_water_litres = 5.0
    listener.learn_from_contacts()
    assert listener.known_water_point == known_point


def test_a_learned_point_does_not_pass_on_in_the_same_exchange():
    """Check that information does not spread beyond direct contacts in one exchange.

    Only the source group has collected water. Groups outside its direct contacts
    must remain without a known point, even if an earlier group in the loop learns it."""
    model = WaterAccessModel(rng=11)
    for group in model.groups:
        group.known_water_point = None
        group.chosen_water_point = None
        group.collected_water_litres = 0.0
    source = first_group_with_a_reachable_point(model)
    point_name = next(iter(source.reachable_point_distances_m))
    source.chosen_water_point = point_name
    source.collected_water_litres = 5.0
    direct_contacts = set(source.contacts)
    model.groups.do("learn_from_contacts")
    for group in model.groups:
        if group is not source and group not in direct_contacts:
            assert group.known_water_point is None


@pytest.mark.parametrize("time_step_hours", [1, 6, 24])
def test_social_exchange_occurs_once_per_day(time_step_hours, monkeypatch):
    """Check that each group receives one learning call per day at every step length.

    Temporarily wrap the learning method with a counter while still running the
    original rule. A two-day run must make twice as many calls as there are groups."""
    call_count = [0]  # A list lets the inner function change the count.
    original_method = ResidentGroup.learn_from_contacts

    def counted_learning(group):
        """Count calls while preserving the actual learning rule."""
        call_count[0] += 1
        original_method(group)

    # pytest supplies monkeypatch and restores the original method after this test.
    # The wrapper counts calls while still running the actual learning rule.
    monkeypatch.setattr(ResidentGroup, "learn_from_contacts", counted_learning)
    model = WaterAccessModel(time_step_hours=time_step_hours, simulation_days=2, rng=4)
    model.run_for(model.number_of_steps)
    assert call_count[0] == len(model.groups) * 2


def test_the_base_has_groups_and_one_municipality():
    """Check the agent types created during model set-up.

    The model must contain ResidentGroup and Municipality agents, with exactly one
    municipality. An unintended extra agent type makes this test fail."""
    model = WaterAccessModel(rng=1)
    assert set(model.agents_by_type) == {ResidentGroup, Municipality}
    assert len(model.municipalities) == 1


def test_the_municipality_only_observes():
    """Check that the municipality records the model's reported percentage.

    After one day, compare its latest observation with groups_without_point_percent.
    This assertion checks the recorded value; it does not compare a run with and
    without a municipality."""
    model = WaterAccessModel(simulation_days=1, rng=3)
    model.run_for(model.number_of_steps)
    municipality = next(iter(model.municipalities))
    assert municipality.observed_groups_without_point_percent == pytest.approx(
        model.groups_without_point_percent
    )


class ExtraActor(mesa.Agent):
    """Provide an extra agent type with no resident-group attributes or rules.

    The test below adds it to one model. If group rules were applied to all agents,
    this agent would not have the attributes or methods those rules require."""


def test_new_agent_type_does_not_receive_group_rules():
    """Check that an unrelated agent does not change resident-group results.

    Add ExtraActor to one of two otherwise identical models. Both runs must complete
    and produce identical model summaries and recorded group data."""
    with_actor = WaterAccessModel(simulation_days=2, collect_group_data=True, rng=8)
    without_actor = WaterAccessModel(simulation_days=2, collect_group_data=True, rng=8)
    ExtraActor(with_actor)  # Mesa: Creating the agent adds it to the model.
    # The model holds the groups, the municipality and the new agent.
    assert len(with_actor.agents) == len(with_actor.groups) + 2
    with_actor.run_for(with_actor.number_of_steps)
    without_actor.run_for(without_actor.number_of_steps)
    assert with_actor.datacollector.get_model_vars_dataframe().equals(
        without_actor.datacollector.get_model_vars_dataframe()
    )
    assert with_actor.datacollector.get_agenttype_vars_dataframe(ResidentGroup).equals(
        without_actor.datacollector.get_agenttype_vars_dataframe(ResidentGroup)
    )


def test_profiles_split_each_junction_and_keep_every_resident():
    """Check that dividing residents into groups preserves the population.

    Sum group populations at each home junction and compare them with the source
    data. The elderly share must also remain within 0.02 of 0.25, allowing for
    rounding when residents are assigned to profiles."""
    model = WaterAccessModel(rng=21)
    people_by_junction = {}
    for group in model.groups:
        people_by_junction[group.home_junction] = (
            people_by_junction.get(group.home_junction, 0) + group.population
        )
    data = model.infrastructure.resident_data
    for junction, residents in zip(data["junction"], data["population"]):
        assert people_by_junction[junction] == pytest.approx(residents)
    elderly_people = sum(group.population for group in model.groups if group.profile == "elderly")
    assert elderly_people / data["population"].sum() == pytest.approx(0.25, abs=0.02)


def test_each_profile_reaches_only_points_within_its_walking_distance():
    """Check that every group uses its profile's walking-distance limit.

    Compare the group's stored limit with its profile setting. Every point in the
    group's reachable-point dictionary must fall within that limit."""
    model = WaterAccessModel(rng=22)
    for group in model.groups:
        distance_limit = model.profiles[group.profile]["walking_distance_m"]
        assert group.walking_distance_m == distance_limit
        for distance_m in group.reachable_point_distances_m.values():
            assert distance_m <= distance_limit


def test_a_single_profile_works():
    """Check that the model can run with one resident profile.

    Replace the defaults with a profile named all. After one day, every group must
    use that profile and the results must contain its water-need-met column."""
    profiles = {"all": {"fraction": 1.0, "walking_distance_m": 1000}}
    model = WaterAccessModel(profiles=profiles, simulation_days=1, rng=23)
    model.run_for(model.number_of_steps)
    assert set(group.profile for group in model.groups) == {"all"}
    data = model.datacollector.get_model_vars_dataframe()
    assert "Water need met, all (%)" in data.columns


def test_groups_walk_to_their_point_and_return_home():
    """Check that group positions follow their water-collection decisions.

    After one step, visitors must occupy their chosen point and other groups must
    be home. Then set home supply to full and run another step. The previous
    visitors must return home because they no longer need to collect water."""
    model = WaterAccessModel(rng=24)
    model.step()
    walkers = []
    for group in model.groups:
        if group.chosen_water_point is not None:
            walkers.append(group)
    assert len(walkers) > 0
    for group in walkers:
        assert group.cell is model.water_space[group.chosen_water_point]
    for group in model.groups:
        if group.chosen_water_point is None:
            assert group.cell is group.home_cell
    # With full supply at home, no group needs to walk, so every walker returns home.
    for junction in model.infrastructure.home_supply_fraction:
        model.infrastructure.home_supply_fraction[junction] = 1.0
    model.step()
    for group in walkers:
        assert group.cell is group.home_cell


def test_several_groups_can_share_one_junction():
    """Check that a water-network cell can hold several resident groups.

    Find the junction with the most groups. It must have more than one, and its
    cell must contain the same number of agents as the group count for that junction."""
    model = WaterAccessModel(rng=25)
    groups_per_junction = {}
    for group in model.groups:
        groups_per_junction[group.home_junction] = (
            groups_per_junction.get(group.home_junction, 0) + 1
        )
    busiest = max(groups_per_junction, key=groups_per_junction.get)
    assert groups_per_junction[busiest] > 1
    assert len(model.water_space[busiest].agents) == groups_per_junction[busiest]


def test_a_group_does_not_learn_a_point_beyond_its_walking_distance():
    """Check that a group ignores a reported point it cannot reach.

    Remove all reachable points from the listener, then give one contact a successful
    visit. The listener must learn no point and collect no water when its rules run."""
    model = WaterAccessModel(rng=2)
    source = first_group_with_a_reachable_point(model)
    listener = source.contacts[0]
    for group in model.groups:
        group.collected_water_litres = 0.0
    listener.known_water_point = None
    listener.reachable_point_distances_m = {}
    source.chosen_water_point = next(iter(source.reachable_point_distances_m))
    source.collected_water_litres = 5.0
    listener.learn_from_contacts()
    assert listener.known_water_point is None
    listener.choose_water_point()
    listener.collect_water()
    assert listener.collected_water_litres == 0


# =========================================================================================
# Maps, infrastructure methods, input checks and figures
# =========================================================================================


@pytest.mark.parametrize("network_name", ["turin_2x2", "turin_4x4", "turin_6x6", "turin_full"])
@pytest.mark.parametrize("time_step_hours", [1, 6, 24])
def test_all_network_packages_run(network_name, time_step_hours):
    """Check every map with every supported step length.

    The two parameter lists create twelve combinations. Each runs for one day and
    must preserve the source population, include every group in the social graph
    and finish at the expected simulated time."""
    model = WaterAccessModel(
        network_name=network_name,
        time_step_hours=time_step_hours,
        simulation_days=1,
        rng=2,
    )
    model.run_for(model.number_of_steps)
    total_people = sum(group.population for group in model.groups)
    assert total_people == pytest.approx(model.infrastructure.resident_data["population"].sum())
    assert model.social_graph.number_of_nodes() == len(model.groups)
    assert model.elapsed_days == 1


def test_public_points_are_distributed_within_each_district():
    """Check how the requested number of water points is applied per district.

    Request three points per district. A district with fewer than three candidate
    junctions must get one point per junction; all others must get three points."""
    model = WaterAccessModel(water_points_per_district=3, rng=14)
    residents = model.infrastructure.resident_data
    points = set(model.infrastructure.water_points)
    for district, group in residents.groupby("district"):
        junctions = set(group["junction"])
        assert len(points.intersection(junctions)) == min(3, len(junctions))


def test_distances_are_straight_lines_within_the_walking_limit():
    """Check the distances stored for reachable water points.

    Each stored distance must match the infrastructure's distance calculation and
    stay within the group's walking limit. A point at the home junction must have
    distance zero."""
    model = WaterAccessModel(rng=3)
    for group in model.groups:
        for point_name, distance_m in group.reachable_point_distances_m.items():
            assert distance_m <= group.walking_distance_m
            assert distance_m == pytest.approx(
                model.infrastructure.distance_m(group.home_junction, point_name)
            )
        if group.home_junction in model.infrastructure.water_points:
            assert group.reachable_point_distances_m[group.home_junction] == 0


def test_repair_method_repairs_one_pipe_and_updates_supply():
    """Check the repair method with the background schedule disabled.

    Repair one broken pipe. It must leave the broken-pipe list and trigger one more
    hydraulic calculation. Repairing the same pipe again must raise ValueError.
    The model must still complete its run afterwards."""
    model = WaterAccessModel(recovery_days=None, rng=12)
    broken_before = len(model.infrastructure.broken_pipes)
    calculations_before = model.infrastructure.hydraulic_calculations
    pipe_name = model.infrastructure.broken_pipes[0]
    model.infrastructure.repair_pipe(pipe_name)
    assert pipe_name not in model.infrastructure.broken_pipes
    assert len(model.infrastructure.broken_pipes) == broken_before - 1
    assert model.infrastructure.hydraulic_calculations == calculations_before + 1
    with pytest.raises(ValueError):
        model.infrastructure.repair_pipe(pipe_name)
    model.run_for(model.number_of_steps)


def test_open_water_point_method_adds_a_reachable_point():
    """Check that opening a point updates the infrastructure and group reachability.

    Choose a junction without a point. After opening it, check its flow entry and
    whether each group can reach it. Opening it again must raise ValueError, and
    the model must still complete its run."""
    model = WaterAccessModel(rng=13)
    points = set(model.infrastructure.water_points)
    new_point = None
    for junction in model.infrastructure.resident_data["junction"]:
        if junction not in points:
            new_point = junction
            break
    model.open_water_point(new_point)
    assert new_point in model.infrastructure.water_points
    assert new_point in model.infrastructure.current_point_flow_litres_per_hour
    for group in model.groups:
        distance_m = model.infrastructure.distance_m(group.home_junction, new_point)
        reachable = new_point in group.reachable_point_distances_m
        assert reachable == (distance_m <= group.walking_distance_m)
    with pytest.raises(ValueError):
        model.open_water_point(new_point)
    model.run_for(model.number_of_steps)


def test_repair_method_refuses_to_run_with_a_repair_schedule():
    """Check that manual repairs are rejected while a repair schedule is active.

    The schedule could otherwise overwrite a manual repair and mark the pipe as
    broken again. The repair method must raise ValueError in this case."""
    model = WaterAccessModel(recovery_days=30, rng=12)
    with pytest.raises(ValueError):
        model.infrastructure.repair_pipe(model.infrastructure.broken_pipes[0])


def test_a_new_water_point_has_no_water_until_the_next_step():
    """Check that a point opened between steps has no water until the next step.

    Its remaining water must initially be zero. After the next step, its available
    water must be non-negative. This test does not require positive supply because
    the damaged network may leave it dry."""
    model = WaterAccessModel(rng=13)
    model.step()
    new_point = None
    for junction in model.infrastructure.resident_data["junction"]:
        if junction not in model.infrastructure.water_points:
            new_point = junction
            break
    model.open_water_point(new_point)
    assert model.remaining_water_litres[new_point] == 0.0
    model.step()
    assert model.available_water_litres[new_point] >= 0


def test_groups_use_a_new_point_only_after_they_are_told():
    """Check the difference between opening a point and informing groups about it.

    Run a step after opening the point: no group should request water there yet.
    Then tell reachable groups about it by setting known_water_point. The next
    step must produce requests at the new point."""
    model = WaterAccessModel(rng=13)
    model.step()
    new_point = None
    for junction in model.infrastructure.resident_data["junction"]:
        if junction not in model.infrastructure.water_points:
            new_point = junction
            break
    model.open_water_point(new_point)
    model.step()
    assert model.requested_water_litres[new_point] == 0.0
    # A municipality agent would tell the groups that can reach the point.
    for group in model.groups:
        if new_point in group.reachable_point_distances_m:
            group.known_water_point = new_point
    model.step()
    assert model.requested_water_litres[new_point] > 0.0


def test_small_batch_completes_every_resolution():
    """Check that the batch runner completes a one-day run at each step length.

    Use 1, 6 and 24-hour steps with an upper limit of 24 steps. The returned results
    must contain three rows, each reporting one simulated day."""
    results = mesa.batch_run(  # Mesa: batch_run runs the model once for each step length.
        WaterAccessModel,
        parameters={
            "simulation_days": 1,
            "time_step_hours": [1, 6, 24],
            "collect_group_data": False,
        },
        rng=[1],
        max_steps=24,
        number_processes=1,
        display_progress=False,
    )
    assert len(results) == 3
    assert all(row["Time (days)"] == 1 for row in results)


@pytest.mark.parametrize(
    "parameters",
    [
        {"time_step_hours": 0},
        {"time_step_hours": 3},
        {"simulation_days": 0},
        {"simulation_days": 1.5},
        {"people_per_group": 0},
        {"broken_pipe_fraction": -0.1},
        {"broken_pipe_fraction": 1.1},
        {"recovery_days": 0},
        {"water_points_per_district": 0},
        {"water_points_per_district": 1.5},
        {"share_information": "False"},
        {"share_information": None},
        {"share_information": 1},
        {"collect_group_data": "False"},
        {"profiles": {}},
        {"profiles": {"a": {"fraction": 0.5, "walking_distance_m": 500}}},
    ],
)
def test_invalid_parameters_fail_before_the_solver(parameters):
    """Check that invalid settings are rejected before the infrastructure is created.

    Each listed dictionary supplies one invalid setting. Replace Infrastructure
    temporarily with a mock, which records whether it was called. The model must
    raise ValueError naming the setting and must not call Infrastructure."""
    # A test Infrastructure class checks that invalid input is rejected before EPANET starts.
    parameter_name = next(iter(parameters))
    with patch("model.model.Infrastructure") as infrastructure_class:
        with pytest.raises(ValueError, match=parameter_name):
            WaterAccessModel(**parameters)
        infrastructure_class.assert_not_called()


@pytest.mark.parametrize("simulation_days", [1, 2])
def test_short_comparison_draws_every_step(simulation_days):
    """Check that short runs produce both lines in each comparison panel.

    Compare sharing on and off for runs of one and two days. Each panel must have
    two non-empty lines whose times stay within the run duration. These checks
    do not require a particular number of plotted points."""
    import matplotlib.pyplot as plt

    from model.plots import plot_comparison

    first = WaterAccessModel(simulation_days=simulation_days, rng=2)
    second = WaterAccessModel(simulation_days=simulation_days, share_information=False, rng=2)
    first.run_for(first.number_of_steps)
    second.run_for(second.number_of_steps)
    figure = plot_comparison(first, second)
    try:
        for axis in figure.axes:
            assert len(axis.lines) == 2
            for line in axis.lines:
                assert len(line.get_xdata()) > 0
                assert max(line.get_xdata()) <= simulation_days
    finally:
        # The figure is closed even if an assertion fails.
        plt.close(figure)


@pytest.mark.parametrize("network_name", ["turin_2x2", "turin_4x4", "turin_6x6", "turin_full"])
def test_network_figure_is_bounded_and_does_not_change_the_simulation(network_name):
    """Check that drawing the maps leaves the simulation state unchanged.

    Save both random-generator states and the social links before plotting. They
    must remain unchanged, and the model must not advance a step. Also check the
    four panels, the limit of nine displayed social nodes and contact-count bars
    that sum to 100%. Repeat for all four maps."""
    import copy

    import matplotlib.pyplot as plt
    from matplotlib.collections import PathCollection

    from model.plots import plot_maps

    model = WaterAccessModel(network_name=network_name, rng=42)
    random_state = model.random.getstate()  # The test saves both random states before drawing.
    numpy_state = copy.deepcopy(model.rng.bit_generator.state)
    edges = set(model.social_graph.edges())
    figure = plot_maps(model)
    try:
        assert model.random.getstate() == random_state
        assert model.rng.bit_generator.state == numpy_state
        assert set(model.social_graph.edges()) == edges
        assert model.steps == 0
        assert len(figure.axes) == 4
        drawn_nodes = 0
        for collection in figure.axes[2].collections:
            if isinstance(collection, PathCollection):
                drawn_nodes += len(collection.get_offsets())
        assert 1 <= drawn_nodes <= 9  # The panel draws group R and at most eight contacts.
        assert sum(bar.get_height() for bar in figure.axes[3].patches) == pytest.approx(100)
        assert "straight-line walk" in figure.axes[1].get_title()
    finally:
        # The figure is closed even if an assertion fails.
        plt.close(figure)
