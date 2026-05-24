# Contamination Image Database

Passively collected contamination images from mushroom growing subreddits.
Built by automated cron jobs — the agent catalogs and labels each entry.

## Structure
- `images/` — downloaded contamination photos (named by date + source)
- `index.md` — master catalog: filename, source URL, title, suspected contam type, date

## Sources
Primary: r/contamfam, r/mushroomgrowing, r/unclebens, r/MushroomGrowers, r/mycology

## Labeling
Labels come from Reddit post titles and flair.
The agent cross-references with `knowledge/contamination-signatures.md`

## Future
This dataset feeds a custom contamination detection model (Phase 2+).
