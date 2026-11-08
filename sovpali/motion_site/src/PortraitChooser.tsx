import React,{useEffect,useRef,useState} from 'react';
import {Camera,ImagePlus,UserRound,Check,ShieldCheck,RefreshCw} from 'lucide-react';
import {api} from './Cabinet';
import {telegram} from './telegram';
import './PortraitChooser.css';

async function compressedJpeg(file:File):Promise<Blob>{
 if(!file.type.startsWith('image/') && !/\.(heic|heif|jpg|jpeg|png|webp)$/i.test(file.name))throw new Error('Выбери файл с фотографией.');
 if(file.size>25*1024*1024)throw new Error('Файл слишком большой. Выбери фотографию до 25 МБ.');
 const src=URL.createObjectURL(file);
 try{
  const image=new Image();
  await new Promise<void>((resolve,reject)=>{image.onload=()=>resolve();image.onerror=()=>reject(new Error('Не удалось открыть фото. Выбери JPG или PNG.'));image.src=src});
  if(image.naturalWidth<80||image.naturalHeight<80)throw new Error('Фотография слишком маленькая.');
  const scale=Math.min(1,1280/Math.max(image.naturalWidth,image.naturalHeight));
  const canvas=document.createElement('canvas');
  canvas.width=Math.max(1,Math.round(image.naturalWidth*scale));
  canvas.height=Math.max(1,Math.round(image.naturalHeight*scale));
  const ctx=canvas.getContext('2d');
  if(!ctx)throw new Error('Не получилось обработать фото.');
  ctx.fillStyle='#ffffff';ctx.fillRect(0,0,canvas.width,canvas.height);
  ctx.drawImage(image,0,0,canvas.width,canvas.height);
  const jpg=await new Promise<Blob|null>(resolve=>canvas.toBlob(resolve,'image/jpeg',0.83));
  if(!jpg||jpg.size>8*1024*1024)throw new Error('Попробуй другое фото, это слишком большое.');
  return jpg;
 }finally{URL.revokeObjectURL(src)}
}

export default function PortraitChooser({mode,choice='',onChoose=()=>{},onSaved=()=>{},currentPhoto}:{
 mode:'onboarding'|'profile';choice?:string;onChoose?:(choice:string)=>void;
 onSaved?:()=>void;currentPhoto?:string|null
}){
 const [tgPhoto,setTgPhoto]=useState('');
 const [localPhoto,setLocalPhoto]=useState('');
 const [loading,setLoading]=useState(true);
 const [busy,setBusy]=useState(false);
 const [error,setError]=useState('');
 const fileRef=useRef<HTMLInputElement>(null);
 const currentChoice=useRef(choice);currentChoice.current=choice;
 useEffect(()=>{
  let cancel=false;let preview='';
  async function find(){
   try{
    const res=await fetch('/s/app/api/photo/telegram-preview',{
     method:'POST',credentials:'same-origin',
     headers:{'X-Telegram-Init-Data':telegram()?.initData||''},
     signal:AbortSignal.timeout(12000)
    });
    if(!res.ok)return;
    if(!(res.headers.get('content-type')||'').startsWith('image/'))return;
    const blob=await res.blob();
    if(!blob.size||cancel)return;
    preview=URL.createObjectURL(blob);
    setTgPhoto(preview);
    if(mode==='onboarding'&&!currentChoice.current)onChoose('telegram');
   }catch{/* Telegram can have no public avatar or the network can be offline. */}
   finally{if(!cancel)setLoading(false)}
  }
  find();
  return()=>{cancel=true;if(preview)URL.revokeObjectURL(preview)};
 },[mode]);
 useEffect(()=>()=>{if(localPhoto)URL.revokeObjectURL(localPhoto)},[localPhoto]);

 const chooseTelegram=async()=>{
  if(!tgPhoto||busy)return;
  setError('');
  if(mode==='onboarding'){onChoose('telegram');return}
  setBusy(true);
  try{await api('/s/app/api/photo/choose',{choice:'telegram'});onSaved()}
  catch(e){setError((e as Error).message)}
  finally{setBusy(false)}
 };
 const chooseSkip=async()=>{
  if(busy)return;
  setError('');
  if(mode==='onboarding'){onChoose('skip');return}
  setBusy(true);
  try{await api('/s/app/api/photo/choose',{choice:'skip'});onSaved()}
  catch(e){setError((e as Error).message)}
  finally{setBusy(false)}
 };
 const upload=async(file?:File)=>{
  if(!file||busy)return;
  setBusy(true);setError('');
  try{
   const jpeg=await compressedJpeg(file);
   const form=new FormData();form.append('photo',jpeg,'portrait.jpg');
   const res=await fetch('/s/app/api/photo/upload',{
    method:'POST',credentials:'same-origin',
    headers:{'X-Telegram-Init-Data':telegram()?.initData||''},
    body:form,signal:AbortSignal.timeout(30000)
   });
   const result=await res.json().catch(()=>null);
   if(!res.ok||!result?.saved)throw new Error(result?.message||'Не удалось загрузить фото.');
   const url=URL.createObjectURL(jpeg);
   setLocalPhoto(url);
   if(mode==='onboarding')onChoose('local');
   else onSaved();
  }catch(e){setError((e as Error).message)}
  finally{setBusy(false);if(fileRef.current)fileRef.current.value=''}
 };
 const selected=mode==='profile'?(currentPhoto?'current':'skip'):choice;
 const preview=selected==='local'&&localPhoto?localPhoto:selected==='telegram'&&tgPhoto?tgPhoto:mode==='profile'?currentPhoto:tgPhoto;
 return <section className="portrait-chooser" aria-label="Фото анкеты">
  <div className="portrait-preview">{preview?<img src={preview} alt="Фото для анкеты"/>:<div className="portrait-empty"><UserRound size={42}/><span>{loading?'Проверяем фотографию Telegram…':'Пока без фотографии'}</span></div>}</div>
  <p className="portrait-caption">{mode==='onboarding'
    ?'Если в Telegram есть аватар, мы предложим использовать его. Можно выбрать другое фото или пропустить шаг.'
    :'Твоё фото в анкете. Можешь использовать аватар Telegram, загрузить новое или удалить.'}</p>
  <div className="portrait-actions">
   {tgPhoto&&<button className={'portrait-option '+(selected==='telegram'?'active':'')} onClick={chooseTelegram} disabled={busy} type="button"><Camera size={19}/><span>Фото из Telegram</span>{selected==='telegram'&&<Check size={17}/>}</button>}
   <button className={'portrait-option '+(selected==='local'?'active':'')} onClick={()=>fileRef.current?.click()} disabled={busy} type="button"><ImagePlus size={19}/><span>{busy?'Загружаем…':'Выбрать своё фото'}</span>{selected==='local'&&<Check size={17}/>}</button>
   <button className={'portrait-option skip '+(selected==='skip'?'active':'')} onClick={chooseSkip} disabled={busy} type="button"><span>{mode==='onboarding'?'Пропустить этот шаг':'Удалить фото'}</span>{selected==='skip'&&<Check size={17}/>}</button>
  </div>
  <input ref={fileRef} type="file" accept="image/*,.heic,.heif" onChange={e=>upload(e.target.files?.[0])} aria-label="Выбрать фотографию" hidden/>
  {error&&<p className="portrait-error" role="alert">{error}</p>}
  <small className="portrait-trust"><ShieldCheck size={14}/> Фотография не обязательна. Доступна только в анкете и разборах подходящих людей. Метаданные изображения удаляются.</small>
 </section>;
}
