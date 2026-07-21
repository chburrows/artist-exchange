/** Every mutation's error is whatever `unwrap()` in queries.ts threw --
 * the raw, typed-as-unknown `error` field openapi-fetch returns for a
 * non-2xx response. FastAPI's error bodies take one of a few shapes
 * depending on the failure: a plain string `detail` (HTTPException), a
 * `{violations: string[]}` detail (422 from execute_trade's own
 * guardrail checks), or pydantic's `detail: ValidationError[]`. */
export function errorMessage(error: unknown, fallback = "Something went wrong -- try again."): string {
  if (error && typeof error === "object" && "detail" in error) {
    const detail = (error as { detail?: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (detail && typeof detail === "object" && "violations" in detail) {
      const violations = (detail as { violations?: unknown }).violations;
      if (Array.isArray(violations)) return violations.join(" ");
    }
    if (Array.isArray(detail)) {
      return (
        detail
          .map((d) => (d && typeof d === "object" && "msg" in d ? String((d as { msg?: unknown }).msg) : ""))
          .filter(Boolean)
          .join(" ") || fallback
      );
    }
  }
  return fallback;
}
