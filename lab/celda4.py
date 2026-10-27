# ======================= FUNDAMENTALES - CELDA 4: MONITOR DE HOY Y PUBLICACIÓN EN EL DASHBOARD =======================
# Calcula los puntajes con lo presentado hasta hoy, arma el ranking y los datos por empresa,
# y los sube al repo MatiasW380/fundamentales (carpeta data/) en un solo commit. Vercel lo publica solo.
# Si no está el secreto GITHUB_TOKEN, deja los archivos en Drive (FUNDAMENTALES/dashboard) para subirlos a mano.
HOY = pd.Timestamp.today().normalize()
ult_crudo = (ci * factor).ffill().iloc[-1]
mom_hoy = AJ_M.shift(1).iloc[-1] / AJ_M.shift(12).iloc[-1] - 1

filas = []
for t, T in EMPRESAS.items():
    p = ult_crudo.get(t, np.nan)
    if not (p == p and p > 0):
        continue
    r = rasgos(T, HOY, float(p))
    if not r["fresco"]:
        continue
    r.update(ticker=t, mom=mom_hoy.get(t, np.nan), ultimo_cierre=str(r["ultimo_cierre"]))
    filas.append(r)
H = pd.DataFrame(filas).set_index("ticker")

def pct_h(c, asc=True):
    return H[c].rank(pct=True, ascending=asc)
Rh = pd.DataFrame({"ey": pct_h("ey"), "fcfy": pct_h("fcfy"), "bm": pct_h("bm"), "gpa": pct_h("gpa"), "roe": pct_h("roe"),
                   "apalanc": pct_h("apalanc", False), "accruals": pct_h("accruals", False)})
H["valor"] = Rh[["ey", "fcfy", "bm"]].mean(axis=1).where(Rh[["ey", "fcfy", "bm"]].notna().sum(axis=1) >= 2)
H["calidad"] = Rh[["gpa", "roe", "apalanc", "accruals"]].mean(axis=1).where(Rh[["gpa", "roe", "apalanc", "accruals"]].notna().sum(axis=1) >= 3)
H["vc"] = (H.valor + H.calidad) / 2
H["piotroski"] = (H.fscore + H.valor).where((H.valor >= 0.6) & (H.fscore >= 7))
H["sorpresa"] = H.sue.where((H.dias_reporte <= 60) & (H.sue > 0))
H["momentum"] = H.mom

ELEGIDAS = {nombre: list(H[col].dropna().nlargest(MONITOR_N).index) for nombre, (col, _) in ESTRATEGIAS.items()}
for nombre, lst in ELEGIDAS.items():
    print(f"{nombre:26s}: {', '.join(lst) if lst else '(ninguna cumple hoy)'}")


# ----------------------------- armado de los JSON -----------------------------
def limpio(x, dec=4):
    if x is None:
        return None
    if isinstance(x, (np.floating, float)):
        return None if not np.isfinite(x) else round(float(x), dec)
    if isinstance(x, (np.integer,)):
        return int(x)
    return x


def curva(r):
    return [limpio(v, 4) for v in (1 + r.fillna(0)).cumprod().values]


estrategias_json = {
    "generado": pd.Timestamp.now(tz="America/Argentina/Buenos_Aires").strftime("%Y-%m-%d %H:%M"),
    "parametros": {"costo_lado": COSTO_LADO, "comision_lado": COMISION_LADO, "reserva": RESERVA, "tops": list(TOPS),
                   "meses_rebalanceo": list(MESES_REBALANCEO), "t_minimo": T_MINIMO, "empresas": len(EMPRESAS)},
    "periodos": {"inicio": f"{BENCH.index[0]:%Y-%m}", "mitad": f"{mitad:%Y-%m}", "reserva": f"{corte:%Y-%m}", "fin": f"{BENCH.index[-1]:%Y-%m}"},
    "fechas": [f"{d:%Y-%m}" for d in BENCH.index],
    "referencias": {"SPY": curva(BENCH.SPY), "Universo": curva(BENCH.Universo)},
    "curvas": {k: curva(v.neto) for k, v in RES.items()},
    "tabla": [],
}
res = PERIODO == "reserva"
for f in TAB.itertuples():
    bt = RES[f.clave]
    estrategias_json["tabla"].append({
        "clave": f.clave, "estrategia": f.estrategia, "top": int(f.top),
        "anual_dev": limpio(f.anual_dev), "vs_spy_1": limpio(f.vs_spy_1), "vs_spy_2": limpio(f.vs_spy_2),
        "vs_univ_1": limpio(f.vs_univ_1), "vs_univ_2": limpio(f.vs_univ_2), "t_univ": limpio(f.t_univ, 2),
        "sharpe_dev": limpio(f.sharpe_dev, 2), "caida_dev": limpio(f.caida_dev), "rotacion": limpio(f.rotacion, 2),
        "costo_anual": limpio(f.costo_anual), "sharpe_defl": limpio(f.sharpe_defl, 2),
        "anual_reserva": limpio(anual(bt.neto[res])), "spy_reserva": limpio(anual(BENCH.SPY[res])),
        "univ_reserva": limpio(anual(BENCH.Universo[res])), "aprobada": bool(f.aprobada), "veredicto": f.veredicto,
        "cartera_actual": bt.cartera.iloc[-1].split(",") if bt.cartera.iloc[-1] else [],
    })
