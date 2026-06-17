Durably Green & Social Claims Scan - v45 replacement package

This version fixes the v44 scan failure:
"cannot access local variable 'green_fs' where it is not associated with a value".

What changed in v45:
- Claim detection now runs before source assignment.
- Website scans again run external public-source signal searches.
- Both agent.py and app.py are included with the same v45 code, so Render will use the updated backend regardless of whether the start command is python agent.py or python app.py.

Files to replace in your GitHub/Render project:
1. agent.py
2. app.py
3. frontend.html
4. methodology.pdf

After replacing, commit and push to GitHub, then wait for Render to redeploy.
Check:
https://social-washing-scan-python.onrender.com/api/health

Expected version:
hostable_v45_fix_green_fs_external_signals
