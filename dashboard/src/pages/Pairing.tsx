import { useMutation } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "@/api/client";
import { PageHeader } from "@/components/PageHeader";

/**
 * First-run pairing (spec §8.3): the dashboard requests a one-time secret
 * from the backend and displays it; the user pastes it into the extension
 * popup, which calls /api/v1/system/pair itself to get a persistent token.
 * The dashboard never sees or holds the extension's token — only the
 * short-lived secret that authorizes issuing one.
 */
export function Pairing() {
  const [secret, setSecret] = useState<string | null>(null);

  const generate = useMutation({
    mutationFn: api.createPairingSecret,
    onSuccess: (data) => setSecret(data.pairing_secret),
  });

  return (
    <div>
      <PageHeader
        title="Pair the extension"
        description="One-time setup to connect the Chrome extension to this backend."
      />

      <div className="max-w-lg rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
        <ol className="mb-5 list-inside list-decimal space-y-2 text-sm text-slate-600">
          <li>Generate a pairing code below.</li>
          <li>Open the Job Agent extension popup in Chrome.</li>
          <li>Paste the code there before it's used elsewhere — it's single-use.</li>
        </ol>

        <button
          onClick={() => generate.mutate()}
          disabled={generate.isPending}
          className="rounded-md bg-brand-500 px-4 py-2 text-sm font-medium text-white hover:bg-brand-600 disabled:opacity-50"
        >
          {generate.isPending ? "Generating…" : "Generate pairing code"}
        </button>

        {secret && (
          <div className="mt-4 rounded-md bg-slate-100 px-4 py-3 font-mono text-sm text-slate-800">
            {secret}
          </div>
        )}

        {generate.isError && (
          <p className="mt-3 text-sm text-red-600">
            Couldn't reach the backend. Make sure it's running on 127.0.0.1:8765.
          </p>
        )}
      </div>
    </div>
  );
}
