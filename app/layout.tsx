import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "NARMA VISION — разбор Dota 2 матча 8963624400",
  description: "Интерактивный доказательный разбор матча Dota 2 по четырём стадиям игры.",
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
      <body className="antialiased">{children}</body>
    </html>
  );
}
