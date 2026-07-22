# Dataset fixtures

`bdg2_sample.csv` is a **real** slice of the public Building Data Genome
Project 2 (BDG2) dataset (github.com/buds-lab/building-data-genome-project-2,
`data/meters/cleaned/electricity_cleaned.csv`), pivoted from BDG2's native
wide format (one column per building) into the long format
`services/ingestion/normalization.py` expects (`meter_id, timestamp, kwh,
circuit_type`).

Provenance:

- Source file: `data/meters/cleaned/electricity_cleaned.csv` (real hourly
  electricity readings, MIT-licensed public dataset).
- Buildings selected: `Robin_office_Dina`, `Robin_lodging_Dorthy`,
  `Robin_education_Zenia` — three real BDG2 buildings on the `Robin` site
  (see `data/metadata/metadata.csv` in the upstream repo for full building
  metadata), chosen for 100% real data completeness across the sliced
  window and variety of `primaryspaceusage` (office / lodging / education).
- Time range: 2016-01-01 00:00 through 2016-04-29 09:00 (real, continuous,
  ~119 days of real hourly readings per building, no synthetic or
  interpolated values — every row is an unmodified real BDG2 reading).
- 8,598 total rows (2,866 real hourly readings x 3 buildings).

This is genuinely real BDG2 data, not a hand-generated approximation of its
shape — it exists as a fixture (rather than fetching the dataset live in
CI) so `pipelines/dataset_ingestion/` and the full training pipeline can be
exercised deterministically and offline.

To ingest the complete BDG2 dataset (all ~1,600 buildings, all meter types,
full 2-year span) instead of this slice:

1. Download from github.com/buds-lab/building-data-genome-project-2
   (`data/meters/cleaned/*.csv`, Git-LFS tracked) or the ASHRAE Great
   Energy Predictor III Kaggle competition as a fallback source.
2. Run `scripts/training/ingest_public_dataset.py` pointed at the
   downloaded CSV(s) — see that script's `--help` for the `--source`
   values (`combed` or `bdg2`) and required tenant/building IDs. A file in
   BDG2's native wide format must be pivoted to the long format above
   first (one row per meter/timestamp/reading) — see
   `scripts/training/prepare_bdg2_fixture.py` for the exact pivot this
   fixture itself was generated with.
