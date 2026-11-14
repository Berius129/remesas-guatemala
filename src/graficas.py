"""Genera las gráficas del reporte en reports/figuras/.

Uso:  .venv/bin/python src/graficas.py   (después de analisis.py)
"""
import json
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.ticker import FuncFormatter, PercentFormatter

RAIZ = Path(__file__).resolve().parents[1]
PROC = RAIZ / "data" / "processed"
FIG = RAIZ / "reports" / "figuras"

SUPERFICIE, TEXTO, TEXTO_2, GRID, GRIS = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df", "#9a9893"
AZUL, NARANJA, VERDE, ROJO = "#2a78d6", "#eb6834", "#1baf7a", "#e34948"
MESES = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]

plt.rcParams.update({
    "figure.facecolor": SUPERFICIE, "axes.facecolor": SUPERFICIE, "savefig.facecolor": SUPERFICIE,
    "font.family": "sans-serif", "font.size": 10, "text.color": TEXTO,
    "axes.edgecolor": GRID, "axes.labelcolor": TEXTO_2, "axes.titlecolor": TEXTO,
    "axes.spines.top": False, "axes.spines.right": False, "axes.spines.left": False,
    "axes.grid": True, "axes.grid.axis": "y", "grid.color": GRID, "grid.linewidth": 0.8,
    "xtick.color": TEXTO_2, "ytick.color": TEXTO_2, "xtick.major.size": 0, "ytick.major.size": 0,
    "lines.linewidth": 2, "legend.frameon": False,
})

MILES_MILLONES = FuncFormatter(lambda v, _: f"${v / 1e9:,.0f}")


def lienzo(titulo: str, subtitulo: str, fuente: str, tam=(9.5, 5.4)):
    fig, ax = plt.subplots(figsize=tam)
    fig.subplots_adjust(top=0.8, bottom=0.12, left=0.08, right=0.95)
    fig.text(0.02, 0.965, titulo, fontsize=14, fontweight="bold", va="top")
    fig.text(0.02, 0.905, subtitulo, fontsize=10, color=TEXTO_2, va="top")
    fig.text(0.02, 0.015, fuente, fontsize=8, color=TEXTO_2)
    return fig, ax


def guardar(fig, nombre):
    fig.savefig(FIG / nombre, dpi=200)
    plt.close(fig)
    print("  ", nombre)


def remesas_12m(m: pd.DataFrame, a: pd.DataFrame, r: dict):
    s = m["remesas_usd"].rolling(12).sum().dropna()
    fig, ax = lienzo(
        f"Las remesas ya equivalen al {r['pct_pib_ultimo_anio']:.0%} del PIB de Guatemala",
        f"Remesas familiares recibidas en los 12 meses previos a cada fecha, miles de millones de US$ (último dato: {r['ultimo_mes']})",
        "Fuente: Banco de Guatemala (SDMX). Elaboración propia.")
    ax.plot(s.index, s, color=AZUL)
    ax.yaxis.set_major_formatter(MILES_MILLONES)
    ax.set_ylim(0, s.max() * 1.15)
    for fecha, texto, dx, dy in [("2020-05-01", "Pandemia: caída de\n3 meses y rebote", -120, 30),
                                 ("2025-12-01", "2025: +19 %, el mayor\nsalto desde 2021", -190, 0)]:
        f = pd.Timestamp(fecha)
        ax.annotate(texto, (f, s.loc[f]), xytext=(dx, dy), textcoords="offset points", fontsize=8.5,
                    color=TEXTO, va="center", arrowprops=dict(arrowstyle="-", color=GRIS, lw=0.8))
    ultimo = s.index[-1]
    ax.annotate(f"${s.iloc[-1] / 1e9:,.1f} mil millones", (ultimo, s.iloc[-1]), xytext=(-150, 14),
                textcoords="offset points", fontsize=9, color=TEXTO, fontweight="bold")
    guardar(fig, "01_remesas_12_meses.png")


