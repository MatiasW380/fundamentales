# ======================= FUNDAMENTALES - CELDA 1: CONFIGURACIÓN Y DESCARGA =======================
# Baja los balances (10-Q y 10-K) de la SEC y los precios de Yahoo de las empresas de EE.UU. con CEDEAR.
# Todo queda en Drive (Mi unidad/Colab Notebooks/FUNDAMENTALES): la segunda vez solo baja lo que tenga
# más de REFRESCAR_DIAS días.
#
# ANTES DE CORRER, en Colab: ícono de la llave (Secretos) -> agregar y activar "Acceso del notebook":
#   SEC_USER_AGENT = "Tu Nombre tu_mail@dominio.com"   (la SEC exige identificarse; sin esto responde 403)
#   GITHUB_TOKEN   = token con permiso de escritura sobre MatiasW380/fundamentales (solo lo usa la celda 4)
import subprocess, sys
subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-U", "yfinance"], check=False)

import os, re, json, gzip, time, math, base64, warnings
import numpy as np, pandas as pd, requests, yfinance as yf
warnings.filterwarnings("ignore")

try:
    from google.colab import drive, userdata
    drive.mount("/content/drive")
    DIR = "/content/drive/MyDrive/Colab Notebooks/FUNDAMENTALES"
except ImportError:                                   # fuera de Colab (pruebas locales)
    userdata = None
    DIR = os.environ.get("FUNDAMENTALES_DIR", "./FUNDAMENTALES")
os.makedirs(os.path.join(DIR, "sec"), exist_ok=True)


ERRORES_SECRETOS = {}


def secreto(nombre):
    if userdata is not None:
        try:
            return userdata.get(nombre) or ""
        except Exception as e:                        # no existe, o el notebook no tiene acceso
            ERRORES_SECRETOS[nombre] = type(e).__name__
    return os.environ.get(nombre, "")


# ----------------------------- contacto para la SEC -----------------------------
# Si preferís no usar los Secretos de Colab, escribilo acá (nombre y mail). Si el secreto existe, tiene prioridad.
SEC_CONTACTO = ""            # ejemplo: "Matias Baronetto tu_mail@dominio.com"

# ----------------------------- parámetros -----------------------------
INICIO_PRECIOS = "2009-01-01"
REFRESCAR_DIAS = 7
COMISION_LADO = 0.00726        # PPI, CEDEARs: cada compra o cada venta
OTROS_LADO = 0.0015            # derechos de mercado + diferencia entre puntas (estimado)
COSTO_LADO = COMISION_LADO + OTROS_LADO
RESERVA = 0.25                 # último 25% de los meses: no se mira hasta el final
TOPS = (10, 20)                # cantidad de empresas en cartera (cada valor es una prueba)
MESES_REBALANCEO = (2, 5, 8, 11)   # fin de feb/may/ago/nov: ya salieron los balances del trimestre
T_MINIMO = 2.0
MONITOR_N = 15
GITHUB_REPO = "MatiasW380/fundamentales"
GITHUB_RAMA = "main"

# Empresas de EE.UU. con CEDEAR en BYMA que presentan 10-K/10-Q (las extranjeras presentan 20-F, sin trimestres).
# Lista editable: si alguna no tiene CEDEAR o falta alguna, cambiala acá.
CEDEARS = """
AAPL MSFT GOOGL AMZN META NVDA TSLA NFLX ADBE CRM ORCL IBM INTC AMD QCOM TXN AVGO MU AMAT LRCX ADI CSCO HPQ
INTU NOW PANW CRWD SNOW PLTR UBER ABNB PYPL XYZ COIN MSTR ZM DOCU TWLO SNAP PINS ROKU EBAY ETSY EA ACN ADP
VRSN AKAM DELL SMCI MRVL ANET NET DDOG SHOP SPOT
KO PEP WMT COST HD LOW TGT MCD SBUX NKE DIS PG CL KMB MO PM MDLZ KHC GIS HSY EL TJX LULU BBY KR CVS MELI
F GM HOG DAL AAL UAL LUV CCL RCL NCLH BKNG MAR YUM CMG DECK ANF URBN
JNJ PFE MRK ABBV LLY BMY AMGN GILD BIIB ABT TMO DHR MDT UNH HUM ISRG MRNA REGN VRTX ZTS
JPM BAC C WFC GS MS AXP V MA BK USB SCHW BLK AIG MET PNC COF
XOM CVX COP OXY SLB HAL EOG DVN NEM FCX NUE DOW DD MOS CAT DE MMM GE HON BA LMT RTX NOC GD UPS FDX UNP CSX
T VZ CMCSA TMUS CHTR WBD AMT SPG O GLW
HUT RIOT MARA RKLB ASTS LUNR
""".split()
CEDEARS = list(dict.fromkeys(CEDEARS))

