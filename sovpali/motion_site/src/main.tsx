import React,{useState,useRef} from 'react';
import {createRoot} from 'react-dom/client';
import {Heart} from 'lucide-react';
import {setupTelegram,telegram,isMiniApp} from './telegram';
import {Cabinet,api,demoCabinet,Pair,CabinetData} from './Cabinet';
import Onboarding from './Onboarding';
const app=createRoot(document.getElementById('root')!);
function Notice({message,retry=false}:{message:string;retry?:boolean}){return <div className="boot"><div className="brand"><span>♡</span>совпали.</div><div className="boot-heart"><Heart/></div><p role="status">{message}</p>{retry&&<button className="primary" onClick={()=>location.reload()}>Попробовать снова</button>}</div>}
function Ready({prefetch}:{prefetch:Promise<CabinetData|undefined>}){
 const [busy,setBusy]=useState(false),[error,setError]=useState('');
 const current=useRef(prefetch);
 async function open(){
  if(busy)return;
  setBusy(true);setError('');
  try{
   let data=await current.current;
   if(!data){current.current=api('/s/app/api/cabinet');data=await current.current}
   app.render(<Cabinet initialData={data}/>);
  }catch(e){setError((e as Error).message)}finally{setBusy(false)}
 }
 return <div className="on-wrap"><div className="on-glow"/><main className="on-shell" style={{justifyContent:'center',textAlign:'center',alignItems:'center',gap:18}}>
   <div className="on-brand"><span>♡</span>совпали<span>.</span></div>
   <div className="on-center" style={{flexShrink:0,width:110,height:110,marginTop:25}}><Heart size={45}/></div>
   <div className="on-eyebrow" style={{marginTop:30}}>ТВОЙ ПРОФИЛЬ СОХРАНЁН</div>
   <h1 style={{fontSize:'clamp(31px,7vw,45px)',letterSpacing:'-1.5px',lineHeight:1.13}}>Твоя история начинается</h1>
   <p className="on-hint" style={{maxWidth:350,margin:'0 auto 22px'}}>Анкета готова. Теперь найдём людей, с которыми у тебя есть настоящее совпадение.</p>
   <button type="button" className="on-next ready-action" onClick={open} disabled={busy}>{busy?'Подбираем совместимых людей…':'Сделать подборку'}<Heart size={19}/></button>
   {error&&<p className="on-error" role="alert">{error} Попробуй ещё раз.</p>}
 </main></div>;
}
async function boot(){
 setupTelegram();
 const initial=(window as any).__SOVPALI_PAIR__;
 let pair:Pair|undefined=initial?.candidate?initial:undefined,data:CabinetData|undefined,error='';
 if(pair&&!pair.demo&&isMiniApp()&&pair.request_path&&!initial.miniapp_auth_path)initial.miniapp_auth_path=pair.request_path.replace('/s/m/request/','/s/mini/auth/');
 if(initial?.miniapp_auth_path||initial?.cabinet_auth_path){
  app.render(<Notice message="Открываем твоё пространство…"/>);
  if(!isMiniApp()){app.render(<Notice message="Открой приложение кнопкой «Открыть» в боте «Совпали»."/>);return}
  if(initial.miniapp_auth_path){
   try{const r=await fetch(initial.miniapp_auth_path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({init_data:telegram().initData}),signal:AbortSignal.timeout(20000)});const result=await r.json().catch(()=>null);if(!r.ok)throw new Error(result?.message||'Эта пара сейчас недоступна. Открой свою подборку в боте.');pair=result}catch(e){app.render(<Notice message={(e as Error).message} retry/>);return}
  }
  try{data=await api('/s/app/api/cabinet')}catch(e){error=(e as Error).message;if(!pair){app.render(<Notice message={error} retry/>);return}}
 }else if(pair?.demo)data=demoCabinet(pair);
 if(data&&!data.profile&&!pair){app.render(<Onboarding onComplete={()=>{const prefetch=api('/s/app/api/cabinet').catch(()=>undefined);app.render(<Ready prefetch={prefetch}/>);}}/>);return;}
 // Main Mini App link after Ozon; the bank's redirect cannot grant access.
 // The returned order is checked using signed Telegram initData in Cabinet.
 const start=String(telegram()?.initDataUnsafe?.start_param||
   new URLSearchParams(location.search).get('tgWebAppStartParam')||'');
 const returnedOrder=/^payment_([a-f0-9]{32})$/.exec(start)?.[1];
 app.render(<Cabinet initialPair={pair} initialData={data} initialError={error}
   initialReturnOrder={returnedOrder}/>);
}
boot().catch(()=>app.render(<Notice message="Не удалось открыть приложение. Попробуй ещё раз." retry/>));
