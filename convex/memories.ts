import { v } from "convex/values";
import { mutation, query } from "./_generated/server";
import { mine, searchReach, takeMine, userArg, who } from "./users";

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
  args: { source: v.string(), facts: v.array(v.string()), ...userArg },
  handler: async (ctx, { source, facts, userId }) => {
    // Only this user's facts count as already known: two users may hold the same fact.
    const user = who(userId);
    const known = (await ctx.db.query("memories").collect())
      .filter((m) => mine(m, user))
      .map((m) => words(m.text));
    let added = 0;
    for (const fact of facts) {
      const text = fact.trim();
      const said = words(text);
      if (!text || known.some((other) => same(said, other))) continue;
      known.push(said);
      await ctx.db.insert("memories", { text, source, userId: user, createdAt: Date.now() });
      added += 1;
    }
    return added;
  },
});

// Remove facts that repeat an earlier one in other words. Returns how many went.
export const tidy = mutation({
  args: { ...userArg },
  handler: async (ctx, { userId }) => {
    const user = who(userId);
    const all = (await ctx.db.query("memories").order("asc").collect()).filter((m) => mine(m, user));
    const kept: Set<string>[] = [];
    let removed = 0;
    for (const memory of all) {
      const said = words(memory.text);
      if (kept.some((other) => same(said, other))) {
        await ctx.db.delete(memory._id);
        removed += 1;
      } else kept.push(said);
    }
    return removed;
  },
});

export const list = query({
  args: { ...userArg },
  handler: async (ctx, { userId }) => {
    return await takeMine(ctx.db.query("memories").order("desc"), who(userId), 300);
  },
});

export const search = query({
  args: { text: v.string(), limit: v.optional(v.number()), ...userArg },
  handler: async (ctx, { text, limit, userId }) => {
    const user = who(userId);
    const found = await ctx.db
      .query("memories")
      .withSearchIndex("search_text", (q) => q.search("text", text))
      .take(searchReach(limit ?? 8));
    return found.filter((memory) => mine(memory, user)).slice(0, limit ?? 8);
  },
});

export const remove = mutation({
  args: { id: v.id("memories"), ...userArg },
  handler: async (ctx, { id, userId }) => {
    const memory = await ctx.db.get(id);
    if (!memory || !mine(memory, who(userId))) return;
    await ctx.db.delete(id);
  },
});
