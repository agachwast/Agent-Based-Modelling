"""
Resident groups and the municipality.

Use this file to change agent attributes. To change how agents make decisions, edit
agent_functions.py. The methods here call the rules defined in that file. Read this file
after model.py and before agent_functions.py.


What is in this file, from top to bottom
----------------------------------------
ResidentGroup         A group of residents who live at the same junction and decide
                      together. A junction is where pipes meet and supply connected homes.
choose_water_point()  Calls agent_functions.choose_water_point.
collect_water()       Calls agent_functions.collect_water.
learn_from_contacts() Calls agent_functions.learn_from_contacts.
Municipality          A placeholder that observes the city. Use it as an example when
                      defining, creating and activating another agent type.
observe_city()        Calls agent_functions.observe_city.

The model in model.py creates the resident groups. During each step, it calls their three
rules in the order listed above. Mesa calls a rule by its method name, so each rule needs
a one-line method in the class.

Each resident group has one profile, such as "elderly". The parameter people_per_group
sets the target number of residents per group. The supplied profiles differ only in how
far they can walk.

In a resident group's methods, self refers to that group. The attribute self.model gives
access to the model shared by all groups. Comments starting with "Mesa:" explain the Mesa
calls. The section "Mesa tools used in the code" in README.md lists the tools used here.
"""

from mesa import Agent  # Mesa: Agent represents an agent without a position in a space.

# Mesa: CellAgent represents an agent that occupies a cell and can move to another.
# Each cell in this model corresponds to one node of the water network.
from mesa.discrete_space import CellAgent

from model import agent_functions  # The agent rules are defined in this module.

# =========================================================================================
# Resident groups and their rules
# =========================================================================================


# Mesa: Using CellAgent gives ResidentGroup the Mesa agent tools and lets it move.
class ResidentGroup(CellAgent):
    """Represent residents who live at one junction and make decisions together."""

    def __init__(
        self,
        model,
        cell,
        home_junction,
        population,
        district,
        profile,
        walking_distance_m,
        reachable_point_distances_m,
    ):
        """Store the group's attributes, place it at home and assign its first water point."""
        super().__init__(model)  # Mesa: This adds the group to the model and assigns its unique_id.

        # ---------------------------------------------------------------------------------
        # Agent attributes supplied when the agent is created
        # ---------------------------------------------------------------------------------

        self.cell = cell  # Mesa: Assigning cell places the group at home.
        self.home_junction = home_junction  # This junction supplies the group's homes.
        self.population = population  # This is an average number of residents, so it can be 8.75.
        self.district = district  # The group lives in this district.
        self.profile = profile  # This names the group's profile, such as "elderly".
        self.walking_distance_m = walking_distance_m  # The group can walk up to this distance.
        # Each entry gives a reachable point and its distance from home: {point: metres}.
        self.reachable_point_distances_m = reachable_point_distances_m

        # ---------------------------------------------------------------------------------
        # Agent attributes calculated or initialised by the model
        # ---------------------------------------------------------------------------------

        self.home_cell = cell  # The group returns to this cell at the start of every step.
        self.contacts = []  # The model assigns social contacts once all groups exist.
        self.chosen_water_point = None  # This is the point visited in the current step, or None.
        self.water_need_litres = 0.0  # The group needs this many litres in the current step.
        self.home_water_litres = 0.0  # The homes receive this many litres from the pipes.
        self.collected_water_litres = 0.0  # The group collects this many litres at a public point.
        self.unmet_water_litres = 0.0  # The group still needs this many litres after collection.

        # A group knows at most one water point. It starts with the nearest point it can
        # reach on foot, or None if no point is within walking distance.
        self.known_water_point = agent_functions.find_nearest_point(
            self.reachable_point_distances_m
        )

    def choose_water_point(self):
        """Use water at home, then visit the known point if the group still needs water."""
        agent_functions.choose_water_point(self)

    def collect_water(self):
        """Collect enough water to meet the remaining need, limited by the point's supply."""
        agent_functions.collect_water(self)

    def learn_from_contacts(self):
        """Learn about a water point from a contact if the group does not know one."""
        agent_functions.learn_from_contacts(self)


# =========================================================================================
# Municipality: an example of a second agent type
# =========================================================================================


# Mesa: Municipality uses Agent because it does not occupy a cell in the water network.
class Municipality(Agent):
    """Record observations about the city without changing water access."""

    def __init__(self, model):
        """Set the initial observation to zero."""
        super().__init__(model)  # Mesa: This adds the municipality to the model.

        # ---------------------------------------------------------------------------------
        # Agent attributes calculated or initialised by the model
        # ---------------------------------------------------------------------------------

        self.observed_groups_without_point_percent = 0.0  # This is the last observed percentage.

    def observe_city(self):
        """Record the share of groups without a known water point at the end of the step."""
        agent_functions.observe_city(self)
