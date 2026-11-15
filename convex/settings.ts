import { v } from "convex/values";
import { mutation, query } from "./_generated/server";

const DEFAULTS = { eagerness: "normal" as const, demo: false, listening: false };

export const get = query({
  args: {},
  handler: async (ctx) => {
    return (await ctx.db.query("settings").first()) ?? DEFAULTS;
  },
});

export const set = mutation({
  args: {
    eagerness: v.optional(v.union(v.literal("quiet"), v.literal("normal"))),
    demo: v.optional(v.boolean()),
    listening: v.optional(v.boolean()),
    state: v.optional(v.string()),
    checkins: v.optional(v.boolean()),
  },
  handler: async (ctx, args) => {
    const changes = Object.fromEntries(Object.entries(args).filter(([, value]) => value !== undefined));
    const existing = await ctx.db.query("settings").first();
    if (existing) await ctx.db.patch(existing._id, changes);
    else await ctx.db.insert("settings", { ...DEFAULTS, ...changes });
  },
});

export const setProfile = mutation({
  args: { profile: v.string() },
  handler: async (ctx, { profile }) => {
    const existing = await ctx.db.query("settings").first();
    if (existing) await ctx.db.patch(existing._id, { profile });
    else await ctx.db.insert("settings", { ...DEFAULTS, profile });
  },
});

// Delete everything Wingman knows. Returns how many rows went from each table.
export const wipe = mutation({
  args: {},
  handler: async (ctx) => {
    const receipt: Record<string, number> = {};
    for (const table of ["lines", "promises", "whispers", "conversations", "people", "chats", "tasks", "memories", "research"] as const) {
      const rows = await ctx.db.query(table).collect();
      for (const row of rows) await ctx.db.delete(row._id);
      receipt[table] = rows.length;
    }
    const settings = await ctx.db.query("settings").first();
    if (settings) await ctx.db.patch(settings._id, { profile: undefined });
    return receipt;
  },
});
