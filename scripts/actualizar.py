"""Actualiza el dashboard de momentum. Lo corre GitHub Actions todos los días hábiles; también se puede correr a mano.

Regla (la única que pasó las pruebas del laboratorio fundamental):
  - Universo: los CEDEARs de config.json.
  - Al cierre del último día hábil de febrero, mayo, agosto y noviembre se eligen las `top` acciones que más
    subieron en los 12 meses anteriores sin contar el último mes (momentum 12-1), en partes iguales.
  - Se mantienen hasta la próxima revisión.

Escribe:
  data/momentum.json  cartera vigente, cambios, candidatas, historia simulada contra SPY
  data/fichas.json    balances trimestrales de la SEC de las empresas en cartera y candidatas (si hay SEC_USER_AGENT)
Si cambió la cartera y hay GITHUB_TOKEN, abre un issue en el repo para que llegue el aviso por mail.
"""
import json
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import requests

RAIZ = Path(__file__).resolve().parents[1]
DATA = RAIZ / "data"
DATA.mkdir(exist_ok=True)
CFG = json.loads((RAIZ / "config.json").read_text(encoding="utf-8"))
TOP = int(CFG["top"])
MESES = list(CFG["meses_revision"])
COSTO = float(CFG["costo_lado"])
INICIO = pd.Timestamp(CFG["inicio"])
N_CAND = int(CFG.get("candidatas", 25))
CEDEARS = list(dict.fromkeys(CFG["cedears"]))
SEC_UA = os.environ.get("SEC_USER_AGENT", "").strip()
GH_TOKEN = os.environ.get("GITHUB_TOKEN", "").strip()
GH_REPO = os.environ.get("GITHUB_REPOSITORY", "MatiasW380/fundamentales")
AHORA = datetime.now(timezone.utc)
SES = requests.Session()


def log(*a):
    print("[actualizar]", *a, file=sys.stderr, flush=True)


def leer(nombre, defecto):
    p = DATA / nombre
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return defecto


def guardar(nombre, obj):
    (DATA / nombre).write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def r4(x, d=4):
    if x is None:
        return None
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return round(x, d) if np.isfinite(x) else None


# ============================================================ precios (Yahoo, velas mensuales)
def yahoo_mensual(t, intentos=3):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{t}"
    params = {"range": "max", "interval": "1mo", "events": "div,splits", "includeAdjustedClose": "true"}
    ultimo = None
    for k in range(intentos):
        try:
            r = SES.get(url, params=params, timeout=30, headers={"User-Agent": "Mozilla/5.0 (fundamentales)"})
            if r.status_code == 200:
                res = (r.json().get("chart") or {}).get("result") or []
                if not res:
                    return None
                res = res[0]
                ts = res.get("timestamp") or []
                adj = (((res.get("indicators") or {}).get("adjclose") or [{}])[0]).get("adjclose") or []
                if not ts or not adj:
                    return None
                idx = pd.to_datetime(ts, unit="s").to_period("M").to_timestamp("M")
                s = pd.Series(adj, index=idx, dtype=float).dropna()
                s = s[~s.index.duplicated(keep="last")]
                meta = res.get("meta") or {}
                return {"serie": s, "precio": meta.get("regularMarketPrice"),
                        "fecha": meta.get("regularMarketTime")}
            ultimo = r.status_code
            if r.status_code == 404:
                return None
        except requests.RequestException as e:
            ultimo = repr(e)
        time.sleep(2 * (k + 1))
    log(f"{t}: Yahoo falló ({ultimo})")
    return None


def bajar_precios():
    series, info = {}, {}
    for i, t in enumerate(CEDEARS + ["SPY"]):
        d = yahoo_mensual(t)
        if d is not None and len(d["serie"]) >= 3:
            series[t] = d["serie"]
            info[t] = d
        time.sleep(0.15)
        if (i + 1) % 40 == 0:
            log(f"precios {i + 1}/{len(CEDEARS) + 1}")
    if "SPY" not in series or len(series) < TOP + 5:
        raise SystemExit("Yahoo no devolvió precios suficientes; no se toca nada.")
    return pd.DataFrame(series).sort_index(), info


# ============================================================ estrategia
def ultimo_habil(fin_mes):
    d = fin_mes
    while d.weekday() >= 5:
        d -= pd.Timedelta(days=1)
    return d


