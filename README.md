# 💰 Finanças Pessoais

Aplicação web local para visualização e gestão de gastos mensais, com importação de PDFs bancários, suporte a múltiplas contas e deteção automática de transferências internas.

---

## Funcionalidades

- **Importar PDFs** de extratos bancários com revisão interativa de duplicados
- **Múltiplos bancos e contas** — cada extrato é associado a uma conta
- **PDFs combinados** (ex: Moey!/CA) com múltiplas contas no mesmo ficheiro são separados automaticamente
- **Períodos mensais 20→19** — os movimentos são agrupados do dia 20 ao dia 19 do mês seguinte
- **Categorização automática** por palavras-chave configuráveis, com re-categorização a qualquer momento
- **Transferências internas** — deteção automática de movimentos entre as tuas contas, excluídos das estatísticas
- **Dashboard** com resumo por período, barras de despesa por categoria e últimos movimentos
- **Estatísticas** com gráfico de evolução, ranking de categorias, doughnut e heatmap categoria × mês
- **Interface responsiva** — funciona em desktop, tablet e telemóvel
- **Base de dados local** SQLite — sem cloud, sem subscrições, os dados ficam na tua máquina

---

## Instalação

### Pré-requisitos
- Python 3.9+
- `poppler-utils` instalado no sistema (fornece `pdftotext`)

```bash
# Ubuntu/Debian
sudo apt install poppler-utils

# macOS
brew install poppler
```

### Passos

```bash
# 1. Entra na pasta
cd financas

# 2. (Opcional mas recomendado) Cria ambiente virtual
python -m venv venv
source venv/bin/activate      # Linux/Mac
venv\Scripts\activate         # Windows

# 3. Instala dependências Python
pip install -r requirements.txt

# 4. Inicia a aplicação
python app.py
```

Abre o browser em **http://localhost:5000**

---

## Instalação com Docker (recomendado para Proxmox LXC)

### Pré-requisitos no LXC

Se o LXC for **unprivileged** (o padrão no Proxmox), adiciona no nó Proxmox:

```bash
# /etc/pve/lxc/<ID>.conf
features: keyctl=1,nesting=1
```

Reinicia o LXC depois.

### Passos

```bash
# 1. Copia o ZIP para o LXC
scp financas.zip root@<IP_DO_LXC>:/opt/

# 2. No LXC — instala Docker
apt update && apt install -y docker.io docker-compose-plugin

# 3. Descompacta e inicia
cd /opt
unzip financas.zip
cd financas
docker compose up -d
```

A app fica disponível em `http://<IP_DO_LXC>:5000`

### Backup dos dados

```bash
docker run --rm \
  -v financas_data:/data \
  -v $(pwd):/backup \
  alpine tar czf /backup/financas_backup.tar.gz /data
```

---

## Estrutura de ficheiros

```
financas/
├── app.py              # Servidor Flask (backend + API REST)
├── requirements.txt    # Dependências Python
├── Dockerfile          # Imagem Docker
├── docker-compose.yml  # Orquestração Docker
├── .dockerignore
├── README.md
├── data/
│   └── financas.db    # Base de dados SQLite (criada automaticamente)
└── static/
    └── index.html     # Interface web (frontend completo)
```

---

## Formatos de PDF suportados

### ActivoBank
Extrato mensal com colunas posicionais:

```
DATA LANC. | DATA VALOR | DESCRITIVO | DÉBITO | CRÉDITO | SALDO
```

- Datas no formato `M.DD` (ex: `7.01` = dia 1 de julho)
- Saldo inicial identificado para validar débito/crédito
- Deteção de débito vs crédito por posição de coluna + confirmação por saldo

### Moey! / Crédito Agrícola
Extrato combinado com múltiplas secções:

```
DD-MM-YYYY / DD-MM-YYYY   DESCRIÇÃO   VALOR,CC +/-   SALDO
```

- Suporta **CONTA MOEY!**, **CONTA POUPANÇA**, **CONTA ORDENADO**, etc.
- Cada secção é apresentada separadamente no passo de revisão
- O utilizador escolhe a conta destino para cada secção individualmente

### Outros bancos
Fallback genérico via `pdfplumber` para PDFs com tabelas extraíveis. Pode funcionar parcialmente com outros bancos portugueses (BPI, Millennium, Santander, Novo Banco) dependendo do layout.

> **Nota:** A extracção funciona com PDFs de **texto seleccionável**. PDFs gerados por digitalização (imagem) não são suportados.

---

## Fluxo de importação

1. Vai a **Contas** e cria as tuas contas bancárias
2. Em **Importar PDF**, seleciona a conta (para formatos simples) e arrasta o extrato
3. A app extrai os movimentos e apresenta a lista com classificação:
   - ✅ **Novo** — será inserido automaticamente
   - ⚠️ **Possível duplicado** — comparação lado a lado com o existente; tu decides
