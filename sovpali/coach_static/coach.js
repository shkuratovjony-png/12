/* Совпали / first free message, paid continuation only after a real reply.
 * Standalone mobile-first browser experience with no new dependencies.
 * This version's first message is rule-based; paid AI is not yet connected.
 */
(function () {
"use strict";
const c=window.__COACH__||{}, mount=document.getElementById("coach");
if(!mount)return;
const state={
  screen:c.saved_plan?"first":"intro",step:0,
  answers:c.saved_answers||{},plan:c.saved_plan||null,
  reply:"",error:"",progress:0,copyDone:false,buildingText:""
};
const person=String(c.candidate||"человека").slice(0,100);
const profileGoal=String(c.goal||"знакомство");
const profilePriority=String(c.priority||"").slice(0,100);
const esc=(s)=>String(s??"").replace(/[&<>"']/g, ch=>({
  "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"
})[ch]);
const questions=[
 {key:"intent",eyebrow:"01 / ТВОЯ ЦЕЛЬ",
  title:"ЧТО ТЫ ХОЧЕШЬ<br><em>ОТ ЗНАКОМСТВА?</em>",
  intro:"Не нужно угадывать, что писать. Скажи, к чему ты хочешь прийти.",
  options:[
   {value:"talk",title:"Просто пообщаться",desc:"Познакомиться спокойно, без давления",icon:"◯"},
   {value:"date",title:"Сходить на свидание",desc:"Начать диалог с перспективой встречи",icon:"✳"},
   {value:"relationship",title:"Серьёзные отношения",desc:"Построить близость шаг за шагом",icon:"♡"}
  ]},
 {key:"tempo",eyebrow:"02 / ТВОЙ ТЕМП",
  title:"КАК БЫСТРО<br><em>ТЫ ХОЧЕШЬ СБЛИЗИТЬСЯ?</em>",
  intro:"Это влияет на тон первого шага. Другой человек вправе выбирать собственный темп.",
  options:[
   {value:"soon",title:"Хочу начать сейчас",desc:"Не откладывать первое сообщение",icon:"↗"},
   {value:"week",title:"Постепенно, за неделю",desc:"Дать диалогу раскрыться",icon:"◷"},
   {value:"slow",title:"Без спешки",desc:"Пусть всё развивается естественно",icon:"∞"}
  ]},
 {key:"tone",eyebrow:"03 / ТВОЙ ХАРАКТЕР",
  title:"КАК ТЕБЕ<br><em>КОМФОРТНО ПИСАТЬ?</em>",
  intro:"Первое сообщение должно быть твоим, а не чужой заученной фразой.",
  options:[
   {value:"gentle",title:"Тепло и внимательно",desc:"С уважением и искренним интересом",icon:"☼"},
   {value:"direct",title:"Спокойно и уверенно",desc:"Коротко, ясно, без заигрываний",icon:"→"},
   {value:"playful",title:"Легко, с юмором",desc:"Ненавязчиво и чуть игриво",icon:"✦"}
  ]}
];
function initials(s){return String(s||"♡").trim().slice(0,1).toUpperCase()}
function localPlan(){
 const name=person.split(/\s+/)[0]||"привет";
 const priority=profilePriority;
 const topics=[
  ["семья","семья","Что для тебя самое важное в близких отношениях?"],
  ["доверие","доверие","Что помогает тебе доверять человеку?"],
  ["честность","честность","Что для тебя значит открытость в общении?"],
  ["развитие","развитие","Чем ты сейчас больше всего увлечена?"],
  ["юмор","юмор","Что обычно может рассмешить тебя?"],
  ["забота","забота","Какие небольшие знаки внимания особенно приятны тебе?"],
  ["уважение","уважение","Что для тебя значит уважение в общении?"],
  ["поддержка","поддержка","Как ты понимаешь поддержку в отношениях?"]
 ];
 const found=topics.find(t=>priority.toLowerCase().includes(t[0]));
 const question=found?found[2]:"Что для тебя важно в начале общения с новым человеком?";
 const open=found?"Привет, "+name+"! Увидел, что тебе важно "+found[1]+".":"Привет, "+name+"! Мне откликнулась твоя анкета.";
 let message=state.answers.tone==="direct"
  ?name+", привет! Рад знакомству. "+question
  :state.answers.tone==="playful"
  ?open+" Кажется, у нас есть с чего начать 🙂 "+question
  :open+" "+question;
 return {
  first_message:message,
  why:"Первое сообщение опирается на заявленный приоритет «"+(priority||"не указан")+"» и вашу цель знакомства. Короткий открытый вопрос показывает интерес, не требуя от человека быстрого решения. Астрология и нумерология не позволяют знать его мысли или желания.",
  engine:"illustrative-demo"
 };
}
function masthead(){
 return '<div class="cc-noise" aria-hidden="true"></div><header class="cc-header">'
  +'<div class="cc-brand">♡ <span>совпали<span class="cc-brand-dot">.</span></span></div>'
  +'<div class="cc-header-note">ЛАБОРАТОРИЯ ПЕРВЫХ СЛОВ <i>/</i> 001</div>'
  +'<div class="cc-header-status"><span class="cc-online"></span> COACH · FIRST STEP</div></header>';
}
function foot(){
 return '<footer class="cc-footer"><span>СОВПАЛИ · 2026</span>'
  +'<span>ПОДСКАЗКИ, А НЕ ГАРАНТИЯ ЧУЖИХ ЧУВСТВ</span><span>18+</span></footer>';
}
function action(text,name,secondary){
 return '<button type="button" class="cc-btn '+(secondary?'cc-btn-ghost':'cc-btn-primary')+
  '" data-action="'+esc(name)+'">'+esc(text)+' <span>↗</span></button>';
}
function content(){
 if(state.screen==="intro"){
  return '<section class="cc-intro cc-intro-new">'
   +'<div class="cc-kicker"><span class="cc-kdot"></span> ПОСЛЕ ПЕРВОГО СОВПАДЕНИЯ — ПРАВИЛЬНЫЙ ПЕРВЫЙ ШАГ</div>'
   +'<div class="cc-intro-grid"><div class="cc-intro-copy">'
   +'<h1>НЕ СПЕШИ<br>ПИСАТЬ.<br><em>НАЧНИ КРАСИВО.</em></h1>'
   +'<p>Ты получил контакт '+esc(person)+'. Мы уже сравнили ваши анкеты, ценности и интересы, а также астрологические и нумерологические интерпретации. Теперь узнаем твою цель и составим первое сообщение именно для этого знакомства.</p>'
   +'<div class="cc-intro-meta"><div><b>03</b><span>КОРОТКИХ<br>ВОПРОСА</span></div>'
   +'<div><b>0 <small>₽</small></b><span>ПЕРВОЕ СООБЩЕНИЕ<br>БЕСПЛАТНО</span></div></div>'
   +action("ПОЛУЧИТЬ ПЕРВОЕ СООБЩЕНИЕ","begin")
   +'<div class="cc-ethics">Мы учитываем то, что человек добровольно указал в анкете. Натальная карта и нумерология — символические интерпретации, а не способ узнать настоящие мысли человека. Решение об общении всегда взаимное.</div></div>'
   +'<div class="cc-art" aria-hidden="true"><div class="cc-orbit cc-orbit1"></div><div class="cc-orbit cc-orbit2"></div>'
   +'<div class="cc-art-core">♡</div><div class="cc-art-note cc-note-a">ЕЁ ЦЕННОСТИ <i>01</i></div>'
   +'<div class="cc-art-note cc-note-b">ТВОЯ ЦЕЛЬ <i>02</i></div>'
   +'<div class="cc-art-note cc-note-c">ПЕРВОЕ СООБЩЕНИЕ <i>03</i></div>'
   +'<span class="cc-orbit-pip cc-pip-a"></span><span class="cc-orbit-pip cc-pip-b"></span>'
   +'<span class="cc-orbit-pip cc-pip-c"></span></div></div></section>';
 }
 if(state.screen==="quiz"){
   const q=questions[state.step];
   return '<section class="cc-quiz"><div class="cc-quiz-top"><span>ТВОЙ ПЕРСОНАЛЬНЫЙ ПЛАН / '
     +esc(person.toUpperCase())+'</span><span>0'+(state.step+1)+' — 03</span></div>'
     +'<div class="cc-progress">'+questions.map((_,i)=>'<i class="'+(i<=state.step?'cc-done':'')+'"></i>').join("")+'</div>'
     +'<div class="cc-quiz-layout"><div class="cc-quiz-titles"><div class="cc-kicker"><span class="cc-kdot"></span>'
     +esc(q.eyebrow)+'</div><h2>'+q.title+'</h2><p>'+esc(q.intro)+'</p>'
     +'<div class="cc-quiz-target">ПАРТНЁР В ТВОЁМ ПЛАНЕ<br><strong>'+esc(person)
     +'</strong><br><small>'+esc(c.city||"Город не указан")+'</small></div></div>'
     +'<div class="cc-options">'+q.options.map((o,i)=>'<button type="button" class="cc-choice '
     +(state.answers[q.key]===o.value?'selected':'')+'" data-choice="'+esc(o.value)+'">'
     +'<span class="cc-choice-index">0'+(i+1)+'</span><span class="cc-choice-main">'
     +'<strong>'+esc(o.title)+'</strong><small>'+esc(o.desc)+'</small></span>'
     +'<span class="cc-choice-icon">'+o.icon+'</span></button>').join("")
     +'<div class="cc-controls">'+action("← НАЗАД","prev",true)
     +action(state.step===2?"СОЗДАТЬ СООБЩЕНИЕ":"ДАЛЬШЕ","next")+'</div>'
     +(state.error?'<p class="cc-small cc-error">'+esc(state.error)+'</p>':'')
     +'<p class="cc-small">Рекомендация не будет отправлена человеку автоматически.</p></div></div></section>';
 }
 if(state.screen==="building"){
  const stages=["Сверяем цели и ценности","Сопоставляем контекст анкеты","Выбираем интонацию","Формулируем первое сообщение"];
  const n=Math.min(stages.length-1,Math.floor(state.progress/25));
  return '<section class="cc-building"><div class="cc-kicker"><span class="cc-kdot"></span> ВАШ КОНСТРУКТОР СОБИРАЕТСЯ</div>'
   +'<div class="cc-build-grid"><div><h2>НАХОДИМ<br><em>ВАШИ СЛОВА.</em></h2>'
   +'<p>Не шаблон для всех. Берём цель знакомства, выбранный тон и ценности из анкеты '+esc(person)+'.</p>'
   +'<div class="cc-build-line"><i style="width:'+state.progress+'%"></i></div>'
   +'<div class="cc-build-label"><span>'+esc(stages[n])+'</span><strong>'+state.progress+'%</strong></div>'
   +'<div class="cc-build-stages">'+stages.map((s,i)=>'<div class="'+(i<=n?'on':'')+'">'
   +'<span>0'+(i+1)+'</span>'+esc(s)+'<b>'+(i<n?'✓':i===n?'●':'')+'</b></div>').join("")+'</div></div>'
   +'<div class="cc-build-orb" aria-hidden="true"><div class="cc-build-ring a"></div>'
   +'<div class="cc-build-ring b"></div><div class="cc-build-ring c"></div>'
   +'<span class="cc-build-glyph">✦</span><span class="cc-build-name">'+esc(person)+'</span></div></div></section>';
 }
 if(state.screen==="first"){
  const plan=state.plan||localPlan();
  return '<section class="cc-first"><div class="cc-kicker"><span class="cc-kdot"></span> ПЕРСОНАЛЬНО ДЛЯ '+esc(person.toUpperCase())+'</div>'
   +'<div class="cc-first-top"><div><h2>ПЕРВОЕ<br><em>СООБЩЕНИЕ</em><br>ГОТОВО.</h2>'
   +'<p>Это начало, а не инструкция управлять чувствами человека. Ты можешь изменить текст под свой голос.</p></div>'
   +'<div class="cc-free-seal"><span>01 / FREE</span><strong>0 ₽</strong><small>ПЕРВОЕ СООБЩЕНИЕ</small></div></div>'
   +'<div class="cc-first-grid"><article class="cc-message-card"><div class="cc-message-top">'
   +'<span>01 / ЧТО НАПИСАТЬ</span><span>ПОДГОТОВЛЕНО ДЛЯ ТВОЕЙ ПАРЫ ✦</span></div>'
   +'<div class="cc-message-avatar"><b>'+esc(initials(person))+'</b><span>'+esc(person)
   +'<small>Персональное начало разговора</small></span></div>'
   +'<blockquote id="cc-first-text">'+esc(plan.first_message)+'</blockquote>'
   +action(state.copyDone?"СКОПИРОВАНО ✓":"СКОПИРОВАТЬ СООБЩЕНИЕ","copy")
   +'<p class="cc-message-hint">Отправь сообщение сам в Telegram. Конструктор ничего не рассылает за тебя.</p></article>'
   +'<aside class="cc-message-why"><small>02 / ПОЧЕМУ ТАК</small>'
   +'<h3>СНАЧАЛА<br><em>ИНТЕРЕС.</em></h3><p>'+esc(plan.why)+'</p>'
   +'<div class="cc-keyfacts"><span>Цель анкеты</span><strong>'+esc(profileGoal)+'</strong>'
   +'<span>Важный приоритет</span><strong>'+esc(profilePriority||"Не указан")+'</strong>'
   +'<span>Совместимость</span><strong>'+esc(c.score??"—")+'%</strong></div></aside></div>'
   +'<div class="cc-reply-step" id="cc-real-reply"><div><span>ЭТАП 02 / ПОСЛЕ ПЕРВОГО СООБЩЕНИЯ</span>'
   +'<h3>ОНА ОТВЕТИЛА?<br><em>ПРИНЕСИ ЕЁ ОТВЕТ СЮДА.</em></h3>'
   +'<p>Скопируй её реальное сообщение. Мы покажем, как устроена помощь с продолжением диалога. Полную персональную подсказку можно будет получить за 900 ₽ после подключения оплаты и AI.</p></div>'
   +'<form class="cc-reply-form" id="cc-reply-form"><label for="cc-real-text">ЕЁ ОТВЕТ</label>'
   +'<textarea id="cc-real-text" name="reply" rows="4" maxlength="1600" placeholder="Например: «Привет! Спасибо за сообщение. Я люблю прогулки. А ты?»" required>'
   +esc(state.reply)+'</textarea>'
   +'<div class="cc-reply-foot"><small>Не вставляй телефон, адрес или другие личные сведения. Пока текст остаётся только в браузере.</small>'
   +'<button type="submit" class="cc-btn cc-btn-primary">РАЗОБРАТЬ ЕЁ ОТВЕТ <span>↗</span></button></div></form></div>'
   +'<div class="cc-restart">'+action("← ИЗМЕНИТЬ СВОЮ ЦЕЛЬ","startOver",true)+'</div></section>';
 }
 if(state.screen==="unlock"){
  return '<section class="cc-unlock"><div class="cc-unlock-heading"><div class="cc-kicker"><span class="cc-kdot"></span> ОНА ОТВЕТИЛА — ВРЕМЯ ПРОДОЛЖИТЬ</div>'
   +'<h2>СЛЕДУЮЩИЕ<br><em>СЛОВА — ВАЖНЫ.</em></h2>'
   +'<p>Первое сообщение мы подготовили бесплатно. Теперь у тебя есть реальный ответ '+esc(person)
   +'. Подключи персональный помощник для продолжения диалога, когда появится оплата.</p></div>'
   +'<div class="cc-unlock-grid"><div class="cc-reply-preview"><small>ЕЁ РЕАЛЬНЫЙ ОТВЕТ</small>'
   +'<blockquote>'+esc(state.reply)+'</blockquote>'
   +'<span>ТЕКСТ НЕ ОТПРАВЛЯЕТСЯ НА СЕРВЕР ДО ПОКУПКИ</span></div>'
   +'<div class="cc-unlock-card"><span class="cc-unlock-badge">02 / ПЕРСОНАЛЬНОЕ ПРОДОЛЖЕНИЕ</span>'
   +'<h3>ПОМОЩНИК<br><em>В ПЕРЕПИСКЕ.</em></h3>'
   +'<div class="cc-unlock-price">'+esc(c.price_reply||900)+' <small>₽</small></div>'
   +'<p>После подключения оплаты и AI помощник сможет предложить варианты следующего сообщения, объяснить тон и помочь вести диалог дальше — без шаблонов и гарантии ответа.</p>'
   +'<div class="cc-unlock-features"><span>✦ Три варианта ответа</span><span>✦ Почему предложен именно такой тон</span><span>✦ Продолжение диалога по реальным сообщениям</span></div>'
   +'<button type="button" class="cc-unlock-disabled" disabled aria-disabled="true">ОПЛАТА ВРЕМЕННО НЕ ПОДКЛЮЧЕНА <span>↗</span></button>'
   +'<small class="cc-unlock-caption">Сейчас деньги не списываются, AI-разбор ответа пока недоступен.</small></div></div>'
   +'<div class="cc-restart">'+action("← ВЕРНУТЬСЯ К ПЕРВОМУ СООБЩЕНИЮ","backFirst",true)+'</div></section>';
 }
 return "";
}
function render(){
 mount.innerHTML=masthead()+'<main class="cc-main">'+content()+'</main>'+foot();
 requestAnimationFrame(()=>mount.querySelector(".cc-main")?.classList.add("cc-in"));
}
function scrollTop(){
 window.scrollTo({top:0,behavior:window.matchMedia("(prefers-reduced-motion: reduce)").matches?"instant":"smooth"});
}
function go(where){state.screen=where;state.error="";render();scrollTop()}
function beginBuild(){
 state.progress=0;
 state.screen="building";render();scrollTop();
 let done=false,failed=false,plan=null;
 const minimum=2850;
 const t0=performance.now();
 const tick=setInterval(()=>{
   const elapsed=performance.now()-t0;
   state.progress=Math.min(done?100:96,Math.floor(elapsed/42));
   if(elapsed<minimum)state.progress=Math.min(state.progress,93);
   const meter=mount.querySelector(".cc-build-line i");
   if(meter)meter.style.width=state.progress+"%";
   const percent=mount.querySelector(".cc-build-label strong");
   if(percent)percent.textContent=state.progress+"%";
   const labels=["Сверяем цели и ценности","Сопоставляем контекст анкеты","Выбираем интонацию","Формулируем первое сообщение"];
   const current=labels[Math.min(labels.length-1,Math.floor(state.progress/25))];
   const subtitle=mount.querySelector(".cc-build-label span");if(subtitle)subtitle.textContent=current;
   const rows=mount.querySelectorAll(".cc-build-stages>div");
   rows.forEach((el,i)=>{el.classList.toggle("on",i<=Math.floor(state.progress/25));el.querySelector("b").textContent=i<Math.floor(state.progress/25)?"✓":i===Math.floor(state.progress/25)?"●":""});
   if(done&&elapsed>=minimum){
      clearInterval(tick);
      if(failed){state.step=2;state.error="Не удалось сохранить план на сервере. Проверь подключение и попробуй ещё раз.";go("quiz");return;}
      state.plan=plan||localPlan();state.copyDone=false;go("first");
   }
 },80);
 const finish=(value,error)=>{done=true;failed=!!error;plan=value;};
 if(c.demo||!c.prepare){
   finish(localPlan(),null);
 }else{
   const controller=new AbortController();
   const kill=setTimeout(()=>controller.abort(),14000);
   fetch(c.prepare,{method:"POST",headers:{"Content-Type":"application/json"},credentials:"same-origin",signal:controller.signal,body:JSON.stringify(state.answers)})
    .then(r=>{if(!r.ok)throw Error("Сохранение недоступно");return r.json()})
    .then(data=>{clearTimeout(kill);if(!data.first_message||!data.why)throw Error("Нет сообщения");finish(data,null)})
    .catch(e=>{clearTimeout(kill);finish(null,e)});
 }
}
async function copyMessage(){
 const value=String((state.plan||localPlan()).first_message);
 try{
  if(navigator.clipboard?.writeText)await navigator.clipboard.writeText(value);
  else{
    const t=document.createElement("textarea");t.value=value;document.body.appendChild(t);t.select();
    if(!document.execCommand("copy"))throw Error("Copy failed");t.remove();
  }
  state.copyDone=true;const btn=mount.querySelector('[data-action="copy"]');
  if(btn)btn.innerHTML="СКОПИРОВАНО ✓ <span>↗</span>";
 }catch(e){
  const box=mount.querySelector("#cc-first-text");
  if(box){const range=document.createRange();range.selectNodeContents(box);window.getSelection()?.removeAllRanges();window.getSelection()?.addRange(range);}
  const hint=mount.querySelector(".cc-message-hint");
  if(hint)hint.textContent="Текст выделен — скопируй его долгим нажатием.";
 }
}
mount.addEventListener("click",e=>{
 const opt=e.target.closest("[data-choice]");
 if(opt){state.answers[questions[state.step].key]=opt.dataset.choice;render();return;}
 const b=e.target.closest("[data-action]");
 if(!b)return;
 const action=b.dataset.action;
 if(action==="begin"){state.step=0;go("quiz");}
 else if(action==="prev"){if(state.step>0){state.step--;go("quiz");}else go("intro");}
 else if(action==="next"){
  if(!state.answers[questions[state.step].key]){
    const list=mount.querySelector(".cc-options");if(list){list.classList.add("cc-shake");setTimeout(()=>list.classList.remove("cc-shake"),400)}return;
  }
  if(state.step<2){state.step++;go("quiz");}else beginBuild();
 }
 else if(action==="copy")copyMessage();
 else if(action==="startOver"){state.step=0;go("quiz");}
 else if(action==="backFirst")go("first");
});
mount.addEventListener("submit",e=>{
 if(e.target.id!=="cc-reply-form")return;
 e.preventDefault();
 const text=mount.querySelector("#cc-real-text")?.value?.trim()||"";
 if(text.length<3)return;
 state.reply=text.slice(0,1600);
 go("unlock");
});
render();
})();
