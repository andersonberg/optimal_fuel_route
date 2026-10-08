import re


def normalize_city(name):
    """Turn a city name into a lookup key, e.g. 'St. Louis' and 'Saint Louis' -> 'saintlouis'."""
    name = re.sub(r'\bst\b', 'saint', name.lower())
    return re.sub(r'[^a-z0-9]', '', name)
