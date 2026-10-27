# ======================= FUNDAMENTALES - CELDA 2: TRIMESTRES "COMO SE CONOCÍAN" Y PANEL MENSUAL =======================
# Regla de oro: en cada fecha del pasado solo se usa lo que ya estaba presentado en la SEC ese día.
#   - Cada dato guarda la fecha de presentación ORIGINAL (si después se corrigió, se usa el valor original).
#   - Un dato presentado el día X se puede usar recién desde el día X+1.
#   - Los trimestres se arman como en la web de SPCX: si la empresa informa acumulado del año, trimestre = acumulado - acumulado anterior.
# Resultado: PANEL, una fila por empresa y fin de mes, con ratios, puntaje Piotroski, sorpresa de ganancias y el retorno del mes siguiente.
UN_DIA = np.timedelta64(1, "D")


def _dias(a, b):
    return (np.datetime64(b, "D") - np.datetime64(a, "D")).astype(int)


class Serie:
    """Fechas de cierre, valores y fecha desde la que se puede usar cada dato. Ordenada por cierre."""
    def __init__(self, d):
        ks = sorted(d)
        self.fin = np.array(ks, dtype="datetime64[D]")
        self.val = np.array([d[k][0] for k in ks], dtype=float)
        self.disp = np.array([d[k][1] for k in ks], dtype="datetime64[D]") + UN_DIA

    def __len__(self):
        return len(self.fin)


def originales(filas, con_inicio):
    """Para cada período se queda con la primera presentación (y, si empatan, con el concepto preferido)."""
    o = {}
    for prio, s, e, v, f in filas:
        if con_inicio and not s:
            continue
        k = (s, e) if con_inicio else e
        if k not in o or (f, prio) < (o[k][1], o[k][2]):
            o[k] = (v, f, prio)
    return o


def trimestral(filas):
    """{fin: (valor del trimestre, presentado)} a partir de trimestres y acumulados."""
    dur = {k: (v, f) for k, (v, f, _) in originales(filas, True).items()}
    q = {}
    for (s, e), (v, f) in dur.items():
        if 80 <= _dias(s, e) <= 100:
            q[e] = (v, f)
    por_inicio = {}
    for (s, e), (v, f) in dur.items():
        por_inicio.setdefault(s, []).append((e, v, f))
    for s, lst in por_inicio.items():
        lst.sort()
        for i in range(1, len(lst)):
            e, v, f = lst[i]
            if e in q or not (170 <= _dias(s, e) <= 375):
                continue
            pe, pv, pf = lst[i - 1]
            if 80 <= _dias(pe, e) <= 100:
                q[e] = (v - pv, max(f, pf))
    return q


def armar_empresa(t):
    datos = leer_sec(t)["datos"]
    F = {k: trimestral(datos.get(k, [])) for k in FLUJOS}
    # ganancia bruta: si no la informa, ventas - costo
    for e in set(F["ventas"]) & set(F["costo"]) - set(F["bruta"]):
        F["bruta"][e] = (F["ventas"][e][0] - F["costo"][e][0], max(F["ventas"][e][1], F["costo"][e][1]))
    # flujo libre = flujo operativo - inversiones en bienes de uso (si nunca informa inversiones, cuenta 0)
    F["fcf"] = {e: (v - F["capex"].get(e, (0.0, f))[0], max(f, F["capex"].get(e, (0, f))[1]))
                for e, (v, f) in F["flujo_op"].items() if e in F["capex"] or not F["capex"]}
    T = {k: Serie(v) for k, v in F.items() if k != "costo"}
    for k in SALDOS:
        T[k] = Serie({e: (v, f) for e, (v, f, _) in originales(datos.get(k, []), False).items()})
    # acciones en circulación: se suman las clases informadas en la misma presentación
    acc = {}
    for prio, accn, e, v, f in datos.get("acciones", []):
        k = (prio, accn or f, e)
        acc[k] = (acc.get(k, (0, f))[0] + v, f)
    mejor = {}
    for (prio, accn, e), (v, f) in acc.items():
        if (f, e) not in mejor or prio < mejor[(f, e)][0]:
            mejor[(f, e)] = (prio, v)
    orden = sorted(mejor)
    T["acc_disp"] = np.array([f for f, _ in orden], dtype="datetime64[D]") + UN_DIA
    T["acc_fecha"] = np.array([e for _, e in orden], dtype="datetime64[D]")
    T["acc_val"] = np.array([mejor[k][1] for k in orden], dtype=float)
    # splits de Yahoo: si hubo un split después de la fecha del conteo, las acciones se multiplican
    s = PRECIOS["splits"][t] if t in PRECIOS["splits"] else pd.Series(dtype=float)
    s = s[s.fillna(0) > 0]
    T["split_fecha"] = np.array(s.index.values, dtype="datetime64[D]")
    T["split_ratio"] = s.values.astype(float)
    return T


