/** Shared SVG line-path geometry for the app's two line charts
 * (PriceChart, PortfolioValueChart) -- kept in one place so padding/scale
 * math can't drift between them. `null` entries break the line into
 * separate subpaths (a sparse series, e.g. fair-value). Points are
 * spaced evenly by *index*, never elapsed time -- backfilled/dev history
 * is unevenly spaced and a time-based x-axis would misrepresent it
 * (ARCHITECTURE.md). */
export function buildLinePath(
  values: (number | null)[],
  min: number,
  max: number,
  { width, height, pad }: { width: number; height: number; pad: number },
): string {
  const span = max - min || 1;
  const step = values.length > 1 ? (width - pad * 2) / (values.length - 1) : 0;
  let d = "";
  let penDown = false;
  values.forEach((v, i) => {
    if (v === null) {
      penDown = false;
      return;
    }
    const x = pad + i * step;
    const y = height - pad - ((v - min) / span) * (height - pad * 2);
    d += `${penDown ? " L" : " M"}${x.toFixed(1)},${y.toFixed(1)}`;
    penDown = true;
  });
  return d.trim();
}
