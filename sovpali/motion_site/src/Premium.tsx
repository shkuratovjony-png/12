import React, { useEffect, useRef, useState } from "react";
import { ArrowDown, ArrowUpRight, ArrowRight, X, Heart, ShieldCheck, LockKeyhole, MoveUpRight, Info, Check, ChevronRight, Sparkles } from "lucide-react";
import "./Experience.css";
type Person={name:string; initial:string; age:number|null; city:string; goal:string; priority:string; photo:string|null};
type Factor={n:string; tag:string; title:string; score:number; copy:string; basis:string;};
type PairPayload={demo:boolean; score:number; reasons:string[]; viewer:Person; candidate:Person; factors:Factor[]; astro:string; numerology:string; same_city:boolean; price:number; payments_enabled:boolean; engagement_path:string|null; checkout_path:string|null; version:string};
declare global {interface Window {__SOVPALI_PAIR__?:PairPayload}}
const pair:PairPayload=window.__SOVPALI_PAIR__||{
 demo:true,score:0,reasons:[],viewer:{name:"Вы",initial:"В",age:null,city:"",goal:"",priority:"",photo:null},
 candidate:{name:"Пара",initial:"♡",age:null,city:"",goal:"",priority:"",photo:null},
 factors:[{n:"01",tag:"Цели",title:"Цели отношений",score:0,copy:"",basis:""},{n:"02",tag:"Ценности",title:"Главные ценности",score:0,copy:"",basis:""},{n:"03",tag:"Астрология",title:"Астрологический разбор",score:0,copy:"",basis:""},{n:"04",tag:"Нумерология",title:"Нумерологический разбор",score:0,copy:"",basis:""}],
 astro:"",numerology:"",same_city:false,price:100,payments_enabled:false,engagement_path:null,checkout_path:null,version:"motion-live-01"};
