-- Vendor-side convenience views named like the Caris ones (tmb, msi, loh).
CREATE OR REPLACE VIEW fmi.tmb AS
SELECT report_id, status AS call, score AS score_per_mb, unit FROM fmi.biomarker WHERE name = 'tumor-mutation-burden';
CREATE OR REPLACE VIEW fmi.msi AS
SELECT report_id, status AS call FROM fmi.biomarker WHERE name = 'microsatellite-instability';
CREATE OR REPLACE VIEW fmi.loh AS
SELECT report_id, status AS call, score AS loh_pct FROM fmi.biomarker WHERE name = 'loss-of-heterozygosity';
