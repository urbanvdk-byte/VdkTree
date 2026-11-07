/* VdkTree v1.0.3 — moderator queue, expert forms and administrator CSV/XLSX import. */
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
    '<button type="button" id="openImport" hidden>📥 Импорт Excel/CSV</button>'+ '<button type="button" id="openUsers" hidden>👥 Пользователи</button>';
  document.body.append(tools);

  const usersDialog=document.createElement("dialog");
  usersDialog.id="usersDialog";
  usersDialog.className="management-dialog";
  usersDialog.innerHTML=
    '<h2>👥 Пользователи</h2>'+
    '<p class="help">Только администраторы могут просматривать участников, менять роли, блокировать учётные записи, завершать сеансы и сбрасывать логин/пароль. Изменения записываются в историю.</p>'+
    '<form id="usersFilters" class="users-filters">'+
      '<label>Найти участника<input name="q" maxlength="100" placeholder="Логин, имя или MAX ID"></label>'+
      '<label>Роль<select name="role"><option value="all">Любая</option>'+
        '<option value="user">Пользователь</option><option value="moderator">Модератор</option>'+
        '<option value="admin">Администратор</option></select></label>'+
      '<label>Доступ<select name="status"><option value="all">Любой</option>'+
        '<option value="active">Активные</option><option value="blocked">Заблокированные</option>'+
      '</select></label><button type="submit">Найти</button>'+
    '</form>'+
    '<p id="usersSummary" role="status" class="help"></p>'+
    '<div id="usersRows" aria-live="polite"></div>'+
    '<div class="dialog-actions"><button type="button" id="usersMore" class="secondary">Ещё 30</button>'+
      '<button type="button" id="usersClose" class="secondary">Закрыть</button></div>';
  document.body.append(usersDialog);

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
    '<div class="dialog-actions"><button type="button" id="downloadReport" class="secondary" hidden>Скачать отчёт CSV</button><button type="button" id="importMore" class="secondary" hidden>Ещё строки</button>'+
    '<button type="button" id="commitImport" hidden>Подтвердить импорт</button>'+
    '<button type="button" id="closeImport" class="secondary">Закрыть</button></div>';
  document.body.append(importer);

  function roles() {
    $("openModeration").hidden=!isStaff();
    $("openImport").hidden=!isAdmin();
    $("openUsers").hidden=!isAdmin();
    if(!isStaff() && moderator.open)moderator.close();
    if(!isAdmin() && importer.open)importer.close();
    if(!isAdmin() && usersDialog.open)usersDialog.close();
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
    $("downloadReport").hidden=!activeBatch;
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
  $("downloadReport").onclick=async()=>{
    if(!activeBatch||!isAdmin())return;
    try{
      const response=await window.VdkAuth.authorizedFetch(
        "/api/v2/admin/imports/"+encodeURIComponent(activeBatch)+"/report.csv");
      if(!response.ok)throw Error("Отчёт недоступен");
      const blob=await response.blob();
      const url=URL.createObjectURL(blob);
      const anchor=document.createElement("a");
      anchor.href=url;anchor.download="VdkTree-отчёт-"+activeBatch+".csv";
      document.body.append(anchor);anchor.click();anchor.remove();
      setTimeout(()=>URL.revokeObjectURL(url),1000);
    }catch(e){msg(e.message);}
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
  // User account administration is entirely server-authorized. These controls
  // are only presentation: role checks, audit and last-admin safety live in Python.
  const roleText = {user:"Пользователь",moderator:"Модератор",admin:"Администратор"};
  let usersOffset=0;
  async function loadUsers(reset=true) {
    if (!isAdmin()) return;
    if (reset) {usersOffset=0;$("usersRows").replaceChildren();}
    const fields=$("usersFilters").elements;
    const params=new URLSearchParams({
      q:fields.q.value.trim(),role:fields.role.value,status:fields.status.value,
      limit:"30",offset:String(usersOffset)
    });
    $("usersSummary").textContent="Загружаем участников…";
    try {
      const result=await api("/api/v2/admin/users?"+params.toString());
      $("usersSummary").textContent="Всего зарегистрировано: "+result.counts.total+
        " · Администраторов: "+result.counts.admins+
        " · Модераторов: "+result.counts.moderators+
        " · Заблокированных: "+result.counts.blocked+
        " · По фильтру: "+result.total;
      for(const item of result.users) usersRow(item);
      usersOffset+=result.users.length;
      $("usersMore").hidden=usersOffset>=result.total;
      if(result.total===0)$("usersRows").textContent="Пользователей по фильтру не найдено.";
    }catch(e){$("usersSummary").textContent="Ошибка загрузки: "+e.message;}
  }
  function managementButton(text,fn,neutral=false) {
    const b=document.createElement("button");
    b.type="button";b.textContent=text;b.onclick=fn;
    if(neutral)b.className="secondary";
    return b;
  }
  function usersRow(u) {
    const item=document.createElement("section");
    item.className="management-item user-admin-item";
    const title=document.createElement("div");
    title.className="management-row-title";
    title.textContent=(u.display_name||"Без имени")+" — "+(u.login||"логин не установлен");
    const meta=document.createElement("p");
    meta.className="help";
    meta.textContent="MAX ID: "+u.max_id+" · "+roleText[u.role]+
      (u.is_blocked?" · ⛔ Заблокирован":" · Активен")+
      " · Регистрация: "+dt(u.created_at)+
      " · Последний вход: "+dt(u.last_login_at);
    const stats=document.createElement("p");
    stats.className="help";
    stats.textContent="Растений/объектов: "+u.plants_count+
      " · Замечаний: "+u.notes_count;
    item.append(title,meta,stats);
    const isOwn=u.id===user()?.id;
    const controls=document.createElement("div");
    controls.className="management-buttons";
    controls.append(managementButton("История изменений",async()=>{
      const view=item.querySelector(".user-history");
      if(!view.hidden){view.hidden=true;return;}
      view.hidden=false;view.textContent="Загружаем…";
      try{
        const data=await api("/api/v2/admin/users/"+encodeURIComponent(u.id)+"/history");
        view.replaceChildren();
        if(!data.events.length)view.textContent="Изменений пока нет.";
        for(const ev of data.events){
          const line=document.createElement("p");line.className="history-entry";
          const from=ev.before?.role||"",to=ev.after?.role||"";
          const effect=from&&to?" ["+from+" → "+to+"]":"";
          line.textContent=dt(ev.created_at)+" · "+ev.action+effect+
            " · "+(ev.actor_login||ev.actor_name||"Система")+
            " · "+ev.reason;
          view.append(line);
        }
      }catch(e){view.textContent="Ошибка: "+e.message;}
    },true));
    if(!isOwn) {
      controls.append(managementButton(u.is_blocked?"Разблокировать":"Заблокировать",
        async()=>{
          const verb=u.is_blocked?"разблокировать":"заблокировать";
          if(!confirm("Точно "+verb+" пользователя "+(u.login||u.display_name)+"?"))return;
          const reason=prompt("Причина изменения доступа (не менее 3 символов):");
          if(!reason||reason.trim().length<3)return;
          try{
            await api("/api/v2/admin/users/"+encodeURIComponent(u.id),{
              method:"PATCH",headers:{"Content-Type":"application/json"},
              body:JSON.stringify({is_blocked:!u.is_blocked,reason:reason.trim()})
            });
            await loadUsers();
          }catch(e){alert(e.message);}
        },true));
      controls.append(managementButton("Завершить все сеансы",async()=>{
        if(!confirm("Завершить все активные входы этого пользователя?"))return;
        const reason=prompt("Укажите причину:");
        if(!reason||reason.trim().length<3)return;
        try{
          const result=await api("/api/v2/admin/users/"+encodeURIComponent(u.id)+"/revoke-sessions",
            json({reason:reason.trim()}));
          alert("Завершено сеансов: "+result.revoked);
          await loadUsers();
        }catch(e){alert(e.message);}
      },true));
      controls.append(managementButton("Сбросить логин/пароль",async()=>{
        if(!confirm("Сбросить логин и пароль "+(u.login||u.display_name)+
          "? Следующий вход возможен только через MAX, все сеансы завершатся."))return;
        const reason=prompt("Причина сброса:");
        if(!reason||reason.trim().length<3)return;
        try{
          await api("/api/v2/admin/users/"+encodeURIComponent(u.id)+"/reset-credentials",
            json({reason:reason.trim()}));
          await loadUsers();
        }catch(e){alert(e.message);}
      },true));
    }
    item.append(controls);
    if(!isOwn){
      const roleForm=document.createElement("form");
      roleForm.className="user-role-form";
      roleForm.innerHTML='<label>Назначить роль<select name="role" required>'+
        '<option value="user">Пользователь</option>'+
        '<option value="moderator">Модератор</option>'+
        '<option value="admin">Администратор</option></select></label>'+
        '<label>Причина<input name="reason" maxlength="500" minlength="3" '+
        'placeholder="Например, назначен модератором" required></label>'+
        '<button type="submit">Сохранить роль</button>';
      roleForm.elements.role.value=u.role;
      roleForm.onsubmit=async event=>{
        event.preventDefault();
        const role=roleForm.elements.role.value;
        const reason=roleForm.elements.reason.value.trim();
        if(role===u.role){alert("Выберите другую роль.");return;}
        if(reason.length<3){alert("Укажите причину.");return;}
        if(!confirm("Изменить роль "+(u.login||u.display_name)+" на "+
          roleText[role]+"?"))return;
        const save=roleForm.querySelector('button[type="submit"]');
        save.disabled=true;
        try{
          await api("/api/v2/admin/users/"+encodeURIComponent(u.id),{
            method:"PATCH",headers:{"Content-Type":"application/json"},
            body:JSON.stringify({role,reason})
          });
          await loadUsers();
        }catch(e){alert(e.message);}
        finally{save.disabled=false;}
      };
      item.append(roleForm);
    }else{
      const note=document.createElement("p");
      note.className="help";note.textContent="Это ваша учётная запись. Самостоятельно изменять её роль или блокировать её нельзя.";
      item.append(note);
    }
    const history=document.createElement("div");
    history.className="reviewHistory user-history";history.hidden=true;
    item.append(history);
    $("usersRows").append(item);
  }
  $("openUsers").onclick=()=>{if(!isAdmin())return;usersDialog.showModal();void loadUsers();};
  $("usersClose").onclick=()=>usersDialog.close();
  $("usersFilters").onsubmit=e=>{e.preventDefault();void loadUsers();};
  $("usersMore").onclick=()=>loadUsers(false);
})();
