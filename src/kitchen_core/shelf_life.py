"""
Shelf-life knowledge base for smart expiry date pre-fill.

Returns a default expiry date based on ingredient name (fuzzy-matched)
and storage location (fridge / freezer / pantry / counter).

All estimates are conservative "use-by" ranges.
Source: USDA FoodKeeper / SFA Singapore guidelines.
"""

from datetime import date, timedelta
from typing import Optional

STORAGE_OPTIONS = ["fridge", "freezer", "pantry", "counter"]

# (keywords, {storage: days}) — longest keyword match wins
_RULES: list[tuple[tuple[str, ...], dict[str, Optional[int]]]] = [
    # --- Meat & Seafood ---
    (("chicken", "poultry", "duck", "turkey"),
     {"fridge": 2, "freezer": 270, "pantry": None, "counter": None}),
    (("beef", "steak", "mince", "minced", "ground beef"),
     {"fridge": 3, "freezer": 120, "pantry": None, "counter": None}),
    (("pork", "bacon", "lard"),
     {"fridge": 3, "freezer": 120, "pantry": None, "counter": None}),
    (("fish", "salmon", "tuna", "cod", "tilapia", "mackerel", "ikan"),
     {"fridge": 2, "freezer": 180, "pantry": None, "counter": None}),
    (("prawn", "shrimp", "squid", "crab", "seafood"),
     {"fridge": 2, "freezer": 90, "pantry": None, "counter": None}),
    # --- Dairy ---
    (("milk", "susu"),
     {"fridge": 7, "freezer": 90, "pantry": None, "counter": None}),
    (("cream", "whipping cream", "heavy cream"),
     {"fridge": 7, "freezer": 60, "pantry": None, "counter": None}),
    (("butter", "mentega"),
     {"fridge": 30, "freezer": 270, "pantry": 3, "counter": 3}),
    (("cheese", "keju"),
     {"fridge": 21, "freezer": 180, "pantry": None, "counter": None}),
    (("yogurt", "yoghurt"),
     {"fridge": 14, "freezer": 60, "pantry": None, "counter": None}),
    (("egg", "telur"),
     {"fridge": 35, "freezer": None, "pantry": 21, "counter": 14}),
    # --- Fresh Produce ---
    (("leafy", "spinach", "lettuce", "kangkung", "bayam", "salad"),
     {"fridge": 5, "freezer": None, "pantry": None, "counter": 2}),
    (("broccoli", "cauliflower", "brocoli"),
     {"fridge": 7, "freezer": 365, "pantry": None, "counter": 2}),
    (("carrot", "wortel"),
     {"fridge": 21, "freezer": 365, "pantry": None, "counter": 5}),
    (("tomato", "tomat"),
     {"fridge": 7, "freezer": None, "pantry": 5, "counter": 5}),
    (("potato", "kentang"),
     {"fridge": 90, "freezer": None, "pantry": 60, "counter": 30}),
    (("onion", "bawang merah", "shallot"),
     {"fridge": 60, "freezer": None, "pantry": 30, "counter": 14}),
    (("garlic", "bawang putih"),
     {"fridge": 90, "freezer": None, "pantry": 60, "counter": 30}),
    (("ginger", "halia", "jahe"),
     {"fridge": 30, "freezer": 180, "pantry": 14, "counter": 7}),
    (("lemon", "lime", "limau"),
     {"fridge": 21, "freezer": None, "pantry": 7, "counter": 7}),
    (("banana", "pisang"),
     {"fridge": 7, "freezer": 90, "pantry": 5, "counter": 5}),
    (("apple", "epal"),
     {"fridge": 42, "freezer": None, "pantry": 14, "counter": 7}),
    (("cucumber", "timun"),
     {"fridge": 7, "freezer": None, "pantry": None, "counter": 3}),
    (("capsicum", "pepper", "bell pepper"),
     {"fridge": 14, "freezer": 365, "pantry": None, "counter": 4}),
    (("chilli", "chili", "cili"),
     {"fridge": 14, "freezer": 180, "pantry": None, "counter": 5}),
    (("mushroom", "cendawan"),
     {"fridge": 7, "freezer": 365, "pantry": None, "counter": 2}),
    # --- Condiments & Sauces ---
    (("soy sauce", "kicap", "kecap"),
     {"fridge": 730, "freezer": None, "pantry": 365, "counter": 365}),
    (("fish sauce", "sos ikan"),
     {"fridge": 730, "freezer": None, "pantry": 365, "counter": 365}),
    (("oyster sauce", "sos tiram"),
     {"fridge": 180, "freezer": None, "pantry": 90, "counter": None}),
    (("sesame oil", "minyak bijan"),
     {"fridge": 365, "freezer": None, "pantry": 180, "counter": None}),
    (("chilli sauce", "sos cili", "sriracha", "tabasco"),
     {"fridge": 365, "freezer": None, "pantry": 180, "counter": None}),
    (("tomato sauce", "ketchup", "tomato paste"),
     {"fridge": 180, "freezer": None, "pantry": 365, "counter": None}),
    (("mayonnaise", "mayo"),
     {"fridge": 60, "freezer": None, "pantry": None, "counter": None}),
    (("vinegar", "cuka"),
     {"fridge": None, "freezer": None, "pantry": 1825, "counter": 1825}),
    (("honey", "madu"),
     {"fridge": None, "freezer": None, "pantry": 3650, "counter": 3650}),
    # --- Dry Pantry ---
    (("rice", "beras", "nasi"),
     {"fridge": None, "freezer": None, "pantry": 730, "counter": 730}),
    (("flour", "tepung"),
     {"fridge": None, "freezer": None, "pantry": 365, "counter": 365}),
    (("sugar", "gula"),
     {"fridge": None, "freezer": None, "pantry": 1825, "counter": 1825}),
    (("salt", "garam"),
     {"fridge": None, "freezer": None, "pantry": 1825, "counter": 1825}),
    (("oil", "minyak"),
     {"fridge": None, "freezer": None, "pantry": 365, "counter": 365}),
    (("coconut milk", "santan"),
     {"fridge": 4, "freezer": 90, "pantry": 730, "counter": None}),
    (("pasta", "spaghetti", "noodle", "mee", "mi"),
     {"fridge": None, "freezer": None, "pantry": 730, "counter": None}),
    (("bread", "roti"),
     {"fridge": 14, "freezer": 90, "pantry": 5, "counter": 3}),
    (("tofu", "tahu", "tempe", "tempeh"),
     {"fridge": 7, "freezer": 90, "pantry": None, "counter": None}),
]