def simular(A, completos):
    """Recorre los meses completos: elige en los meses de revisión, cobra el retorno del mes siguiente."""
    mom = A.shift(1) / A.shift(12) - 1
    ret = A.pct_change(fill_method=None).shift(-1)
    meses = [d for d in completos if d >= INICIO]
    cartera, historial, filas = [], [], []
    for d in meses:
        costo = 0.0
        if d.month in MESES or not cartera:
            m = mom.loc[d, CEDEARS_OK].dropna()
            m = m[A.loc[d, m.index].notna()]
            if len(m) >= TOP:
                nueva = list(m.nlargest(TOP).index)
                if set(nueva) != set(cartera):
                    w0 = {t: 1 / len(cartera) for t in cartera} if cartera else {}
                    w1 = {t: 1 / len(nueva) for t in nueva}
                    costo = sum(abs(w1.get(t, 0) - w0.get(t, 0)) for t in set(w0) | set(w1)) * COSTO
                cartera = nueva
                historial.append({"fecha": f"{d:%Y-%m-%d}", "tickers": nueva,
                                  "momentum": {t: r4(m[t]) for t in nueva}})
        univ = ret.loc[d, CEDEARS_OK][A.loc[d, CEDEARS_OK].notna() & mom.loc[d, CEDEARS_OK].notna()]
        filas.append({"fecha": d + pd.offsets.MonthEnd(1),
                      "estrategia": (ret.loc[d, cartera].fillna(0).mean() if cartera else 0.0) - costo,
                      "spy": ret.loc[d, "SPY"], "universo": univ.dropna().mean()})
    S = pd.DataFrame(filas).set_index("fecha").dropna(subset=["spy"])
    return S, historial, mom


def anual(r):
    r = r.dropna()
    return (1 + r).prod() ** (12 / len(r)) - 1 if len(r) else None


def caida(r):
    v = (1 + r.fillna(0)).cumprod()
    return (v / v.cummax() - 1).min()


# ============================================================ SEC (fichas de las empresas)
def sec_get(url):
    for k in range(3):
        try:
            r = SES.get(url, timeout=60, headers={"User-Agent": SEC_UA, "Accept-Encoding": "gzip, deflate"})
            if r.status_code == 200:
                time.sleep(0.12)
                return r.json()
            if r.status_code == 404:
                return None
        except requests.RequestException:
            pass
        time.sleep(2 * (k + 1))
    return None


FLUJOS = {
    "ventas": ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax",
               "RevenueFromContractWithCustomerIncludingAssessedTax", "SalesRevenueNet"],
    "bruta": ["GrossProfit"],
    "operativo": ["OperatingIncomeLoss"],
    "neto": ["NetIncomeLoss", "ProfitLoss"],
    "flujo_op": ["NetCashProvidedByUsedInOperatingActivities"],
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment"],
}
SALDOS = {"activo": ["Assets"], "pasivo": ["Liabilities"], "patrimonio": ["StockholdersEquity"],
          "caja": ["CashAndCashEquivalentsAtCarryingValue"], "deuda_lp": ["LongTermDebtNoncurrent", "LongTermDebt"]}
FORMAS = {"10-Q", "10-K", "10-Q/A", "10-K/A"}


def _dias(a, b):
    return (date.fromisoformat(b) - date.fromisoformat(a)).days


def trimestral(entradas):
    """Valores por trimestre a partir de trimestres y acumulados del año (la última presentación manda)."""
    dur = {}
    for e in sorted(entradas, key=lambda e: e["filed"]):
        if e.get("start"):
            dur[(e["start"], e["end"])] = e["val"]
    q = {e: v for (s, e), v in dur.items() if 80 <= _dias(s, e) <= 100}
    por_inicio = {}
    for (s, e), v in dur.items():
        por_inicio.setdefault(s, []).append((e, v))
    for s, lst in por_inicio.items():
        lst.sort()
        for i in range(1, len(lst)):
            e, v = lst[i]
            if e in q or not 170 <= _dias(s, e) <= 375:
                continue
            pe, pv = lst[i - 1]
            if 80 <= _dias(pe, e) <= 100:
                q[e] = v - pv
    return q