def ttm(S, D):
    """Suma de los últimos 4 trimestres conocidos al día D, y la de los 4 anteriores. También el cierre del último."""
    if S is None or not len(S):
        return np.nan, np.nan, None
    idx = np.flatnonzero(S.disp <= D)
    if len(idx) < 4:
        return np.nan, np.nan, None
    f = S.fin
    if not 250 <= (f[idx[-1]] - f[idx[-4]]).astype(int) <= 290:
        return np.nan, np.nan, f[idx[-1]]
    act = S.val[idx[-4:]].sum()
    ant = np.nan
    if len(idx) >= 8 and 250 <= (f[idx[-5]] - f[idx[-8]]).astype(int) <= 290 and 340 <= (f[idx[-1]] - f[idx[-5]]).astype(int) <= 390:
        ant = S.val[idx[-8:-4]].sum()
    return act, ant, f[idx[-1]]


def saldo(S, D):
    """Último saldo conocido y el de un año antes (±45 días)."""
    if S is None or not len(S):
        return np.nan, np.nan
    idx = np.flatnonzero(S.disp <= D)
    if not len(idx):
        return np.nan, np.nan
    ult = idx[-1]
    objetivo = S.fin[ult] - np.timedelta64(365, "D")
    previos = idx[:-1]
    ant = np.nan
    if len(previos):
        dist = np.abs((S.fin[previos] - objetivo).astype(int))
        j = np.argmin(dist)
        if dist[j] <= 45:
            ant = S.val[previos[j]]
    return S.val[ult], ant


def sorpresa(S, D):
    """Sorpresa estandarizada: (ganancia del último trimestre - la del mismo trimestre del año anterior),
    dividida por la variabilidad de esas diferencias en los 8 trimestres previos. Devuelve también los días desde el reporte."""
    if S is None or not len(S):
        return np.nan, np.nan
    idx = np.flatnonzero(S.disp <= D)
    if len(idx) < 9:
        return np.nan, np.nan
    fin, val = S.fin[idx], S.val[idx]
    pos = np.searchsorted(fin, fin - np.timedelta64(365, "D"))
    difs = np.full(len(fin), np.nan)
    for i, p in enumerate(pos):
        for c in (p - 1, p):
            if 0 <= c < i and abs((fin[i] - fin[c]).astype(int) - 365) <= 20:
                difs[i] = val[i] - val[c]
    previas = difs[-9:-1]
    previas = previas[~np.isnan(previas)]
    dias = (np.datetime64(D, "D") - S.disp[idx[-1]]).astype(int)
    if np.isnan(difs[-1]) or len(previas) < 4 or previas.std() == 0:
        return np.nan, dias
    return difs[-1] / previas.std(), dias


def acciones(T, D, atras=0):
    lim = np.datetime64(D, "D") - np.timedelta64(atras, "D")
    i = np.searchsorted(T["acc_disp"], lim, side="right") - 1
    if i < 0:
        return np.nan
    m = (T["split_fecha"] > T["acc_fecha"][i]) & (T["split_fecha"] <= np.datetime64(D, "D"))   # todo expresado en acciones de hoy (D)
    return T["acc_val"][i] * np.prod(T["split_ratio"][m])


def rasgos(T, D, precio):
    D = np.datetime64(D, "D")
    r = {}
    for k in ("ventas", "bruta", "operativo", "neto", "flujo_op", "fcf"):
        r[k], r[k + "_ant"], fin = ttm(T.get(k), D)
        if k == "neto":
            r["ultimo_cierre"] = fin
    for k in SALDOS:
        r[k], r[k + "_ant"] = saldo(T.get(k), D)
    r["sue"], r["dias_reporte"] = sorpresa(T.get("neto"), D)
    r["acciones"], r["acciones_ant"] = acciones(T, D), acciones(T, D, 365)
    # frescura: el último trimestre conocido debe haber cerrado hace menos de 200 días
    r["fresco"] = r["ultimo_cierre"] is not None and (D - r["ultimo_cierre"]).astype(int) <= 200
    r["precio"] = precio
    mc = precio * r["acciones"] if precio and precio > 0 else np.nan
    r["mktcap"] = mc if 5e7 < (mc if mc == mc else 0) < 8e12 else np.nan
    mc, eq, a = r["mktcap"], r["patrimonio"], r["activo"]
    r["ey"] = r["neto"] / mc
    r["fcfy"] = r["fcf"] / mc
    r["bm"] = eq / mc
    r["sy"] = r["ventas"] / mc
    r["gpa"] = r["bruta"] / a if a and a > 0 else np.nan
    eq_med = np.nanmean([eq, r["patrimonio_ant"]]) if eq == eq else np.nan
    r["roe"] = r["neto"] / eq_med if eq_med == eq_med and eq_med > 0 else np.nan
    r["apalanc"] = r["pasivo"] / a if a and a > 0 else np.nan
    r["accruals"] = (r["neto"] - r["flujo_op"]) / a if a and a > 0 else np.nan
    r["crec"] = r["ventas"] / r["ventas_ant"] - 1 if r["ventas_ant"] and r["ventas_ant"] > 0 else np.nan
    r["margen_bruto"] = r["bruta"] / r["ventas"] if r["ventas"] and r["ventas"] > 0 else np.nan
    r["margen_op"] = r["operativo"] / r["ventas"] if r["ventas"] and r["ventas"] > 0 else np.nan
    r["fscore"] = piotroski(r)
    return r


