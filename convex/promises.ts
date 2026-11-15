import { v } from "convex/values";
import { mutation, query } from "./_generated/server";

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
  },
  handler: async (ctx, args) => {
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
    return await ctx.db.insert("promises", { ...args, status: "open", createdAt: Date.now() });
  },
});

export const open = query({
  args: {},
  handler: async (ctx) => {
    return await ctx.db
      .query("promises")
      .withIndex("by_status", (q) => q.eq("status", "open"))
      .order("desc")
      .take(200);
  },
});

export const all = query({
  args: {},
  handler: async (ctx) => {
    return await ctx.db.query("promises").order("desc").take(200);
  },
});

export const setStatus = mutation({
  args: {
    id: v.id("promises"),
    status: v.union(v.literal("open"), v.literal("done"), v.literal("dropped")),
  },
  handler: async (ctx, { id, status }) => {
    await ctx.db.patch(id, { status });
  },
});
