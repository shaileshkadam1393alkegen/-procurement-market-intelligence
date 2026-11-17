import os, sqlite3, hashlib, secrets, json, datetime, statistics, math, hmac
from pathlib import Path
from contextlib import contextmanager
from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
import httpx

BASE=Path(__file__).parent
DB=Path(os.getenv('DATABASE_PATH', str(BASE/'intelligence.db')))
SECRET=os.getenv('SESSION_SECRET','')
if len(SECRET)<32: raise RuntimeError('Set SESSION_SECRET to at least 32 random characters')
COOKIE_SECURE=os.getenv('COOKIE_SECURE','true').lower()=='true'
SER=URLSafeTimedSerializer(SECRET,salt='market-intel-session')
app=FastAPI(title='Procurement Market Intelligence')
app.mount('/static',StaticFiles(directory=BASE/'static'),name='static')

SERIES={
 'us_cpi':dict(name='US CPI All Items',source='BLS',series='CUUR0000SA0',unit='index',geo='US',category='macro',link='https://www.bls.gov/cpi/'),
 'us_energy':dict(name='US CPI Energy',source='BLS',series='CUUR0000SA0E',unit='index',geo='US',category='waste',link='https://www.bls.gov/cpi/'),
 'us_gas':dict(name='US CPI Gasoline',source='BLS',series='CUUR0000SETB01',unit='index',geo='US',category='logistics',link='https://www.bls.gov/cpi/'),
 'us_hourly':dict(name='US Average Hourly Earnings, Private',source='BLS',series='CES0500000003',unit='USD/hour',geo='US',category='labor',link='https://www.bls.gov/ces/'),
 'eu_hicp':dict(name='Euro Area HICP All Items',source='EUROSTAT',dataset='prc_hicp_midx',filters={'geo':'EA20','coicop':'CP00','unit':'I15'},unit='index',geo='EA20',category='macro',link='https://ec.europa.eu/eurostat/web/hicp'),
 'eu_ppi':dict(name='Euro Area Industrial PPI Total',source='EUROSTAT',dataset='sts_inpp_m',filters={'geo':'EA20','nace_r2':'B-E36','indic_bt':'PRIN','s_adj':'NSA'},unit='index',geo='EA20',category='mro',link='https://ec.europa.eu/eurostat/web/short-term-business-statistics'),
}
CATEGORIES={
 'mro':{'name':'MRO & Industrial','series':['eu_ppi','us_cpi','eu_hicp'],'drivers':['industrial PPI','metals','machinery','freight']},
 'waste':{'name':'Waste Management','series':['us_energy','us_gas','us_hourly'],'drivers':['diesel proxy','labor','disposal charges']},
 'needles':{'name':'Industrial Needles & Textiles','series':['eu_ppi','us_hourly','eu_hicp'],'drivers':['specialty alloys','labor','manufacturing']},
 'heating':{'name':'Heating Elements','series':['eu_ppi','us_energy'],'drivers':['nickel/chromium','industrial energy']},
 'bearings':{'name':'Bearings & Mechanical','series':['eu_ppi','us_cpi','eu_hicp'],'drivers':['steel','energy','freight']},
 'ppe':{'name':'PPE & Uniforms','series':['us_cpi','us_hourly'],'drivers':['textiles','polymers','labor']},
 'labor':{'name':'Labor & Services','series':['us_hourly','us_cpi','eu_hicp'],'drivers':['wages','ECI','productivity']},
 'logistics':{'name':'Logistics & Packaging','series':['us_gas','us_energy','eu_ppi'],'drivers':['fuel','paper','polymers']},
}
@contextmanager
def connect():
 DB.parent.mkdir(parents=True,exist_ok=True)
 c=sqlite3.connect(DB);c.row_factory=sqlite3.Row
 try: yield c;c.commit()
 finally:c.close()
def init():
 with connect() as c:
  c.executescript('''CREATE TABLE IF NOT EXISTS users(email TEXT PRIMARY KEY, salt TEXT NOT NULL, password_hash TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1, admin INTEGER NOT NULL DEFAULT 0);CREATE TABLE IF NOT EXISTS observations(series_key TEXT NOT NULL,period TEXT NOT NULL,value REAL NOT NULL, retrieved_at TEXT NOT NULL,source_url TEXT NOT NULL, PRIMARY KEY(series_key,period));CREATE TABLE IF NOT EXISTS alerts(id INTEGER PRIMARY KEY AUTOINCREMENT,series_key TEXT NOT NULL,period TEXT NOT NULL,metric TEXT NOT NULL,change REAL NOT NULL,severity TEXT NOT NULL,created_at TEXT NOT NULL,UNIQUE(series_key,period,metric));CREATE TABLE IF NOT EXISTS sync_runs(id INTEGER PRIMARY KEY AUTOINCREMENT,at TEXT NOT NULL,status TEXT NOT NULL,details TEXT NOT NULL);''')
