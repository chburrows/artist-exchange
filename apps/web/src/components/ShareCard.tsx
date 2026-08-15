"use client";

import { useEffect, useState } from "react";

import { Avatar } from "@/components/Avatar";
import { BrandMark } from "@/components/BrandMark";
import { LinkIcon, ShareIcon, XIcon } from "@/components/icons";
import { artistAvatar } from "@/lib/avatar";
import { formatCents, formatPct } from "@/lib/format";

export type ShareCardData = {
  username: string;
  best: { name: string; slug: string; gainPct: number; boughtCents: number; nowCents: number };
  equityCents: number;
  todayPct: number | null;
  scoutRank: number | null;
};

// Concrete hexes for the exported PNG -- canvas needs standalone colors
// that read well regardless of the viewer's theme, so the shared image
// always uses the dark brand palette (mirrors the on-screen preview).
const CANVAS = {
  card: "#181b24",
  edge: "#262a37",
  strip: "#12141b",
  text: "#f3f3ef",
  muted: "#9aa0b0",
  faint: "#6b7180",
  accent: "#c4e84a",
  violet: "#c774e6",
  up: "#41cf8a",
  down: "#f0685f",
};

/** Full-screen share sheet: a styled preview of the user's "best call"
 * plus the real virality actions. "Share image" renders the card to an
 * offscreen canvas and hands it to `navigator.share({files})` where
 * available (mobile); everywhere else it downloads the PNG. No
 * image-generation service -- canvas is enough (ARCHITECTURE.md). */
export function ShareCard({ data, onClose }: { data: ShareCardData; onClose: () => void }) {
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const up = data.best.gainPct >= 0;

  const shareImage = async () => {
    setError(null);
    setBusy(true);
    try {
      const blob = await renderCanvas(data);
      if (!blob) throw new Error("Could not render image.");
      const file = new File([blob], "artist-exchange.png", { type: "image/png" });
      if (typeof navigator.share === "function" && navigator.canShare?.({ files: [file] })) {
        await navigator.share({
          files: [file],
          title: "My best call — Artist Exchange",
          text: `${data.best.name} ${up ? "+" : ""}${data.best.gainPct.toFixed(1)}% on Artist Exchange`,
        });
      } else {
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = "artist-exchange.png";
        a.click();
        URL.revokeObjectURL(url);
      }
    } catch (err) {
      // A user dismissing the native share sheet isn't an error.
      if (!(err instanceof DOMException && err.name === "AbortError")) {
        setError("Couldn't create the image. Try downloading instead.");
      }
    } finally {
      setBusy(false);
    }
  };

  const copyLink = async () => {
    try {
      await navigator.clipboard.writeText(window.location.origin);
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    } catch {
      setError("Couldn't copy the link.");
    }
  };

  return (
    <div
      className="animate-fade-in fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-label="Share your best call"
      onClick={onClose}
    >
      <div
        className="animate-pop-in flex w-full max-w-sm flex-col items-center gap-4"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Preview -- mirrors the exported PNG */}
        <div className="border-border w-full overflow-hidden rounded-3xl border bg-card">
          <div className="flex items-center justify-between px-6 pt-6">
            <BrandMark size={16} />
            <span className="text-faint font-mono text-[0.7rem]">@{data.username}</span>
          </div>
          <div className="px-6 pt-5">
            <div className="text-violet mb-3 font-mono text-[0.65rem] font-bold tracking-[0.1em] uppercase">
              My best call
            </div>
            <div className="mb-4 flex items-center gap-3.5">
              <Avatar seed={data.best.slug} entity="artist" size={52} />
              <div className="min-w-0">
                <div className="font-heading truncate text-xl font-bold">{data.best.name}</div>
                <div className="text-muted-foreground text-xs">Top holding</div>
              </div>
            </div>
            <div
              className="font-heading text-6xl leading-none font-bold tabular-nums"
              style={{ color: up ? "var(--positive)" : "var(--destructive)" }}
            >
              {up ? "+" : ""}
              {data.best.gainPct.toFixed(1)}%
            </div>
            <div className="text-muted-foreground mt-2 mb-5 text-sm">
              Bought {formatCents(data.best.boughtCents)} · now {formatCents(data.best.nowCents)}
            </div>
          </div>
          <div className="border-border grid grid-cols-3 border-t">
            <Cell label="Portfolio" value={formatCents(data.equityCents)} />
            <Cell
              label="Today"
              value={data.todayPct !== null ? formatPct(data.todayPct) : "—"}
              tone={data.todayPct !== null ? (data.todayPct >= 0 ? "up" : "down") : undefined}
              bordered
            />
            <Cell
              label="Scout rank"
              value={data.scoutRank !== null ? `#${data.scoutRank}` : "—"}
              tone="violet"
            />
          </div>
          <div className="bg-bg-alt py-3 text-center">
            <span className="text-faint font-mono text-[0.65rem] tracking-wide">
              artistexchange.app
            </span>
          </div>
        </div>

        {error && <p className="text-destructive text-xs">{error}</p>}

        <div className="flex gap-2.5">
          <button
            type="button"
            onClick={shareImage}
            disabled={busy}
            className="press bg-primary text-primary-foreground flex items-center gap-2 rounded-xl px-5 py-3 text-sm font-bold disabled:opacity-60"
          >
            <ShareIcon className="text-base" /> {busy ? "Rendering…" : "Share image"}
          </button>
          <button
            type="button"
            onClick={copyLink}
            className="press border-border-strong text-foreground flex items-center gap-2 rounded-xl border px-5 py-3 text-sm font-bold"
          >
            <LinkIcon className="text-base" /> {copied ? "Copied!" : "Copy link"}
          </button>
        </div>

        <button
          type="button"
          onClick={onClose}
          aria-label="Close"
          className="press flex size-10 items-center justify-center rounded-full bg-white/10 text-white"
        >
          <XIcon className="text-lg" />
        </button>
      </div>
    </div>
  );
}

