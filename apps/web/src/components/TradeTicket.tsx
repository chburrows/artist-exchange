"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { errorMessage } from "@/lib/errors";
import { formatCents } from "@/lib/format";
import { type TradeSide, useExecuteTrade, useTradeQuote } from "@/lib/queries";

export function TradeTicket({
  artistSlug,
  userShares,
}: {
  artistSlug: string;
  userShares: number;
}) {
  const [side, setSide] = useState<TradeSide>("buy");
  const [qty, setQty] = useState(10);
  // Tracks which (side, qty) the last successful trade was for, so the
  // confirmation banner disappears as soon as either changes -- derived
  // during render instead of reset via an effect.
  const [confirmedFor, setConfirmedFor] = useState<{ side: TradeSide; qty: number; message: string } | null>(
    null,
  );

  const quote = useTradeQuote(qty > 0 ? { artistSlug, side, shares: qty } : null);
  const execute = useExecuteTrade();

  const confirmed =
    confirmedFor && confirmedFor.side === side && confirmedFor.qty === qty ? confirmedFor.message : null;

  // No naive `qty * spotPrice` fallback: the AMM's real cost/proceeds
  // include a per-share slippage term and a fee that a linear multiply
  // can't reproduce, so a wrong-but-confident number is worse here than a
  // loading state until the real quote lands.
  const estCents = quote.data?.total_cents;
  const violations = quote.data?.violations ?? [];
  const sellingMoreThanHeld = side === "sell" && qty > userShares;

  const handleConfirm = () => {
    execute.mutate(
      { artistSlug, side, shares: qty },
      {
        onSuccess: (data) => {
          setConfirmedFor({
            side,
            qty,
            message: `${side === "buy" ? "Bought" : "Sold"} ${data.shares} share${data.shares === 1 ? "" : "s"} at ${formatCents(data.exec_price_cents)}`,
          });
        },
      },
    );
  };

  return (
    <div className="rounded-2xl border border-border bg-card p-5">
      <Tabs value={side} onValueChange={(v) => setSide(v as TradeSide)}>
        <TabsList className="grid w-full grid-cols-2">
          <TabsTrigger value="buy">Buy</TabsTrigger>
          <TabsTrigger value="sell">Sell</TabsTrigger>
        </TabsList>
      </Tabs>

      <div className="mt-4 flex items-center gap-3">
        <span className="text-sm text-muted-foreground">Shares</span>
        <Button
          variant="outline"
          size="icon"
          aria-label="Decrease shares"
          onClick={() => setQty((q) => Math.max(1, q - 1))}
        >
          –
        </Button>
        <span className="w-8 text-center text-sm font-bold tabular-nums">{qty}</span>
        <Button
          variant="outline"
          size="icon"
          aria-label="Increase shares"
          onClick={() => setQty((q) => q + 1)}
        >
          +
        </Button>
        <span className="ml-auto text-right text-sm text-muted-foreground">
          Est. {side === "buy" ? "cost" : "proceeds"}{" "}
          <b className="font-bold text-foreground">
            {estCents !== undefined ? formatCents(estCents) : "…"}
          </b>
        </span>
      </div>

      {side === "sell" && (
        <div className="mt-2 text-xs text-muted-foreground">You hold {userShares} shares</div>
      )}

      {sellingMoreThanHeld && (
        <div className="mt-3 rounded-xl bg-destructive/10 p-3 text-xs text-destructive">
          You only hold {userShares} shares.
        </div>
      )}
      {!sellingMoreThanHeld && violations.length > 0 && (
        <div className="mt-3 rounded-xl bg-destructive/10 p-3 text-xs text-destructive">
          {violations.join(" ")}
        </div>
      )}
      {quote.isError && (
        <div className="mt-3 rounded-xl bg-destructive/10 p-3 text-xs text-destructive">
          {errorMessage(quote.error)}
        </div>
      )}
      {execute.isError && (
        <div className="mt-3 rounded-xl bg-destructive/10 p-3 text-xs text-destructive">
          {errorMessage(execute.error)}
        </div>
      )}
      {confirmed && (
        <div className="mt-3 rounded-xl bg-positive/10 p-3 text-xs text-positive">{confirmed}</div>
      )}

      <Button
        className="mt-4 w-full"
        size="lg"
        disabled={
          execute.isPending ||
          quote.isError ||
          violations.length > 0 ||
          sellingMoreThanHeld ||
          (side === "sell" && userShares === 0)
        }
        onClick={handleConfirm}
      >
        {execute.isPending ? "Submitting…" : `${side === "buy" ? "Buy" : "Sell"} ${qty} share${qty === 1 ? "" : "s"}`}
      </Button>
    </div>
  );
}