init()
def pw_hash(p,s):return hashlib.scrypt(p.encode(),salt=bytes.fromhex(s),n=16384,r=8,p=1).hex()

def bootstrap_demo_admin():
 # Demo-only bootstrap. Never expose credentials in source code or logs.
 email=os.getenv('BOOTSTRAP_ADMIN_EMAIL','').strip().lower()
 password=os.getenv('BOOTSTRAP_ADMIN_PASSWORD','')
 if not email and not password:
  return
 if '@' not in email or len(password)<16:
  raise RuntimeError('Set BOOTSTRAP_ADMIN_EMAIL and a BOOTSTRAP_ADMIN_PASSWORD of at least 16 characters')
 with connect() as c:
  existing=c.execute('SELECT email FROM users WHERE admin=1 LIMIT 1').fetchone()
  if existing:
   return
  salt=secrets.token_hex(16)
  c.execute('INSERT INTO users(email,salt,password_hash,active,admin) VALUES(?,?,?,?,1)',
            (email,salt,pw_hash(password,salt),1))

bootstrap_demo_admin()
def session_user(req:Request):
 token=req.cookies.get('market_session')
 if not token:raise HTTPException(401,'Sign in required')
 try: email=SER.loads(token,max_age=60*60*12)
 except (BadSignature,SignatureExpired):raise HTTPException(401,'Session expired')
 with connect() as c: row=c.execute('SELECT email,admin FROM users WHERE email=? AND active=1',(email,)).fetchone()
 if not row:raise HTTPException(401,'User disabled')
 return dict(row)
def admin_user(user=Depends(session_user)):
 if not user['admin']:raise HTTPException(403,'Admin only')
 return user
class Credentials(BaseModel):email:str;password:str
@app.get('/')
def home():return FileResponse(BASE/'static'/'index.html')
@app.post('/api/login')
def login(data:Credentials):
 with connect() as c: row=c.execute('SELECT * FROM users WHERE email=? AND active=1',(data.email.strip().lower(),)).fetchone()
 if not row or not hmac.compare_digest(pw_hash(data.password,row['salt']),row['password_hash']):raise HTTPException(401,'Invalid credentials')
 response=JSONResponse({'ok':True,'email':row['email'],'admin':bool(row['admin'])})
 response.set_cookie('market_session',SER.dumps(row['email']),max_age=43200,httponly=True,secure=COOKIE_SECURE,samesite='lax',path='/')
 return response
@app.post('/api/logout')
def logout(user=Depends(session_user)):
 r=JSONResponse({'ok':True});r.delete_cookie('market_session',path='/');return r
@app.get('/api/me')
def me(user=Depends(session_user)):return user
@app.get('/api/catalog')
def catalog(user=Depends(session_user)):return {'categories':CATEGORIES,'series':SERIES}
@app.get('/api/dashboard/{category}')
def dashboard(category:str,user=Depends(session_user)):
 if category not in CATEGORIES:raise HTTPException(404,'Unknown category')
 items=[]
 with connect() as c:
  for key in CATEGORIES[category]['series']:
   rows=c.execute('SELECT period,value,retrieved_at,source_url FROM observations WHERE series_key=? ORDER BY period DESC LIMIT 60',(key,)).fetchall()
   pts=[dict(r) for r in reversed(rows)]
   current=pts[-1]['value'] if pts else None
   prev=pts[-2]['value'] if len(pts)>1 else None
   mom=(current/prev-1)*100 if prev and current is not None else None
   yoy=(current/pts[-13]['value']-1)*100 if len(pts)>=13 and pts[-13]['value'] else None
   items.append({'key':key,**SERIES[key],'points':pts,'latest':current,'previous':prev,'mom':mom,'yoy':yoy,'forecast':forecast(pts)})
 return {'category':category,'name':CATEGORIES[category]['name'],'items':items,'as_of':datetime.datetime.now(datetime.timezone.utc).isoformat()}