FORMAS = {"10-Q", "10-K", "10-Q/A", "10-K/A", "10-KT"}
CONCEPTOS = {
    # flujos: tienen inicio y fin (trimestre o acumulado del año)
    "ventas": ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax",
               "RevenueFromContractWithCustomerIncludingAssessedTax", "SalesRevenueNet", "SalesRevenueGoodsNet"],
    "costo": ["CostOfRevenue", "CostOfGoodsAndServicesSold", "CostOfGoodsSold", "CostOfGoodsAndServiceExcludingDepreciationDepletionAndAmortization"],
    "bruta": ["GrossProfit"],
    "operativo": ["OperatingIncomeLoss"],
    "neto": ["NetIncomeLoss", "ProfitLoss", "NetIncomeLossAvailableToCommonStockholdersBasic"],
    "flujo_op": ["NetCashProvidedByUsedInOperatingActivities", "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"],
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets"],
    # saldos: una fecha
    "activo": ["Assets"],
    "pasivo": ["Liabilities"],
    "patrimonio": ["StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"],
    "activo_cte": ["AssetsCurrent"],
    "pasivo_cte": ["LiabilitiesCurrent"],
    "deuda_lp": ["LongTermDebtNoncurrent", "LongTermDebt"],
    "caja": ["CashAndCashEquivalentsAtCarryingValue", "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"],
}
FLUJOS = ["ventas", "costo", "bruta", "operativo", "neto", "flujo_op", "capex"]
SALDOS = ["activo", "pasivo", "patrimonio", "activo_cte", "pasivo_cte", "deuda_lp", "caja"]


# ----------------------------- SEC -----------------------------
SEC_UA = secreto("SEC_USER_AGENT") or SEC_CONTACTO
if not re.search(r"\S+@\S+\.\S+", SEC_UA):
    motivo = ERRORES_SECRETOS.get("SEC_USER_AGENT", "")
    if motivo == "NotebookAccessError":
        detalle = "El secreto existe pero este notebook no tiene acceso: en la llave, activá 'Acceso del notebook' en SEC_USER_AGENT."
    elif motivo == "SecretNotFoundError":
        detalle = "No hay ningún secreto llamado exactamente SEC_USER_AGENT (revisá mayúsculas y guion bajo)."
    else:
        detalle = "El valor no tiene un mail válido."
    raise SystemExit(f"Falta el contacto para la SEC. {detalle} O completá SEC_CONTACTO al principio de esta celda.")
SES = requests.Session()
SES.headers.update({"User-Agent": SEC_UA, "Accept-Encoding": "gzip, deflate"})


def sec_get(url, intentos=4):
    r = None
    for k in range(intentos):
        try:
            r = SES.get(url, timeout=60)
            if r.status_code == 200:
                time.sleep(0.12)                      # la SEC permite hasta 10 pedidos por segundo
                return r.json()
            if r.status_code == 404:
                return None
        except requests.RequestException:
            pass
        time.sleep(2 * (k + 1))
    raise RuntimeError(f"SEC respondió {getattr(r, 'status_code', '?')} en {url}")


def viejo(ruta, dias=REFRESCAR_DIAS):
    return not os.path.exists(ruta) or time.time() - os.path.getmtime(ruta) > dias * 86400


