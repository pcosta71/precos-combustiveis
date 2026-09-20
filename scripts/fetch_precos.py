#!/usr/bin/env python3
"""
Recolhe os precos de combustiveis da DGEG para os concelhos configurados,
grava um CSV por dia em dados/ e reconstroi o historico.csv consolidado.

Sem dependencias externas - usa apenas a biblioteca padrao do Python.

Codigos de saida:
    0 - recolha completa
    2 - recolha incompleta (o ficheiro foi gravado na mesma)
    1 - recolha falhou por completo (nada foi gravado)
"""

from __future__ import annotations

import csv
import json
import os
import sys
import time
import urllib.request
from datetime import date
from pathlib import Path

API = "https://precoscombustiveis.dgeg.gov.pt/api/PrecoComb/PesquisarPostos"

# Zonas a recolher: (nome, idDistrito, idsMunicipios)
# A API so aceita um distrito de cada vez, por isso cada distrito e uma entrada.
ZONAS = [
    ("Porto", 13, "184,196"),   # 184 = Gondomar, 196 = Valongo
    ("Vila Real", 17, "251"),   # 251 = Murca
]

# Combustiveis: (idTipoComb, nome legivel)
COMBUSTIVEIS = [
    (3201, "Gasolina simples 95"),
    (1120, "GPL Auto"),
]

# Abaixo deste total de registos assume-se que a recolha ficou incompleta.
MINIMO_TOTAL = 40

CABECALHO = [
    "Data", "Combustivel", "PostoId", "Posto", "Marca", "TipoPosto",
    "Morada", "Municipio", "Preco", "DataAtualizacao", "Latitude", "Longitude",
]

RAIZ = Path(__file__).resolve().parent.parent
PASTA_DADOS = RAIZ / "dados"
HISTORICO = RAIZ / "historico.csv"

avisos: list[str] = []   # informativos: a API respondeu, mas sem postos
falhas: list[str] = []   # reais: a API nao respondeu apos tres tentativas


def pedir(id_comb: int, id_distrito: int, ids_municipios: str) -> list[dict]:
    """Um pedido a API, com tres tentativas. Devolve a lista de postos."""
    url = (
        f"{API}?qtdPorPagina=200&pagina=1&orderAsc=true"
        f"&idsTiposComb={id_comb}&idMarca=&idTipoPosto="
        f"&idDistrito={id_distrito}&idsMunicipios={ids_municipios}"
        f"&qtdPorPaginaFiltro=200"
    )
    pedido = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "precos-combustiveis/1.0 (+github actions)",
        },
    )

    ultimo_erro = None
    for tentativa in range(3):
        try:
            with urllib.request.urlopen(pedido, timeout=30) as resposta:
                corpo = json.loads(resposta.read().decode("utf-8"))
            if not corpo.get("status"):
                # Resposta valida a dizer que nao ha postos - nao e erro de rede.
                avisos.append(
                    f"comb {id_comb} / distrito {id_distrito}: "
                    f"{corpo.get('mensagem', 'sem resultados')}"
                )
                return []
            return corpo.get("resultado") or []
        except Exception as erro:          # noqa: BLE001
            ultimo_erro = erro
            time.sleep(5 * (tentativa + 1))

    falhas.append(f"comb {id_comb} / distrito {id_distrito}: falhou - {ultimo_erro}")
    return []


def preco_pt(valor: str) -> str:
    """A API devolve '2,114 EUR' ja com virgula decimal - so tiramos o simbolo."""
    return (valor or "").replace("€", "").strip()


def numero_pt(valor) -> str:
    """41.40636 -> '41,40636' (virgula decimal, para leitura com locale PT)."""
    if valor is None or valor == "":
        return ""
    return str(float(valor)).replace(".", ",")


def para_linha(registo: dict, hoje: str) -> list[str]:
    return [
        hoje,
        (registo.get("Combustivel") or "").strip(),
        str(registo.get("Id") or ""),
        (registo.get("Nome") or "").strip(),
        (registo.get("Marca") or "").strip(),
        (registo.get("TipoPosto") or "").strip(),
        (registo.get("Morada") or "").strip(),
        (registo.get("Municipio") or "").strip(),
        preco_pt(registo.get("Preco")),
        (registo.get("DataAtualizacao") or "").strip(),
        numero_pt(registo.get("Latitude")),
        numero_pt(registo.get("Longitude")),
    ]


