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
  reply:"",error:"",progress:0,copyDone:false,buildingText:"",aiBusy:false,aiError:"",aiReport:null
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
 let question=found?found[2]:"Что для тебя важно в начале общения с новым человеком?";
 let open=found?"Привет, "+name+"! Увидел, что тебе важно "+found[1]+".":"Привет, "+name+"! Мне откликнулась твоя анкета.";
 if(state.answers.intent==="date"&&state.answers.tempo==="soon")question="Если разговор пойдёт легко, что тебе ближе для первой встречи — прогулка или кофе?";
 else if(state.answers.intent==="date"&&state.answers.tempo==="week")question="Как ты обычно любишь проводить свободные выходные?";
 else if(state.answers.intent==="relationship"&&!found)question="Что для тебя важнее всего в отношениях, которые хочется строить надолго?";
 if(state.answers.tempo==="slow")question="Что тебе особенно интересно узнавать о человеке в самом начале общения?";
 if(state.answers.intent==="relationship")open="Привет, "+name+"! Мне понравилось, что мы оба открыты к серьёзному знакомству.";
 else if(state.answers.intent==="date"&&state.answers.tempo!=="slow")open="Привет, "+name+"! Мне откликнулась твоя анкета, захотелось познакомиться.";
 let message=state.answers.tone==="direct"
  ?name+", привет! "+question
  :state.answers.tone==="playful"
  ?open+" Кажется, у нас есть с чего начать 🙂 "+question
  :open+" "+question;
 const goal={"talk":"пообщаться","date":"познакомиться с перспективой свидания","relationship":"серьёзные отношения"}[state.answers.intent]||"общение";
 const pace={"soon":"начать сейчас","week":"узнавать друг друга в течение недели","slow":"не торопить события"}[state.answers.tempo]||"постепенно";
 return {
  first_message:message,
  why:"Этот пример основан на приоритете из анкеты — «"+(priority||"не указан")+"», твоей цели («"+goal+"») и темпе («"+pace+"»). Мы предлагаем открытый вопрос, который не навязывает встречу или чувства. Астрология и нумерология не позволяют знать чужие мысли.",
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
   +'<div><b>'+(c.workshop_paid?'ОПЛАЧЕНО':'ДЕМО')+'</b><span>ЭМУЛЯТОР<br>ОБЩЕНИЯ</span></div></div>'
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
   +'<div class="cc-free-seal"><span>01 / TEST</span><strong>FREE</strong><small>ПЕРВОЕ СООБЩЕНИЕ</small></div></div>'
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
   +'<p>Скопируй её ответ и проверь, как конструктор предлагает продолжить разговор. На тесте всё открыто без оплаты. Это пример подсказки, не полноценный AI.</p></div>'
   +'<form class="cc-reply-form" id="cc-reply-form"><label for="cc-real-text">ЕЁ ОТВЕТ</label>'
   +'<textarea id="cc-real-text" name="reply" rows="4" maxlength="1600" placeholder="Например: «Привет! Спасибо за сообщение. Я люблю прогулки. А ты?»" required>'
   +esc(state.reply)+'</textarea>'
   +'<div class="cc-reply-foot"><small>Не вставляй телефон, адрес или другие личные сведения. Пока текст остаётся только в браузере.</small>'
   +'<button type="submit" class="cc-btn cc-btn-primary">РАЗОБРАТЬ ЕЁ ОТВЕТ <span>↗</span></button></div></form></div>'
   +'<div class="cc-restart">'+action("← ИЗМЕНИТЬ СВОЮ ЦЕЛЬ","startOver",true)+'</div></section>';
 }
 if(state.screen==="unlock"){
  const guidance=replyDraft(state.reply);
  return '<section class="cc-unlock"><div class="cc-unlock-heading">'
   +'<div class="cc-kicker"><span class="cc-kdot"></span> ЭТАП 02 / ТЕСТОВОЕ ПРОДОЛЖЕНИЕ</div>'
   +'<h2>ОНА ОТВЕТИЛА.<br><em>ЧТО НАПИСАТЬ ДАЛЬШЕ?</em></h2>'
   +'<p>Ниже — пример работы помощника с сообщением, которое ты вставил. Подсказки создаются по сценариям, а не AI. Они помогают потренироваться, но не предсказывают ответ человека.</p></div>'
   +'<div class="cc-unlock-grid"><div class="cc-reply-preview"><small>ЕЁ ОТВЕТ — ИЗ ТВОЕГО ТЕСТА</small>'
   +'<blockquote>'+esc(state.reply)+'</blockquote>'
   +'<span>ТЕКСТ АНАЛИЗИРУЕТСЯ В ТВОЁМ БРАУЗЕРЕ · НЕ ОТПРАВЛЯЕТСЯ НА СЕРВЕР</span></div>'
   +'<div class="cc-unlock-card"><span class="cc-unlock-badge">02 / СЛЕДУЮЩЕЕ СООБЩЕНИЕ · ТЕСТ</span>'
   +'<h3>ВОТ КАК<br><em>МОЖНО ОТВЕТИТЬ.</em></h3>'
   +'<p class="cc-test-tip">Вариант продолжения</p>'
   +'<blockquote class="cc-test-answer" id="cc-next-text">'+esc(guidance.text)+'</blockquote>'
   +action(state.copyDone?"СКОПИРОВАНО ✓":"СКОПИРОВАТЬ ПОДСКАЗКУ","copyReply")
   +'<div class="cc-guide-why"><span>ПОЧЕМУ ТАК</span><p>'+esc(guidance.why)+'</p></div>'
   +'<div class="cc-test-note">🧪 БЕСПЛАТНЫЙ ШАБЛОН · НЕ AI · БЕЗ АВТОМАТИЧЕСКОЙ ОТПРАВКИ</div>'
   +'</div></div>'
   +(c.paid_ai_available&&c.paid_checkout_path?'<section class="cc-unlock-card" style="margin-top:22px"><span class="cc-unlock-badge">03 / ПЕРСОНАЛЬНЫЙ РАЗБОР</span><h3>А ЕСЛИ<br><em>РАЗОБРАТЬ ГЛУБЖЕ?</em></h3>'
     +'<p class="cc-test-tip">Один подробный AI-разбор реального ответа и альтернативы. 900 ₽ за один результат. Никаких автосписаний.</p>'
     +(c.paid_reply_ready?
       '<p class="cc-test-tip">Платёж подтверждён. Только после нажатия твой текст будет передан ИИ. Не вставляй секреты или личные сведения.</p>'
       +'<button class="cc-btn cc-btn-primary" type="button" data-action="paidAi"'+(state.aiBusy?' disabled':'')+'>'+(state.aiBusy?'ГОТОВИМ РАЗБОР…':'СОЗДАТЬ ОПЛАЧЕННЫЙ AI-РАЗБОР')+' <span>↗</span></button>'
       :'<a class="cc-btn cc-btn-primary" href="'+esc(c.paid_checkout_path)+'">ПЕРСОНАЛЬНЫЙ AI-РАЗБОР · 900 ₽ ↗</a>')
     +(state.aiError?'<p class="cc-test-note" role="alert">'+esc(state.aiError)+'</p>':'')
     +(state.aiReport?'<blockquote class="cc-test-answer" style="white-space:pre-wrap">'+esc(state.aiReport)+'</blockquote>':'')
     +'</section>':'')
   +'<div class="cc-restart">'+action("← ПОПРОБОВАТЬ ДРУГОЙ ОТВЕТ","backFirst",true)
   +'</div></section>';
 }
 return "";
}
function replyDraft(raw){
  const reply=String(raw||"").trim();
  // Test-only deterministic rules entirely inside the user's browser.
  if(/(?:не хочу|не интересно|не интересует|не пиши|не готова?|нет[,.! ]*спасибо|оставь меня|отстань)/i.test(reply)){
    return {text:"Спасибо, что сказала прямо. Я уважаю твоё решение и не буду настаивать.",
      why:"Человек обозначил границу. Уважительный ответ без повторных предложений важнее попытки продолжить знакомство."};
  }
  if(/(?:свидани|встрет|встреч|прогул|кофе|кафе|увидеться)/i.test(reply)){
    return {text:"Здорово, мне тоже приятно продолжить знакомство. Как ты смотришь на спокойную прогулку или кофе, когда нам обоим будет удобно?",
      why:"В ответе появилась тема встречи. Предлагаем конкретный, но необязательный вариант, сохраняя свободу выбора времени и места."};
  }
  if(/(?:путешеств|поездк|отдых|город|страна|море)/i.test(reply)){
    return {text:"Здорово! Мне всегда интересно узнавать, какие места нравятся людям. А что тебе особенно запомнилось из поездок?",
      why:"Подхватываем тему собеседника, вместо резкой смены темы или давления."};
  }
  if(/(?:книг|фильм|сериал|музык|концерт|спорт|трениров)/i.test(reply)){
    return {text:"Интересно! А что тебе больше всего нравится в этом увлечении? Посоветуешь, с чего лучше начать?",
      why:"Уточняющий вопрос помогает человеку раскрыть собственные интересы и не требует длинного ответа."};
  }
  if(reply.includes("?")){
    return {text:"Спасибо за вопрос! Я бы ответил своими словами, а потом спросил: «А как у тебя с этим?»",
      why:"Если тебе задали вопрос, сначала ответь честно — не игнорируй его ради готового скрипта. Замени пример своим настоящим ответом."};
  }
  if(reply.length<24){
    return {text:"Рад, что ты ответила 🙂 Как у тебя проходит день? Есть что-то, что сегодня особенно порадовало?",
      why:"На короткий ответ предлагаем лёгкий открытый вопрос без попытки форсировать встречу."};
  }
  return {text:"Спасибо, что поделилась! Мне интересно узнать тебя получше. А что в этом для тебя самое важное?",
    why:"Поддерживаем доброжелательный тон и задаём один открытый вопрос. Это тестовый пример, не AI-анализ."};
}
function render(){
 mount.innerHTML=masthead()+'<main class="cc-main">'+content()+'</main>'+foot();
 requestAnimationFrame(()=>mount.querySelector(".cc-main")?.classList.add("cc-in"));
}
function scrollTop(){
 window.scrollTo({top:0,behavior:window.matchMedia("(prefers-reduced-motion: reduce)").matches?"auto":"smooth"});
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
   state.progress=Math.min(done?100:96,Math.floor(elapsed/minimum*100));
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
      if(failed){state.step=2;go("quiz");state.error="Не удалось сохранить план на сервере. Проверь подключение и попробуй ещё раз.";render();return;}
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
async function copyMessage(replyMode=false){
 const value=replyMode?replyDraft(state.reply).text:String((state.plan||localPlan()).first_message);
 try{
  if(navigator.clipboard?.writeText)await navigator.clipboard.writeText(value);
  else{
    const t=document.createElement("textarea");t.value=value;document.body.appendChild(t);t.select();
    if(!document.execCommand("copy"))throw Error("Copy failed");t.remove();
  }
  state.copyDone=true;const btn=mount.querySelector(replyMode?'[data-action="copyReply"]':'[data-action="copy"]');
  if(btn)btn.innerHTML="СКОПИРОВАНО ✓ <span>↗</span>";
 }catch(e){
  const box=mount.querySelector(replyMode?"#cc-next-text":"#cc-first-text");
  if(box){const range=document.createRange();range.selectNodeContents(box);window.getSelection()?.removeAllRanges();window.getSelection()?.addRange(range);}
  const hint=mount.querySelector(replyMode?".cc-test-note":".cc-message-hint");
  if(hint)hint.textContent="Текст выделен — скопируй его долгим нажатием.";
 }
}
async function requestAiReport(){
 if(state.aiBusy||!c.paid_reply_ready||!c.paid_reply_path||!c.paid_csrf)return;
 if(state.reply.trim().length<3){state.aiError="Сначала вставь реальный ответ собеседника.";render();return;}
 state.aiBusy=true;state.aiError="";render();
 try{
   const response=await fetch(c.paid_reply_path,{
     method:"POST",credentials:"same-origin",
     headers:{"Content-Type":"application/json"},
     body:JSON.stringify({reply:state.reply,consent:true,csrf:c.paid_csrf})
   });
   const data=await response.json();
   if(!response.ok||!data.ok||!data.report)throw Error(data.message||"Сервис временно недоступен");
   state.aiReport=String(data.report);
 }catch(e){state.aiError=String(e.message||"Разбор пока не готов. Оплата сохранена.");}
 finally{state.aiBusy=false;render();}
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
 else if(action==="copyReply")copyMessage(true);
 else if(action==="paidAi")requestAiReport();
 else if(action==="startOver"){state.step=0;go("quiz");}
 else if(action==="backFirst")go("first");
});
mount.addEventListener("submit",e=>{
 if(e.target.id!=="cc-reply-form")return;
 e.preventDefault();
 const text=mount.querySelector("#cc-real-text")?.value?.trim()||"";
 if(text.length<3)return;
 state.reply=text.slice(0,1600);state.copyDone=false;
 go("unlock");
});
render();
})();