def ficha(cik, nombre, precio):
    facts = sec_get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json")
    if not facts:
        return None
    gaap = (facts.get("facts") or {}).get("us-gaap") or {}
    dei = (facts.get("facts") or {}).get("dei") or {}

    def entradas(nombres):
        out = []
        for n in nombres:
            out += [e for e in ((gaap.get(n) or {}).get("units") or {}).get("USD", []) if e.get("form") in FORMAS]
        return out
    T = {k: trimestral(entradas(v)) for k, v in FLUJOS.items()}
    T["fcf"] = {e: v - T["capex"].get(e, 0) for e, v in T["flujo_op"].items()}
    fines = sorted(set().union(*[set(T[k]) for k in ("ventas", "neto", "fcf")]))[-12:]
    trimestres = [{"fin": e, **{k: r4(T[k].get(e), 0) for k in ("ventas", "bruta", "operativo", "neto", "fcf")}} for e in fines]
    bal = {}
    for k, nombres in SALDOS.items():
        for e in sorted(entradas(nombres), key=lambda e: e["filed"]):
            bal.setdefault(e["end"], {})[k] = e["val"]
    balance = [{"fin": e, **{k: r4(v, 0) for k, v in bal[e].items()}} for e in sorted(bal)[-8:]]
    # precio / ganancias de los últimos 12 meses
    pe = None
    netos = sorted(T["neto"].items())[-4:]
    acc = [e for e in ((dei.get("EntityCommonStockSharesOutstanding") or {}).get("units") or {}).get("shares", [])]
    if len(netos) == 4 and _dias(netos[0][0], netos[-1][0]) <= 290 and acc and precio:
        ult = max(e["filed"] for e in acc)
        acciones = sum(e["val"] for e in acc if e["filed"] == ult)
        ttm = sum(v for _, v in netos)
        pe = r4(precio * acciones / ttm, 1) if ttm > 0 else -1
    return {"nombre": nombre, "cik": cik, "pe": pe, "trimestres": trimestres, "balance": balance,
            "actualizado": f"{AHORA:%Y-%m-%d}"}


def actualizar_fichas(tickers, info):
    fichas = leer("fichas.json", {})
    if not SEC_UA:
        log("Sin SEC_USER_AGENT: no se actualizan las fichas de balances.")
        return fichas
    mapa = sec_get("https://www.sec.gov/files/company_tickers.json") or {}
    por_ticker = {v["ticker"].upper(): (int(v["cik_str"]), v["title"]) for v in mapa.values()}
    hace_una_semana = f"{AHORA - timedelta(days=7):%Y-%m-%d}"
    for t in tickers:
        if t in fichas and fichas[t].get("actualizado", "") >= hace_una_semana:
            continue
        if t.upper() not in por_ticker:
            continue
        cik, nombre = por_ticker[t.upper()]
        f = ficha(cik, nombre, (info.get(t) or {}).get("precio"))
        if f:
            fichas[t] = f
    return fichas


# ============================================================ aviso por mail (issue de GitHub)
def avisar(revision, salen, entran, cartera):
    if not GH_TOKEN:
        return
    dueño = GH_REPO.split("/")[0]
    cuerpo = (f"@{dueño} hay revisión de cartera ({revision}).\n\n"
              f"**Vender:** {', '.join(salen) or 'nada'}\n\n**Comprar:** {', '.join(entran) or 'nada'}\n\n"
              f"**Cartera nueva (partes iguales):** {', '.join(cartera)}\n\nDetalle en el dashboard.")
    try:
        r = SES.post(f"https://api.github.com/repos/{GH_REPO}/issues", timeout=30,
                     headers={"Authorization": f"Bearer {GH_TOKEN}", "Accept": "application/vnd.github+json"},
                     json={"title": f"Revisión de cartera {revision}: vender {len(salen)}, comprar {len(entran)}", "body": cuerpo})
        log("aviso:", r.status_code)
    except requests.RequestException as e:
        log("no se pudo avisar:", e)


