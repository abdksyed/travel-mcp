import asyncio
import json
import sys
from contextlib import AsyncExitStack
from datetime import date
from pathlib import Path

import mcp_types
from mcp import Client, StdioServerParameters
from openai import AsyncOpenAI

import config

here = Path(__file__).parent
servers = {
    "flights": StdioServerParameters(
        command="uv", args=["run", "python", "server_flights.py"], cwd=here
    ),
    # start it first: uv run python server_rail.py
    "rail": "http://127.0.0.1:8001/mcp",
    # someone else's server, on an older spec version
    "nuitee": f"https://mcp.liteapi.travel/api/mcp?apiKey={config.keys['nuitee']}",
}

# Nuitee lists 95 tools. Only these reach the model, and post_rates_book is not one.
# The experience tools return 403 on this account, so they stay out too.
allow = {
    "nuitee": {"get_data_hotels", "post_hotels_rates", "post_rates_prebook", "get_data_reviews"},
}

# get_data_hotels without a limit returns half a megabyte. Nobody's context holds that.
MAX_RESULT = 20_000

PROMPT = (
    "I start in Bangalore on 5 December. Train to Mumbai, two nights there, then "
    "train to Delhi, two nights. Then fly Delhi to London, three nights, and on to "
    "New York, three nights. Plan the whole trip: the trains, the flights, a hotel "
    "in each city with the price, and what to do in each city."
)

# Slash commands the user can type. The user picks a prompt, the model never sees the list.
commands = {"/plan": ("rail", "plan_trip")}


async def show_progress(progress: float, total: float | None, message: str | None) -> None:
    """Called for every progress notification while a tool is still running."""
    print(f"[progress] {progress:g}/{total:g} {message}")


async def ask_user(context, params) -> mcp_types.ElicitResult:
    """A server needs the human, not the model. Ask in the terminal."""
    print(f"[elicit]  {params.message}")
    if params.mode == "url":
        # the user does this part in a browser, the answer never comes back through MCP
        print(f"          open {params.url}")
        done = await asyncio.to_thread(input, "          done? [y/n] ")
        return mcp_types.ElicitResult(action="accept" if done.strip() == "y" else "decline")
    print("          leave any field blank to cancel")
    content = {}
    for key in params.requested_schema["properties"]:
        value = (await asyncio.to_thread(input, f"          {key}: ")).strip()
        if not value:
            return mcp_types.ElicitResult(action="decline")
        content[key] = value
    return mcp_types.ElicitResult(action="accept", content=content)


async def watch(c: Client, sub) -> None:
    """Re-read a resource each time the server says it changed."""
    async for event in sub:
        r = await c.read_resource(event.uri)
        print(f"[event]   {event.uri} changed -> {r.contents[0].text}")


def schema_tokens(tools: list[dict]) -> int:
    """Rough cost of the catalog, four characters to a token."""
    return len(json.dumps(tools)) // 4


async def main():
    llm = AsyncOpenAI(api_key=config.API_KEY, base_url=config.BASE_URL)

    # the shell already split and unquoted the words, so use argv as given
    words = sys.argv[1:]
    # catch a typo before paying for three connections
    if words and words[0].startswith("/") and words[0] not in commands:
        raise SystemExit(f"unknown command {words[0]}, try: {', '.join(commands)}")
    if words and words[0] in commands and len(words) == 1:
        raise SystemExit(f"usage: {words[0]} <describe the trip in plain English>")

    async with AsyncExitStack() as stack:
        clients = {}
        everything = []
        for name, target in servers.items():
            c = await stack.enter_async_context(
                Client(target, elicitation_callback=ask_user)
            )
            clients[name] = c
            listed = (await c.list_tools()).tools
            transport = "http" if isinstance(target, str) else "stdio"
            print(
                f"[connect] {name:8} {transport:6} {len(listed):3} tools"
                f"   protocol {c.protocol_version}"
            )

            # Two servers may both have a plan_journey. The prefix is the host's job.
            for t in listed:
                everything.append(
                    {
                        "type": "function",
                        "function": {
                            "name": f"{name}__{t.name}",
                            "description": t.description,
                            "parameters": t.input_schema,
                        },
                    }
                )
        print(
            f"[catalog] {len(everything)} tools from {len(clients)} servers,"
            f" about {schema_tokens(everything)} tokens of schema per request"
        )

        # Every request pays for every schema, so cut the catalog down first.
        tools = []
        for t in everything:
            server, tool = t["function"]["name"].split("__", 1)
            if server not in allow or tool in allow[server]:
                tools.append(t)
        # MCP is not only request and response. The server can speak first.
        sub = await stack.enter_async_context(
            clients["flights"].listen(resource_subscriptions=["flights://bookings"])
        )
        watcher = asyncio.create_task(watch(clients["flights"], sub))
        stack.callback(watcher.cancel)
        print("[listen]  flights://bookings")

        print(f"[catalog] filtered to {len(tools)} tools, about {schema_tokens(tools)} tokens")
        print("catalog:", [t["function"]["name"] for t in tools])

        messages = []

        # The application decides what the model may know, before it is asked.
        # rail://stations and rail://trains are 13k entries each, so they stay out.
        for uri in ("flights://policy/baggage", "flights://airports"):
            r = await clients["flights"].read_resource(uri)
            print(
                "[resource]", uri, "->", len(r.contents[0].text), "chars,",
                f"ttl {r.ttl_ms} ms {r.cache_scope}",
            )
            messages.append(
                {"role": "system", "content": f"{uri}\n{r.contents[0].text}"}
            )

        system = f"You are a concise travel assistant. Today is {date.today()}."
        messages.append({"role": "system", "content": system})
        if words and words[0].startswith("/"):
            command, *words = words
            server, name = commands[command]
            listed = (await clients[server].list_prompts()).prompts
            prompt = next(p for p in listed if p.name == name)
            # everything after the command is the request, in the user's own words
            arguments = {prompt.arguments[0].name: " ".join(words)}
            print(f"[prompt]  {name}({', '.join(f'{k}={v}' for k, v in arguments.items())})")
            result = await clients[server].get_prompt(name, arguments)
            for m in result.messages:
                messages.append({"role": m.role, "content": m.content.text})
        else:
            messages.append({"role": "user", "content": " ".join(words) or PROMPT})

        while True:
            response = await llm.chat.completions.create(
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
                r = await clients[server].call_tool(
                    tool, arguments, progress_callback=show_progress
                )

                # Three shapes: a list arrives as one block per element, a dict as one
                # block, and an error as one block with structured_content None.
                if r.is_error:
                    content = "\n".join(b.text for b in r.content)
                elif r.structured_content is not None:
                    content = json.dumps(r.structured_content)
                else:
                    content = "\n".join(b.text for b in r.content)

                if len(content) > MAX_RESULT:
                    content = (
                        content[:MAX_RESULT]
                        + f"\n[truncated, {len(content)} chars. Ask for fewer results.]"
                    )

                print("         ->", content.splitlines()[0][:70])

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": content,
                    }
                )


asyncio.run(main())
