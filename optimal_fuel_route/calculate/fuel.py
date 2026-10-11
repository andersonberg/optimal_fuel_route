class FuelPlanError(Exception):
    pass


def plan_fuel_stops(stations, total_miles, max_range=500, mpg=10):
    """Choose where to buy fuel along a route to make the whole trip as cheap as possible.

    Args:
        stations: A list of (stop, mile_marker, price) tuples.
        total_miles: The total miles of the route.
        max_range: The maximum range of the vehicle in miles.
        mpg: The miles per gallon of the vehicle.

    Returns:
        {'stops', 'total_gallons', 'total_cost'}, where 'stops' is a list of
        {'stop', 'mile', 'price', 'gallons', 'cost'} for a station where fuel is bought,
        'total_gallons' is the total gallons of fuel bought, and 'total_cost' is the total cost of fuel bought.

    The vehicle starts with a full tank that costs nothing, and ends the trip empty. Only fuel bought
    at stations is counted. Stops are returned in order of purchase.
    """
    stations = sorted((s for s in stations if s[1] < total_miles), key=lambda s: s[1])

    stops = []
    current = None  # the station we are at; None at the start
    position = 0.0
    fuel = float(max_range)  # miles of range left in the tank
    price = float('inf')  # nothing is bought at the start, so any station counts as cheaper

    while True:
        reachable = [s for s in stations if position < s[1] <= position + max_range]
        finish_reachable = total_miles - position <= max_range

        # Buy just enough to reach the next cheaper station, or the finish if none comes first.
        target = next((s for s in reachable if s[2] < price), None)
        if target is not None:
            destination = target[1]
            buy_miles = max(0.0, destination - position - fuel)
        elif finish_reachable:
            destination = total_miles
            buy_miles = max(0.0, destination - position - fuel)
        else:
            # Nothing cheaper in range: fill up and go to the cheapest station we can reach.
            if not reachable:
                raise FuelPlanError(
                    f'No fuel station within {max_range} miles after mile {position:.0f} of the route.'
                )
            target = min(reachable, key=lambda s: (s[2], -s[1]))
            destination = target[1]
            buy_miles = max_range - fuel

        if buy_miles > 0:
            gallons = buy_miles / mpg
            stops.append({
                'stop': current[0], 'mile': current[1], 'price': price,
                'gallons': gallons, 'cost': gallons * price,
            })

        fuel += buy_miles - (destination - position)
        position = destination
        if target is None:  # reached the finish
            break
        current = target
        price = target[2]

    return {
        'stops': stops,
        'total_gallons': sum(s['gallons'] for s in stops),
        'total_cost': sum(s['cost'] for s in stops),
    }
