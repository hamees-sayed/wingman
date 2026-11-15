import { v } from "convex/values";
import { mutation, query } from "./_generated/server";

const FILLER = new Set(
  "the a an to with for of and on in at by my your his her their our this that it is be me him them about from up out please".split(" "),
);
const ALIKE: Record<string, string> = {
  share: "send", email: "send", forward: "send", message: "send", text: "send", mail: "send",
  ring: "call", phone: "call", check: "confirm", verify: "confirm", book: "schedule", arrange: "schedule",
};

// The words that carry a to-do's meaning, with near-synonyms folded together.
function words(text: string): Set<string> {
  const out = new Set<string>();
  for (const raw of text.toLowerCase().replace(/[^a-z0-9]+/g, " ").trim().split(" ")) {
    const word = raw.length > 3 && raw.endsWith("s") ? raw.slice(0, -1) : raw;
    if (word && !FILLER.has(word)) out.add(ALIKE[word] ?? word);
  }
  return out;
}

export const add = mutation({
  args: {
    kind: v.union(v.literal("reminder"), v.literal("note")),
    text: v.string(),
    due: v.optional(v.number()),
    dueText: v.optional(v.string()),
    conversationId: v.optional(v.id("conversations")),
    auto: v.optional(v.boolean()),
  },
  handler: async (ctx, args) => {
    // Asking twice for the same thing keeps one entry.
    const open = await ctx.db
      .query("tasks")
      .withIndex("by_status", (q) => q.eq("status", "open"))
      .collect();
    // The same job worded differently ("Send Karen the paper link", "Share the paper link with
    // Karen") is one entry: the existing one is edited, not joined by a second.
    const mine = words(args.text);
    const same = open.find((task) => {
      const theirs = words(task.text);
      const shared = [...mine].filter((word) => theirs.has(word)).length;
      const smaller = Math.min(mine.size, theirs.size);
      return smaller > 0 && shared === smaller ? true : shared >= 2 && shared / smaller >= 0.6;
    });
    if (same) {
      const changes: Record<string, unknown> = {};
      if (mine.size > words(same.text).size) changes.text = args.text; // the fuller wording wins
      if (args.due !== undefined) {
        changes.due = args.due;
        changes.dueText = args.dueText;
        changes.fired = false;
        changes.kind = "reminder";
      }
      if (same.auto && !args.auto) changes.auto = false; // the owner has now asked for it themselves
      if (Object.keys(changes).length) await ctx.db.patch(same._id, changes);
      return same._id;
    }
    return await ctx.db.insert("tasks", { ...args, status: "open", createdAt: Date.now() });
  },
});

export const open = query({
  args: {},
  handler: async (ctx) => {
    const rows = await ctx.db
      .query("tasks")
      .withIndex("by_status", (q) => q.eq("status", "open"))
      .order("desc")
      .take(100);
    // Reminders with a time first, soonest at the top; then everything else, newest first.
    return rows.sort((a, b) => (a.due ?? Infinity) - (b.due ?? Infinity) || b.createdAt - a.createdAt);
  },
});

// Reminders whose time has come and which have not been spoken yet.
export const due = query({
  args: { now: v.number() },
  handler: async (ctx, { now }) => {
    const rows = await ctx.db
      .query("tasks")
      .withIndex("by_status", (q) => q.eq("status", "open"))
      .collect();
    return rows.filter((task) => task.kind === "reminder" && task.due !== undefined && task.due <= now && !task.fired);
  },
});

export const markFired = mutation({
  args: { id: v.id("tasks") },
  handler: async (ctx, { id }) => {
    await ctx.db.patch(id, { fired: true });
  },
});

export const setStatus = mutation({
  args: {
    id: v.id("tasks"),
    status: v.union(v.literal("open"), v.literal("done"), v.literal("suggested")),
    how: v.optional(v.string()),
  },
  handler: async (ctx, { id, status, how }) => {
    // A finished to-do keeps when and how it was finished; reopening it clears that.
    await ctx.db.patch(
      id,
      status === "done"
        ? { status, doneAt: Date.now(), doneHow: how ?? "tapped" }
        : { status, doneAt: undefined, doneHow: undefined },
    );
  },
});

// The record of what was finished, newest first.
export const finished = query({
  args: { limit: v.optional(v.number()) },
  handler: async (ctx, { limit }) => {
    const rows = await ctx.db
      .query("tasks")
      .withIndex("by_status", (q) => q.eq("status", "done"))
      .order("desc")
      .take(200);
    return rows
      .sort((a, b) => (b.doneAt ?? b.createdAt) - (a.doneAt ?? a.createdAt))
      .slice(0, limit ?? 30);
  },
});

// To-dos Wingman proposes after a conversation; they wait for the owner's yes or no.
export const suggest = mutation({
  args: {
    conversationId: v.optional(v.id("conversations")),
    items: v.array(v.object({ text: v.string(), due: v.optional(v.number()), dueText: v.optional(v.string()) })),
  },
  handler: async (ctx, { conversationId, items }) => {
    const existing = await ctx.db.query("tasks").collect();
    const key = (text: string) => text.toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
    const known = new Set(existing.filter((t) => t.status !== "done").map((t) => key(t.text)));
    const added = [];
    for (const item of items) {
      if (!item.text.trim() || known.has(key(item.text))) continue;
      known.add(key(item.text));
      const id = await ctx.db.insert("tasks", {
        kind: item.due !== undefined ? "reminder" : "note", text: item.text.trim(), due: item.due,
        dueText: item.dueText, status: "suggested", conversationId, createdAt: Date.now(),
      });
      added.push({ _id: id, text: item.text.trim() });
    }
    return added;
  },
});

export const suggested = query({
  args: {},
  handler: async (ctx) => {
    return await ctx.db
      .query("tasks")
      .withIndex("by_status", (q) => q.eq("status", "suggested"))
      .order("desc")
      .take(20);
  },
});

// The owner said yes (add them all) or no (drop them all).
export const answerSuggestions = mutation({
  args: { accept: v.boolean() },
  handler: async (ctx, { accept }) => {
    const rows = await ctx.db
      .query("tasks")
      .withIndex("by_status", (q) => q.eq("status", "suggested"))
      .collect();
    for (const row of rows) {
      if (accept) await ctx.db.patch(row._id, { status: "open" });
      else await ctx.db.delete(row._id);
    }
    return rows.length;
  },
});

export const remove = mutation({
  args: { id: v.id("tasks") },
  handler: async (ctx, { id }) => {
    await ctx.db.delete(id);
  },
});
