from flask import Flask, request, jsonify, send_from_directory
import pdfplumber
import re, json, os, sqlite3
from datetime import datetime, timedelta

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
        CREATE TABLE IF NOT EXISTS contas (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            nome    TEXT NOT NULL,
            banco   TEXT NOT NULL,
            numero  TEXT,
            cor     TEXT DEFAULT '#6366f1',
            icone   TEXT DEFAULT '🏦',
            ativa   INTEGER DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS movimentos (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            conta_id        INTEGER REFERENCES contas(id),
            data_lanc       TEXT,
            data_valor      TEXT,
            descritivo      TEXT,
            debito          REAL,
            credito         REAL,
            saldo           REAL,
            categoria       TEXT DEFAULT 'Sem categoria',
            fonte           TEXT,
            transferencia_id INTEGER DEFAULT NULL
        );

        CREATE TABLE IF NOT EXISTS categorias (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            nome           TEXT UNIQUE NOT NULL,
            cor            TEXT DEFAULT '#6366f1',
            icone          TEXT DEFAULT '💳',
            palavras_chave TEXT DEFAULT '[]'
        );

        -- Migração: adiciona conta_id e transferencia_id se não existirem
        CREATE TABLE IF NOT EXISTS _migrations (chave TEXT PRIMARY KEY);
        """)

        # Migração segura — adiciona colunas se não existirem
        cols = {r[1] for r in conn.execute("PRAGMA table_info(movimentos)").fetchall()}
        if 'conta_id' not in cols:
            conn.execute("ALTER TABLE movimentos ADD COLUMN conta_id INTEGER REFERENCES contas(id)")
        if 'transferencia_id' not in cols:
            conn.execute("ALTER TABLE movimentos ADD COLUMN transferencia_id INTEGER DEFAULT NULL")

        conn.executescript("""
        INSERT OR IGNORE INTO categorias (nome, cor, icone, palavras_chave) VALUES
            ('Alimentação',        '#f59e0b','🛒','["continente","pingo doce","lidl","aldi","mercadona","minipreço","supermercado","padaria","talho","peixaria","intermarche","jumbo"]'),
            ('Restauração',        '#ef4444','🍽️','["mcdonald","burger","kfc","nandos","pizza","restaurante","cafe","cervejaria","tasca","snack","sushi","uber eats","glovo","bolt food"]'),
            ('Transportes',        '#3b82f6','🚗','["galp","bp","repsol","cepsa","shell","combustivel","portagem","via verde","cp comboios","metro","carris","uber","bolt","renault","volkswagen","peugeot"]'),
            ('Saúde',              '#10b981','💊','["farmacia","clinica","hospital","centro saude","dentista","medico","wellbe","dr consultas","multicare","medis"]'),
            ('Lazer',              '#8b5cf6','🎭','["cinema","teatro","netflix","spotify","youtube","nba","tidal","apple","google play","steam","playstation","xbox","fnac","worten"]'),
            ('Casa',               '#f97316','🏠','["edp","endesa","galp gas","aguas","epal","nos ","meo ","vodafone","nowo","condominio","imobiliaria","renda","arrendamento"]'),
            ('Vestuário',          '#ec4899','👗','["zara","hm","pull","springfield","mango","primark","cortefiel","sport zone","decathlon","intersport"]'),
            ('Seguros',            '#64748b','🛡️','["fidelidade","ok teleseguros","tranquilidade","allianz","generali","axa","zurich","lusitania","seguro"]'),
            ('Telecomunicações',   '#0ea5e9','📱','["nos ","meo ","vodafone","nowo","nphone","lycamobile"]'),
            ('Educação',           '#84cc16','📚','["escola","colegio","universidade","wook","bertrand","livraria","udemy","coursera"]'),
            ('Finanças',           '#6366f1','🏦','["prestacao","credito","emprestimo","financiamento","seguro vida","mbway","transferencia","comissao","anuidade"]'),
            ('Transferência Interna','#94a3b8','🔄','[]'),
            ('Sem categoria',      '#475569','❓','[]');
        """)
    print("DB iniciada.")

# ── PDF Parsing ───────────────────────────────────────────────────────────────

def parse_valor(s):
    if not s or str(s).strip() == '': return None
    s = str(s).strip().replace(' ', '').replace('.', '').replace(',', '.')
    try: return float(s)
    except: return None

def parse_data(s):
    if not s: return None
    s = str(s).strip()
    for fmt in ('%d-%m-%Y','%d/%m/%Y','%Y-%m-%d','%d.%m.%Y'):
        try: return datetime.strptime(s, fmt).strftime('%Y-%m-%d')
        except: continue
    return s

def categorizar(descritivo, categorias):
    desc_lower = (descritivo or '').lower()
    for cat in categorias:
        if cat['nome'] in ('Sem categoria', 'Transferência Interna'): continue
        for p in json.loads(cat['palavras_chave'] or '[]'):
            if p.lower() in desc_lower: return cat['nome']
    return 'Sem categoria'

def parse_pdf(filepath):
    """Parser principal: tenta ActivoBank via pdftotext, fallback pdfplumber."""
    import subprocess
    result = subprocess.run(['pdftotext','-layout', filepath,'-'], capture_output=True, text=True)
    text = result.stdout
    if text.strip():
        movs = _parse_activobank(text)
        if movs: return movs
    return _parse_pdfplumber(filepath)

def _parse_activobank(text):
    ano_m = re.search(r'EXTRATO DE (\d{4})', text)
    ano   = ano_m.group(1) if ano_m else str(datetime.now().year)

    def fmt_data(s):
        p = s.split('.')
        return f'{ano}-{int(p[0]):02d}-{int(p[1]):02d}' if len(p)==2 else None

    saldo_ant_m = re.search(r'SALDO INICIAL\s+([\d ]+\.\d{2})', text)
    saldo_ant   = float(saldo_ant_m.group(1).replace(' ','')) if saldo_ant_m else None

    SKIP = ['Capital Social','Banco Activo','SALDO INICIAL','SALDO FINAL',
            'SALDO DISPONIVEL','ULTRAPASSAGEM','EXTRATO DE','PAG:','www.',
            'Poderá obter','legislação','MENSAGEM','AGENDA','RESUMO',
            'CONTA SIMPLES','MOEDA BASE','BIC/SWIFT','DEPOSITO A ORDEM',
            'EXT. N.','EXTRATO COMBINADO']

    movimentos = []
    for line in text.splitlines():
        if any(p in line for p in SKIP): continue
        m = re.match(r'\s{80,}(\d{1,2}\.\d{2})\s+(\d{1,2}\.\d{2})\s', line)
        if not m: continue
        data_lanc  = fmt_data(m.group(1))
        data_valor = fmt_data(m.group(2))
        if not data_lanc: continue

        vals_pos = [(vm.start(), float(vm.group().replace(' ','')))
                    for vm in re.finditer(r'(?<!\d)(\d{1,3}(?: \d{3})*\.\d{2})(?!\d)', line)
                    if vm.start() > 160]
        if len(vals_pos) < 2: continue

        saldo = vals_pos[-1][1]
        val_pos, val = vals_pos[-2]
        LIMIAR = 230
        if val_pos >= LIMIAR:
            debito, credito = None, val
        else:
            if saldo_ant is not None:
                diff = round(saldo - saldo_ant, 2)
                if   abs(diff + val) < 0.02: debito, credito = val, None
                elif abs(diff - val) < 0.02: debito, credito = None, val
                else: debito, credito = val, None
            else:
                debito, credito = val, None

        saldo_ant = saldo
        inicio = m.end()
        fim    = vals_pos[-2][0]
        desc   = re.sub(r'\s{2,}',' ', line[inicio:fim]).strip()
        desc   = re.sub(r'\s*CONTACTLESS\s*$','', desc).strip()

        movimentos.append({'data_lanc':data_lanc,'data_valor':data_valor or data_lanc,
                           'descritivo':desc,'debito':debito,'credito':credito,'saldo':saldo})
    return movimentos

def _parse_pdfplumber(filepath):
    rows = []
    with pdfplumber.open(filepath) as pdf:
        for page in pdf.pages:
            tables = page.extract_tables()
            for t in tables:
                for row in t:
                    if row and len(row) >= 5: rows.append(row)
            if not tables:
                text = page.extract_text(layout=True) or ''
                for line in text.splitlines():
                    cols = re.split(r'\s{2,}', line.strip())
                    if cols and len(cols) >= 5: rows.append(cols)
    movimentos = []
    for row in rows:
        row = [str(c).strip() if c else '' for c in row]
        if any(h in ' '.join(row).upper() for h in ['DATA LANC','DESCRITIVO','DÉBITO','CRÉDITO']): continue
        filled = [c for c in row if c]
        if len(filled) < 4: continue
        try:
            if len(row) >= 6:
                dl,dv,desc,deb,cre,sal = parse_data(row[0]),parse_data(row[1]),row[2],parse_valor(row[3]),parse_valor(row[4]),parse_valor(row[5]) if len(row)>5 else None
            elif len(row) == 5:
                dl,dv,desc,deb,cre,sal = parse_data(row[0]),parse_data(row[0]),row[1],parse_valor(row[2]),parse_valor(row[3]),parse_valor(row[4])
            else: continue
            if not dl or not desc: continue
            movimentos.append({'data_lanc':dl,'data_valor':dv or dl,'descritivo':desc,'debito':deb,'credito':cre,'saldo':sal})
        except: continue
    return movimentos

# ── Período 20→19 ─────────────────────────────────────────────────────────────

def get_periodo(data_str):
    try: d = datetime.strptime(data_str, '%Y-%m-%d')
    except: return 'Desconhecido'
    if d.day >= 20:
        mes, ano = d.month+1, d.year
        if mes > 12: mes, ano = 1, ano+1
    else:
        mes, ano = d.month, d.year
    return f'{ano}-{mes:02d}'

def periodo_label(p):
    meses = ['Janeiro','Fevereiro','Março','Abril','Maio','Junho',
             'Julho','Agosto','Setembro','Outubro','Novembro','Dezembro']
    try:
        ano, mes = p.split('-')
        return f"{meses[int(mes)-1]} {ano}"
    except: return p

# ── Transferências internas ───────────────────────────────────────────────────

def detectar_transferencias(conn, conta_id=None, janela_dias=5):
    """
    Deteta pares débito↔crédito entre contas diferentes com mesmo valor
    e datas dentro de uma janela de N dias.
    Marca ambos os movimentos com o mesmo transferencia_id e categoria 'Transferência Interna'.
    """
    # Apaga deteções anteriores (re-run idempotente)
    conn.execute("UPDATE movimentos SET transferencia_id=NULL, categoria=CASE WHEN categoria='Transferência Interna' THEN 'Sem categoria' ELSE categoria END WHERE transferencia_id IS NOT NULL")

    debitos  = [dict(r) for r in conn.execute(
        "SELECT * FROM movimentos WHERE debito IS NOT NULL AND debito > 0 ORDER BY data_lanc").fetchall()]
    creditos = [dict(r) for r in conn.execute(
        "SELECT * FROM movimentos WHERE credito IS NOT NULL AND credito > 0 ORDER BY data_lanc").fetchall()]

    pares = []
    usados_deb  = set()
    usados_cred = set()

    for d in debitos:
        if d['id'] in usados_deb: continue
        for c in creditos:
            if c['id'] in usados_cred: continue
            # Não pode ser da mesma conta
            if d['conta_id'] and c['conta_id'] and d['conta_id'] == c['conta_id']: continue
            # Mesmo valor
            if abs((d['debito'] or 0) - (c['credito'] or 0)) > 0.01: continue
            # Dentro da janela de dias
            try:
                dd = datetime.strptime(d['data_lanc'], '%Y-%m-%d')
                dc = datetime.strptime(c['data_lanc'], '%Y-%m-%d')
                if abs((dd - dc).days) > janela_dias: continue
            except: continue
            pares.append((d['id'], c['id']))
            usados_deb.add(d['id'])
            usados_cred.add(c['id'])
            break

    # Atribui um transferencia_id sequencial a cada par
    for i, (did, cid) in enumerate(pares, start=1):
        tid = i
        conn.execute("UPDATE movimentos SET transferencia_id=?, categoria='Transferência Interna' WHERE id IN (?,?)", (tid, did, cid))

    return len(pares)

# ── Routes — Contas ───────────────────────────────────────────────────────────

@app.route('/')
def index(): return send_from_directory('static', 'index.html')

@app.route('/api/contas')
def get_contas():
    with get_db() as conn:
        contas = [dict(r) for r in conn.execute('SELECT * FROM contas ORDER BY nome').fetchall()]
        for c in contas:
            ult = conn.execute(
                'SELECT saldo FROM movimentos WHERE conta_id=? AND saldo IS NOT NULL ORDER BY data_lanc DESC, id DESC LIMIT 1',
                (c['id'],)).fetchone()
            c['saldo_atual'] = dict(ult)['saldo'] if ult else None
            c['n_movimentos'] = conn.execute('SELECT COUNT(*) FROM movimentos WHERE conta_id=?',(c['id'],)).fetchone()[0]
    return jsonify(contas)

@app.route('/api/contas', methods=['POST'])
def add_conta():
    d = request.json
    with get_db() as conn:
        cur = conn.execute(
            'INSERT INTO contas (nome,banco,numero,cor,icone) VALUES (?,?,?,?,?)',
            (d['nome'], d['banco'], d.get('numero',''), d.get('cor','#6366f1'), d.get('icone','🏦')))
    return jsonify({'ok': True, 'id': cur.lastrowid})

@app.route('/api/contas/<int:id>', methods=['PUT'])
def update_conta(id):
    d = request.json
    with get_db() as conn:
        conn.execute('UPDATE contas SET nome=?,banco=?,numero=?,cor=?,icone=? WHERE id=?',
            (d['nome'],d['banco'],d.get('numero',''),d.get('cor','#6366f1'),d.get('icone','🏦'),id))
    return jsonify({'ok': True})

@app.route('/api/contas/<int:id>', methods=['DELETE'])
def delete_conta(id):
    with get_db() as conn:
        conn.execute('DELETE FROM movimentos WHERE conta_id=?', (id,))
        conn.execute('DELETE FROM contas WHERE id=?', (id,))
    return jsonify({'ok': True})

# ── Routes — Upload ───────────────────────────────────────────────────────────

@app.route('/api/upload/parse', methods=['POST'])
def upload_parse():
    """
    Fase 1: recebe o PDF, extrai movimentos, classifica cada um como:
      - 'novo'      → não existe na DB, será inserido
      - 'duplicado' → já existe na DB (mesmo valor, data, descrição, conta)
    Não insere nada. Devolve tudo para o utilizador rever.
    """
    if 'pdf' not in request.files:
        return jsonify({'error': 'Nenhum ficheiro enviado'}), 400
    file = request.files['pdf']
    conta_id = request.form.get('conta_id')
    if not file.filename.lower().endswith('.pdf'):
        return jsonify({'error': 'Ficheiro deve ser PDF'}), 400
    if not conta_id:
        return jsonify({'error': 'Seleciona uma conta antes de importar'}), 400

    tmp = f'/tmp/upload_{file.filename}'
    file.save(tmp)
    try:
        movimentos = parse_pdf(tmp)
    except Exception as e:
        return jsonify({'error': f'Erro a ler PDF: {str(e)}'}), 500
    finally:
        os.remove(tmp)

    if not movimentos:
        return jsonify({'error': 'Não foi possível extrair movimentos. Verifica o formato do PDF.'}), 422

    with get_db() as conn:
        cats = [dict(r) for r in conn.execute('SELECT * FROM categorias').fetchall()]
        resultado = []
        for i, m in enumerate(movimentos):
            m['categoria'] = categorizar(m['descritivo'], cats)
            existente = conn.execute(
                'SELECT id, data_lanc, descritivo, debito, credito, saldo FROM movimentos '
                'WHERE conta_id=? AND data_lanc=? AND descritivo=? AND debito IS ? AND credito IS ?',
                (conta_id, m['data_lanc'], m['descritivo'], m['debito'], m['credito'])
            ).fetchone()
            resultado.append({
                '_idx':      i,
                '_estado':   'duplicado' if existente else 'novo',
                '_existente': dict(existente) if existente else None,
                'conta_id':  conta_id,
                'fonte':     file.filename,
                **m,
            })

    novos      = sum(1 for r in resultado if r['_estado'] == 'novo')
    duplicados = [r for r in resultado if r['_estado'] == 'duplicado']

    return jsonify({
        'movimentos':  resultado,
        'novos':       novos,
        'duplicados':  len(duplicados),
        'total':       len(resultado),
        'fonte':       file.filename,
        'conta_id':    conta_id,
    })


@app.route('/api/upload/confirmar', methods=['POST'])
def upload_confirmar():
    """
    Fase 2: recebe a lista final de movimentos a inserir (escolhida pelo utilizador).
    Insere todos e corre a deteção de transferências.
    """
    data     = request.json
    movimentos = data.get('movimentos', [])
    conta_id   = data.get('conta_id')
    fonte      = data.get('fonte', '')

    if not movimentos:
        return jsonify({'inseridos': 0, 'transferencias': 0})

    with get_db() as conn:
        cats = [dict(r) for r in conn.execute('SELECT * FROM categorias').fetchall()]
        inseridos = 0
        for m in movimentos:
            # Garante categorização mesmo que venha do front sem ela
            if not m.get('categoria'):
                m['categoria'] = categorizar(m.get('descritivo', ''), cats)
            conn.execute(
                'INSERT INTO movimentos '
                '(conta_id,data_lanc,data_valor,descritivo,debito,credito,saldo,categoria,fonte) '
                'VALUES (?,?,?,?,?,?,?,?,?)',
                (conta_id, m['data_lanc'], m.get('data_valor') or m['data_lanc'],
                 m['descritivo'], m.get('debito'), m.get('credito'),
                 m.get('saldo'), m['categoria'], fonte))
            inseridos += 1
        pares = detectar_transferencias(conn)

    return jsonify({'inseridos': inseridos, 'transferencias': pares})

# ── Routes — Movimentos ───────────────────────────────────────────────────────

@app.route('/api/movimentos')
def get_movimentos():
    periodo      = request.args.get('periodo')
    categoria    = request.args.get('categoria')
    conta_id     = request.args.get('conta_id')
    so_externas  = request.args.get('so_externas','0') == '1'

    with get_db() as conn:
        query  = 'SELECT m.*, c.nome as conta_nome, c.cor as conta_cor, c.icone as conta_icone FROM movimentos m LEFT JOIN contas c ON m.conta_id=c.id WHERE 1=1'
        params = []
        if categoria:
            query += ' AND m.categoria=?'; params.append(categoria)
        if conta_id:
            query += ' AND m.conta_id=?'; params.append(conta_id)
        if so_externas:
            query += ' AND m.transferencia_id IS NULL'
        rows = [dict(r) for r in conn.execute(query+' ORDER BY m.data_lanc DESC, m.id DESC', params).fetchall()]

    for r in rows:
        r['periodo']       = get_periodo(r['data_lanc'])
        r['periodo_label'] = periodo_label(r['periodo'])

    if periodo:
        rows = [r for r in rows if r['periodo'] == periodo]

    return jsonify(rows)

@app.route('/api/movimentos/<int:id>/categoria', methods=['PUT'])
def update_movimento_categoria(id):
    d = request.json
    with get_db() as conn:
        conn.execute('UPDATE movimentos SET categoria=? WHERE id=?', (d['categoria'], id))
    return jsonify({'ok': True})

@app.route('/api/movimentos/<int:id>', methods=['DELETE'])
def delete_movimento(id):
    with get_db() as conn:
        conn.execute('DELETE FROM movimentos WHERE id=?', (id,))
    return jsonify({'ok': True})

# ── Routes — Categorias ───────────────────────────────────────────────────────

@app.route('/api/categorias')
def get_categorias():
    with get_db() as conn:
        rows = [dict(r) for r in conn.execute('SELECT * FROM categorias ORDER BY nome').fetchall()]
    return jsonify(rows)

@app.route('/api/categorias', methods=['POST'])
def add_categoria():
    d = request.json
    with get_db() as conn:
        conn.execute('INSERT INTO categorias (nome,cor,icone,palavras_chave) VALUES (?,?,?,?)',
            (d['nome'], d.get('cor','#6366f1'), d.get('icone','💳'), json.dumps(d.get('palavras_chave',[]))))
    return jsonify({'ok': True})

@app.route('/api/categorias/<int:id>', methods=['PUT'])
def update_categoria(id):
    d = request.json
    with get_db() as conn:
        conn.execute('UPDATE categorias SET nome=?,cor=?,icone=?,palavras_chave=? WHERE id=?',
            (d['nome'],d.get('cor','#6366f1'),d.get('icone','💳'),json.dumps(d.get('palavras_chave',[])),id))
        cats = [dict(r) for r in conn.execute('SELECT * FROM categorias').fetchall()]
        for m in conn.execute('SELECT id,descritivo FROM movimentos WHERE categoria=?',(d['nome'],)).fetchall():
            conn.execute('UPDATE movimentos SET categoria=? WHERE id=?', (categorizar(m['descritivo'], cats), m['id']))
    return jsonify({'ok': True})

@app.route('/api/categorias/<int:id>', methods=['DELETE'])
def delete_categoria(id):
    with get_db() as conn:
        nome = conn.execute('SELECT nome FROM categorias WHERE id=?',(id,)).fetchone()
        if nome:
            conn.execute("UPDATE movimentos SET categoria='Sem categoria' WHERE categoria=?",(nome[0],))
        conn.execute('DELETE FROM categorias WHERE id=?',(id,))
    return jsonify({'ok': True})

@app.route('/api/recategorizar', methods=['POST'])
def recategorizar():
    with get_db() as conn:
        cats = [dict(r) for r in conn.execute('SELECT * FROM categorias').fetchall()]
        movs = [dict(r) for r in conn.execute(
            "SELECT id,descritivo FROM movimentos WHERE categoria != 'Transferência Interna'").fetchall()]
        for m in movs:
            conn.execute('UPDATE movimentos SET categoria=? WHERE id=?', (categorizar(m['descritivo'], cats), m['id']))
    return jsonify({'ok': True, 'total': len(movs)})

# ── Routes — Transferências ───────────────────────────────────────────────────

@app.route('/api/transferencias/detetar', methods=['POST'])
def detetar_transferencias():
    janela = int(request.json.get('janela_dias', 5))
    with get_db() as conn:
        pares = detectar_transferencias(conn, janela_dias=janela)
    return jsonify({'ok': True, 'pares': pares})

@app.route('/api/transferencias')
def get_transferencias():
    """Lista todos os pares de transferências internas detetados."""
    with get_db() as conn:
        rows = [dict(r) for r in conn.execute("""
            SELECT m.*, c.nome as conta_nome, c.cor as conta_cor, c.icone as conta_icone
            FROM movimentos m
            LEFT JOIN contas c ON m.conta_id=c.id
            WHERE m.transferencia_id IS NOT NULL
            ORDER BY m.transferencia_id, m.data_lanc
        """).fetchall()]

    pares = {}
    for r in rows:
        tid = r['transferencia_id']
        pares.setdefault(tid, []).append(r)

    return jsonify(list(pares.values()))

@app.route('/api/movimentos/<int:id>/desligar_transferencia', methods=['POST'])
def desligar_transferencia(id):
    """Remove a ligação de transferência interna de um movimento."""
    with get_db() as conn:
        m = dict(conn.execute('SELECT * FROM movimentos WHERE id=?',(id,)).fetchone())
        tid = m.get('transferencia_id')
        if tid:
            conn.execute("UPDATE movimentos SET transferencia_id=NULL, categoria='Sem categoria' WHERE transferencia_id=?",(tid,))
    return jsonify({'ok': True})

# ── Routes — Resumo / Períodos / Estatísticas ─────────────────────────────────

@app.route('/api/resumo')
def get_resumo():
    conta_id    = request.args.get('conta_id')
    so_externas = request.args.get('so_externas','1') == '1'   # default: exclui internas

    with get_db() as conn:
        q = 'SELECT * FROM movimentos WHERE 1=1'
        p = []
        if conta_id:
            q += ' AND conta_id=?'; p.append(conta_id)
        if so_externas:
            q += ' AND transferencia_id IS NULL'
        rows = [dict(r) for r in conn.execute(q+' ORDER BY data_lanc', p).fetchall()]

    periodos = {}
    for r in rows:
        per = get_periodo(r['data_lanc'])
        cat = r['categoria'] or 'Sem categoria'
        periodos.setdefault(per, {'periodo':per,'label':periodo_label(per),'categorias':{},'total_debito':0,'total_credito':0})
        periodos[per]['categorias'].setdefault(cat, {'total':0,'count':0})
        periodos[per]['categorias'][cat]['total'] += r['debito'] or 0
        periodos[per]['categorias'][cat]['count'] += 1
        periodos[per]['total_debito']  += r['debito']  or 0
        periodos[per]['total_credito'] += r['credito'] or 0

    result = sorted(periodos.values(), key=lambda x: x['periodo'], reverse=True)
    for r in result:
        r['categorias'] = sorted([{'nome':k,**v} for k,v in r['categorias'].items()], key=lambda x: x['total'], reverse=True)
    return jsonify(result)

@app.route('/api/periodos')
def get_periodos():
    with get_db() as conn:
        rows = [dict(r) for r in conn.execute('SELECT DISTINCT data_lanc FROM movimentos').fetchall()]
    periodos = sorted(set(get_periodo(r['data_lanc']) for r in rows), reverse=True)
    return jsonify([{'periodo':p,'label':periodo_label(p)} for p in periodos])

@app.route('/api/estatisticas')
def get_estatisticas():
    filtro_ano  = request.args.get('ano')
    conta_id    = request.args.get('conta_id')
    so_externas = request.args.get('so_externas','1') == '1'

    with get_db() as conn:
        q = 'SELECT * FROM movimentos WHERE 1=1'
        p = []
        if conta_id:
            q += ' AND conta_id=?'; p.append(conta_id)
        if so_externas:
            q += ' AND transferencia_id IS NULL'
        rows = [dict(r) for r in conn.execute(q+' ORDER BY data_lanc', p).fetchall()]

    for r in rows:
        r['periodo']       = get_periodo(r['data_lanc'])
        r['periodo_label'] = periodo_label(r['periodo'])
        r['ano_civil']     = r['data_lanc'][:4] if r['data_lanc'] else '?'

    if filtro_ano:
        rows = [r for r in rows if r['ano_civil'] == filtro_ano]

    def agg(rows_in, key_fn):
        d = {}
        for r in rows_in:
            k   = key_fn(r)
            cat = r['categoria'] or 'Sem categoria'
            val = r['debito'] or 0
            if not val: continue
            d.setdefault(k, {})
            d[k][cat] = round(d[k].get(cat,0)+val, 2)
        return sorted([{'chave':k,'categorias':[{'nome':cn,'total':cv} for cn,cv in sorted(v.items(),key=lambda x:x[1],reverse=True)]} for k,v in d.items()], key=lambda x:x['chave'])

    evolucao = {}
    for r in rows:
        p = r['periodo']
        evolucao.setdefault(p, {'periodo':p,'label':r['periodo_label'],'debito':0,'credito':0})
        evolucao[p]['debito']  = round(evolucao[p]['debito']  + (r['debito']  or 0), 2)
        evolucao[p]['credito'] = round(evolucao[p]['credito'] + (r['credito'] or 0), 2)

    top = {}
    for r in rows:
        cat = r['categoria'] or 'Sem categoria'
        top[cat] = round(top.get(cat,0) + (r['debito'] or 0), 2)

    anos_disp = sorted(set(r['ano_civil'] for r in rows if r['data_lanc']), reverse=True)

    return jsonify({
        'por_mes':         agg(rows, lambda r: r['periodo']),
        'por_ano':         agg(rows, lambda r: r['ano_civil']),
        'evolucao_mensal': sorted(evolucao.values(), key=lambda x: x['periodo']),
        'top_categorias':  sorted([{'categoria':k,'total':v} for k,v in top.items()], key=lambda x:x['total'], reverse=True),
        'anos':            anos_disp,
    })

if __name__ == '__main__':
    init_db()
    debug = os.environ.get('FLASK_ENV') != 'production'
    print("\n🏦 Finanças Pessoais — http://0.0.0.0:5000\n")
    app.run(host='0.0.0.0', port=5000, debug=debug)
