import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "BC Lead Intelligence",
  description: "Auditoria inteligente e governança do ciclo de vida de leads.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="pt-BR">
      <body>{children}</body>
    </html>
  );
}
