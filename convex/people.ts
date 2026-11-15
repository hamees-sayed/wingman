import { v } from "convex/values";
import { mutation, query } from "./_generated/server";

export const list = query({
  args: {},
  handler: async (ctx) => {
    const people = await ctx.db.query("people").collect();
    // Voiceprints are for the server's matching only; screens never need them.
    return people
      .map(({ voiceprint, ...person }) => ({ ...person, hasVoice: voiceprint !== undefined }))
      .sort((a, b) => b.lastMet - a.lastMet);
  },
});

// For the server: everyone with a voiceprint, to recognise a speaker.
export const voices = query({
  args: {},
  handler: async (ctx) => {
    const people = await ctx.db.query("people").collect();
    return people
      .filter((person) => person.voiceprint !== undefined)
      .map(({ _id, name, isOwner, voiceprint, voiceSeconds }) => ({
        _id,
        name,
        isOwner,
        voiceprint,
        voiceSeconds: voiceSeconds ?? 0,
      }));
  },
});

export const owner = query({
  args: {},
  handler: async (ctx) => {
    return await ctx.db
      .query("people")
      .withIndex("by_owner", (q) => q.eq("isOwner", true))
      .first();
  },
});

export const find = query({
  args: { name: v.string() },
  handler: async (ctx, { name }) => {
    return await ctx.db
      .query("people")
      .withSearchIndex("search_name", (q) => q.search("name", name))
      .take(5);
  },
});

// Save or update a person by exact name (case-insensitive). Returns the id.
export const upsert = mutation({
  args: {
    name: v.string(),
    isOwner: v.optional(v.boolean()),
    about: v.optional(v.string()),
    voiceprint: v.optional(v.array(v.float64())),
    voiceSeconds: v.optional(v.number()),
  },
  handler: async (ctx, { name, isOwner, about, voiceprint, voiceSeconds }) => {
    const now = Date.now();
    const everyone = await ctx.db.query("people").collect();
    const existing = isOwner
      ? everyone.find((person) => person.isOwner)
      : everyone.find(
          (person) => !person.isOwner && person.name.toLowerCase() === name.toLowerCase(),
        );
    if (existing) {
      const patch: Record<string, unknown> = { lastMet: now };
      if (isOwner) patch.name = name;
      if (about) patch.about = about;
      if (voiceprint) {
        patch.voiceprint = voiceprint;
        patch.voiceSeconds = voiceSeconds;
      }
      await ctx.db.patch(existing._id, patch);
      return existing._id;
    }
    return await ctx.db.insert("people", {
      name,
      isOwner: isOwner ?? false,
      about,
      voiceprint,
      voiceSeconds,
      firstMet: now,
      lastMet: now,
    });
  },
});

export const forgetVoice = mutation({
  args: { id: v.id("people") },
  handler: async (ctx, { id }) => {
    await ctx.db.patch(id, { voiceprint: undefined, voiceSeconds: undefined });
  },
});

export const remove = mutation({
  args: { id: v.id("people") },
  handler: async (ctx, { id }) => {
    await ctx.db.delete(id);
  },
});

// One person's page: who they are, what stands between you, and when you spoke.
export const profile = query({
  args: { id: v.id("people") },
  handler: async (ctx, { id }) => {
    const person = await ctx.db.get(id);
    if (!person) return null;
    const { voiceprint, ...rest } = person;
    const name = person.name.toLowerCase();
    const promises = (await ctx.db.query("promises").order("desc").take(300)).filter(
      (p) => p.personId === id || p.person.toLowerCase() === name,
    );
    const recent = await ctx.db.query("conversations").withIndex("by_started").order("desc").take(80);
    const conversations = [];
    for (const conversation of recent) {
      if (!conversation.peopleIds.includes(id)) continue;
      const lines = await ctx.db
        .query("lines")
        .withIndex("by_conversation", (q) => q.eq("conversationId", conversation._id))
        .take(80);
      conversations.push({
        _id: conversation._id,
        title: conversation.title ?? "In progress",
        summary: conversation.summary ?? "",
        startedAt: conversation.startedAt,
        lines: lines.filter((l) => !l.retracted).map((l) => ({ label: l.label, text: l.text })),
      });
      if (conversations.length >= 6) break;
    }
    return {
      person: { ...rest, hasVoice: voiceprint !== undefined },
      owe: promises.filter((p) => p.by === "you" && p.status === "open"),
      owed: promises.filter((p) => p.by === "them" && p.status === "open"),
      conversations,
    };
  },
});
