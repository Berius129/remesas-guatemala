"""Descarga los datos y arma la tabla mensual del proyecto.

Fuentes (todas públicas y sin clave):
- Banguat SDMX: remesas (Remittances), tipo de cambio (EXR) e índice de precios (CPI).
- BLS (EE. UU.): empleo de la población hispana o latina, serie LNS12000009
  (miles de personas, ajustada por estacionalidad).

Uso:  .venv/bin/python src/descargar.py
Escribe data/raw/* (crudos) y data/processed/mensual.csv
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).parent))
import sdmx  # noqa: E402

RAIZ = Path(__file__).resolve().parents[1]
RAW = RAIZ / "data" / "raw"
SALIDA = RAIZ / "data" / "processed" / "mensual.csv"

BLS_SERIE = "LNS12000009"
BLS_URL = "https://api.bls.gov/publicAPI/v1/timeseries/data/"
INICIO = 2010


def ipc_encadenado(cpi: pd.DataFrame) -> pd.Series:
    """Une los tres tramos del IPC en un solo índice (base dic 2010 = 100 del primer tramo).

    - PCPI_BY2010M12_IX: base dic 2010, hasta dic 2023.
    - PCPI_BY2023M12_IX: base dic 2023, se usa solo para 2024 (después de 2024 no es confiable:
      se queda casi plana mientras el índice oficial nuevo sube).
    - PCPI_IX: base promedio 2024 = 100, desde ene 2025.
    Cada tramo se reescala para empalmar con el anterior.
    """
    t1 = sdmx.serie_mensual(cpi, "PCPI_BY2010M12_IX")
    t2 = sdmx.serie_mensual(cpi, "PCPI_BY2023M12_IX")
    t3 = sdmx.serie_mensual(cpi, "PCPI_IX")

    t2 = t2[t2.index.year == 2024] * t1.loc["2023-12-01"] / 100
    # PCPI_IX tiene base "promedio 2024 = 100": se empalma con el promedio 2024 del tramo 2.
    t3 = t3[t3.index.year >= 2025] * t2.mean() / 100
    ipc = pd.concat([t1, t2, t3]).sort_index()
    if ipc.index.duplicated().any():
        raise ValueError("IPC: periodos repetidos al encadenar")
    return ipc.rename("ipc")


def empleo_hispano() -> pd.Series:
    """Empleo hispano en EE. UU. desde la API v1 de BLS.

    Ojo: por GET la API ignora startyear/endyear y devuelve solo los últimos años; hay que usar
    POST. Se pide en bloques de 3 años. BLS no publicó octubre 2025 (cierre del gobierno de
    EE. UU.), así que ese mes queda vacío.
    """
    filas = []
    hoy = date.today().year
    for inicio in range(INICIO, hoy + 1, 3):
        cuerpo = {"seriesid": [BLS_SERIE], "startyear": str(inicio), "endyear": str(min(inicio + 2, hoy))}
        r = requests.post(BLS_URL, json=cuerpo, timeout=60)
        r.raise_for_status()
        d = r.json()
        if d.get("status") != "REQUEST_SUCCEEDED":
            raise RuntimeError(f"BLS: {d.get('status')} {d.get('message')}")
        filas += d["Results"]["series"][0]["data"]
    (RAW / f"bls_{BLS_SERIE}.json").write_text(json.dumps(filas, indent=1))
    return serie_bls(filas)


def serie_bls(filas: list[dict]) -> pd.Series:
    s = pd.Series({
        pd.Timestamp(int(f["year"]), int(f["period"][1:]), 1): float(f["value"]) * 1000
        for f in filas if f["period"].startswith("M") and f["period"] != "M13" and f["value"] not in ("-", "")
    })
    return s.sort_index().rename("empleo_hispano_eeuu")


def main() -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    datos = {c: sdmx.leer(sdmx.descargar(c, RAW / f"{c}_Guatemala.xml")) for c in ["Remittances", "EXR", "CPI"]}

    remesas = sdmx.serie_mensual(datos["Remittances"], "GTM_REMIT_USD").rename("remesas_usd")
    tc = sdmx.serie_mensual(datos["EXR"], "ENDA_XDC_USD_RATE").rename("tipo_cambio")
    ipc = ipc_encadenado(datos["CPI"])
    try:
        empleo = empleo_hispano()
    except (requests.RequestException, RuntimeError, KeyError) as e:
        # La API pública de BLS limita las consultas por día y por IP (en GitHub Actions las IPs
        # son compartidas). Si falla, se reutiliza la última descarga guardada.
        respaldo = RAW / f"bls_{BLS_SERIE}.json"
        if not respaldo.exists():
            raise
        print(f"AVISO: BLS no respondió ({e}); se usa {respaldo.name}", file=sys.stderr)
        empleo = serie_bls(json.loads(respaldo.read_text()))

    df = pd.concat([remesas, tc, ipc, empleo], axis=1)
    df = df[df.index >= remesas.index.min()]
    df.index.name = "mes"
    # Remesas en quetzales y en quetzales constantes (poder de compra en Guatemala).
    df["remesas_gtq"] = df["remesas_usd"] * df["tipo_cambio"]
    base = df["ipc"].dropna().iloc[-1]
    df["remesas_gtq_reales"] = df["remesas_gtq"] / df["ipc"] * base

    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(SALIDA, date_format="%Y-%m")
    ult = df["remesas_usd"].last_valid_index()
    print(f"{len(df)} meses ({df.index.min():%Y-%m} a {ult:%Y-%m}) -> {SALIDA.relative_to(RAIZ)}")
    print("Último dato por columna:")
    for c in df.columns:
        print(f"  {c:22} {df[c].last_valid_index():%Y-%m}")


if __name__ == "__main__":
    main()
