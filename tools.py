def search_flights(slices: list[dict]) -> list[dict]:
    """Return two fake flight offers for the first requested slice."""
    first = slices[0]
    departure_date = first["departure_date"]
    origin = first["origin"]
    destination = first["destination"]

    return [
        {
            "offer_id": "fake-BA-001",
            "airline": "British Airways",
            "price": "129.99",
            "currency": "GBP",
            "depart_at": f"{departure_date}T08:00:00",
            "origin": origin,
            "destination": destination,
        },
        {
            "offer_id": "fake-VS-002",
            "airline": "Virgin Atlantic",
            "price": "149.99",
            "currency": "GBP",
            "depart_at": f"{departure_date}T12:30:00",
            "origin": origin,
            "destination": destination,
        },
    ]


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_flights",
            "description": "Return fake demo flight offers for the first slice. Use IATA airport codes and YYYY-MM-DD dates.",
            "parameters": {
                "type": "object",
                "properties": {
                    "slices": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "origin": {"type": "string"},
                                "destination": {"type": "string"},
                                "departure_date": {"type": "string"},
                            },
                            "required": ["origin", "destination", "departure_date"],
                        },
                    }
                },
                "required": ["slices"],
            },
        },
    }
]
