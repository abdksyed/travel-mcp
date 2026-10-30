import argparse
import asyncio
from pathlib import Path

from mcp import Client, StdioServerParameters

here = Path(__file__).parent
params = StdioServerParameters(
    command="uv", args=["run", "python", "server_flights.py"], cwd=here
)


async def main(url: str | None):
    # a URL means Streamable HTTP, otherwise spawn the flights server over stdio
    async with Client(url or params) as c:
        print("protocol:", c.protocol_version)
        print("server:", c.server_info.name, c.server_info.version)
        print("tools:", [t.name for t in (await c.list_tools()).tools])
        print("resources:", [str(r.uri) for r in (await c.list_resources()).resources])
        if url:
            return
        r = await c.call_tool(
            "search_flights",
            {
                "slices": [
                    {"origin": "BOM", "destination": "DEL", "departure_date": "2026-12-05"}
                ]
            },
        )
        print("result:", r.structured_content if not r.is_error else r.content)


parser = argparse.ArgumentParser()
parser.add_argument("--url", help="Streamable HTTP endpoint, e.g. http://127.0.0.1:8001/mcp")
asyncio.run(main(parser.parse_args().url))