def recolher(hoje: str) -> list[list[str]]:
    linhas: list[list[str]] = []
    vistos: set[tuple[str, str]] = set()

    for id_comb, nome_comb in COMBUSTIVEIS:
        for nome_zona, id_distrito, ids_municipios in ZONAS:
            registos = pedir(id_comb, id_distrito, ids_municipios)
            print(f"  {nome_comb:22s} {nome_zona:10s} -> {len(registos):3d} postos")
            for registo in registos:
                linha = para_linha(registo, hoje)
                chave = (linha[1], linha[2])          # combustivel + PostoId
                if chave in vistos:
                    continue                          # defesa contra sobreposicoes
                vistos.add(chave)
                linhas.append(linha)

    ordem = {nome: i for i, (_, nome) in enumerate(COMBUSTIVEIS)}

    def chave_ordenacao(linha: list[str]):
        try:
            preco = float(linha[8].replace(",", "."))
        except ValueError:
            preco = 999.0
        return (ordem.get(linha[1], 99), preco, linha[2])

    linhas.sort(key=chave_ordenacao)
    return linhas


def gravar_csv(caminho: Path, linhas: list[list[str]]) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with caminho.open("w", encoding="utf-8-sig", newline="") as saida:
        escritor = csv.writer(
            saida, delimiter=";", quoting=csv.QUOTE_MINIMAL, lineterminator="\r\n"
        )
        escritor.writerow(CABECALHO)
        escritor.writerows(linhas)


def reconstruir_historico() -> tuple[int, int]:
    """Junta todos os ficheiros diarios num so. Reconstruir do zero de cada vez
    torna o historico auto-corrigivel: se um dia for corrigido a mao, o
    consolidado acompanha na execucao seguinte."""
    ficheiros = sorted(PASTA_DADOS.glob("precos_*.csv"))
    total = 0
    with HISTORICO.open("w", encoding="utf-8-sig", newline="") as saida:
        escritor = csv.writer(
            saida, delimiter=";", quoting=csv.QUOTE_MINIMAL, lineterminator="\r\n"
        )
        escritor.writerow(CABECALHO)
        for ficheiro in ficheiros:
            with ficheiro.open(encoding="utf-8-sig", newline="") as entrada:
                leitor = csv.reader(entrada, delimiter=";")
                next(leitor, None)                    # salta o cabecalho
                for registo in leitor:
                    if registo and any(campo.strip() for campo in registo):
                        escritor.writerow(registo)
                        total += 1
    return len(ficheiros), total


def resumo(texto: str) -> None:
    print(texto)
    caminho = os.environ.get("GITHUB_STEP_SUMMARY")
    if caminho:
        with open(caminho, "a", encoding="utf-8") as ficheiro:
            ficheiro.write(texto + "\n")


def main() -> int:
    hoje = date.today().isoformat()
    print(f"Recolha de {hoje}")

    linhas = recolher(hoje)

    if not linhas:
        resumo(f"**Recolha de {hoje} falhou** - nenhum posto obtido. Nada foi gravado.")
        for mensagem in falhas + avisos:
            resumo(f"- {mensagem}")
        return 1

    destino = PASTA_DADOS / f"precos_{hoje}.csv"
    gravar_csv(destino, linhas)
    n_ficheiros, n_historico = reconstruir_historico()

    gasolina = sum(1 for linha in linhas if linha[1].startswith("Gasolina"))
    gpl = sum(1 for linha in linhas if linha[1].startswith("GPL"))

    resumo(
        f"### Precos de {hoje}\n\n"
        f"- {len(linhas)} registos ({gasolina} gasolina 95, {gpl} GPL auto)\n"
        f"- ficheiro: `dados/precos_{hoje}.csv`\n"
        f"- historico: {n_historico} registos em {n_ficheiros} dias\n"
    )

    if avisos:
        resumo("\n**Sem postos** (resposta valida da API, apenas informativo)\n")
        for aviso in avisos:
            resumo(f"- {aviso}")

    if falhas:
        resumo("\n**Falhas de comunicacao**\n")
        for falha in falhas:
            resumo(f"- {falha}")

    # So sinaliza problema se a API nao respondeu, ou se o volume caiu muito
    # abaixo do normal. Um concelho sem GPL nao e um erro.
    if falhas or len(linhas) < MINIMO_TOTAL:
        resumo(f"\nRecolha incompleta (minimo esperado: {MINIMO_TOTAL} registos).")
        return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
