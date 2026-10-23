export type Perfume = {
  id: number;
  name: string;
  brand: string;
  year?: number | null;
  image_url?: string | null;
};
export type WeightedTerm = { name: string; weight: number };
export type Offer = {
  price: number;
  size_ml: number;
  url: string;
  fetched_at: string;
  store: string;
};
export type Recommendation = Perfume & {
  gender?: string;
  rating_avg?: number | null;
  vote_count?: number | null;
  accords?: WeightedTerm[];
  longevity_avg?: number | null;
  because_of: number;
  shared_accords: string[];
  shared_notes: string[];
  best_offer: Offer | null;
};
export type RecommendationRow = {
  key: string;
  title: string;
  items: Recommendation[];
};
export type PerfumeDetail = Recommendation & {
  notes_top?: WeightedTerm[];
  notes_middle?: WeightedTerm[];
  notes_base?: WeightedTerm[];
  season_share_winter?: number;
  season_share_spring?: number;
  season_share_summer?: number;
  season_share_autumn?: number;
};
