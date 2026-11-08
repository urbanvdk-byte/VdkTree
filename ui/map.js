/* VdkTree v1.0.0: public map, mobile forms, shared BotHost inventory and notes. */
(() => {
  "use strict";
  const api = String(window.VDK_AUTH_API || "").replace(/\/$/, "");
  const el = id => document.getElementById(id);
  const map = L.map("map", {preferCanvas:true}).setView([43.1155,131.8855],13);
  map.attributionControl.setPrefix(false);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom:19,attribution:"© OpenStreetMap contributors"
  }).addTo(map);
  const layers=L.layerGroup().addTo(map),drawingLayer=L.layerGroup().addTo(map);
  const form=el("objectForm"),editor=el("editor"),detail=el("details");
  const names={tree:"Дерево",shrub:"Кустарник",lawn:"Газон",flowerbed:"Цветник",natural_community:"Природное сообщество"};
  const conditions={unknown:"Не знаю",looks_healthy:"Выглядит здоровым",damaged:"Повреждено",dry:"Засохшее"};
  const heights={unknown:"Не знаю",under_2m:"До 2 м","2_5m":"2–5 м","5_10m":"5–10 м",over_10m:"Более 10 м"};
  const damage={broken_branches:"Сломанные ветки",hollow:"Дупло",cracks:"Трещины",leaning:"Наклон",dry_crown:"Сухая крона",other:"Другое"};
  const areaColors={lawn:"#63ae72",flowerbed:"#b879b7",natural_community:"#528d69"};
  const esc=x=>String(x??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  const current=()=>window.VdkAuth?.getUser?.()||null;
  const staff=()=>["admin","moderator"].includes(current()?.role);
  const toast=s=>{el("toast").textContent=s||"";};
  const date=s=>s?new Date(s*1000).toLocaleDateString("ru-RU"):"—";
  const label=(k,v)=>v!==null&&v!==undefined&&v!==""?"<p><b>"+esc(k)+":</b> "+esc(v)+"</p>":"";
  const error=(where,message)=>{where.textContent=message;where.classList.add("error");};
  const clear=where=>{where.textContent="";where.classList.remove("error");};
  const safePhoto=p=>{
    const name=String(p||"").split("/").pop();
    return /^[a-f0-9]{32,40}\.(jpg|png|webp)$/.test(name)?api+"/photos/"+name:null;
  };
  let objects=[],editing=null,activeEditingObject=null,placing=false,drawing=false,areaVertices=[],areaGeometry=null;

  async function fetchJSON(path,options) {
    if(!api)throw Error("Не указан адрес BotHost");
    let res;
    try {
      res = options ? await window.VdkAuth.authorizedFetch(path,options)
        : await fetch(api+path,{cache:"no-store"});
    } catch (_) {throw Error("Сервер BotHost недоступен. Проверьте подключение.");}
    const body=await res.json().catch(()=>({}));
    if(!res.ok)throw Error(typeof body.detail==="string"?body.detail:"Ошибка "+res.status);
    return body;
  }
  const json=(method,payload)=>({method,headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)});
  function permitted() {
    if(current())return true;
    toast("Для добавления и замечаний нужно войти через MAX.");
    document.querySelector(".vdk-auth-btn")?.click();
    return false;
  }
  function visible(o,filter) {
    if(filter==="all")return true;
    if(filter==="area")return ["lawn","flowerbed","natural_community"].includes(o.object_type);
    if(filter==="notes")return !!o.needs_clarification;
    if(filter==="proposed"||filter==="confirmed")return o.confirmation_status===filter;
    return o.object_type===filter;
  }
  function render() {
    layers.clearLayers();
    const filter=el("filter").value;
    for(const o of objects) {
      if(!visible(o,filter))continue;
      if(o.geometry && ["lawn","flowerbed","natural_community"].includes(o.object_type)) {
        const c=areaColors[o.object_type]||"#64b477";
        L.geoJSON(o.geometry,{style:{color:c,fillColor:c,fillOpacity:.24,weight:3}})
          .on("click",()=>showCard(o.id)).addTo(layers);
        if(o.needs_clarification){
          const c=L.geoJSON(o.geometry).getBounds().getCenter();
          L.circleMarker(c,{radius:7,color:"#fff",weight:2,fillColor:"#e43d36",fillOpacity:1})
            .on("click",()=>showCard(o.id)).addTo(layers);
        }
      } else if(Number.isFinite(o.lat)&&Number.isFinite(o.lon)) {
        const type=o.object_type==="shrub"?"shrub":"tree";
        const state=o.confirmation_status==="confirmed"?"confirmed":"proposed";
        const red=o.needs_clarification?'<i class="vdk-alert"></i>':"";
        const icon=L.divIcon({className:"vdk-marker-shell",
          html:'<span class="vdk-marker '+type+" "+state+'">'+red+"</span>",
          iconSize:[30,30],iconAnchor:[15,15]});
        L.marker([o.lat,o.lon],{icon,title:(names[o.object_type]||"Растение")+": "+(o.species_common||"Вид неизвестен")})
          .on("click",()=>showCard(o.id)).addTo(layers);
      }
    }
  }
  async function reload(){
    try{
      const response=await fetchJSON("/api/v2/objects");
      objects=response.objects||[];
      render();
      const pending=objects.filter(x=>x.confirmation_status==="proposed").length;
      toast("Общая карта: "+objects.length+" объектов. Предложено: "+pending+".");
    }catch(e){objects=[];render();error(el("toast"),e.message);}
  }
  function roleControls(){
    el("addAreaButton").style.display=staff()?"block":"none";
    for(const opt of el("objectType").options)
      if(["lawn","flowerbed","natural_community"].includes(opt.value))opt.disabled=!staff();
  }
  window.addEventListener("vdktree:auth",()=>{roleControls();if(detail.open)detail.close();});

  function cancelDraw(){
    drawing=false;placing=false;activeEditingObject=null;areaVertices=[];areaGeometry=null;drawingLayer.clearLayers();
    el("drawControls").style.display="none";
  }
  function isArea(kind){return ["lawn","flowerbed","natural_community"].includes(kind);}
  function toggleKind(){
    const area=isArea(form.elements.object_type.value);
    el("pointInputs").hidden=area;el("areaInfo").hidden=!area;
    for(const input of el("pointInputs").querySelectorAll("input"))input.required=!area;
    if(area)el("areaInfo").textContent=areaGeometry?"Контур территории выбран":"Нарисуйте контур на карте";
  }
  function openEditor(point,obj){
    if(!permitted())return;
    const fromPlacing=placing;
    const selected=obj||(fromPlacing?activeEditingObject:null);
    placing=false;
    editing=selected?.id||null;
    activeEditingObject=selected;
    if(selected?.geometry)areaGeometry=selected.geometry;
    if(!fromPlacing)form.reset();
    clear(el("editor-status"));
    el("editor-title").textContent=editing?"Редактировать растение":"Новое растение";
    el("objectType").disabled=Boolean(editing);
    if(selected&&!fromPlacing){
      for(const field of ["object_type","lat","lon","species_common","approx_height_band",
        "approx_diameter_cm","visible_condition","observed_on","comment"]){
        if(form.elements[field]&&selected[field]!==null&&selected[field]!==undefined)
          form.elements[field].value=selected[field];
      }
      const checks=new Set(selected.visible_damage||[]);
      for(const control of form.querySelectorAll('input[name="damage"]'))
        control.checked=checks.has(control.value);
    }else if(!fromPlacing) {
      form.elements.object_type.value=areaGeometry?"lawn":"tree";
      form.elements.observed_on.value=new Date().toLocaleDateString("sv-SE");
    }
    if(!selected||fromPlacing){
      form.elements.lat.value=point.lat.toFixed(6);
      form.elements.lon.value=point.lng.toFixed(6);
    }
    toggleKind();
    if(!editor.open)editor.showModal();
  }
  el("objectType").onchange=toggleKind;
  el("addButton").onclick=()=>{cancelDraw();openEditor(map.getCenter());};
  el("choosePoint").onclick=()=>{
    if(isArea(form.elements.object_type.value))return;
    placing=true;editor.close();toast("Нажмите на карту, чтобы указать координаты растения.");
  };
  el("cancelEdit").onclick=()=>{editor.close();cancelDraw();};
  el("addAreaButton").onclick=()=>{
    if(!permitted()||!staff())return;
    cancelDraw();drawing=true;el("drawControls").style.display="block";
    toast("Нажмите на карте по углам территории; затем «Готово».");
  };
  el("cancelArea").onclick=()=>{cancelDraw();toast("");};
  el("finishArea").onclick=()=>{
    if(areaVertices.length<3){toast("Нужно не менее трёх точек.");return;}
    const ring=areaVertices.map(x=>x.slice());ring.push(ring[0].slice());
    areaGeometry={type:"Polygon",coordinates:[ring]};
    drawing=false;el("drawControls").style.display="none";
    openEditor(map.getCenter());
  };
  map.on("click",e=>{
    if(drawing){
      areaVertices.push([Number(e.latlng.lng.toFixed(6)),Number(e.latlng.lat.toFixed(6))]);
      drawingLayer.clearLayers();
      if(areaVertices.length>1)L.polyline(areaVertices.map(x=>[x[1],x[0]]),
        {color:"#18753e",weight:3}).addTo(drawingLayer);
      for(const v of areaVertices)L.circleMarker([v[1],v[0]],{
        radius:5,color:"#fff",weight:2,fillColor:"#18753e",fillOpacity:1
      }).addTo(drawingLayer);
      toast("Указано точек: "+areaVertices.length+". Нажмите «Готово» для завершения.");
    }else if(placing)openEditor(e.latlng);
  });
  el("locate").onclick=()=>map.locate({setView:true,maxZoom:17});
  map.on("locationerror",()=>toast("Геолокация недоступна. Разрешите доступ в браузере."));
  el("filter").onchange=render;

  function editable(o) {
    const u=current();if(!u)return false;
    if(u.role==="admin")return true;
    if(isArea(o.object_type))return u.role==="moderator"&&o.created_by===u.id;
    if(o.confirmation_status!=="proposed")return false;
    if(u.role==="moderator")return true;
    return u.id===o.created_by && Date.now()/1000<o.created_at+604800;
  }
  async function sendPhotos(id,files){
    const failed=[];
    for(const file of files){
      if(file.size>5*1024*1024||!["image/jpeg","image/png","image/webp"].includes(file.type)){
        failed.push("Недопустимое фото "+file.name);continue;
      }
      const body=new FormData();body.append("photo",file);
      try{await fetchJSON("/api/v2/objects/"+encodeURIComponent(id)+"/photos",{method:"POST",body});}
      catch(e){failed.push(file.name+": "+e.message);}
    }
    return failed;
  }
  form.onsubmit=async e=>{
    e.preventDefault();if(!permitted())return;
    const status=el("editor-status");clear(status);
    const f=form.elements,kind=f.object_type.value,area=isArea(kind);
    if(area&&!areaGeometry){error(status,"Сначала нарисуйте контур территории.");return;}
    if(area&&!staff()){error(status,"Площадь может добавить только модератор или администратор.");return;}
    const files=Array.from(f.photos.files||[]);
    if(files.length>8){error(status,"Не более 8 фотографий.");return;}
    const body={
      species_common:f.species_common.value.trim(),approx_height_band:f.approx_height_band.value,
      visible_condition:f.visible_condition.value,
      visible_damage:Array.from(form.querySelectorAll('input[name="damage"]:checked'),x=>x.value),
      comment:f.comment.value.trim()
    };
    if(f.approx_diameter_cm.value)body.approx_diameter_cm=Number(f.approx_diameter_cm.value);
    if(f.observed_on.value)body.observed_on=f.observed_on.value;
    if(area)body.geometry=areaGeometry;
    else{body.lat=Number(f.lat.value);body.lon=Number(f.lon.value);}
    if(!editing)body.object_type=kind;
    try{
      el("saveObject").disabled=true;status.textContent="Сохраняем…";
      const result=await fetchJSON(editing?"/api/v2/objects/"+encodeURIComponent(editing):"/api/v2/objects",
        json(editing?"PATCH":"POST",body));
      const failed=await sendPhotos(result.id,files);
      editor.close();cancelDraw();await reload();
      toast(failed.length?"Объект сохранён, но некоторые фото не загружены: "+failed.join("; "):
        editing?"Изменения сохранены.":"Объект добавлен и виден всем. Пока он не подтверждён.");
      await showCard(result.id);
    }catch(err){error(status,err.message);}
    finally{el("saveObject").disabled=false;}
  };

  async function showCard(id){
    try{
      const o=await fetchJSON("/api/v2/objects/"+encodeURIComponent(id));
      const photos=(o.photos||[]).map(safePhoto).filter(Boolean);
      const isPoly=isArea(o.object_type), notes=o.notes||[],u=current();
      const mainStatus=isPoly?"Площадной объект":
        o.confirmation_status==="confirmed"?"Произрастает":"Предложено";
      const target=el("card-content");
      target.innerHTML="<h2>"+esc(names[o.object_type]||"Объект")+" — "+esc(o.species_common||"вид не определён")+"</h2>"+
        '<span class="badge">'+esc(mainStatus)+"</span> "+
        (o.needs_clarification?'<span class="badge note-badge">🔴 Требует уточнения</span>':"")+
        label("Примерная высота",heights[o.approx_height_band])+
        label("Примерная толщина ствола",o.approx_diameter_cm?o.approx_diameter_cm+" см":"")+
        label("Дата наблюдения",o.observed_on?new Date(o.observed_on+"T00:00:00").toLocaleDateString("ru-RU"):"")+
        label("Внешнее состояние",conditions[o.visible_condition])+
        label("Повреждения",(o.visible_damage||[]).map(x=>damage[x]||x).join(", "))+label("Комментарий",o.comment)+
        '<p class="meta">Добавлено: '+esc(date(o.created_at))+
        " · Автор: участник "+esc(String(o.created_by||"").slice(0,6))+
        " · ID: "+esc(o.id.slice(0,8))+"</p>"+
        '<div id="cardPhotos"></div><div id="cardActions" class="dialog-actions"></div>'+
        "<h3>Замечания ("+notes.length+')</h3><div id="cardNotes"></div><div id="cardNewNote"></div>';
      for(const url of photos){
        const img=document.createElement("img");img.src=url;img.alt="Фотография растения";
        img.loading="lazy";target.querySelector("#cardPhotos").append(img);
      }
      const actions=target.querySelector("#cardActions");
      const btn=(text,cb,secondary)=>{
        const b=document.createElement("button");b.textContent=text;b.type="button";
        if(secondary)b.className="secondary";b.onclick=cb;actions.append(b);
      };
      if(editable(o))btn("✏️ Редактировать",()=>{
        detail.close();areaGeometry=o.geometry||null;
        openEditor({lat:o.lat??map.getCenter().lat,lng:o.lon??map.getCenter().lng},o);
      },true);
      if(staff()&&!isPoly&&o.confirmation_status==="proposed")
        btn("✅ Подтвердить",async()=>{
          if(!confirm("Подтвердить растение и его характеристики?"))return;
          try{
            await fetchJSON("/api/v2/objects/"+encodeURIComponent(id)+"/confirm",json("POST",{}));
            await reload();await showCard(id);
          }catch(e){error(el("detail-status"),e.message);}
        },false);
      const notesEl=target.querySelector("#cardNotes");
      if(!notes.length)notesEl.innerHTML='<p class="help">Замечаний пока нет.</p>';
      for(const n of notes){
        const box=document.createElement("div");box.className="note";
        box.innerHTML='<div class="meta">'+esc(date(n.created_at))+" — "+
          (n.status==="open"?"🔴 Открыто":"✅ Закрыто")+"</div><p>"+esc(n.message)+"</p>"+
          (n.resolution?label("Результат проверки",n.resolution):"");
        if(staff()&&n.status==="open"){
          const close=document.createElement("button");close.type="button";close.className="secondary";
          close.textContent="Закрыть замечание";close.onclick=async()=>{
            const reason=prompt("Результат проверки:");if(!reason)return;
            try{
              await fetchJSON("/api/v2/objects/"+encodeURIComponent(id)+"/notes/"+encodeURIComponent(n.id)+"/close",
                json("POST",{resolution:reason}));
              await reload();await showCard(id);
            }catch(e){error(el("detail-status"),e.message);}
          };box.append(close);
        }
        notesEl.append(box);
      }
      const add=target.querySelector("#cardNewNote");
      if(u){
        add.innerHTML='<h3>Требует уточнения?</h3><p class="help">Замечание не меняет данные дерева.</p>'+
          '<form id="newNote"><textarea name="message" maxlength="1500" minlength="3" rows="3" required '+
          'placeholder="Что изменилось?"></textarea><button type="submit">🔴 Отправить замечание</button></form>';
        add.querySelector("form").onsubmit=async event=>{
          event.preventDefault();
          const message=event.target.elements.message.value.trim();
          if(message.length<3){error(el("detail-status"),"Опишите замечание подробнее.");return;}
          try{
            await fetchJSON("/api/v2/objects/"+encodeURIComponent(id)+"/notes",json("POST",{message}));
            await reload();await showCard(id);
          }catch(e){error(el("detail-status"),e.message);}
        };
      }else add.innerHTML='<p class="help">Войдите через MAX, чтобы оставить замечание.</p>';
      clear(el("detail-status"));if(!detail.open)detail.showModal();
      document.dispatchEvent(new CustomEvent("vdktree:card",{detail:o}));
    }catch(e){error(el("toast"),"Ошибка карточки: "+e.message);}
  }
  el("closeDetails").onclick=()=>detail.close();
  window.VdkMap={showCard,refresh:reload};
  roleControls();void reload();
  const timer=setInterval(()=>{if(!editor.open&&!detail.open&&!drawing)void reload();},60000);
  window.addEventListener("beforeunload",()=>clearInterval(timer));
})();
