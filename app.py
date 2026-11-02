# Middleware Mónica ManyChat -> OpenAI. MODO PRUEBA: solo atiende contactos con la etiqueta tester_monica.
import os,re,json,threading,logging,requests
from flask import Flask,request,jsonify
logging.basicConfig(level=logging.INFO)
OA=os.environ['OPENAI_API_KEY']; MC=os.environ.get('MANYCHAT_API_KEY',''); SECRET=os.environ['MONICA_SECRET']
MODEL=os.environ.get('MODEL','gpt-5-mini'); FLOW_NS=os.environ.get('MANYCHAT_FLOW_RESPUESTA','')
ALLOWED=set(x for x in os.environ.get('ALLOWED_CONTACT_IDS','').split(',') if x)  # opcional: lista blanca extra
import base64,gzip
_p=os.path.join(os.path.dirname(__file__),'SYSTEM_PROMPT_MONICA_MANYCHAT_COMPLETO.txt')
SYS=gzip.decompress(base64.b64decode(os.environ['MONICA_PROMPT_GZ_B64'])).decode() if os.environ.get('MONICA_PROMPT_GZ_B64') else open(_p).read()
SCH={"type":"object","additionalProperties":False,"required":["reply","nombre","whatsapp","tipo_lead","propiedad","handoff"],"properties":{"reply":{"type":"string"},"nombre":{"type":"string"},"whatsapp":{"type":"string"},"tipo_lead":{"type":"string","enum":["","Visita","Búsqueda","Captación","Colega"]},"propiedad":{"type":"string"},"handoff":{"type":"boolean"}}}
COLEGA=re.compile(r'colega|asesor[a]? inmobiliari|agente inmobiliari|inmobiliaria\b(?! for rent)|profesional inmobiliari|corredor|realtor|broker|group\b',re.I)
DUENO=re.compile(r'\bmi (apartamento|apto|casa|local|oficina|inmueble|propiedad|terreno|galp[oó]n)|\b(vendo|alquilo|estoy (vendiendo|alquilando))\b|soy (el |la )?(due[ñn]o|propietari)',re.I)
TEL=re.compile(r'(?<![\w-])(?:\+?58[\s\-.]?)?\(?0?(?:4\d{2}|2\d{2})\)?[\s\-.]?\d{3}[\s\-.]?\d{2}[\s\-.]?\d{2}(?!\d)')
def corregir(j,texto):
    t=j.get('tipo_lead','')
    if t=='Colega' and not COLEGA.search(texto): t=''
    if t=='Captación' and not DUENO.search(texto): t=''
    if not t and COLEGA.search(texto): t='Colega'
    j['tipo_lead']=t
    j['reply']=TEL.sub('tu número',j.get('reply',''))[:1000]   # nunca teléfonos en la respuesta
    j['reply']=re.sub(r'https?://(?!(www\.)?grupoinmobiliarioforrent\.com|(\w+\.)?mercadolibre\.com\.ve)\S+','',j['reply'])
    return j
def pensar(d):
    hist=(d.get('historial') or '')[-4000:]
    body={"model":MODEL,"instructions":SYS,"reasoning":{"effort":"low"},"store":False,"prompt_cache_key":"monica",
          "input":f"canal: {d.get('canal','instagram')}\nnombre_contacto: {d.get('nombre','')}\nhistorial:\n{hist or '(vacío)'}\n\nmensaje_cliente:\n{d.get('mensaje','')}",
          "text":{"format":{"type":"json_schema","name":"monica","strict":True,"schema":SCH}}}
    r=requests.post('https://api.openai.com/v1/responses',headers={'Authorization':'Bearer '+OA},json=body,timeout=90).json()
    txt=''.join(c.get('text','') for it in r.get('output',[]) if it.get('type')=='message' for c in it.get('content',[]))
    j=corregir(json.loads(txt),hist+'\n'+d.get('mensaje',''))
    u=r.get('usage',{}); logging.info('usage in=%s cached=%s out=%s',u.get('input_tokens'),(u.get('input_tokens_details') or {}).get('cached_tokens'),u.get('output_tokens'))
    j['_historial']=(hist+f"\nCLIENTE: {d.get('mensaje','')}\nMÓNICA: {j['reply']}")[-4000:]
    return j,u
def mc(path,body):
    r=requests.post('https://api.manychat.com'+path,headers={'Authorization':'Bearer '+MC},json=body,timeout=20)
    logging.info('manychat %s -> %s %s',path,r.status_code,r.text[:300]); return r
def work(d):
    try:
        j,_=pensar(d); sid=int(d['contact_id'])
        f=[("monica_respuesta",j['reply']),("monica_historial",j['_historial']),("Nombre_Apellido",j['nombre']),("WhatsApp_Cliente",j['whatsapp']),("Tipo_Lead",j['tipo_lead']),("Propiedad",j['propiedad']),("monica_handoff","si" if j['handoff'] else "no")]
        mc('/fb/subscriber/setCustomFields',{"subscriber_id":sid,"fields":[{"field_name":k,"field_value":v} for k,v in f if v]})
        if FLOW_NS: mc('/fb/sending/sendFlow',{"subscriber_id":sid,"flow_ns":FLOW_NS})
    except Exception as e: logging.exception('work error: %s',e)
app=Flask(__name__)
@app.post('/monica')
def monica():
    if request.headers.get('X-Monica-Secret')!=SECRET: return jsonify(ok=False,error='secret'),403
    d=request.get_json(force=True,silent=True) or {}
    if d.get('dry_run'):   # prueba sin ManyChat: responde la respuesta en línea
        j,u=pensar(d); j.pop('_historial',None); return jsonify(ok=True,**j,usage=u)
    if d.get('tag')!='tester_monica': return jsonify(ok=False,error='solo tester_monica'),200
    if ALLOWED and str(d.get('contact_id')) not in ALLOWED: return jsonify(ok=False,error='contacto no permitido'),200
    threading.Thread(target=work,args=(d,),daemon=True).start()
    return jsonify(ok=True)
@app.get('/healthz')
def h(): return 'ok'
if __name__=='__main__': app.run(host='0.0.0.0',port=int(os.environ.get('PORT',10000)))