def extraer(facts):
    """Se queda solo con los conceptos que usa el laboratorio: [prioridad, inicio, fin, valor, presentado]."""
    gaap = (facts.get("facts") or {}).get("us-gaap") or {}
    dei = (facts.get("facts") or {}).get("dei") or {}
    out = {}
    for clave, nombres in CONCEPTOS.items():
        filas = []
        for prio, nombre in enumerate(nombres):
            for e in ((gaap.get(nombre) or {}).get("units") or {}).get("USD", []):
                if e.get("form") in FORMAS and e.get("val") is not None:
                    filas.append([prio, e.get("start"), e["end"], float(e["val"]), e["filed"]])
        out[clave] = filas
    acc = []
    for prio, nodo in ((0, dei.get("EntityCommonStockSharesOutstanding")), (1, gaap.get("CommonStockSharesOutstanding"))):
        for e in ((nodo or {}).get("units") or {}).get("shares", []):
            if e.get("form") in FORMAS and e.get("val"):
                acc.append([prio, e.get("accn"), e["end"], float(e["val"]), e["filed"]])
    out["acciones"] = acc
    return out


def bajar_sec(tickers):
    ruta_mapa = os.path.join(DIR, "sec_tickers.json")
    if viejo(ruta_mapa, 30):
        mapa = sec_get("https://www.sec.gov/files/company_tickers.json")
        json.dump(mapa, open(ruta_mapa, "w"))
    mapa = json.load(open(ruta_mapa))
    por_ticker = {v["ticker"].upper(): (int(v["cik_str"]), v["title"]) for v in mapa.values()}
    info, faltan = {}, []
    for i, t in enumerate(tickers):
        clave = t.replace(".", "-").upper()
        if clave not in por_ticker:
            faltan.append(t); continue
        cik, nombre = por_ticker[clave]
        ruta = os.path.join(DIR, "sec", f"{t}.json.gz")
        if viejo(ruta):
            facts = sec_get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json")
            if not facts:
                faltan.append(t); continue
            with gzip.open(ruta, "wt") as f:
                json.dump({"cik": cik, "nombre": nombre, "datos": extraer(facts)}, f)
        info[t] = {"cik": cik, "nombre": nombre}
        if (i + 1) % 25 == 0:
            print(f"  SEC: {i + 1}/{len(tickers)}")
    if faltan:
        print(f"  Sin datos en la SEC (no presentan 10-K/10-Q o cambió el ticker): {', '.join(faltan)}")
    return info


def leer_sec(t):
    with gzip.open(os.path.join(DIR, "sec", f"{t}.json.gz"), "rt") as f:
        return json.load(f)


# ----------------------------- precios -----------------------------
def bajar_precios(tickers):
    ruta = os.path.join(DIR, "precios.pkl")
    if not viejo(ruta, 1):
        guardado = pd.read_pickle(ruta)
        if set(tickers) <= set(guardado["ajustado"].columns):
            return guardado
    cierre, ajustado, splits = [], [], []
    todos = list(tickers) + ["SPY", "^IRX"]
    for k in range(0, len(todos), 40):
        lote = todos[k:k + 40]
        for intento in range(3):
            try:
                d = yf.download(lote, start=INICIO_PRECIOS, auto_adjust=False, actions=True, progress=False,
                                threads=True, group_by="column")
                break
            except Exception as e:
                print(f"  Yahoo falló ({e}); reintento"); time.sleep(5 * (intento + 1)); d = None
        if d is None or d.empty:
            continue
        if not isinstance(d.columns, pd.MultiIndex):     # un solo ticker
            d.columns = pd.MultiIndex.from_product([d.columns, lote])
        cierre.append(d["Close"]); ajustado.append(d["Adj Close"])
        if "Stock Splits" in d.columns.get_level_values(0):
            splits.append(d["Stock Splits"])
        print(f"  Yahoo: {min(k + 40, len(todos))}/{len(todos)}")
    guardado = {"cierre": pd.concat(cierre, axis=1), "ajustado": pd.concat(ajustado, axis=1),
                "splits": pd.concat(splits, axis=1) if splits else pd.DataFrame()}
    for k in guardado:
        guardado[k].index = pd.to_datetime(guardado[k].index).tz_localize(None)
        guardado[k] = guardado[k].loc[:, ~guardado[k].columns.duplicated()]
    pd.to_pickle(guardado, ruta)
    return guardado


print("Bajando balances de la SEC...")
INFO = bajar_sec(CEDEARS)
print("Bajando precios de Yahoo...")
PRECIOS = bajar_precios(list(INFO))
con_precio = [t for t in INFO if t in PRECIOS["ajustado"].columns and PRECIOS["ajustado"][t].notna().sum() > 250]
print(f"\nListo: {len(INFO)} empresas con balances, {len(con_precio)} con precios. Carpeta: {DIR}")
