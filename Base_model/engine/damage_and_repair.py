"""
Broken pipes and the repair schedule.

You are not expected to change this file. The model calls it through engine/infrastructure.py.
The method Infrastructure.repair_pipe repairs a chosen pipe during a run.


What is in this file, from top to bottom
----------------------------------------
choose_broken_pipes()       Selects the pipes broken at the start and sets their repair order.
count_scheduled_repairs()   Returns how many pipes the schedule has repaired by a given day.
"""

import math  # The math module rounds the number of repairs down.


def choose_broken_pipes(water_network, broken_pipe_fraction, random_generator):
    """Return the broken pipes in their scheduled repair order."""
    # The smaller maps are sections of the full network. Pipes named SUPPLY at their edges
    # bring in water from the rest of the city, so they never break. Closed pipes
    # can also be selected for damage, but breaking them does not change the supply.
    breakable_pipes = []
    for pipe_name in water_network.pipe_name_list:
        if not pipe_name.startswith("SUPPLY"):
            breakable_pipes.append(pipe_name)

    # For example, breaking 0.4 of the 1,540 breakable pipes on turin_2x2 gives
    # round(616.0) = 616 broken pipes. The random sample also sets the repair order.
    # It uses the model's random-number generator, so the same seed breaks the same pipes.
    broken_count = round(len(breakable_pipes) * broken_pipe_fraction)
    return random_generator.sample(breakable_pipes, broken_count)


def count_scheduled_repairs(broken_count, elapsed_days, recovery_days):
    """Return how many scheduled repairs are complete after elapsed_days."""
    # Repairs are spread evenly over the recovery time. With 50 broken pipes and
    # 30 days to repair them, 6 days gives floor(50 * 6 / 30) = 10 completed repairs.
    # Adding 0.000001 prevents a rounding error from turning 10 into 9.999999,
    # which would round down to 9.
    repaired_fraction = min(1.0, elapsed_days / recovery_days)  # The fraction cannot exceed 1.0.
    return math.floor(broken_count * repaired_fraction + 0.000001)
