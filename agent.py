import asyncio
import json
from contextlib import AsyncExitStack
from datetime import date
from pathlib import Path

from mcp import Client, StdioServerParameters
from openai import OpenAI

import config

here = Path(__file__).parent
servers = {
    "flights": StdioServerParameters(
        command="uv", args=["run", "python", "server_flights.py"], cwd=here
    ),
    # start it first: uv run python server_rail.py
    "rail": "http://127.0.0.1:8001/mcp",
}

PROMPT = (
    "get me from Mumbai to Delhi on 5 December. Compare train and flight, "
    "and tell me which is better value."
)


async def main():
    llm = OpenAI(api_key=config.API_KEY, base_url=config.BASE_URL)

    async with AsyncExitStack() as stack:
        clients = {}
        tools = []
        for name, target in servers.items():
            c = await stack.enter_async_context(Client(target))
            clients[name] = c
            listed = (await c.list_tools()).tools
            transport = "http" if isinstance(target, str) else "stdio"
            print(f"[connect] {name:8} {transport:6} {len(listed)} tools")

            # Two servers may both have a plan_journey. The prefix is the host's job.
            for t in listed:
                tools.append(
                    {
                        "type": "function",
                        "function": {
                            "name": f"{name}__{t.name}",
                            "description": t.description,
                            "parameters": t.input_schema,
                        },
                    }
                )
        print(f"[catalog] {len(tools)} tools from {len(clients)} servers")
        print("catalog:", [t["function"]["name"] for t in tools])

        messages = []

        # The application decides what the model may know, before it is asked.
        # rail://stations and rail://trains are 13k entries each, so they stay out.
        for uri in ("flights://policy/baggage", "flights://airports"):
            r = await clients["flights"].read_resource(uri)
            print("[resource]", uri, "->", len(r.contents[0].text), "chars")
            messages.append(
                {"role": "system", "content": f"{uri}\n{r.contents[0].text}"}
            )

        system = f"You are a concise travel assistant. Today is {date.today()}."
        messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": PROMPT})

        while True:
            response = llm.chat.completions.create(
                model=config.MODEL, messages=messages, tools=tools
            )
            message = response.choices[0].message

            if not message.tool_calls:
                print("Agent:", message.content)
                print("usage:", response.usage.model_dump_json())
                break

            messages.append(message.model_dump(exclude_none=True))

            for call in message.tool_calls:
                arguments = json.loads(call.function.arguments)
                print(f"[tool]    {call.function.name}({json.dumps(arguments)})")

                # Dispatch on the prefix. The host does not care which one is a pipe.
                server, tool = call.function.name.split("__", 1)
                r = await clients[server].call_tool(tool, arguments)

                # Three shapes: a list arrives as one block per element, a dict as one
                # block, and an error as one block with structured_content None.
                if r.is_error:
                    content = "\n".join(b.text for b in r.content)
                elif r.structured_content is not None:
                    content = json.dumps(r.structured_content)
                else:
                    content = "\n".join(b.text for b in r.content)

                print("         ->", content.splitlines()[0][:70])

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": content,
                    }
                )


asyncio.run(main())
