"use client";

import { useEffect, useRef, useState } from "react";

import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { hashString } from "@/lib/avatar";
import { formatCents, formatPct } from "@/lib/format";
import type { PortfolioPosition } from "@/lib/queries";

const WIDTH = 720;
const HEIGHT = 960;

function hues(seed: string): [number, number] {
  const hash = hashString(seed);
  return [hash % 360, (hash % 360) + 35 + (hash % 25)];
}

function drawCard(
  ctx: CanvasRenderingContext2D,
  data: {
    username: string;
    equityCents: number;
    totalGainPct: number;
    topPositions: PortfolioPosition[];
  },
) {
  const { username, equityCents, totalGainPct, topPositions } = data;
  const positive = totalGainPct >= 0;
  const [h1, h2] = hues(username);

  // Background -- a fixed dark gradient regardless of the viewer's own
  // theme: this image is meant to look identical wherever it lands
  // (Instagram, Twitter, iMessage), not follow app dark/light state.
  const bg = ctx.createLinearGradient(0, 0, WIDTH, HEIGHT);
  bg.addColorStop(0, `hsl(${h1} 45% 12%)`);
  bg.addColorStop(1, `hsl(${h2} 45% 7%)`);
  ctx.fillStyle = bg;
  ctx.fillRect(0, 0, WIDTH, HEIGHT);

  ctx.textBaseline = "alphabetic";

  // Wordmark
  ctx.fillStyle = "rgba(255,255,255,0.55)";
  ctx.font = "700 24px system-ui, sans-serif";
  ctx.fillText("ARTIST EXCHANGE", 56, 90);

  // Avatar circle
  const avatarGrad = ctx.createLinearGradient(56, 130, 136, 210);
  avatarGrad.addColorStop(0, `hsl(${h1} 65% 55%)`);
  avatarGrad.addColorStop(1, `hsl(${h2} 60% 40%)`);
  ctx.fillStyle = avatarGrad;
  ctx.beginPath();
  ctx.arc(96, 170, 40, 0, Math.PI * 2);
  ctx.fill();

  // Username
  ctx.fillStyle = "#ffffff";
  ctx.font = "700 32px system-ui, sans-serif";
  ctx.fillText(username, 154, 182);

  // Equity value
  ctx.fillStyle = "rgba(255,255,255,0.6)";
  ctx.font = "600 20px system-ui, sans-serif";
  ctx.fillText("Portfolio value", 56, 290);
  ctx.fillStyle = "#ffffff";
  ctx.font = "800 76px system-ui, sans-serif";
  ctx.fillText(formatCents(equityCents), 56, 370);

  // Return
  ctx.fillStyle = positive ? "hsl(150 60% 55%)" : "hsl(0 70% 62%)";
  ctx.font = "700 34px system-ui, sans-serif";
  ctx.fillText(`${formatPct(totalGainPct)} all-time`, 56, 420);

  // Holdings
  let y = 500;
  if (topPositions.length > 0) {
    ctx.fillStyle = "rgba(255,255,255,0.5)";
    ctx.font = "700 18px system-ui, sans-serif";
    ctx.fillText("TOP HOLDINGS", 56, y);
    y += 40;

    for (const position of topPositions.slice(0, 3)) {
      const [ph1, ph2] = hues(position.artist_slug);
      const dotGrad = ctx.createLinearGradient(56, y - 24, 96, y + 4);
      dotGrad.addColorStop(0, `hsl(${ph1} 65% 55%)`);
      dotGrad.addColorStop(1, `hsl(${ph2} 60% 40%)`);
      ctx.fillStyle = dotGrad;
      ctx.beginPath();
      ctx.arc(72, y - 10, 20, 0, Math.PI * 2);
      ctx.fill();

      ctx.fillStyle = "#ffffff";
      ctx.font = "600 26px system-ui, sans-serif";
      ctx.fillText(position.artist_name, 108, y);

      const gain = position.unrealized_pnl_cents >= 0;
      ctx.fillStyle = gain ? "hsl(150 60% 55%)" : "hsl(0 70% 62%)";
      ctx.font = "700 26px system-ui, sans-serif";
      const gainText = formatCents(position.unrealized_pnl_cents);
      const metrics = ctx.measureText(gainText);
      ctx.fillText(gainText, WIDTH - 56 - metrics.width, y);

      y += 56;
    }
  }

  // Footer
  ctx.fillStyle = "rgba(255,255,255,0.4)";
  ctx.font = "500 18px system-ui, sans-serif";
  ctx.fillText("Play money. Not affiliated with or endorsed by any artist.", 56, HEIGHT - 48);
}

export function ShareCardDialog({
  open,
  onOpenChange,
  username,
  equityCents,
  totalGainPct,
  topPositions,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  username: string;
  equityCents: number;
  totalGainPct: number;
  topPositions: PortfolioPosition[];
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [busy, setBusy] = useState(false);

  const sorted = [...topPositions].sort((a, b) => b.market_value_cents - a.market_value_cents);

  useEffect(() => {
    if (!open) return;
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !ctx) return;
    drawCard(ctx, { username, equityCents, totalGainPct, topPositions: sorted });
    // sorted is derived fresh every render from topPositions -- listing
    // it as a dep would re-run this effect every render for no reason.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, username, equityCents, totalGainPct]);

  async function handleShare() {
    const canvas = canvasRef.current;
    if (!canvas) return;
    setBusy(true);
    try {
      const blob: Blob | null = await new Promise((resolve) =>
        canvas.toBlob(resolve, "image/png"),
      );
      if (!blob) return;
      const file = new File([blob], "artist-exchange-portfolio.png", { type: "image/png" });

      // Mobile-first: a native share sheet (Messages, Instagram, etc.) if
      // the browser supports sharing files at all. Desktop browsers
      // typically don't, so they fall through to a plain download.
      if (
        typeof navigator.share === "function" &&
        typeof navigator.canShare === "function" &&
        navigator.canShare({ files: [file] })
      ) {
        await navigator.share({
          files: [file],
          title: "My Artist Exchange portfolio",
          text: `${formatPct(totalGainPct)} all-time on Artist Exchange`,
        });
        return;
      }

      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "artist-exchange-portfolio.png";
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      // AbortError from a user canceling the native share sheet is
      // expected, not a failure worth surfacing.
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-sm">
        <DialogHeader>
          <DialogTitle>Share your portfolio</DialogTitle>
        </DialogHeader>
        <div className="overflow-hidden rounded-xl border border-border">
          <canvas
            ref={canvasRef}
            width={WIDTH}
            height={HEIGHT}
            className="block h-auto w-full"
            aria-label="Portfolio share card preview"
          />
        </div>
        <Button onClick={handleShare} disabled={busy} className="mt-4 w-full">
          {busy ? "Preparing…" : "Share image"}
        </Button>
      </DialogContent>
    </Dialog>
  );
}