const factors=pair.factors;
const woman=pair.candidate.photo,man=pair.viewer.photo;
const personAge=(p:Person)=>p.age===null?"":", "+p.age;
function Portrait({src,name,loading="lazy"}:{src:string|null;name:string;loading?:"lazy"|"eager"}){
 const [failed,setFailed]=useState(false);useEffect(()=>setFailed(false),[src]);
 return src&&!failed ? <img src={src} alt={"Фото анкеты: "+name} loading={loading} decoding="async" referrerPolicy="no-referrer" onError={()=>setFailed(true)}/> :
 <div className="sx-photo-empty" aria-label={"В анкете нет фотографии: "+name}><span>{(name||"♡").slice(0,1).toUpperCase()}</span><small>ФОТО НЕ ДОБАВЛЕНО</small></div>;
}
function useReveal() {
  useEffect(() => {
    const es = document.querySelectorAll(".sx [data-reveal]");
    if (!("IntersectionObserver" in window)) {
      es.forEach(x => x.classList.add("sx-in"));
      return;
    }
    const io = new IntersectionObserver(entries => {
      entries.forEach(e => {
        if (e.isIntersecting) {
          e.target.classList.add("sx-in");
          io.unobserve(e.target);
        }
      });
    }, {
      threshold: .10,
      rootMargin: "0px 0px -25px 0px"
    });
    es.forEach(e => io.observe(e));
    return () => io.disconnect();
  }, []);
}
function AnimatedNumber({
  value
}: {
  value: number;
}) {
  const [n, setN] = useState(0);
  const ref = useRef<HTMLSpanElement>(null);
  useEffect(() => {
    let frame = 0,
      started = false,
      start = 0;
    const el = ref.current;
    if (!el) return;
    const io = new IntersectionObserver(entries => {
      if (!entries[0].isIntersecting || started) return;
      started = true;
      const animate = (t: number) => {
        if (!start) start = t;
        const p = Math.min(1, (t - start) / 1500);
        setN(Math.round(value * (1 - Math.pow(1 - p, 4))));
        if (p < 1) frame = requestAnimationFrame(animate);
      };
      frame = requestAnimationFrame(animate);
    });
    io.observe(el);
    return () => {
      io.disconnect();
      cancelAnimationFrame(frame);
    };
  }, [value]);
  return <span ref={ref}>{n}</span>;
}
function Mark({
  className = ""
}: {
  className?: string;
}) {
  return <div className={"sx-mark " + className}><span className="sx-mark-symbol">♡</span><span>совпали<span className="sx-dot">.</span></span></div>;
}
function BigHeart() {
  return <svg className="sx-heart-svg" width="120" height="120" viewBox="0 0 120 120" fill="none" aria-hidden="true"><path d="M60 99C50 90 15 67 15 42C15 13 47 11 60 33C73 11 105 13 105 42C105 67 70 90 60 99Z" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" /><path d="M60 87C50 78 29 62 29 43C29 29 49 27 60 46C71 27 91 29 91 43C91 62 70 78 60 87Z" stroke="currentColor" strokeWidth=".6" strokeOpacity=".5" /></svg>;
}
function Connection({
  active
}: {
  active: number;
}) {
  return <div className="sx-orbit" aria-hidden="true"><div className="sx-orbit-halo" /><div className="sx-orbit-circle sx-orbit-1" /><div className="sx-orbit-circle sx-orbit-2" /><div className="sx-orbit-circle sx-orbit-3" /><div className="sx-orbit-line sx-orbit-line-1" /><div className="sx-orbit-line sx-orbit-line-2" /><div className="sx-orbit-nudge" /><div className="sx-orbit-core"><svg viewBox="0 0 180 180"><defs><linearGradient id="sxg" x1="0" y1="0" x2="1" y2="1"><stop stopColor="#F6B2A7" /><stop offset="1" stopColor="#B8778B" /></linearGradient></defs><circle cx="90" cy="90" r="68" fill="none" stroke="#F2E7DE" strokeOpacity=".25" strokeWidth="1" /><circle cx="90" cy="90" r="68" fill="none" stroke="url(#sxg)" strokeWidth="3" strokeDasharray="285 145" strokeLinecap="round" transform="rotate(-90 90 90)" /><text x="90" y="94" textAnchor="middle" fontFamily="inherit" fill="#F6E9E2" fontSize="42" fontWeight="400" letterSpacing="-4">{factors[active].score}</text><text x="90" y="114" textAnchor="middle" fill="#D0AEB6" fontSize="10" letterSpacing="3">/ 100</text></svg></div><span className="sx-orbit-node sx-node-1" /><span className="sx-orbit-node sx-node-2" /><span className="sx-orbit-node sx-node-3" /><span className="sx-orbit-node sx-node-4" /></div>;
}
function RevealLine({
  children,
  small = false
}: {
  children: React.ReactNode;
  small?: boolean;
}) {
  return <div data-reveal className={small ? "sx-reveal-small" : "sx-reveal-text"}>{children}</div>;
}

/**
 * One passive scroll listener + one requestAnimationFrame for the entire story.
 * We mutate CSS custom properties directly to avoid React re-renders on every
 * scroll event. Safari/iPhone scroll remains native and fully touch-driven.
 */
