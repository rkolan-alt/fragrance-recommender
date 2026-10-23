import type { Metadata } from "next";
import "./globals.css";
export const metadata: Metadata = {
  title: "Fragrance Recommender — Your next scent",
  description:
    "Discover fragrances through the collection you already love. Personalized recommendations by notes, accords, seasons, and community ratings.",
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
