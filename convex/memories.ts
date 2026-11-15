import { v } from "convex/values";
import { mutation, query } from "./_generated/server";

const FILLER = new Set(
  "you your are is a an the to of and in on at for with that have has was were be been as it its by from about or this".split(" "),
);

// The words that carry a fact's meaning, so the same fact reworded is recognised.
function words(text: string): Set<string> {
  const out = new Set<string>();
  for (const raw of text.toLowerCase().replace(/[^a-z0-9]+/g, " ").trim().split(" ")) {
    const word = raw.length > 3 && raw.endsWith("s") ? raw.slice(0, -1) : raw;
    if (word && !FILLER.has(word)) out.add(word);
  }
  return out;
}

// Two facts say the same thing when nearly all the words of the shorter are in the longer.
function same(a: Set<string>, b: Set<string>): boolean {
  const small = a.size <= b.size ? a : b;
  const large = a.size <= b.size ? b : a;
  if (small.size === 0) return false;
  let shared = 0;
  for (const word of small) if (large.has(word)) shared += 1;
  return shared / small.size >= 0.8 && small.size / large.size >= 0.6;
}

export const addMany = mutation({
  args: { source: v.string(), facts: v.array(v.string()) },
  handler: async (ctx, { source, facts }) => {
    const known = (await ctx.db.query("memories").collect()).map((m) => words(m.text));
    let added = 0;
    for (const fact of facts) {
      const text = fact.trim();
      const mine = words(text);
      if (!text || known.some((other) => same(mine, other))) continue;
      known.push(mine);
      await ctx.db.insert("memories", { text, source, createdAt: Date.now() });
      added += 1;
    }
    return added;
  },
});

// Remove facts that repeat an earlier one in other words. Returns how many went.
export const tidy = mutation({
  args: {},
  handler: async (ctx) => {
    const all = await ctx.db.query("memories").order("asc").collect();
    const kept: Set<string>[] = [];
    let removed = 0;
    for (const memory of all) {
      const mine = words(memory.text);
      if (kept.some((other) => same(mine, other))) {
        await ctx.db.delete(memory._id);
        removed += 1;
      } else kept.push(mine);
    }
    return removed;
  },
});

export const list = query({
  args: {},
  handler: async (ctx) => {
    return await ctx.db.query("memories").order("desc").take(300);
  },
});

export const search = query({
  args: { text: v.string(), limit: v.optional(v.number()) },
  handler: async (ctx, { text, limit }) => {
    return await ctx.db
      .query("memories")
      .withSearchIndex("search_text", (q) => q.search("text", text))
      .take(limit ?? 8);
  },
});

export const remove = mutation({
  args: { id: v.id("memories") },
  handler: async (ctx, { id }) => {
    await ctx.db.delete(id);
  },
});
