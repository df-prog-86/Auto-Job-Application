import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "@/api/client";
import { PageHeader } from "@/components/PageHeader";
import { Button, Card } from "@/components/ui";
import { pingExtension } from "@/lib/extensionBridge";

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
  const queryClient = useQueryClient();
  const status = useQuery({ queryKey: ["pairing-status"], queryFn: api.pairingStatus, refetchInterval: 30000 });
  const ping = useQuery({ queryKey: ["extension-ping"], queryFn: pingExtension, staleTime: 60_000 });
  const connected = ping.data?.ok === true;
  const paired = status.data?.paired === true;
  const pairedOn = status.data?.paired_at
    ? new Date(status.data.paired_at).toLocaleDateString("en-US", { month: "short", day: "numeric" })
    : null;

  const generate = useMutation({
    mutationFn: api.createPairingSecret,
    onSuccess: (data) => {
      setSecret(data.pairing_secret);
      setCopied(false);
      void queryClient.invalidateQueries({ queryKey: ["pairing-status"] });
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
        description="One quick step to connect the extension."
      />

      {status.data && (
        <div
          role="status"
          className={`mb-4 flex max-w-xl flex-wrap items-center gap-x-3 gap-y-1 rounded-2xl px-4 py-3.5 text-[14.5px] font-bold ${
            paired ? "bg-[#e8f6ee] text-[#17603f]" : "bg-[#f0eff7] text-ink-700"
          }`}
        >
          <span className="h-2.5 w-2.5 shrink-0 rounded-full bg-current" aria-hidden="true" />
          {paired ? `Paired${pairedOn ? ` on ${pairedOn}` : ""} \u00b7 ${ping.isLoading ? "Checking" : connected ? "Connected" : "Not connected right now"}` : "Not paired"}
          <span className="basis-full pl-[22px] text-[13px] font-semibold opacity-85">
            {paired ? (connected || ping.isLoading ? "Create a new code only to connect another browser." : "Open Chrome to reconnect, or create a new code below.") : "Create a code below to connect the extension."}
          </span>
        </div>
      )}

      <Card className="max-w-xl p-6">
        <ol className="mb-6 space-y-4">
          {[
            "Create a pairing code below.",
            "Open the OtterApply extension in Chrome.",
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
          {generate.isPending ? "Creating…" : secret || paired ? "Create a new code" : "Create pairing code"}
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
