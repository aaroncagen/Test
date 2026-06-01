import os
from pathlib import Path
from flask import Flask, render_template, request, send_from_directory
from dotenv import load_dotenv
from gtm_engine import analyze, batch_analyze, REPORTS

load_dotenv()
app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = Path(__file__).parent / 'uploads'
app.config['UPLOAD_FOLDER'].mkdir(exist_ok=True)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/analyze', methods=['POST'])
def analyze_route():
    url = request.form.get('url', '').strip()
    if not url:
        return render_template('index.html', error='Enter a company website URL.')
    report = analyze(url)
    return render_template('result.html', report=report)

@app.route('/batch', methods=['POST'])
def batch_route():
    file = request.files.get('csv')
    if not file or file.filename == '':
        return render_template('index.html', error='Upload a CSV file.')
    path = app.config['UPLOAD_FOLDER'] / file.filename
    file.save(path)
    reports = batch_analyze(path)
    return render_template('batch.html', reports=reports)

@app.route('/reports/<path:filename>')
def reports(filename):
    return send_from_directory(REPORTS, filename)

if __name__ == '__main__':
    port = int(os.getenv('PORT', '5050'))
    app.run(host='0.0.0.0', port=port, debug=True)
