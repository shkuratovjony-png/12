import React,{useEffect,useRef,useState} from 'react';
import {Heart,Sparkles,UserRound,ArrowLeft,ArrowUpRight,ChevronRight,ChevronDown,Check,Clock3,MapPin,ShieldCheck,RefreshCw,Pencil,LockKeyhole,X,MessageCircle,Gift,Mail} from 'lucide-react';
import {telegram,isMiniApp,haptic} from './telegram';
import {useBrowserCheckout} from './useBrowserCheckout';
import './Cabinet.css';
import Affiliate from './Affiliate';
import PortraitChooser from './PortraitChooser';
import TimeWheel from './TimeWheel';
import './CheckoutModal.css';
import './Onboarding.css';
export type Person={name:string;age:number|null;city:string;goal:string;priority:string;photo:string|null};
type Factor={n:string;tag:string;title:string;score:number;copy:string;basis:string};
export type Pair={demo:boolean;premium_path?:string;premium_active?:boolean;pair_key?:string;candidate_id?:number;score:number;viewer:Person;candidate:Person;factors:Factor[];reasons:string[];astro:string;numerology:string;price?:number;request_status:string;request_path?:string;engagement_path?:string;checkout_path?:string;contact_url?:string;payments_enabled:boolean;contact_credit_available?:boolean;incoming_request_id?:number|null};
type Card={id:number;person:Person;score:number;reason:string;status:string;token?:string};
type Profile=Person&{gender:string;birth_date:string;birth_place:string;username:string};
export type CabinetData={profile:Profile|null;suggestions:Card[];history:Card[];purchases:{sku:string;amount_kopecks:number;status:string;created_at:string}[];premium_active:boolean;premium_until?:string;credits:number;premium_path?:string;support_url?:string;bot_url?:string;goals:string[];priorities:string[]};
type Tab='discover'|'pairs'|'profile'|'affiliate';
const labels:Record<string,string>={ready:'Разбор открыт',pending:'Ждём ответа',incoming:'Ответь на запрос в боте',accepted:'Знакомство подтверждено',accepted_target:'Знакомство подтверждено',processing:'Оплачено · отправляем запрос',error:'Статус уточняется'};
const products:Record<string,string>={contact:'Запрос на знакомство',premium:'Premium · 30 дней'};
const money=(x:number)=>new Intl.NumberFormat('ru-RU').format(x)+' ₽';
const date=(x?:string)=>x?new Date(x).toLocaleDateString('ru-RU'):'';
export async function api(path:string,body:object={}){
 const response=await fetch(path,{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-Telegram-Init-Data':telegram()?.initData||''},body:JSON.stringify(body),signal:AbortSignal.timeout(20000)});
 const result=await response.json().catch(()=>null);
 if(!response.ok)throw new Error(result?.message||(response.status===401?'Сессия закончилась. Открой приложение заново из бота.':response.status===404?'Эта пара сейчас недоступна. Обнови подбор.':'Не удалось загрузить данные. Попробуй ещё раз.'));
 return result;
}
function go(url?:string){if(!url)return;const tg=telegram();if(isMiniApp()&&url.startsWith('https://t.me/'))tg.openTelegramLink(url);else if(isMiniApp()&&(url.startsWith('/billing/')||url.startsWith('/coach/')))tg.openLink(new URL(url,location.origin).href);else window.location.assign(url);}
function Photo({person,className=''}:{person:Person;className?:string}){const[failed,setFailed]=useState(false);useEffect(()=>setFailed(false),[person.photo]);return <div className={'photo '+className}>{person.photo&&!failed?<img src={person.photo} alt={person.name} decoding="async" onError={()=>setFailed(true)}/>:<div className="photo-placeholder"><UserRound size={42} strokeWidth={1}/><span>{person.name}</span><small>Фото не добавлено</small></div>}</div>}
function Empty({title,children,icon='heart'}:{title:string;children:React.ReactNode;icon?:string}){return <div className="empty"><span>{icon==='profile'?<UserRound/>:<Heart/>}</span><h2>{title}</h2><p>{children}</p></div>}
function PairCard({card,onOpen,history=false}:{card:Card;onOpen:()=>void;history?:boolean}){return <button className={'pair-card '+(history?'history-card':'')} onClick={onOpen}><Photo person={card.person}/><div className="card-content"><div className="card-name"><h2>{card.person.name}{card.person.age?', '+card.person.age:''}</h2><span className="score-pill">{card.score}%</span></div><p className="city"><MapPin size={13}/>{card.person.city}</p>{history?<p className={'status '+card.status}>{labels[card.status]||'Разбор пары'}</p>:<><p className="card-goal">{card.person.goal}</p><p className="card-reason">{card.reason}</p></>}<span className="card-open">{'Полный разбор'}<ArrowUpRight size={17}/></span></div></button>}
function PairView({pair,onBack,onUpdate,botUrl,onRefresh,onNext,onBrowse,onSkip,skipBusy,nextAvailable}:{pair:Pair;onBack:()=>void;onUpdate:(p:Pair)=>void;botUrl?:string;onRefresh:()=>void;onNext:()=>void;onBrowse:()=>void;onSkip:()=>void;skipBusy:boolean;nextAvailable:boolean}){
 const [displayScore,setDisplayScore]=useState(pair.score),[firstReveal,setFirstReveal]=useState(false);
 const [filled,setFilled]=useState(false),[busy,setBusy]=useState(false),[notice,setNotice]=useState('');
 const [decisionBusy,setDecisionBusy]=useState(false);
 const incoming=pair.request_status==='incoming'&&Boolean(pair.incoming_request_id);
 const checkout=useBrowserCheckout('contact',pair.candidate_id||null,()=>{
  onUpdate({...pair,request_status:'pending'});
  setNotice('Оплата подтверждена. Запрос на общение отправлен. Ответ придёт в Telegram.');
 });
 const reasons=useRef<HTMLDivElement>(null);
 const key=pair.pair_key||pair.engagement_path||'demo';
 useEffect(()=>{let seen=false;try{seen=sessionStorage.getItem('pair-revealed:'+key)==='1'}catch{};
 if(seen||matchMedia('(prefers-reduced-motion: reduce)').matches){setFilled(true);setDisplayScore(pair.score);setFirstReveal(false);return}
 setFirstReveal(true);setFilled(false);setDisplayScore(0);let frame=0;let start=0;
 const tick=(now:number)=>{if(!start)start=now;const progress=Math.min(1,(now-start)/1200);setDisplayScore(Math.round(pair.score*(1-Math.pow(1-progress,3))));if(progress<1)frame=requestAnimationFrame(tick)};
 const t=setTimeout(()=>{setFilled(true);frame=requestAnimationFrame(tick);try{sessionStorage.setItem('pair-revealed:'+key,'1')}catch{}},80);
 return()=>{clearTimeout(t);cancelAnimationFrame(frame)}},[key,pair.score]);
 useEffect(()=>{if(!pair.engagement_path||pair.demo||!reasons.current)return;let done=false;const observer=new IntersectionObserver(entries=>{if(done||!entries.some(e=>e.isIntersecting))return;done=true;observer.disconnect();fetch(pair.engagement_path!,{method:'POST',credentials:'same-origin',keepalive:true}).catch(()=>{});},{threshold:.2});observer.observe(reasons.current);return()=>observer.disconnect()},[key]);
 const status=pair.request_status;
 const ready=status==='ready';
 const respondToIncoming=async(decision:'accept'|'decline')=>{
  if(!incoming||decisionBusy||!pair.incoming_request_id)return;
  haptic();setDecisionBusy(true);setNotice('');
  try{
   const result=await api('/s/app/api/incoming/respond',{request_id:pair.incoming_request_id,decision});
   onUpdate({...pair,request_status:decision==='accept'?'accepted_target':'declined',incoming_request_id:null});
   setNotice(result.message||'Ответ сохранён.');
  }catch(e){setNotice((e as Error).message)}
  finally{setDecisionBusy(false)}
 };
 const label=status==='accepted'&&pair.contact_url?'Написать в Telegram':ready?(pair.contact_credit_available?'Использовать оплаченный запрос':(pair.demo||pair.payments_enabled)?'Предложить общение · '+money(pair.price||100):'Предложить общение'):labels[status]||'Обновить статус';
 const action=async()=>{
  if(busy)return;haptic();
  if(status==='accepted'&&pair.contact_url){go(pair.contact_url);return}
  if(!ready){if(status==='incoming'||status==='accepted_target'||status==='accepted'){go(botUrl);return}onRefresh();return}
  if(pair.demo){setNotice('Это демонстрация. Настоящее предложение можно отправить из своей пары в боте.');return}
  if(pair.contact_credit_available||pair.premium_active){
   setBusy(true);setNotice('');
   try{
    const response=await fetch('/s/app/api/checkout/redeem',{
      method:'POST',credentials:'same-origin',
      headers:{'Content-Type':'application/json','X-Telegram-Init-Data':telegram()?.initData||''},
      body:JSON.stringify({candidate_id:pair.candidate_id})
    });
    const data=await response.json().catch(()=>null);
    if(!response.ok)throw new Error(data?.message||'Не удалось отправить запрос.');
    onUpdate({...pair,request_status:'pending'});
    setNotice(data?.message||'Запрос отправлен. Ответ придёт в Telegram.');
   }catch(e){setNotice((e as Error).message)}
   finally{setBusy(false)}
   return;
  }
  if(pair.payments_enabled&&pair.checkout_path){checkout.setOpen(true);return}
  if(!pair.request_path)return;
  setBusy(true);setNotice('');
  try{const response=await fetch(pair.request_path,{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:'{}'});const data=await response.json();if(['sent','pending','incoming','accepted'].includes(data.status))onUpdate({...pair,request_status:data.status==='sent'?'pending':data.status});setNotice(data.message||'Проверь статус запроса.');}catch{setNotice('Нет подтверждения отправки. Обнови статус перед повторной попыткой.')}finally{setBusy(false)}
 };
 return <><div className="pair-toolbar"><button className="icon-button" onClick={onBack} aria-label="Назад"><ArrowLeft size={21}/></button><div><span className="eyebrow">ЛИЧНОЕ СОВПАДЕНИЕ</span><p>Полный разбор пары</p></div><button className="icon-button" onClick={onRefresh} aria-label="Обновить статус пары"><RefreshCw size={18}/></button></div>
 <div className="pair-person"><Photo person={pair.candidate}/><div><h1>{pair.candidate.name}{pair.candidate.age?', '+pair.candidate.age:''}</h1><p className="city"><MapPin size={14}/>{pair.candidate.city}</p><span className="goal-tag">{pair.candidate.goal}</span></div></div>
 {!incoming&&<section className="browse-bridge" aria-label="Выбор другой анкеты">
   <span className="eyebrow">САМОСТОЯТЕЛЬНЫЙ ПОДБОР</span>
   <h2>Не подошёл? Выбирай дальше.</h2>
   <p>Смотри фотографии и совместимость до оплаты. Если есть подходящие анкеты, покажем до трёх вариантов.</p>
   <div className="browse-bridge-actions">
    <button className="browse-bridge-next" type="button" onClick={nextAvailable?onNext:onBrowse}>
      {nextAvailable?'Следующая анкета':'Открыть подбор'} <ArrowUpRight size={17}/>
    </button>
    <button className="browse-bridge-all" type="button" onClick={onBrowse}>Мой ТОП-3</button>
   </div>
   {ready&&<button className="browse-bridge-skip" type="button" onClick={onSkip} disabled={skipBusy}>
     {skipBusy?'Подбираем другого…':'Не подходит · убрать из моего подбора'}
   </button>}
  </section>}
 <section className={"report-card "+(firstReveal?"report-reveal":"")}><div className="report-title"><div><span className="eyebrow">ВАШИ ПЕРЕСЕЧЕНИЯ</span><h2>Почему вы подходите</h2></div><div className="overall" aria-label={'Совместимость '+pair.score+'%'}><svg viewBox="0 0 100 100" aria-hidden="true"><circle className="score-track" cx="50" cy="50" r="43"/><circle className="score-progress" cx="50" cy="50" r="43" pathLength="100" strokeDasharray="100" strokeDashoffset={100-displayScore}/></svg><span>{displayScore}<small>%</small></span></div></div><p className="report-caption">Индекс совместимости по модели «Совпали»</p>
 <div className={'factors '+(filled?'filled':'')}>{pair.factors.map((f,i)=><div className="factor" key={f.n} style={{'--delay':i*110+'ms'} as React.CSSProperties}><div className="factor-label"><span><i className="factor-index">{String(i+1).padStart(2,'0')}</i>{f.tag}</span><strong>{i<2?(f.score===100?'Совпадают':'Различаются'):f.score+'%'}</strong></div><div className="bar"><i style={{width:filled?Math.max(0,Math.min(100,f.score))+'%':'0%'}}/></div></div>)}</div><p className="footnote">Цели и ценности — из анкет. Астрология и нумерология — символические интерпретации, а не прогноз отношений.</p></section>
 <section className="why-card" ref={reasons}><div className="section-title"><span className="round-icon"><Heart size={19}/></span><h2>Почему вы подошли</h2></div><ol>{pair.reasons.map((r,i)=><li key={i}><span>{String(i+1).padStart(2,'0')}</span><p>{r}</p></li>)}</ol></section>
 <div className="detail-list">{pair.factors.map(f=><details key={f.n} onToggle={e=>{if(e.currentTarget.open)haptic()}}><summary><span>{f.tag}</span><ChevronDown size={17}/></summary><div><h3>{f.title}</h3><p>{f.copy}</p><small>{f.basis}</small></div></details>)}</div>
 <div className="consent-note"><ShieldCheck size={20}/><p>Решение всегда за вами. Контакт открывается после согласия на знакомство.</p></div>
 {notice&&<div className="notice" role="status">{notice}</div>}
 {incoming?<section className="pair-action" aria-label="Ответ на предложение">
   <p>Этот человек уже предложил тебе знакомство. Ты посмотрел(а) совместимость — теперь решение за тобой. Контакт откроется инициатору только если ты согласишься.</p>
   <button type="button" className="primary" disabled={decisionBusy} onClick={()=>void respondToIncoming('accept')}>
    {decisionBusy?'Сохраняем ответ…':'❤️ Да, хочу познакомиться'} <Heart size={18}/>
   </button>
   <button type="button" className="checkout-dismiss-inline" style={{width:'100%',fontSize:14}}
     disabled={decisionBusy} onClick={()=>void respondToIncoming('decline')}>Не хочу знакомиться</button>
  </section>:<div className="pair-action">
    {status!=='accepted_target'&&status!=='declined'&&<button className="primary" disabled={busy||status==='pending'||status==='processing'} onClick={action}>{busy?'Отправляем…':label}{status==='accepted'?<MessageCircle size={18}/>:ready?<ArrowUpRight size={18}/>:<Clock3 size={18}/>}</button>}
    <p>{ready?'Отправим предложение. Контакт откроется после согласия.':status==='pending'?'Мы сообщим об ответе в Telegram. Повторная оплата не нужна.':status==='processing'?'Покупка подтверждена. Обнови статус чуть позже.':status==='accepted_target'?'Ты согласился(ась). Первым напишет человек, который предложил познакомиться.':status==='declined'?'Предложение отклонено. Контакт не раскрывался.':'Статус знакомства сохранён в «Мои пары».'}</p>
   </div>}
 {checkout.open&&<div className="checkout-overlay" role="presentation" onMouseDown={e=>{if(e.target===e.currentTarget&&!checkout.busy)checkout.setOpen(false)}}>
  <section className="checkout-panel" role="dialog" aria-modal="true" aria-labelledby="checkout-title">
   <button type="button" className="checkout-dismiss" onClick={()=>checkout.setOpen(false)} disabled={checkout.busy} aria-label="Закрыть"><X size={20}/></button>
   <div className="checkout-emblem"><Heart size={22}/></div>
   <span className="checkout-overline">ОФОРМЛЕНИЕ ЗНАКОМСТВА</span>
   <h2 id="checkout-title">Шаг навстречу<br/><em>{pair.candidate.name}</em></h2>
   <p className="checkout-lead">100 ₽ — один контакт после согласия. Если человек откажет или не ответит за 24 часа, сможешь выбрать другую пару без доплаты.</p>
   <form className="checkout-form" onSubmit={checkout.launch}>
     <label htmlFor="checkout-email"><Mail size={17}/> Электронная почта для чека</label>
     <input id="checkout-email" type="email" inputMode="email" autoComplete="email" maxLength={120} required
       value={checkout.email} onChange={e=>checkout.changeEmail(e.target.value)}
       placeholder="name@example.ru" disabled={checkout.busy||checkout.started}/>
     <small>Чек придёт на указанный email. Оплата картой или СБП — на странице Ozon во внешнем браузере.</small>
     {checkout.error&&<p className="checkout-error" role="alert">{checkout.error}</p>}
     {checkout.started?<div className="checkout-recovery">
       <p role="status" className="checkout-lead">{checkout.statusText}</p>
       <button type="button" className="checkout-confirm" onClick={checkout.reopen}>Открыть оплату ещё раз <ArrowUpRight size={18}/></button>
       <button type="button" className="checkout-recovery-link" onClick={checkout.copyForSafari}>Скопировать ссылку Ozon для Safari</button>
       {checkout.copyHint&&<small role="status" className="checkout-recovery-hint">{checkout.copyHint}</small>}
       {checkout.manualLink&&<input className="checkout-manual-link" value={checkout.manualLink}
         readOnly aria-label="Платёжная ссылка Ozon, выдели и скопируй"
         onFocus={e=>e.currentTarget.select()}/>}
       <button type="button" className="checkout-dismiss-inline" onClick={checkout.checkStatus}>Проверить статус оплаты</button>
       {checkout.hasOrder&&<small>Заказ уже создан в Ozon. Его email нельзя изменить, пока платёж ожидает подтверждения. Повторно оплачивать не нужно.</small>}
       <button type="button" className="checkout-recovery-link" onClick={checkout.cancelAttempt} disabled={checkout.cancelBusy}>
         {checkout.cancelBusy?'Проверяем заказ…':'Отменить оформление / изменить email'}
       </button>
       <button type="button" className="checkout-dismiss-inline" onClick={()=>checkout.setOpen(false)}>Вернуться к анкете</button>
     </div>:<>
       <button type="submit" className="checkout-confirm" disabled={checkout.busy||!checkout.prepared}>
         {checkout.busy?'Готовим оплату…':'Оплатить 100 ₽'} <ArrowUpRight size={19}/>
       </button>
       {checkout.error&&!checkout.busy&&<button type="button" className="checkout-dismiss-inline" onClick={checkout.retry}>Попробовать ещё раз</button>}
     </>}
   </form>
   <p className="checkout-safe"><ShieldCheck size={15}/> Оплата на защищённой странице Ozon. Реквизиты карты мы не получаем.</p>
  </section>
 </div>}
 {!incoming&&status!=='accepted_target'&&status!=='declined'&&<PremiumCard path={pair.premium_path} active={pair.premium_active} demo={pair.demo}/>}</>;
}
function PremiumCard({path,active=false,until,demo=false}:{path?:string;active?:boolean;until?:string;demo?:boolean}){
 const checkout=useBrowserCheckout('premium',null,()=>{
  window.location.reload(); // Server-verified Premium grant; refresh the cabinet immediately.
 });
 const [error,setError]=useState('');
 const open=checkout.open,setOpen=checkout.setOpen,busy=checkout.busy;
 return <><section className="premium-card">
  <span className="eyebrow"><Sparkles size={15}/> СОВПАЛИ PREMIUM</span>
  <h2>{active?'Твой Premium активен':'Больше знакомств. Один доступ.'}</h2>
  <p>{active&&until?'Действует до '+date(until):'1 200 ₽ / 30 дней'}</p>
  <ul><li>До 3 запросов на знакомство в сутки.</li><li>Без отдельной оплаты каждого запроса.</li><li>Контакт открывается только после согласия второй стороны.</li></ul>
  <button className="primary" disabled={active||!path&&!demo} onClick={()=>{if(demo){setError('В демоверсии оплата недоступна.');return}setError('');setOpen(true)}}>{active?'Premium подключён':'Оформить Premium · 1 200 ₽'}<ArrowUpRight size={18}/></button>
  <small>{active?'Без автоматического продления.':'30 дней, без автоматического продления. Лимит обновляется каждый день.'}</small>
  {error&&!open&&<p role="status">{error}</p>}
 </section>
 {open&&<div className="checkout-overlay" role="presentation" onMouseDown={e=>{if(e.target===e.currentTarget&&!busy)setOpen(false)}}>
  <section className="checkout-panel" role="dialog" aria-modal="true" aria-labelledby="premium-checkout-title">
   <button className="checkout-dismiss" type="button" disabled={busy} aria-label="Закрыть" onClick={()=>setOpen(false)}><X size={20}/></button>
   <div className="checkout-emblem"><Sparkles size={22}/></div>
   <span className="checkout-overline">СОВПАЛИ PREMIUM</span>
   <h2 id="premium-checkout-title">Больше встреч.<br/><em>Без доплат.</em></h2>
   <p className="checkout-lead">1 200 ₽ на 30 дней. До трёх запросов на знакомство ежедневно. Контакты открываются после согласия.</p>
   <form className="checkout-form" onSubmit={checkout.launch}>
    <label htmlFor="premium-receipt-email"><Mail size={17}/> Электронная почта для чека</label>
    <input id="premium-receipt-email" type="email" inputMode="email" autoComplete="email" maxLength={120} required
      placeholder="name@example.ru" value={checkout.email} onChange={e=>checkout.changeEmail(e.target.value)}
      disabled={checkout.busy||checkout.started}/>
    <small>Чек на почту. Картой или СБП можно оплатить на странице Ozon во внешнем браузере.</small>
    {checkout.error&&<p role="alert" className="checkout-error">{checkout.error}</p>}
    {checkout.started?<div className="checkout-recovery">
      <p role="status" className="checkout-lead">{checkout.statusText}</p>
      <button type="button" className="checkout-confirm" onClick={checkout.reopen}>Открыть оплату ещё раз <ArrowUpRight size={18}/></button>
      <button type="button" className="checkout-recovery-link" onClick={checkout.copyForSafari}>Скопировать ссылку Ozon для Safari</button>
      {checkout.copyHint&&<small role="status" className="checkout-recovery-hint">{checkout.copyHint}</small>}
       {checkout.manualLink&&<input className="checkout-manual-link" value={checkout.manualLink}
         readOnly aria-label="Платёжная ссылка Ozon, выдели и скопируй"
         onFocus={e=>e.currentTarget.select()}/>}
      <button type="button" className="checkout-dismiss-inline" onClick={checkout.checkStatus}>Проверить статус Premium</button>
      {checkout.hasOrder&&<small>Заказ уже создан в Ozon. Email нельзя изменить, пока платёж ожидает подтверждения. Не оплачивай второй раз.</small>}
      <button type="button" className="checkout-recovery-link" onClick={checkout.cancelAttempt} disabled={checkout.cancelBusy}>
        {checkout.cancelBusy?'Проверяем заказ…':'Отменить оформление / изменить email'}
      </button>
      <button type="button" className="checkout-dismiss-inline" onClick={()=>checkout.setOpen(false)}>Вернуться в профиль</button>
    </div>:<>
      <button type="submit" className="checkout-confirm" disabled={checkout.busy||!checkout.prepared}>
       {checkout.busy?'Готовим оплату…':'Оплатить 1 200 ₽'} <ArrowUpRight size={19}/>
      </button>
      {checkout.error&&!checkout.busy&&<button type="button" className="checkout-dismiss-inline" onClick={checkout.retry}>Попробовать ещё раз</button>}
    </>}
   </form>
   <p className="checkout-safe"><ShieldCheck size={15}/> Платёж на защищённой странице Ozon. Без автопродления.</p>
  </section>
 </div>}
 </>;
}
function ProfileEditor({data,onSave,onCancel,demo}:{data:CabinetData;onSave:(p:Profile)=>void;onCancel:()=>void;demo:boolean}){
 const p=data.profile!;const [form,setForm]=useState({name:p.name,birth_date:p.birth_date,birth_place:p.birth_place,city:p.city,goal:p.goal,priority:p.priority});const[busy,setBusy]=useState(false),[error,setError]=useState('');
 const field=(key:keyof typeof form,value:string)=>setForm({...form,[key]:value});
 return <section className="editor"><div className="section-title"><h2>Редактировать анкету</h2><button className="icon-button" onClick={onCancel} aria-label="Закрыть редактор"><X size={20}/></button></div><form onSubmit={async e=>{e.preventDefault();setError('');setBusy(true);try{if(demo){onSave({...p,...form});return}const result=await api('/s/app/api/profile',form);onSave(result.profile)}catch(e){setError((e as Error).message)}finally{setBusy(false)}}}>
 <label>Имя<input required maxLength={90} value={form.name} onChange={e=>field('name',e.target.value)}/></label><label>Дата рождения<input required inputMode="numeric" placeholder="ДД.ММ.ГГГГ" value={form.birth_date} onChange={e=>field('birth_date',e.target.value)}/></label><label>Место рождения<input required maxLength={90} value={form.birth_place} onChange={e=>field('birth_place',e.target.value)}/></label><label>Город проживания<input required maxLength={90} value={form.city} onChange={e=>field('city',e.target.value)}/></label><label>Цель знакомства<select value={form.goal} onChange={e=>field('goal',e.target.value)}>{data.goals.map(x=><option key={x}>{x}</option>)}</select></label><label>Главное в отношениях<select value={form.priority} onChange={e=>field('priority',e.target.value)}>{data.priorities.map(x=><option key={x}>{x}</option>)}</select></label><p className="footnote">Обновлённые данные будут использоваться действующим алгоритмом подбора.</p>{error&&<p className="error" role="alert">{error}</p>}<button className="primary" disabled={busy}>{busy?'Сохраняем…':'Сохранить изменения'}<Check size={18}/></button></form></section>;
}
function ExtraProfile({onClose}:{onClose:()=>void}){
 const [state,setState]=useState({birth_time:'',lifestyle:'',relationship_style:'',family_plan:''}),[saving,setSaving]=useState(false),[message,setMessage]=useState('');
 useEffect(()=>{api('/s/app/api/natal-extra').then(d=>setState(v=>({...v,...d.values}))).catch(e=>setMessage(e.message))},[]);
 const choose=(key:keyof typeof state,items:string[])=> <div className="on-choices">{items.map(x=><button type="button" key={x} className={'on-choice '+(state[key]===x?'active':'')} onClick={()=>setState(v=>({...v,[key]:x}))}>{x}{state[key]===x?<Check size={17}/>:null}</button>)}</div>;
 return <section className="editor"><div className="section-title"><h2>Твоя глубокая совместимость</h2><button className="icon-button" onClick={onClose} aria-label="Закрыть"><X/></button></div><p className="muted">Дополнительные ответы будут участвовать в подборе. Для точной натальной карты укажи время рождения, если знаешь.</p>
 <div className="on-field" style={{marginTop:24}}><label>Время рождения <span>необязательно</span></label><TimeWheel value={state.birth_time} onChange={time=>setState(v=>({...v,birth_time:time}))}/></div>
 <div className="on-triples"><div><label>Твой темп жизни</label>{choose('lifestyle',['Активный','Домашний','Баланс'])}</div><div><label>Как обсуждаешь разногласия?</label>{choose('relationship_style',['Обсуждаю сразу','Нужно время','Спокойный диалог'])}</div><div><label>Планы на семью</label>{choose('family_plan',['Хочу семью и детей','Семья без детей','Пока не решил'])}</div></div>
 {message&&<p className="notice" role="status">{message}</p>}
 <button className="primary" style={{marginTop:28}} disabled={saving} onClick={async()=>{setSaving(true);setMessage('');try{await api('/s/app/api/natal-extra',state);onClose()}catch(e){setMessage((e as Error).message)}finally{setSaving(false)}}}>{saving?'Сохраняем…':'Сохранить совместимость'}<Check size={18}/></button>
 <p className="footnote" style={{marginTop:16}}>Астрологические и нумерологические выводы — символический разбор, не прогноз отношений.</p></section>
}
function ProfileView({data,onSave,onPhotoChanged,demo}:{data:CabinetData;onSave:(p:Profile)=>void;onPhotoChanged:()=>void;demo:boolean}){
 const [editing,setEditing]=useState(false),[enhancing,setEnhancing]=useState(false);const p=data.profile;
 if(!p)return <><Empty title="Давай познакомимся" icon="profile">Заполни анкету в боте. После этого здесь появятся твой профиль и подходящие люди.</Empty><button className="primary" onClick={()=>go(data.bot_url)}>Перейти в бот<ArrowUpRight size={18}/></button></>;
 if(enhancing)return <ExtraProfile onClose={()=>setEnhancing(false)}/>;
 if(editing)return <ProfileEditor data={data} demo={demo} onSave={p=>{onSave(p);setEditing(false)}} onCancel={()=>setEditing(false)}/>;
 return <><div className="profile-top"><Photo person={p}/>{!demo&&<details className="profile-photo-manager"><summary>Добавить или изменить фотографию</summary><PortraitChooser mode="profile" currentPhoto={p.photo} onSaved={onPhotoChanged}/></details>}<h1>{p.name}{p.age?', '+p.age:''}</h1>{p.username&&<p className="username">@{p.username}</p>}<p className="city"><MapPin size={14}/>{p.city}</p><button className="secondary" onClick={()=>setEditing(true)}><Pencil size={15}/>Редактировать анкету</button><button className="secondary" onClick={()=>setEnhancing(true)}><Sparkles size={15}/>Углубить совместимость</button></div><PremiumCard path={data.premium_path} active={data.premium_active} until={data.premium_until} demo={demo}/><section className="profile-info"><h2>Моя анкета</h2>{[['Цель знакомства',p.goal],['Главное в отношениях',p.priority],['Дата рождения',p.birth_date],['Место рождения',p.birth_place]].map(([label,value])=><div key={label}><span>{label}</span><strong>{value}</strong></div>)}<p className="footnote"><LockKeyhole size={13}/> Дату и место рождения здесь видишь только ты.</p></section>
 <section className="access-card"><div className="credit-line"><span>Оплаченные повторные запросы</span><strong>{data.credits}</strong></div></section>
 <section className="purchases"><h2>Мои покупки</h2>{data.purchases.length?data.purchases.map((p,i)=><div className="purchase" key={i}><div><strong>{products[p.sku]||'Архивная покупка'}</strong><span>{date(p.created_at)} · {p.status==='paid'?'Оплачено':p.status==='pending'?'Ожидает оплаты':p.status==='failed'?'Оплата не прошла':'Не завершено'}</span></div><b>{money(p.amount_kopecks/100)}</b></div>):<p className="muted">Пока нет покупок. Здесь будут их суммы и статусы.</p>}</section>
 <div className="profile-links">{data.support_url&&<button onClick={()=>go(data.support_url)}>Поддержка<ArrowUpRight size={17}/></button>}{data.bot_url&&<button onClick={()=>go(data.bot_url)}>Вернуться в бот<ArrowUpRight size={17}/></button>}</div></>;
}
export function demoCabinet(pair:Pair):CabinetData{return {profile:{...pair.viewer,name:'Александр',gender:'Мужчина',birth_date:'05.01.1990',birth_place:'Владивосток',username:'',photo:null},suggestions:[{id:2,person:pair.candidate,score:pair.score,reason:pair.reasons[0],status:'ready'}],history:[],purchases:[],premium_active:false,credits:0,goals:['Серьёзные отношения','Любовь и семья','Общение и знакомство','Пока присматриваюсь'],priorities:['Семья','Любовь','Ценности','Страсть','Опора']};}
export function Cabinet({initialPair,initialData,initialError='',initialReturnOrder}:{initialPair?:Pair;initialData?:CabinetData;initialError?:string;initialReturnOrder?:string}){
 const[pair,setPair]=useState<Pair|undefined>(initialPair),[data,setData]=useState(initialData),[tab,setTab]=useState<Tab>('discover'),[busy,setBusy]=useState(false),[error,setError]=useState(initialError),[filter,setFilter]=useState('all'),[skipBusy,setSkipBusy]=useState(false),[browseNotice,setBrowseNotice]=useState('');const seq=useRef(0);const demo=Boolean(initialPair?.demo);const demoPair=useRef(initialPair);
 const [paymentNotice,setPaymentNotice]=useState(initialReturnOrder?'Проверяем оплату…':'');
 const [paymentBusy,setPaymentBusy]=useState(Boolean(initialReturnOrder));
 const [paymentComplete,setPaymentComplete]=useState(false);
 const [paymentCheck,setPaymentCheck]=useState(0);
 const top=()=>window.scrollTo({top:0,behavior:'instant' as ScrollBehavior});
 const load=async()=>{if(demo)return;const id=++seq.current;setBusy(true);setError('');try{const d=await api('/s/app/api/cabinet');if(id===seq.current)setData(d)}catch(e){if(id===seq.current)setError((e as Error).message)}finally{if(id===seq.current)setBusy(false)}};
 const navigate=(next:Tab)=>{++seq.current;setBusy(false);haptic();setPair(undefined);setTab(next);setFilter('all');top();if(!data&&!demo&&isMiniApp())load()};
 // Telegram's startapp order is an untrusted identifier. The API checks
 // the signed Telegram user and verifies the bank before showing any result.
 useEffect(()=>{
  if(!initialReturnOrder||demo)return;
  let cancelled=false;
  const check=async()=>{
   setPaymentBusy(true);
   try{
    const result=await api('/s/app/api/checkout/return',{order_id:initialReturnOrder});
    if(cancelled)return;
    setPaymentNotice(String(result.message||'Проверяем платёж.'));
    setPaymentComplete(Boolean(result.paid&&result.delivered));
    if(result.paid){
     try{const updated=await api('/s/app/api/cabinet');if(!cancelled)setData(updated)}catch{}
     if(cancelled)return;
     if(result.sku==='premium'){setPair(undefined);setTab('profile')}
     else if(result.sku==='contact'&&result.candidate_id&&result.delivered){
      try{const detail=await api('/s/app/api/pair',{candidate_id:result.candidate_id});
       if(!cancelled){setPair(detail);setTab('pairs');top()}}
      catch{if(!cancelled){setPair(undefined);setTab('pairs')}}
     }
    }
   }catch(e){if(!cancelled)setPaymentNotice((e as Error).message)}
   finally{if(!cancelled)setPaymentBusy(false)}
  };
  void check();
  return()=>{cancelled=true}
 },[initialReturnOrder,paymentCheck]);
 const browse=()=>{navigate('discover');setBrowseNotice('');if(!demo)void load()};
 const nextPair=()=>{if(!pair)return;const choices=data?.suggestions||[];const current=choices.findIndex(c=>c.id===pair.candidate_id);const next=choices.length>1?choices[(current+1)%choices.length]:current===-1?choices[0]:undefined;if(next){void open(next)}else browse()};
 const skipPair=async()=>{
  if(!pair||skipBusy||pair.request_status!=='ready')return;
  if(demo){browse();setBrowseNotice('В демо нет новых реальных анкет.');return}
  const cid=pair.candidate_id;
  if(!cid){browse();return}
  setSkipBusy(true);setError('');
  try{
   await api('/s/app/api/browse/skip',{candidate_id:cid});
   setBrowseNotice('Анкета пропущена. Показываем следующие доступные варианты.');
   setData(old=>old?{...old,suggestions:old.suggestions.filter(c=>c.id!==cid),
     history:old.history.filter(c=>c.id!==cid||!['ready'].includes(c.status))}:old);
   navigate('discover');
   await load();
  }catch(e){setError((e as Error).message)}
  finally{setSkipBusy(false)}
 };
 const open=async(card:Card)=>{haptic();setError('');if(demo&&demoPair.current){setPair(demoPair.current);setData(d=>d?{...d,history:d.history.some(x=>x.id===card.id)?d.history:[card,...d.history]}:d);top();return}const id=++seq.current;setBusy(true);try{const p=await api('/s/app/api/pair',{candidate_id:card.id});if(id!==seq.current)return;setPair(p);setData(d=>d?{...d,history:d.history.some(x=>x.id===card.id)?d.history:[{...card,status:p.request_status},...d.history]}:d);top()}catch(e){if(id===seq.current)setError((e as Error).message)}finally{if(id===seq.current)setBusy(false)}};
 const refreshPair=async()=>{if(!pair)return;if(pair.request_status==='incoming'){location.reload();return}if(demo){setError('В демо показан пример. Реальные статусы доступны в твоём кабинете.');return}if(pair.candidate_id){await open({id:pair.candidate_id,person:pair.candidate,score:pair.score,reason:'',status:pair.request_status})}else location.reload()};
 const updatePair=(p:Pair)=>{setPair(p);setData(d=>d?{...d,history:d.history.map(c=>c.id===p.candidate_id?{...c,status:p.request_status}:c)}:d)};
 useEffect(()=>{const tg=telegram();if(!isMiniApp()||!tg.isVersionAtLeast('6.1'))return;const back=()=>{setPair(undefined);top()};tg.BackButton.onClick(back);pair?tg.BackButton.show():tg.BackButton.hide();return()=>{tg.BackButton.offClick(back);tg.BackButton.hide()}},[Boolean(pair)]);
 const history=(data?.history||[]).filter(c=>filter==='all'||(filter==='waiting'?['pending','processing'].includes(c.status):c.status==='accepted'));
 return <div className={'cabinet '+(pair?'has-pair':'')}><header className="app-header"><a href="#" onClick={e=>{e.preventDefault();navigate('discover')}} className="brand"><span>♡</span>совпали<span className="brand-dot">.</span></a><button className="premium-shortcut" onClick={()=>navigate('profile')}><Sparkles size={13}/>Премиум</button></header><main>
 {error&&<div className="notice error" role="alert"><p>{error}</p>{!demo&&<button onClick={load}>Повторить</button>}</div>}
 {initialReturnOrder&&<div className="notice" role="status" style={{marginBottom:15}}>
   <p>{paymentNotice||'Проверяем платёж…'}</p>
   {!paymentComplete&&<button type="button" disabled={paymentBusy} onClick={()=>setPaymentCheck(v=>v+1)}>
     {paymentBusy?'Проверяем…':'Обновить статус оплаты'}
   </button>}
 </div>}
 {busy&&<div className="loading-line" role="status"><span className="loading-spark"><Heart size={19}/></span><span>Открываем ваше совпадение<span className="loading-dots" aria-hidden="true">•••</span></span></div>}
 {pair?<PairView key={pair.pair_key||pair.engagement_path||'pair'} pair={pair} onBack={()=>navigate(tab)} onUpdate={updatePair} botUrl={data?.bot_url} onRefresh={refreshPair} onNext={nextPair} onBrowse={browse} onSkip={()=>void skipPair()} skipBusy={skipBusy} nextAvailable={Boolean(data?.suggestions.some(c=>c.id!==pair.candidate_id))}/>:<>
 {tab==='discover'&&<><div className="page-heading"><span className="eyebrow">ТВОЙ ВЫБОР · ДО 3 АНКЕТ</span><h1>Подбери сам<span>.</span></h1><p>Сначала посмотри фотографии и разбор совместимости. Платить за просмотр не нужно.</p></div><div className="list-heading"><span>Сейчас доступно {data?.suggestions.length||0} из 3</span><button className="text-button" onClick={demo?()=>setError('Это демонстрационный подбор.'):load} disabled={busy}><RefreshCw size={14}/>Обновить подбор</button></div>{browseNotice&&<div className="notice" role="status">{browseNotice}</div>}{data?.suggestions.length?<div className="cards">{data.suggestions.map(c=><PairCard key={c.id} card={c} onOpen={()=>open(c)}/>)}</div>:!busy&&<Empty title={data?.profile?'Нужно немного времени':'Твой подбор ещё впереди'}>{data?.profile?'Новые подходящие анкеты пока не найдены. Обнови подбор позже — бот также сообщит о новом совпадении.':'Открой приложение из бота и заполни свою анкету.'}</Empty>}<div className="small-tip"><Sparkles size={18}/><p>Это самостоятельный выбор: открой понравившуюся анкету, листай следующие или нажми «Не подходит». Пропуск бесплатный и не отправляет запрос другому человеку.</p></div></>}
 {tab==='pairs'&&<><div className="page-heading"><span className="eyebrow">ВАШИ ВОЗМОЖНЫЕ ИСТОРИИ</span><h1>Мои пары<span>.</span></h1><p>Сохраняем знакомства и их статусы.</p></div><div className="history-controls"><div className="filters">{[['all','Все'],['waiting','Ждём ответа'],['accepted','Подтверждены']].map(([id,label])=><button key={id} aria-pressed={filter===id} onClick={()=>{haptic();setFilter(id)}}>{label}</button>)}</div><button className="icon-button" disabled={busy} onClick={load} aria-label="Обновить мои пары"><RefreshCw size={17}/></button></div>{history.length?<div className="history-list">{history.map(c=><PairCard key={c.id} card={c} history onOpen={()=>open(c)}/>)}</div>:<Empty title={filter==='all'?'Здесь начнётся ваша история':'Пока нет таких знакомств'}>{filter==='all'?'Посмотренные пары и отправленные предложения будут сохраняться здесь.':'Когда статус знакомства изменится, ты увидишь его здесь.'}</Empty>}</>}
 {tab==='profile'&&(data?<ProfileView data={data} demo={demo} onPhotoChanged={()=>{setError('');load()}} onSave={p=>{setData({...data,profile:p});setError('');if(!demo)load()}}/>:<Empty title="Твой личный профиль" icon="profile">Открой приложение кнопкой «Открыть» в боте «Совпали».</Empty>)}
 {tab==='affiliate'&&<Affiliate api={api} demo={demo}/>}
 </>}
 </main><nav className="app-tabs" aria-label="Личный кабинет">{([['discover','Подбор',Sparkles],['pairs','Мои пары',Heart],['affiliate','Партнёрам',Gift],['profile','Профиль',UserRound]] as const).map(([id,label,Icon])=><button key={id} aria-current={tab===id?'page':undefined} onClick={()=>navigate(id)}><Icon size={22} strokeWidth={tab===id?1.9:1.5}/><span>{label}</span></button>)}</nav></div>;
}
