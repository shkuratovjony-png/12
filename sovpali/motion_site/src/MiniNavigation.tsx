import React,{useEffect,useState} from 'react';
import {Heart, Sparkles, UserRound, ArrowUpRight, Maximize2} from 'lucide-react';
import {telegram,isMiniApp,haptic,fullscreen} from './telegram';
const sections=[['sx-top','Встреча',Heart],['sx-match','Ваша пара',UserRound],['sx-data','Почему',Sparkles],['sx-start','Первый шаг',ArrowUpRight]] as const;
export function MiniNavigation(){
 const [active,setActive]=useState('sx-top');
 const jump=(id:string)=>{haptic();document.getElementById(id)?.scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth'});};
 useEffect(()=>{
  let frame=0;
  const update=()=>{frame=0;let id='sx-top';for(const [key] of sections){if((document.getElementById(key)?.getBoundingClientRect().top??Infinity)<innerHeight*.55)id=key;}setActive(id);};
  const scroll=()=>{if(!frame)frame=requestAnimationFrame(update);};
  window.addEventListener('scroll',scroll,{passive:true});update();
  return()=>{window.removeEventListener('scroll',scroll);cancelAnimationFrame(frame);};
 },[]);
 useEffect(()=>{
  const tg=telegram();if(!isMiniApp()||!tg.isVersionAtLeast('6.1'))return;
  const back=()=>jump('sx-top');
  tg.BackButton.onClick(back);
  active==='sx-top'?tg.BackButton.hide():tg.BackButton.show();
  return()=>{tg.BackButton.offClick(back);tg.BackButton.hide();};
 },[active]);
 return <><nav className="mini-chapters" aria-label="Разделы совместимости">{sections.map(([id,label,Icon],i)=><button key={id} aria-current={active===id?'step':undefined} onClick={()=>jump(id)}><Icon size={18} strokeWidth={1.5}/><span>{label}</span><i>{String(i+1).padStart(2,'0')}</i></button>)}</nav>{isMiniApp()&&telegram().isVersionAtLeast('8.0')&&<button className="mini-fullscreen" aria-label="Переключить полный экран" onClick={fullscreen}><Maximize2 size={18}/></button>}</>;
}
