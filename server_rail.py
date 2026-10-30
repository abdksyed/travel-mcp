import asyncio
import http.client
import json
import urllib.error
import urllib.parse
import urllib.request

import config
from mcp.server import MCPServer
from mcp.server.mcpserver import Context
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
    # OSError covers URLError, timeouts and a connection reset mid-read
    except (OSError, http.client.HTTPException, json.JSONDecodeError) as error:
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


@mcp.tool()
async def check_fares(
    trains: list[str],
    from_station: str,
    to_station: str,
    date: str,
    travel_class: str,
    ctx: Context,
) -> list[dict]:
    """Price several trains on the same route in one call. Reports progress as it goes.

    Same arguments as train_fare, with a list of train numbers.
    """
    fares = []
    for i, train in enumerate(trains, 1):
        # a sync tool runs on a worker thread and cannot report, so this one is async
        await ctx.report_progress(i - 1, len(trains), f"pricing {train}")
        try:
            fare = await asyncio.to_thread(
                train_fare, train, from_station, to_station, date, travel_class
            )
        except ToolError as error:
            fare = {"train": train, "error": str(error)}
        fares.append(fare)
    await ctx.report_progress(len(trains), len(trains), "done")
    return fares


@mcp.resource("rail://stations")
def stations() -> str:
    """Every station code to name."""
    return json.dumps(railradar("/lookup/stations"))


@mcp.resource("rail://trains")
def trains() -> str:
    """Every train number to name."""
    return json.dumps(railradar("/lookup/trains"))


@mcp.prompt()
def plan_trip(request: str) -> str:
    """Plan a whole trip from a plain English request.

    e.g. "Bangalore to Mumbai to Delhi by train from 5 December, then London and
    New York, 2 nights each in India, 3 abroad, budget 4 lakh".
    """
    return f"""Plan a complete trip from this request:

{request}

Read the route, start date, nights per city, travellers, train class, budget and
interests from the request. Anything it does not say: 1 adult, train class 3A,
2 nights per city, no fixed budget, interests food, history and local markets.
If the start date is missing, ask for it instead of guessing.

Transport
- Between two Indian cities, go by train. Find station codes with search_stations,
  then route every Indian leg in one plan_journey call, using stayDays for the
  nights. Nothing should depart before 06:00 or arrive after 22:00.
- Price the chosen trains with check_fares in the requested class, one call
  per leg.
- Any leg that leaves India or runs between two cities outside India is a flight.
  Use search_flights with IATA codes and pick the cheapest sensible offer.
- Overnight trains and long flights arrive the next day. Shift the hotel dates
  so the nights in each city stay as asked.

Hotels
- One hotel per city for exactly those nights. Use post_hotels_rates with
  cityName and countryCode, limit 3, maxRatesPerHotel 1, currency INR,
  guestNationality IN.
- For the hotel you pick, read get_data_reviews with limit 5 and say in one
  line what guests like or dislike.

Things to do
- Two or three things per day in each city, matching the interests.
- No tool covers this. Use what you know and say so.

If the total goes over the budget, say which choice to change.

Answer with
1. A day by day table: date, city, what happens.
2. A transport table: leg, train or flight number, depart, arrive, price.
3. A hotel table: city, hotel, rating, dates, total price.
4. A total in INR. Convert other currencies roughly and say that you did.

Do not book or prebook anything. Trains cannot be booked here, so point to
https://www.irctc.co.in for those."""

if __name__ == "__main__":
    mcp.run(transport="streamable-http", port=8001)
