/* Совпали / Conversation Coach: lightweight, zero paid UI dependencies.
 * Real chat training is gated until AI and verified payments are enabled.
 */
(function(){
"use strict";
const c=window.__COACH__||{}, host=document.getElementById("coach");
if(!host)return;
const state={step:-1,answers:{},screen:"intro",demoTurns:0,dialog:[]};
const sections=[
 {key:"intent",label:"ЧЕГО ТЫ ХОЧЕШЬ?",subtitle:"Твоя цель определяет тон и первый шаг.",options:[
  ["talk","Начать общение","Узнать друг друга без давления","message-circle"],
  ["date","Пригласить на свидание","Постепенно предложить встречу","coffee"],
  ["friendship","Подружиться","Лёгкое дружеское знакомство","users"],
  ["relationship","Серьёзные отношения","Общение с перспективой","heart"]]},
 {key:"tempo",label:"КАК БЫСТРО ТЫ ХОЧЕШЬ ЭТОГО?",subtitle:"Без спешки и навязчивости — ритм должен подходить обоим.",options:[
  ["soon","В ближайшие дни","Хочу действовать, но без давления","zap"],
  ["week","В течение недели","Предпочитаю немного переписки","calendar"],
  ["slow","Без спешки","Пусть общение развивается естественно","leaf"]]},
 {key:"tone",label:"КАКОЙ ТОН ТЕБЕ БЛИЖЕ?",subtitle:"Рекомендации подстроятся под твою манеру письма.",options:[
  ["gentle","Тёплый и внимательный","Искренность, интерес, уважение","sun"],
  ["direct","Спокойный и уверенный","По делу, без шаблонных комплиментов","arrow-up-right"],
  ["playful","Лёгкий с юмором","Немного игры — без странных пикап-фраз","sparkles"]]},
 {key:"experience",label:"ЧТО УЖЕ БЫЛО МЕЖДУ ВАМИ?",subtitle:"Не предлагаем «привет» второй раз, если знакомство началось.",options:[
  ["new","Ещё не переписывались","Нужно самое первое сообщение","send"],
  ["already_chatted","Уже немного говорили","Хочу продолжить интересно","message-square"],
  ["awkward","Разговор застопорился","Не знаю, как вернуть диалог","refresh-cw"]]}
];
const safe=s=>String(s??"").replace(/[&<>"']/g,m=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[m]));
const short=s=>String(s??"").slice(0,120);
const who=short(c.candidate||"человеком");
const goal=short(c.goal||"знакомство");
const priority=short(c.priority||"уважительное общение");
const intentPhrase=()=>({talk:"начать разговор",date:"познакомиться поближе",friendship:"найти общий язык",relationship:"построить настоящее знакомство"})[state.answers.intent]||"начать общение";
const tone=(t)=>({gentle:"тёплый",direct:"спокойный",playful:"с юмором"})[t]||"внимательный";
const icon=(name)=>({heart:"♡",zap:"✳",coffee:"☕",users:"♧",leaf:"✺",sun:"☼",sparkles:"✦",calendar:"▣",send:"↗",refresh:"↻","message-square":"▤","message-circle":"◯","arrow-up-right":"↗"})[name]||"✳";
const top=()=>'<div class="cc-noise" aria-hidden="true"></div><header class="cc-header"><div class="cc-brand">♡ <span>совпали<span class="cc-brand-dot">.</span></span></div><div class="cc-header-note">ЛАБОРАТОРИЯ ПЕРВЫХ СЛОВ <i>/</i> 001</div><div class="cc-header-status"> <span class="cc-online"></span> COACH · BETA </div></header>';
const foot=()=>'<footer class="cc-footer"><span>СОВПАЛИ · 2026</span><span>РЕАЛЬНЫЕ ЧУВСТВА НЕ ПРОСЧИТЫВАЮТСЯ НА 99%</span><span>18+</span></footer>';
const button=(txt,action,secondary=false)=>'<button class="cc-btn '+(secondary?'cc-btn-ghost':'cc-btn-primary')+'" data-action="'+safe(action)+'">'+safe(txt)+' <span>↗</span></button>';
function render(){
 let content="";
 if(state.screen==="intro"){
  content='<section class="cc-intro"><div class="cc-kicker"><span class="cc-kdot"></span> ПЕРСОНАЛЬНЫЙ ПЛАН ОБЩЕНИЯ</div><div class="cc-intro-grid"><div class="cc-intro-copy"><h1>ВСТРЕЧА<br>НАЧИНАЕТСЯ<br><em>С ПЕРВЫХ СЛОВ.</em></h1><p>Не случайная фраза из интернета. Конструктор учитывает вашу цель знакомства, ответы в анкетах и выбранный стиль общения.</p><div class="cc-intro-meta"><div><b>'+safe(c.score??"—")+'<small>%</small></b><span>ИНДЕКС ПАРЫ<br>ИЗ БОТА</span></div><div><b>04</b><span>ВОПРОСА ДО<br>ЛИЧНОГО ПЛАНА</span></div></div>'+button("СОЗДАТЬ МОЙ ПЛАН","begin")+'<div class="cc-ethics">Мы не читаем мысли '+safe(who)+' и не обещаем результат. Астрология и нумерология — развлекательные интерпретации; в основе подсказок — ваши цели и заявленные ценности.</div></div><div class="cc-art" aria-hidden="true"><div class="cc-orbit cc-orbit1"></div><div class="cc-orbit cc-orbit2"></div><div class="cc-art-core">♡</div><div class="cc-art-note cc-note-a">Намерения <i>01</i></div><div class="cc-art-note cc-note-b">Ценности <i>02</i></div><div class="cc-art-note cc-note-c">Первый шаг <i>03</i></div><span class="cc-orbit-pip cc-pip-a"></span><span class="cc-orbit-pip cc-pip-b"></span><span class="cc-orbit-pip cc-pip-c"></span></div></div></section>';
 }
 else if(state.screen==="quiz"){
  const step=state.step,q=sections[step];
  content='<section class="cc-quiz"><div class="cc-quiz-top"><span>КОНСТРУКТОР / ТВОЯ ЦЕЛЬ</span><span>'+String(step+1).padStart(2,"0")+' — 04</span></div><div class="cc-progress">'+sections.map((_,i)=>'<i class="'+(i<=step?'cc-done':'')+'"></i>').join("")+'</div><div class="cc-quiz-layout"><div class="cc-quiz-titles"><div class="cc-kicker"><span class="cc-kdot"></span> ШАГ '+(step+1)+'</div><h2>'+safe(q.label)+'</h2><p>'+safe(q.subtitle)+'</p><div class="cc-quiz-target">НАША ПАРА<br><strong>'+safe(who)+'</strong><br><small>'+safe(c.city||"ГОРОД НЕ УКАЗАН")+'</small></div></div><div class="cc-options">'+q.options.map(([key,title,detail,symbol],i)=>'<button class="cc-choice '+(state.answers[q.key]===key?'selected':'')+'" data-choice="'+safe(key)+'"><span class="cc-choice-index">0'+(i+1)+'</span><span class="cc-choice-main"><strong>'+safe(title)+'</strong><small>'+safe(detail)+'</small></span><span class="cc-choice-icon">'+icon(symbol)+'</span></button>').join("")+'<div class="cc-controls">'+button("← НАЗАД","prev",true)+button(step===sections.length-1?"ПОДГОТОВИТЬ КОНСТРУКТОР":"ДАЛЬШЕ","next")+'</div><p class="cc-small">Выбранный темп не гарантирует реакции другого человека.</p></div></div></section>';
 }
 else if(state.screen==="ready"){
  const intro=state.answers.experience==="new"?"Напиши первое сообщение":"Продолжи разговор";
  content='<section class="cc-ready"><div class="cc-ready-kicker">✦ ПОДГОТОВЛЕНО ДЛЯ ТВОЕЙ ПАРЫ</div><h2>КОНСТРУКТОР<br><em>ГОТОВ.</em></h2><p class="cc-ready-lead">Ты хочешь '+safe(intentPhrase())+'. Мы учли выбранный тобой '+safe(tone(state.answers.tone))+' тон и заявленный приоритет '+safe(who)+': <b>'+safe(priority)+'</b>.</p><div class="cc-ready-summary"><div><span>ТВОЯ ЦЕЛЬ</span><strong>'+safe(intentPhrase())+'</strong></div><div><span>ТВОЙ ТОН</span><strong>'+safe(tone(state.answers.tone))+'</strong></div><div><span>ПЕРВЫЙ ШАГ</span><strong>'+safe(intro)+'</strong></div></div><div class="cc-pricing-head">ВЫБЕРИ СЦЕНАРИЙ</div><div class="cc-plans"><article class="cc-plan"><small>01 / БАЗОВЫЙ</small><h3>Первое<br><em>сообщение.</em></h3><div class="cc-price">900 <small>₽</small></div><p>Подбор первого сообщения под цель, тон и ответы анкет. Несколько вариантов и объяснение подхода.</p><div class="cc-plan-unavailable">Оплата подключается</div><span class="cc-plan-meta">Без работающего тренажёра переписки</span></article><article class="cc-plan cc-pro"><div class="cc-featured">ПОЛНЫЙ ПЛАН</div><small>02 / ПРЕМИУМ</small><h3>Живой<br><em>тренажёр.</em></h3><div class="cc-price">2 900 <small>₽</small></div><p>Персональный старт и AI-эмулятор: вставляешь ответ из переписки — получаешь варианты продолжения и объяснение, почему это уместно.</p><div class="cc-plan-unavailable">Оплата и AI подключаются</div><span class="cc-plan-meta">Не пишет человеку автоматически и не гарантирует взаимность</span></article></div><div class="cc-demo-invite"><div><strong>Хочешь посмотреть механику?</strong><p>Испытай бесплатный демонстрационный тренажёр на примере. Это не настоящий AI-анализ партнёра.</p></div>'+button("ОТКРЫТЬ ДЕМО","simulator")+'</div>'+button("← ИЗМЕНИТЬ ОТВЕТЫ","backQuiz",true)+'</section>';
 }
 else if(state.screen==="simulator"){
  const suggestion=coachingSuggestion(state.dialog.at(-1)?.text||"");
  const messages='<div class="cc-dialog">'+state.dialog.map((m,i)=>'<div class="cc-bubble '+(m.role==="user"?"cc-bubble-user":"cc-bubble-partner")+'"><span>'+ (m.role==="user"?"ТЫ":"УСЛОВНЫЙ СОБЕСЕДНИК") +'</span><p>'+safe(m.text)+'</p></div>').join("")+'</div>';
  content='<section class="cc-sim"><div class="cc-sim-head"><div><div class="cc-kicker">04 / DEMO LAB</div><h2>РЕПЕТИЦИЯ<br><em>ДИАЛОГА.</em></h2></div><button class="cc-return" data-action="ready">← К ТАРИФАМ</button></div><p class="cc-sim-note">Это демонстрация принципа: ответы собеседника придуманы для примера. Реальный платный AI-тренажёр пока не подключён. Он не сможет знать настоящие мысли '+safe(who)+'.</p><div class="cc-sim-columns"><div class="cc-chat-panel"><div class="cc-chat-header"><span class="cc-avatar">♡</span><span>ЭМУЛЯТОР<br><small>ПРИМЕР · НЕ РЕАЛЬНЫЙ ЧЕЛОВЕК</small></span><b>✳</b></div>'+messages+'<form id="cc-chat-form" class="cc-chat-input"><input id="cc-chat-text" maxlength="400" placeholder="Напиши, что хочешь отправить…" autocomplete="off" required><button aria-label="Получить подсказку">↗</button></form></div><div class="cc-guidance"><small>ЛИЧНЫЙ СОВЕТНИК</small><h3>Как написать<br><em>лучше?</em></h3><div class="cc-guide-block"><span>РЕКОМЕНДУЕМЫЙ ВАРИАНТ</span><p>'+safe(suggestion.message)+'</p></div><div class="cc-guide-block"><span>ПОЧЕМУ ЭТО УМЕСТНО</span><p>'+safe(suggestion.why)+'</p></div><p class="cc-guide-foot">Рекомендации основаны на цели и выбранном тоне. Нумерология и астрология могут использоваться только как творческие темы разговора.</p></div></div></section>';
 }
 host.innerHTML=top()+'<main class="cc-main">'+content+'</main>'+foot();
 requestAnimationFrame(()=>host.querySelector(".cc-main")?.classList.add("cc-in"));
}
function coachingSuggestion(text){
 let intro=state.answers.experience==="new";
 let msg;
 if(text.trim().length>0){
   const typed=String(text).slice(0,400);
   msg=typed.length<12?"Привет! Как проходит твоя неделя? Увидел(а), что для тебя важно "+priority.toLowerCase()+", и стало интересно, что ты в это вкладываешь.":"Можно чуть короче и конкретнее: «Рад(а) познакомиться! Ты указал(а), что для тебя важно "+priority.toLowerCase()+". Что в этом для тебя самое главное?»";
 }else if(state.answers.intent==="date"){
   msg="Привет! Было интересно посмотреть твою анкету. Что бы ты предпочёл(ла) для первой встречи — прогулку или кофе? Без спешки 🙂";
 }else if(state.answers.tone==="playful"){
   msg="Привет! Кажется, у нас нашлось кое-что общее. Проверим: какой маленький момент может сделать твой день лучше?";
 }else if(state.answers.intent==="friendship"){
   msg="Привет! Мне понравилось, что для тебя важно "+priority.toLowerCase()+". А какое занятие помогает тебе отдыхать после насыщенного дня?";
 }else{
   msg="Привет! Мне откликнулось, что для тебя важно "+priority.toLowerCase()+". А что ты обычно ценишь в первом разговоре с новым человеком?";
 }
 const why=intro?"Вместо комплимента внешности начинаем с уважительного вопроса по заявленным ценностям. Это даёт пространство для настоящего ответа, без давления.":"Вместо сложной заготовки — короткий вопрос, который позволяет человеку отвечать свободно. Если ответа нет, не стоит настаивать.";
 return {message:msg,why};
}
function prepare(){
 if(c.demo||!c.prepare){state.screen="ready";render();return;}
 const btn=host.querySelector('[data-action="next"]');
 if(btn){btn.disabled=true;btn.textContent="ГОТОВИМ…";}
 fetch(c.prepare,{method:"POST",headers:{"Content-Type":"application/json"},credentials:"same-origin",body:JSON.stringify(state.answers)})
  .then(r=>{if(!r.ok)throw Error("Не удалось сохранить");return r.json()})
  .then(()=>{state.screen="ready";render()})
  .catch(()=>{state.screen="ready";render();const p=host.querySelector(".cc-ready-lead");if(p)p.insertAdjacentHTML("afterend",'<p class="cc-small cc-error">Ответы показаны в браузере, но сервер не подтвердил сохранение. Покупка пока недоступна.</p>');});
}
host.addEventListener("click",e=>{
 const choice=e.target.closest("[data-choice]");
 if(choice){state.answers[sections[state.step].key]=choice.dataset.choice;render();return;}
 const action=e.target.closest("[data-action]")?.dataset.action;
 if(!action)return;
 if(action==="begin"){state.step=0;state.screen="quiz";render();}
 if(action==="prev"){if(state.step===0)state.screen="intro";else state.step--;render();}
 if(action==="next"){
  if(!state.answers[sections[state.step].key]){host.querySelector(".cc-options")?.classList.add("cc-shake");setTimeout(()=>host.querySelector(".cc-options")?.classList.remove("cc-shake"),420);return;}
  if(state.step===sections.length-1)prepare();else{state.step++;render();}
 }
 if(action==="ready"){state.screen="ready";render();}
 if(action==="backQuiz"){state.step=0;state.screen="quiz";render();}
 if(action==="simulator"){
  state.demoTurns=0;
  state.dialog=[{role:"partner",text:"Привет! Рада знакомству. Что ты любишь делать в свободное время?"}];
  state.screen="simulator";render();
 }
});
host.addEventListener("submit",e=>{
 if(e.target.id!=="cc-chat-form")return;
 e.preventDefault();
 const field=host.querySelector("#cc-chat-text"),value=field?.value.trim();
 if(!value)return;
 if(state.demoTurns>=3){const note=host.querySelector(".cc-sim-note");if(note)note.textContent="Демо завершено после трёх реплик. В полной версии тренажёр потребует оплаты и подключённую AI-модель.";return;}
 state.dialog.push({role:"user",text:value.slice(0,400)});
 state.demoTurns++;
 const responses=[
 "Интересно! Мне тоже нравится, когда люди могут спокойно разговаривать. А ты больше любишь прогулки или уютные места?",
 "Звучит здорово. Я обычно не тороплюсь — сначала хочу узнать человека получше.",
 "Спасибо за разговор! Мне приятно, когда собеседник умеет слушать."
 ];
 state.dialog.push({role:"partner",text:responses[(state.demoTurns-1)%responses.length]});
 render();
 host.querySelector(".cc-dialog")?.scrollTo(0,100000);
});
render();
})();
