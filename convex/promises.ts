import { v } from "convex/values";
import { mutation, query } from "./_generated/server";
import { mine, takeMine, userArg, who } from "./users";

export const add = mutation({
  args: {
    conversationId: v.id("conversations"),
    by: v.union(v.literal("you"), v.literal("them")),
    personId: v.optional(v.id("people")),
    person: v.string(),
    what: v.string(),
    due: v.optional(v.string()),
    dueDate: v.optional(v.string()),
    lineId: v.optional(v.id("lines")),
    ...userArg,
  },
  handler: async (ctx, { userId, ...args }) => {
    // A promise belongs to whoever owns its conversation; someone else's is not there to add to.
    const user = who(userId);
    if (!mine(await ctx.db.get(args.conversationId), user)) return null;
    // The same promise restated in one conversation is saved once.
    const same = await ctx.db
      .query("promises")
      .withIndex("by_conversation", (q) => q.eq("conversationId", args.conversationId))
      .collect();
    const key = (text: string) => text.toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
    const existing = same.find(
      (promise) => promise.by === args.by && key(promise.what) === key(args.what),
    );
    if (existing) return existing._id;
    return await ctx.db.insert("promises", { ...args, userId: user, status: "open", createdAt: Date.now() });
  },
});

export const open = query({
  args: { ...userArg },
  handler: async (ctx, { userId }) => {
    return await takeMine(
      ctx.db
        .query("promises")
        .withIndex("by_status", (q) => q.eq("status", "open"))
        .order("desc"),
      who(userId),
      200,
    );
  },
});

export const all = query({
  args: { ...userArg },
  handler: async (ctx, { userId }) => {
    return await takeMine(ctx.db.query("promises").order("desc"), who(userId), 200);
  },
});

export const setStatus = mutation({
  args: {
    id: v.id("promises"),
    status: v.union(v.literal("open"), v.literal("done"), v.literal("dropped")),
    ...userArg,
  },
  handler: async (ctx, { id, status, userId }) => {
    const promise = await ctx.db.get(id);
    if (!promise || !mine(promise, who(userId))) return;
    await ctx.db.patch(id, { status });
  },
});

// The follow-up message for a promise, kept so it is there the moment the owner wants it.
export const setDraft = mutation({
  args: { id: v.id("promises"), draft: v.string(), ...userArg },
  handler: async (ctx, { id, draft, userId }) => {
    const promise = await ctx.db.get(id);
    if (!promise || !mine(promise, who(userId))) return;
    await ctx.db.patch(id, { draft });
  },
});
