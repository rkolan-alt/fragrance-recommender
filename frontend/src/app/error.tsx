"use client";
import Link from "next/link";
export default function Error({
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <main className="account-token">
      <p className="eyebrow">A MOMENT TO REGROUP</p>
      <h1>Something didn’t load.</h1>
      <p>Please try again, or return to your collection.</p>
      <button className="primary-button" onClick={reset}>
        Try again
      </button>
      <Link href="/">Return to your collection</Link>
    </main>
  );
}
