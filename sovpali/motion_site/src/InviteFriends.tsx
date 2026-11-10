import React,{useEffect,useState} from 'react';
import {ArrowUpRight,Check,Copy,Gift,Share2,Users,RefreshCw} from 'lucide-react';
import {telegram} from './telegram';
import './InviteFriends.css';

type Stats={
  referral_url:string;
  invited_count:number;
  qualified_count:number;
  pending_count:number;
  progress:number;
  needed:number;
  reward_every:number;
  rewards_earned:number;
  available_rewards:number;
};
type Props={api:(path:string)=>Promise<any>;demo?:boolean;compact?:boolean};

export default function InviteFriends({api,demo=false,compact=false}:Props){
  const [data,setData]=useState<Stats|null>(null);
  const [busy,setBusy]=useState(false);
  const [copied,setCopied]=useState(false);
  const [error,setError]=useState('');
  const [expanded,setExpanded]=useState(!compact);
  const load=async()=>{
    if(demo)return;
    setBusy(true);
    setError('');
    try{setData(await api('/s/app/api/friends') as Stats)}
    catch(err){setError((err as Error).message||'Не удалось получить ссылку.')}
    finally{setBusy(false)}
  };
  useEffect(()=>{void load()},[demo]);
  const copy=async()=>{
    if(!data?.referral_url)return;
    try{await navigator.clipboard.writeText(data.referral_url);setCopied(true)}
    catch{
      const field=document.createElement('textarea');
      field.value=data.referral_url;
      field.style.position='fixed';field.style.left='-9999px';
      document.body.appendChild(field);field.select();
      try{setCopied(document.execCommand('copy'))}
      catch{setError('Не удалось скопировать ссылку. Удерживай ссылку, чтобы скопировать.')}
      field.remove();
    }
  };
  const share=()=>{
    if(!data?.referral_url)return;
    const url='https://t.me/share/url?url='+encodeURIComponent(data.referral_url)
      +'&text='+encodeURIComponent('Попробуй «Совпали» 💞 Здесь можно найти человека по общим ценностям и интересам.');
    const tg=telegram();
    if(tg?.openTelegramLink)tg.openTelegramLink(url);
    else window.open(url,'_blank','noopener,noreferrer');
  };
  const current=data?.progress||0;
  return <section className={'friend-card '+(compact?'friend-compact':'')} aria-label="Пригласи друзей">
    <div className="friend-heading">
      <span className="friend-icon"><Gift size={20}/></span>
      <div><span className="eyebrow">ПОДАРОК ОТ «СОВПАЛИ»</span><h2>Пригласи 3 друзей — получи знакомство</h2></div>
    </div>
    <p>Каждые три новых участника, заполнивших анкеты по твоей ссылке, дают один бесплатный запрос на знакомство.</p>
    {compact&&!expanded&&<button className="friend-expand" type="button" onClick={()=>setExpanded(true)}>
      Пригласить друзей <ArrowUpRight size={16}/>
    </button>}
    {(!compact||expanded)&&<>
      {data?<div className="friend-progress">
        <div className="friend-progress-top"><span>До следующего бонуса</span><strong>{current} из 3</strong></div>
        <div className="friend-track" role="progressbar" aria-label="Заполненные анкеты приглашённых" aria-valuenow={current} aria-valuemin={0} aria-valuemax={3}><i style={{width:(current/3*100)+'%'}}/></div>
        <div className="friend-metrics">
          <span><Users size={14}/> Заполнили анкету: <b>{data.qualified_count}</b></span>
          <span>Ожидают: <b>{data.pending_count}</b></span>
        </div>
        {data.available_rewards>0&&<div className="friend-earned"><Check size={16}/> Доступно бесплатных запросов: <b>{data.available_rewards}</b>. Выбирай человека в «Подборе».</div>}
        {data.rewards_earned>0&&<p className="friend-history">Всего заработано бонусов: {data.rewards_earned}.</p>}
      </div>:<div className="friend-hint">{demo?'Приглашения доступны после настоящей регистрации.':busy?'Загружаем твою ссылку…':'Подготовим твою персональную ссылку.'}</div>}
      {data?.referral_url&&<div className="friend-url"><a href={data.referral_url} target="_blank" rel="noopener noreferrer">{data.referral_url}</a></div>}
      <div className="friend-actions">
        <button className="friend-primary" type="button" disabled={!data?.referral_url} onClick={share}><Share2 size={17}/> Поделиться</button>
        <button className="friend-secondary" type="button" disabled={!data?.referral_url} onClick={()=>void copy()}>{copied?<Check size={16}/>:<Copy size={16}/>} {copied?'Скопировано':'Скопировать'}</button>
        {!data&&!demo&&<button className="friend-retry" type="button" onClick={()=>void load()} disabled={busy} aria-label="Обновить приглашение"><RefreshCw size={16}/></button>}
      </div>
      {error&&<p className="friend-error" role="alert">{error}</p>}
      <p className="friend-small">Учитываются только новые Telegram-аккаунты с полностью заполненной анкетой. За одно приглашение начисляется либо этот бонус, либо партнёрская комиссия 30%. Бонус не заменяет согласие второго человека.</p>
    </>}
  </section>;
}
