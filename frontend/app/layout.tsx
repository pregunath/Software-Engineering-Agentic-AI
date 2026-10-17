import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Forge | Local AI Software Engineer",
  description: "A local-first workspace for investigating and fixing software issues.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
