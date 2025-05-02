from typing import List, Dict

# Template generator helpers for each state
def get_destinations() -> List[Dict]:
    return [
        {"id": "paris", "title": "Paris"},
        {"id": "tokyo", "title": "Tokyo"},
        {"id": "new_york", "title": "New York"},
        {"id": "bali", "title": "Bali"},
        {"id": "maldives", "title": "Maldives"},
        {"id": "london", "title": "London"},
        {"id": "dubai", "title": "Dubai"},
        {"id": "sydney", "title": "Sydney"},
        {"id": "rome", "title": "Rome"},
        {"id": "other", "title": "Other"}
    ]

def get_budget_options(currency_symbol="₹") -> List[Dict]:
    return [
        {"id": "50000_100000", "title": f"{currency_symbol}50K–{currency_symbol}1L"},
        {"id": "100000_200000", "title": f"{currency_symbol}1L–{currency_symbol}2L"},
        {"id": "200000_500000", "title": f"{currency_symbol}2L–{currency_symbol}5L"},
        {"id": "custom_budget", "title": "Custom"}
    ]
