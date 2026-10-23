# Fragrance Recommender frontend

Next.js App Router and React client components for the guest collection builder
and recommendation carousels. See the root README for project setup and data.

Start FastAPI with `make backend` from the repository root, then run:

```sh
npm run dev
```

Open http://127.0.0.1:3000. Search for five fragrances or load the example,
then choose **Discover my matches**. Your collection is saved in this browser.
Account UI is not implemented yet.

Guest requests pass through the local `/api` handlers. Upstream defaults to
`http://127.0.0.1:8001`; optionally set `FRAGRANCE_API_URL` in `.env.local` here.
Never put the root backend `.env`, Google secrets or SerpApi key in this folder.

```sh
npm run lint
npm run build
```

The production build uses webpack. Fonts use system families without downloads.
