import { v } from "convex/values";
import { mutation, query } from "./_generated/server";

const outcome = v.union(
  v.literal("spoken"),
  v.literal("card"),
  v.literal("held"),
  v.literal("declined"),
  v.literal("stale"),
  v.literal("cut"),
);

export const log = mutation({
  args: {
    conversationId: v.id("conversations"),
    kind: v.string(),
    text: v.string(),
    why: v.string(),
    outcome,
    confidence: v.number(),
    source: v.optional(v.string()),
    conversationSeconds: v.number(),
    latencyMs: v.optional(v.number()),
  },
  handler: async (ctx, args) => {
    return await ctx.db.insert("whispers", { ...args, at: Date.now() });
  },
});

export const setOutcome = mutation({
  args: { id: v.id("whispers"), outcome },
  handler: async (ctx, { id, outcome }) => {
    await ctx.db.patch(id, { outcome });
  },
});

export const grade = mutation({
  args: { id: v.id("whispers"), grade: v.optional(v.union(v.literal("up"), v.literal("down"))) },
  handler: async (ctx, { id, grade }) => {
    await ctx.db.patch(id, { grade });
  },
});

export const forConversation = query({
  args: { conversationId: v.id("conversations") },
  handler: async (ctx, { conversationId }) => {
    return await ctx.db
      .query("whispers")
      .withIndex("by_conversation", (q) => q.eq("conversationId", conversationId))
      .collect();
  },
});

// Thumbs per kind, so the bar for each kind of whisper can move on its own.
export const grades = query({
  args: {},
  handler: async (ctx) => {
    const graded = (await ctx.db.query("whispers").order("desc").take(500)).filter(
      (whisper) => whisper.grade !== undefined,
    );
    const byKind: Record<string, { up: number; down: number }> = {};
    for (const whisper of graded) {
      const tally = (byKind[whisper.kind] ??= { up: 0, down: 0 });
      tally[whisper.grade!] += 1;
    }
    return byKind;
  },
});
