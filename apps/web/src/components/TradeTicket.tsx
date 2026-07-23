"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { errorMessage } from "@/lib/errors";
import { formatCents } from "@/lib/format";
import { useExecuteTrade, useQuoteTrade } from "@/lib/queries";
import type { QuoteResponse, TradeSide } from "@/lib/queries";

/** Buy/sell preview + execute for one artist. Trade quotes are always
 * server-computed (ARCHITECTURE.md) -- there is no client-side
 * `qty * price` estimate anywhere in this component. */
export function TradeTicket({ artistSlug }: { artistSlug: string }) {
  const [side, setSide] = useState<TradeSide>("buy");
  const [shares, setShares] = useState(1);
  const [quote, setQuote] = useState<QuoteResponse | null>(null);
  const [executed, setExecuted] = useState<{ shares: number; side: TradeSide; execPriceCents: number } | null>(null);
  const [idempotencyKey, setIdempotencyKey] = useState<string | null>(null);

  const quoteTrade = useQuoteTrade();
  const executeTrade = useExecuteTrade();

  const requestQuote = () => {
    setExecuted(null);
    quoteTrade.mutate(
      { artist_slug: artistSlug, side, shares },
      { onSuccess: (data) => setQuote(data) },
    );
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

  const changeShares = (next: number) => {
    setShares(next);
    setQuote(null);
    setExecuted(null);
    setIdempotencyKey(null);
    quoteTrade.reset();
    executeTrade.reset();
  };

  const changeSide = (next: TradeSide) => {
    setSide(next);
    setQuote(null);
    setExecuted(null);
    setIdempotencyKey(null);
    quoteTrade.reset();
    executeTrade.reset();
  };

  return (
    <div className="flex flex-col gap-3 rounded-xl border border-border p-4">
      <h2 className="text-sm font-bold">Trade</h2>

      <div className="flex gap-2">
        <button
          type="button"
          onClick={() => changeSide("buy")}
          className={`min-h-11 flex-1 rounded-lg border border-border text-sm font-bold ${
            side === "buy" ? "bg-primary text-primary-foreground" : "text-muted-foreground"
          }`}
        >
          Buy
        </button>
        <button
          type="button"
          onClick={() => changeSide("sell")}
          className={`min-h-11 flex-1 rounded-lg border border-border text-sm font-bold ${
            side === "sell" ? "bg-destructive text-destructive-foreground" : "text-muted-foreground"
          }`}
        >
          Sell
        </button>
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor="shares">Shares</Label>
        <Input
          id="shares"
          type="number"
          min={1}
          step={1}
          value={shares}
          onChange={(e) => changeShares(Math.max(1, Math.floor(Number(e.target.value) || 1)))}
        />
      </div>

      {!quote && (
        <Button type="button" variant="outline" onClick={requestQuote} disabled={quoteTrade.isPending}>
          {quoteTrade.isPending ? "Getting quote…" : "Get quote"}
        </Button>
      )}
      {quoteTrade.isError && <p className="text-xs text-destructive">{errorMessage(quoteTrade.error)}</p>}

      {quote && (
        <div className="flex flex-col gap-2 rounded-lg bg-secondary p-3 text-sm">
          <div className="flex justify-between">
            <span className="text-muted-foreground">Exec price</span>
            <span className="font-bold">{formatCents(quote.exec_price_cents)}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-muted-foreground">Amount</span>
            <span>{formatCents(quote.amount_cents)}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-muted-foreground">Fee</span>
            <span>{formatCents(quote.fee_cents)}</span>
          </div>
          <div className="flex justify-between font-bold">
            <span>Total</span>
            <span>{formatCents(quote.total_cents)}</span>
          </div>

          {quote.violations.length > 0 ? (
            <p className="text-xs text-destructive">{quote.violations.join(" ")}</p>
          ) : (
            <Button type="button" onClick={confirm} disabled={executeTrade.isPending}>
              {executeTrade.isPending ? "Placing…" : `Confirm ${side}`}
            </Button>
          )}
          <button
            type="button"
            className="text-xs text-muted-foreground underline underline-offset-2"
            onClick={() => setQuote(null)}
          >
            Cancel
          </button>
        </div>
      )}
      {executeTrade.isError && <p className="text-xs text-destructive">{errorMessage(executeTrade.error)}</p>}

      {executed && (
        <p className="text-sm text-positive">
          {executed.side === "buy" ? "Bought" : "Sold"} {executed.shares} share{executed.shares === 1 ? "" : "s"} at{" "}
          {formatCents(executed.execPriceCents)}.
        </p>
      )}
    </div>
  );
}
