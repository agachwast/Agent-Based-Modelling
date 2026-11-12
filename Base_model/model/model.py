"""
Water access: the model, its parameters and the order of one step.

This file defines the parameters, set-up order and step sequence. It calls
model_functions.py for longer set-up tasks and calculations. Change this file to add
parameters, agents or steps. Read it after your first run of run_model.ipynb and
before agents.py.


What is in this file, from top to bottom
----------------------------------------
DEFAULT_PROFILES        This dictionary defines the two supplied resident profiles.
WaterAccessModel        This class sets up the model and runs it one step at a time.
  __init__()            This method stores the parameters and runs the set-up steps.
  step()                This method runs one step. Read it first.
  open_water_point()    This method adds a public water point during a run.

The model has two agent types: resident groups and one placeholder municipality. The
municipality only observes the city and shows how to build another agent type. There are
no water-utility or repair-crew agents. Repairs follow a schedule. Walking takes no model
time, but a distance limit determines which points each group can reach.

Lines that use Mesa have comments starting with "Mesa:". See "Mesa tools used in the code"
in README.md for the full list of Mesa tools used here.
"""

import networkx as nx  # NetworkX converts the pipe graph into the space used by the groups.

from mesa import Model  # Mesa: Every Mesa model is built on the Model class.
from mesa.discrete_space import Network  # Mesa: A Network space has one cell per network node.

# The Infrastructure class stores the water network and its supply. It comes from
# the engine folder. You are not expected to change these files.
from engine.infrastructure import Infrastructure
from model import model_functions  # The set-up steps and calculations are in this file.
from model.agents import Municipality, ResidentGroup  # The agents are defined in agents.py.

# =========================================================================================
# The resident profiles
# =========================================================================================

# Each profile defines a fraction of the residents and a maximum walking distance
# in metres. The fractions must add up to 1. These values are teaching assumptions,
# not data. Change profiles in the notebook's parameter cell. The notebook passes
# these profiles to the model, replacing the defaults below.
DEFAULT_PROFILES = {
    "elderly": {"fraction": 0.25, "walking_distance_m": 300},
    "other": {"fraction": 0.75, "walking_distance_m": 1000},
}

# =========================================================================================
# The model
# =========================================================================================


