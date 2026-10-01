import { useMutation } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "@/api/client";
import { PageHeader } from "@/components/PageHeader";
import { Button, Card } from "@/components/ui";

/**
 * First-run pairing (spec §8.3): the dashboard requests a one-time secret
 * from the backend and displays it; the user pastes it into the extension
 * popup, which calls /api/v1/system/pair itself to get a persistent token.
 * The dashboard never sees or holds the extension's token, only the
 * short-lived secret that authorizes issuing one.
 */
export function Pairing() {
  const [secret, setSecret] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const generate = useMutation({
    mutationFn: api.createPairingSecret,
    onSuccess: (data) => {
      setSecret(data.pairing_secret);
      setCopied(false);
    },
  });

  async function copy() {
    if (!secret) return;
    try {
      await navigator.clipboard.writeText(secret);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  }

  return (
    <div>
      <PageHeader
        title="Pair the extension"
        description="A one-time step that connects the Chrome extension to this app."
      />

      <Card className="max-w-xl p-6">
        <ol className="mb-6 space-y-4">
          {[
            "Create a pairing code below.",
            "Open the Job Agent extension in Chrome.",
            "Paste the code there. It works once, so use it right away.",
          ].map((text, i) => (
            <li key={text} className="flex items-center gap-3 text-sm text-ink-700">
              <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-brand-50 text-xs font-bold text-brand-700">
                {i + 1}
              </span>
              {text}
            </li>
          ))}
        </ol>

        <Button variant="primary" onClick={() => generate.mutate()} disabled={generate.isPending}>
          {generate.isPending ? "Creating…" : secret ? "Create a new code" : "Create pairing code"}
        </Button>

        {secret && (
          <div className="mt-5 flex items-center justify-between gap-3 rounded-2xl bg-ink-900/[0.04] px-4 py-3">
            <code className="min-w-0 break-all font-mono text-sm text-ink-900">{secret}</code>
            <Button size="sm" onClick={() => void copy()}>
              {copied ? "Copied" : "Copy"}
            </Button>
          </div>
        )}

        {generate.isError && (
          <p className="mt-3 text-sm text-red-600">
            Can't reach the backend. Make sure it is running, then try again.
          </p>
        )}
      </Card>
    </div>
  );
}
