/**
 * Placeholder for ATS-detection-on-page-load logic. Not wired into
 * manifest.json yet and not built into any bundle path Chrome loads: per
 * spec §32, this platform opens and drives ATS tabs itself, so adapter
 * scripts are injected programmatically by the service worker via
 * chrome.scripting.executeScript once a tab is opened for a specific
 * application — not declared as a static content_scripts entry that would
 * run on every page matching a broad host pattern.
 *
 * This file becomes the multi-signal detector from spec §37 (hostname,
 * URL path, DOM markers, form structure, page metadata) starting with
 * Milestone 6, once there's a generic adapter and a real tab-management
 * flow in the service worker to call it from.
 */

export {};