# Mesa: WaterAccessModel inherits Mesa's Model tools.
class WaterAccessModel(Model):
    """Simulate water access for resident groups during pipe repairs."""

    def __init__(
        self,
        # The model uses the defaults below when a call does not supply a parameter.
        # The notebook supplies its own values for the main parameters, replacing these
        # defaults. Each parameter is explained under its banner below.
        network_name="turin_2x2",
        time_step_hours=6,
        simulation_days=20,
        people_per_group=10,
        broken_pipe_fraction=0.4,
        recovery_days=30,
        share_information=True,
        water_points_per_district=4,
        nominal_point_flow_litres_per_hour=900,
        collect_group_data=False,
        profiles=DEFAULT_PROFILES,
        water_need_litres_per_person_per_day=15,
        rng=None,
    ):
        """Store the parameters, load the water network and create the resident groups."""
        # Mesa: This call sets up the Model part, including the list of all agents, the
        # clock (self.time) and the random-number generator (self.random). The seed rng
        # starts the generator. The same seed gives the same run.
        super().__init__(rng=rng)

        # ---------------------------------------------------------------------------------
        # Attributes of the model (settable)
        # ---------------------------------------------------------------------------------

        # The Turin map is "turin_2x2", "turin_4x4", "turin_6x6" or "turin_full".
        self.network_name = network_name
        # One step lasts 1, 6 or 24 hours. Groups use this to calculate their water need.
        self.time_step_hours = time_step_hours
        self.simulation_days = simulation_days  # The model simulates this many days.
        # This sets the target number of residents per group. If a junction has few
        # residents of a profile, they form one smaller group. This lowers the average size.
        self.people_per_group = people_per_group
        # This sets the fraction of breakable pipes damaged at the start, from 0 to 1.
        self.broken_pipe_fraction = broken_pipe_fraction
        # All broken pipes are repaired after this many days. None keeps them broken.
        self.recovery_days = recovery_days
        self.share_information = share_information  # If True, groups learn from contacts daily.
        # This sets the maximum number of public water points per district.
        self.water_points_per_district = water_points_per_district
        # This is one point's flow in litres per hour at full pressure (20 m or more).
        self.nominal_point_flow_litres_per_hour = nominal_point_flow_litres_per_hour
        # With True, the model records each group at every step.
        self.collect_group_data = collect_group_data
        # Each resident profile has a fraction of the residents and a walking distance
        # in metres. The model uses these to divide residents into groups and create one
        # result column per profile.
        self.profiles = profiles

        # ---------------------------------------------------------------------------------
        # Agent-level parameters (settable, passed on to the agents)
        # ---------------------------------------------------------------------------------

        # This sets emergency water need in litres per person per day. Groups read it
        # through self.model.water_need_litres_per_person_per_day.
        self.water_need_litres_per_person_per_day = water_need_litres_per_person_per_day

        # ---------------------------------------------------------------------------------
        # Attributes of the model (derived or fixed)
        # ---------------------------------------------------------------------------------

        # SET-UP 1: The model checks the inputs before it loads the maps.
        model_functions.check_parameters(self)
        # The model calculates the number of steps for the requested number of days.
        # For example, 20 days * 24 hours / 6 hours per step = 80 steps.
        self.number_of_steps = int(simulation_days * 24 / time_step_hours)
        self.elapsed_days = 0.0  # Tables and figures show this simulated time in days.

        # SET-UP 2: The infrastructure loads the water network, breaks pipes, places water
        # points and calculates the water supply. It is a Python object, not a Mesa agent.
        # Mesa: Passing self.random makes the broken pipes and points follow the seed.
        self.infrastructure = Infrastructure(
            network_name=network_name,
            broken_pipe_fraction=broken_pipe_fraction,
            recovery_days=recovery_days,
            water_points_per_district=water_points_per_district,
            nominal_point_flow_litres_per_hour=nominal_point_flow_litres_per_hour,
            random_generator=self.random,
        )

        # SET-UP 3: The groups live and walk in the water network.
        # The call nx.Graph keeps one link per pair of nodes. At some pumps, a bypass pipe
        # links the same pair. Removing this second link does not affect the groups:
        # they use nodes as cells and never walk along pipes.
        # Mesa: Network creates one cell per water-network node, including each junction,
        # reservoir and tank. With capacity=None, a cell can hold any number of groups.
        # The layout gives each cell its map coordinates.
        self.water_space = Network(
            nx.Graph(self.infrastructure.water_graph),
            capacity=None,
            random=self.random,
            layout=self.infrastructure.coordinates,
        )

        # SET-UP 4: The model divides residents at each junction into profiles and groups.
        model_functions.create_groups(self)
        # Mesa: The set agents_by_type[ResidentGroup] contains all resident groups.
        # The group rules use this set. Other agent types therefore do not receive these
        # rules or change the group results. Mesa updates the set. Use it to read and
        # loop over groups, but do not add or remove agents in it.
        self.groups = self.agents_by_type[ResidentGroup]

        # SET-UP 5: The model links the groups in an assumed social network.
        model_functions.link_social_network(self)

        # SET-UP 6: The model creates one municipality, the second agent type.
        Municipality(self)  # Mesa: Creating the agent adds it to the model.
        # Mesa: This set contains all municipalities, just as self.groups contains all groups.
        self.municipalities = self.agents_by_type[Municipality]

        # SET-UP 7: The model prepares the water-point and result data.
        # These dictionaries use the junction of each point as the key.
        self.available_water_litres = {}  # This stores the litres each point can supply in a step.
        self.remaining_water_litres = {}  # This tracks the litres left as groups collect water.
        # This stores the litres requested at each point per step.
        self.requested_water_litres = {}
        # This is the percentage of total need met at home or at a point.
        self.water_need_met_percent = 0.0
        # This is the percentage of groups without a known water point.
        self.groups_without_point_percent = model_functions.calculate_groups_without_point_percent(
            self
        )
        # This is the number of pipes that are still broken.
        self.broken_pipe_count = len(self.infrastructure.broken_pipes)

        # SET-UP 8: The model tells Mesa which values to record.
        self.datacollector = model_functions.set_up_data_collection(self)
        # Mesa: collect() saves the starting state as one row, before any water is used.
        self.datacollector.collect(self)

    def step(self):  # Mesa: The run_for() method calls step() once for every time unit.
        """Run one step: supply, decide, collect, learn, summarise, observe and repair."""
        # Mesa: self.time increases by one at the start of each step. Multiply it by the
        # step length to get hours. After 4 steps of 6 hours, 4 * 6 / 24 = 1 day has passed.
        self.elapsed_days = self.time * self.time_step_hours / 24

        # 1. Each point's water supply equals its current hourly flow times the step length
        # in hours. At 450 litres per hour, a point supplies 450 * 6 = 2,700 litres in a
        # six-hour step. Water left from the previous step is not kept.
        for point_name in self.infrastructure.water_points:
            self.available_water_litres[point_name] = (
                self.infrastructure.current_point_flow_litres_per_hour[point_name]
                * self.time_step_hours
            )
            self.remaining_water_litres[point_name] = self.available_water_litres[point_name]
            self.requested_water_litres[point_name] = 0.0

        # 2. Every group decides before any group collects water.
        self.groups.do("choose_water_point")  # Mesa: do() runs the rule once for every group.

        # 3. The groups take water in a random order.
        # Mesa: shuffle_do runs the rule in a new random order each step. This means
        # the first group to collect water changes at random between steps.
        self.groups.shuffle_do("collect_water")

        # 4. Once a day, the groups learn from their contacts.
        # After each full day, elapsed_days is a whole number, such as 1.0 or 2.0.
        # The call is_integer() then returns True.
        if self.share_information and self.elapsed_days.is_integer():
            self.groups.do("learn_from_contacts")  # Mesa: The rule runs once for every group.

        # 5. The model summarises this step.
        # Mesa: agg("attribute", sum) sums that attribute across all groups.
        total_need_litres = self.groups.agg("water_need_litres", sum)
        total_unmet_litres = self.groups.agg("unmet_water_litres", sum)
        # For example, a need of 1,000 litres with 250 litres unmet gives
        # 100 * (1 - 250 / 1000) = 75%.
        self.water_need_met_percent = 100 * (1 - total_unmet_litres / total_need_litres)
        self.groups_without_point_percent = model_functions.calculate_groups_without_point_percent(
            self
        )

        # 6. The municipality observes the city. Each agent type has its own call here.
        self.municipalities.do("observe_city")  # Mesa: The rule runs once for every municipality.

        # 7. Repairs completed now affect the next step's water supply.
        self.infrastructure.advance_recovery(self.elapsed_days)
        # The len() function counts the items in a list.
        self.broken_pipe_count = len(self.infrastructure.broken_pipes)

        # 8. Mesa: collect() saves one row of results. Water results cover the step that
        # just ended. The broken-pipe count describes the state at the end of that step.
        self.datacollector.collect(self)
        # Mesa: self.steps counts steps so far, including the current step.
        # The batch runner stops a run when running is False.
        if self.steps >= self.number_of_steps:
            self.running = False

    def open_water_point(self, junction_name):
        """Add a public water point during a run using model_functions.py."""
        model_functions.open_water_point(self, junction_name)
