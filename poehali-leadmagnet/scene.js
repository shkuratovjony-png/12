
(()=>{"use strict";
const $=s=>document.querySelector(s), $$=s=>[...document.querySelectorAll(s)];
const story=$("#story"),stepNumber=$("#stepNumber"),title=$("#stepTitle"),description=$("#stepText"),
 tag=$("#stepTag"),indicators=$$(".story-indicators i"),nodes=$$(".dnode"),paths=$$(".diagram-routes path"),
 core=$("#diagramCore"),gesture=$("#gesture"),line=$("#gestureLine"),tip=$("#gestureTip"),
 progressBar=$("#progressFill");
const steps=[
 ["00 / НАЧАЛО","Всё начинается с одной идеи.","Листай — и на доске шаг за шагом сложится система цифрового продукта."],
 ["01 / GPT","Сначала — идея.","GPT поможет найти проблему, собрать варианты решения и наметить, как проверить спрос."],
 ["02 / TELEGRAM","Потом — продукт.","Бот знакомит человека с предложением, отвечает по сценарию и помогает пройти путь до покупки."],
 ["03 / АУДИТОРИЯ","Теперь — внимание людей.","Короткие ролики и полезный контент приводят заинтересованных. Сначала проверяем, что работает."],
 ["04 / АВТОМАТИЗАЦИЯ","И всё соединяется.","Подтверждённая оплата, выдача материалов и сообщения складываются в одну управляемую систему."]
];
const endpoints=[[0,0],[455,179],[844,179],[455,465],[844,465]];
const lengths=paths.map(path=>{
 try{const n=path.getTotalLength();path.style.strokeDasharray=String(n);path.style.strokeDashoffset=String(n);return n}
 catch(e){return 1000}
});
let active=-1,raf=false,quiet=matchMedia("(prefers-reduced-motion: reduce)").matches;
const clamp=(v,a=0,b=1)=>Math.max(a,Math.min(b,v));
function update(){
 raf=false;
 const max=document.documentElement.scrollHeight-innerHeight;
 progressBar.style.width=(max>0?clamp(scrollY/max)*100:0)+"%";
 const h=Math.max(1,story.offsetHeight-innerHeight);
 const p=clamp(-story.getBoundingClientRect().top/h);
 const stage=clamp(Math.floor(p*5+.0001),0,4);
 nodes.forEach((n,i)=>{n.classList.toggle("visible",stage>=i+1);n.classList.toggle("active",stage===i+1)});
 core.classList.toggle("visible",stage===4);
 paths.forEach((path,i)=>{
   const v=clamp((p*5-(i+1)*.78)/.95);
   path.style.strokeDashoffset=String(lengths[i]*(1-v));
 });
 indicators.forEach((b,i)=>b.classList.toggle("active",i===stage));
 stepNumber.textContent=String(stage+1).padStart(2,"0");
 if(stage!==active){
   active=stage;
   tag.textContent=steps[stage][0];
   title.textContent=steps[stage][1];
   description.textContent=steps[stage][2];
   if(!quiet){
     title.animate([{opacity:.2,transform:"translateY(12px)"},{opacity:1,transform:"translateY(0)"}],{duration:550,easing:"cubic-bezier(.22,1,.36,1)"});
     description.animate([{opacity:.2,transform:"translateY(7px)"},{opacity:1,transform:"translateY(0)"}],{duration:620,easing:"cubic-bezier(.22,1,.36,1)"});
   }
   if(stage===0)gesture.classList.remove("active");
   else{
     const point=endpoints[stage];
     line.setAttribute("x2",point[0]);line.setAttribute("y2",point[1]);
     tip.setAttribute("cx",point[0]);tip.setAttribute("cy",point[1]);
     gesture.classList.add("active");
   }
   playStage(stage);
 }
}
function refresh(){if(!raf){raf=true;requestAnimationFrame(update)}}
addEventListener("scroll",refresh,{passive:true});
addEventListener("resize",refresh,{passive:true});
addEventListener("pageshow",refresh);requestAnimationFrame(update);
const scene=$(".hero-diagram");
if(scene&&!quiet){
 scene.parentElement.addEventListener("pointermove",e=>{
   if(e.pointerType==="touch")return;
   const r=scene.getBoundingClientRect();
   const x=clamp((e.clientX-r.left)/r.width-.5,-.5,.5),y=clamp((e.clientY-r.top)/r.height-.5,-.5,.5);
   scene.style.transform="rotate("+(-5+x*3)+"deg) rotateY("+(-11+x*12)+"deg) rotateX("+(3-y*11)+"deg)";
 },{passive:true});
 scene.parentElement.addEventListener("pointerleave",()=>scene.style.transform="");
}
if("IntersectionObserver" in window){
 const obs=new IntersectionObserver(entries=>entries.forEach(item=>{
  if(item.isIntersecting){item.target.classList.add("inview");obs.unobserve(item.target)}
 }),{threshold:.1});
 $$(".enter-onview").forEach(el=>obs.observe(el));
}else $$(".enter-onview").forEach(el=>el.classList.add("inview"));
const audio=$("#narrationAudio"),voice=$("#audioToggle"),voiceText=$("#voiceLabel");
let voiceOn=false,speaking=-1;
function playStage(i){
 if(!voiceOn)return;
 if(i<1||i>4){audio.pause();speaking=-1;return}
 if(speaking===i)return;
 speaking=i;audio.src="audio/"+String(i).padStart(2,"0")+".mp3";
 audio.play().catch(()=>{voiceOn=false;speaking=-1;voiceUpdate()});
}
function voiceUpdate(){
 voice.setAttribute("aria-pressed",String(voiceOn));
 voice.setAttribute("aria-label",voiceOn?"Выключить рассказ":"Включить рассказ");
 voiceText.textContent=voiceOn?"Звук включён":"Со звуком";
}
voice.addEventListener("click",()=>{
 voiceOn=!voiceOn;
 if(!voiceOn){audio.pause();speaking=-1}
 voiceUpdate();
 if(voiceOn)playStage(active<0?0:active);
});
addEventListener("pagehide",()=>audio.pause());voiceUpdate();
const download=$("#saveSchema");
download.addEventListener("click",()=>{
 const svg=['<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="740" viewBox="0 0 1200 740">',
 '<rect width="1200" height="740" fill="#f7f9f5"/>',
 '<text x="70" y="97" font-family="Arial" font-size="24" font-weight="bold" fill="#2e5d45">ПОЕХАЛИ · БЕСПЛАТНАЯ СХЕМА</text>',
 '<text x="70" y="163" font-family="Arial" font-size="49" font-weight="bold" fill="#173c2b">От идеи до своей системы.</text>',
 '<g stroke="#83a68d" stroke-width="5" fill="none"><path d="M370 320H490"/><path d="M710 320H820"/><path d="M360 555H490"/><path d="M710 555H820"/><path d="M600 410v90"/></g>',
 '<g fill="#fff" stroke="#d7e4d8" stroke-width="2"><rect x="65" y="240" width="305" height="160" rx="22"/><rect x="825" y="240" width="305" height="160" rx="22"/><rect x="65" y="470" width="305" height="160" rx="22"/><rect x="825" y="470" width="305" height="160" rx="22"/></g>',
 '<circle cx="600" cy="400" r="126" fill="#1c503a" stroke="#f7f9f5" stroke-width="13"/>',
 '<g font-family="Arial,sans-serif" fill="#1d533d">',
 '<text x="95" y="296" font-size="20" fill="#7ba08a">01 · ИДЕЯ</text><text x="95" y="345" font-size="39" font-weight="bold">GPT</text>',
 '<text x="854" y="296" font-size="20" fill="#7ba08a">02 · ПРОДУКТ</text><text x="854" y="345" font-size="39" font-weight="bold">Telegram</text>',
 '<text x="95" y="526" font-size="20" fill="#7ba08a">03 · ЛЮДИ</text><text x="95" y="575" font-size="39" font-weight="bold">Контент</text>',
 '<text x="854" y="526" font-size="20" fill="#7ba08a">04 · АВТОМАТИЗАЦИЯ</text><text x="854" y="575" font-size="39" font-weight="bold">Оплата</text></g>',
 '<text x="600" y="383" text-anchor="middle" font-family="Arial" font-size="27" fill="#fff">ВАША</text>',
 '<text x="600" y="422" text-anchor="middle" font-family="Arial" font-size="37" font-weight="bold" fill="#fff">СИСТЕМА</text>',
 '<text x="70" y="700" font-family="Arial" font-size="19" fill="#718b79">Схема бесплатна. Курс по сборке системы приобретается отдельно.</text></svg>'].join("");
 const url=URL.createObjectURL(new Blob([svg],{type:"image/svg+xml;charset=utf-8"}));
 const a=document.createElement("a");a.href=url;a.download="poehali-shema.svg";document.body.append(a);a.click();a.remove();
 setTimeout(()=>URL.revokeObjectURL(url),1500);
});
const q=new URLSearchParams(location.search),p=q.get("ft")||"";
const ref=/^[A-Za-z0-9_-]{30,70}$/.test(p)?p:"";
const BASE="https://poehali-checkout.onrender.com";
const target=BASE+"/checkout"+(ref?"?funnel="+encodeURIComponent(ref):"");
const buy=$("#buyCourse"),modal=$("#paymentWait"),modalText=$("#paymentWaitText"),cancel=$("#paymentCancel");
let ready=false,task=null,pending=false,eventSent=false;
async function health(){
 try{
  const r=await fetch(BASE+"/health",{method:"GET",mode:"cors",credentials:"omit",cache:"no-store"});
  if(!r.ok)return false;
  const d=await r.json();ready=Boolean(d&&d.checkout_ready===true);
  if(ready&&ref&&!eventSent){
    eventSent=true;
    fetch(BASE+"/funnel/event",{method:"POST",mode:"cors",credentials:"omit",keepalive:true,
     headers:{"Content-Type":"application/json"},body:JSON.stringify({kind:"landing",ref})}).catch(()=>{});
  }
  return ready;
 }catch(e){return false}
}
function wake(){
 if(ready)return Promise.resolve(true);
 if(task)return task;
 task=(async()=>{
   const until=Date.now()+90000;
   while(Date.now()<until){
     if(await health())return true;
     await new Promise(done=>setTimeout(done,3000));
   }
   return false;
 })().finally(()=>{task=null});
 return task;
}
void wake();
function close(){
 pending=false;modal.classList.remove("open");modal.setAttribute("aria-hidden","true");buy.focus();
}
buy.addEventListener("click",()=>{
 if(ready){location.assign(target);return}
 pending=true;modalText.textContent="Подключаем защищённую оплату…";
 modal.classList.add("open");modal.setAttribute("aria-hidden","false");
 wake().then(ok=>{
   if(!pending)return;
   if(ok)location.assign(target);
   else modalText.textContent="Подключение заняло больше обычного. Попробуй ещё раз чуть позже.";
 });
});
cancel.addEventListener("click",close);
modal.addEventListener("click",e=>{if(e.target===modal)close()});
addEventListener("keydown",e=>{if(e.key==="Escape"&&modal.classList.contains("open"))close()});
})();
