from http.server import BaseHTTPRequestHandler
import json
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from db import load_data

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        data = load_data()
        t_tot = data.get("target_total", 0)
        t_nw = data.get("target_non_wasfaty", 0)
        days_recorded = len(data.get("history", {}))

        html = f"""<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
  <meta charset="utf-8">
  <title>بوت مبيعات صيدلية زهرة الروضة 103</title>
  <style>
    body {{ font-family: system-ui, -apple-system, sans-serif; background: #0f172a; color: #f8fafc; text-align: center; padding: 40px 20px; }}
    .card {{ background: #1e293b; max-width: 500px; margin: 0 auto; padding: 30px; border-radius: 16px; box-shadow: 0 10px 25px rgba(0,0,0,0.3); border: 1px solid #334155; }}
    h1 {{ color: #38bdf8; margin-bottom: 8px; font-size: 22px; }}
    .badge {{ display: inline-block; background: #059669; color: white; padding: 6px 14px; border-radius: 20px; font-weight: bold; font-size: 13px; margin: 15px 0; }}
    .stats {{ background: #0f172a; padding: 15px; border-radius: 10px; margin: 20px 0; text-align: right; font-size: 14px; }}
    .stats p {{ margin: 8px 0; }}
    a.btn {{ display: inline-block; background: #0284c7; color: white; padding: 10px 20px; border-radius: 8px; text-decoration: none; font-weight: bold; }}
  </style>
</head>
<body>
  <div class="card">
    <h1>💊 صيدلية زهرة الروضة 103</h1>
    <p>نظام تقارير المبيعات السحابي الآلي (Vercel Serverless)</p>
    <div class="badge">🟢 البوت نشط ويعمل 24/7</div>
    <div class="stats">
      <p>🎯 <b>تارجت التوتال:</b> {t_tot:,.2f} SAR</p>
      <p>💊 <b>تارجت غير وصفتي:</b> {t_nw:,.2f} SAR</p>
      <p>📅 <b>الأيام المسجلة:</b> {days_recorded} يوم</p>
    </div>
    <a class="btn" href="https://t.me/MyPharmaSalesBot" target="_blank">📲 فتح البوت في تليجرام (@MyPharmaSalesBot)</a>
  </div>
</body>
</html>"""
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write(html.encode('utf-8'))
