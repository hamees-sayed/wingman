"""Copy what an account already has into Supermemory, so it can be found by meaning.

    uv run python -m scripts.recall_backfill            # the first owner
    uv run python -m scripts.recall_backfill <account>  # any other account id

Safe to run again: each fact and conversation has a fixed id there, so nothing is doubled.
"""

import asyncio
import sys
from datetime import datetime

from wingman import recall, users
from wingman.store import Store


async def main(account: str):
    users.become(account)
    store = Store()
    facts = await store.query("memories:list")
    by_source: dict[str, list[str]] = {}
    for fact in facts:
        by_source.setdefault(fact["source"], []).append(fact["text"])
    kept = 0
    for source, texts in by_source.items():
        kept += await recall.keep_facts(source, texts)
    print(f"facts: {kept} of {len(facts)} taken")
    kept = 0
    conversations = [c for c in await store.query("conversations:list") if c.get("endedAt") and c.get("title")]
    for conversation in conversations:
        lines = await store.query("conversations:lines", conversationId=conversation["_id"])
        said = "\n".join(f"[{line['label']}] {line['text']}" for line in lines if not line.get("retracted"))
        if len(said.split()) < 25:
            continue
        day = datetime.fromtimestamp(conversation["startedAt"] / 1000).strftime("%A %d %B %Y")
        kept += await recall.keep_conversation(conversation["_id"], conversation["title"], conversation.get("summary") or "",
                                               conversation.get("points") or [], said, day)
    print(f"conversations: {kept} of {len(conversations)} taken")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else users.OWNER))
