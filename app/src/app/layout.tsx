import type { Metadata, Viewport } from "next";
import "./globals.css";
import { Footer, Header } from "@/components/Chrome";
import { I18nProvider } from "@/components/I18n";
import { getIndex } from "@/lib/data";

export const metadata: Metadata = {
  title: { default: "Quai libre — affluence des gares de métro et RER", template: "%s · Quai libre" },
  description:
    "Quand prendre le métro ou le RER en Île-de-France pour éviter la foule : affluence heure par heure, d’après les données ouvertes de validation.",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#0b2545" },
    { media: "(prefers-color-scheme: dark)", color: "#0b1626" },
  ],
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  const index = getIndex();
  return (
    <html lang="fr">
      <body>
        <I18nProvider>
          <Header />
          <main className="wrap">{children}</main>
          <Footer attribution={index.attribution} period={index.data_period} />
        </I18nProvider>
      </body>
    </html>
  );
}
