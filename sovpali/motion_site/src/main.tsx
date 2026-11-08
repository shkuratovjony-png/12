import React from 'react';
import {createRoot} from 'react-dom/client';
import {Heart} from 'lucide-react';
import {setupTelegram,telegram,isMiniApp} from './telegram';
import {Cabinet,api,demoCabinet,Pair,CabinetData} from './Cabinet';
import Onboarding from './Onboarding';
const app=createRoot(document.getElementById('root')!);
function Notice({message,retry=false}:{message:string;retry?:boolean}){return <div className="boot"><div className="brand"><span>♡</span>совпали.</div><div className="boot-heart"><Heart/></div><p role="status">{message}</p>{retry&&<button className="primary" onClick={()=>location.reload()}>Попробовать снова</button>}</div>}
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
 if(data&&!data.profile&&!pair){app.render(<Onboarding onComplete={async()=>{const fresh=await api('/s/app/api/cabinet');app.render(<Cabinet initialData={fresh}/>);}}/>);return;}
 app.render(<Cabinet initialPair={pair} initialData={data} initialError={error}/>);
}
boot().catch(()=>app.render(<Notice message="Не удалось открыть приложение. Попробуй ещё раз." retry/>));