function useCinematicScroll() {
  useEffect(() => {
    const root = document.querySelector<HTMLElement>(".sx");
    const journey = document.querySelector<HTMLElement>(".sx-journey");
    const candidate = document.getElementById("sx-match");
    const data = document.getElementById("sx-data");
    const quote = document.querySelector<HTMLElement>(".sx-quote");
    const nav = document.querySelector<HTMLElement>(".sx-nav");
    if (!root || !journey) return;
    const motion = window.matchMedia("(prefers-reduced-motion: reduce)");
    const clamp = (v: number) => Math.max(0, Math.min(1, v));
    const ease = (v: number) => {
      const p = clamp(v);
      return p * p * (3 - 2 * p);
    };
    let ticking = false;
    let raf = 0;
    const set = (k: string, v: string | number) => {
      // Scope invalidation to the active scene, not the entire long page.
      const target = k.startsWith("candidate-") ? candidate : k.startsWith("diagram-") ? data : k.startsWith("quote-") ? quote : k === "page-progress" ? nav : journey;
      (target || root).style.setProperty("--sx-" + k, String(v));
    };
    const update = () => {
      ticking = false;
      const viewport = Math.max(320, window.innerHeight);
      const rect = journey.getBoundingClientRect();
      // Read all geometry together BEFORE mutating styles (avoids layout thrash).
      const candidateRect = candidate?.getBoundingClientRect();
      const dataRect = data?.getBoundingClientRect();
      const quoteRect = quote?.getBoundingClientRect();
      const travel = Math.max(1, journey.offsetHeight - viewport);
      const p = clamp(-rect.top / travel);
      const compact = window.matchMedia("(max-width: 780px)").matches;
      const f = ease((p - .19) / .57);
      const fly = ease((p - .10) / .46);
      const out = ease((p - .08) / .29);
      const caption = ease((p - .67) / .19);
      const initial = compact ? [57, 8, 9, 50] : [20, 7, 18, 65];
      const names = ["clip-top", "clip-right", "clip-bottom", "clip-left"];
      initial.forEach((v, i) => set(names[i], (v * (1 - f)).toFixed(2) + "%"));
      set("journey", p.toFixed(4));
      set("fly", fly.toFixed(4));
      const ww = window.innerWidth;
      // Precompute pixel transforms: no CSS multiplication (Safari compatibility).
      set("photo-a-x", (-fly * ww * (compact ? .18 : .19)).toFixed(2) + "px");
      set("photo-a-y", (-fly * viewport * .08).toFixed(2) + "px");
      set("photo-a-rotation", (-6 - fly * (compact ? 12 : 19)).toFixed(2) + "deg");
      set("photo-a-scale", (1 - fly * (compact ? .15 : .18)).toFixed(4));
      set("photo-b-x", (-fly * ww * (compact ? .18 : .32)).toFixed(2) + "px");
      set("photo-b-y", (-fly * viewport * (compact ? .21 : .04)).toFixed(2) + "px");
      set("photo-b-rotation", (5 - 5 * fly).toFixed(2) + "deg");
      set("photo-b-scale", (1 + fly * (compact ? 2.65 : 2.1)).toFixed(4));
      set("hero-lift-y", (-65 * out).toFixed(1) + "px");
      set("hero-opacity", (1 - out).toFixed(4));
      set("hero-lift", out.toFixed(4));
      set("photo-opacity", (1 - ease((p - .30) / .19)).toFixed(4));
      set("heart-opacity", (1 - ease((p - .12) / .23)).toFixed(4));
      set("film-opacity", ease((p - .24) / .14).toFixed(4));
      set("film-caption", caption.toFixed(4));
      set("film-shift", (-24 * (1 - caption)).toFixed(1) + "px");
      // Progress indicators respond to the page's real scroll position.
      const doc = Math.max(1, document.documentElement.scrollHeight - viewport);
      set("page-progress", (window.scrollY / doc).toFixed(5));
      if (candidate && candidateRect) {
        const v = ease((viewport - candidateRect.top) / (viewport + candidateRect.height * .52));
        set("candidate-clip", (16 * (1 - v)).toFixed(2) + "%");
        set("candidate-scale", (1.15 - .13 * v).toFixed(4));
        set("candidate-shift", (38 * (1 - v)).toFixed(2) + "px");
      }
      if (data && dataRect) {
        const v = ease((viewport - dataRect.top) / (viewport + dataRect.height * .55));
        set("diagram-scale", (.82 + .18 * v).toFixed(4));
        set("diagram-opacity", (.45 + .55 * v).toFixed(4));
      }
      if (quote && quoteRect) {
        const v = ease((viewport - quoteRect.top) / (viewport + quoteRect.height * .5));
        set("quote-drift", (-50 + 100 * v).toFixed(1) + "px");
      }
    };
    const onScroll = () => {
      if (!ticking) {
        ticking = true;
        raf = window.requestAnimationFrame(update);
      }
    };
    if (!motion.matches) {
      window.addEventListener("scroll", onScroll, {
        passive: true
      });
      window.addEventListener("resize", onScroll, {
        passive: true
      });
      window.addEventListener("orientationchange", onScroll);
      onScroll();
    } else {
      // Static, legible end state for users who prefer reduced motion.
      ["clip-top", "clip-right", "clip-bottom", "clip-left"].forEach(k => set(k, "0%"));
      set("journey", 0);
      set("fly", 0);
      set("film-opacity", 0);
      set("hero-opacity", 1);
      set("hero-lift", 0);
      set("heart-opacity", 1);
      set("photo-opacity", 1);
      set("film-caption", 0);
      set("candidate-clip", "0%");
      set("candidate-scale", 1.02);
      set("candidate-shift", "0px");
      set("diagram-scale", 1);
      set("diagram-opacity", 1);
    }
    return () => {
      window.removeEventListener("scroll", onScroll);
      window.removeEventListener("resize", onScroll);
      window.removeEventListener("orientationchange", onScroll);
      window.cancelAnimationFrame(raf);
    };
  }, []);
}
export const Premium = () => {
  const [intro, setIntro] = useState(true);
  const [active, setActive] = useState(0);
  const [modal, setModal] = useState(false);
  const [scroll, setScroll] = useState(0);
  const [tilt, setTilt] = useState({
    x: 0,
    y: 0
  });
  const [openMethod, setOpenMethod] = useState(false);
  useReveal();
  useCinematicScroll();
  useEffect(() => {
    // A human reading the compatibility section is a meaningful engagement.
    // No reminder on a page preview, initial load, demo or photo request.
    if (pair.demo || !pair.engagement_path) return;
    const element = document.getElementById("sx-data");
    if (!element || !("IntersectionObserver" in window)) return;
    let recorded = false;
    const observer = new IntersectionObserver(entries => {
      if (recorded || !entries.some(e => e.isIntersecting)) return;
      recorded = true;
      observer.disconnect();
      fetch(pair.engagement_path!, {
        method: "POST",
        credentials: "same-origin",
        keepalive: true,
      }).catch(() => {});
    }, { threshold: 0.12, rootMargin: "0px 0px -18% 0px" });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  useEffect(() => {
    const t = setTimeout(() => setIntro(false), 1700);
    return () => clearTimeout(t);
  }, []);
  useEffect(() => {
    const onScroll = () => setScroll(window.scrollY > 90 ? 100 : 0);
    window.addEventListener("scroll", onScroll, {
      passive: true
    });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);
  const jump = (id: string) => document.getElementById(id)?.scrollIntoView({
    behavior: "smooth"
  });
  return <div className="sx">
{intro && <div className="sx-intro" aria-label="Загрузка прототипа"><div className="sx-intro-index">01 — 04</div><span className="sx-intro-word">совпали.</span><div className="sx-intro-rule"><i /></div><span className="sx-intro-note">ИСТОРИЯ ВОЗМОЖНОЙ ВСТРЕЧИ</span></div>}
<div className="sx-grain" aria-hidden="true" />
<header className={"sx-nav " + (scroll > 90 ? "sx-nav-fixed" : "")}><Mark /><div className="sx-nav-mid"><span className="sx-nav-issue">СЕРИЯ 001</span><span className="sx-nav-slash">/</span><span>КОНТАКТЫ, КОТОРЫЕ ЗНАЧАТ БОЛЬШЕ</span></div><button className="sx-nav-btn" onClick={() => jump("sx-start")}>К ЗНАКОМСТВУ <ArrowUpRight size={15} /></button><div className="sx-page-meter" aria-hidden="true"><i /></div></header>
<main>
<div className="sx-journey">
<section className="sx-hero" id="sx-top"><div className="sx-hero-grid" aria-hidden="true" /><div className="sx-hero-glow" aria-hidden="true" /><div className="sx-hero-lside"><div className="sx-label"><i className="sx-label-dot" /> АЛГОРИТМ ВСТРЕЧ · ДЕМО</div><h1 className="sx-hero-title"><span>НЕ</span><span>ПРОСТО</span><em>СОВПАЛИ.</em></h1><p className="sx-hero-copy">Два незнакомых человека. <br />Несколько важных общих вещей. <br />И шанс узнать друг друга по-настоящему.</p><div className="sx-hero-actions"><button onClick={() => jump("sx-match")} className="sx-primary">ПОЧЕМУ ВЫ ПОДХОДИТЕ <ArrowUpRight size={18} /></button><button onClick={() => jump("sx-story")} className="sx-scroll"><span>ЛИСТАЙ ВНИЗ</span><ArrowDown size={16} /></button></div></div>
<div className="sx-hero-art" style={{
            "--sx-pointer-a-x": -tilt.x * 15 + "px",
            "--sx-pointer-a-y": -tilt.y * 12 + "px",
            "--sx-pointer-b-x": tilt.x * 12 + "px",
            "--sx-pointer-b-y": tilt.y * 10 + "px"
          } as React.CSSProperties} onPointerMove={e => {
            if (e.pointerType === "mouse" && window.matchMedia("(pointer:fine)").matches) {
              const r = e.currentTarget.getBoundingClientRect();
              setTilt({
                x: (e.clientX - r.left - r.width / 2) / r.width,
                y: (e.clientY - r.top - r.height / 2) / r.height
              });
            }
          }} onPointerLeave={() => setTilt({
            x: 0,
            y: 0
          })}>
<div className="sx-photo sx-photo-a"><Portrait src={man} name={pair.viewer.name} loading="eager"/><span className="sx-photo-tag">01 <b>ВЫ</b></span></div>
<div className="sx-photo sx-photo-b"><Portrait src={woman} name={pair.candidate.name} loading="eager"/><span className="sx-photo-tag">02 <b>ПАРА</b></span></div>
<div className="sx-center-heart"><BigHeart /></div><svg className="sx-hero-arc" viewBox="0 0 700 700" fill="none" aria-hidden="true"><path d="M59 330C161 54 483 81 634 294" stroke="#F6B9B1" strokeOpacity=".65" strokeWidth=".9" strokeDasharray="3 9" /><path d="M70 420C144 661 475 702 617 483" stroke="#F6B9B1" strokeOpacity=".45" strokeWidth=".9" strokeDasharray="3 11" /></svg>
<div className="sx-art-glint" aria-hidden="true" /><div className="sx-hero-index">TWO PEOPLE <span>/</span> ONE POSSIBILITY</div>
</div>
<div className="sx-hero-bottom"><span>© 2026 СОВПАЛИ</span><span>СМОТРИ ГЛУБЖЕ, ЧЕМ ФОТО</span><span>01 / 04</span></div>
<div className="sx-film" aria-hidden="true">
<Portrait src={woman} name={pair.candidate.name} loading="eager"/>
<div className="sx-film-shade" />
<div className="sx-film-title"><span>{pair.same_city ? "ОДИН ГОРОД. ДВА ЧЕЛОВЕКА." : "ДВА ЧЕЛОВЕКА. ОДНА ВОЗМОЖНОСТЬ."}</span><strong>А ВДРУГ<br /><em>ЭТО ОНА?</em></strong><small>СКРОЛЛ ОТКРЫВАЕТ ИСТОРИЮ</small></div>
<div className="sx-film-index"><span>02 / ПЕРВАЯ ИСКРА</span><span>СОВПАЛИ · 2026</span></div>
</div>
</section>
</div>
<div className="sx-marquee" aria-hidden="true"><div className="sx-marquee-track">НЕ СЛУЧАЙНЫЙ СВАЙП <b>✳</b> НАСТОЯЩИЕ ЦЕННОСТИ <b>✳</b> ПЕРВАЯ ИСКРА <b>✳</b> ВАЖНО КТО ПЕРЕД ТОБОЙ <b>✳</b> НЕ СЛУЧАЙНЫЙ СВАЙП <b>✳</b> НАСТОЯЩИЕ ЦЕННОСТИ <b>✳</b> ПЕРВАЯ ИСКРА <b>✳</b> ВАЖНО КТО ПЕРЕД ТОБОЙ <b>✳</b></div></div>
<section className="sx-story" id="sx-story"><div className="sx-section-meta"><span>АКТ 01 / ЗНАКОМСТВО</span><span>01 — 04</span></div><div className="sx-story-content"><div className="sx-story-aside"><div className="sx-side-symbol">✳</div><p>Всё начинается<br />с небольшого «а вдруг».</p></div><div className="sx-story-main"><RevealLine><h2>Среди тысяч <i>лиц</i></h2></RevealLine><RevealLine><h2>ты заметил одно.</h2></RevealLine><p data-reveal className="sx-story-description">Но что, если за первой симпатией уже есть что-то важное? Общая цель. Похожий взгляд на близость. Тема, с которой захочется начать разговор.</p><div data-reveal className="sx-story-sub"><span>01</span><div className="sx-story-line" /><span>НЕ ДЛЯ ТЕХ, КТО ИЩЕТ БЕСКОНЕЧНЫЙ СВАЙП</span></div></div></div></section>
<section className="sx-candidate" id="sx-match"><div className="sx-candidate-photo"><Portrait src={woman} name={pair.candidate.name}/><div className="sx-photo-film" /><div className="sx-candidate-huge">{pair.candidate.name.toUpperCase()}</div><div className="sx-candidate-portrait-index">#001 / ПЕРСОНА</div></div><div className="sx-candidate-info"><div className="sx-section-meta light"><span>АКТ 02 / ВАША ПАРА</span><span>02 — 04</span></div><div className="sx-profile-meta">{pair.candidate.name.toUpperCase()} / {pair.candidate.age??"—"} / {pair.candidate.city.toUpperCase()}</div><h2 data-reveal>Всё<br />начинается<br /><em>с разговора.</em></h2><p data-reveal>{pair.candidate.name} · {pair.candidate.city}. Цель знакомства: {pair.candidate.goal}. Главный приоритет: {pair.candidate.priority}. {pair.reasons[0]||"Посмотри, какие пересечения нашёл алгоритм."}</p><div className="sx-candidate-stats"><div><strong><AnimatedNumber value={pair.score} /><small>%</small></strong><span>ИНДЕКС<br />ПО МОДЕЛИ БОТА</span></div><div className="sx-stat-sep" /><div><strong>{String(pair.reasons.length).padStart(2,"0")}</strong><span>НАЙДЕННЫХ<br />ОРИЕНТИРА</span></div></div><button className="sx-link-button" onClick={() => jump("sx-data")}>РАССМОТРЕТЬ СОВПАДЕНИЕ <ArrowUpRight size={17} /></button><div className="sx-disclaimer-inline">* Рассчитано по актуальным данным анкет. Астрология и нумерология — развлекательные интерпретации.</div></div></section>
<section className="sx-data" id="sx-data"><div className="sx-section-meta"><span>АКТ 03 / ВНУТРИ СОВПАДЕНИЯ</span><span>03 — 04</span></div><div className="sx-data-heading"><h2 data-reveal>У притяжения<br />бывают <i>причины.</i></h2><p data-reveal>Мы не предсказываем любовь. Мы показываем, о чём вам может быть интересно поговорить.</p></div><div className="sx-data-workspace"><div className="sx-data-list"><div className="sx-data-list-head"><span>ПАРАМЕТР</span><span>ИНДЕКС</span></div>{factors.map((f, i) => <button key={f.n} className={"sx-factor " + (active === i ? "sx-factor-active" : "")} onClick={() => setActive(i)} aria-pressed={active === i}><div className="sx-factor-leading"><span>{f.n}</span><strong>{f.tag}</strong></div><div className="sx-factor-trailing"><b>{f.score}</b><ChevronRight size={18} /></div><div className="sx-factor-progress"><span style={{
                  width: f.score + "%"
                }} /></div></button>)}</div><div className="sx-viz"><Connection active={active} /><div className="sx-viz-bottom"><span>ЧЕТЫРЕ СЛОЯ</span><span>ОДНА ИСТОРИЯ</span></div></div><div className="sx-data-copy" key={active}><span className="sx-data-copy-num">{factors[active].n} / 04</span><h3>{factors[active].title}</h3><p>{factors[active].copy}</p><div className="sx-data-basis"><span>ОТКУДА ДАННЫЕ</span><div>{factors[active].basis}</div></div></div></div></section>

<section className="sx-match-details" id="sx-match-details">
<div className="sx-section-meta"><span>ПОДРОБНЫЙ РАЗБОР / ДАННЫЕ ДВУХ АНКЕТ</span><span>ОБНОВЛЯЕТСЯ ПРИ ИЗМЕНЕНИИ АНКЕТЫ</span></div>
<div className="sx-match-details-head"><h2 data-reveal>Почему <em>совпали?</em></h2><p>Именно эти причины возвращает алгоритм бота для вашей пары.</p></div>
<div className="sx-reasons-list">{pair.reasons.map((r,i)=><div className="sx-reason-row" key={i}><span>{String(i+1).padStart(2,"0")}</span><p>{r}</p></div>)}</div>
<div className="sx-rich-grid">
{pair.astro&&<article className="sx-rich-panel"><span>03 / АСТРОЛОГИЯ</span><h3>Астрологический профиль</h3><p>{pair.astro}</p></article>}
{pair.numerology&&<article className="sx-rich-panel"><span>04 / НУМЕРОЛОГИЯ</span><h3>Числа и ритмы пары</h3><p>{pair.numerology}</p></article>}
</div>
</section>
<section className="sx-quote"><div className="sx-quote-aura" aria-hidden="true" /><div className="sx-section-meta"><span>ПАУЗА / ПЕРЕД ПЕРВЫМ ШАГОМ</span><span>•••</span></div><div className="sx-quote-content" data-reveal><span className="sx-star">✦</span><h2>Ни один алгоритм<br />не заменит <em>искру.</em><br />Но может помочь<br />её заметить.</h2><div className="sx-quote-rule" /><p>Главное начинается не на экране. Главное начинается между людьми.</p></div></section>
<section className="sx-start" id="sx-start"><div className="sx-section-meta light"><span>АКТ 04 / ПЕРВЫЙ ШАГ</span><span>04 — 04</span></div><div className="sx-start-grid"><div><span className="sx-kicker"><i /> КОГДА ПОЧУВСТВУЕШЬ, ЧТО ГОТОВ</span><h2 data-reveal>Остался<br /><em>один шаг.</em></h2><p data-reveal>Не обещаем судьбу. Помогаем начать разговор с человеком, чья анкета тебе откликнулась.</p><div className="sx-start-steps"><div><span>01</span>Ты проявляешь интерес</div><div><span>02</span>Вторая сторона решает, ответить ли взаимностью</div><div><span>03</span>Контакт открывается только при согласии</div></div></div><div className="sx-paycard"><div className="sx-paycard-top"><span>ЗНАКОМСТВО / 001</span><LockKeyhole size={18} strokeWidth={1.3} /></div><div className="sx-paycard-photo"><Portrait src={woman} name={pair.candidate.name}/><div>{pair.candidate.name}{personAge(pair.candidate)} <small>{pair.candidate.city.toUpperCase()}</small></div></div><div className="sx-paycard-body"><div><span>ПЕРВЫЙ ШАГ</span><strong>{pair.price} ₽</strong></div><p>Один запрос на взаимное знакомство.<br />Контакт не раскрывается автоматически.</p><button onClick={() => pair.checkout_path ? window.location.assign(pair.checkout_path) : setModal(true)}>ПРОДОЛЖИТЬ <ArrowUpRight size={18} /></button><div className="sx-paycard-trust"><ShieldCheck size={14} /> СБП ПОКА НЕ ПОДКЛЮЧЕНА · БЕЗ СПИСАНИЯ</div></div></div></div></section>
</main><footer className="sx-footer"><Mark /><span>ЗНАКОМСТВА НАЧИНАЮТСЯ С ЛЮДЕЙ</span><span>© СОВПАЛИ 2026 · 18+</span></footer>
{modal && <div className="sx-modal-back" role="presentation" onClick={() => setModal(false)}><div className="sx-modal" role="dialog" aria-modal="true" aria-labelledby="sx-dialog-title" onClick={e => e.stopPropagation()}><button className="sx-modal-close" onClick={() => setModal(false)} aria-label="Закрыть"><X size={22} /></button><span className="sx-modal-flag"><LockKeyhole size={15} /> ОПЛАТА ВРЕМЕННО НЕДОСТУПНА</span><h3 id="sx-dialog-title">Первый шаг<br /><em>без спешки.</em></h3><p>СБП пока не подключена. Сейчас деньги не списываются и запрос на знакомство не отправляется.</p><div className="sx-modal-mini"><Check size={18} /> В рабочей версии контакт появится только после взаимного согласия.</div><button className="sx-modal-action" onClick={() => setModal(false)}>ВЕРНУТЬСЯ К ПАРЕ <ArrowRight size={17} /></button></div></div>}
</div>;
};