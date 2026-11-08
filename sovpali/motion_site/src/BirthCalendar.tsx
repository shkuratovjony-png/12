import React,{useEffect,useState} from 'react';
import {ChevronLeft,ChevronRight,CalendarDays,Check} from 'lucide-react';
import './BirthCalendar.css';

const MONTHS=['Январь','Февраль','Март','Апрель','Май','Июнь','Июль','Август','Сентябрь','Октябрь','Ноябрь','Декабрь'];
const pad=(n:number)=>String(n).padStart(2,'0');
function parse(s:string):Date|null {
 const m=/^(\d{2})\.(\d{2})\.(\d{4})$/.exec(s);
 if(!m)return null;
 const d=new Date(Number(m[3]),Number(m[2])-1,Number(m[1]));
 return d.getFullYear()===Number(m[3])&&d.getMonth()===Number(m[2])-1&&d.getDate()===Number(m[1])?d:null;
}
export function BirthCalendar({value,onChange}:{value:string;onChange:(v:string)=>void}){
 const now=new Date();const cutoff=new Date(now.getFullYear()-18,now.getMonth(),now.getDate());
 const earliest=new Date(now.getFullYear()-100,now.getMonth(),now.getDate());
 const parsed=parse(value);
 const defaultYear=parsed?parsed.getFullYear():now.getFullYear()-30;
 const [year,setYear]=useState(defaultYear);
 const [month,setMonth]=useState(parsed?parsed.getMonth():0);
 const [visible,setVisible]=useState(true);
 useEffect(()=>{const d=parse(value);if(d){setYear(d.getFullYear());setMonth(d.getMonth())}},[value]);
 const firstDay=(new Date(year,month,1).getDay()+6)%7;
 const total=new Date(year,month+1,0).getDate();
 const monthShift=(shift:number)=>{const target=new Date(year,month+shift,1);setYear(target.getFullYear());setMonth(target.getMonth())};
 return <div className="birth-calendar" data-calendar="sovpali-v2">
  <div className="birth-calendar-head"><div><CalendarDays size={18}/><span>Твоя дата рождения</span></div><span className="birth-calendar-selected">{parsed?value:'Выбери день'}</span></div>
  <div className="birth-calendar-navigation">
    <button type="button" aria-label="Предыдущий месяц" onClick={()=>monthShift(-1)}><ChevronLeft size={20}/></button>
    <select aria-label="Месяц рождения" value={month} onChange={e=>setMonth(Number(e.target.value))}>{MONTHS.map((m,i)=><option key={m} value={i}>{m}</option>)}</select>
    <select aria-label="Год рождения" value={year} onChange={e=>setYear(Number(e.target.value))}>{Array.from({length:cutoff.getFullYear()-earliest.getFullYear()+1},(_,i)=>cutoff.getFullYear()-i).map(y=><option key={y} value={y}>{y}</option>)}</select>
    <button type="button" aria-label="Следующий месяц" onClick={()=>monthShift(1)}><ChevronRight size={20}/></button>
  </div>
  <div className="birth-calendar-grid" role="group" aria-label="Выбери день рождения">
    {['Пн','Вт','Ср','Чт','Пт','Сб','Вс'].map(x=><span className="birth-calendar-week" key={x}>{x}</span>)}
    {Array.from({length:firstDay},(_,i)=><span key={'empty'+i}/>)}
    {Array.from({length:total},(_,i)=>{const day=i+1;const d=new Date(year,month,day);const allowed=d<=cutoff&&d>=earliest;const isSelected=!!parsed&&parsed.getTime()===d.getTime();return <button type="button" key={day} aria-label={day+' '+MONTHS[month]+' '+year} aria-pressed={isSelected} disabled={!allowed} className={isSelected?'selected':''} onClick={()=>onChange(pad(day)+'.'+pad(month+1)+'.'+year)}>{isSelected?<><span>{day}</span><Check size={10}/></>:day}</button>})}
  </div>
  <p className="birth-calendar-note">Дату не нужно печатать. Выбери год, месяц и коснись числа.</p>
 </div>
}
