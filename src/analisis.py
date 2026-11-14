"""Análisis de remesas: peso en la economía, estacionalidad, relación con el empleo
hispano en EE. UU. y pronóstico a 12 meses.

Uso:  .venv/bin/python src/analisis.py   (después de descargar.py)
Escribe data/processed/{anual,estacionalidad,pronostico,backtest}.csv y resumen.json
"""
from __future__ import annotations

import json
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from statsmodels.tsa.seasonal import STL
from statsmodels.tsa.holtwinters import ExponentialSmoothing
from statsmodels.tsa.statespace.sarimax import SARIMAX

sys.path.insert(0, str(Path(__file__).parent))
import sdmx  # noqa: E402

RAIZ = Path(__file__).resolve().parents[1]
PROC = RAIZ / "data" / "processed"
RAW = RAIZ / "data" / "raw"

H = 12  # meses de pronóstico y de cada ventana de prueba
N_ORIGENES = 10  # ventanas de validación: una por año, la última termina en el último dato


def cargar() -> pd.DataFrame:
    df = pd.read_csv(PROC / "mensual.csv", index_col="mes")
    df.index = pd.PeriodIndex(df.index, freq="M").to_timestamp()
    return df.asfreq("MS")


def pib_anual() -> pd.DataFrame:
    """PIB nominal y consumo privado anuales (quetzales) de las cuentas nacionales de Banguat."""
    ruta = RAW / "NAG_Guatemala.xml"
    if not ruta.exists():
        sdmx.descargar("NAG", ruta)
    nag = sdmx.leer(ruta)
    a = nag[nag["FREQ"] == "A"].pivot_table(index="periodo", columns="INDICATOR", values="valor")
    a.index = a.index.astype(int)
    return a[["NGDP_XDC", "NCP_XDC"]].rename(columns={"NGDP_XDC": "pib_gtq", "NCP_XDC": "consumo_privado_gtq"})


def anual(df: pd.DataFrame) -> pd.DataFrame:
    meses = df["remesas_usd"].groupby(df.index.year).count()
    a = df.groupby(df.index.year)[["remesas_usd", "remesas_gtq", "remesas_gtq_reales"]].sum()
    a = a[meses == 12]  # solo años completos
    a["crecimiento_usd"] = a["remesas_usd"].pct_change()
    a["crecimiento_real_gtq"] = a["remesas_gtq_reales"].pct_change()
    a = a.join(pib_anual())
    a["pct_pib"] = a["remesas_gtq"] / a["pib_gtq"]
    a["pct_consumo_privado"] = a["remesas_gtq"] / a["consumo_privado_gtq"]
    a.index.name = "anio"
    return a


def estacionalidad(df: pd.DataFrame) -> pd.DataFrame:
    """Factor estacional por mes con STL sobre el logaritmo (2012 en adelante).

    exp(factor) - 1 = cuánto se aparta ese mes de la tendencia, en %.
    """
    y = np.log(df["remesas_usd"].dropna())
    y = y[y.index.year >= 2012]
    stl = STL(y, period=12, robust=True).fit()
    est = stl.seasonal.groupby(stl.seasonal.index.month).mean()
    return pd.DataFrame({"mes": est.index, "efecto_pct": np.exp(est.values) - 1})


def interanual(df: pd.DataFrame) -> pd.DataFrame:
    """Crecimiento interanual de remesas (suma de 12 meses) y del empleo hispano en EE. UU. (promedio de 12 meses)."""
    r12 = df["remesas_usd"].rolling(12).sum()
    out = pd.DataFrame({
        "remesas_12m_usd": r12,
        "crec_remesas": r12.pct_change(12),
        # Promedio de 12 meses para comparar con la suma de 12 meses de remesas (misma ventana).
        # min_periods=11 tolera el mes que BLS no publicó (oct 2025).
        "crec_empleo_hispano": df["empleo_hispano_eeuu"].rolling(12, min_periods=11).mean().pct_change(12, fill_method=None),
    })
    return out


