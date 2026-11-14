"""Lector de los archivos SDMX que publica el Banco de Guatemala.

Banguat publica sus estadísticas en formato SDMX 2.1 "StructureSpecificData" (estándar del FMI)
en https://www.banguat.gob.gt/sites/default/files/banguat/Publica/sdmx/<CONJUNTO>_Guatemala.xml

Conjuntos disponibles: CPI (precios), Remittances (remesas), EXR (tipo de cambio), ILV (reservas),
INR (tasas), IND (IMAE), NAG (cuentas nacionales), BOP (balanza de pagos), IIP, DOT, MET (comercio),
CBS, DCS (monetario), EMP (empleo), POP (población).

Este módulo no depende del conjunto: devuelve una tabla larga con todas las dimensiones de cada
serie, para que cualquier proyecto lo reutilice.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pandas as pd
import requests

URL = "https://www.banguat.gob.gt/sites/default/files/banguat/Publica/sdmx/{}_Guatemala.xml"
AGENTE = "remesas-gt/1.0 (analisis de datos publicos; github.com/Berius129)"


def descargar(conjunto: str, destino: Path) -> Path:
    """Descarga el XML del conjunto y lo guarda tal cual (dato crudo, sin modificar)."""
    r = requests.get(URL.format(conjunto), headers={"User-Agent": AGENTE}, timeout=60)
    r.raise_for_status()
    if not r.content.lstrip().startswith(b"<?xml"):
        raise ValueError(f"{conjunto}: la respuesta no es XML (¿cambió la URL o hay bloqueo?)")
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(r.content)
    return destino


def leer(ruta: Path) -> pd.DataFrame:
    """Devuelve una fila por observación: dimensiones de la serie + periodo + valor.

    El valor se multiplica por 10**UNIT_MULT, así que queda en unidades (no en miles/millones).
    """
    filas = []
    for _, elem in ET.iterparse(ruta, events=("end",)):
        if elem.tag.split("}")[-1] != "Series":
            continue
        dims = dict(elem.attrib)
        mult = 10 ** int(dims.get("UNIT_MULT", "0") or 0)
        for obs in elem:
            if obs.tag.split("}")[-1] != "Obs":
                continue
            # Banguat marca datos faltantes con "." u otros textos: se omiten.
            try:
                valor = float(obs.attrib.get("OBS_VALUE", ""))
            except ValueError:
                continue
            if valor != valor:  # NaN
                continue
            filas.append({**dims, "periodo": obs.attrib["TIME_PERIOD"], "valor": valor * mult})
        elem.clear()
    if not filas:
        raise ValueError(f"{ruta.name}: no se encontraron observaciones")
    return pd.DataFrame(filas)


def serie_mensual(df: pd.DataFrame, indicador: str) -> pd.Series:
    """Serie mensual de un indicador, indexada por el primer día del mes."""
    d = df[(df["INDICATOR"] == indicador) & (df["FREQ"] == "M")]
    if d.empty:
        raise KeyError(f"No hay serie mensual {indicador}")
    s = d.set_index(pd.PeriodIndex(d["periodo"], freq="M").to_timestamp())["valor"].sort_index()
    if s.index.duplicated().any():
        raise ValueError(f"{indicador}: periodos repetidos")
    return s.rename(indicador)
