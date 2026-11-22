import type { Metadata, Viewport } from "next";
import "./globals.css";
import { I18nProvider } from "@/components/I18n";
import { RegisterSW } from "@/components/pwa/RegisterSW";
import { CHUNK_RECOVER } from "@/components/pwa/recover";
import { SPLASH_BOOT, Splash } from "@/components/pwa/Splash";

export const metadata: Metadata = {
  title: { default: "à point : l’affluence des gares de métro et de RER", template: "%s · à point" },
  description:
    "L’affluence prévue dans les gares de métro et de RER d’Île-de-France, jour par jour et heure par heure, à partir des données ouvertes de validation. Gratuit, sans compte, sans traceur.",
  applicationName: "à point",
  manifest: "/manifest.webmanifest",
  icons: {
    icon: [{ url: "/brand/favicon.svg", type: "image/svg+xml" }],
    apple: [{ url: "/icons/apple-touch-icon.png", sizes: "180x180" }],
  },
  appleWebApp: { capable: true, title: "à point", statusBarStyle: "default" },
  formatDetection: { telephone: false },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
  themeColor: "#F6F7F4",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="fr">
      <head>
        <script dangerouslySetInnerHTML={{ __html: CHUNK_RECOVER }} />
        <script dangerouslySetInnerHTML={{ __html: SPLASH_BOOT }} />
        <link
          rel="preload"
          href="/fonts/onest-latin-wght-normal.woff2"
          as="font"
          type="font/woff2"
          crossOrigin="anonymous"
        />
      </head>
      <body>
        <I18nProvider>{children}</I18nProvider>
        <RegisterSW />
        <Splash />
      </body>
    </html>
  );
}
