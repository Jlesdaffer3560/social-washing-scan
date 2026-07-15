# Add this to the existing Flask application after `app = Flask(...)`.

from flask import session
from company_report_v2 import register_company_report_v2

register_company_report_v2(
    app,
    report_provider=lambda: session.get("last_scan_result"),
)

# Existing HTML button:
# <button type="button"
#         onclick="window.open('/company-report-v2?print=1', '_blank')">
#   Download / save 2-page company report as PDF
# </button>
