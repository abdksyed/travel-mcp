import asyncio
import json
from pathlib import Path

from mcp import Client, StdioServerParameters
from openai import OpenAI

import config

here = Path(__file__).parent
params = StdioServerParameters(
    command="uv", args=["run", "python", "server_flights.py"], cwd=here
)

PROMPT = "what is the baggage allowance from BOM to DEL, and which airport is DEL?"


async def main():
    llm = OpenAI(api_key=config.API_KEY, base_url=config.BASE_URL)

    async with Client(params) as c:
        print("[connect] flights via stdio")

        tools = []
        for t in (await c.list_tools()).tools:
            print("[list]   ", t.name, "|", t.description.splitlines()[0])
            tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.input_schema,
                    },
                }
            )

        messages = []

        # The application decides what the model may know, before it is asked.
        for uri in ("flights://policy/baggage", "flights://airports"):
            r = await c.read_resource(uri)
            print("[resource]", uri, "->", len(r.contents[0].text), "chars")
            messages.append(
                {"role": "system", "content": f"{uri}\n{r.contents[0].text}"}
            )

        messages.append({"role": "system", "content": "You are a concise travel assistant."})
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

                r = await c.call_tool(call.function.name, arguments)

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