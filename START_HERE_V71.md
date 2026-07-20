# Start here — Durably Sustainability Scan v71

This release corrects external-source false negatives observed in the live SHEIN scan.

1. Deploy the complete v71 package with the existing `render.yaml`.
2. Keep the existing Tavily and/or Google Custom Search credentials configured.
3. Confirm that `/api/health` returns release `v71` and version `hostable_v71_external_signal_recall_precision`.
4. Run a new SHEIN scan. The external section should retain qualifying independent regulator, NGO or media sources when returned by the configured provider.
5. Confirm that SHEIN-owned pages and modern-slavery statements remain excluded.
6. Run one additional company scan to confirm that the generic discovery path works outside the SHEIN example.

External sources remain automated review signals and require human verification.
