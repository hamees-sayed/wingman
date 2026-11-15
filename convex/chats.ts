import { v } from "convex/values";
import { mutation, query } from "./_generated/server";
import { mine, takeMine, userArg, who } from "./users";

export const add = mutation({
  args: {
    role: v.union(v.literal("you"), v.literal("wingman")),
    text: v.string(),
    sources: v.optional(v.array(v.string())),
    ...userArg,
  },
  handler: async (ctx, { userId, ...chat }) => {
    return await ctx.db.insert("chats", { ...chat, userId: who(userId), at: Date.now() });
  },
});

// The most recent messages, oldest first.
export const recent = query({
  args: { limit: v.optional(v.number()), ...userArg },
  handler: async (ctx, { limit, userId }) => {
    const rows = await takeMine(
      ctx.db.query("chats").withIndex("by_at").order("desc"),
      who(userId),
      limit ?? 40,
    );
    return rows.reverse();
  },
});

export const clear = mutation({
  args: { ...userArg },
  handler: async (ctx, { userId }) => {
    const user = who(userId);
    const rows = (await ctx.db.query("chats").collect()).filter((row) => mine(row, user));
    for (const row of rows) await ctx.db.delete(row._id);
    return rows.length;
  },
});
