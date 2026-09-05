import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: {
    default: "NARMA VISION — разбор матчей Dota 2",
    template: "%s | NARMA VISION",
  },
  description: "Разбор матча Dota 2 по событиям, экономике, карте и replay-данным.",
  other: {
    "codex-preview": "development",
  },
  icons: {
    icon: "/favicon.svg",
    shortcut: "/favicon.svg",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="ru">
      <body className="antialiased">
        <a className="skip-link" href="#main-content">Перейти к основному содержимому</a>
        {children}
      </body>
    </html>
  );
}
