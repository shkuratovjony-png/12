import React, { useEffect, useRef, useState } from "react";
import { ArrowDown, ArrowUpRight, ArrowRight, X, Heart, ShieldCheck, LockKeyhole, MoveUpRight, Info, Check, ChevronRight, Sparkles } from "lucide-react";
import "./Experience.css";
const woman = "https://images.unsplash.com/photo-1534528741775-53994a69daeb?w=1400&q=85&fit=crop&crop=faces";
const man = "https://images.unsplash.com/photo-1500648767791-00dcc994a43e?w=1100&q=85&fit=crop&crop=faces";
const factors = [{
  n: "01",
  tag: "Намерения",
  title: "Вы смотрите в одну сторону.",
  score: 96,
  copy: "Оба выбрали серьёзные отношения. Это не обещание совместного будущего — но отличная точка, с которой может начаться разговор.",
  basis: "Совпадение ответов о цели знакомства"
}, {
  n: "02",
  tag: "Ценности",
  title: "Важное звучит одинаково.",
  score: 95,
  copy: "В анкетах вы назвали близкие жизненные приоритеты. Когда ориентиры схожи, у знакомства появляется содержательный первый вопрос.",
  basis: "Сопоставление выбранных приоритетов"
}, {
  n: "03",
  tag: "Астрология",
  title: "Разные характеры. Свой ритм.",
  score: 91,
  copy: "Символическая интерпретация дат рождения помогает придумать темы для разговора — воспринимай её как вдохновение, а не научный прогноз.",
  basis: "Развлекательная интерпретация по знакам"
}, {
  n: "04",
  tag: "Нумерология",
  title: "Любопытные пересечения.",
  score: 86,
  copy: "Нумерологическая история пары — ещё один повод узнать друг друга. Настоящую близость определяют поступки и общение.",
  basis: "Развлекательная интерпретация дат рождения"
}];
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
  useEffect(() => {
    const t = setTimeout(() => setIntro(false), 1700);
    return () => clearTimeout(t);
  }, []);
  useEffect(() => {
    const onScroll = () => setScroll(window.scrollY);
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
<header className={"sx-nav " + (scroll > 90 ? "sx-nav-fixed" : "")}><Mark /><div className="sx-nav-mid"><span className="sx-nav-issue">СЕРИЯ 001</span><span className="sx-nav-slash">/</span><span>КОНТАКТЫ, КОТОРЫЕ ЗНАЧАТ БОЛЬШЕ</span></div><button className="sx-nav-btn" onClick={() => jump("sx-start")}>К ЗНАКОМСТВУ <ArrowUpRight size={15} /></button></header>
<main>
<section className="sx-hero" id="sx-top"><div className="sx-hero-grid" aria-hidden="true" /><div className="sx-hero-glow" aria-hidden="true" /><div className="sx-hero-lside"><div className="sx-label"><i className="sx-label-dot" /> АЛГОРИТМ ВСТРЕЧ · ДЕМО</div><h1 className="sx-hero-title"><span>НЕ</span><span>ПРОСТО</span><em>СОВПАЛИ.</em></h1><p className="sx-hero-copy">Два незнакомых человека. <br />Несколько важных общих вещей. <br />И шанс узнать друг друга по-настоящему.</p><div className="sx-hero-actions"><button onClick={() => jump("sx-match")} className="sx-primary">ПОЧЕМУ ВЫ ПОДХОДИТЕ <ArrowUpRight size={18} /></button><button onClick={() => jump("sx-story")} className="sx-scroll"><span>ЛИСТАЙ ВНИЗ</span><ArrowDown size={16} /></button></div></div>
<div className="sx-hero-art" onPointerMove={e => {
          if (e.pointerType === "mouse") {
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
<div className="sx-photo sx-photo-a" style={{
            transform: "translate3d(" + -tilt.x * 15 + "px," + -tilt.y * 12 + "px,0) rotate(-6deg)"
          }}><img src={man} alt="Демонстрационный портрет мужчины" /><span className="sx-photo-tag">01 <b>ОН</b></span></div>
<div className="sx-photo sx-photo-b" style={{
            transform: "translate3d(" + tilt.x * 12 + "px," + tilt.y * 10 + "px,0) rotate(5deg)"
          }}><img src={woman} alt="Демонстрационный портрет женщины" /><span className="sx-photo-tag">02 <b>ОНА</b></span></div>
<div className="sx-center-heart"><BigHeart /></div><svg className="sx-hero-arc" viewBox="0 0 700 700" fill="none" aria-hidden="true"><path d="M59 330C161 54 483 81 634 294" stroke="#F6B9B1" strokeOpacity=".65" strokeWidth=".9" strokeDasharray="3 9" /><path d="M70 420C144 661 475 702 617 483" stroke="#F6B9B1" strokeOpacity=".45" strokeWidth=".9" strokeDasharray="3 11" /></svg>
<div className="sx-art-glint" aria-hidden="true" /><div className="sx-hero-index">TWO PEOPLE <span>/</span> ONE POSSIBILITY</div>
</div>
<div className="sx-hero-bottom"><span>© 2026 СОВПАЛИ</span><span>СМОТРИ ГЛУБЖЕ, ЧЕМ ФОТО</span><span>01 / 04</span></div>
</section>
<div className="sx-marquee" aria-hidden="true"><div className="sx-marquee-track">НЕ СЛУЧАЙНЫЙ СВАЙП <b>✳</b> НАСТОЯЩИЕ ЦЕННОСТИ <b>✳</b> ПЕРВАЯ ИСКРА <b>✳</b> ВАЖНО КТО ПЕРЕД ТОБОЙ <b>✳</b> НЕ СЛУЧАЙНЫЙ СВАЙП <b>✳</b> НАСТОЯЩИЕ ЦЕННОСТИ <b>✳</b> ПЕРВАЯ ИСКРА <b>✳</b> ВАЖНО КТО ПЕРЕД ТОБОЙ <b>✳</b></div></div>
<section className="sx-story" id="sx-story"><div className="sx-section-meta"><span>АКТ 01 / ЗНАКОМСТВО</span><span>01 — 04</span></div><div className="sx-story-content"><div className="sx-story-aside"><div className="sx-side-symbol">✳</div><p>Всё начинается<br />с небольшого «а вдруг».</p></div><div className="sx-story-main"><RevealLine><h2>Среди тысяч <i>лиц</i></h2></RevealLine><RevealLine><h2>ты заметил одно.</h2></RevealLine><p data-reveal className="sx-story-description">Но что, если за первой симпатией уже есть что-то важное? Общая цель. Похожий взгляд на близость. Тема, с которой захочется начать разговор.</p><div data-reveal className="sx-story-sub"><span>01</span><div className="sx-story-line" /><span>НЕ ДЛЯ ТЕХ, КТО ИЩЕТ БЕСКОНЕЧНЫЙ СВАЙП</span></div></div></div></section>
<section className="sx-candidate" id="sx-match"><div className="sx-candidate-photo"><img src={woman} alt="Анна, демонстрационная анкета" /><div className="sx-photo-film" /><div className="sx-candidate-huge">АННА</div><div className="sx-candidate-portrait-index">#001 / ПЕРСОНА</div></div><div className="sx-candidate-info"><div className="sx-section-meta light"><span>АКТ 02 / ВАША ПАРА</span><span>02 — 04</span></div><div className="sx-profile-meta">АННА / 33 ГОДА / ВЛАДИВОСТОК</div><h2 data-reveal>Похожий<br />взгляд на<br /><em>главное.</em></h2><p data-reveal>Анна ищет серьёзные отношения. Для неё важны ценности и возможность встретиться в реальной жизни. В вашей анкете нашлись близкие ответы.</p><div className="sx-candidate-stats"><div><strong><AnimatedNumber value={92} /><small>%</small></strong><span>ДЕМО-ИНДЕКС<br />СОВПАДЕНИЯ</span></div><div className="sx-stat-sep" /><div><strong>03</strong><span>ОБЩИХ<br />ОРИЕНТИРА</span></div></div><button className="sx-link-button" onClick={() => jump("sx-data")}>РАССМОТРЕТЬ СОВПАДЕНИЕ <ArrowUpRight size={17} /></button><div className="sx-disclaimer-inline">* Демонстрационные данные. Астрологические и нумерологические показатели — развлекательная интерпретация.</div></div></section>
<section className="sx-data" id="sx-data"><div className="sx-section-meta"><span>АКТ 03 / ВНУТРИ СОВПАДЕНИЯ</span><span>03 — 04</span></div><div className="sx-data-heading"><h2 data-reveal>У притяжения<br />бывают <i>причины.</i></h2><p data-reveal>Мы не предсказываем любовь. Мы показываем, о чём вам может быть интересно поговорить.</p></div><div className="sx-data-workspace"><div className="sx-data-list"><div className="sx-data-list-head"><span>ПАРАМЕТР</span><span>ИНДЕКС</span></div>{factors.map((f, i) => <button key={f.n} className={"sx-factor " + (active === i ? "sx-factor-active" : "")} onClick={() => setActive(i)} aria-pressed={active === i}><div className="sx-factor-leading"><span>{f.n}</span><strong>{f.tag}</strong></div><div className="sx-factor-trailing"><b>{f.score}</b><ChevronRight size={18} /></div><div className="sx-factor-progress"><span style={{
                  width: f.score + "%"
                }} /></div></button>)}</div><div className="sx-viz"><Connection active={active} /><div className="sx-viz-bottom"><span>ЧЕТЫРЕ СЛОЯ</span><span>ОДНА ИСТОРИЯ</span></div></div><div className="sx-data-copy" key={active}><span className="sx-data-copy-num">{factors[active].n} / 04</span><h3>{factors[active].title}</h3><p>{factors[active].copy}</p><div className="sx-data-basis"><span>ОТКУДА ДАННЫЕ</span><div>{factors[active].basis}</div></div></div></div></section>
<section className="sx-quote"><div className="sx-quote-aura" aria-hidden="true" /><div className="sx-section-meta"><span>ПАУЗА / ПЕРЕД ПЕРВЫМ ШАГОМ</span><span>•••</span></div><div className="sx-quote-content" data-reveal><span className="sx-star">✦</span><h2>Ни один алгоритм<br />не заменит <em>искру.</em><br />Но может помочь<br />её заметить.</h2><div className="sx-quote-rule" /><p>Главное начинается не на экране. Главное начинается между людьми.</p></div></section>
<section className="sx-start" id="sx-start"><div className="sx-section-meta light"><span>АКТ 04 / ПЕРВЫЙ ШАГ</span><span>04 — 04</span></div><div className="sx-start-grid"><div><span className="sx-kicker"><i /> КОГДА ПОЧУВСТВУЕШЬ, ЧТО ГОТОВ</span><h2 data-reveal>Остался<br /><em>один шаг.</em></h2><p data-reveal>Не обещаем судьбу. Поможем начать разговор с человеком, чьи ответы отозвались в твоей анкете.</p><div className="sx-start-steps"><div><span>01</span>Ты проявляешь интерес</div><div><span>02</span>Анна решает, ответить ли взаимностью</div><div><span>03</span>Контакт открывается только при согласии</div></div></div><div className="sx-paycard"><div className="sx-paycard-top"><span>ЗНАКОМСТВО / 001</span><LockKeyhole size={18} strokeWidth={1.3} /></div><div className="sx-paycard-photo"><img src={woman} alt="Анна — демонстрационная карточка" /><div>Анна, 33 <small>ВЛАДИВОСТОК</small></div></div><div className="sx-paycard-body"><div><span>ПЕРВЫЙ ШАГ</span><strong>100 ₽</strong></div><p>Один запрос на взаимное знакомство.<br />Контакт не раскрывается автоматически.</p><button onClick={() => setModal(true)}>ПРОДОЛЖИТЬ <ArrowUpRight size={18} /></button><div className="sx-paycard-trust"><ShieldCheck size={14} /> ДЕМО · ОПЛАТА ПОКА НЕ ПОДКЛЮЧЕНА</div></div></div></div></section>
</main><footer className="sx-footer"><Mark /><span>ЗНАКОМСТВА НАЧИНАЮТСЯ С ЛЮДЕЙ</span><span>© СОВПАЛИ 2026 · 18+</span></footer>
{modal && <div className="sx-modal-back" role="presentation" onClick={() => setModal(false)}><div className="sx-modal" role="dialog" aria-modal="true" aria-labelledby="sx-dialog-title" onClick={e => e.stopPropagation()}><button className="sx-modal-close" onClick={() => setModal(false)} aria-label="Закрыть"><X size={22} /></button><span className="sx-modal-flag"><LockKeyhole size={15} /> ДЕМОНСТРАЦИОННЫЙ ЭКРАН</span><h3 id="sx-dialog-title">Первый шаг<br /><em>без спешки.</em></h3><p>Это интерактивный дизайн-прототип. СБП пока не подключена: списания денег нет, запрос Анне не отправляется.</p><div className="sx-modal-mini"><Check size={18} /> В рабочей версии контакт появится только после взаимного согласия.</div><button className="sx-modal-action" onClick={() => setModal(false)}>ВЕРНУТЬСЯ К ПАРЕ <ArrowRight size={17} /></button></div></div>}
</div>;
};