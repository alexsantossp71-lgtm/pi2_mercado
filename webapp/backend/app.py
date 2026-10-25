from flask import Flask, jsonify, request
import subprocess, os, json, pathlib
app = Flask(__name__)

# Helper to run the analysis script and capture output
def run_analysis(item_id: str):
    # The prototype script expects no arguments; we will just call it
    script_path = os.path.join(os.path.dirname(__file__), '..', '..', 'prototipo', 'analise_sazonalidade.py')
    # Ensure script exists
    if not pathlib.Path(script_path).exists():
        return {'error': 'analysis script not found'}
    # Run script (it writes files we can read)
    subprocess.run(['python3', script_path], check=False)
    # Read generated CSV for the requested item (simplified: return whole CSV)
    csv_path = os.path.join(os.path.dirname(__file__), '..', '..', 'prototipo', 'sazonalidade.csv')
    if not pathlib.Path(csv_path).exists():
        return {'error': 'CSV not generated'}
    with open(csv_path, 'r', encoding='utf-8') as f:
        data = f.read()
    return {'csv': data}

@app.route('/api/sazonalidade', methods=['GET'])
def get_sazonalidade():
    item = request.args.get('item')
    if not item:
        return jsonify({'error': 'item query param required'}), 400
    result = run_analysis(item)
    return jsonify(result)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
