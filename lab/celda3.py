# ======================= FUNDAMENTALES - CELDA 3: ESTRATEGIAS Y VEREDICTO =======================
# Cada fin de mes se ordenan las empresas por un puntaje (percentiles 0-1 dentro de las disponibles ese mes)
# y se compran las N mejores en partes iguales. Costos: COSTO_LADO por cada compra y cada venta.
# Se compara contra:
#   - SPY (lo que haría cualquiera sin analizar nada)
#   - el universo igual ponderado: todas las empresas de la lista, en partes iguales. Es la comparación importante,
#     porque la lista son empresas que HOY existen (sesgo de supervivencia): cualquier estrategia sobre ellas
#     parece buena mirando para atrás. Si no le gana al universo, el análisis no agregó nada.
# Aprobación (solo con el período de desarrollo, sin mirar el 25% final):
#   neto de costos le gana a SPY y al universo en las DOS mitades, y t >= T_MINIMO contra el universo.
from scipy.stats import norm, skew, kurtosis

P = PANEL.copy()
g = P.groupby(level="fecha")
def pct(col, asc=True):
    return g[col].rank(pct=True, ascending=asc)

R = pd.DataFrame({"ey": pct("ey"), "fcfy": pct("fcfy"), "bm": pct("bm"), "gpa": pct("gpa"), "roe": pct("roe"),
                  "apalanc": pct("apalanc", False), "accruals": pct("accruals", False)}, index=P.index)
P["valor"] = R[["ey", "fcfy", "bm"]].mean(axis=1).where(R[["ey", "fcfy", "bm"]].notna().sum(axis=1) >= 2)
P["calidad"] = R[["gpa", "roe", "apalanc", "accruals"]].mean(axis=1).where(R[["gpa", "roe", "apalanc", "accruals"]].notna().sum(axis=1) >= 3)
P["vc"] = (P.valor + P.calidad) / 2
P["piotroski"] = (P.fscore + P.valor).where((P.valor >= 0.6) & (P.fscore >= 7))
P["sorpresa"] = P.sue.where((P.dias_reporte <= 60) & (P.sue > 0))
P["momentum"] = P.mom

ESTRATEGIAS = {
    "Valor": ("valor", MESES_REBALANCEO),
    "Calidad": ("calidad", MESES_REBALANCEO),
    "Valor + calidad": ("vc", MESES_REBALANCEO),
    "Piotroski en baratas": ("piotroski", MESES_REBALANCEO),
    "Sorpresa de ganancias": ("sorpresa", tuple(range(1, 13))),
    "Momentum 12-1 (control)": ("momentum", MESES_REBALANCEO),
}

RET = P["ret"].unstack()
MESES = [d for d in RET.index if RET.loc[d].notna().any()]
SIG = {d: d + pd.offsets.MonthEnd(1) for d in MESES}           # el retorno de la fila d se cobra a fin del mes siguiente


def backtest(col, n, meses):
    cartera, filas, minimo = [], [], 5
    for d in MESES:
        costo = 0.0
        if d.month in meses or not cartera:
            s = P.loc[d, col].dropna()
            nueva = list(s.nlargest(n).index) if len(s) >= minimo else cartera
            if set(nueva) != set(cartera):
                w0 = {t: 1 / len(cartera) for t in cartera} if cartera else {}
                w1 = {t: 1 / len(nueva) for t in nueva} if nueva else {}
                costo = sum(abs(w1.get(t, 0) - w0.get(t, 0)) for t in set(w0) | set(w1)) * COSTO_LADO
                cartera = nueva
        bruto = RET.loc[d, cartera].fillna(0).mean() if cartera else 0.0
        filas.append((SIG[d], bruto - costo, bruto, costo, len(cartera), ",".join(cartera)))
    return pd.DataFrame(filas, columns=["fecha", "neto", "bruto", "costo", "n", "cartera"]).set_index("fecha")


spy_m = AJ_M["SPY"].pct_change(fill_method=None).shift(-1).reindex(MESES)
BENCH = pd.DataFrame({"SPY": spy_m.values,
                      "Universo": [RET.loc[d].drop(labels=["SPY", "^IRX"], errors="ignore").dropna().mean() for d in MESES]},
                     index=[SIG[d] for d in MESES])
RF = RF_M.reindex(MESES).fillna(0).values
RF = pd.Series(RF, index=BENCH.index)

n_meses = len(BENCH)
corte = BENCH.index[int(n_meses * (1 - RESERVA))]
mitad = BENCH.index[int(n_meses * (1 - RESERVA) / 2)]
PERIODO = pd.Series(np.where(BENCH.index >= corte, "reserva", np.where(BENCH.index < mitad, "dev1", "dev2")), index=BENCH.index)
print(f"Meses: {n_meses} ({BENCH.index[0]:%Y-%m} a {BENCH.index[-1]:%Y-%m}) | desarrollo 1 hasta {mitad:%Y-%m} | "
      f"desarrollo 2 hasta {corte:%Y-%m} | reserva desde {corte:%Y-%m}")


def anual(r):
    r = r.dropna()
    return (1 + r).prod() ** (12 / len(r)) - 1 if len(r) else np.nan


def max_caida(r):
    v = (1 + r.fillna(0)).cumprod()
    return (v / v.cummax() - 1).min()


def t_stat(x):
    x = x.dropna()
    return x.mean() / x.std() * np.sqrt(len(x)) if len(x) > 2 and x.std() > 0 else np.nan


