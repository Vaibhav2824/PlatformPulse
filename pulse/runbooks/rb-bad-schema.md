# Input schema mismatch / unresolved column
Symptoms: `AnalysisException`, `[UNRESOLVED_COLUMN.WITH_SUGGESTION]`, `cannot resolve column`, missing or renamed fields in the input file.
Diagnosis: compare the header of the input file with the columns the job expects (`event_id,user_id,event_type`). Upstream producer probably renamed columns.
Fix: contact the upstream owner; add a column mapping or enforce an explicit schema with `mode=FAILFAST`; quarantine the bad file and re-run.
Prevention: schema contract checks at ingest; alert on first failure.
