import { v } from "convex/values";
import { mutation, query } from "./_generated/server";

export const add = mutation({
  args: {
    role: v.union(v.literal("you"), v.literal("wingman")),
    text: v.string(),
    sources: v.optional(v.array(v.string())),
  },
  handler: async (ctx, args) => {
    return await ctx.db.insert("chats", { ...args, at: Date.now() });
  },
});

// The most recent messages, oldest first.
export const recent = query({
  args: { limit: v.optional(v.number()) },
  handler: async (ctx, { limit }) => {
    const rows = await ctx.db.query("chats").withIndex("by_at").order("desc").take(limit ?? 40);
    return rows.reverse();
  },
});

export const clear = mutation({
  args: {},
  handler: async (ctx) => {
    const rows = await ctx.db.query("chats").collect();
    for (const row of rows) await ctx.db.delete(row._id);
    return rows.length;
  },
});