def forecast(points):
 # Simple linear regression extrapolation, with no claim of statistical confidence.
 values=[p['value'] for p in points[-18:]]
 if len(values)<6:return {'method':'unavailable','reason':'At least 6 historical observations required','values':[]}
 n=len(values);xs=list(range(n));xm=(n-1)/2;ym=statistics.mean(values);den=sum((x-xm)**2 for x in xs);slope=sum((x-xm)*(y-ym) for x,y in zip(xs,values))/den
 fitted=[ym+slope*(x-xm) for x in xs];rmse=math.sqrt(sum((y-f)**2 for y,f in zip(values,fitted))/n)
 return {'method':'linear trend scenario (not validated forecast)','values':[{'horizon_months':h,'central':round(ym+slope*(n-1+h-xm),3),'illustrative_low':round(ym+slope*(n-1+h-xm)-1.96*rmse*math.sqrt(h),3),'illustrative_high':round(ym+slope*(n-1+h-xm)+1.96*rmse*math.sqrt(h),3)} for h in (3,6,12)]}
@app.get('/api/alerts')
def alerts(user=Depends(session_user)):
 with connect() as c:return [dict(r) for r in c.execute('SELECT * FROM alerts ORDER BY id DESC LIMIT 100')]
@app.get('/api/status')
def status(user=Depends(session_user)):
 with connect() as c:
  r=c.execute('SELECT * FROM sync_runs ORDER BY id DESC LIMIT 1').fetchone()
  return {'last_sync':dict(r) if r else None,'observations':c.execute('SELECT COUNT(*) FROM observations').fetchone()[0]}
async def pull_bls(client,key,config):
 url='https://api.bls.gov/publicAPI/v1/timeseries/data/'+config['series']
 r=await client.get(url);r.raise_for_status();payload=r.json()
 if payload.get('status')!='REQUEST_SUCCEEDED':raise ValueError(str(payload.get('message','BLS error')))
 result=[]
 for x in payload['Results']['series'][0]['data']:
  if x['period'].startswith('M') and x['period']!='M13':result.append((f"{x['year']}-{x['period'][1:]}",float(x['value']),url))
 return result
async def pull_eurostat(client,key,config):
 url=f"https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/{config['dataset']}"
 r=await client.get(url,params={'lang':'EN',**config['filters']});r.raise_for_status();data=r.json()
 ids=data['id'];sizes=data['size'];dimensions=data['dimension'];vals=data.get('value',{})
 # Reject non-singleton dimensions except time, to avoid silently mixing measures.
 for name,size in zip(ids,sizes):
  if name!='time' and size!=1:
   choices=list(dimensions[name].get('category',{}).get('index',{}).keys())
   raise ValueError(f'Eurostat dimension {name} has {size} matches; available codes: {choices[:12]}. Verify filters for {config["dataset"]}.')
 times=dimensions['time']['category']['index'];out=[]
 for period,index in times.items():
  pos=index if isinstance(index,int) else int(index)
  v=vals.get(str(pos)) if isinstance(vals,dict) else vals[pos]
  if v is not None:out.append((period,float(v),str(r.url)))
 return out
async def sync():
 now=datetime.datetime.now(datetime.timezone.utc).isoformat();out=[];success=0
 async with httpx.AsyncClient(timeout=25,follow_redirects=True,headers={'User-Agent':'ProcurementMarketIntelligence/0.1'}) as client:
  bls_quota_exceeded=False
  for key,config in SERIES.items():
   if config['source']=='BLS' and bls_quota_exceeded:
    out.append({'series':key,'status':'skipped','reason':'BLS quota already reached during this sync; avoiding repeated requests.'})
    continue
   try:
    rows=await (pull_bls(client,key,config) if config['source']=='BLS' else pull_eurostat(client,key,config))
    with connect() as c:
     for period,value,url in rows:c.execute('INSERT INTO observations VALUES(?,?,?,?,?) ON CONFLICT(series_key,period) DO UPDATE SET value=excluded.value,retrieved_at=excluded.retrieved_at,source_url=excluded.source_url',(key,period,value,now,url))
     recent=c.execute('SELECT period,value FROM observations WHERE series_key=? ORDER BY period DESC LIMIT 2',(key,)).fetchall()
     if len(recent)==2 and recent[1]['value']!=0:
