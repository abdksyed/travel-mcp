import asyncio

from mcp import Client, StdioServerParameters

params = StdioServerParameters(command="uv", args=["run", "python", "server_flights.py"])


async def main():
    async with Client(params) as c:
        print("protocol:", c.protocol_version)
        print("server:", c.server_info.name, c.server_info.version)
        for t in (await c.list_tools()).tools:
            print("tool:", t.name, "|", t.description.splitlines()[0])
        r = await c.call_tool(
            "search_flights",
            {
                "slices": [
                    {"origin": "BOM", "destination": "DEL", "departure_date": "2026-12-05"}
                ]
            },
        )
        print("result:", r.structured_content)


asyncio.run(main())