4. Para PDFs Moey com múltiplas contas, escolhe a conta destino para cada secção
5. Clica **Confirmar** — só então os movimentos são inseridos
6. As transferências internas são detetadas automaticamente após cada importação

---

## Períodos mensais 20→19

Os movimentos são agrupados em períodos que começam no dia 20 e terminam no dia 19 do mês seguinte:

| Data do movimento | Período |
|---|---|
| 25 de Janeiro | Fevereiro |
| 10 de Fevereiro | Fevereiro |
| 20 de Fevereiro | Março |
| 20 de Dezembro | Janeiro (ano seguinte) |

---

## Transferências internas

A app deteta automaticamente pares de movimentos com o **mesmo valor** em **contas diferentes**, dentro de uma janela de tolerância de datas (padrão: 5 dias).

- São marcados com 🔄 na lista de movimentos
- Excluídos das estatísticas por defeito (checkbox "Excluir internas")
- Podes ver e gerir todos os pares em **Transferências Internas**
- Podes desligar pares incorretos com ✂️ Desligar
- Podes re-detetar a qualquer momento com ⚙️ Re-detetar (janela configurável de 1 a 10 dias)

---

## Categorias por defeito

| Categoria | Exemplos de palavras-chave |
|---|---|
| 🛒 Alimentação | continente, pingo doce, lidl, aldi, mercadona |
| 🍽️ Restauração | mcdonald, pizza, uber eats, glovo, restaurante |
| 🚗 Transportes | galp, bp, via verde, cp comboios, uber, bolt |
| 💊 Saúde | farmacia, clinica, hospital, dentista |
| 🎭 Lazer | netflix, spotify, cinema, steam, playstation |
| 🏠 Casa | edp, aguas, nos, meo, vodafone, condominio |
| 👗 Vestuário | zara, hm, primark, decathlon |
| 🛡️ Seguros | fidelidade, allianz, generali, seguro |
| 📱 Telecomunicações | nos, meo, vodafone |
| 📚 Educação | escola, universidade, wook, udemy |
| 🏦 Finanças | prestacao, credito, transferencia, comissao |

Podes adicionar, editar e gerir categorias em **Categorias**. Após editar palavras-chave, usa **Re-categorizar tudo** para aplicar às retroactivamente a todos os movimentos.

---

## Limpar dados

### Apagar só os movimentos (mantém contas e categorias)

```bash
# Com Docker
docker exec -it financas python3 -c "
import sqlite3
conn = sqlite3.connect('/app/data/financas.db')
conn.execute('DELETE FROM movimentos')
conn.execute('DELETE FROM transferencias')
conn.commit()
print('Movimentos apagados.')
"

# Sem Docker
python3 -c "
import sqlite3
conn = sqlite3.connect('data/financas.db')
conn.execute('DELETE FROM movimentos')
conn.execute('DELETE FROM transferencias')
conn.commit()
print('Feito.')
"
```

### Apagar tudo (recomeçar do zero)

```bash
# Com Docker
docker exec -it financas rm /app/data/financas.db
docker restart financas

# Sem Docker
rm data/financas.db
python app.py
```

---

## API REST (resumo)

| Método | Endpoint | Descrição |
|---|---|---|
| GET | `/api/contas` | Lista contas |
| POST | `/api/contas` | Cria conta |
| PUT | `/api/contas/<id>` | Edita conta |
| DELETE | `/api/contas/<id>` | Elimina conta e movimentos |
| POST | `/api/upload/parse` | Processa PDF sem inserir (fase 1) |
| POST | `/api/upload/confirmar` | Insere movimentos confirmados (fase 2) |
| GET | `/api/movimentos` | Lista movimentos (filtros: periodo, conta_id, categoria, so_externas) |
| PUT | `/api/movimentos/<id>/categoria` | Altera categoria de um movimento |
| DELETE | `/api/movimentos/<id>` | Elimina movimento |
| GET | `/api/resumo` | Resumo por período (filtros: conta_id, so_externas) |
| GET | `/api/estatisticas` | Dados para gráficos (filtros: ano, conta_id, so_externas) |
| GET | `/api/periodos` | Lista períodos disponíveis |
| GET | `/api/categorias` | Lista categorias |
| POST | `/api/categorias` | Cria categoria |
| PUT | `/api/categorias/<id>` | Edita categoria |
| POST | `/api/recategorizar` | Re-categoriza todos os movimentos |
| GET | `/api/transferencias` | Lista pares de transferências internas |
| POST | `/api/transferencias/detetar` | Corre deteção (body: `{"janela_dias": 5}`) |
| POST | `/api/movimentos/<id>/desligar_transferencia` | Remove ligação de transferência |
