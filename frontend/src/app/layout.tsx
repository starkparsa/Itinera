import type { Metadata, Viewport } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Itinera",
  description: "Chat-driven AI travel planner",
  // No explicit `icons` block -- favicon.ico/icon.png/apple-icon.png in this
  // same app/ directory already cover that via Next's file-based metadata
  // convention; redeclaring it here would just point back to the
  // unoptimized full-size logo-mark.png instead.
  openGraph: {
    title: "Itinera",
    description: "Chat-driven AI travel planner",
    type: "website",
  },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#ffffff" },
    { media: "(prefers-color-scheme: dark)", color: "#171717" },
  ],
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${geistSans.variable} ${geistMono.variable}`}>
      <body>
        {/* Keyboard-only skip link -- invisible until focused, then jumps
            straight past the sidebar toggle/header to #main-content
            (ChatApp's <main>) so a keyboard/screen-reader user doesn't have
            to tab through the header on every page load. */}
        <a
          href="#main-content"
          className="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-50 focus:rounded-md focus:bg-primary focus:px-3 focus:py-2 focus:text-sm focus:text-primary-foreground"
        >
          Skip to main content
        </a>
        {children}
      </body>
    </html>
  );
}
