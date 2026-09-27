import { Placeholder } from "@/pages/Placeholder";

export function NeedsAttention() {
  return (
    <Placeholder
      title="Needs Attention"
      description="Every case requiring human input: CAPTCHA, MFA, unknown credentials, unresolved questions."
      milestoneNote="Populated once the extension execution layer and account management land (Milestones 6, 8)."
    />
  );
}
