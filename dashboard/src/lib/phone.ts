/** A US phone number shown as (614) 555-0142. Anything else is shown as it was saved. */
export function formatPhone(raw: string): string {
  const digits = raw.replace(/\D/g, "");
  const local = digits.length === 11 && digits.startsWith("1") ? digits.slice(1) : digits;
  if (local.length !== 10 || /[a-z]/i.test(raw)) return raw;
  const plus = digits.length === 11 ? "+1 " : "";
  return `${plus}(${local.slice(0, 3)}) ${local.slice(3, 6)}-${local.slice(6)}`;
}
