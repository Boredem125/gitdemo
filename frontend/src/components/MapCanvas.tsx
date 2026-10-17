import { useEffect, useRef, useState } from "react";
import type { MapInfo } from "../api";

export type Layer = (ctx: CanvasRenderingContext2D, toPx: (x: number, y: number) => [number, number], kmToPx: number) => void;

type Props = {
  map: MapInfo | undefined;
  layers: Layer[];
  /** optional view box in km [x0, y0, x1, y1] to zoom into */
  view?: [number, number, number, number];
};

const imageCache = new Map<string, HTMLImageElement>();

/** Square map with the reference image underneath and vector layers on top (km coords). */
export function MapCanvas({ map, layers, view }: Props) {
  const ref = useRef<HTMLCanvasElement>(null);
  const wrap = useRef<HTMLDivElement>(null);
  const [img, setImg] = useState<HTMLImageElement | null>(null);
  const [size, setSize] = useState(600);

  useEffect(() => {
    if (!map?.has_image) {
      setImg(null);
      return;
    }
    const cached = imageCache.get(map.name);
    if (cached?.complete) {
      setImg(cached);
      return;
    }
    const im = cached ?? new Image();
    im.src = `/api/maps/${map.name}/image`;
    imageCache.set(map.name, im);
    im.onload = () => setImg(im);
  }, [map]);

  useEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setSize(Math.min(el.clientWidth, 900)));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  useEffect(() => {
    const c = ref.current;
    if (!c || !map) return;
    const dpr = window.devicePixelRatio || 1;
    c.width = size * dpr;
    c.height = size * dpr;
    const ctx = c.getContext("2d")!;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const [vx0, vy0, vx1, vy1] = view ?? [0, 0, map.size_km, map.size_km];
    const span = Math.max(vx1 - vx0, vy1 - vy0);
    const kmToPx = size / span;
    const toPx = (x: number, y: number): [number, number] => [(x - vx0) * kmToPx, (y - vy0) * kmToPx];

    ctx.fillStyle = "#0b1220";
    ctx.fillRect(0, 0, size, size);
    if (img) {
      // reference image placement in km: u = x/size*scale + du  ->  image spans km [-du*S/scale, (1-du)*S/scale]
      const [scale, du, dv] = map.display;
      const S = map.size_km;
      const ix0 = (-du * S) / scale;
      const iy0 = (-dv * S) / scale;
      const iw = S / scale;
      const [px, py] = toPx(ix0, iy0);
      ctx.globalAlpha = 0.85;
      ctx.drawImage(img, px, py, iw * kmToPx, iw * kmToPx);
      ctx.globalAlpha = 1;
    }
    // 1 km grid
    ctx.strokeStyle = "rgba(255,255,255,0.10)";
    ctx.lineWidth = 1;
    for (let k = 0; k <= map.size_km; k++) {
      const [gx] = toPx(k, 0);
      const [, gy] = toPx(0, k);
      ctx.beginPath();
      ctx.moveTo(gx, 0);
      ctx.lineTo(gx, size);
      ctx.moveTo(0, gy);
      ctx.lineTo(size, gy);
      ctx.stroke();
    }
    for (const layer of layers) layer(ctx, toPx, kmToPx);
  }, [img, map, layers, size, view]);

  return (
    <div ref={wrap} className="map-wrap">
      <canvas ref={ref} style={{ width: size, height: size }} />
      {!map && <div className="map-empty">Map not identified for this match</div>}
    </div>
  );
}

export function teamColor(c: string, fallback = "#9aa4b2"): string {
  return /^#[0-9a-f]{6}$/i.test(c) ? c : fallback;
}