function Cell({
  label,
  value,
  tone,
  bordered,
}: {
  label: string;
  value: string;
  tone?: "up" | "down" | "violet";
  bordered?: boolean;
}) {
  const color =
    tone === "up"
      ? "text-positive"
      : tone === "down"
        ? "text-destructive"
        : tone === "violet"
          ? "text-violet"
          : "text-foreground";
  return (
    <div
      className={
        bordered ? "border-border border-x px-3 py-4 text-center" : "px-3 py-4 text-center"
      }
    >
      <div className="text-faint mb-1 text-[0.62rem]">{label}</div>
      <div className={`font-mono text-sm font-bold tabular-nums ${color}`}>{value}</div>
    </div>
  );
}

/** Draw the share card to an offscreen canvas at 2x for crisp export.
 * Font family names come from the `--font-*-family` CSS variables --
 * next/font registers hashed family names, so the literal "Space
 * Grotesk" would silently fall back to the system font on canvas. */
async function renderCanvas(data: ShareCardData): Promise<Blob | null> {
  if (typeof document === "undefined") return null;
  try {
    await document.fonts.ready;
  } catch {
    // Fonts API unavailable -- fall through and draw with whatever's ready.
  }

  const cs = getComputedStyle(document.documentElement);
  const heading = `${cs.getPropertyValue("--font-heading-family").trim() || "sans-serif"}, sans-serif`;
  const body = `${cs.getPropertyValue("--font-body-family").trim() || "sans-serif"}, sans-serif`;
  const mono = `${cs.getPropertyValue("--font-mono-family").trim() || "monospace"}, monospace`;

  const W = 540;
  const H = 675;
  const scale = 2;
  const canvas = document.createElement("canvas");
  canvas.width = W * scale;
  canvas.height = H * scale;
  const ctx = canvas.getContext("2d");
  if (!ctx) return null;
  ctx.scale(scale, scale);

  const up = data.best.gainPct >= 0;
  const pad = 36;

  // Card background.
  roundRect(ctx, 0, 0, W, H, 30);
  ctx.fillStyle = CANVAS.card;
  ctx.fill();

  // Brand row.
  drawPentagon(ctx, pad, 44, 18, CANVAS.accent);
  ctx.fillStyle = CANVAS.text;
  ctx.textBaseline = "middle";
  ctx.font = `700 18px ${heading}`;
  ctx.fillText("Artist Exchange", pad + 26, 45);
  ctx.fillStyle = CANVAS.faint;
  ctx.font = `500 13px ${mono}`;
  ctx.textAlign = "right";
  ctx.fillText(`@${data.username}`, W - pad, 45);
  ctx.textAlign = "left";

  // Eyebrow.
  ctx.fillStyle = CANVAS.violet;
  ctx.font = `700 12px ${mono}`;
  ctx.fillText("MY BEST CALL", pad, 108);

  // Avatar + name.
  drawArtistAvatar(ctx, data.best.slug, pad, 128, 60);
  ctx.fillStyle = CANVAS.text;
  ctx.font = `700 24px ${heading}`;
  ctx.fillText(truncate(ctx, data.best.name, W - pad - 116), pad + 76, 150);
  ctx.fillStyle = CANVAS.muted;
  ctx.font = `500 13px ${body}`;
  ctx.fillText("Top holding", pad + 76, 174);

  // Big gain.
  ctx.fillStyle = up ? CANVAS.up : CANVAS.down;
  ctx.font = `700 84px ${heading}`;
  ctx.fillText(`${up ? "+" : ""}${data.best.gainPct.toFixed(1)}%`, pad, 300);

  // Bought / now.
  ctx.fillStyle = CANVAS.muted;
  ctx.font = `500 15px ${body}`;
  ctx.fillText(
    `Bought ${formatCents(data.best.boughtCents)}  ·  now ${formatCents(data.best.nowCents)}`,
    pad,
    352,
  );

  // Divider.
  ctx.strokeStyle = CANVAS.edge;
  ctx.lineWidth = 1;
  line(ctx, pad, 420, W - pad, 420);

  // Stats row.
  const cols = [
    { label: "Portfolio", value: formatCents(data.equityCents), color: CANVAS.text },
    {
      label: "Today",
      value: data.todayPct !== null ? formatPct(data.todayPct) : "—",
      color: data.todayPct !== null ? (data.todayPct >= 0 ? CANVAS.up : CANVAS.down) : CANVAS.text,
    },
    {
      label: "Scout rank",
      value: data.scoutRank !== null ? `#${data.scoutRank}` : "—",
      color: CANVAS.violet,
    },
  ];
  const colW = (W - pad * 2) / 3;
  ctx.textAlign = "center";
  cols.forEach((c, i) => {
    const cx = pad + colW * i + colW / 2;
    ctx.fillStyle = CANVAS.faint;
    ctx.font = `500 12px ${body}`;
    ctx.fillText(c.label, cx, 462);
    ctx.fillStyle = c.color;
    ctx.font = `700 20px ${mono}`;
    ctx.fillText(c.value, cx, 492);
    if (i > 0) {
      ctx.strokeStyle = CANVAS.edge;
      line(ctx, pad + colW * i, 448, pad + colW * i, 506);
    }
  });
  ctx.textAlign = "left";

  // Footer strip.
  roundRectBottom(ctx, 0, H - 56, W, 56, 30);
  ctx.fillStyle = CANVAS.strip;
  ctx.fill();
  ctx.fillStyle = CANVAS.faint;
  ctx.font = `500 13px ${mono}`;
  ctx.textAlign = "center";
  ctx.fillText("artistexchange.app", W / 2, H - 28);
  ctx.textAlign = "left";

  return new Promise((resolve) => canvas.toBlob(resolve, "image/png"));
}

