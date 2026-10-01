import { ComingSoon } from "@/pages/Placeholder";

export function NeedsAttention() {
  return (
    <ComingSoon
      title="Needs Attention"
      description="The few things only you can answer."
      points={[
        "Application questions the app is not sure how to answer for you.",
        "Anything that needs a quick yes or no before it moves forward.",
        "Nothing is ever sent without your approval.",
      ]}
    />
  );
}
