import {useEffect,useRef,useState} from 'react';
import type {FormEvent} from 'react';
import {telegram,isMiniApp} from './telegram';

type Product='contact'|'premium';
type PaymentState={paid:boolean;delivered:boolean;status:string;sku:string;delivery?:string|null;has_order?:boolean;payment_url?:string|null};
type Prepared={ticket:string;url:string};

const validEmail=(value:string)=>/^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(value.trim())&&value.trim().length<=120;

async function postCheckout(path:string,body:object){
 const response=await fetch(path,{
  method:'POST',credentials:'same-origin',
  headers:{'Content-Type':'application/json','X-Telegram-Init-Data':telegram()?.initData||''},
  body:JSON.stringify(body),signal:AbortSignal.timeout(25000)
 });
 const result=await response.json().catch(()=>null);
 if(!response.ok)throw new Error(result?.message||'Не удалось подготовить оплату. Попробуй ещё раз.');
 return result;
}

function openExternalCheckout(url:string){
 const destination=new URL(url);
 if(destination.protocol!=='https:'||destination.origin!==location.origin||
    !/^\/billing\/ozon\/launch\/[a-f0-9]{32}$/.test(destination.pathname)){
  throw new Error('Некорректная ссылка оплаты. Обнови оформление.');
 }
 const tg=telegram();
 if(isMiniApp()&&typeof tg?.openLink==='function'){
  // This call MUST execute during the physical tap; Telegram ignores delayed calls.
  tg.openLink(destination.href);
 }else{
  window.location.assign(destination.href);
 }
}

