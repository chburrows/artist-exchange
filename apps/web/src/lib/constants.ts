/** Mirrors services/api/src/ax/core/config.py -- keep in sync if that
 * value is retuned. Used only for onboarding marketing copy shown before
 * an account (and its real `cash_cents`) exists; every post-signup
 * balance comes straight from the API, never from this constant. */
export const STARTING_BALANCE_CENTS = 1_000_000;
