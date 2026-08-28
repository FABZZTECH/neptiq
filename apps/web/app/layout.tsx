import type { Metadata, Viewport } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";
import "./globals.css";

/*
 * Fonts are self-hosted at build time by next/font, not linked from Google's
 * CDN at runtime. Two reasons that matter here rather than being a preference:
 *
 *  - ARCHITECTURE §4 "Not in the runtime: no ... hosted platform appears in the
 *    production dependency graph or deployment topology". A runtime font
 *    request to fonts.gstatic.com would put a third party in the render path.
 *  - It keeps the CSP tight. No external font origin needs allowing.
 */
const inter = Inter({
  variable: "--font-inter",
  subsets: ["latin"],
  display: "swap",
});

const jetbrainsMono = JetBrains_Mono({
  variable: "--font-jetbrains-mono",
  subsets: ["latin"],
  display: "swap",
});

/*
 * Invariant 6: "No hostname, domain, or URL is hardcoded in source. All come
 * from env vars." NEXT_PUBLIC_APP_URL is the browser-visible mirror of
 * NEPTIQ_APP_URL. It is read here with no fallback string: if it is unset,
 * metadataBase is left undefined and Next emits relative URLs, which is the
 * honest degradation. Substituting "http://localhost:3000" would ship a
 * localhost canonical to production.
 */
const appUrl = process.env.NEXT_PUBLIC_APP_URL;

export const metadata: Metadata = {
  ...(appUrl ? { metadataBase: new URL(appUrl) } : {}),
  title: {
    default: "NEPTIQ",
    template: "%s · NEPTIQ",
  },
  description:
    "The system of record for search work: proves what is wrong, proves the fix shipped, and proves what happened next.",
  applicationName: "NEPTIQ",
  icons: {
    /*
     * These files are produced by `make brand` from the SVG masters in brand/.
     * They are gitignored generated output — the masters are the source of
     * truth. A missing icon here means `make brand` has not been run.
     */
    icon: [
      { url: "/brand/favicon.svg", type: "image/svg+xml" },
      { url: "/brand/favicon.ico", sizes: "any" },
    ],
    apple: [{ url: "/brand/apple-touch-icon.png", sizes: "180x180" }],
  },
  /*
   * The app is authenticated and behind a login; there is nothing here for a
   * crawler, and P13 ("be a good citizen of the web") cuts both ways — we do
   * not want other crawlers spending budget on our app shell. The marketing
   * route group overrides this locally where indexing IS wanted.
   */
  robots: { index: false, follow: false },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: [
    // Values mirrored from brand/tokens.css; CI enforces they stay in step.
    { media: "(prefers-color-scheme: light)", color: "#FAFAF8" },
    { media: "(prefers-color-scheme: dark)", color: "#0B0F14" },
  ],
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${inter.variable} ${jetbrainsMono.variable} h-full`}
    >
      <body className="flex min-h-full flex-col">
        {/*
          Skip link. The findings views are long lists behind a persistent nav;
          without this, a keyboard user tabs through the entire chrome on every
          page load.
        */}
        <a
          href="#main"
          className="sr-only focus:not-sr-only focus:absolute focus:top-2 focus:left-2 focus:z-50 focus:rounded focus:bg-surface-raised focus:px-3 focus:py-2 focus:text-on-surface"
        >
          Skip to main content
        </a>
        {children}
      </body>
    </html>
  );
}
