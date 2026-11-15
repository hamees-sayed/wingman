/* eslint-disable */
/**
 * Generated `api` utility.
 *
 * THIS CODE IS AUTOMATICALLY GENERATED.
 *
 * To regenerate, run `npx convex dev`.
 * @module
 */

import type * as chats from "../chats.js";
import type * as conversations from "../conversations.js";
import type * as memories from "../memories.js";
import type * as people from "../people.js";
import type * as promises from "../promises.js";
import type * as research from "../research.js";
import type * as settings from "../settings.js";
import type * as tasks from "../tasks.js";
import type * as whispers from "../whispers.js";

import type {
  ApiFromModules,
  FilterApi,
  FunctionReference,
} from "convex/server";

declare const fullApi: ApiFromModules<{
  chats: typeof chats;
  conversations: typeof conversations;
  memories: typeof memories;
  people: typeof people;
  promises: typeof promises;
  research: typeof research;
  settings: typeof settings;
  tasks: typeof tasks;
  whispers: typeof whispers;
}>;

/**
 * A utility for referencing Convex functions in your app's public API.
 *
 * Usage:
 * ```js
 * const myFunctionReference = api.myModule.myFunction;
 * ```
 */
export declare const api: FilterApi<
  typeof fullApi,
  FunctionReference<any, "public">
>;

/**
 * A utility for referencing Convex functions in your app's internal API.
 *
 * Usage:
 * ```js
 * const myFunctionReference = internal.myModule.myFunction;
 * ```
 */
export declare const internal: FilterApi<
  typeof fullApi,
  FunctionReference<any, "internal">
>;

export declare const components: {};
