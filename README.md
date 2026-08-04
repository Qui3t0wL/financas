# 💰 Finanças Pessoais

Aplicação web local para visualização e gestão de gastos mensais, com importação de PDFs bancários.

## Funcionalidades

- **Importar PDFs** do banco (colunas: DATA LANC · DATA VALOR · DESCRITIVO · DÉBITO · CRÉDITO · SALDO)
- **Períodos mensais** de dia 20 a dia 19 do mês seguinte
- **Categorização automática** por palavras-chave configuráveis
- **Dashboard** com resumo por período, barras de despesa por categoria
- **Movimentos** com filtros por período, categoria e pesquisa de texto
- **Edição manual** de categorias por movimento
- **Base de dados local** SQLite (sem cloud, sem subscrições)

## Instalação

### Pré-requisitos
- Python 3.9+

### Passos

```bash
# 1. Entra na pasta
cd financas

# 2. (Opcional) Cria ambiente virtual
python -m venv venv
source venv/bin/activate      # Linux/Mac
venv\Scripts\activate         # Windows

# 3. Instala dependências
pip install -r requirements.txt

# 4. Inicia a aplicação
python app.py
```

Abre o browser em **http://localhost:5000**

## Estrutura de ficheiros

```
financas/
├── app.py              # Servidor Flask (backend + API)
├── requirements.txt    # Dependências Python
├── README.md
├── data/
│   └── financas.db    # Base de dados SQLite (criada automaticamente)
└── static/
    └── index.html     # Interface web (frontend)
```

## Categorias por defeito

| Categoria         | Palavras-chave de exemplo                       |
|-------------------|-------------------------------------------------|
| 🛒 Alimentação    | continente, pingo doce, lidl, aldi, mercadona   |
| 🍽️ Restauração    | mcdonald, pizza, uber eats, glovo               |
| 🚗 Transportes    | galp, bp, via verde, cp comboios, uber, bolt    |
| 💊 Saúde          | farmacia, clinica, hospital, dentista           |
| 🎭 Lazer          | netflix, spotify, cinema, steam, playstation    |
| 🏠 Casa           | edp, aguas, nos, meo, vodafone, condominio      |
| 👗 Vestuário      | zara, hm, primark, decathlon                    |
| 🛡️ Seguros        | fidelidade, allianz, generali, seguro           |
| 📱 Telecomunicações| nos, meo, vodafone                             |
| 📚 Educação       | escola, universidade, wook, udemy               |
| 🏦 Finanças       | prestacao, credito, transferencia, comissao     |

Podes adicionar e editar categorias na secção **Categorias**.

## Período mensal 20→19

O agrupamento funciona assim:
- Movimento de **25 de Janeiro** → período **Fevereiro** (entre 20 Jan e 19 Fev)
- Movimento de **10 de Fevereiro** → período **Fevereiro** (entre 20 Jan e 19 Fev)
- Movimento de **20 de Fevereiro** → período **Março** (entre 20 Fev e 19 Mar)

## Notas sobre compatibilidade de PDFs

A aplicação usa `pdfplumber` para extrair texto e tabelas dos PDFs.
Funciona bem com PDFs com texto seleccionável (o que a maioria dos bancos portugueses gera).
Se o teu banco gera PDFs com imagens (scanned), a extracção não funcionará — nesse caso,
exporta os movimentos em formato texto/CSV se disponível.

Bancos testáveis: CGD, BPI, Millennium BCP, Santander, Novo Banco, Montepio (varia conforme o layout do extracto).