def get_default_expiry(ingredient_name: str, storage_location: str) -> Optional[date]:
    """Return a default expiry date for ingredient_name at storage_location, or None."""
    if storage_location not in STORAGE_OPTIONS:
        storage_location = "pantry"

    name_lower = ingredient_name.lower().strip()
    best_match_len = 0
    best_days: Optional[int] = None

    for keywords, shelf_map in _RULES:
        for kw in keywords:
            if kw in name_lower and len(kw) > best_match_len:
                best_match_len = len(kw)
                best_days = shelf_map.get(storage_location)

    if best_days is None:
        return None
    return date.today() + timedelta(days=best_days)


def get_storage_guess(ingredient_name: str) -> str:
    """
    Guess the most likely storage location for an ingredient.
    Returns one of: fridge, freezer, pantry, counter.
    Longest keyword match wins.
    """
    name_lower = ingredient_name.lower().strip()

    _GUESS_RULES: list[tuple[tuple[str, ...], str]] = [
        (("frozen", "ice cream", "ais krim"), "freezer"),
        (("fish sauce", "sos ikan", "fish ball", "fishball", "fish cake", "fish fingers"), "pantry"),
        (("tomato sauce", "tomato paste", "tomato ketchup", "ketchup", "tomato puree"), "pantry"),
        (("soy sauce", "dark soy", "light soy", "kicap", "kecap",
          "oyster sauce", "sos tiram", "chilli sauce", "sos cili",
          "sriracha", "tabasco", "sambal", "sesame oil", "minyak bijan",
          "coconut milk", "santan"), "pantry"),
        (("cooking oil", "vegetable oil", "olive oil", "sunflower oil",
          "palm oil", "canola oil"), "pantry"),
        (("vinegar", "cuka", "honey", "madu",
          "sugar", "gula", "salt", "garam",
          "rice", "beras", "flour", "tepung",
          "pasta", "spaghetti", "noodle", "mee"), "pantry"),
        (("chicken", "poultry", "duck", "turkey",
          "beef", "steak", "pork", "bacon",
          "prawn", "shrimp", "squid", "crab", "seafood",
          "salmon", "tuna", "cod", "tilapia", "mackerel"), "fridge"),
        (("fish", "ikan"), "fridge"),
        (("milk", "susu", "cream", "butter", "mentega",
          "cheese", "keju", "yogurt", "yoghurt",
          "egg", "telur"), "fridge"),
        (("tofu", "tahu", "tempe", "tempeh"), "fridge"),
        (("broccoli", "cauliflower", "leafy", "spinach",
          "lettuce", "kangkung", "bayam",
          "cucumber", "timun", "capsicum"), "fridge"),
        (("banana", "pisang", "avocado", "alpukat"), "counter"),
        (("tomato", "tomat"), "counter"),
    ]

    if "frozen" in name_lower:
        return "freezer"

    best_len = 0
    best_storage = "pantry"

    for keywords, storage in _GUESS_RULES:
        for kw in keywords:
            if kw in name_lower and len(kw) > best_len:
                best_len = len(kw)
                best_storage = storage

    return best_storage
