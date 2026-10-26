# Fragrance Recommender

A full-stack web app that recommends fragrances based on a user's collection. Add at least five fragrances to explore personalized recommendations drawn from a catalog of **140,000+ perfumes**, with images, scent profiles, community ratings, and matched Amazon offers when available.

**[Try the live app](https://fragrance-web-887969780478.us-central1.run.app)** — browse as a guest or sign in with Google to save your collection. The first request after inactivity may take around 40 seconds while the API starts.

## Features

- Ten recommendation categories, including For You, seasonal picks, Budget, Hidden Gems, and Something Different.
- Custom filters for notes, accords, gender, seasons, ratings, longevity, and price.
- Saved collections, personal ratings, wishlists, and clone exclusions.
- Content-based recommendations using TF-IDF, cosine similarity, taste clustering, and Bayesian ratings.

## Tech Stack

- **Next.js, React & TypeScript:** Build the collection editor, fragrance search, detail views, account controls, and filtering interface. Next.js server routes proxy requests to FastAPI, keeping account requests on the website's origin. TypeScript defines shared frontend data structures for fragrance cards, collections, and recommendation responses.
- **Tailwind CSS, custom CSS & Embla Carousel:** Provide responsive styling and horizontally scrolling recommendation rows with touch, keyboard, and arrow navigation.
- **Python & FastAPI:** Power catalog search, fragrance details, recommendation categories, filtering, and account endpoints. Request validation checks collection size and filter inputs before running the recommendation engine.
- **pandas, NumPy & SciPy:** Clean and transform the fragrance dataset, calculate rating and popularity scores, and represent fragrance features as sparse matrices for efficient similarity calculations.
- **scikit-learn:** Supports feature normalization and K-means taste clustering. TF-IDF note weights and cosine-based comparisons match candidates to a user's collection, while Bayesian ratings balance community scores against vote counts.
- **RapidFuzz:** Handles fuzzy catalog search and helps match retail listings to fragrance names, accommodating differences in spelling and product titles.
- **Neon PostgreSQL, SQLAlchemy & Alembic:** Persist users, collections, personal ratings, saved filters, and cached product offers. SQLAlchemy manages database access, and Alembic applies explicit, versioned schema migrations.
- **FastAPI Users & Google OAuth:** Manage account authentication and Google sign-in. Database-backed sessions use secure, HTTP-only cookies, with CSRF and origin checks protecting account changes. Guests can explore before signing in to save their collection.
- **SerpApi:** Retrieves retail search results that are matched to Amazon products by fragrance identity, concentration, and bottle size. Cached offers supply prices and purchase links without requiring a new search for every recommendation; automatic searches are currently disabled to conserve credits.
- **Docker & Google Cloud Run:** Package the frontend and backend as separate containers and host them over HTTPS. Services scale to zero when idle, while a separate Cloud Run job handles database migrations.
- **Cloud Build, Artifact Registry & Secret Manager:** Build container images, store versioned releases, and supply database and authentication secrets to the backend without committing credentials to Git.
- **Cloud Monitoring & billing alerts:** Check website uptime, notify on sustained outages or elevated server errors, and flag project spending against a monthly budget. Budget alerts do not impose a spending cap.

## Data & Documentation

Dataset: [Fragrantica Perfumes](https://www.kaggle.com/datasets/ledecanteur/fragrantica-perfumes) by Le Decanteur, licensed under [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/).

See the [GCP runbook](deployment/GCP.md) for hosting details.
