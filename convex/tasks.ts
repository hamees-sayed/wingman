import { v } from "convex/values";
import { mutation, query } from "./_generated/server";
import { mine, takeMine, userArg, who } from "./users";

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
    ...userArg,
  },
  handler: async (ctx, { userId, ...args }) => {
    const user = who(userId);
    // Asking twice for the same thing keeps one entry. Only this user's to-dos are compared.
    const open = (
      await ctx.db
        .query("tasks")
        .withIndex("by_status", (q) => q.eq("status", "open"))
        .collect()
    ).filter((task) => mine(task, user));
    // The same job worded differently ("Send Karen the paper link", "Share the paper link with
    // Karen") is one entry: the existing one is edited, not joined by a second.
    const asked = words(args.text);
    const same = open.find((task) => {
      const theirs = words(task.text);
      const shared = [...asked].filter((word) => theirs.has(word)).length;
      const smaller = Math.min(asked.size, theirs.size);
      return smaller > 0 && shared === smaller ? true : shared >= 2 && shared / smaller >= 0.6;
    });
    if (same) {
      const changes: Record<string, unknown> = {};
      if (asked.size > words(same.text).size) changes.text = args.text; // the fuller wording wins
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
    return await ctx.db.insert("tasks", { ...args, userId: user, status: "open", createdAt: Date.now() });
  },
});

export const open = query({
  args: { ...userArg },
  handler: async (ctx, { userId }) => {
    const rows = await takeMine(
      ctx.db
        .query("tasks")
        .withIndex("by_status", (q) => q.eq("status", "open"))
        .order("desc"),
      who(userId),
      100,
    );
    // Reminders with a time first, soonest at the top; then everything else, newest first.
    return rows.sort((a, b) => (a.due ?? Infinity) - (b.due ?? Infinity) || b.createdAt - a.createdAt);
  },
});

// Reminders whose time has come and which have not been spoken yet.
export const due = query({
  args: { now: v.number(), ...userArg },
  handler: async (ctx, { now, userId }) => {
    const user = who(userId);
    const rows = await ctx.db
      .query("tasks")
      .withIndex("by_status", (q) => q.eq("status", "open"))
      .collect();
    return rows.filter((task) => mine(task, user) && task.kind === "reminder" && task.due !== undefined && task.due <= now && !task.fired);
  },
});

export const markFired = mutation({
  args: { id: v.id("tasks"), ...userArg },
  handler: async (ctx, { id, userId }) => {
    const task = await ctx.db.get(id);
    if (!task || !mine(task, who(userId))) return;
    await ctx.db.patch(id, { fired: true });
  },
});

export const setStatus = mutation({
  args: {
    id: v.id("tasks"),
    status: v.union(v.literal("open"), v.literal("done"), v.literal("suggested")),
    how: v.optional(v.string()),
    ...userArg,
  },
  handler: async (ctx, { id, status, how, userId }) => {
    const task = await ctx.db.get(id);
    if (!task || !mine(task, who(userId))) return;
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
  args: { limit: v.optional(v.number()), ...userArg },
  handler: async (ctx, { limit, userId }) => {
    const rows = await takeMine(
      ctx.db
        .query("tasks")
        .withIndex("by_status", (q) => q.eq("status", "done"))
        .order("desc"),
      who(userId),
      200,
    );
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
    ...userArg,
  },
  handler: async (ctx, { conversationId, items, userId }) => {
    const user = who(userId);
    const existing = (await ctx.db.query("tasks").collect()).filter((t) => mine(t, user));
    const key = (text: string) => text.toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
    const known = new Set(existing.filter((t) => t.status !== "done").map((t) => key(t.text)));
    const added = [];
    for (const item of items) {
      if (!item.text.trim() || known.has(key(item.text))) continue;
      known.add(key(item.text));
      const id = await ctx.db.insert("tasks", {
        kind: item.due !== undefined ? "reminder" : "note", text: item.text.trim(), due: item.due,
        dueText: item.dueText, status: "suggested", conversationId, userId: user, createdAt: Date.now(),
      });
      added.push({ _id: id, text: item.text.trim() });
    }
    return added;
  },
});

export const suggested = query({
  args: { ...userArg },
  handler: async (ctx, { userId }) => {
    return await takeMine(
      ctx.db
        .query("tasks")
        .withIndex("by_status", (q) => q.eq("status", "suggested"))
        .order("desc"),
      who(userId),
      20,
    );
  },
});

// The owner said yes (add them all) or no (drop them all).
export const answerSuggestions = mutation({
  args: { accept: v.boolean(), ...userArg },
  handler: async (ctx, { accept, userId }) => {
    const user = who(userId);
    const rows = (
      await ctx.db
        .query("tasks")
        .withIndex("by_status", (q) => q.eq("status", "suggested"))
        .collect()
    ).filter((task) => mine(task, user));
    for (const row of rows) {
      if (accept) await ctx.db.patch(row._id, { status: "open" });
      else await ctx.db.delete(row._id);
    }
    return rows.length;
  },
});

export const remove = mutation({
  args: { id: v.id("tasks"), ...userArg },
  handler: async (ctx, { id, userId }) => {
    const task = await ctx.db.get(id);
    if (!task || !mine(task, who(userId))) return;
    await ctx.db.delete(id);
  },
});
