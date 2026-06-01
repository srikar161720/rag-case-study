import type { Metadata } from "next";

import "./globals.css";

export const metadata: Metadata = {
  title: "Customs Analytics Agent",
  description:
    "Conversational Q&A over U.S. customs entry data, grounded in domain knowledge.",
  // Demo URL — keep it out of search indexes. Favicon + OG image (G22) land on
  // a later branch with user-provided assets.
  robots: { index: false, follow: false },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
