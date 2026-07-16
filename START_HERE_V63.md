# Start here — V63 external public-source signals

Deploy the complete repository, not only `app.py`.

The important changes are in:

- `app.py` — external query, classification, ownership and diagnostics logic;
- `frontend.html` — visible search diagnostics;
- `test_v63_external_signals.py` — offline regression tests.

After deployment, check `/api/health` for:

`hostable_v63_external_signal_recall_diagnostics`

Then run a completely new website scan. Check the diagnostics under **External public-source signals**. They show whether the provider returned results and at which filtering stage results were removed.
