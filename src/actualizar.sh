#!/usr/bin/env bash
# Corre todo el flujo: descarga -> análisis -> gráficas.
set -euo pipefail
cd "$(dirname "$0")/.."
PY="${PYTHON:-.venv/bin/python}"
"$PY" -W ignore src/descargar.py
"$PY" -W ignore src/analisis.py > /dev/null
"$PY" src/graficas.py
