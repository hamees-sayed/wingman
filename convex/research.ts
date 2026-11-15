import { v } from "convex/values";
import { mutation, query } from "./_generated/server";

export const start = mutation({
  args: { topic: v.string() },
  handler: async (ctx, { topic }) => {
    return await ctx.db.insert("research", { topic, status: "working", createdAt: Date.now() });
  },
});

export const finish = mutation({
  args: { id: v.id("research"), short: v.string(), report: v.string(), sources: v.array(v.string()) },
  handler: async (ctx, { id, short, report, sources }) => {
    await ctx.db.patch(id, { status: "ready", short, report, sources, readyAt: Date.now(), announced: false });
  },
});

export const fail = mutation({
  args: { id: v.id("research") },
  handler: async (ctx, { id }) => {
    await ctx.db.patch(id, { status: "failed", readyAt: Date.now(), announced: false });
  },
});

export const list = query({
  args: {},
  handler: async (ctx) => {
    return await ctx.db.query("research").withIndex("by_created").order("desc").take(20);
  },
});

// Finished but not yet told to the owner.
export const unannounced = query({
  args: {},
  handler: async (ctx) => {
    const rows = await ctx.db.query("research").withIndex("by_created").order("desc").take(30);
    return rows.filter((row) => row.status !== "working" && row.announced === false);
  },
});

export const markAnnounced = mutation({
  args: { id: v.id("research") },
  handler: async (ctx, { id }) => {
    await ctx.db.patch(id, { announced: true });
  },
});

export const remove = mutation({
  args: { id: v.id("research") },
  handler: async (ctx, { id }) => {
    await ctx.db.delete(id);
  },
});
