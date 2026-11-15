import { v } from "convex/values";
import { mutation, query, type QueryCtx } from "./_generated/server";
import { mine, userArg, who } from "./users";

const DEFAULTS = { eagerness: "normal" as const, demo: false, listening: false };

// Each user has at most one settings row; the one with no userId is the legacy owner's.
async function rowFor(ctx: { db: QueryCtx["db"] }, user: string) {
  const rows = await ctx.db.query("settings").collect();
  return rows.find((row) => mine(row, user)) ?? null;
}

export const get = query({
  args: { ...userArg },
  handler: async (ctx, { userId }) => {
    return (await rowFor(ctx, who(userId))) ?? DEFAULTS;
  },
});

export const set = mutation({
  args: {
    eagerness: v.optional(v.union(v.literal("quiet"), v.literal("normal"))),
    demo: v.optional(v.boolean()),
    listening: v.optional(v.boolean()),
    state: v.optional(v.string()),
    checkins: v.optional(v.boolean()),
    ...userArg,
  },
  handler: async (ctx, { userId, ...args }) => {
    const user = who(userId);
    const changes = Object.fromEntries(Object.entries(args).filter(([, value]) => value !== undefined));
    const existing = await rowFor(ctx, user);
    if (existing) await ctx.db.patch(existing._id, changes);
    else await ctx.db.insert("settings", { ...DEFAULTS, ...changes, userId: user });
  },
});

export const setProfile = mutation({
  args: { profile: v.string(), ...userArg },
  handler: async (ctx, { profile, userId }) => {
    const user = who(userId);
    const existing = await rowFor(ctx, user);
    if (existing) await ctx.db.patch(existing._id, { profile });
    else await ctx.db.insert("settings", { ...DEFAULTS, profile, userId: user });
  },
});

// Delete everything Wingman knows about this user. Returns how many rows went from each table.
export const wipe = mutation({
  args: { ...userArg },
  handler: async (ctx, { userId }) => {
    const user = who(userId);
    const receipt: Record<string, number> = {};
    for (const table of ["lines", "promises", "whispers", "conversations", "people", "chats", "tasks", "memories", "research"] as const) {
      const rows = (await ctx.db.query(table).collect()).filter((row) => mine(row, user));
      for (const row of rows) await ctx.db.delete(row._id);
      receipt[table] = rows.length;
    }
    const settings = await rowFor(ctx, user);
    if (settings) await ctx.db.patch(settings._id, { profile: undefined });
    return receipt;
  },
});