def sharpe_deflactado(sr, sr_todos, n_obs, sesgo, curt):
    """López de Prado: probabilidad de que el Sharpe (mensual) sea real habiendo probado len(sr_todos) variantes."""
    N = len(sr_todos)
    if N < 2 or n_obs < 3:
        return np.nan
    gamma = 0.5772156649
    sr0 = np.std(sr_todos, ddof=1) * ((1 - gamma) * norm.ppf(1 - 1 / N) + gamma * norm.ppf(1 - 1 / (N * np.e)))
    den = np.sqrt(max(1e-12, 1 - sesgo * sr + (curt - 1) / 4 * sr ** 2))
    return float(norm.cdf((sr - sr0) * np.sqrt(n_obs - 1) / den))


RES, filas = {}, []
for nombre, (col, meses) in ESTRATEGIAS.items():
    for n in TOPS:
        clave = f"{nombre} | top {n}"
        bt = backtest(col, n, meses)
        RES[clave] = bt
        r, b = bt.neto, BENCH
        dev = PERIODO != "reserva"
        fila = dict(estrategia=nombre, top=n, clave=clave,
                    anual_dev=anual(r[dev]), spy_dev=anual(b.SPY[dev]), univ_dev=anual(b.Universo[dev]),
                    vs_spy_1=anual(r[PERIODO == "dev1"]) - anual(b.SPY[PERIODO == "dev1"]),
                    vs_spy_2=anual(r[PERIODO == "dev2"]) - anual(b.SPY[PERIODO == "dev2"]),
                    vs_univ_1=anual(r[PERIODO == "dev1"]) - anual(b.Universo[PERIODO == "dev1"]),
                    vs_univ_2=anual(r[PERIODO == "dev2"]) - anual(b.Universo[PERIODO == "dev2"]),
                    t_univ=t_stat((r - b.Universo)[dev]),
                    sharpe_dev=((r - RF)[dev].mean() / (r - RF)[dev].std() * np.sqrt(12)),
                    caida_dev=max_caida(r[dev]),
                    rotacion=bt.costo[dev].sum() / COSTO_LADO / (dev.sum() / 12) / 2,
                    costo_anual=bt.costo[dev].sum() / (dev.sum() / 12))
        filas.append(fila)
TAB = pd.DataFrame(filas)

# Sharpe deflactado sobre el exceso contra el universo (mensual), contando todas las variantes probadas
activos = {k: (RES[k].neto - BENCH.Universo)[PERIODO != "reserva"] for k in RES}
sr_todos = [a.mean() / a.std() for a in activos.values() if a.std() > 0]
TAB["sharpe_defl"] = [sharpe_deflactado(a.mean() / a.std(), sr_todos, len(a), skew(a), kurtosis(a, fisher=False))
                      if a.std() > 0 else np.nan for a in activos.values()]
TAB["aprobada"] = ((TAB.vs_spy_1 > 0) & (TAB.vs_spy_2 > 0) & (TAB.vs_univ_1 > 0) & (TAB.vs_univ_2 > 0) & (TAB.t_univ >= T_MINIMO))

pd.set_option("display.width", 200)
print("\nPERÍODO DE DESARROLLO, neto de costos (anual):")
print(f"  SPY {anual(BENCH.SPY[PERIODO != 'reserva']):+.1%} | universo igual ponderado {anual(BENCH.Universo[PERIODO != 'reserva']):+.1%}")
print(TAB.drop(columns=["clave", "spy_dev", "univ_dev"]).to_string(index=False, formatters={
    "anual_dev": "{:+.1%}".format, "vs_spy_1": "{:+.1%}".format, "vs_spy_2": "{:+.1%}".format,
    "vs_univ_1": "{:+.1%}".format, "vs_univ_2": "{:+.1%}".format, "t_univ": "{:+.2f}".format,
    "sharpe_dev": "{:.2f}".format, "caida_dev": "{:.0%}".format, "rotacion": "{:.0%}".format,
    "costo_anual": "{:.2%}".format, "sharpe_defl": "{:.2f}".format}))

aprob = TAB[TAB.aprobada]
print(f"\nAprobadas en desarrollo: {len(aprob)} de {len(TAB)}")
if len(aprob):
    print("\nPERÍODO RESERVADO (se mira una sola vez):")
    res = PERIODO == "reserva"
    for f in aprob.itertuples():
        r = RES[f.clave].neto[res]
        a_s, a_u = anual(r) - anual(BENCH.SPY[res]), anual(r) - anual(BENCH.Universo[res])
        print(f"  {f.clave:38s} anual {anual(r):+.1%} | vs SPY {a_s:+.1%} | vs universo {a_u:+.1%} | "
              f"{'SIGUE FUNCIONANDO' if a_s > 0 and a_u > 0 else 'FALLA'}")
else:
    print("Ninguna supera los filtros: no se abre el período reservado.")

VEREDICTO = {}
res = PERIODO == "reserva"
for f in TAB.itertuples():
    r = RES[f.clave].neto[res]
    VEREDICTO[f.clave] = ("aprobada y confirmada" if f.aprobada and anual(r) > max(anual(BENCH.SPY[res]), anual(BENCH.Universo[res]))
                          else "aprobada pero falla en reserva" if f.aprobada else "no aprobada")
TAB["veredicto"] = TAB.clave.map(VEREDICTO)
TAB.to_csv(os.path.join(DIR, "resumen_estrategias.csv"), index=False)
print(f"\nVariantes probadas: {len(TAB)}. Sesgo de supervivencia: la lista son empresas vivas hoy; por eso la vara es el universo.")
print(f"Guardado en {DIR}/resumen_estrategias.csv")