estrategias_json["referencias_anual"] = {
    "dev": {"SPY": limpio(anual(BENCH.SPY[~res])), "Universo": limpio(anual(BENCH.Universo[~res]))},
    "reserva": {"SPY": limpio(anual(BENCH.SPY[res])), "Universo": limpio(anual(BENCH.Universo[res]))},
}

COLS = ["precio", "mktcap", "ey", "fcfy", "bm", "gpa", "roe", "apalanc", "accruals", "crec", "margen_bruto", "margen_op",
        "fscore", "sue", "dias_reporte", "valor", "calidad", "vc", "momentum", "ventas", "neto", "fcf", "ultimo_cierre"]
ranking_json = {"fecha": f"{HOY:%Y-%m-%d}", "top_n": MONITOR_N, "elegidas": ELEGIDAS, "filas": []}
for t, r in H.iterrows():
    fila = {"ticker": t, "nombre": INFO[t]["nombre"], "en": [k for k, v in ELEGIDAS.items() if t in v]}
    fila.update({c: limpio(r.get(c)) if c != "ultimo_cierre" else r.get(c) for c in COLS})
    ranking_json["filas"].append(fila)

historia = P[["valor", "calidad"]].unstack()
empresas_json = {}
for t, T in EMPRESAS.items():
    if t not in H.index:
        continue
    trim = {}
    for k in ("ventas", "bruta", "operativo", "neto", "flujo_op", "fcf"):
        S = T.get(k)
        if S is None or not len(S):
            continue
        for e, v in zip(S.fin[-12:], S.val[-12:]):
            trim.setdefault(str(e), {})[k] = limpio(v, 0)
    bal = {}
    for k in ("activo", "pasivo", "patrimonio", "caja", "deuda_lp"):
        S = T.get(k)
        if S is None or not len(S):
            continue
        for e, v in zip(S.fin[-8:], S.val[-8:]):
            bal.setdefault(str(e), {})[k] = limpio(v, 0)
    hv = historia["valor"][t].dropna().iloc[-36:] if t in historia["valor"] else pd.Series(dtype=float)
    hc = historia["calidad"][t].reindex(hv.index) if t in historia["calidad"] else pd.Series(dtype=float)
    empresas_json[t] = {
        "nombre": INFO[t]["nombre"], "cik": INFO[t]["cik"],
        "trimestres": [{"fin": e, **v} for e, v in sorted(trim.items())][-12:],
        "balance": [{"fin": e, **v} for e, v in sorted(bal.items())][-8:],
        "historia": {"fechas": [f"{d:%Y-%m}" for d in hv.index], "valor": [limpio(x, 3) for x in hv.values],
                     "calidad": [limpio(x, 3) for x in hc.values]},
    }

ARCHIVOS = {
    "data/estrategias.json": json.dumps(estrategias_json, ensure_ascii=False, separators=(",", ":")),
    "data/ranking.json": json.dumps(ranking_json, ensure_ascii=False, separators=(",", ":")),
    "data/empresas.json": json.dumps(empresas_json, ensure_ascii=False, separators=(",", ":")),
}
os.makedirs(os.path.join(DIR, "dashboard", "data"), exist_ok=True)
for ruta, txt in ARCHIVOS.items():
    open(os.path.join(DIR, "dashboard", ruta), "w", encoding="utf-8").write(txt)
tamanos = ", ".join("%s %.0f KB" % (k.split("/")[-1], len(v) / 1024) for k, v in ARCHIVOS.items())
print(f"\nArchivos guardados en {DIR}/dashboard/data ({tamanos})")


# ----------------------------- publicación en GitHub (un solo commit) -----------------------------
def publicar(archivos):
    tok = secreto("GITHUB_TOKEN")
    if not tok:
        print("No está el secreto GITHUB_TOKEN: subí a mano la carpeta dashboard/data al repo."); return
    api = f"https://api.github.com/repos/{GITHUB_REPO}"
    H_ = {"Authorization": f"Bearer {tok}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    def pedir(metodo, ruta, **kw):
        r = requests.request(metodo, api + ruta, headers=H_, timeout=60, **kw)
        if r.status_code >= 300:
            raise RuntimeError(f"GitHub {r.status_code} en {ruta}: {r.text[:300]}")
        return r.json()
    base = pedir("GET", f"/git/ref/heads/{GITHUB_RAMA}")["object"]["sha"]
    arbol_base = pedir("GET", f"/git/commits/{base}")["tree"]["sha"]
    arbol = pedir("POST", "/git/trees", json={"base_tree": arbol_base, "tree": [
        {"path": p, "mode": "100644", "type": "blob", "content": c} for p, c in archivos.items()]})["sha"]
    commit = pedir("POST", "/git/commits", json={"message": f"Datos fundamentales {HOY:%Y-%m-%d}", "tree": arbol,
                                                 "parents": [base]})["sha"]
    pedir("PATCH", f"/git/refs/heads/{GITHUB_RAMA}", json={"sha": commit})
    print(f"Publicado en GitHub ({commit[:7]}). Vercel actualiza el dashboard en un minuto.")


publicar(ARCHIVOS)
