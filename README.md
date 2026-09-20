# Preços de combustíveis — Gondomar, Valongo e Murça

Recolha diária automática dos preços de **gasolina simples 95** e **GPL auto**
a partir da API pública da [DGEG](https://precoscombustiveis.dgeg.gov.pt/),
para alimentar um relatório Power BI.

Corre inteiramente no GitHub Actions — não depende de nenhum computador ligado.

## Como funciona

Todos os dias às 06:05 UTC o workflow chama a API da DGEG (quatro pedidos:
dois combustíveis × dois distritos), grava `dados/precos_AAAA-MM-DD.csv` e
reconstrói o `historico.csv` consolidado a partir de todos os ficheiros diários.

| Caminho | Conteúdo |
|---|---|
| `dados/precos_AAAA-MM-DD.csv` | Um ficheiro por dia — o registo histórico |
| `historico.csv` | Todos os dias juntos — **é este que o Power BI lê** |
| `scripts/fetch_precos.py` | A recolha |
| `.github/workflows/precos.yml` | O agendamento |

## Formato dos ficheiros

UTF-8 com BOM, separador `;`, fim de linha CRLF, **vírgula decimal**
(para leitura com locale português). Doze colunas, sempre as mesmas:

```
Data;Combustivel;PostoId;Posto;Marca;TipoPosto;Morada;Municipio;Preco;DataAtualizacao;Latitude;Longitude
```

`Data` é o dia da recolha. `DataAtualizacao` é a data que a DGEG indica para
aquele preço — nem todos os postos reportam diariamente, por isso é normal
encontrar preços com vários dias.

## Alterar os concelhos ou os combustíveis

Tudo em `scripts/fetch_precos.py`, no topo:

```python
ZONAS = [
    ("Porto", 13, "184,196"),   # 184 = Gondomar, 196 = Valongo
    ("Vila Real", 17, "251"),   # 251 = Murça
]
COMBUSTIVEIS = [
    (3201, "Gasolina simples 95"),
    (1120, "GPL Auto"),
]
```

Os identificadores vêm da própria API:

- distritos: `/api/PrecoComb/GetDistritos`
- municípios: `/api/PrecoComb/GetMunicipios?idDistrito=13`
- combustíveis: `/api/PrecoComb/GetTiposCombustiveis`

A API só aceita **um distrito por pedido** — municípios do mesmo distrito
vão juntos, separados por vírgula; distritos diferentes são entradas separadas.

## Quando algo corre mal

O workflow marca a execução como falhada se a API não responder ou se o volume
de registos cair abaixo de `MINIMO_TOTAL`. Um concelho sem determinado
combustível é apenas informativo e não faz falhar nada.

O ficheiro do dia é gravado mesmo em recolhas parciais — mais vale um dia
incompleto do que um buraco na série.
