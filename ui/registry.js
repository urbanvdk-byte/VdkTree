/* VdkTree v1.1.0 — searchable registry, DNS-like multi-facet sidebar and expert editor. */
(()=>{
 "use strict";
 const $=id=>document.getElementById(id);
 const base=String(window.VDK_AUTH_API||"").replace(/\/$/,"");
 const EXPERT=["plot_number","biogroup_number","plant_number","planting_type","life_form","botanical_species","quantity","trunk_diameter_130_cm","height_m","approx_age_years","sanitary_condition_score","dieback_category","defects","care_recommendations","slope_protection","trunk_lean_degrees","crown_asymmetry","endemic_or_relict"];
 const NUMBERS=new Set(["quantity","trunk_diameter_130_cm","height_m","approx_age_years","approx_diameter_cm","trunk_lean_degrees","lat","lon","sanitary_condition_score"]);
 const BOOLS=new Set(["slope_protection","endemic_or_relict","needs_clarification"]);
 const SCALE={1:"Без признаков ослабления",2:"Ослабленное",3:"Сильно ослабленное",4:"Усыхающее",5:"Сухостой текущего года",6:"Сухостой прошлых лет"};
 const LABELS={
  object_type:{tree:"Дерево",shrub:"Кустарник"},
  confirmation_status:{proposed:"Предложено",confirmed:"Произрастает"},
  visible_condition:{unknown:"Не знаю",looks_healthy:"Выглядит здоровым",damaged:"Есть повреждения",dry:"Засохшее"},
  approx_height_band:{unknown:"Не знаю",under_2m:"До 2 м","2_5m":"2–5 м","5_10m":"5–10 м",over_10m:"Больше 10 м"},
  source_type:{citizen:"Житель",moderator:"Модератор",admin:"Администратор",bulk_import:"Массовый импорт"},
  sanitary_condition_score:SCALE,
  slope_protection:{"0":"Нет","1":"Да"},
  endemic_or_relict:{"0":"Нет","1":"Да"},
  needs_clarification:{true:"С замечаниями",false:"Без замечаний"}
 };
 const DEFAULT=["inventory_number","object_type","species_common","botanical_species","confirmation_status","plot_number","plant_number","height_m","trunk_diameter_130_cm","approx_age_years","sanitary_condition_score","observed_on"];
 const AVAILABLE=[...DEFAULT,"biogroup_number","planting_type","life_form","quantity","visible_condition","dieback_category","slope_protection","trunk_lean_degrees","endemic_or_relict","photo_count","lat","lon","created_at","updated_at","id"];
 let meta=[],byKey={},facets={},rows=[],total=0,offset=0,pageSize=50,sort="created_at",direction="desc",currentId=null,sequence=0,timer=null;
 let columns=DEFAULT.slice(),q="";
 const filterValues=Object.create(null),facetElements=Object.create(null);
 const admin=()=>window.VdkAuth?.getUser?.()?.role==="admin";
 function state(key){return filterValues[key]||(filterValues[key]={selected:[],text:"",min:"",max:""});}
 function create(tag,text,cl){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cl)n.className=cl;return n;}
 function button(text,onclick,cl="secondary"){const n=create("button",text,cl);n.type="button";n.onclick=onclick;return n;}
 async function get(path,options){
  if(!base)throw Error("Адрес BotHost не настроен");
  let response;
  try{response=options?await window.VdkAuth.authorizedFetch(path,options):await fetch(base+path,{cache:"no-store"});}
  catch(_){throw Error("Сервер BotHost недоступен");}
  const content=await response.json().catch(()=>({}));
  if(!response.ok)throw Error(typeof content.detail==="string"?content.detail:"Ошибка HTTP "+response.status);
  return content;
 }
 const reqBody=(payload,method="PATCH")=>({method,headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)});
 function pretty(key,value){
  if(value===null||value===undefined||value==="")return "—";
  if(BOOLS.has(key))return ["true","1"].includes(String(value))?"Да":"Нет";
  if(["created_at","updated_at","confirmed_at"].includes(key))return new Date(Number(value)*1000).toLocaleDateString("ru-RU");
  if(key==="sanitary_condition_score")return String(value)+" — "+(SCALE[value]||"");
  return LABELS[key]?.[String(value)]||String(value);
 }
 function params(withPaging=true){
  const p=new URLSearchParams();if(q.trim())p.set("q",q.trim());
  for(const f of meta){
   const v=filterValues[f.key];if(!v)continue;
   if(f.facet)v.selected.forEach(x=>p.append("f_"+f.key,x));
   if(f.kind==="text"&&v.text.trim())p.set("contains_"+f.key,v.text.trim());
   if(f.kind==="number"||f.kind==="date"){
    if(v.min)p.set("min_"+f.key,v.min);
    if(v.max)p.set("max_"+f.key,v.max);
   }
  }
  if(withPaging){p.set("limit",pageSize);p.set("offset",offset);p.set("sort",sort);p.set("direction",direction);}
  return p;
 }
 function later(){clearTimeout(timer);timer=setTimeout(()=>void refresh(true),450);}
 function addChoice(f,list){
  list.replaceChildren();
  const selected=new Set(state(f.key).selected);
  const options=[...(facets[f.key]||[])];
  if(f.key==="object_type")for(const value of ["tree","shrub"])
   if(!options.some(x=>x.value===value))options.push({value,count:0});
  for(const value of selected)if(!options.some(x=>x.value===value))options.push({value,count:0});
  if(!options.length)list.append(create("p","Нет значений","facet-empty"));
  for(const row of options){
   const label=create("label",undefined,"facet-option");
   const input=document.createElement("input");input.type="checkbox";input.checked=selected.has(row.value);
   input.onchange=()=>{
    const arr=state(f.key).selected;
    if(input.checked&&!arr.includes(row.value))arr.push(row.value);
    if(!input.checked)state(f.key).selected=arr.filter(x=>x!==row.value);
    later();
   };
   label.append(input,create("span",row.value==="__empty__"?"Не заполнено":pretty(f.key,row.value)),create("em",String(row.count||0)));
   list.append(label);
  }
 }
 function updateChoices(data){
  facets=data.facets||{};
  for(const f of meta)if(facetElements[f.key])addChoice(f,facetElements[f.key]);
 }
 function createFilters(){
  const groups=new Map();facetElementsClear();
  for(const f of meta){if(!groups.has(f.group))groups.set(f.group,[]);groups.get(f.group).push(f);}
  const host=$("filterGroups");host.replaceChildren();
  for(const [name,fields] of groups){
   const details=document.createElement("details");details.className="filter-group";
   details.open=["Учет","Вид и посадка","Размеры и возраст"].includes(name);
   details.append(create("summary",name));
   const inner=create("div",undefined,"filter-fields");
   for(const f of fields){
    const v=state(f.key),group=create("div",undefined,"filter-field");
    group.append(create("span",f.label,"filter-label"));
    if(f.facet){
     const list=create("div",undefined,"facet-list");
     facetElements[f.key]=list;group.append(list);
    }
    if(f.kind==="text"){
     const label=document.createElement("label"),input=document.createElement("input");
     input.type="search";input.maxLength=150;input.placeholder="Содержит…";input.value=v.text;
     input.setAttribute("aria-label","Фильтр "+f.label);
     input.oninput=()=>{v.text=input.value;later();};
     label.append(input);group.append(label);
    }
    if(f.kind==="number"||f.kind==="date"){
     const range=create("div",undefined,"range-inputs");
     for(const prop of ["min","max"]){
      const input=document.createElement("input");
      input.type=f.kind==="date"?"date":"number";if(input.type==="number")input.step="any";
      input.placeholder=prop==="min"?"От":"До";input.value=v[prop];
      input.setAttribute("aria-label",f.label+" "+input.placeholder);
      input.oninput=()=>{v[prop]=input.value;later();};
      range.append(input);
     }
     group.append(range);
    }
    inner.append(group);
   }
   details.append(inner);host.append(details);
  }
 }
 function facetElementsClear(){for(const k of Object.keys(facetElements))delete facetElements[k];}
 function chooseColumns(){
  const controls=$("columnControls");controls.replaceChildren();
  for(const key of AVAILABLE){
   if(!byKey[key])continue;
   const line=create("label"),input=document.createElement("input");
   input.type="checkbox";input.checked=columns.includes(key);
   input.onchange=()=>{
    if(!input.checked&&columns.length===1){input.checked=true;return;}
    columns=input.checked?[...columns,key]:columns.filter(x=>x!==key);
    columns=[...new Set(columns)];
    try{localStorage.setItem("vdktree-registry-columns-v110",JSON.stringify(columns));}catch(_){}
    renderTable();
   };
   line.append(input,create("span",byKey[key].label));controls.append(line);
  }
 }
 function sorts(){
  const select=$("registrySort");select.replaceChildren();
  for(const key of ["created_at","species_common","botanical_species","inventory_number","object_type","confirmation_status","height_m","trunk_diameter_130_cm","approx_age_years","sanitary_condition_score","observed_on","plot_number","quantity","photo_count","trunk_lean_degrees"]){
   if(!byKey[key]?.sortable)continue;
   const option=document.createElement("option");option.value=key;option.textContent=byKey[key].label;select.append(option);
  }
  select.value=sort;
  select.onchange=()=>{sort=select.value;void refresh(true);};
  $("sortDirection").onclick=()=>{
   direction=direction==="asc"?"desc":"asc";
   $("sortDirection").textContent=direction==="asc"?"↑":"↓";void refresh(true);
  };
 }
 function renderTable(){
  const head=$("tableHead"),body=$("registryRows");head.replaceChildren();body.replaceChildren();
  for(const key of columns){
   const th=create("th");
   if(byKey[key]?.sortable){
    th.append(button(byKey[key].label+(sort===key?(direction==="asc"?" ↑":" ↓"):""),()=>{
     if(sort===key)direction=direction==="asc"?"desc":"asc";else{sort=key;direction="asc";}
     $("registrySort").value=sort;$("sortDirection").textContent=direction==="asc"?"↑":"↓";
     void refresh(true);
    },"column-sort"));
   }else th.textContent=byKey[key]?.label||key;
   head.append(th);
  }
  if(!rows.length){
   const tr=create("tr"),td=create("td","По выбранным фильтрам растений не найдено.");
   td.colSpan=columns.length;tr.append(td);body.append(tr);return;
  }
  for(const record of rows){
   const tr=create("tr");tr.tabIndex=0;tr.setAttribute("role","button");
   tr.setAttribute("aria-label","Карточка "+(record.species_common||record.botanical_species||record.id));
   tr.onclick=()=>void openDetail(record.id);
   tr.onkeydown=e=>{if(e.key==="Enter"||e.key===" "){e.preventDefault();void openDetail(record.id);}};
   for(const key of columns){
    const td=create("td");
    if(key==="confirmation_status")td.append(create("span",pretty(key,record[key]),"status-pill "+(record[key]==="confirmed"?"confirmed":"")));
    else if(key==="object_type")td.append(create("span",pretty(key,record[key]),"type-pill"));
    else if(key==="id")td.textContent=String(record[key]||"").slice(0,12)+"…";
    else td.textContent=key==="sanitary_condition_score"?(record[key]??"—"):pretty(key,record[key]);
    td.title=td.textContent;tr.append(td);
   }
   body.append(tr);
  }
 }
 function chips(){
  const root=$("activeFilters");root.replaceChildren();
  if(q)root.append(button("Поиск: "+q+" ×",()=>{q="";$("registrySearch").value="";void refresh(true);}));
  for(const f of meta){
   const v=filterValues[f.key];if(!v)continue;
   for(const val of v.selected)root.append(button(f.label+": "+pretty(f.key,val)+" ×",()=>{
    v.selected=v.selected.filter(x=>x!==val);void refresh(true);
   }));
   if(f.kind==="text"&&v.text)root.append(button(f.label+": "+v.text+" ×",()=>{
    v.text="";createFilters();updateChoices({facets});void refresh(true);
   }));
   for(const prop of ["min","max"])if(v[prop])root.append(button(f.label+" "+(prop==="min"?"от ":"до ")+v[prop]+" ×",()=>{
    v[prop]="";createFilters();updateChoices({facets});void refresh(true);
   }));
  }
 }
 async function refresh(reset=false){
  if(reset)offset=0;
  const ticket=++sequence;$("resultsSummary").textContent="Применяем фильтры…";
  try{
   const result=await get("/api/v2/registry?"+params().toString());
   if(ticket!==sequence)return;
   rows=result.items||[];total=result.total||0;
   $("totalResults").textContent=total.toLocaleString("ru-RU");
   $("visibleResults").textContent=rows.length;
   $("resultsSummary").textContent="Найдено: "+total.toLocaleString("ru-RU")+" · На странице: "+rows.length;
   $("pageStatus").textContent=total?(offset+1)+"–"+(offset+rows.length)+" из "+total:"Нет записей";
   $("prevPage").disabled=offset===0;$("nextPage").disabled=offset+rows.length>=total;
   renderTable();chips();
   if(reset){
    const choices=await get("/api/v2/registry/facets?"+params(false).toString());
    if(ticket===sequence)updateChoices(choices);
   }
  }catch(e){if(ticket===sequence)$("resultsSummary").textContent="Ошибка: "+e.message;}
 }
 function section(title,keys,obj){
  const section=create("section",undefined,"detail-section");section.append(create("h3",title));
  const grid=create("div",undefined,"detail-grid");
  for(const key of keys){
   const f=byKey[key];if(!f)continue;
   const c=create("div",undefined,"detail-cell");
   c.append(create("span",f.label),create("strong",pretty(key,obj[key])));grid.append(c);
  }
  section.append(grid);return section;
 }
 function formControl(key,value){
  const label=create("label",byKey[key]?.label||key);
  let input;
  if(["defects","care_recommendations","crown_asymmetry","comment"].includes(key)){
   input=document.createElement("textarea");input.rows=3;
  }else if(BOOLS.has(key)){
   input=document.createElement("select");
   for(const [value,text] of [["","Неизвестно"],["true","Да"],["false","Нет"]]){
    const o=document.createElement("option");o.value=value;o.textContent=text;input.append(o);
   }
  }else if(["sanitary_condition_score","visible_condition","approx_height_band"].includes(key)){
   input=document.createElement("select");
   const values=key==="sanitary_condition_score"?Object.entries(SCALE):Object.entries(LABELS[key]||{});
   for(const [value,text] of [["","Не указано"],...values]){
    const o=document.createElement("option");o.value=value;o.textContent=text;input.append(o);
   }
  }else{
   input=document.createElement("input");
   input.type=key==="observed_on"?"date":NUMBERS.has(key)?"number":"text";
   if(input.type==="number")input.step="any";input.maxLength=2000;
  }
  input.name=key;input.value=value===null||value===undefined?"":String(value);
  label.append(input);return label;
 }
 const setMessage=(text,error=false)=>{
  $("detailMessage").textContent=text;$("detailMessage").classList.toggle("error",error);
 };
 function editForm(record,professional){
  const form=create("form",undefined,"detail-edit-form"),title=professional?"Профессиональная карточка":"Основные сведения";
  form.append(create("h3",title));
  const keys=professional?EXPERT:["inventory_number","species_common","observed_on","lat","lon","visible_condition","approx_height_band","approx_diameter_cm","comment"];
  const grid=create("div",undefined,"edit-form-grid");
  for(const key of keys)grid.append(formControl(key,record[key]));
  form.append(grid);
  form.append(create("p",professional?
   "Пустое профессиональное поле очищается. Балл 1–6 не подменяет показатель Х/У/Н таблицы 2.4.":
   "Инвентарный номер изменяется отдельно. Неизвестные числовые поля и дату оставляйте пустыми.","notice"));
  const actions=create("div",undefined,"actions");
  actions.append(button("Сохранить изменения",()=>form.requestSubmit(),"primary"),
                 button("Отмена",()=>form.remove()));
  form.append(actions);
  form.onsubmit=async event=>{
   event.preventDefault();
   const payload={};
   for(const key of keys){
    const raw=String(form.elements[key].value||"").trim();
    if(professional){
     payload[key]=raw===""?null:BOOLS.has(key)?raw==="true":NUMBERS.has(key)?Number(raw):raw;
    }else if(key!=="inventory_number"){
     const old=record[key]===null||record[key]===undefined?"":String(record[key]);
     if(raw!==old){
      if(!raw&&["observed_on","lat","lon","approx_diameter_cm"].includes(key))continue;
      payload[key]=NUMBERS.has(key)?Number(raw):raw;
     }
    }
   }
   try{
    if(professional){
     await get("/api/v2/objects/"+encodeURIComponent(record.id)+"/expert",
               {method:"PATCH",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)});
    }else{
     if(Object.keys(payload).length)await get("/api/v2/objects/"+encodeURIComponent(record.id),
          {method:"PATCH",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)});
     const number=form.elements.inventory_number.value.trim()||null;
     if(number!==(record.inventory_number||null))
      await get("/api/v2/registry/"+encodeURIComponent(record.id)+"/inventory-number",
          {method:"PATCH",headers:{"Content-Type":"application/json"},body:JSON.stringify({inventory_number:number})});
    }
    await openDetail(record.id,false);void refresh(false);
   }catch(e){setMessage("Не сохранено: "+e.message,true);}
  };
  return form;
 }
 async function openDetail(id,first=true){
  currentId=id;const dialog=$("treeDetail"),body=$("detailBody"),actions=$("detailActions");
  if(first&&!dialog.open)dialog.showModal();
  body.textContent="Загружаем профессиональные сведения…";actions.replaceChildren();setMessage("");
  try{
   const {object:d,photos,notes}=await get("/api/v2/registry/"+encodeURIComponent(id));
   if(currentId!==id)return;
   $("detailHeading").textContent=pretty("object_type",d.object_type)+" · "+(d.species_common||d.botanical_species||"Порода не указана");
   body.replaceChildren();
   body.append(section("Общие сведения",["id","inventory_number","species_common","object_type","confirmation_status","created_at","observed_on","lat","lon","visible_condition","approx_height_band","approx_diameter_cm","source_type","comment"],d));
   body.append(section("Подеревный учёт · таблица 2.4",["plot_number","biogroup_number","plant_number","planting_type","life_form","botanical_species","quantity","trunk_diameter_130_cm","height_m","approx_age_years","sanitary_condition_score","dieback_category","defects","care_recommendations"],d));
   body.append(section("Дополнительные факторы Владивостока · пункт 5.4",["slope_protection","trunk_lean_degrees","crown_asymmetry","endemic_or_relict"],d));
   if(photos?.length){
    const pics=section("Фотографии",[],d);
    const holder=create("div",undefined,"photo-previews");
    for(const path of photos){
     if(!/^\/photos\/[0-9a-f]{40}\.(jpg|png|webp)$/.test(path))continue;
     const link=document.createElement("a");link.href=base+path;link.target="_blank";link.rel="noopener noreferrer";
     const img=document.createElement("img");img.src=base+path;img.alt="Фотография насаждения";img.loading="lazy";
     link.append(img);holder.append(link);
    }
    pics.append(holder);body.append(pics);
   }
   if(notes?.length){
    const part=section("Замечания",[],d);
    for(const note of notes.slice(0,30))
     part.append(create("p",pretty("created_at",note.created_at)+" · "+(note.status==="open"?"Открыто":"Закрыто")+" · "+note.message+(note.resolution?" · "+note.resolution:"")));
    body.append(part);
   }
   const download=document.createElement("a");
   download.href=base+"/api/v2/registry/"+encodeURIComponent(id)+"/sheet.xlsx";
   download.download="VdkTree-vedomost.xlsx";download.textContent="↓ Скачать ведомость 2.4 (Excel)";
   actions.append(download,button("Закрыть",()=>dialog.close()));
   if(admin()){
    actions.prepend(button("Редактировать основные",()=>{
     body.querySelector("#editBasic")?.remove();const form=editForm(d,false);form.id="editBasic";
     body.prepend(form);form.scrollIntoView({block:"start",behavior:"smooth"});
    }),button("Редактировать профессиональные",()=>{
     body.querySelector("#editExpert")?.remove();const form=editForm(d,true);form.id="editExpert";
     body.prepend(form);form.scrollIntoView({block:"start",behavior:"smooth"});
    },"primary"));
   }
  }catch(e){setMessage("Ошибка карточки: "+e.message,true);body.replaceChildren();}
 }
 function filterPanel(open){$("filterPanel").classList.toggle("mobile-open",open);$("filterScrim").hidden=!open;}
 async function initialize(){
  try{
   const saved=JSON.parse(localStorage.getItem("vdktree-registry-columns-v110")||"null");
   if(Array.isArray(saved)&&saved.length&&saved.every(x=>AVAILABLE.includes(x)))columns=[...new Set(saved)];
  }catch(_){}
  $("registrySearch").oninput=e=>{q=e.target.value;later();};
  $("applyFilters").onclick=()=>{filterPanel(false);void refresh(true);};
  $("resetFilters").onclick=()=>{
   for(const key of Object.keys(filterValues))delete filterValues[key];
   q="";$("registrySearch").value="";createFilters();updateChoices({facets});void refresh(true);
  };
  $("mobileFilters").onclick=()=>filterPanel(true);
  $("closeFilters").onclick=()=>filterPanel(false);
  $("filterScrim").onclick=()=>filterPanel(false);
  $("prevPage").onclick=()=>{offset=Math.max(0,offset-pageSize);void refresh();};
  $("nextPage").onclick=()=>{if(offset+rows.length<total){offset+=pageSize;void refresh();}};
  $("closeDetail").onclick=()=>{$("treeDetail").close();currentId=null;};
  $("treeDetail").addEventListener("close",()=>{currentId=null;});
  window.addEventListener("vdktree:auth",()=>{if(currentId&&$("treeDetail").open)void openDetail(currentId,false);});
  try{
   const result=await get("/api/v2/registry/meta");
   meta=result.fields||[];byKey=Object.fromEntries(meta.map(f=>[f.key,f]));
   pageSize=Number(result.page_size)||50;
   createFilters();chooseColumns();sorts();await refresh(true);
   const selected=new URLSearchParams(window.location.search).get("id");
   if(selected&&/^[a-f0-9]{32}$/.test(selected))void openDetail(selected);
  }catch(e){$("resultsSummary").textContent="Не удалось загрузить реестр: "+e.message;}
 }
 void initialize();
})();