function drawArtistAvatar(
  ctx: CanvasRenderingContext2D,
  seed: string,
  x: number,
  y: number,
  size: number,
) {
  const { bg, facets } = artistAvatar(seed);
  const s = size / 100;
  ctx.save();
  roundRect(ctx, x, y, size, size, size * 0.28);
  ctx.clip();
  ctx.fillStyle = bg;
  ctx.fillRect(x, y, size, size);
  for (const f of facets) {
    const pts = f.points.split(" ").map((p) => p.split(",").map(Number));
    ctx.beginPath();
    pts.forEach(([px, py], i) => {
      const cx = x + px * s;
      const cy = y + py * s;
      if (i === 0) ctx.moveTo(cx, cy);
      else ctx.lineTo(cx, cy);
    });
    ctx.closePath();
    try {
      ctx.fillStyle = f.fill;
    } catch {
      ctx.fillStyle = CANVAS.edge;
    }
    ctx.fill();
  }
  ctx.restore();
}

function drawPentagon(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  size: number,
  color: string,
) {
  const pts = [
    [10, 1],
    [18, 7],
    [15, 19],
    [5, 19],
    [2, 7],
  ];
  const s = size / 20;
  ctx.beginPath();
  pts.forEach(([px, py], i) => {
    const cx = x + px * s;
    const cy = y - size / 2 + py * s;
    if (i === 0) ctx.moveTo(cx, cy);
    else ctx.lineTo(cx, cy);
  });
  ctx.closePath();
  ctx.fillStyle = color;
  ctx.fill();
}

function truncate(ctx: CanvasRenderingContext2D, text: string, maxWidth: number): string {
  if (ctx.measureText(text).width <= maxWidth) return text;
  let t = text;
  while (t.length > 1 && ctx.measureText(t + "…").width > maxWidth) t = t.slice(0, -1);
  return t + "…";
}

function line(ctx: CanvasRenderingContext2D, x1: number, y1: number, x2: number, y2: number) {
  ctx.beginPath();
  ctx.moveTo(x1, y1);
  ctx.lineTo(x2, y2);
  ctx.stroke();
}

function roundRect(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  w: number,
  h: number,
  r: number,
) {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r);
  ctx.closePath();
}

function roundRectBottom(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  w: number,
  h: number,
  r: number,
) {
  ctx.beginPath();
  ctx.moveTo(x, y);
  ctx.lineTo(x + w, y);
  ctx.lineTo(x + w, y + h - r);
  ctx.arcTo(x + w, y + h, x + w - r, y + h, r);
  ctx.lineTo(x + r, y + h);
  ctx.arcTo(x, y + h, x, y + h - r, r);
  ctx.closePath();
}
