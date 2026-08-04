from flask import Flask, request, jsonify, send_from_directory
import pdfplumber
import pandas as pd
import re
import json
import os
from datetime import datetime, date
from io import StringIO
import sqlite3

app = Flask(__name__, static_folder='static')
DB_PATH = os.path.join(os.path.dirname(__file__), 'data', 'financas.db')

# ── Database ──────────────────────────────────────────────────────────────────

def get_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS movimentos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            data_lanc TEXT,
            data_valor TEXT,
            descritivo TEXT,
            debito REAL,
            credito REAL,
            saldo REAL,
            categoria TEXT DEFAULT 'Sem categoria',
            fonte TEXT
        );
        CREATE TABLE IF NOT EXISTS categorias (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT UNIQUE NOT NULL,
            cor TEXT DEFAULT '#6366f1',
            icone TEXT DEFAULT '💳',
            palavras_chave TEXT DEFAULT '[]'
        );
        INSERT OR IGNORE INTO categorias (nome, cor, icone, palavras_chave) VALUES
            ('Alimentação',     '#f59e0b', '🛒', '["continente","pingo doce","lidl","aldi","mercadona","minipreço","supermercado","padaria","talho","peixaria","intermarche","jumbo"]'),
            ('Restauração',     '#ef4444', '🍽️', '["mcdonald","burger","kfc","nandos","pizza","restaurante","cafe","cervejaria","tasca","snack","sushi","uber eats","glovo","bolt food"]'),
            ('Transportes',     '#3b82f6', '🚗', '["galp","bp","repsol","cepsa","shell","combustivel","portagem","via verde","cp comboios","metro","carris","uber","bolt","renault","volkswagen","peugeot"]'),
            ('Saúde',           '#10b981', '💊', '["farmacia","clinica","hospital","centro saude","dentista","medico","wellbe","dr consultas","multicare","medis"]'),
            ('Lazer',           '#8b5cf6', '🎭', '["cinema","teatro","netflix","spotify","youtube","nba","tidal","apple","google play","steam","playstation","xbox","fnac","worten"]'),
            ('Casa',            '#f97316', '🏠', '["edp","endesa","galp gas","aguas","epal","nos ","meo ","vodafone","nowo","condominio","imobiliaria","renda","arrendamento"]'),
            ('Vestuário',       '#ec4899', '👗', '["zara","hm","pull","springfield","mango","primark","cortefiel","sport zone","decathlon","intersport"]'),
            ('Seguros',         '#64748b', '🛡️', '["fidelidade","ok teleseguros","tranquilidade","allianz","generali","axa","zurich","lusitania","seguro"]'),
            ('Telecomunicações','#0ea5e9', '📱', '["nos ","meo ","vodafone","nowo","nphone","lycamobile"]'),
            ('Educação',        '#84cc16', '📚', '["escola","colegio","universidade","wook","bertrand","livraria","udemy","coursera"]'),
            ('Finanças',        '#6366f1', '🏦', '["prestacao","credito","emprestimo","financiamento","seguro vida","mbway","transferencia","comissao","anuidade"]'),
            ('Sem categoria',   '#94a3b8', '❓', '[]');
        """)
    print("DB iniciada.")

# ── PDF Parsing ───────────────────────────────────────────────────────────────

def parse_valor(s):
    """Converte string portuguesa para float. '1.234,56' → 1234.56"""
    if not s or str(s).strip() == '':
        return None
    s = str(s).strip().replace(' ', '')
    # Remove pontos de milhar, substitui vírgula decimal
    s = s.replace('.', '').replace(',', '.')
    try:
        return float(s)
    except Exception:
        return None

def parse_data(s):
    """Tenta vários formatos de data."""
    if not s:
        return None
    s = str(s).strip()
    for fmt in ('%d-%m-%Y', '%d/%m/%Y', '%Y-%m-%d', '%d.%m.%Y'):
        try:
            return datetime.strptime(s, fmt).strftime('%Y-%m-%d')
        except Exception:
            continue
    return s

def categorizar(descritivo, categorias):
    desc_lower = (descritivo or '').lower()
    for cat in categorias:
        if cat['nome'] == 'Sem categoria':
            continue
        palavras = json.loads(cat['palavras_chave'] or '[]')
        for p in palavras:
            if p.lower() in desc_lower:
                return cat['nome']
    return 'Sem categoria'

def parse_pdf(filepath):
    """
    Tenta extrair movimentos de PDFs bancários com colunas:
    DATA LANC | DATA VALOR | DESCRITIVO | DEBITO | CREDITO | SALDO
    """
    rows = []
    with pdfplumber.open(filepath) as pdf:
        for page in pdf.pages:
            # Tenta extração de tabelas primeiro
            tables = page.extract_tables()
            for table in tables:
                for row in table:
                    if row and len(row) >= 5:
                        rows.append(row)
            # Se não encontrou tabelas, tenta texto com layout
            if not tables:
                text = page.extract_text(layout=True) or ''
                for line in text.splitlines():
                    cols = re.split(r'\s{2,}', line.strip())
                    if cols and len(cols) >= 5:
                        rows.append(cols)

    movimentos = []
    for row in rows:
        # Normaliza para lista de strings
        row = [str(c).strip() if c else '' for c in row]
        # Ignora cabeçalhos
        if any(h in ' '.join(row).upper() for h in ['DATA LANC', 'DESCRITIVO', 'DÉBITO', 'CRÉDITO', 'DATA VALOR']):
            continue
        # Ignora linhas vazias ou com menos de 4 colunas com conteúdo
        filled = [c for c in row if c]
        if len(filled) < 4:
            continue
        # Tenta mapear colunas
        try:
            # Formato: DATA_LANC DATA_VALOR DESCRITIVO DEBITO CREDITO SALDO
            if len(row) >= 6:
                data_lanc  = parse_data(row[0])
                data_valor = parse_data(row[1])
                descritivo = row[2]
                debito     = parse_valor(row[3])
                credito    = parse_valor(row[4])
                saldo      = parse_valor(row[5]) if len(row) > 5 else None
            elif len(row) == 5:
                data_lanc  = parse_data(row[0])
                data_valor = parse_data(row[0])
                descritivo = row[1]
                debito     = parse_valor(row[2])
                credito    = parse_valor(row[3])
                saldo      = parse_valor(row[4])
            else:
                continue

            if not data_lanc or not descritivo:
                continue

            movimentos.append({
                'data_lanc':  data_lanc,
                'data_valor': data_valor or data_lanc,
                'descritivo': descritivo,
                'debito':     debito,
                'credito':    credito,
                'saldo':      saldo,
            })
        except Exception:
            continue

    return movimentos

# ── Período 20→19 ─────────────────────────────────────────────────────────────

def get_periodo(data_str):
    """
    Retorna o label do período mensal 20→19.
    Ex: 2024-01-25 → '2024-02' (vai para Fev, pois está entre 20Jan e 19Fev)
    """
    try:
        d = datetime.strptime(data_str, '%Y-%m-%d')
    except Exception:
        return 'Desconhecido'
    if d.day >= 20:
        # Pertence ao período que termina no mês seguinte
        mes = d.month + 1
        ano = d.year
        if mes > 12:
            mes = 1
            ano += 1
    else:
        mes = d.month
        ano = d.year
    return f'{ano}-{mes:02d}'

def periodo_label(periodo_str):
    """'2024-02' → 'Fevereiro 2024'"""
    meses = ['Janeiro','Fevereiro','Março','Abril','Maio','Junho',
             'Julho','Agosto','Setembro','Outubro','Novembro','Dezembro']
    try:
        ano, mes = periodo_str.split('-')
        return f"{meses[int(mes)-1]} {ano}"
    except Exception:
        return periodo_str

# ── Routes ────────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return send_from_directory('static', 'index.html')

@app.route('/api/upload', methods=['POST'])
def upload():
    if 'pdf' not in request.files:
        return jsonify({'error': 'Nenhum ficheiro enviado'}), 400
    file = request.files['pdf']
    if not file.filename.lower().endswith('.pdf'):
        return jsonify({'error': 'Ficheiro deve ser PDF'}), 400

    tmp = f'/tmp/upload_{file.filename}'
    file.save(tmp)

    try:
        movimentos = parse_pdf(tmp)
    except Exception as e:
        return jsonify({'error': f'Erro a ler PDF: {str(e)}'}), 500
    finally:
        os.remove(tmp)

    if not movimentos:
        return jsonify({'error': 'Não foi possível extrair movimentos do PDF. Verifica se o formato é suportado.'}), 422

    with get_db() as conn:
        cats = [dict(r) for r in conn.execute('SELECT * FROM categorias').fetchall()]
        inseridos = 0
        ignorados = 0
        for m in movimentos:
            m['categoria'] = categorizar(m['descritivo'], cats)
            m['fonte'] = file.filename
            # Evita duplicados exatos
            existe = conn.execute(
                'SELECT id FROM movimentos WHERE data_lanc=? AND descritivo=? AND debito IS ? AND credito IS ?',
                (m['data_lanc'], m['descritivo'], m['debito'], m['credito'])
            ).fetchone()
            if existe:
                ignorados += 1
                continue
            conn.execute(
                'INSERT INTO movimentos (data_lanc,data_valor,descritivo,debito,credito,saldo,categoria,fonte) VALUES (?,?,?,?,?,?,?,?)',
                (m['data_lanc'],m['data_valor'],m['descritivo'],m['debito'],m['credito'],m['saldo'],m['categoria'],m['fonte'])
            )
            inseridos += 1

    return jsonify({'inseridos': inseridos, 'ignorados': ignorados, 'total': len(movimentos)})

@app.route('/api/movimentos')
def get_movimentos():
    periodo = request.args.get('periodo')
    categoria = request.args.get('categoria')
    with get_db() as conn:
        query = 'SELECT * FROM movimentos WHERE 1=1'
        params = []
        if categoria:
            query += ' AND categoria=?'
            params.append(categoria)
        rows = [dict(r) for r in conn.execute(query + ' ORDER BY data_lanc DESC', params).fetchall()]

    # Adiciona label de período
    for r in rows:
        r['periodo'] = get_periodo(r['data_lanc'])
        r['periodo_label'] = periodo_label(r['periodo'])

    if periodo:
        rows = [r for r in rows if r['periodo'] == periodo]

    return jsonify(rows)

@app.route('/api/resumo')
def get_resumo():
    with get_db() as conn:
        rows = [dict(r) for r in conn.execute('SELECT * FROM movimentos ORDER BY data_lanc').fetchall()]

    # Agrupa por período e categoria
    periodos = {}
    for r in rows:
        p = get_periodo(r['data_lanc'])
        cat = r['categoria'] or 'Sem categoria'
        if p not in periodos:
            periodos[p] = {'periodo': p, 'label': periodo_label(p), 'categorias': {}, 'total_debito': 0, 'total_credito': 0}
        if cat not in periodos[p]['categorias']:
            periodos[p]['categorias'][cat] = {'total': 0, 'count': 0}
        val = r['debito'] or 0
        periodos[p]['categorias'][cat]['total'] += val
        periodos[p]['categorias'][cat]['count'] += 1
        periodos[p]['total_debito'] += r['debito'] or 0
        periodos[p]['total_credito'] += r['credito'] or 0

    # Converte para lista ordenada
    result = sorted(periodos.values(), key=lambda x: x['periodo'], reverse=True)
    for r in result:
        r['categorias'] = [{'nome': k, **v} for k, v in r['categorias'].items()]
        r['categorias'].sort(key=lambda x: x['total'], reverse=True)
    return jsonify(result)

@app.route('/api/categorias')
def get_categorias():
    with get_db() as conn:
        rows = [dict(r) for r in conn.execute('SELECT * FROM categorias ORDER BY nome').fetchall()]
    return jsonify(rows)

@app.route('/api/categorias', methods=['POST'])
def add_categoria():
    data = request.json
    with get_db() as conn:
        conn.execute(
            'INSERT INTO categorias (nome, cor, icone, palavras_chave) VALUES (?,?,?,?)',
            (data['nome'], data.get('cor','#6366f1'), data.get('icone','💳'), json.dumps(data.get('palavras_chave',[])))
        )
    return jsonify({'ok': True})

@app.route('/api/categorias/<int:id>', methods=['PUT'])
def update_categoria(id):
    data = request.json
    with get_db() as conn:
        conn.execute(
            'UPDATE categorias SET nome=?, cor=?, icone=?, palavras_chave=? WHERE id=?',
            (data['nome'], data.get('cor','#6366f1'), data.get('icone','💳'), json.dumps(data.get('palavras_chave',[])), id)
        )
        # Re-categorizar movimentos
        cats = [dict(r) for r in conn.execute('SELECT * FROM categorias').fetchall()]
        movs = [dict(r) for r in conn.execute('SELECT id, descritivo FROM movimentos WHERE categoria=?', (data['nome'],)).fetchall()]
        for m in movs:
            nova_cat = categorizar(m['descritivo'], cats)
            conn.execute('UPDATE movimentos SET categoria=? WHERE id=?', (nova_cat, m['id']))
    return jsonify({'ok': True})

@app.route('/api/movimentos/<int:id>/categoria', methods=['PUT'])
def update_movimento_categoria(id):
    data = request.json
    with get_db() as conn:
        conn.execute('UPDATE movimentos SET categoria=? WHERE id=?', (data['categoria'], id))
    return jsonify({'ok': True})

@app.route('/api/movimentos/<int:id>', methods=['DELETE'])
def delete_movimento(id):
    with get_db() as conn:
        conn.execute('DELETE FROM movimentos WHERE id=?', (id,))
    return jsonify({'ok': True})

@app.route('/api/recategorizar', methods=['POST'])
def recategorizar():
    with get_db() as conn:
        cats = [dict(r) for r in conn.execute('SELECT * FROM categorias').fetchall()]
        movs = [dict(r) for r in conn.execute('SELECT id, descritivo FROM movimentos').fetchall()]
        for m in movs:
            cat = categorizar(m['descritivo'], cats)
            conn.execute('UPDATE movimentos SET categoria=? WHERE id=?', (cat, m['id']))
    return jsonify({'ok': True, 'total': len(movs)})

@app.route('/api/periodos')
def get_periodos():
    with get_db() as conn:
        rows = [dict(r) for r in conn.execute('SELECT DISTINCT data_lanc FROM movimentos').fetchall()]
    periodos = sorted(set(get_periodo(r['data_lanc']) for r in rows), reverse=True)
    return jsonify([{'periodo': p, 'label': periodo_label(p)} for p in periodos])

if __name__ == '__main__':
    init_db()
    debug = os.environ.get('FLASK_ENV') != 'production'
    print("\n🏦 Finanças Pessoais — http://0.0.0.0:5000\n")
    app.run(host='0.0.0.0', port=5000, debug=debug)
