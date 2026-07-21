# Dataset fixtures

`combed_sample.csv` is a small, hand-generated sample in COMBED's
documented long-format column shape (`meter_id, timestamp, kwh,
circuit_type`) — **not** a redistribution of the actual COMBED dataset.
It exists to exercise `pipelines/dataset_ingestion/` end-to-end in tests
without requiring network access to fetch the real public dataset.

To ingest the real COMBED or Building Data Genome 2 / ASHRAE dataset:

1. Download the dataset from its public source (COMBED: combed.github.io;
   BDG2: github.com/buds-lab/building-data-genome-project-2).
2. Run `scripts/training/ingest_public_dataset.py` pointed at the
   downloaded CSV(s) — see that script's `--help` for the `--source`
   values (`combed` or `bdg2`) and required tenant/building IDs.
