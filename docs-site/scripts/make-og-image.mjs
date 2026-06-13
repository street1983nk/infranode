// Generiert public/og-image.png (1200x630) aus dem Logo plus Claim.
// Weisser Grund, Petrol/Gruen-Akzente, Logo oben, Claim darunter. Nutzt sharp
// aus node_modules. Einmaliger Build-Helfer: `node scripts/make-og-image.mjs`.
import sharp from "sharp";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = join(__dirname, "..");
const logoPath = join(root, "public", "logo-infranode.png");
const outPath = join(root, "public", "og-image.png");

const W = 1200;
const H = 630;
const PETROL = "#1d4e5c";
const GREEN = "#5f9e2f";

// Logo auf feste Breite skalieren (Seitenverhaeltnis 1408x768) und ggf.
// vorhandenen hellen Rand wegtrimmen, damit kein Kasten entsteht.
const logoW = 380;
const logoH = Math.round((logoW * 768) / 1408);
const logoBuf = await sharp(logoPath)
  .trim({ threshold: 12 })
  .resize(logoW, logoH, { fit: "inside", background: { r: 255, g: 255, b: 255, alpha: 0 } })
  .png()
  .toBuffer();
const logoMeta = await sharp(logoBuf).metadata();
const logoTop = 130;

// Hintergrund-SVG: weisser Grund, Petrol/Gruen-Akzentbalken, Claim und
// Sub-Claim deutlich unter dem Logo (keine Ueberlappung).
const svg = `<svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg">
  <rect width="${W}" height="${H}" fill="#ffffff"/>
  <rect x="0" y="0" width="${W}" height="14" fill="${PETROL}"/>
  <rect x="0" y="${H - 14}" width="${W}" height="14" fill="${GREEN}"/>
  <text x="${W / 2}" y="430" text-anchor="middle"
        font-family="Segoe UI, Helvetica, Arial, sans-serif" font-size="50"
        font-weight="700" fill="${PETROL}">Offene Stadtdaten-API für Deutschland</text>
  <text x="${W / 2}" y="492" text-anchor="middle"
        font-family="Segoe UI, Helvetica, Arial, sans-serif" font-size="28"
        fill="#56656c">84 Großstädte, ein konsistenter JSON-Envelope, ohne Schlüssel</text>
  <rect x="${W / 2 - 60}" y="528" width="120" height="6" rx="3" fill="${GREEN}"/>
</svg>`;

await sharp(Buffer.from(svg))
  .composite([
    { input: logoBuf, top: logoTop, left: Math.round((W - (logoMeta.width ?? logoW)) / 2) },
  ])
  .png()
  .toFile(outPath);

console.log(`og-image.png erzeugt: ${W}x${H} -> ${outPath}`);
