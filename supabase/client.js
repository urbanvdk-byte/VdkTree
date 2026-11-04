// VdkTree v0.3.0: Supabase is optional until public credentials are configured.
const cfg=window.VDK_SUPABASE||{};
if(cfg.url&&cfg.anonKey){
  const {createClient}=await import('https://esm.sh/@supabase/supabase-js@2');
  const sb=createClient(cfg.url,cfg.anonKey);
  const app=window.VdkApp;
  const notice=document.querySelector('.notice');
  notice.textContent='Общая карта: новые деревья появляются после проверки модератором. Фото пока недоступны.';
  const login=document.createElement('button');login.textContent='Войти';login.style.cssText='position:absolute;z-index:1000;right:12px;bottom:95px;border:0;border-radius:20px;padding:11px 18px;background:white;box-shadow:0 2px 9px #0003';document.body.append(login);
  let session=null,remote=[];
  async function refreshAuth(){const {data}=await sb.auth.getSession();session=data.session;login.textContent=session?'Выйти':'Войти по email'}
  login.onclick=async()=>{if(session){await sb.auth.signOut();await refreshAuth();return}const email=prompt('Email для входа (ссылка придёт на почту):');if(!email)return;const {error}=await sb.auth.signInWithOtp({email,emailRedirectTo:location.origin+location.pathname});alert(error?'Ошибка: '+error.message:'Проверьте почту и перейдите по ссылке для входа.')};
  sb.auth.onAuthStateChange(()=>setTimeout(refreshAuth,0));await refreshAuth();
  async function load(){const b=app.map.getBounds();const {data,error}=await sb.from('trees').select('id,lat,lon,species,condition,height,diameter,comment,photo').gte('lat',b.getSouth()).lte('lat',b.getNorth()).gte('lon',b.getWest()).lte('lon',b.getEast()).limit(5000);if(error){console.error(error);notice.textContent='Ошибка загрузки общей карты: '+error.message;return}remote=data||[];renderRemote()}
  function safe(s){return String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
  function renderRemote(){app.layer.clearLayers();for(const t of remote){const selected=document.getElementById('filter').value;if(selected!=='all'&&selected!==t.condition)continue;const marker=L.circleMarker([t.lat,t.lon],{radius:9,color:'white',weight:2,fillColor:({healthy:'#26924b',damaged:'#e89924',dead:'#ce4545'})[t.condition],fillOpacity:1}).addTo(app.layer);const div=document.createElement('div');div.innerHTML='<b>'+safe(t.species)+'</b><p>'+safe(({healthy:'Здоровое',damaged:'Повреждено',dead:'Погибло'})[t.condition])+'</p>'+(t.comment?'<p>'+safe(t.comment)+'</p>':'');marker.bindPopup(div)}}
  app.map.on('moveend',load);document.getElementById('filter').addEventListener('change',renderRemote);
  const form=document.getElementById('form');form.onsubmit=async e=>{e.preventDefault();const err=document.getElementById('error');err.textContent='';if(!session){err.textContent='Сначала войдите по email';return}const f=form.elements;const lat=Number(f.lat.value),lon=Number(f.lon.value);if(!(lat>=42&&lat<=44&&lon>=130&&lon<=134)){err.textContent='Координаты за пределами региона';return}if(f.photo.files.length){err.textContent='Фото в общей базе появятся на следующем этапе. Уберите файл.';return}const record={lat,lon,species:f.species.value.trim(),condition:f.condition.value,height:f.height.value?Number(f.height.value):null,diameter:f.diameter.value?Number(f.diameter.value):null,comment:f.comment.value.trim(),status:'pending',author_id:session.user.id};const {error}=await sb.from('trees').insert(record);if(error){err.textContent='Ошибка: '+error.message;return}document.getElementById('dialog').close();alert('Дерево отправлено на модерацию. После одобрения оно появится на карте.')};
  await load();
}
