import { v } from "convex/values";
import { mutation, query } from "./_generated/server";
import { mine, takeMine, userArg, who } from "./users";

export const start = mutation({
  args: { topic: v.string(), ...userArg },
  handler: async (ctx, { topic, userId }) => {
    return await ctx.db.insert("research", {
      topic, status: "working", userId: who(userId), createdAt: Date.now(),
    });
  },
});

export const finish = mutation({
  args: {
    id: v.id("research"), short: v.string(), report: v.string(), sources: v.array(v.string()),
    ...userArg,
  },
  handler: async (ctx, { id, short, report, sources, userId }) => {
    const row = await ctx.db.get(id);
    if (!row || !mine(row, who(userId))) return;
    await ctx.db.patch(id, { status: "ready", short, report, sources, readyAt: Date.now(), announced: false });
  },
});

export const fail = mutation({
  args: { id: v.id("research"), ...userArg },
  handler: async (ctx, { id, userId }) => {
    const row = await ctx.db.get(id);
    if (!row || !mine(row, who(userId))) return;
    await ctx.db.patch(id, { status: "failed", readyAt: Date.now(), announced: false });
  },
});

export const list = query({
  args: { ...userArg },
  handler: async (ctx, { userId }) => {
    return await takeMine(ctx.db.query("research").withIndex("by_created").order("desc"), who(userId), 20);
  },
});

// Finished but not yet told to the owner.
export const unannounced = query({
  args: { ...userArg },
  handler: async (ctx, { userId }) => {
    const rows = await takeMine(ctx.db.query("research").withIndex("by_created").order("desc"), who(userId), 30);
    return rows.filter((row) => row.status !== "working" && row.announced === false);
  },
});

export const markAnnounced = mutation({
  args: { id: v.id("research"), ...userArg },
  handler: async (ctx, { id, userId }) => {
    const row = await ctx.db.get(id);
    if (!row || !mine(row, who(userId))) return;
    await ctx.db.patch(id, { announced: true });
  },
});

export const remove = mutation({
  args: { id: v.id("research"), ...userArg },
  handler: async (ctx, { id, userId }) => {
    const row = await ctx.db.get(id);
    if (!row || !mine(row, who(userId))) return;
    await ctx.db.delete(id);
  },
});