def estacionalidad(e: pd.DataFrame):
    fig, ax = lienzo("Mayo es el mes fuerte; enero y febrero, los más débiles",
                     "Cuánto se aparta cada mes de la tendencia de las remesas (promedio 2012-2026)",
                     "Fuente: Banco de Guatemala. Descomposición STL sobre el logaritmo de la serie mensual.")
    colores = [AZUL if v >= 0 else ROJO for v in e["efecto_pct"]]
    ax.bar(range(12), e["efecto_pct"], color=colores, width=0.7, edgecolor=SUPERFICIE, linewidth=2)
    ax.axhline(0, color=GRIS, lw=1)
    ax.set_xticks(range(12), MESES)
    ax.yaxis.set_major_formatter(PercentFormatter(1, decimals=0))
    for i, v in enumerate(e["efecto_pct"]):
        ax.text(i, v + (0.006 if v >= 0 else -0.006), f"{v:+.0%}", ha="center",
                va="bottom" if v >= 0 else "top", fontsize=8.5, color=TEXTO)
    ax.set_ylim(e["efecto_pct"].min() * 1.3, e["efecto_pct"].max() * 1.5)
    ax.text(4, e["efecto_pct"].iloc[4] * 1.33, "Día de la Madre", ha="center", fontsize=8, color=TEXTO_2)
    guardar(fig, "02_estacionalidad.png")


def crecimiento_vs_empleo(ia: pd.DataFrame, r: dict):
    d = ia.dropna(subset=["crec_remesas"]).loc["2012-01":]
    fig, ax = lienzo("Las remesas crecen más rápido que el empleo de los migrantes",
                     "Crecimiento interanual, ventanas de 12 meses: remesas a Guatemala y empleo hispano en EE. UU.",
                     "Fuentes: Banco de Guatemala; U.S. Bureau of Labor Statistics, serie LNS12000009 "
                     "(oct 2025 no se publicó). Elaboración propia.")
    ax.axvspan(pd.Timestamp("2025-01-01"), d.index[-1], color=GRID, alpha=0.6, lw=0)
    ax.axvspan(pd.Timestamp("2021-01-01"), pd.Timestamp("2021-12-31"), color=GRID, alpha=0.6, lw=0)
    ax.axhline(0, color=GRIS, lw=1)
    ax.plot(d.index, d["crec_remesas"], color=AZUL, label="Remesas a Guatemala")
    ax.plot(d.index, d["crec_empleo_hispano"], color=NARANJA, label="Empleo hispano en EE. UU.")
    ax.yaxis.set_major_formatter(PercentFormatter(1, decimals=0))
    ax.legend(loc="upper left", ncol=2, bbox_to_anchor=(0, 1.08))
    ax.text(pd.Timestamp("2025-02-01"), ax.get_ylim()[0] * 0.85,
            f"Correlación\n2012-2024: {r['correlacion_crecimiento_2012_2024']:.2f}",
            fontsize=8.5, color=TEXTO_2, va="bottom")
    for fecha, texto, ha in [("2020-12-01", "2021: estímulos fiscales\nen EE. UU.", "right"), ("2025-02-01", "2025", "left")]:
        ax.text(pd.Timestamp(fecha), ax.get_ylim()[1] * 0.93, texto, fontsize=8.5, color=TEXTO_2, va="top", ha=ha)
    guardar(fig, "03_crecimiento_vs_empleo.png")


def dolares_vs_quetzales(a: pd.DataFrame):
    d = a.loc[2015:, ["remesas_usd", "remesas_gtq", "remesas_gtq_reales"]]
    d = d / d.iloc[0] * 100
    fig, ax = lienzo("En quetzales de hoy, las remesas rinden menos de lo que crecen en dólares",
                     "Índice 2015 = 100. Remesas anuales en dólares, en quetzales y en quetzales constantes",
                     "Fuente: Banco de Guatemala (remesas, tipo de cambio de fin de mes, IPC encadenado). "
                     "Elaboración propia.")
    series = [("remesas_usd", "En dólares", AZUL), ("remesas_gtq", "En quetzales", NARANJA),
              ("remesas_gtq_reales", "En quetzales constantes\n(descontando inflación)", VERDE)]
    # Dólares y quetzales casi se superponen (el tipo de cambio apenas se movió): etiquetas separadas.
    desfase = {"remesas_usd": -9, "remesas_gtq": 9, "remesas_gtq_reales": 0}
    for col, nombre, color in series:
        ax.plot(d.index, d[col], color=color, marker="o", markersize=4, label=nombre.replace("\n", " "))
        ax.annotate(f"{nombre}  {d[col].iloc[-1]:.0f}", (d.index[-1], d[col].iloc[-1]), xytext=(8, desfase[col]),
                    textcoords="offset points", va="center", fontsize=9, color=TEXTO)
    ax.set_xticks(d.index)
    ax.set_xlim(d.index[0] - 0.3, d.index[-1] + 3.2)
    ax.legend(loc="upper left", ncol=3, fontsize=9, bbox_to_anchor=(0, 1.08))
    guardar(fig, "04_dolares_vs_quetzales.png")


