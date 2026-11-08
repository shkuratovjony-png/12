// Native capabilities are optional: the same report still works in a browser.
export const telegram = () => (window as any).Telegram?.WebApp;
export const isMiniApp = () => Boolean(telegram()?.initData);
export function haptic() {
  const tg=telegram();
  if(isMiniApp() && tg.isVersionAtLeast('6.1')) tg.HapticFeedback.selectionChanged();
}
export function setupTelegram() {
  const tg=telegram();
  if(!isMiniApp()) return;
  document.documentElement.classList.add('tg-miniapp');
  tg.ready(); tg.expand();
  if(tg.isVersionAtLeast('6.1')) { tg.setHeaderColor('#171319'); tg.setBackgroundColor('#171319'); }
  if(tg.isVersionAtLeast('7.10')) tg.setBottomBarColor('#171319');
  const sync=()=>{
    const style=document.documentElement.style;
    style.setProperty('--mini-top', `${(tg.safeAreaInset?.top||0)+(tg.contentSafeAreaInset?.top||0)}px`);
    style.setProperty('--mini-bottom', `${Math.max(tg.safeAreaInset?.bottom||0,tg.contentSafeAreaInset?.bottom||0)}px`);
  };
  ['safeAreaChanged','contentSafeAreaChanged','viewportChanged'].forEach(event=>tg.onEvent(event,sync));
  sync();
}
export function fullscreen() {
  const tg=telegram();
  if(isMiniApp() && tg.isVersionAtLeast('8.0')) { haptic(); tg.isFullscreen?tg.exitFullscreen():tg.requestFullscreen(); }
}
