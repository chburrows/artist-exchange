"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { ChevronDownIcon, MinusIcon, PlusIcon } from "@/components/icons";
import { errorMessage } from "@/lib/errors";
import { formatCents } from "@/lib/format";
import { useDebouncedValue } from "@/lib/use-debounced-value";
import { useExecuteTrade, usePortfolio, useQuoteTrade } from "@/lib/queries";
import type { TradeSide } from "@/lib/queries";
import { cn } from "@/lib/utils";

/** Buy/sell preview + execute for one artist. Trade quotes are always
 * server-computed (ARCHITECTURE.md) -- there is no client-side
 * `qty * price` estimate anywhere in this component; the stepper only
 * chooses a share count, and every money figure comes from the quote,
 * fetched automatically (debounced) whenever shares/side change. */
export function TradeTicket({
  artistSlug,
  spotPriceCents,
}: {
  artistSlug: string;
  spotPriceCents: number;
}) {
  const [side, setSide] = useState<TradeSide>("buy");
  const [shares, setShares] = useState(1);
  const [executed, setExecuted] = useState<{ shares: number; side: TradeSide; execPriceCents: number } | null>(null);
  const [idempotencyKey, setIdempotencyKey] = useState<string | null>(null);

  const portfolio = usePortfolio(true);
  const debouncedShares = useDebouncedValue(shares, 300);
  const quoteQuery = useQuoteTrade({ artist_slug: artistSlug, side, shares: debouncedShares });
  const executeTrade = useExecuteTrade();
  const quote = quoteQuery.data ?? null;

  const confirm = () => {
    const key = idempotencyKey ?? crypto.randomUUID();
    setIdempotencyKey(key);
    executeTrade.mutate(
      { artist_slug: artistSlug, side, shares, idempotency_key: key },
      {
        onSuccess: (data) => {
          setExecuted({ shares: data.shares, side: data.side, execPriceCents: data.exec_price_cents });
          setIdempotencyKey(null);
        },
      },
    );
  };

  const changeShares = (next: number) => {
    setShares(Math.max(1, Math.floor(next) || 1));
    setExecuted(null);
    executeTrade.reset();
  };

  const changeSide = (next: TradeSide) => {
    setSide(next);
    setExecuted(null);
    executeTrade.reset();
  };

  const cash = portfolio.data?.cash_cents ?? null;
  const balanceAfter =
    quote && cash !== null && quote.violations.length === 0
      ? side === "buy"
        ? cash - quote.total_cents
        : cash + quote.total_cents
      : null;

  return (
    <div className="border-border bg-card flex flex-col gap-3 rounded-2xl border p-4">
      <div className="flex items-center justify-between">
        <h2 className="font-heading text-base font-bold">Trade</h2>
        <span
          title="Live spot price for a single share. Larger orders execute at an average price (Exec price below) that includes AMM slippage."
          className="text-faint cursor-help font-mono text-xs tabular-nums underline decoration-dotted underline-offset-2"
        >
          Market {formatCents(spotPriceCents)}
        </span>
      </div>

      <div className="flex items-center gap-2">
        <div className="bg-secondary flex flex-1 gap-1 rounded-xl p-1">
          <button
            type="button"
            onClick={() => changeSide("buy")}
            className={cn(
              "press min-h-9 flex-1 rounded-lg text-sm font-bold transition-colors",
              side === "buy" ? "bg-primary text-primary-foreground" : "text-muted-foreground",
            )}
          >
            Buy
          </button>
          <button
            type="button"
            onClick={() => changeSide("sell")}
            className={cn(
              "press min-h-9 flex-1 rounded-lg text-sm font-bold transition-colors",
              side === "sell" ? "bg-destructive text-destructive-foreground" : "text-muted-foreground",
            )}
          >
            Sell
          </button>
        </div>

        <div className="flex items-center gap-1.5">
          <button
            type="button"
            onClick={() => changeShares(shares - 1)}
            aria-label="Decrease shares"
            disabled={shares <= 1}
            className="press border-border text-foreground flex size-9 shrink-0 items-center justify-center rounded-lg border disabled:opacity-40"
          >
            <MinusIcon className="text-base" />
          </button>
          <input
            id="shares"
            aria-label="Shares"
            type="number"
            min={1}
            step={1}
            value={shares}
            onChange={(e) => changeShares(Number(e.target.value))}
            className="border-input bg-background focus-visible:ring-ring h-9 w-12 shrink-0 rounded-lg border text-center font-mono text-sm font-bold tabular-nums outline-none focus-visible:ring-2"
          />
          <button
            type="button"
            onClick={() => changeShares(shares + 1)}
            aria-label="Increase shares"
            className="press border-border text-foreground flex size-9 shrink-0 items-center justify-center rounded-lg border"
          >
            <PlusIcon className="text-base" />
          </button>
        </div>
      </div>

      {quoteQuery.isError && <p className="text-destructive text-xs">{errorMessage(quoteQuery.error)}</p>}

      {quote && (
        <div className={cn("bg-secondary flex flex-col gap-1.5 rounded-xl p-3 text-sm", quoteQuery.isFetching && "opacity-60")}>
          <details className="group">
            <summary className="text-muted-foreground hover:text-foreground flex cursor-pointer list-none items-center gap-1.5 text-xs font-semibold [&::-webkit-details-marker]:hidden">
              <ChevronDownIcon className="transition-transform duration-200 group-open:rotate-180" />
              Price breakdown
            </summary>
            <div className="mt-2 flex flex-col gap-1.5">
              <Row
                label="Exec price"
                value={formatCents(quote.exec_price_cents)}
                hint="Average price across all shares in this order, including AMM slippage. Differs from the Market price above for orders over 1 share."
              />
              <Row label="Amount" value={formatCents(quote.amount_cents)} muted />
              <Row label="Fee" value={formatCents(quote.fee_cents)} muted />
            </div>
          </details>
          <div className="border-border my-0.5 border-t" />
          <Row label="Total" value={formatCents(quote.total_cents)} strong />

          {quote.violations.length > 0 ? (
            <p className="text-destructive text-xs">{quote.violations.join(" ")}</p>
          ) : (
            <Button
              type="button"
              onClick={confirm}
              disabled={executeTrade.isPending || quoteQuery.isFetching}
              variant={side === "sell" ? "destructive" : "default"}
              className="mt-0.5"
            >
              {executeTrade.isPending ? "Placing…" : `Confirm ${side}`}
            </Button>
          )}
          {balanceAfter !== null && (
            <p className="text-faint text-center font-mono text-[0.7rem] tabular-nums">
              Balance after: {formatCents(balanceAfter)}
            </p>
          )}
        </div>
      )}
      {executeTrade.isError && <p className="text-destructive text-xs">{errorMessage(executeTrade.error)}</p>}

      {executed && (
        <p className="text-positive text-sm font-semibold">
          {executed.side === "buy" ? "Bought" : "Sold"} {executed.shares} share
          {executed.shares === 1 ? "" : "s"} at {formatCents(executed.execPriceCents)}.
        </p>
      )}
    </div>
  );
}

function Row({
  label,
  value,
  muted,
  strong,
  hint,
}: {
  label: string;
  value: string;
  muted?: boolean;
  strong?: boolean;
  hint?: string;
}) {
  return (
    <div className="flex items-center justify-between">
      <span
        title={hint}
        className={cn(
          muted ? "text-muted-foreground" : "text-foreground",
          strong && "font-bold",
          hint && "cursor-help underline decoration-dotted underline-offset-2",
        )}
      >
        {label}
      </span>
      <span className={cn("font-mono tabular-nums", strong ? "font-bold" : muted ? "text-muted-foreground" : "")}>
        {value}
      </span>
    </div>
  );
}
