import json
import urllib.error
import urllib.parse
import urllib.request

import config
from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

DUFFEL_URL = "https://api.duffel.com"


def duffel(path: str, payload: dict | None = None) -> dict:
    """Call the Duffel API. GET when payload is None, POST otherwise.

    Every failure becomes a ToolError, because only ToolError text reaches the model.
    """
    method = "POST" if payload is not None else "GET"
    request = urllib.request.Request(
        DUFFEL_URL + path,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={
            "Authorization": f"Bearer {config.keys['duffel']}",
            "Duffel-Version": "v2",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        raise ToolError(f"Duffel {error.code}: {error.read().decode()}") from error
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
        raise ToolError(
            f"Duffel request to {path.split('?')[0]} failed: {error}"
        ) from error


mcp = MCPServer("flights", version="0.1.0")


@mcp.tool()
def search_flights(slices: list[dict]) -> list[dict]:
    """Search flights between two IATA airport codes.

    Each slice is {origin, destination, departure_date} with a YYYY-MM-DD date.
    One slice is one way. Three slices is a multi city trip.
    """
    data = duffel(
        "/air/offer_requests?return_offers=true",
        {
            "data": {
                "cabin_class": "economy",
                "slices": slices,
                "passengers": [{"type": "adult"}],
            }
        },
    )
    offers = data["data"]["offers"]
    # Duffel does not guarantee price order, so sort before truncating
    offers = sorted(offers, key=lambda o: float(o["total_amount"]))
    return [
        {
            "offer_id": offer["id"],
            "airline": offer["owner"]["name"],
            "price": offer["total_amount"],
            "currency": offer["total_currency"],
            "depart_at": offer["slices"][0]["segments"][0]["departing_at"],
        }
        for offer in offers[:10]
    ]


@mcp.tool()
def seats_for_offer(offer_id: str) -> dict:
    """Free seats per row for one offer. The raw seat map is too big for a model."""
    maps = duffel(f"/air/seat_maps?offer_id={urllib.parse.quote(offer_id, safe='')}")["data"]
    if not maps:
        return {"cabins": []}

    cabins = []
    for cabin in maps[0]["cabins"]:
        free: dict[str, int] = {}
        for row in cabin["rows"]:
            for section in row["sections"]:
                for element in section["elements"]:
                    designator = element["designator"]
                    if element["type"] != "seat" or designator is None:
                        continue
                    if element["available_services"]:
                        continue
                    free[designator[:-1]] = free.get(designator[:-1], 0) + 1
        cabins.append(
            {
                "cabin": cabin["cabin_class"],
                "rows": len(cabin["rows"]),
                "free_seats_per_row": free,
            }
        )
    return {"cabins": cabins}


@mcp.tool()
def book_flight(offer_id: str, given_name: str, family_name: str) -> dict:
    """Book one offer for one adult passenger. Test mode only."""
    offer = duffel(f"/air/offers/{urllib.parse.quote(offer_id, safe='')}")["data"]
    passenger_id = offer["passengers"][0]["id"]

    order = duffel(
        "/air/orders",
        {
            "data": {
                "type": "instant",
                "selected_offers": [offer_id],
                "payments": [
                    {
                        "type": "balance",
                        "amount": offer["total_amount"],
                        "currency": offer["total_currency"],
                    }
                ],
                "passengers": [
                    {
                        "id": passenger_id,
                        "given_name": given_name,
                        "family_name": family_name,
                        "born_on": "1990-01-01",
                        "gender": "m",
                        "title": "mr",
                        "email": "student@example.com",
                        "phone_number": "+442080160509",
                    }
                ],
            }
        },
    )["data"]

    return {
        "order_id": order["id"],
        "booking_reference": order["booking_reference"],
        "live_mode": order["live_mode"],
    }


@mcp.resource("flights://policy/baggage")
def baggage_policy() -> str:
    """Baggage rules for economy fares."""
    return (
        "Economy baggage allowance:\n"
        "- One cabin bag, 7 kg, 55 x 40 x 20 cm\n"
        "- One checked bag, 23 kg, included on long haul only\n"
        "- Domestic India economy: 15 kg checked, no free cabin bag on the lowest fare\n"
        "- Excess baggage is charged at the airport, not at booking\n"
        "These rules are the same for every passenger on every search."
    )


@mcp.resource("flights://airports")
def airports() -> str:
    """IATA code to airport name."""
    return (
        "BOM Mumbai Chhatrapati Shivaji Maharaj\n"
        "DEL Delhi Indira Gandhi\n"
        "LHR London Heathrow\n"
        "JFK New York John F Kennedy\n"
        "LAX Los Angeles International\n"
        "LON London all airports"
    )


if __name__ == "__main__":
    mcp.run(transport="stdio")