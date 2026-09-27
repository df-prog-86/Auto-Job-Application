/**
 * The extension's persistent auth token lives in chrome.storage.local
 * (spec §8.3). This module is imported only by the service worker — it is
 * never imported by, or reachable from, a content script, so adapter code
 * (which runs in page context) can never read the token directly; any
 * action that needs it (credential retrieval, application claiming) is
 * requested from the service worker via runtime messaging instead.
 */

const TOKEN_KEY = "jobAgent.extensionToken";

export async function getStoredToken(): Promise<string | null> {
  const result = await chrome.storage.local.get(TOKEN_KEY);
  return (result[TOKEN_KEY] as string | undefined) ?? null;
}

export async function setStoredToken(token: string): Promise<void> {
  await chrome.storage.local.set({ [TOKEN_KEY]: token });
}

export async function clearStoredToken(): Promise<void> {
  await chrome.storage.local.remove(TOKEN_KEY);
}