# ---------------------------------------------------------------- modelos candidatos
# Cada función recibe la historia y devuelve el pronóstico de los próximos H meses.
# Los modelos estadísticos trabajan sobre el logaritmo: el efecto estacional es proporcional
# al nivel (mayo sube ~8 % sobre la tendencia, no una cantidad fija de dólares).

def _indice_futuro(y: pd.Series) -> pd.DatetimeIndex:
    return pd.date_range(y.index[-1] + pd.offsets.MonthBegin(1), periods=H, freq="MS")


def ingenuo_estacional(y: pd.Series) -> pd.Series:
    return pd.Series(y.iloc[-12:].values, index=_indice_futuro(y))


def ingenuo_con_tendencia(y: pd.Series) -> pd.Series:
    crec = y.iloc[-12:].sum() / y.iloc[-24:-12].sum()
    return ingenuo_estacional(y) * crec


def _sarima(y: pd.Series, orden, est) -> pd.Series:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        m = SARIMAX(np.log(y), order=orden, seasonal_order=est).fit(disp=False)
    return np.exp(m.get_forecast(H).predicted_mean)


def sarima_airline(y):  # (0,1,1)(0,1,1)12, el modelo clásico para series mensuales con tendencia
    return _sarima(y, (0, 1, 1), (0, 1, 1, 12))


def sarima_111(y):
    return _sarima(y, (1, 1, 1), (0, 1, 1, 12))


def ets_amortiguado(y):  # Holt-Winters con tendencia amortiguada: el crecimiento se frena con el tiempo
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        m = ExponentialSmoothing(np.log(y), trend="add", damped_trend=True, seasonal="add",
                                 seasonal_periods=12).fit()
    f = np.exp(m.forecast(H))
    f.index = _indice_futuro(y)
    return f


MODELOS = {
    "Ingenuo estacional": ingenuo_estacional,
    "Ingenuo con tendencia": ingenuo_con_tendencia,
    "SARIMA (0,1,1)(0,1,1)": sarima_airline,
    "SARIMA (1,1,1)(0,1,1)": sarima_111,
    "Holt-Winters amortiguado": ets_amortiguado,
}


