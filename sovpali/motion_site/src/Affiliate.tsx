import React,{useEffect,useState} from 'react';
import {ArrowUpRight,Check,Copy,RefreshCw,Users,Gift,Clock3,ShieldCheck,Share2,Wallet,ChevronRight} from 'lucide-react';
import './Affiliate.css';

type Award={request_id:string;amount_kopecks:number;status:string;requested_at:string};
type Stats={referral_url:string;rate_percent:number;invited_count:number;total_kopecks:number;available_kopecks:number;pending_kopecks:number;requested_kopecks:number;paid_kopecks:number;hold_days:number;minimum_payout_kopecks:number;payout_requests:Award[]};
type Api=(path:string,body?:object)=>Promise<any>;
const rub=(v:number)=>new Intl.NumberFormat('ru-RU',{minimumFractionDigits:0,maximumFractionDigits:2}).format(v/100)+' ₽';

export default function Affiliate({api,demo=false}:{api:Api;demo?:boolean}){
 const [data,setData]=useState<Stats|null>(null);
 const [error,setError]=useState('');
 const [busy,setBusy]=useState(false);
 const [copied,setCopied]=useState(false);
 const [legal,setLegal]=useState('ip');
 const [processing,setProcessing]=useState(false);
 const load=async()=>{if(demo){setError('В демоверсии реферальная ссылка недоступна.');return}
  setBusy(true);setError('');try{setData(await api('/s/app/api/affiliate'))}catch(e){setError((e as Error).message)}finally{setBusy(false)}};
 useEffect(()=>{load()},[]);
 const copy=async()=>{if(!data?.referral_url)return;try{await navigator.clipboard.writeText(data.referral_url);setCopied(true)}catch{
  const el=document.createElement('textarea');el.value=data.referral_url;el.style.position='fixed';el.style.left='-9999px';document.body.appendChild(el);el.select();
  try{setCopied(document.execCommand('copy'))}catch{setError('Не удалось скопировать ссылку. Нажми на неё и скопируй вручную.')}el.remove();
 }};
 const share=()=>{if(!data?.referral_url)return;const url='https://t.me/share/url?url='+encodeURIComponent(data.referral_url)+'&text='+encodeURIComponent('«Совпали» — знакомства по астрологии, нумерологии и совместимости. Присоединяйся!');
  const tg=(window as any).Telegram?.WebApp;
  if(tg?.openTelegramLink)tg.openTelegramLink(url);else window.open(url,'_blank','noopener,noreferrer');
 };
 const payout=async()=>{if(processing)return;setProcessing(true);setError('');try{await api('/s/app/api/affiliate/request',{legal_status:legal});await load()}catch(e){setError((e as Error).message)}finally{setProcessing(false)}};
 return <div className="affiliate-page">
  <div className="affiliate-intro"><span className="eyebrow">ПАРТНЁРСКАЯ ПРОГРАММА</span><h1>Совпадения<br/><em>приносят больше.</em></h1><p>Приглашай людей в «Совпали» и получай часть оплат, которые они совершают в приложении.</p></div>
  <div className="affiliate-hero"><div className="affiliate-hero-top"><span>ТВОЁ ВОЗНАГРАЖДЕНИЕ</span><Gift size={24}/></div><div className="affiliate-rate">30<span>%</span></div><p>От каждой подтверждённой оплаты приглашённого человека. Включая повторные покупки.</p><div className="affiliate-orbit" aria-hidden="true"/></div>
  <div className="affiliate-link-section"><div className="affiliate-row-title"><span>Твоя персональная ссылка</span><Share2 size={17}/></div>
    <div className="affiliate-referral-link">{data?.referral_url?<a href={data.referral_url} target="_blank" rel="noopener noreferrer">{data.referral_url}</a>:<span>{busy?'Создаём ссылку…':'Ссылка недоступна'}</span>}</div>
    <div className="affiliate-actions"><button className="affiliate-copy" disabled={!data?.referral_url} onClick={copy}>{copied?<Check size={17}/>:<Copy size={17}/>} {copied?'Скопировано':'Скопировать'}</button><button className="affiliate-share" disabled={!data?.referral_url} onClick={share}><Share2 size={17}/> Поделиться</button></div>
  </div>
  <div className="affiliate-row-title" style={{marginTop:35}}><span>Твоя статистика</span><button type="button" className="affiliate-refresh" onClick={load} disabled={busy} aria-label="Обновить статистику"><RefreshCw size={17}/></button></div>
  <div className="affiliate-stats">
    <div><Users size={18}/><span>Приглашено</span><strong>{data?.invited_count??'—'}</strong></div>
    <div><Wallet size={18}/><span>Начислено за всё время</span><strong>{data?rub(data.total_kopecks):'—'}</strong></div>
    <div><Check size={18}/><span>Доступно к выплате</span><strong>{data?rub(data.available_kopecks):'—'}</strong></div>
    <div><Clock3 size={18}/><span>Ожидает подтверждения срока</span><strong>{data?rub(data.pending_kopecks):'—'}</strong></div>
  </div>
  <div className="affiliate-payout"><div className="affiliate-row-title"><span>Получить вознаграждение</span><ShieldCheck size={18}/></div>
   <p>Выплаты оформляются вручную после проверки документов. Начисления становятся доступными через {data?.hold_days||14} дней после подтверждённой оплаты. Минимальная заявка — {rub(data?.minimum_payout_kopecks||100000)}.</p>
   <label htmlFor="affiliate-legal">Как оформлен партнёр?</label>
   <select id="affiliate-legal" value={legal} onChange={e=>setLegal(e.target.value)}><option value="ip">Индивидуальный предприниматель</option><option value="company">Юридическое лицо</option></select>
   <button className="affiliate-request" onClick={payout} disabled={processing||!data||data.available_kopecks<(data.minimum_payout_kopecks||100000)}>{processing?'Оформляем заявку…':'Запросить выплату'}<ChevronRight size={17}/></button>
   <p className="affiliate-legal-note">Деньги не переводятся автоматически. До выплаты потребуется договор и документы. Для физических лиц и самозанятых условия нужно согласовать отдельно.</p>
  </div>
  {data?.requested_kopecks? <p className="affiliate-note">Ожидает перечисления: <b>{rub(data.requested_kopecks)}</b>. Уже выплачено: <b>{rub(data.paid_kopecks)}</b>.</p>:null}
  {data?.payout_requests?.length?<div className="affiliate-history"><h3>Заявки на выплату</h3>{data.payout_requests.map(p=><div key={p.request_id}><span>{new Date(p.requested_at).toLocaleDateString('ru-RU')} · {p.status==='paid'?'Выплачено':'На проверке'}</span><b>{rub(p.amount_kopecks)}</b></div>)}</div>:null}
  {error&&<p className="affiliate-error" role="alert">{error}</p>}
  <p className="affiliate-foot">Комиссия рассчитывается только по оплаченным банковским заказам. Тестовые операции, отменённые и возвращённые платежи не включаются; при возврате уже выплаченного вознаграждения потребуется перерасчёт.</p>
 </div>;
}