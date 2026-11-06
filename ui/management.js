/* VdkTree v1.0.0 — moderator queue, expert forms and administrator CSV/XLSX import. */
(() => {
  "use strict";
  const $ = id => document.getElementById(id);
  const user = () => window.VdkAuth?.getUser?.() || null;
  const isStaff = () => ["moderator","admin"].includes(user()?.role);
  const isAdmin = () => user()?.role === "admin";
  const esc = text => String(text ?? "").replace(/[&<>"']/g,
    c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  const dt = seconds => seconds ? new Date(seconds*1000).toLocaleString("ru-RU") : "—";
  const api = async (path, options={}) => {
    if (!window.VdkAuth?.authorizedFetch) throw Error("Вход MAX ещё не настроен");
    let response;
    try { response = await window.VdkAuth.authorizedFetch(path,options); }
    catch (_) { throw Error("BotHost недоступен"); }
    const data = await response.json().catch(()=>({}));
    if(!response.ok) {
      const detail = data.detail;
      throw Error(typeof detail==="string" ? detail : "Ошибка "+response.status);
    }
    return data;
  };
  const json = payload => ({
    method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)
  });

  const tools=document.createElement("div");
  tools.id="staffTools";
  tools.innerHTML=
    '<button type="button" id="openModeration" hidden>🛡️ Модерация</button>'+
    '<button type="button" id="openImport" hidden>📥 Импорт Excel/CSV</button>';
  document.body.append(tools);

  const moderator=document.createElement("dialog");
  moderator.id="moderationDialog";
  moderator.className="management-dialog";
  moderator.innerHTML=
    '<h2>🛡️ Панель модератора</h2>'+
    '<p class="help">Проверяйте предложенные растения и замечания. Подтверждённые записи доступны для просмотра.</p>'+
    '<div class="management-filters">'+
    '<label>Очередь<select id="modFilter">'+
    '<option value="all">Вся очередь</option>'+
    '<option value="pending">Предложенные</option>'+
    '<option value="notes">Открытые замечания</option></select></label>'+
    '<label>Тип<select id="modKind"><option value="all">Все</option><option value="tree">Деревья</option>'+
    '<option value="shrub">Кустарники</option><option value="area">Площади</option></select></label></div>'+
    '<p id="modCounts" class="help" role="status"></p>'+
    '<div id="modRows"></div>'+
    '<div class="dialog-actions"><button type="button" id="modMore" class="secondary">Ещё 30</button>'+
    '<button type="button" id="modClose" class="secondary">Закрыть</button></div>';
  document.body.append(moderator);

  const expert=document.createElement("dialog");
  expert.id="expertDialog";
  expert.className="management-dialog";
  expert.innerHTML='<h2 id="expertHeading">Профессиональная карточка</h2>'+
    '<p class="help">Экспертные измерения отличаются от приблизительных наблюдений жителей.</p>'+
    '<form id="expertForm"><div id="expertFields" class="expert-grid"></div>'+
    '<p id="expertError" role="alert" class="error"></p>'+
    '<div class="dialog-actions"><button type="submit" id="expertSave">Сохранить сведения</button>'+
    '<button type="button" id="expertCancel" class="secondary">Отмена</button></div></form>';
  document.body.append(expert);

  const importer=document.createElement("dialog");
  importer.id="importDialog";
  importer.className="management-dialog";
  importer.innerHTML=
    '<h2>📥 Массовый импорт Excel / CSV</h2>'+
    '<p class="help">Только администратор. Сначала проверка и поиск повторов, затем отдельное подтверждение загрузки. '+
    'Каждое растение получит статус «Предложено».</p>'+
    '<button type="button" id="downloadTemplate" class="secondary">Скачать шаблон CSV</button>'+
    '<form id="importForm"><label>Источник (единое имя ведомости)'+
    '<input name="import_source" minlength="2" maxlength="80" pattern="[0-9A-Za-zА-Яа-яЁё_.\\-]+" '+
    'placeholder="Ведомость_2026" required></label>'+
    '<label>Файл (CSV UTF-8/Windows-1251 или XLSX, до 8 МБ, до 5000 строк)'+
    '<input name="file" type="file" accept=".csv,.xlsx" required></label>'+
    '<button type="submit" id="previewFile">Проверить файл</button></form>'+
    '<div id="importMessage" role="status"></div>'+
    '<div id="importSummary"></div>'+
    '<div id="importRows"></div>'+
    '<div class="dialog-actions"><button type="button" id="importMore" class="secondary" hidden>Ещё строки</button>'+
    '<button type="button" id="commitImport" hidden>Подтвердить импорт</button>'+
    '<button type="button" id="closeImport" class="secondary">Закрыть</button></div>';
  document.body.append(importer);

  function roles() {
    $("openModeration").hidden=!isStaff();
    $("openImport").hidden=!isAdmin();
    if(!isStaff() && moderator.open)moderator.close();
    if(!isAdmin() && importer.open)importer.close();
    if(!isStaff() && expert.open)expert.close();
  }
  window.addEventListener("vdktree:auth",roles);
  roles();

  let queueOffset=0;
  async function loadQueue(reset=true) {
    if(!isStaff())return;
    if(reset){queueOffset=0;$("modRows").replaceChildren();}
    $("modCounts").textContent="Загружаем очередь…";
    const query = "?mode="+encodeURIComponent($("modFilter").value)+
      "&kind="+encodeURIComponent($("modKind").value)+
      "&limit=30&offset="+queueOffset;
    try {
      const data=await api("/api/v2/moderation/queue"+query);
      $("modCounts").textContent="Предложено: "+data.counts.proposed+
        " · Открытых замечаний: "+data.counts.open_notes+
        " · Найдено: "+data.total;
      for(const obj of data.items)renderQueueRow(obj);
      queueOffset+=data.items.length;
      $("modMore").hidden=queueOffset>=data.total;
      if(!data.total)$("modRows").innerHTML='<p class="help">Очередь пуста.</p>';
    }catch(e){$("modCounts").textContent="Ошибка: "+e.message;}
  }
  function renderQueueRow(o) {
    const card=document.createElement("section");
    card.className="management-item";
    card.innerHTML='<div class="management-row-title">'+
      esc(o.species_common||({tree:"Дерево",shrub:"Кустарник"}[o.object_type]||o.object_type))+
      '</div><p class="help">Добавлено: '+esc(dt(o.created_at))+
      ' · '+esc(o.confirmation_status==="proposed"?"Предложено":"Подтверждено")+
      ' · Замечаний: '+Number(o.open_notes||0)+'</p>';
    const controls=document.createElement("div");
    controls.className="management-buttons";
    const button=(text,fn,neutral=false)=>{
      const b=document.createElement("button");b.type="button";b.textContent=text;
      if(neutral)b.className="secondary";b.onclick=fn;controls.append(b);return b;
    };
    button("Карточка",()=>{
      moderator.close();window.VdkMap?.showCard(o.id);
    },true);
    if(o.confirmation_status==="proposed" && ["tree","shrub"].includes(o.object_type)){
      button("✅ Подтвердить",async()=>{
        if(!confirm("Подтвердить это растение?"))return;
        try{await api("/api/v2/moderation/objects/"+encodeURIComponent(o.id)+"/review",
          json({action:"confirm"}));
          await loadQueue();await window.VdkMap?.refresh();}
        catch(e){alert(e.message);}
      });
      button("↩ На уточнение",()=>{
        const area=card.querySelector(".reviewRequest");
        area.hidden=!area.hidden;
        if(!area.hidden)area.querySelector("textarea").focus();
      },true);
      const request=document.createElement("form");
      request.className="reviewRequest";request.hidden=true;
      request.innerHTML='<label>Что необходимо уточнить<textarea name="comment" minlength="3" maxlength="1500" required '+
        'placeholder="Опишите замечание автору"></textarea></label>'+
        '<button type="submit">Отправить на уточнение</button>';
      request.onsubmit=async ev=>{
        ev.preventDefault();
        const comment=ev.target.elements.comment.value.trim();
        if(comment.length<3){alert("Введите не менее 3 символов");return;}
        try{await api("/api/v2/moderation/objects/"+encodeURIComponent(o.id)+"/review",
          json({action:"request_changes",comment}));
          await loadQueue();await window.VdkMap?.refresh();}
        catch(e){alert(e.message);}
      };
      card.append(request);
    }
    button("История решений",async()=>{
      const history=card.querySelector(".reviewHistory");
      if(!history.hidden){history.hidden=true;return;}
      history.textContent="Загружаем историю…";history.hidden=false;
      try{
        const data=await api("/api/v2/moderation/objects/"+encodeURIComponent(o.id)+"/history");
        history.replaceChildren();
        if(!data.events.length)history.textContent="История отсутствует.";
        for(const event of data.events){
          const entry=document.createElement("div");entry.className="history-entry";
          const comment=event.after?.comment||event.after?.message||"";
          entry.textContent=dt(event.created_at)+" · "+event.action+" · "+
            (event.actor_name||"Участник")+(comment?" · "+comment:"");
          history.append(entry);
        }
      }catch(e){history.textContent=e.message;}
    },true);
    card.append(controls);
    const history=document.createElement("div");history.hidden=true;
    history.className="reviewHistory";card.append(history);
    $("modRows").append(card);
  }
  $("openModeration").onclick=()=>{
    if(!isStaff())return;
    moderator.showModal();void loadQueue();
  };
  $("modFilter").onchange=()=>loadQueue();
  $("modKind").onchange=()=>loadQueue();
  $("modMore").onclick=()=>loadQueue(false);
  $("modClose").onclick=()=>moderator.close();

  const expertFields=[
    ["plot_number","№ участка","text"],
    ["biogroup_number","№ биогруппы","text"],
    ["plant_number","№ растения","text"],
    ["planting_type","Тип насаждения","text"],
    ["life_form","Жизненная форма","text"],
    ["botanical_species","Ботанический вид","text"],
    ["quantity","Количество, шт.","integer",1,100000],
    ["trunk_diameter_130_cm","Диаметр на высоте 1,3 м, см","number",0.1,1000],
    ["height_m","Высота, м","number",0.1,100],
    ["approx_age_years","Возраст, лет","integer",0,10000],
    ["sanitary_condition_score","Санитарная оценка (1–6)","score"],
    ["dieback_category","Категория усыхания","text"],
    ["defects","Дефекты","textarea"],
    ["care_recommendations","Рекомендации по уходу","textarea"],
    ["slope_protection","Противоэрозионная функция","boolean"],
    ["trunk_lean_degrees","Наклон ствола, °","number",0,90],
    ["crown_asymmetry","Асимметрия кроны","text"],
    ["endemic_or_relict","Эндемик / реликт","boolean"]
  ];
  const areaFields=[
    ["area_m2","Площадь, м²","number",0.01,100000000],
    ["lawn_type","Тип газона","choice","ordinary:Обыкновенный|meadow:Луговой|parterre:Партерный|slope:На откосе|inert:Инертный"],
    ["area_condition","Состояние","choice","good:Хорошее|satisfactory:Удовлетворительное|poor:Плохое"],
    ["annual_m2","Однолетники, м²","number",0,100000000],
    ["perennial_m2","Многолетники, м²","number",0,100000000],
    ["bulbous_m2","Луковичные, м²","number",0,100000000],
    ["roses_m2","Розы, м²","number",0,100000000],
    ["mixed_m2","Смешанные посадки, м²","number",0,100000000],
    ["community_type","Тип сообщества","choice","forest:Лесное|meadow:Луговое|waterside:Околоводное"]
  ];
  let editExpert=null;
  function fieldControl(def,value) {
    const [name,label,type,a,b]=def;
    const wrap=document.createElement("label");wrap.textContent=label;
    let control;
    if(type==="textarea"){control=document.createElement("textarea");control.rows=2;}
    else if(type==="choice"||type==="score"||type==="boolean"){
      control=document.createElement("select");
      const opts=[["","Не заполнено"]];
      if(type==="boolean")opts.push(["true","Да"],["false","Нет"]);
      if(type==="score")for(let i=1;i<=6;i++)opts.push([String(i),String(i)]);
      if(type==="choice")for(const opt of a.split("|"))opts.push(opt.split(":"));
      for(const [key,text] of opts){const op=document.createElement("option");op.value=key;op.textContent=text;control.append(op);}
    }else{
      control=document.createElement("input");
      control.type=(type==="number"||type==="integer")?"number":"text";
      if(type==="number"||type==="integer"){
        control.step=type==="integer"?"1":"any";
        if(a!==undefined)control.min=String(a);
        if(b!==undefined)control.max=String(b);
      }
      if(type==="text")control.maxLength=type==="text"?2000:1000;
    }
    control.name=name;
    if(value!==null&&value!==undefined){
      if(type==="boolean")control.value=value?"true":"false";
      else control.value=String(value);
    }
    wrap.append(control);
    return wrap;
  }
  function editableByStaff(obj) {
    const u=user();if(!isStaff()||!u)return false;
    if(u.role==="admin")return true;
    if(["lawn","flowerbed","natural_community"].includes(obj.object_type))
      return obj.created_by===u.id;
    return obj.confirmation_status==="proposed";
  }
  function readExpertForm(fields) {
    const data={};
    for(const [name,,type] of fields){
      const input=$("expertForm").elements[name];
      const val=input.value.trim();
      if(!val){data[name]=null;continue;}
      if(type==="boolean")data[name]=val==="true";
      else if(type==="integer"||type==="score"||type==="number")data[name]=Number(val);
      else data[name]=val;
    }
    return data;
  }
  function openExpert(obj,kind,data) {
    editExpert={id:obj.id,kind};
    $("expertHeading").textContent=kind==="point"?"🌳 Профессиональная карточка":"▧ Характеристики территории";
    $("expertFields").replaceChildren();
    for(const def of (kind==="point"?expertFields:areaFields))
      $("expertFields").append(fieldControl(def,data[def[0]]));
    $("expertError").textContent="";
    $("details").close();
    expert.showModal();
  }
  $("expertCancel").onclick=()=>{expert.close();if(editExpert)window.VdkMap?.showCard(editExpert.id);};
  $("expertForm").onsubmit=async event=>{
    event.preventDefault();
    if(!editExpert||!isStaff())return;
    const fields=editExpert.kind==="point"?expertFields:areaFields;
    const data=readExpertForm(fields);
    const endpoint="/api/v2/objects/"+encodeURIComponent(editExpert.id)+
      (editExpert.kind==="point"?"/expert":"/area-details");
    $("expertSave").disabled=true;
    try{
      await api(endpoint,{
        method:"PATCH",headers:{"Content-Type":"application/json"},
        body:JSON.stringify(data)
      });
      expert.close();
      await window.VdkMap?.refresh();
      await window.VdkMap?.showCard(editExpert.id);
    }catch(e){$("expertError").textContent=e.message;}
    finally{$("expertSave").disabled=false;}
  };
  document.addEventListener("vdktree:card",async event=>{
    const obj=event.detail;
    if(!obj||!obj.id)return;
    const slot=document.createElement("section");slot.className="expert-summary";
    slot.innerHTML="<h3>Профессиональные сведения</h3><p class=\"help\">Загружаем…</p>";
    const target=$("card-content");
    const actions=target?.querySelector("#cardActions");
    if(!target||!actions)return;
    target.insertBefore(slot,actions);
    try{
      const result=await api("/api/v2/objects/"+encodeURIComponent(obj.id)+"/expert");
      if(slot.isConnected===false || $("details").open===false)return;
      const values=result.data||{};
      const defs=result.kind==="point"?expertFields:areaFields;
      const items=defs.filter(d=>values[d[0]]!==null&&values[d[0]]!==undefined&&values[d[0]]!=="");
      slot.replaceChildren();
      const h=document.createElement("h3");h.textContent="Профессиональные сведения";slot.append(h);
      if(!items.length){const p=document.createElement("p");p.className="help";
        p.textContent="Пока не заполнены.";slot.append(p);}
      for(const [name,title,type,a] of items){
        const p=document.createElement("p");
        let text=String(values[name]);
        if(type==="boolean")text=values[name]?"Да":"Нет";
        if(type==="score")text=String(values[name])+" / 6";
        if(type==="choice")text=(a.split("|").find(x=>x.split(":")[0]===text)||"").split(":")[1]||text;
        p.textContent=title+": "+text;slot.append(p);
      }
      if(editableByStaff(obj)){
        const b=document.createElement("button");b.type="button";b.className="secondary";
        b.textContent=items.length?"✏️ Изменить экспертные данные":"＋ Заполнить экспертные данные";
        b.onclick=()=>openExpert(obj,result.kind,values);
        slot.append(b);
      }
    }catch(e){slot.textContent="Профессиональные данные недоступны: "+e.message;}
  });

  let activeBatch=null,importOffset=0;
  const msg=s=>{$("importMessage").textContent=s;};
  function paintBatch(data,append=false) {
    activeBatch=data.batch_id;
    if(!append)$("importRows").replaceChildren();
    $("importSummary").textContent="Строк: "+data.total_rows+
      " · Готово: "+data.ready+" · Ошибок: "+data.invalid+
      " · Повторов: "+data.duplicates+" · Импортировано: "+data.imported_rows+
      " · Статус: "+data.state;
    for(const row of data.rows){
      const div=document.createElement("div");div.className="import-line";
      const reason=(row.errors||[]).join("; ");
      div.textContent="Строка "+row.row_number+" · "+row.row_state+
        " · "+(row.species_common||"вид не указан")+
        (row.latitude!==null&&row.latitude!==undefined?
          " ["+row.latitude+", "+row.longitude+"]":"")+
        (reason?" · "+reason:"");
      $("importRows").append(div);
    }
    importOffset=data.offset+data.rows.length;
    $("importMore").hidden=importOffset>=data.total_rows;
    $("commitImport").hidden=data.state!=="validated"||data.ready<1;
  }
  $("openImport").onclick=()=>{
    if(!isAdmin())return;
    importer.showModal();
  };
  $("closeImport").onclick=()=>importer.close();
  $("downloadTemplate").onclick=async()=>{
    try{
      const response=await window.VdkAuth.authorizedFetch("/api/v2/admin/imports/template");
      if(!response.ok)throw Error("Шаблон недоступен");
      const blob=await response.blob();
      const url=URL.createObjectURL(blob);
      const link=document.createElement("a");link.href=url;link.download="VdkTree-import-template.csv";
      document.body.append(link);link.click();link.remove();
      setTimeout(()=>URL.revokeObjectURL(url),1000);
    }catch(e){msg(e.message);}
  };
  $("importForm").onsubmit=async event=>{
    event.preventDefault();if(!isAdmin())return;
    const form=$("importForm"),data=new FormData(form);
    activeBatch=null;importOffset=0;$("importRows").replaceChildren();
    $("commitImport").hidden=true;
    $("previewFile").disabled=true;msg("Проверяем файл…");
    try{
      const result=await api("/api/v2/admin/imports/preview",{method:"POST",body:data});
      paintBatch(result);msg("Файл проверен. Проверьте отчёт и подтвердите импорт.");
    }catch(e){msg("Ошибка проверки: "+e.message);}
    finally{$("previewFile").disabled=false;}
  };
  $("importMore").onclick=async()=>{
    if(!activeBatch||!isAdmin())return;
    try{
      const result=await api("/api/v2/admin/imports/"+encodeURIComponent(activeBatch)+
        "?offset="+importOffset);
      paintBatch(result,true);
    }catch(e){msg(e.message);}
  };
  $("commitImport").onclick=async()=>{
    if(!activeBatch||!isAdmin())return;
    if(!confirm("Импортировать проверенные строки в общую карту? Повторные и ошибочные строки будут пропущены."))return;
    $("commitImport").disabled=true;msg("Сохраняем объекты в PostgreSQL…");
    try{
      const result=await api("/api/v2/admin/imports/"+encodeURIComponent(activeBatch)+"/commit",
        json({}));
      $("commitImport").hidden=true;
      msg("Готово. Добавлено объектов: "+result.imported+". Пропущено: "+result.skipped+".");
      await window.VdkMap?.refresh();
    }catch(e){msg("Импорт не завершён: "+e.message);}
    finally{$("commitImport").disabled=false;}
  };
})();