def pronostico(m: pd.DataFrame, pr: pd.DataFrame, r: dict):
    hist = m["remesas_usd"].dropna().iloc[-36:]
    p = r["pronostico_12m"]
    bajo, alto = p["p10"] / p["total"], p["p90"] / p["total"]
    fig, ax = lienzo(
        f"Pronóstico: ${p['total'] / 1e9:,.1f} mil millones en los próximos 12 meses",
        f"Remesas mensuales, millones de US$. Modelo: {r['modelo_elegido']} "
        f"(error promedio {r['mape_modelo_elegido']:.1%} en 10 años de validación)",
        "Fuente: Banco de Guatemala. La banda aplica a cada mes el rango 10-90 % de los errores "
        "históricos del total anual.")
    ax.fill_between(pr.index, pr["pronostico"] * bajo, pr["pronostico"] * alto, color=AZUL, alpha=0.15, lw=0,
                    label="Rango probable (10-90 %)")
    ax.plot(hist.index, hist, color=AZUL, label="Observado")
    ax.plot([hist.index[-1]] + list(pr.index), [hist.iloc[-1]] + list(pr["pronostico"]), color=AZUL,
            ls=(0, (4, 3)), label="Pronóstico")
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v / 1e6:,.0f}"))
    ax.set_ylim(hist.min() * 0.85, (pr["pronostico"] * alto).max() * 1.05)
    ax.legend(loc="upper left", ncol=3, fontsize=9)
    guardar(fig, "05_pronostico.png")


def modelos(t: pd.DataFrame):
    t = t.sort_values("mape", ascending=True)
    fig, ax = lienzo("El modelo con tendencia amortiguada fue el más preciso",
                     "Error porcentual absoluto medio mensual (MAPE) en 10 ventanas de 12 meses, 2016-2026. "
                     "Menor es mejor",
                     "Fuente: Banco de Guatemala. Validación con origen móvil: cada ventana se pronostica "
                     "solo con datos anteriores.", tam=(9.5, 4.6))
    fig.subplots_adjust(left=0.27, top=0.76)
    ax.grid(False)
    colores = [AZUL if i == 0 else GRIS for i in range(len(t))]
    ax.barh(range(len(t)), t["mape"], color=colores, height=0.6, edgecolor=SUPERFICIE, linewidth=2)
    ax.set_yticks(range(len(t)), t.index)
    ax.invert_yaxis()
    ax.xaxis.set_visible(False)
    for i, v in enumerate(t["mape"]):
        ax.text(v + 0.002, i, f"{v:.1%}", va="center", fontsize=9, color=TEXTO)
    guardar(fig, "06_validacion_modelos.png")


def main():
    FIG.mkdir(parents=True, exist_ok=True)
    m = pd.read_csv(PROC / "mensual.csv", index_col=0, parse_dates=True)
    a = pd.read_csv(PROC / "anual.csv", index_col=0)
    e = pd.read_csv(PROC / "estacionalidad.csv")
    ia = pd.read_csv(PROC / "interanual.csv", index_col=0, parse_dates=True)
    pr = pd.read_csv(PROC / "pronostico.csv", index_col=0, parse_dates=True)
    t = pd.read_csv(PROC / "modelos.csv", index_col=0)
    r = json.loads((PROC / "resumen.json").read_text())
    remesas_12m(m, a, r)
    estacionalidad(e)
    crecimiento_vs_empleo(ia, r)
    dolares_vs_quetzales(a)
    pronostico(m, pr, r)
    modelos(t)


if __name__ == "__main__":
    main()
