export default function Home() {
  return (
    <main className="mx-auto flex min-h-screen max-w-3xl flex-col justify-center gap-4 px-4">
      <h1 className="text-3xl font-semibold tracking-tight">Fragrance Recommender</h1>
      <p className="text-zinc-600 dark:text-zinc-400">
        Add at least 5 fragrances you own and get personalized recommendations.
      </p>
    </main>
  );
}
