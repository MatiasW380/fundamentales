# Fundamentales

Dashboard del laboratorio de análisis fundamental de CEDEARs.

- Los datos (`data/estrategias.json`, `data/ranking.json`, `data/empresas.json`) los genera y sube la celda 4 del
  laboratorio en Colab (carpeta de Drive `Mi unidad/Colab Notebooks/FUNDAMENTALES`), en un solo commit.
- La página (`index.html`) es estática: Vercel la publica en cada commit, sin configuración extra.
- Fuente: balances 10-Q/10-K de la SEC (XBRL companyfacts), usando solo lo presentado hasta cada fecha; precios de Yahoo.

Pestañas: **Estrategias** (backtest neto de costos contra SPY y el universo, con período reservado),
**Ranking de hoy** (percentiles de valor y calidad, Piotroski, sorpresa de ganancias) y **Empresa** (trimestres y balance).
