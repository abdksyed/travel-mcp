import json
import urllib.error
import urllib.parse
import urllib.request

import config
from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

RAILRADAR_URL = "https://api.railradar.in/v1"
requests_made = 0


def railradar(path: str, payload: dict | None = None) -> dict:
    """Call RailRadar and return the data field. GET when payload is None, POST otherwise.

    Every failure becomes a ToolError, because only ToolError text reaches the model.
    """
    global requests_made
    requests_made += 1
    # the free tier is 100 a month, so make the drain visible
    print(f"[railradar] request {requests_made}: {path.split('?')[0]}", flush=True)

    method = "POST" if payload is not None else "GET"
    request = urllib.request.Request(
        RAILRADAR_URL + path,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={
            "Authorization": f"Bearer {config.keys['railradar']}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.load(response)["data"]
    except urllib.error.HTTPError as error:
        raise ToolError(f"RailRadar {error.code}: {error.read().decode()}") from error
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
        raise ToolError(
            f"RailRadar request to {path.split('?')[0]} failed: {error}"
        ) from error


def slim_leg(leg: dict) -> dict:
    """One train on one leg, without coordinates and display noise."""
    return {
        "train": leg["train"]["number"],
        "name": leg["train"]["name"],
        "classes": leg["train"]["classes"],
        "from": leg["from"]["code"],
        "depart": f"{leg['from']['date']} {leg['from']['departure']}",
        "to": leg["to"]["code"],
        "arrive": f"{leg['to']['date']} {leg['to']['arrival']}",
        "minutes": leg["durationMinutes"],
        "expected_delay": leg.get("expectedDelayMinutes"),
        "reliability": leg.get("reliability"),
    }


mcp = MCPServer("rail-http", version="0.1.0")


@mcp.tool()
def search_stations(query: str) -> list[dict]:
    """Search Indian Railways stations by name or code."""
    q = urllib.parse.quote(query)
    stations = railradar(f"/lookup/search/stations?q={q}&limit=5")
    return [{"code": s["code"], "name": s["name"], "city": s["city"]} for s in stations]


@mcp.tool()
def plan_journey(
    stops: list[dict],
    date: str,
    max_transfers: int = 1,
    depart_after: str | None = None,
    arrive_before: str | None = None,
    categories: list[str] | None = None,
) -> dict:
    """Plan a train trip over 2 to 6 stops in one call.

    Each stop is {station, stayDays?} with a station code. stayDays is nights in
    that city before moving on, and the onward date is computed for you.
    date is the start date, YYYY-MM-DD. depart_after and arrive_before are HH:MM.
    categories filters trains, e.g. ["Rajdhani/Shatabdi"] or ["Vande Bharat"].
    """
    body = {
        "stops": stops,
        "date": date,
        "maxTransfers": max_transfers,
        "maxItineraries": 3,
        "departAfter": depart_after,
        "arriveBefore": arrive_before,
    }
    if categories:
        body["categories"] = categories
    data = railradar("/journeys/plan", body)

    segments = []
    for segment in data["segments"]:
        plan = segment["plan"]
        segments.append(
            {
                "from": segment["from"],
                "to": segment["to"],
                "date": segment["date"],
                "direct": [slim_leg(leg) for leg in plan["direct"][:5]],
                "connections": [
                    {
                        "legs": [slim_leg(leg) for leg in it["legs"]],
                        "minutes": it["totalDurationMinutes"],
                        "risk": it["overallRisk"],
                    }
                    for it in plan["itineraries"][:3]
                ],
            }
        )
    return {"segments": segments, "summary": data["summary"]}


@mcp.tool()
def train_fare(
    train: str, from_station: str, to_station: str, date: str, travel_class: str
) -> dict:
    """Fare for one train between two station codes on a YYYY-MM-DD date.

    travel_class is one of 1A, 2A, 3A, 3E, CC, EC, SL, 2S. General quota.
    """
    query = urllib.parse.urlencode(
        {
            "source": from_station,
            "destination": to_station,
            "journeyDate": date,
            "classCode": travel_class,
        }
    )
    data = railradar(f"/trains/{urllib.parse.quote(train)}/fare?{query}")
    # nine line breakdown, one number the model needs
    return {
        "train": data["trainNumber"],
        "name": data["trainName"],
        "class": travel_class,
        "total_fare_inr": data["breakdown"]["totalFare"],
    }


@mcp.resource("rail://stations")
def stations() -> str:
    """Every station code to name."""
    return json.dumps(railradar("/lookup/stations"))


@mcp.resource("rail://trains")
def trains() -> str:
    """Every train number to name."""
    return json.dumps(railradar("/lookup/trains"))


if __name__ == "__main__":
    mcp.run(transport="streamable-http", port=8001)
