import React,{useEffect,useState} from 'react';
import {ArrowLeft,ArrowRight,Check,Heart,MapPin,Moon,ShieldCheck,Sparkles,Sun,Orbit,Clock3,CalendarDays} from 'lucide-react';
import {api} from './Cabinet';
import './Onboarding.css';

type Answers=Record<string,string>;
const questions=[
 {key:'gender',tag:'01 / ЗНАКОМСТВО',title:'Начнём с тебя',hint:'Немного о тебе, чтобы искать именно твоих людей.',choices:['Мужчина','Женщина']},
 {key:'birth_date',tag:'02 / АСТРОЛОГИЯ',title:'Всё начинается с даты',hint:'По дате определяем солнечный знак и рассчитываем нумерологический профиль.',choices:[]},
 {key:'birth_place',tag:'03 / НАТАЛЬНАЯ КАРТА',title:'Где началась твоя история?',hint:'Место рождения важно для точных астрологических расчётов. Время рождения можно указать, если знаешь.',choices:[]},
 {key:'city',tag:'04 / ГЕОГРАФИЯ',title:'Где ты сейчас?',hint:'Сначала покажем людей поблизости. Совпадения из других городов тоже доступны.',choices:[]},
 {key:'goal',tag:'05 / НАМЕРЕНИЯ',title:'Какую историю ты ищешь?',hint:'В отношениях важно хотеть похожего будущего.',choices:['Серьёзные отношения','Любовь и семья','Общение и знакомство','Пока присматриваюсь']},
 {key:'priority',tag:'06 / ЦЕННОСТИ',title:'Что для тебя в центре любви?',hint:'Выбери самое важное. Остальное узнаем в процессе знакомства.',choices:['Семья','Любовь','Ценности','Страсть','Опора']},
 {key:'details',tag:'07 / ГЛУБИНА',title:'Твоя формула близости',hint:'Три коротких ответа сделают подбор более содержательным.',choices:[]}
];
const lifestyle=['Активный','Домашний','Баланс'];
const style=['Обсуждаю сразу','Нужно время','Спокойный диалог'];
const family=['Хочу семью и детей','Семья без детей','Пока не решил'];
function options(values:string[],selected:string,onSelect:(s:string)=>void){return <div className="on-choices">{values.map(x=><button type="button" className={'on-choice '+(selected===x?'active':'')} key={x} onClick={()=>onSelect(x)}><span>{x}</span>{selected===x?<Check size={18}/>:<span className="on-choice-circle"/>}</button>)}</div>}
export default function Onboarding({onComplete}:{onComplete:()=>Promise<void>|void}){
 const [step,setStep]=useState(0),[form,setForm]=useState<Answers>({}),[loading,setLoading]=useState(true),[busy,setBusy]=useState(false),[error,setError]=useState('');
 const set=(k:string,v:string)=>setForm(f=>({...f,[k]:v}));
 const today=new Date();
 const maxBirthDate=[today.getFullYear()-18,String(today.getMonth()+1).padStart(2,'0'),String(today.getDate()).padStart(2,'0')].join('-');
 useEffect(()=>{api('/s/app/api/onboarding').then(d=>{if(d.completed){onComplete();return}setForm({...d.draft,name:d.draft?.name||d.telegram_name||''});}).catch(e=>setError(e.message)).finally(()=>setLoading(false))},[]);
 const valid=()=>{const v=form[questions[step].key];
  if(step===0)return Boolean(form.name?.trim()&&v);
  if(step===1){let m=/^(\d{2})\.(\d{2})\.(\d{4})$/.exec(v||'');if(!m)return false;let d=new Date(Number(m[3]),Number(m[2])-1,Number(m[1]));let age=(Date.now()-d.getTime())/31557600000;return d.getFullYear()===Number(m[3])&&d.getMonth()===Number(m[2])-1&&d.getDate()===Number(m[1])&&age>=18&&age<=100}
  if(step===2)return Boolean(form.birth_place?.trim()&&(!form.birth_time||/^([01]\d|2[0-3]):[0-5]\d$/.test(form.birth_time)));
  if(step===6)return Boolean(form.lifestyle&&form.relationship_style&&form.family_plan);
  return Boolean(v?.trim());
 };
 const next=async()=>{if(!valid()){setError('Заполни этот шаг, чтобы продолжить.');return}setError('');setBusy(true);try{await api('/s/app/api/onboarding/save',form);if(step===6){await api('/s/app/api/onboarding/finish');await onComplete()}else setStep(x=>x+1)}catch(e){setError((e as Error).message)}finally{setBusy(false)}};
 return <div className="on-wrap"><div className="on-glow"/><div className="on-shell">
 <header className="on-head"><div className="on-brand"><span>♡</span>совпали<span>.</span></div><div className="on-chip"><ShieldCheck size={13}/> Личное пространство</div></header>
 <div className="on-track"><div className="on-track-fill" style={{width:((step+1)/7*100)+'%'}}/><i className="on-track-light" style={{left:((step+1)/7*100)+'%'}}/></div>
 <div className="on-progress"><span>ТВОЯ ИСТОРИЯ</span><b>{String(step+1).padStart(2,'0')} <em>/ 07</em></b></div>
 <div className="on-visual" aria-hidden="true"><div className="on-orbit orbit-one"/><div className="on-orbit orbit-two"/><div className="on-orbit orbit-three"/><div className="on-center"><Heart size={35} strokeWidth={1.2}/></div><span className="on-star s1">✦</span><span className="on-star s2">✧</span><span className="on-star s3">✦</span></div>
 {loading?<div className="on-loading">Открываем твою историю…</div>:<div className="on-stage" key={step}><div className="on-eyebrow">{questions[step].tag}</div><h1>{questions[step].title}</h1><p className="on-hint">{questions[step].hint}</p>
 {step===0&&<div className="on-field"><label>Как к тебе обращаться?</label><input maxLength={90} placeholder="Твоё имя" value={form.name||''} onChange={e=>set('name',e.target.value)}/></div>}
 {step===1&&<div className="on-field on-date-field"><label htmlFor="sovpali-birth-date">Дата рождения</label><div className="on-date-control"><input id="sovpali-birth-date" type="date" lang="ru-RU" required min="1926-01-01" max={maxBirthDate} value={/^(\d{2})\.(\d{2})\.(\d{4})$/.test(form.birth_date||'')?(form.birth_date!.slice(6)+'-'+form.birth_date!.slice(3,5)+'-'+form.birth_date!.slice(0,2)):''} onChange={e=>{const d=e.target.value;set('birth_date',/^\d{4}-\d{2}-\d{2}$/.test(d)?d.slice(8,10)+'.'+d.slice(5,7)+'.'+d.slice(0,4):'');setError('')}}/><span className="on-date-icon"><CalendarDays size={22}/></span></div><small><Sun size={14}/> Выбери день, месяц и год в календаре. Ничего печатать не нужно.</small></div>}
 {step===2&&<><div className="on-field"><label>Город рождения</label><input maxLength={90} placeholder="Например, Казань" value={form.birth_place||''} onChange={e=>set('birth_place',e.target.value)}/></div><div className="on-field"><label>Время рождения <span>необязательно</span></label><input type="time" lang="ru-RU" value={form.birth_time||''} onChange={e=>set('birth_time',e.target.value)}/><small><Moon size={14}/> Без времени мы не показываем точный асцендент и дома</small></div></>}
 {step===3&&<div className="on-field"><label>Город проживания</label><input maxLength={90} placeholder="Например, Москва" value={form.city||''} onChange={e=>set('city',e.target.value)}/><small><MapPin size={14}/> Расстояние не исключает хорошее совпадение</small></div>}
 {questions[step].choices.length>0&&options(questions[step].choices,form[questions[step].key]||'',x=>set(questions[step].key,x))}
 {step===6&&<div className="on-triples"><div><label>Твой темп жизни</label>{options(lifestyle,form.lifestyle||'',v=>set('lifestyle',v))}</div><div><label>Когда возникает разногласие</label>{options(style,form.relationship_style||'',v=>set('relationship_style',v))}</div><div><label>Планы на семью</label>{options(family,form.family_plan||'',v=>set('family_plan',v))}</div></div>}
 {error&&<p className="on-error" role="alert">{error}</p>}
 </div>}
 <footer className="on-actions"><div className="on-trust"><Sparkles size={15}/> Совместимость начинается с настоящего знакомства</div><div className="on-buttons">{step>0&&<button className="on-back" disabled={busy} onClick={()=>{setError('');setStep(s=>s-1)}} aria-label="Назад"><ArrowLeft/></button>}<button className="on-next" disabled={loading||busy} onClick={next}>{busy?'Сохраняем…':step===6?'Найти мои совпадения':'Продолжить'}<ArrowRight size={20}/></button></div><p className="on-small">Астрология и нумерология — символическая интерпретация, не гарантия отношений. 18+</p></footer>
 </div></div>;
}