def validacion(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Validación con origen móvil: para cada año se entrena con la historia previa y se
    pronostican los 12 meses siguientes, que se comparan con lo observado.

    Devuelve (errores por ventana y modelo, detalle mensual de la última ventana).
    """
    y = df["remesas_usd"].dropna()
    filas, ultima = [], None
    for k in range(N_ORIGENES, 0, -1):
        corte = len(y) - k * H
        train, test = y.iloc[:corte], y.iloc[corte:corte + H]
        pron = {}
        for nombre, f in MODELOS.items():
            p = f(train)
            p.index = test.index
            pron[nombre] = p
            filas.append({
                "ventana": f"{test.index[0]:%Y-%m} a {test.index[-1]:%Y-%m}",
                "modelo": nombre,
                "mape": float((p / test - 1).abs().mean()),
                "error_total": float(p.sum() / test.sum() - 1),
            })
        if k == 1:
            ultima = pd.DataFrame({"observado": test, **pron})
    return pd.DataFrame(filas), ultima


def pronostico(df: pd.DataFrame, modelo: str) -> pd.DataFrame:
    """Pronóstico del modelo elegido. El intervalo sale de los errores de la validación
    (percentiles del error de cada horizonte), así sirve igual para cualquier modelo."""
    y = df["remesas_usd"].dropna()
    return pd.DataFrame({"pronostico": MODELOS[modelo](y)})


def intervalos(pr: pd.DataFrame, errores_total: pd.Series) -> dict:
    """Rango del total a 12 meses según los errores históricos de ese modelo (min-max y 10-90 %)."""
    total = pr["pronostico"].sum()
    # error = pronóstico/observado - 1  ->  observado = pronóstico / (1 + error)
    obs = total / (1 + errores_total)
    return {"total": float(total), "p10": float(obs.quantile(0.1)), "p90": float(obs.quantile(0.9)),
            "min": float(obs.min()), "max": float(obs.max())}


def main() -> None:
    df = cargar()
    a = anual(df)
    est = estacionalidad(df)
    ia = interanual(df)
    val, ultima = validacion(df)
    tabla = val.groupby("modelo").agg(mape=("mape", "mean"), error_total_abs=("error_total", lambda e: e.abs().mean()),
                                      peor_error_total=("error_total", lambda e: e.abs().max()))
    tabla = tabla.sort_values("mape")
    ganador = tabla.index[0]
    pr = pronostico(df, ganador)
    rango = intervalos(pr, val.loc[val["modelo"] == ganador, "error_total"])

    a.to_csv(PROC / "anual.csv")
    est.to_csv(PROC / "estacionalidad.csv", index=False)
    ia.to_csv(PROC / "interanual.csv", date_format="%Y-%m")
    val.to_csv(PROC / "validacion.csv", index=False)
    tabla.to_csv(PROC / "modelos.csv")
    ultima.to_csv(PROC / "ultima_ventana.csv", date_format="%Y-%m")
    pr.to_csv(PROC / "pronostico.csv", date_format="%Y-%m")

    ult = df["remesas_usd"].last_valid_index()
    ytd = df.loc[f"{ult.year}-01":ult, "remesas_usd"].sum()
    ytd_prev = df.loc[f"{ult.year - 1}-01":ult - pd.DateOffset(years=1), "remesas_usd"].sum()
    # Correlación del crecimiento interanual antes de 2025, y la brecha desde entonces.
    c = ia.dropna()
    resumen = {
        "ultimo_mes": f"{ult:%Y-%m}",
        "acumulado_anio_usd": ytd, "acumulado_anio_anterior_usd": ytd_prev,
        "crecimiento_acumulado": ytd / ytd_prev - 1,
        "ultimo_anio_completo": int(a.index.max()),
        "remesas_ultimo_anio_usd": float(a["remesas_usd"].iloc[-1]),
        "pct_pib_ultimo_anio": float(a["pct_pib"].iloc[-1]),
        "pct_consumo_privado_ultimo_anio": float(a["pct_consumo_privado"].iloc[-1]),
        "correlacion_crecimiento_2012_2024": float(c.loc[:"2024-12", ["crec_remesas", "crec_empleo_hispano"]].corr().iloc[0, 1]),
        "modelo_elegido": ganador,
        "mape_modelo_elegido": float(tabla.loc[ganador, "mape"]),
        "pronostico_12m": rango,
        "pronostico_desde": f"{pr.index[0]:%Y-%m}", "pronostico_hasta": f"{pr.index[-1]:%Y-%m}",
        "remesas_12m_actual_usd": float(df["remesas_usd"].iloc[-12:].sum()),
    }
    (PROC / "resumen.json").write_text(json.dumps(resumen, indent=2, ensure_ascii=False))

    pd.set_option("display.width", 200)
    print(a[["remesas_usd", "crecimiento_usd", "crecimiento_real_gtq", "pct_pib", "pct_consumo_privado"]]
          .assign(remesas_usd=lambda x: (x["remesas_usd"] / 1e6).round(0)).round(3).tail(8).to_string())
    print("\nEstacionalidad:", {int(m): f"{v:+.1%}" for m, v in zip(est["mes"], est["efecto_pct"])})
    print("\nCrecimiento interanual (últimos):\n", ia.dropna().iloc[-24::3].round(3).to_string())
    print("\nValidación (promedio de", N_ORIGENES, "ventanas de 12 meses):\n", tabla.round(3).to_string())
    print("\nError total por ventana:\n", val.pivot(index="ventana", columns="modelo", values="error_total").round(3).to_string())
    print("\nResumen:", json.dumps(resumen, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
