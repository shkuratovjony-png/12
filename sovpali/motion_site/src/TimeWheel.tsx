import React,{useEffect,useRef,useState} from 'react';
import './TimeWheel.css';

const ROW=46;
const hours=Array.from({length:24},(_,i)=>i);
const minutes=Array.from({length:60},(_,i)=>i);
const two=(v:number)=>String(v).padStart(2,'0');
function parseTime(value:string){
 const match=/^([01]\d|2[0-3]):([0-5]\d)$/.exec(value||'');
 return match?{hour:Number(match[1]),minute:Number(match[2])}:null;
}
type WheelKey='hour'|'minute';

export default function TimeWheel({value,onChange,compact=false}:{
 value:string;
 onChange:(time:string)=>void;
 compact?:boolean;
}){
 const chosen=parseTime(value);
 const current=useRef({hour:chosen?.hour??12,minute:chosen?.minute??0});
 const [display,setDisplay]=useState({...current.current});
 const hourRef=useRef<HTMLDivElement>(null),minuteRef=useRef<HTMLDivElement>(null);
 const suppress=useRef(true),interacted=useRef(false);
 const schedule=useRef(0);

 // Existing saved time is loaded from the server after the editor opens.
 // Center both wheels without mistakenly treating it as a user selection.
 useEffect(()=>{
  if(interacted.current)return;
  const parsed=parseTime(value);
  const next={hour:parsed?.hour??12,minute:parsed?.minute??0};
  current.current=next;
  setDisplay(next);
  suppress.current=true;
  if(hourRef.current)hourRef.current.scrollTop=next.hour*ROW;
  if(minuteRef.current)minuteRef.current.scrollTop=next.minute*ROW;
  const frame=requestAnimationFrame(()=>{
   schedule.current=requestAnimationFrame(()=>{suppress.current=false});
  });
  return ()=>{cancelAnimationFrame(frame);cancelAnimationFrame(schedule.current)};
 },[value]);

 const choose=(key:WheelKey,nextValue:number,scroll=false)=>{
  const limit=key==='hour'?23:59;
  const clamped=Math.min(limit,Math.max(0,nextValue));
  const next={...current.current,[key]:clamped};
  current.current=next;
  setDisplay(next);
  interacted.current=true;
  onChange(two(next.hour)+':'+two(next.minute));
  if(scroll){
   const target=key==='hour'?hourRef.current:minuteRef.current;
   target?.scrollTo({top:clamped*ROW,behavior:'smooth'});
  }
 };
 const onWheel=(key:WheelKey,e:React.UIEvent<HTMLDivElement>)=>{
  if(suppress.current)return;
  const n=Math.round(e.currentTarget.scrollTop/ROW);
  if(n!==current.current[key])choose(key,n);
 };
 return <section className={'time-wheel'+(compact?' time-wheel-compact':'')} aria-label="Выбор времени рождения">
  <div className="time-wheel-head">
   <span>Часы</span><span>Минуты</span>
  </div>
  <div className="time-wheel-columns">
   <div className="time-wheel-column" ref={hourRef} onScroll={e=>onWheel('hour',e)} role="group" aria-label="Прокрутка часов">
    {hours.map(hour=><button type="button" key={hour} className={'time-wheel-option'+(display.hour===hour?' selected':'')} aria-pressed={display.hour===hour} aria-label={two(hour)+' часов'} onClick={()=>choose('hour',hour,true)}>{two(hour)}</button>)}
   </div>
   <span className="time-wheel-colon" aria-hidden="true">:</span>
   <div className="time-wheel-column" ref={minuteRef} onScroll={e=>onWheel('minute',e)} role="group" aria-label="Прокрутка минут">
    {minutes.map(minute=><button type="button" key={minute} className={'time-wheel-option'+(display.minute===minute?' selected':'')} aria-pressed={display.minute===minute} aria-label={two(minute)+' минут'} onClick={()=>choose('minute',minute,true)}>{two(minute)}</button>)}
   </div>
   <div className="time-wheel-highlight" aria-hidden="true"/>
  </div>
  <div className="time-wheel-footer">
   <span aria-live="polite">{value?'Выбрано: '+value:'Время пока не указано'}</span>
   {value?<button type="button" onClick={()=>{interacted.current=true;onChange('')}}>Не знаю время</button>:
   <button type="button" onClick={()=>choose('hour',current.current.hour)}>Указать {two(display.hour)}:{two(display.minute)}</button>}
  </div>
  <p className="time-wheel-tip">Прокрути часы и минуты пальцем или коснись нужного значения. Клавиатура не нужна.</p>
 </section>;
}