export function useBrowserCheckout(
 sku:Product,candidateId:number|null,
 onConfirmed:(state:PaymentState)=>void
){
 const [open,setOpen]=useState(false);
 const [email,setEmail]=useState(()=>{try{return sessionStorage.getItem('sovpali-receipt-email')||''}catch{return ''}});
 const [busy,setBusy]=useState(false);
 const [error,setError]=useState('');
 const pendingKey='sovpali-pending-'+sku+'-'+(candidateId??'all');
 const readPending=():Prepared|null=>{try{
  const raw=sessionStorage.getItem(pendingKey);
  if(!raw)return null;
  const obj=JSON.parse(raw);
  if(typeof obj.ticket==='string'&&/^[a-f0-9]{32}$/.test(obj.ticket)&&
    typeof obj.url==='string'&&obj.url.startsWith(location.origin+'/billing/ozon/launch/'))return obj;
 }catch{}return null};
 const initialPending=useRef<Prepared|null>(readPending());
 const [prepared,setPrepared]=useState<Prepared|null>(initialPending.current);
 const [started,setStarted]=useState(Boolean(initialPending.current));
 const [statusText,setStatusText]=useState(
   initialPending.current?'Проверяем ранее начатую оплату…':''
 );
 const [retry,setRetry]=useState(0);
 const [hasOrder,setHasOrder]=useState(false);
 const [bankLink,setBankLink]=useState('');
 const [copyHint,setCopyHint]=useState('');
 const [manualLink,setManualLink]=useState('');
 const [cancelBusy,setCancelBusy]=useState(false);
 const checking=useRef(false),confirmed=useRef(false);
 const onConfirmedRef=useRef(onConfirmed);onConfirmedRef.current=onConfirmed;
 const intent=useRef((typeof crypto!=='undefined'&&typeof crypto.randomUUID==='function')
   ?crypto.randomUUID().replace(/-/g,'')
   :String(Date.now())+Math.random().toString(36).slice(2)+Math.random().toString(36).slice(2));

 // A ticket is only a secret browser launch address; Ozon is NOT charged or reserved here.
 useEffect(()=>{
  if(!open||started||!validEmail(email))return;
  let cancelled=false;
  setPrepared(null);
  setError('');
  const timer=setTimeout(async()=>{
   setBusy(true);
   try{
    const data=await postCheckout('/s/app/api/checkout/prepare',{
     sku,candidate_id:sku==='contact'?candidateId:null,
     email:email.trim().toLowerCase(),intent:intent.current
    });
    const url=new URL(data?.url||'');
    if(url.protocol!=='https:'||url.origin!==location.origin||
      !/^\/billing\/ozon\/launch\/[a-f0-9]{32}$/.test(url.pathname)||
      typeof data?.ticket!=='string'||!/^([a-f0-9]{32})$/.test(data.ticket)){
     throw new Error('Не удалось получить безопасную ссылку оплаты.');
    }
    if(!cancelled){setPrepared({ticket:data.ticket,url:url.href});setError('')}
   }catch(err){if(!cancelled)setError((err as Error).message)}
   finally{if(!cancelled)setBusy(false)}
  },450);
  return()=>{cancelled=true;clearTimeout(timer)}
 },[open,email,sku,candidateId,started,retry]);

 const changeEmail=(next:string)=>{
  if(started||busy||cancelBusy)return;
  setEmail(next);setPrepared(null);setError('');
 };

 const launch=(e:FormEvent)=>{
  e.preventDefault();
  if(!validEmail(email)){setError('Укажи действующий email для чека.');return}
  if(!prepared||busy){setError('Оформление ещё подготавливается.');return}
  try{
   // Call Telegram.openLink NOW, from the tap, before any asynchronous work.
   try{
    sessionStorage.setItem('sovpali-receipt-email',email.trim().toLowerCase());
    sessionStorage.setItem(pendingKey,JSON.stringify(prepared));
   }catch{}
   setStarted(true);
   openExternalCheckout(prepared.url);
   setStatusText('Ожидаем подтверждение Ozon. Вернись сюда после оплаты.');
   setError('');
  }catch(err){setStarted(false);setError((err as Error).message)}
 };

 const checkStatus=async()=>{
  if(!started||!prepared||checking.current||confirmed.current||document.visibilityState==='hidden')return;
  checking.current=true;
  try{
   const data:PaymentState=await postCheckout('/s/app/api/checkout/status',{ticket:prepared.ticket});
   setHasOrder(Boolean(data.has_order));
   const url=String(data.payment_url||'');
   try{
     const target=new URL(url);
     const host=target.hostname.toLowerCase();
     setBankLink(target.protocol==='https:'&&(host.endsWith('.ozon.ru')||host.endsWith('.ozonpay.ru'))?target.href:'');
   }catch{setBankLink('')}
   if(data.paid&&data.delivered){
    confirmed.current=true;
    try{sessionStorage.removeItem(pendingKey)}catch{}
    setStatusText(sku==='contact'
     ?'Оплата подтверждена. Запрос на общение отправлен второй стороне.'
     :'Оплата подтверждена. Premium активирован.');
    onConfirmedRef.current(data);
   }else if(data.paid){
    setStatusText('Оплата подтверждена. Завершаем активацию, повторно платить не нужно.');
   }else if(data.status==='preparing'){
    setStatusText('Создаём платёж в Ozon. Подожди подтверждения.');
   }else{
    setStatusText('Ожидаем подтверждение Ozon. Если оплатил, вернись сюда — статус обновится.');
   }
  }catch(err){setStatusText((err as Error).message)}
  finally{checking.current=false}
 };
 // Recovery stays available when the OS opens the Ozon shopping app
 // instead of the provider-hosted form. Reusing an existing order is safe.
 const reopen=()=>{
  if(!prepared)return;
  try{openExternalCheckout(prepared.url);setError('');setCopyHint('')}
  catch(err){setError((err as Error).message)}
 };
 const copyForSafari=async()=>{
  if(!prepared)return;
  setManualLink('');
  let link=bankLink;
  if(!link){
   try{
    const state:PaymentState=await postCheckout('/s/app/api/checkout/status',{ticket:prepared.ticket});
    if(state.paid){setStatusText('Оплата уже подтверждена. Возвращаться к оплате не нужно.');return}
    if(!state.payment_url){
      setCopyHint('Платёжная ссылка ещё не создана. Нажми «Открыть оплату ещё раз», затем повтори копирование.');
      return;
    }
    const target=new URL(state.payment_url);
    const host=target.hostname.toLowerCase();
    if(target.protocol!=='https:'||!(host.endsWith('.ozon.ru')||host.endsWith('.ozonpay.ru')))
      throw new Error('Неверная ссылка Ozon.');
    link=target.href;setBankLink(link);
   }catch(err){setCopyHint((err as Error).message);return}
  }
  try{
   await navigator.clipboard.writeText(link);
   setCopyHint('Ссылка скопирована. Открой Safari и вставь её в адресную строку, а не нажимай ссылку в Telegram.');
  }catch{
   setManualLink(link);
   setCopyHint('Нажми на ссылку ниже, выдели и скопируй её вручную. Затем вставь в адресную строку Safari.');
  }
 };
 const cancelAttempt=async()=>{
  if(!prepared||cancelBusy)return;
  setCancelBusy(true);setError('');
  try{
   const data=await postCheckout('/s/app/api/checkout/cancel',{ticket:prepared.ticket});
   if(!data.cancelled)throw new Error(data.message||'Не удалось отменить оформление.');
   try{sessionStorage.removeItem(pendingKey)}catch{}
   setStarted(false);setPrepared(null);setHasOrder(false);setBankLink('');
   setStatusText('');setCopyHint('');setManualLink('');confirmed.current=false;
   setRetry(v=>v+1);
  }catch(err){
   setStatusText((err as Error).message);
   void checkStatus();
  }finally{setCancelBusy(false)}
 };
 const checkerRef=useRef(checkStatus);checkerRef.current=checkStatus;
 useEffect(()=>{
  if(!started||!prepared)return;
  const run=()=>{if(document.visibilityState!=='hidden')void checkerRef.current()};
  window.addEventListener('focus',run);
  document.addEventListener('visibilitychange',run);
  const timer=window.setInterval(run,9000);
  run();
  return()=>{window.removeEventListener('focus',run);
    document.removeEventListener('visibilitychange',run);window.clearInterval(timer)}
 },[started,prepared?.ticket]);

 return {open,setOpen,email,changeEmail,busy,error,prepared,started,statusText,
   launch,checkStatus:()=>void checkStatus(),reopen,copyForSafari,copyHint,manualLink,
   cancelAttempt,cancelBusy,hasOrder,
   retry:()=>{setError('');setRetry(v=>v+1)}};
}
