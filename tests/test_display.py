import display


def test_retailer_names_are_capitalized():
    assert display.retailer_name("target") == "Target"
    assert display.retailer_name("bestbuy") == "Best Buy"
    assert display.retailer_name("bn") == "Barnes & Noble"
    assert display.retailer_name("pokemon_center") == "Pokémon Center"
    assert display.retailer_name("amazon") == "Amazon"


def test_game_names_are_capitalized():
    assert display.game_name("pokemon") == "Pokémon"
    assert display.game_name("mtg") == "Magic: The Gathering"
    assert display.game_name("yugioh") == "Yu-Gi-Oh!"
    assert display.game_name("onepiece") == "One Piece"


def test_status_label_distinguishes_blocked_from_generic_error():
    """Regression guard: these must read as genuinely different things on
    the dashboard, not both collapse into a generic 'Error checking
    stock' — that distinction is the whole point of the fix."""
    assert display.status_label("BLOCKED_OR_KEY_INVALID") == "Blocked by retailer"
    assert display.status_label("RATE_LIMITED") == "Rate limited, will retry"
    assert display.status_label("UNEXPECTED_RESPONSE") == "Unexpected response"
    assert display.status_label("NOT_FOUND") == "Not found"


def test_unknown_retailer_falls_back_to_title_case():
    assert display.retailer_name("some_new_store") == "Some New Store"


def test_unknown_game_falls_back_to_title_case():
    assert display.game_name("some_new_game") == "Some New Game"
