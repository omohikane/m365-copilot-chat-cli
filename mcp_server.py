"""MCP server for copilot-cli (stdio, low-level API implementation).

Exposes M365 Copilot to MCP clients such as opencode as tools.
Each tool call starts a browser, completes the work, and closes it
(no long-running daemon).

Tools:
    copilot_once(prompt)         Ask a single question and get the answer.
    copilot_chat(prompts[])      Converse over multiple turns in the same
                                 thread, carrying context between turns.
    copilot_threads()            List past thread titles.
"""
from __future__ import annotations

import asyncio
import json

import app as app_mod
import mcp_types as types
from copilot_agent import CopilotAgent
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

HEADLESS_DEFAULT = True

SCHEMA_ONCE = {
    "type": "object",
    "properties": {"prompt": {"type": "string"}, "headless": {"type": "boolean"}},
    "required": ["prompt"],
}
SCHEMA_CHAT = {
    "type": "object",
    "properties": {
        "prompts": {"type": "array", "items": {"type": "string"}},
        "headless": {"type": "boolean"},
    },
    "required": ["prompts"],
}
SCHEMA_THREADS = {"type": "object", "properties": {}}


def _code_blocks(agent: CopilotAgent) -> list[dict]:
    return [
        {"language": b.language, "content": b.content}
        for b in agent.last_code_blocks
    ]


def _chat(prompts: list[str], headless: bool) -> list[dict]:
    agent = CopilotAgent(headless=headless)
    agent.start()
    try:
        if not agent.is_logged_in():
            agent.wait_for_login(timeout=300)
        out: list[dict] = []
        for prompt in prompts:
            answer = agent.send(prompt)
            out.append(
                {
                    "prompt": prompt,
                    "answer": answer,
                    "code_blocks": _code_blocks(agent),
                    "tables": agent.last_tables,
                }
            )
        return out
    finally:
        agent.close()


def _threads() -> list[str]:
    agent = CopilotAgent(headless=HEADLESS_DEFAULT)
    agent.start()
    try:
        if not agent.is_logged_in():
            agent.wait_for_login(timeout=300)
        return agent.list_threads(limit=40)
    finally:
        agent.close()


async def list_tools(ctx, params):
    return types.ListToolsResult(
        tools=[
            types.Tool(
                name="copilot_once",
                description="M365 Copilot に1回だけ質問し、回答・コードブロックを得る。単発の質問向け。",
                input_schema=SCHEMA_ONCE,
            ),
            types.Tool(
                name="copilot_chat",
                description="複数の質問を1つのブラウザ・同一スレッドで順に送信し、文脈を引き継いで連続会話する。前の回答を参照する複数ターン向け。",
                input_schema=SCHEMA_CHAT,
            ),
            types.Tool(
                name="copilot_threads",
                description="サイドバーの過去スレッドタイトル一覧を返す。",
                input_schema=SCHEMA_THREADS,
            ),
        ]
    )


async def call_tool(ctx, params):
    name = params.name
    args = params.arguments or {}
    try:
        if name == "copilot_once":
            result = await asyncio.to_thread(
                app_mod.run_once,
                args["prompt"],
                args.get("headless", HEADLESS_DEFAULT),
                False,
            )
            body = {"ok": True, "answer": result.answer, "code_blocks": result.code_blocks}
        elif name == "copilot_chat":
            out = await asyncio.to_thread(
                _chat, args["prompts"], args.get("headless", HEADLESS_DEFAULT)
            )
            body = {"ok": True, "turns": out}
        elif name == "copilot_threads":
            titles = await asyncio.to_thread(_threads)
            body = {"ok": True, "threads": titles}
        else:
            body = {"ok": False, "error": f"unknown tool: {name}"}
            return types.CallToolResult(
                content=[types.TextContent(type="text", text=json.dumps(body, ensure_ascii=False))],
                is_error=True,
            )
    except Exception as exc:  # noqa: BLE001
        body = {"ok": False, "error": str(exc)}
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=json.dumps(body, ensure_ascii=False))],
            is_error=True,
        )
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=json.dumps(body, ensure_ascii=False, indent=2))],
        is_error=False,
    )


server = Server("copilot-cli", on_list_tools=list_tools, on_call_tool=call_tool)


def main() -> int:
    async def _run() -> None:
        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())

    asyncio.run(_run())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())