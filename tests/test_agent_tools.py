"""Offline tests for the direct agent tool loop.

The tests patch the model and tool registry, so no network or real integrations are used.
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

from wingman import agent, tools


class FakeStore:
    def __init__(self):
        self.chats: list[dict] = []
        self.tasks: list[dict] = []

    async def query(self, path: str, **kwargs):
        if path == "chats:recent":
            return self.chats[-int(kwargs.get("limit", 10)):]
        if path == "tasks:open":
            return list(self.tasks)
        raise AssertionError(f"Unexpected query: {path}")

    async def mutation(self, path: str, **kwargs):
        if path == "chats:add":
            self.chats.append({"role": kwargs["role"], "text": kwargs["text"]})
            return
        raise AssertionError(f"Unexpected mutation: {path}")


class Patch:
    def __init__(self):
        self._undo: list[tuple[object, str, object]] = []

    def set(self, obj: object, name: str, value: object):
        self._undo.append((obj, name, getattr(obj, name)))
        setattr(obj, name, value)

    def close(self):
        for obj, name, old in reversed(self._undo):
            setattr(obj, name, old)


async def _run_with_patches(work):
    patch = Patch()
    try:
        async def profile_text(_store):
            return ""
        patch.set(agent.profile, "text", profile_text)
        await work(patch)
    finally:
        patch.close()


async def _case_lookup_then_answer():
    async def work(patch: Patch):
        store = FakeStore()

        async def memory_search(_store, args):
            assert args["query"] == "diet"
            return tools.ToolResult("- You are vegetarian.", [])

        fake_registry = {
            "memory_search": tools.Tool(
                "memory_search",
                "Search memory",
                {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
                memory_search,
            )
        }
        patch.set(tools, "registry", lambda: fake_registry)

        calls = [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "memory_search", "arguments": '{"query":"diet"}'},
                }],
            },
            {"role": "assistant", "content": json.dumps({"reply": "You are vegetarian.", "steps": [], "sources": ["Memory"]})},
        ]

        async def fake_chat_tools(messages, _specs, **_kwargs):
            del messages
            return calls.pop(0)

        patch.set(agent.llm, "chat_tools", fake_chat_tools)
        answer = await agent.chat(store, "What diet do I follow?")
        assert "vegetarian" in answer["reply"].lower()
        assert answer["done"] == []

    await _run_with_patches(work)


async def _case_slack_import_todos():
    async def work(patch: Patch):
        store = FakeStore()

        added = [
            {"id": "t1", "kind": "note", "text": "Reply to Maya about launch plan", "due": None, "dueText": None},
            {"id": "t2", "kind": "note", "text": "Review Sam's PR by Friday", "due": None, "dueText": None},
        ]

        async def slack_import(_store, _args):
            return tools.ToolResult(
                "Added 2 Slack to-dos: Reply to Maya about launch plan; Review Sam's PR by Friday.",
                added,
            )

        fake_registry = {
            "slack_import_todos": tools.Tool("slack_import_todos", "Import Slack todos", {"type": "object", "properties": {}}, slack_import),
        }
        patch.set(tools, "registry", lambda: fake_registry)

        calls = [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "slack_import_todos", "arguments": "{}"},
                }],
            },
            {"role": "assistant", "content": json.dumps({"reply": "Done.", "steps": [], "sources": []})},
        ]

        async def fake_chat_tools(messages, _specs, **_kwargs):
            del messages
            return calls.pop(0)

        patch.set(agent.llm, "chat_tools", fake_chat_tools)
        answer = await agent.chat(store, "pick up my tasks from Slack and list them as to-dos")
        assert "reply to maya" in answer["reply"].lower()
        assert "review sam's pr" in answer["reply"].lower()
        assert [item["text"] for item in answer["done"]] == [item["text"] for item in added]

    await _run_with_patches(work)


async def _case_tool_failure():
    async def work(patch: Patch):
        store = FakeStore()

        async def failing_tool(_store, _args):
            raise RuntimeError("Docs timeout")

        fake_registry = {
            "docs_search": tools.Tool(
                "docs_search",
                "Search docs",
                {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
                failing_tool,
            )
        }
        patch.set(tools, "registry", lambda: fake_registry)

        calls = [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "docs_search", "arguments": '{"query":"roadmap"}'},
                }],
            },
            {"role": "assistant", "content": json.dumps({"reply": "I couldn't reach docs right now.", "steps": [], "sources": []})},
        ]

        async def fake_chat_tools(messages, _specs, **_kwargs):
            if messages and messages[-1]["role"] == "tool":
                assert "failed" in messages[-1]["content"].lower()
            return calls.pop(0)

        patch.set(agent.llm, "chat_tools", fake_chat_tools)
        answer = await agent.chat(store, "Find my roadmap in docs")
        assert "couldn't reach docs" in answer["reply"].lower()
        assert answer["done"] == []

    await _run_with_patches(work)


async def _case_round_cap():
    async def work(patch: Patch):
        store = FakeStore()

        async def noop_tool(_store, _args):
            return tools.ToolResult("No result.", [])

        fake_registry = {
            "memory_search": tools.Tool("memory_search", "Search memory", {"type": "object", "properties": {}}, noop_tool)
        }
        patch.set(tools, "registry", lambda: fake_registry)

        count = SimpleNamespace(n=0)

        async def fake_chat_tools(_messages, _specs, **_kwargs):
            count.n += 1
            return {
                "role": "assistant",
                "content": "",
                "tool_calls": [{
                    "id": f"call_{count.n}",
                    "type": "function",
                    "function": {"name": "memory_search", "arguments": "{}"},
                }],
            }

        patch.set(agent.llm, "chat_tools", fake_chat_tools)
        answer = await agent.chat(store, "loop forever")
        assert count.n == 6
        assert answer["reply"] == agent.APOLOGY

    await _run_with_patches(work)


def test_lookup_then_answer():
    asyncio.run(_case_lookup_then_answer())


def test_slack_import_todos():
    asyncio.run(_case_slack_import_todos())


def test_tool_failure():
    asyncio.run(_case_tool_failure())


def test_round_cap():
    asyncio.run(_case_round_cap())


if __name__ == "__main__":
    test_lookup_then_answer()
    test_slack_import_todos()
    test_tool_failure()
    test_round_cap()
    print("ok")