def piotroski(r):
    def div(a, b):
        return a / b if b and b == b and b != 0 and a == a else np.nan
    pruebas = [
        (r["neto"] > 0) if r["neto"] == r["neto"] else None,
        (r["flujo_op"] > 0) if r["flujo_op"] == r["flujo_op"] else None,
    ]
    roa, roa_a = div(r["neto"], r["activo"]), div(r["neto_ant"], r["activo_ant"])
    pruebas.append(roa > roa_a if roa == roa and roa_a == roa_a else None)
    pruebas.append(r["flujo_op"] > r["neto"] if r["flujo_op"] == r["flujo_op"] and r["neto"] == r["neto"] else None)
    d, d_a = r["deuda_lp"] if r["deuda_lp"] == r["deuda_lp"] else 0, r["deuda_lp_ant"] if r["deuda_lp_ant"] == r["deuda_lp_ant"] else 0
    lev, lev_a = div(d, r["activo"]), div(d_a, r["activo_ant"])
    pruebas.append(lev <= lev_a if lev == lev and lev_a == lev_a else None)
    cr, cr_a = div(r["activo_cte"], r["pasivo_cte"]), div(r["activo_cte_ant"], r["pasivo_cte_ant"])
    pruebas.append(cr > cr_a if cr == cr and cr_a == cr_a else None)
    pruebas.append(r["acciones"] <= r["acciones_ant"] * 1.01 if r["acciones"] == r["acciones"] and r["acciones_ant"] == r["acciones_ant"] else None)
    mb, mb_a = div(r["bruta"], r["ventas"]), div(r["bruta_ant"], r["ventas_ant"])
    pruebas.append(mb > mb_a if mb == mb and mb_a == mb_a else None)
    at, at_a = div(r["ventas"], r["activo"]), div(r["ventas_ant"], r["activo_ant"])
    pruebas.append(at > at_a if at == at and at_a == at_a else None)
    validas = [p for p in pruebas if p is not None]
    return float(sum(validas)) if len(validas) >= 7 else np.nan


# ----------------------------- precios mensuales -----------------------------
def a_fin_de_mes(df):
    try:
        return df.resample("ME").last()
    except ValueError:
        return df.resample("M").last()


aj = PRECIOS["ajustado"]
ci = PRECIOS["cierre"]
sp = PRECIOS["splits"].reindex(index=ci.index, columns=ci.columns).fillna(0).replace(0, 1.0)
# Yahoo devuelve el cierre ya corregido por splits; para multiplicar por las acciones de la SEC hace falta el precio real de ese día
factor = sp.iloc[::-1].cumprod().iloc[::-1].shift(-1).fillna(1.0)
CRUDO_M = a_fin_de_mes(ci * factor)
AJ_M = a_fin_de_mes(aj)
RET_SIG = AJ_M.pct_change(fill_method=None).shift(-1)          # retorno del mes siguiente (lo que gana quien compra a fin de mes)
MOM = AJ_M.shift(1) / AJ_M.shift(12) - 1                       # momentum 12-1
RF_M = (AJ_M["^IRX"].shift(0) / 100 / 12) if "^IRX" in AJ_M else pd.Series(0.0, index=AJ_M.index)

EMPRESAS, t0 = {}, time.time()
for t in INFO:
    try:
        EMPRESAS[t] = armar_empresa(t)
    except Exception as e:
        print(f"  {t}: no se pudo armar ({e})")
print(f"Trimestres armados: {len(EMPRESAS)} empresas ({time.time() - t0:.0f}s)")

FECHAS = [d for d in AJ_M.index if d >= pd.Timestamp("2010-06-30") and d < AJ_M.index[-1]]
filas = []
for t, T in EMPRESAS.items():
    if t not in CRUDO_M:
        continue
    for D in FECHAS:
        p = CRUDO_M.at[D, t]
        if not (p == p and p > 0):
            continue
        r = rasgos(T, D, float(p))
        if not r["fresco"]:
            continue
        r.update(fecha=D, ticker=t, mom=MOM.at[D, t], ret=RET_SIG.at[D, t])
        filas.append(r)
PANEL = pd.DataFrame(filas).set_index(["fecha", "ticker"]).sort_index()
PANEL.drop(columns=["ultimo_cierre", "fresco"], inplace=True)
PANEL.to_pickle(os.path.join(DIR, "panel.pkl"))
n_mes = PANEL.groupby(level="fecha").size()
print(f"Panel: {len(PANEL):,} filas | {PANEL.index.get_level_values(0).nunique()} meses "
      f"({FECHAS[0]:%Y-%m} a {FECHAS[-1]:%Y-%m}) | empresas por mes: mín {n_mes.min()}, mediana {int(n_mes.median())}, máx {n_mes.max()}")
print("Datos disponibles (% de filas):",
      ", ".join(f"{c} {PANEL[c].notna().mean():.0%}" for c in ("ey", "fcfy", "bm", "gpa", "roe", "fscore", "sue", "mktcap")))
