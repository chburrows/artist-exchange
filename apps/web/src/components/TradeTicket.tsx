"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { MinusIcon, PlusIcon } from "@/components/icons";
import { errorMessage } from "@/lib/errors";
import { formatCents } from "@/lib/format";
import { useExecuteTrade, usePortfolio, useQuoteTrade } from "@/lib/queries";
import type { QuoteResponse, TradeSide } from "@/lib/queries";
import { cn } from "@/lib/utils";

/** Buy/sell preview + execute for one artist. Trade quotes are always
 * server-computed (ARCHITECTURE.md) -- there is no client-side
 * `qty * price` estimate anywhere in this component; the stepper only
 * chooses a share count, and every money figure comes from the quote. */
export function TradeTicket({
  artistSlug,
  spotPriceCents,
}: {
  artistSlug: string;
  spotPriceCents: number;
}) {
  const [side, setSide] = useState<TradeSide>("buy");
  const [shares, setShares] = useState(1);
  const [quote, setQuote] = useState<QuoteResponse | null>(null);
  const [executed, setExecuted] = useState<{ shares: number; side: TradeSide; execPriceCents: number } | null>(null);
  const [idempotencyKey, setIdempotencyKey] = useState<string | null>(null);

  const portfolio = usePortfolio(true);
  const quoteTrade = useQuoteTrade();
  const executeTrade = useExecuteTrade();

  const requestQuote = () => {
    setExecuted(null);
    quoteTrade.mutate({ artist_slug: artistSlug, side, shares }, { onSuccess: (data) => setQuote(data) });
  };

  const confirm = () => {
    const key = idempotencyKey ?? crypto.randomUUID();
    setIdempotencyKey(key);
    executeTrade.mutate(
      { artist_slug: artistSlug, side, shares, idempotency_key: key },
      {
        onSuccess: (data) => {
          setExecuted({ shares: data.shares, side: data.side, execPriceCents: data.exec_price_cents });
          setQuote(null);
          setIdempotencyKey(null);
        },
      },
    );
  };

  const resetPreview = () => {
    setQuote(null);
    setExecuted(null);
    setIdempotencyKey(null);
    quoteTrade.reset();
    executeTrade.reset();
  };

  const changeShares = (next: number) => {
    setShares(Math.max(1, Math.floor(next) || 1));
    resetPreview();
  };

  const changeSide = (next: TradeSide) => {
    setSide(next);
    resetPreview();
  };

  const cash = portfolio.data?.cash_cents ?? null;
  const balanceAfter =
    quote && cash !== null && quote.violations.length === 0
      ? side === "buy"
        ? cash - quote.total_cents
        : cash + quote.total_cents
      : null;

  return (
    <div className="border-border bg-card flex flex-col gap-4 rounded-2xl border p-4">
      <div className="flex items-center justify-between">
        <h2 className="font-heading text-base font-bold">Trade</h2>
        <span className="text-faint font-mono text-xs tabular-nums">Market {formatCents(spotPriceCents)}</span>
      </div>

      <div className="bg-secondary flex gap-1 rounded-xl p-1">
        <button
          type="button"
          onClick={() => changeSide("buy")}
          className={cn(
            "press min-h-10 flex-1 rounded-lg text-sm font-bold transition-colors",
            side === "buy" ? "bg-primary text-primary-foreground" : "text-muted-foreground",
          )}
        >
          Buy
        </button>
        <button
          type="button"
          onClick={() => changeSide("sell")}
          className={cn(
            "press min-h-10 flex-1 rounded-lg text-sm font-bold transition-colors",
            side === "sell" ? "bg-destructive text-destructive-foreground" : "text-muted-foreground",
          )}
        >
          Sell
        </button>
      </div>

      <div className="flex items-center justify-between gap-3">
        <label htmlFor="shares" className="text-muted-foreground text-sm font-medium">
          Shares
        </label>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => changeShares(shares - 1)}
            aria-label="Decrease shares"
            disabled={shares <= 1}
            className="press border-border text-foreground flex size-9 items-center justify-center rounded-lg border disabled:opacity-40"
          >
            <MinusIcon className="text-base" />
          </button>
          <input
            id="shares"
            type="number"
            min={1}
            step={1}
            value={shares}
            onChange={(e) => changeShares(Number(e.target.value))}
            className="border-input bg-background focus-visible:ring-ring h-9 w-16 rounded-lg border text-center font-mono text-sm font-bold tabular-nums outline-none focus-visible:ring-2"
          />
          <button
            type="button"
            onClick={() => changeShares(shares + 1)}
            aria-label="Increase shares"
            className="press border-border text-foreground flex size-9 items-center justify-center rounded-lg border"
          >
            <PlusIcon className="text-base" />
          </button>
        </div>
      </div>

      {!quote && (
        <Button type="button" variant="outline" onClick={requestQuote} disabled={quoteTrade.isPending}>
          {quoteTrade.isPending ? "Getting quote…" : "Get quote"}
        </Button>
      )}
      {quoteTrade.isError && <p className="text-destructive text-xs">{errorMessage(quoteTrade.error)}</p>}

      {quote && (
        <div className="bg-secondary flex flex-col gap-2 rounded-xl p-3.5 text-sm">
          <Row label="Exec price" value={formatCents(quote.exec_price_cents)} />
          <Row label="Amount" value={formatCents(quote.amount_cents)} muted />
          <Row label="Fee" value={formatCents(quote.fee_cents)} muted />
          <div className="border-border my-0.5 border-t" />
          <Row label="Total" value={formatCents(quote.total_cents)} strong />

          {quote.violations.length > 0 ? (
            <p className="text-destructive text-xs">{quote.violations.join(" ")}</p>
          ) : (
            <Button
              type="button"
              onClick={confirm}
              disabled={executeTrade.isPending}
              variant={side === "sell" ? "destructive" : "default"}
              className="mt-1"
            >
              {executeTrade.isPending ? "Placing…" : `Confirm ${side}`}
            </Button>
          )}
          {balanceAfter !== null && (
            <p className="text-faint text-center font-mono text-[0.7rem] tabular-nums">
              Balance after: {formatCents(balanceAfter)}
            </p>
          )}
          <button
            type="button"
            className="text-muted-foreground hover:text-foreground text-xs underline underline-offset-2"
            onClick={() => setQuote(null)}
          >
            Cancel
          </button>
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
}: {
  label: string;
  value: string;
  muted?: boolean;
  strong?: boolean;
}) {
  return (
    <div className="flex items-center justify-between">
      <span className={cn(muted ? "text-muted-foreground" : "text-foreground", strong && "font-bold")}>
        {label}
      </span>
      <span className={cn("font-mono tabular-nums", strong ? "font-bold" : muted ? "text-muted-foreground" : "")}>
        {value}
      </span>
    </div>
  );
}