# ============================================================ principal
def main():
    global CEDEARS_OK
    A, info = bajar_precios()
    CEDEARS_OK = [t for t in CEDEARS if t in A.columns]
    ult_ts = (info["SPY"].get("fecha") or 0)
    ult_dia = pd.Timestamp(datetime.fromtimestamp(ult_ts, timezone.utc).date()) if ult_ts else pd.Timestamp(AHORA.date())
    # un mes está "completo" cuando ya cerró su último día hábil
    completos = [d for d in A.index if ult_dia >= ultimo_habil(d)]
    S, historial, mom = simular(A, completos)
    if not historial:
        raise SystemExit("No se pudo armar ninguna cartera.")

    vigente = historial[-1]
    anterior = historial[-2] if len(historial) > 1 else {"fecha": None, "tickers": []}
    salen = [t for t in anterior["tickers"] if t not in vigente["tickers"]]
    entran = [t for t in vigente["tickers"] if t not in anterior["tickers"]]

    # próxima revisión: último día hábil del próximo mes de revisión
    prox, m = None, pd.Timestamp(ult_dia.year, ult_dia.month, 1) + pd.offsets.MonthEnd(0)
    for _ in range(13):
        if m.month in MESES and ultimo_habil(m) > pd.Timestamp(vigente["fecha"]):
            prox = ultimo_habil(m); break
        m = m + pd.offsets.MonthEnd(1)

    # cómo le va a la cartera vigente desde que se eligió
    f0 = pd.Timestamp(vigente["fecha"])
    ult = A.ffill().iloc[-1]
    desde = {t: r4(ult[t] / A.at[f0, t] - 1) for t in vigente["tickers"] if t in A.columns}
    spy_desde = r4(ult["SPY"] / A.at[f0, "SPY"] - 1)

    # candidatas: cómo quedaría el ranking si la revisión fuera hoy
    mom_hoy = (A.ffill().shift(1).iloc[-1] / A.ffill().shift(12).iloc[-1] - 1)[CEDEARS_OK].dropna().sort_values(ascending=False)
    candidatas = [{"ticker": t, "momentum": r4(v), "en_cartera": t in vigente["tickers"]} for t, v in mom_hoy.head(N_CAND).items()]

    fichas = actualizar_fichas(list(dict.fromkeys(vigente["tickers"] + [c["ticker"] for c in candidatas])), info)
    guardar("fichas.json", fichas)

    ult5 = S.index >= S.index[-1] - pd.DateOffset(years=5)
    previo = leer("momentum.json", {})
    salida = {
        "generado": f"{AHORA.astimezone(timezone(timedelta(hours=-3))):%Y-%m-%d %H:%M}",
        "precios_al": f"{ult_dia:%Y-%m-%d}",
        "regla": {"top": TOP, "meses_revision": MESES, "costo_lado": COSTO, "universo": len(CEDEARS_OK)},
        "cartera": {"fecha": vigente["fecha"], "tickers": vigente["tickers"], "momentum_eleccion": vigente["momentum"],
                    "desde_eleccion": desde, "spy_desde_eleccion": spy_desde},
        "cambios": {"desde": anterior["fecha"], "salen": salen, "entran": entran},
        "proxima_revision": f"{prox:%Y-%m-%d}" if prox is not None else None,
        "candidatas": candidatas,
        "historial": historial[-12:],
        "curva": {"fechas": [f"{d:%Y-%m}" for d in S.index],
                  "estrategia": [r4(v) for v in (1 + S.estrategia).cumprod()],
                  "spy": [r4(v) for v in (1 + S.spy).cumprod()],
                  "universo": [r4(v) for v in (1 + S.universo.fillna(0)).cumprod()]},
        "resumen": {"anual": r4(anual(S.estrategia)), "anual_spy": r4(anual(S.spy)), "anual_universo": r4(anual(S.universo)),
                    "anual_5": r4(anual(S.estrategia[ult5])), "anual_spy_5": r4(anual(S.spy[ult5])),
                    "caida_max": r4(caida(S.estrategia)), "caida_max_spy": r4(caida(S.spy)),
                    "anios_perdedores": int(sum(1 for _, g in S.estrategia.groupby(S.index.year) if (1 + g).prod() < 1)),
                    "anios": int(S.index.year.nunique()), "desde": f"{S.index[0]:%Y-%m}"},
        "nombres": {t: fichas.get(t, {}).get("nombre") for t in set(vigente["tickers"]) | {c["ticker"] for c in candidatas}},
    }
    guardar("momentum.json", salida)
    log(f"cartera {vigente['fecha']}: {', '.join(vigente['tickers'])} | próxima revisión {salida['proxima_revision']}")

    if previo and previo.get("cartera", {}).get("fecha") != vigente["fecha"]:
        avisar(vigente["fecha"], salen, entran, vigente["tickers"])


CEDEARS_OK = []
if __name__ == "__main__":
    main()
