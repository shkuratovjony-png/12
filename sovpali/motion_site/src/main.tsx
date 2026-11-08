import React from 'react';
import {createRoot} from 'react-dom/client';
import {setupTelegram, telegram} from './telegram';
import './reset.css';
import './MiniApp.css';
const root=document.getElementById('root')!;
const app=createRoot(root);
function Notice({message,retry=false}:{message:string,retry?:boolean}) {
 return <div className="mini-loading" role="status"><span className="mini-brand">совпали.</span><div className="mini-loading-heart">♡</div><p>{message}</p>{retry&&<button onClick={()=>location.reload()}>Попробовать снова</button>}</div>;
}
async function boot(){
 setupTelegram();
 const path=(window as any).__SOVPALI_PAIR__?.miniapp_auth_path;
 if(path){
  app.render(<Notice message="Открываем историю вашей пары…"/>);
  if(!telegram()?.initData){app.render(<Notice message="Открой персональный разбор кнопкой в боте «Совпали»."/>);return;}
  try {
   const response=await fetch(path,{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:JSON.stringify({init_data:telegram().initData}),signal:AbortSignal.timeout(20000)});
   const data=await response.json();
   if(!response.ok){app.render(<Notice message={data.message||'Разбор недоступен. Вернись в бот и открой подборку заново.'}/>);return;}
   (window as any).__SOVPALI_PAIR__=data;
  } catch {app.render(<Notice message="Не удалось загрузить разбор. Проверь соединение." retry/>);return;}
 }
 try {const {Premium,preparePair}=await import('./Premium');preparePair();app.render(<Premium/>);}
 catch {app.render(<Notice message="Не удалось загрузить страницу." retry/>);}
}
boot();
